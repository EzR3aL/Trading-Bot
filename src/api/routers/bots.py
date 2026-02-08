"""
Multibot management endpoints.

CRUD for bot configs + lifecycle (start/stop/restart).
Replaces the old bot_control router for the new multibot system.
"""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, cast, Date, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.bots import (
    BotConfigCreate,
    BotConfigResponse,
    BotConfigUpdate,
    BotListResponse,
    BotRuntimeStatus,
    StrategiesListResponse,
    StrategyInfo,
)
from src.auth.dependencies import get_current_user
from src.models.database import BotConfig, TradeRecord, User
from src.models.session import get_db
from src.strategy.base import StrategyRegistry
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/bots", tags=["bots"])

# Orchestrator will be injected at app startup
_orchestrator = None

MAX_BOTS_PER_USER = 10


def set_orchestrator(orchestrator):
    """Set the orchestrator instance (called during app initialization)."""
    global _orchestrator
    _orchestrator = orchestrator


def _get_orchestrator():
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Bot orchestrator not initialized")
    return _orchestrator


def _config_to_response(config: BotConfig) -> BotConfigResponse:
    """Convert a BotConfig ORM object to a response schema."""
    return BotConfigResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        strategy_type=config.strategy_type,
        exchange_type=config.exchange_type,
        mode=config.mode,
        trading_pairs=json.loads(config.trading_pairs) if config.trading_pairs else [],
        leverage=config.leverage,
        position_size_percent=config.position_size_percent,
        max_trades_per_day=config.max_trades_per_day,
        take_profit_percent=config.take_profit_percent,
        stop_loss_percent=config.stop_loss_percent,
        daily_loss_limit_percent=config.daily_loss_limit_percent,
        strategy_params=json.loads(config.strategy_params) if config.strategy_params else None,
        schedule_type=config.schedule_type,
        schedule_config=json.loads(config.schedule_config) if config.schedule_config else None,
        is_enabled=config.is_enabled,
        created_at=config.created_at.isoformat() if config.created_at else None,
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


# ─── Strategies ───────────────────────────────────────────────

@router.get("/strategies", response_model=StrategiesListResponse)
async def list_strategies(user: User = Depends(get_current_user)):
    """List all available trading strategies with their parameter schemas."""
    # Ensure strategies are registered
    from src.strategy.liquidation_hunter import LiquidationHunterStrategy  # noqa: F401

    strategies = StrategyRegistry.list_available()
    return StrategiesListResponse(
        strategies=[StrategyInfo(**s) for s in strategies]
    )


# ─── CRUD ─────────────────────────────────────────────────────

@router.post("", response_model=BotConfigResponse)
async def create_bot(
    body: BotConfigCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new bot configuration."""
    # Validate strategy exists
    try:
        StrategyRegistry.get(body.strategy_type)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check bot limit
    count_result = await db.execute(
        select(func.count(BotConfig.id)).where(BotConfig.user_id == user.id)
    )
    if count_result.scalar() >= MAX_BOTS_PER_USER:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_BOTS_PER_USER} bots per user")

    config = BotConfig(
        user_id=user.id,
        name=body.name,
        description=body.description,
        strategy_type=body.strategy_type,
        exchange_type=body.exchange_type,
        mode=body.mode,
        trading_pairs=json.dumps(body.trading_pairs),
        leverage=body.leverage,
        position_size_percent=body.position_size_percent,
        max_trades_per_day=body.max_trades_per_day,
        take_profit_percent=body.take_profit_percent,
        stop_loss_percent=body.stop_loss_percent,
        daily_loss_limit_percent=body.daily_loss_limit_percent,
        strategy_params=json.dumps(body.strategy_params) if body.strategy_params else None,
        schedule_type=body.schedule_type,
        schedule_config=json.dumps(body.schedule_config) if body.schedule_config else None,
        is_enabled=False,
    )
    db.add(config)
    await db.flush()
    await db.refresh(config)

    logger.info(f"Bot created: {config.name} (id={config.id}) by user {user.id}")
    return _config_to_response(config)


@router.get("", response_model=BotListResponse)
async def list_bots(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all bots for the current user with runtime status."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.user_id == user.id).order_by(BotConfig.created_at.desc())
    )
    configs = result.scalars().all()

    orchestrator = _get_orchestrator()
    bots = []

    for config in configs:
        # Get runtime status from orchestrator
        runtime = orchestrator.get_bot_status(config.id)
        trading_pairs = json.loads(config.trading_pairs) if config.trading_pairs else []

        # Get trade stats from DB
        stats_result = await db.execute(
            select(
                func.count(TradeRecord.id),
                func.coalesce(func.sum(TradeRecord.pnl), 0),
            ).where(
                TradeRecord.bot_config_id == config.id,
            )
        )
        total_trades, total_pnl = stats_result.one()

        open_result = await db.execute(
            select(func.count(TradeRecord.id)).where(
                TradeRecord.bot_config_id == config.id,
                TradeRecord.status == "open",
            )
        )
        open_trades = open_result.scalar()

        # LLM-specific metrics
        llm_data = {}
        if config.strategy_type == "llm_signal":
            # Get last trade for latest signal info
            last_trade_result = await db.execute(
                select(TradeRecord)
                .where(TradeRecord.bot_config_id == config.id)
                .order_by(TradeRecord.entry_time.desc())
                .limit(1)
            )
            last_trade = last_trade_result.scalar_one_or_none()

            if last_trade:
                llm_data["llm_last_direction"] = last_trade.side.upper() if last_trade.side else None
                llm_data["llm_last_confidence"] = last_trade.confidence
                if last_trade.metrics_snapshot:
                    try:
                        metrics = json.loads(last_trade.metrics_snapshot)
                        llm_data["llm_last_reasoning"] = metrics.get("llm_reasoning", "")[:200]
                        llm_data["llm_provider"] = metrics.get("llm_provider")
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Accuracy = winning / total closed trades
            closed_result = await db.execute(
                select(
                    func.count(TradeRecord.id),
                    func.sum(
                        case(
                            (TradeRecord.pnl > 0, 1),
                            else_=0,
                        )
                    ),
                ).where(
                    TradeRecord.bot_config_id == config.id,
                    TradeRecord.status == "closed",
                )
            )
            closed_total, winners = closed_result.one()
            if closed_total and closed_total > 0:
                llm_data["llm_accuracy"] = round(
                    (float(winners or 0) / closed_total) * 100, 1
                )
            llm_data["llm_total_predictions"] = total_trades

            # Aggregate token usage from metrics_snapshot
            try:
                snapshots_result = await db.execute(
                    select(TradeRecord.metrics_snapshot).where(
                        TradeRecord.bot_config_id == config.id,
                        TradeRecord.metrics_snapshot.isnot(None),
                    )
                )
                total_tokens = 0
                token_count = 0
                for (snapshot_json,) in snapshots_result:
                    try:
                        snapshot = json.loads(snapshot_json)
                        tokens = snapshot.get("llm_tokens_used", 0)
                        if tokens and tokens > 0:
                            total_tokens += tokens
                            token_count += 1
                    except (json.JSONDecodeError, TypeError):
                        pass
                if token_count > 0:
                    llm_data["llm_total_tokens_used"] = total_tokens
                    llm_data["llm_avg_tokens_per_call"] = round(
                        total_tokens / token_count, 1
                    )
            except Exception:
                pass  # Non-critical — don't break bot listing

            # Get provider from strategy_params
            if not llm_data.get("llm_provider") and config.strategy_params:
                try:
                    sp = json.loads(config.strategy_params)
                    llm_data["llm_provider"] = sp.get("llm_provider")
                except (json.JSONDecodeError, TypeError):
                    pass

        bots.append(BotRuntimeStatus(
            bot_config_id=config.id,
            name=config.name,
            strategy_type=config.strategy_type,
            exchange_type=config.exchange_type,
            mode=config.mode,
            trading_pairs=trading_pairs,
            status=runtime["status"] if runtime else ("idle" if not config.is_enabled else "stopped"),
            error_message=runtime.get("error_message") if runtime else None,
            started_at=runtime.get("started_at") if runtime else None,
            last_analysis=runtime.get("last_analysis") if runtime else None,
            trades_today=runtime.get("trades_today", 0) if runtime else 0,
            is_enabled=config.is_enabled,
            total_trades=total_trades,
            total_pnl=round(float(total_pnl), 2),
            open_trades=open_trades,
            **llm_data,
        ))

    return BotListResponse(bots=bots)


@router.get("/{bot_id}", response_model=BotConfigResponse)
async def get_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific bot configuration."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")
    return _config_to_response(config)


@router.put("/{bot_id}", response_model=BotConfigResponse)
async def update_bot(
    bot_id: int,
    body: BotConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a bot configuration. Bot must be stopped to update."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Check if running
    orchestrator = _get_orchestrator()
    if orchestrator.is_running(bot_id):
        raise HTTPException(status_code=400, detail="Stop the bot before editing its configuration")

    # Validate strategy if changed
    if body.strategy_type:
        try:
            StrategyRegistry.get(body.strategy_type)
        except KeyError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Apply updates
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "trading_pairs" and value is not None:
            setattr(config, field, json.dumps(value))
        elif field == "strategy_params" and value is not None:
            setattr(config, field, json.dumps(value))
        elif field == "schedule_config" and value is not None:
            setattr(config, field, json.dumps(value))
        elif value is not None:
            setattr(config, field, value)

    await db.flush()
    await db.refresh(config)

    logger.info(f"Bot updated: {config.name} (id={bot_id})")
    return _config_to_response(config)


@router.delete("/{bot_id}")
async def delete_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a bot configuration. Bot must be stopped first."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Stop if running
    orchestrator = _get_orchestrator()
    if orchestrator.is_running(bot_id):
        await orchestrator.stop_bot(bot_id)

    await db.delete(config)
    logger.info(f"Bot deleted: {config.name} (id={bot_id})")
    return {"status": "ok", "message": f"Bot '{config.name}' deleted"}


# ─── Lifecycle ────────────────────────────────────────────────

@router.post("/{bot_id}/start")
async def start_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a bot."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    orchestrator = _get_orchestrator()

    try:
        await orchestrator.start_bot(bot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Mark as enabled
    config.is_enabled = True
    await db.flush()

    return {"status": "ok", "message": f"Bot '{config.name}' started"}


@router.post("/{bot_id}/stop")
async def stop_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop a running bot."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    orchestrator = _get_orchestrator()
    success = await orchestrator.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail="Bot is not running")

    # Mark as disabled
    config.is_enabled = False
    await db.flush()

    return {"status": "ok", "message": f"Bot '{config.name}' stopped"}


@router.post("/{bot_id}/restart")
async def restart_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Restart a bot (stop + start)."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    orchestrator = _get_orchestrator()

    try:
        await orchestrator.restart_bot(bot_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    config.is_enabled = True
    await db.flush()

    return {"status": "ok", "message": f"Bot '{config.name}' restarted"}


@router.post("/stop-all")
async def stop_all_bots(user: User = Depends(get_current_user)):
    """Stop all running bots for the current user."""
    orchestrator = _get_orchestrator()
    stopped = await orchestrator.stop_all_for_user(user.id)
    return {"status": "ok", "message": f"{stopped} bot(s) stopped"}


# ─── Per-Bot Statistics ──────────────────────────────────────

@router.get("/{bot_id}/statistics")
async def get_bot_statistics(
    bot_id: int,
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed statistics for a specific bot including daily PnL series."""
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")

    since = datetime.utcnow() - timedelta(days=days)

    # Daily PnL series (cumulative)
    daily_result = await db.execute(
        select(
            cast(TradeRecord.exit_time, Date).label("date"),
            func.sum(TradeRecord.pnl).label("pnl"),
            func.count(TradeRecord.id).label("trades"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
        ).where(
            TradeRecord.bot_config_id == bot_id,
            TradeRecord.status == "closed",
            TradeRecord.exit_time >= since,
        ).group_by(
            cast(TradeRecord.exit_time, Date)
        ).order_by(
            cast(TradeRecord.exit_time, Date)
        )
    )
    daily_rows = daily_result.all()

    cumulative = 0.0
    daily_series = []
    for row in daily_rows:
        cumulative += float(row.pnl or 0)
        daily_series.append({
            "date": row.date.isoformat() if row.date else None,
            "pnl": round(float(row.pnl or 0), 2),
            "cumulative_pnl": round(cumulative, 2),
            "trades": row.trades,
            "wins": int(row.wins or 0),
        })

    # Overall stats
    overall_result = await db.execute(
        select(
            func.count(TradeRecord.id).label("total"),
            func.coalesce(func.sum(TradeRecord.pnl), 0).label("total_pnl"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.sum(case((TradeRecord.pnl <= 0, 1), else_=0)).label("losses"),
            func.coalesce(func.sum(TradeRecord.fees), 0).label("total_fees"),
            func.avg(TradeRecord.pnl).label("avg_pnl"),
            func.max(TradeRecord.pnl).label("best_trade"),
            func.min(TradeRecord.pnl).label("worst_trade"),
        ).where(
            TradeRecord.bot_config_id == bot_id,
            TradeRecord.status == "closed",
        )
    )
    stats = overall_result.one()

    total = stats.total or 0
    wins = int(stats.wins or 0)
    win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

    # Recent trades
    recent_result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.bot_config_id == bot_id,
        ).order_by(TradeRecord.entry_time.desc()).limit(20)
    )
    recent_trades = []
    for trade in recent_result.scalars().all():
        recent_trades.append({
            "id": trade.id,
            "symbol": trade.symbol,
            "side": trade.side,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "pnl": round(float(trade.pnl or 0), 2),
            "pnl_percent": round(float(trade.pnl_percent or 0), 2),
            "confidence": trade.confidence,
            "status": trade.status,
            "demo_mode": trade.demo_mode,
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else None,
            "exit_reason": trade.exit_reason,
        })

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
            "avg_pnl": round(float(stats.avg_pnl or 0), 2),
            "best_trade": round(float(stats.best_trade or 0), 2),
            "worst_trade": round(float(stats.worst_trade or 0), 2),
        },
        "daily_series": daily_series,
        "recent_trades": recent_trades,
    }


@router.get("/compare/performance")
async def compare_bots_performance(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get comparative performance data for all bots (for multi-line chart)."""
    configs_result = await db.execute(
        select(BotConfig).where(BotConfig.user_id == user.id).order_by(BotConfig.created_at)
    )
    configs = configs_result.scalars().all()

    since = datetime.utcnow() - timedelta(days=days)
    bots_data = []

    for config in configs:
        daily_result = await db.execute(
            select(
                cast(TradeRecord.exit_time, Date).label("date"),
                func.sum(TradeRecord.pnl).label("pnl"),
            ).where(
                TradeRecord.bot_config_id == config.id,
                TradeRecord.status == "closed",
                TradeRecord.exit_time >= since,
            ).group_by(
                cast(TradeRecord.exit_time, Date)
            ).order_by(
                cast(TradeRecord.exit_time, Date)
            )
        )

        cumulative = 0.0
        series = []
        for row in daily_result.all():
            cumulative += float(row.pnl or 0)
            series.append({
                "date": row.date.isoformat() if row.date else None,
                "cumulative_pnl": round(cumulative, 2),
            })

        # Overall stats for the summary table
        stats_result = await db.execute(
            select(
                func.count(TradeRecord.id).label("total"),
                func.coalesce(func.sum(TradeRecord.pnl), 0).label("pnl"),
                func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            ).where(
                TradeRecord.bot_config_id == config.id,
                TradeRecord.status == "closed",
            )
        )
        stats = stats_result.one()
        total = stats.total or 0
        wins = int(stats.wins or 0)

        # Last trade for direction/confidence
        last_result = await db.execute(
            select(TradeRecord).where(
                TradeRecord.bot_config_id == config.id,
            ).order_by(TradeRecord.entry_time.desc()).limit(1)
        )
        last_trade = last_result.scalar_one_or_none()

        bots_data.append({
            "bot_id": config.id,
            "name": config.name,
            "strategy_type": config.strategy_type,
            "exchange_type": config.exchange_type,
            "mode": config.mode,
            "total_trades": total,
            "total_pnl": round(float(stats.pnl or 0), 2),
            "win_rate": round((wins / total) * 100, 1) if total > 0 else 0.0,
            "wins": wins,
            "last_direction": last_trade.side.upper() if last_trade and last_trade.side else None,
            "last_confidence": last_trade.confidence if last_trade else None,
            "series": series,
        })

    return {"days": days, "bots": bots_data}
