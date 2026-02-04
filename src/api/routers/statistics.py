"""Statistics and performance endpoints (user-scoped)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.models.database import TradeRecord, User
from src.models.session import get_db

router = APIRouter(prefix="/api/statistics", tags=["statistics"])


@router.get("")
async def get_statistics(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get trading statistics for the current user over N days."""
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.count().label("total_trades"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("winning_trades"),
            func.sum(case((TradeRecord.pnl <= 0, 1), else_=0)).label("losing_trades"),
            func.sum(TradeRecord.pnl).label("total_pnl"),
            func.sum(TradeRecord.fees).label("total_fees"),
            func.sum(TradeRecord.funding_paid).label("total_funding"),
            func.avg(TradeRecord.pnl_percent).label("avg_pnl_percent"),
            func.max(TradeRecord.pnl).label("best_trade"),
            func.min(TradeRecord.pnl).label("worst_trade"),
        )
        .where(
            TradeRecord.user_id == user.id,
            TradeRecord.status == "closed",
            TradeRecord.entry_time >= since,
        )
    )
    row = result.one()

    total = row.total_trades or 0
    winning = row.winning_trades or 0
    total_pnl = row.total_pnl or 0
    total_fees = row.total_fees or 0
    total_funding = row.total_funding or 0

    return {
        "period_days": days,
        "total_trades": total,
        "winning_trades": winning,
        "losing_trades": row.losing_trades or 0,
        "win_rate": (winning / total * 100) if total > 0 else 0,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "total_funding": total_funding,
        "net_pnl": total_pnl - total_fees - abs(total_funding),
        "avg_pnl_percent": row.avg_pnl_percent or 0,
        "best_trade": row.best_trade or 0,
        "worst_trade": row.worst_trade or 0,
    }


@router.get("/daily")
async def get_daily_stats(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get daily trading statistics."""
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.date(TradeRecord.entry_time).label("date"),
            func.count().label("trades"),
            func.sum(TradeRecord.pnl).label("pnl"),
            func.sum(TradeRecord.fees).label("fees"),
            func.sum(TradeRecord.funding_paid).label("funding"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("wins"),
            func.sum(case((TradeRecord.pnl <= 0, 1), else_=0)).label("losses"),
        )
        .where(
            TradeRecord.user_id == user.id,
            TradeRecord.status == "closed",
            TradeRecord.entry_time >= since,
        )
        .group_by(func.date(TradeRecord.entry_time))
        .order_by(func.date(TradeRecord.entry_time))
    )

    return {
        "days": [
            {
                "date": str(row.date),
                "trades": row.trades,
                "pnl": row.pnl or 0,
                "fees": row.fees or 0,
                "funding": row.funding or 0,
                "wins": row.wins or 0,
                "losses": row.losses or 0,
            }
            for row in result.all()
        ]
    }
