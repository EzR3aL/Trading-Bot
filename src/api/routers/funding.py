"""Funding payment endpoints (user-scoped)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_user
from src.models.database import FundingPayment, User
from src.models.session import get_db

router = APIRouter(prefix="/api/funding", tags=["funding"])


@router.get("")
async def list_funding_payments(
    days: int = Query(30, ge=1, le=365),
    symbol: str = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List funding payments for the current user."""
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(days=days)

    query = (
        select(FundingPayment)
        .where(FundingPayment.user_id == user.id, FundingPayment.timestamp >= since)
    )
    if symbol:
        query = query.where(FundingPayment.symbol == symbol)

    query = query.order_by(FundingPayment.timestamp.desc()).limit(500)
    result = await db.execute(query)
    payments = result.scalars().all()

    return {
        "payments": [
            {
                "id": p.id,
                "symbol": p.symbol,
                "funding_rate": p.funding_rate,
                "position_size": p.position_size,
                "payment_amount": p.payment_amount,
                "side": p.side,
                "timestamp": p.timestamp.isoformat(),
            }
            for p in payments
        ],
        "total_count": len(payments),
    }


@router.get("/summary")
async def funding_summary(
    days: int = Query(30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get funding payment summary."""
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.count().label("total_payments"),
            func.sum(FundingPayment.payment_amount).label("total_amount"),
            func.sum(
                case(
                    (FundingPayment.payment_amount > 0, FundingPayment.payment_amount),
                    else_=0,
                )
            ).label("total_received"),
            func.sum(
                case(
                    (FundingPayment.payment_amount < 0, FundingPayment.payment_amount),
                    else_=0,
                )
            ).label("total_paid"),
        )
        .where(FundingPayment.user_id == user.id, FundingPayment.timestamp >= since)
    )
    row = result.one()

    return {
        "period_days": days,
        "total_payments": row.total_payments or 0,
        "total_amount": row.total_amount or 0,
        "total_received": row.total_received or 0,
        "total_paid": row.total_paid or 0,
        "net": (row.total_received or 0) + (row.total_paid or 0),
    }
