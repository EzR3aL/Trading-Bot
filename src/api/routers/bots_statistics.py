"""Bot statistics endpoints: per-bot stats and cross-bot comparison."""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.auth.dependencies import get_current_user
from src.errors import ERR_BOT_NOT_FOUND
from src.models.database import BotConfig, TradeRecord, User
from src.models.session import get_db
from src.api.routers.trades import _compute_trailing_stop
from src.utils.logger import get_logger

logger = get_logger(__name__)

_closed_date = func.coalesce(TradeRecord.exit_time, TradeRecord.entry_time)

statistics_router = APIRouter(tags=["bots"])


@statistics_router.get("/{bot_id}/statistics")
@limiter.limit("30/minute")
async def get_bot_statistics(
    request: Request,
    bot_id: int,
    days: int = Query(default=30, ge=1, le=365),
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed statistics for a specific bot including daily PnL series."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Daily PnL series (cumulative)
    daily_filters = [
        TradeRecord.bot_config_id == bot_id,
        TradeRecord.status == "closed",
        _closed_date >= since,
    ]
    if demo_mode is not None:
        daily_filters.append(TradeRecord.demo_mode == demo_mode)

    daily_result = await db.execute(
        select(
            func.date(_closed_date).label("date"),
            func.sum(TradeRecord.pnl).label("pnl"),
            func.count(TradeRecord.id).label("trades"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.coalesce(func.sum(TradeRecord.fees), 0).label("fees"),
            func.coalesce(func.sum(TradeRecord.funding_paid), 0).label("funding"),
        ).where(
            *daily_filters
        ).group_by(
            func.date(_closed_date)
        ).order_by(
            func.date(_closed_date)
        )
    )
    daily_rows = daily_result.all()

    cumulative = 0.0
    daily_series = []
    for row in daily_rows:
        cumulative += float(row.pnl or 0)
        daily_series.append({
            "date": str(row.date) if row.date else None,
            "pnl": round(float(row.pnl or 0), 2),
            "cumulative_pnl": round(cumulative, 2),
            "trades": row.trades,
            "wins": int(row.wins or 0),
            "fees": round(float(row.fees or 0), 4),
            "funding": round(float(row.funding or 0), 4),
        })

    # Overall stats
    overall_filters = [
        TradeRecord.bot_config_id == bot_id,
        TradeRecord.status == "closed",
    ]
    if demo_mode is not None:
        overall_filters.append(TradeRecord.demo_mode == demo_mode)

    overall_result = await db.execute(
        select(
            func.count(TradeRecord.id).label("total"),
            func.coalesce(func.sum(TradeRecord.pnl), 0).label("total_pnl"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.sum(case((TradeRecord.pnl <= 0, 1), else_=0)).label("losses"),
            func.coalesce(func.sum(TradeRecord.fees), 0).label("total_fees"),
            func.coalesce(func.sum(TradeRecord.funding_paid), 0).label("total_funding"),
            func.avg(TradeRecord.pnl).label("avg_pnl"),
            func.max(TradeRecord.pnl).label("best_trade"),
            func.min(TradeRecord.pnl).label("worst_trade"),
        ).where(*overall_filters)
    )
    stats = overall_result.one()

    total = stats.total or 0
    wins = int(stats.wins or 0)
    win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

    # Recent trades
    recent_filters = [TradeRecord.bot_config_id == bot_id]
    if demo_mode is not None:
        recent_filters.append(TradeRecord.demo_mode == demo_mode)

    recent_result = await db.execute(
        select(TradeRecord).where(
            *recent_filters
        ).order_by(TradeRecord.entry_time.desc()).limit(20)
    )
    recent_trades = []
    for trade in recent_result.scalars().all():
        row = {
            "id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "size": trade.size,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "pnl": round(float(trade.pnl or 0), 2),
            "pnl_percent": round(float(trade.pnl_percent or 0), 2),
            "confidence": trade.confidence,
            "leverage": trade.leverage,
            "reason": trade.reason,
            "status": trade.status,
            "demo_mode": trade.demo_mode,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_reason": trade.exit_reason,
            "fees": round(float(trade.fees or 0), 4),
            "funding_paid": round(float(trade.funding_paid or 0), 4),
        }
        if trade.status == "open":
            ts = await _compute_trailing_stop(
                trade, config.strategy_type, config.strategy_params,
            )
            row.update(ts)
        recent_trades.append(row)

    return {
        "bot_id": bot_id,
        "bot_name": config.name,
        "strategy_type": config.strategy_type,
        "exchange_type": config.exchange_type,
        "mode": config.mode,
        "days": days,
        "summary": {
            "total_trades": total,
            "wins": wins,
            "losses": int(stats.losses or 0),
            "win_rate": win_rate,
            "total_pnl": round(float(stats.total_pnl or 0), 2),
            "total_fees": round(float(stats.total_fees or 0), 2),
            "total_funding": round(float(stats.total_funding or 0), 2),
            "avg_pnl": round(float(stats.avg_pnl or 0), 2),
            "best_trade": round(float(stats.best_trade or 0), 2),
            "worst_trade": round(float(stats.worst_trade or 0), 2),
        },
        "daily_series": daily_series,
        "recent_trades": recent_trades,
    }


@statistics_router.get("/compare/performance")
@limiter.limit("30/minute")
async def compare_bots_performance(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get comparative performance data for all bots (for multi-line chart)."""
    bot_query = select(BotConfig).where(BotConfig.user_id == user.id)
    if demo_mode is True:
        bot_query = bot_query.where(BotConfig.mode.in_(["demo", "both"]))
    elif demo_mode is False:
        bot_query = bot_query.where(BotConfig.mode.in_(["live", "both"]))
    bot_query = bot_query.order_by(BotConfig.created_at)

    configs_result = await db.execute(bot_query)
    configs = configs_result.scalars().all()

    since = datetime.now(timezone.utc) - timedelta(days=days)
    bot_ids = [c.id for c in configs]
    if not bot_ids:
        return {"days": days, "bots": []}

    # ── Batch 1: Daily PnL per bot (single query) ────────────────────
    daily_filters = [
        TradeRecord.bot_config_id.in_(bot_ids),
        TradeRecord.status == "closed",
        _closed_date >= since,
    ]
    if demo_mode is not None:
        daily_filters.append(TradeRecord.demo_mode == demo_mode)

    daily_result = await db.execute(
        select(
            TradeRecord.bot_config_id,
            func.date(_closed_date).label("date"),
            func.sum(TradeRecord.pnl).label("pnl"),
        ).where(*daily_filters).group_by(
            TradeRecord.bot_config_id, func.date(_closed_date)
        ).order_by(
            TradeRecord.bot_config_id, func.date(_closed_date)
        )
    )
    # Build per-bot daily series
    daily_by_bot: dict[int, list] = {bid: [] for bid in bot_ids}
    for row in daily_result.all():
        daily_by_bot[row.bot_config_id].append({
            "date": str(row.date) if row.date else None,
            "pnl": float(row.pnl or 0),
        })

    # ── Batch 2: Overall stats per bot (single query) ────────────────
    stats_filters = [
        TradeRecord.bot_config_id.in_(bot_ids),
        TradeRecord.status == "closed",
    ]
    if demo_mode is not None:
        stats_filters.append(TradeRecord.demo_mode == demo_mode)

    stats_result = await db.execute(
        select(
            TradeRecord.bot_config_id,
            func.count(TradeRecord.id).label("total"),
            func.coalesce(func.sum(TradeRecord.pnl), 0).label("pnl"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.coalesce(func.sum(TradeRecord.fees), 0).label("total_fees"),
            func.coalesce(func.sum(TradeRecord.funding_paid), 0).label("total_funding"),
        ).where(*stats_filters).group_by(TradeRecord.bot_config_id)
    )
    stats_by_bot: dict[int, Any] = {}
    for row in stats_result.all():
        stats_by_bot[row.bot_config_id] = row

    # ── Batch 3: Last trade per bot (subquery + join) ────────────────
    last_trade_filters = [TradeRecord.bot_config_id.in_(bot_ids)]
    if demo_mode is not None:
        last_trade_filters.append(TradeRecord.demo_mode == demo_mode)

    max_id_subq = (
        select(func.max(TradeRecord.id).label("max_id"))
        .where(*last_trade_filters)
        .group_by(TradeRecord.bot_config_id)
        .subquery()
    )
    last_trades_result = await db.execute(
        select(TradeRecord).where(TradeRecord.id.in_(select(max_id_subq.c.max_id)))
    )
    last_trade_by_bot: dict[int, TradeRecord] = {}
    for trade in last_trades_result.scalars().all():
        last_trade_by_bot[trade.bot_config_id] = trade

    # ── Assemble response ────────────────────────────────────────────
    bots_data = []
    for config in configs:
        # Build cumulative series from daily data
        cumulative = 0.0
        series = []
        for day in daily_by_bot.get(config.id, []):
            cumulative += day["pnl"]
            series.append({
                "date": day["date"],
                "cumulative_pnl": round(cumulative, 2),
            })

        stats = stats_by_bot.get(config.id)
        total = int(stats.total) if stats else 0
        wins = int(stats.wins or 0) if stats else 0
        pnl = float(stats.pnl or 0) if stats else 0.0
        total_fees = float(stats.total_fees or 0) if stats else 0.0
        total_funding = float(stats.total_funding or 0) if stats else 0.0

        last_trade = last_trade_by_bot.get(config.id)

        bots_data.append({
            "bot_id": config.id,
            "name": config.name,
            "strategy_type": config.strategy_type,
            "exchange_type": config.exchange_type,
            "mode": config.mode,
            "total_trades": total,
            "total_pnl": round(pnl, 2),
            "total_fees": round(total_fees, 2),
            "total_funding": round(total_funding, 2),
            "win_rate": round((wins / total) * 100, 1) if total > 0 else 0.0,
            "wins": wins,
            "last_direction": last_trade.side.upper() if last_trade and last_trade.side else None,
            "last_confidence": last_trade.confidence if last_trade else None,
            "series": series,
        })

    return {"days": days, "bots": bots_data}
