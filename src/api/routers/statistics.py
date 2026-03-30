"""Statistics and performance endpoints (user-scoped)."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.auth.dependencies import get_current_user
from src.models.database import TradeRecord, User
from src.models.session import get_db

# Fallback to entry_time when exit_time is NULL (defensive against data issues)
_closed_date = func.coalesce(TradeRecord.exit_time, TradeRecord.entry_time)

router = APIRouter(prefix="/api/statistics", tags=["statistics"])


@router.get("")
@limiter.limit("30/minute")
async def get_statistics(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get trading statistics for the current user over N days."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)

    filters = [
        TradeRecord.user_id == user.id,
        TradeRecord.status == "closed",
        _closed_date >= since,
    ]
    if demo_mode is not None:
        filters.append(TradeRecord.demo_mode == demo_mode)

    result = await db.execute(
        select(
            func.count().label("total_trades"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("winning_trades"),
            func.sum(case((TradeRecord.pnl <= 0, 1), else_=0)).label("losing_trades"),
            func.sum(TradeRecord.pnl).label("total_pnl"),
            func.sum(TradeRecord.fees).label("total_fees"),
            func.sum(TradeRecord.funding_paid).label("total_funding"),
            func.sum(TradeRecord.builder_fee).label("total_builder_fees"),
            func.avg(TradeRecord.pnl_percent).label("avg_pnl_percent"),
            func.max(TradeRecord.pnl).label("best_trade"),
            func.min(TradeRecord.pnl).label("worst_trade"),
        )
        .where(*filters)
    )
    row = result.one()

    total = row.total_trades or 0
    winning = row.winning_trades or 0
    total_pnl = row.total_pnl or 0
    total_fees = row.total_fees or 0
    total_funding = row.total_funding or 0
    total_builder_fees = row.total_builder_fees or 0

    return {
        "period_days": days,
        "total_trades": total,
        "winning_trades": winning,
        "losing_trades": row.losing_trades or 0,
        "win_rate": (winning / total * 100) if total > 0 else 0,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "total_funding": total_funding,
        "total_builder_fees": total_builder_fees,
        "net_pnl": total_pnl - total_fees - abs(total_funding),
        "avg_pnl_percent": row.avg_pnl_percent or 0,
        "best_trade": row.best_trade or 0,
        "worst_trade": row.worst_trade or 0,
    }


@router.get("/daily")
@limiter.limit("30/minute")
async def get_daily_stats(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get daily trading statistics."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)

    filters = [
        TradeRecord.user_id == user.id,
        TradeRecord.status == "closed",
        _closed_date >= since,
    ]
    if demo_mode is not None:
        filters.append(TradeRecord.demo_mode == demo_mode)

    result = await db.execute(
        select(
            func.date(_closed_date).label("date"),
            func.count().label("trades"),
            func.sum(TradeRecord.pnl).label("pnl"),
            func.sum(TradeRecord.fees).label("fees"),
            func.sum(TradeRecord.funding_paid).label("funding"),
            func.sum(TradeRecord.builder_fee).label("builder_fees"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.sum(case((TradeRecord.pnl <= 0, 1), else_=0)).label("losses"),
        )
        .where(*filters)
        .group_by(func.date(_closed_date))
        .order_by(func.date(_closed_date))
    )

    return {
        "days": [
            {
                "date": str(row.date),
                "trades": row.trades,
                "pnl": row.pnl or 0,
                "fees": row.fees or 0,
                "funding": row.funding or 0,
                "builder_fees": row.builder_fees or 0,
                "wins": row.wins or 0,
                "losses": row.losses or 0,
            }
            for row in result.all()
        ]
    }


@router.get("/revenue")
@limiter.limit("30/minute")
async def get_revenue_analytics(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get Hyperliquid revenue analytics (builder fees earned)."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)

    filters = [
        TradeRecord.user_id == user.id,
        TradeRecord.status == "closed",
        _closed_date >= since,
        TradeRecord.exchange == "hyperliquid",
    ]
    if demo_mode is not None:
        filters.append(TradeRecord.demo_mode == demo_mode)

    result = await db.execute(
        select(
            func.count().label("total_trades"),
            func.sum(TradeRecord.builder_fee).label("total_builder_fees"),
            func.sum(TradeRecord.fees).label("total_exchange_fees"),
            func.sum(TradeRecord.pnl).label("total_pnl"),
        )
        .where(*filters)
    )
    row = result.one()

    total_trades = row.total_trades or 0
    total_builder_fees = row.total_builder_fees or 0

    daily_avg = total_builder_fees / days if days > 0 and total_trades > 0 else 0
    monthly_estimate = daily_avg * 30

    daily_result = await db.execute(
        select(
            func.date(_closed_date).label("date"),
            func.count().label("trades"),
            func.sum(TradeRecord.builder_fee).label("builder_fees"),
            func.sum(TradeRecord.fees).label("exchange_fees"),
            func.sum(TradeRecord.pnl).label("pnl"),
        )
        .where(*filters)
        .group_by(func.date(_closed_date))
        .order_by(func.date(_closed_date))
    )

    return {
        "period_days": days,
        "total_trades": total_trades,
        "total_builder_fees": total_builder_fees,
        "total_exchange_fees": row.total_exchange_fees or 0,
        "monthly_estimate": monthly_estimate,
        "daily": [
            {
                "date": str(r.date),
                "trades": r.trades,
                "builder_fees": r.builder_fees or 0,
                "exchange_fees": r.exchange_fees or 0,
                "pnl": r.pnl or 0,
            }
            for r in daily_result.all()
        ],
    }
