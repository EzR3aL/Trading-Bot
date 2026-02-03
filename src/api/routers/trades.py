"""Trade history endpoints (user-scoped)."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.trade import TradeListResponse, TradeResponse
from src.auth.dependencies import get_current_user
from src.models.database import TradeRecord, User
from src.models.session import get_db

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=TradeListResponse)
async def list_trades(
    status: Optional[str] = Query(None, pattern="^(open|closed|cancelled)$"),
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List trades for the current user with filters."""
    query = select(TradeRecord).where(TradeRecord.user_id == user.id)

    if status:
        query = query.where(TradeRecord.status == status)
    if symbol:
        query = query.where(TradeRecord.symbol == symbol)
    if exchange:
        query = query.where(TradeRecord.exchange == exchange)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(TradeRecord.entry_time.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    trades = result.scalars().all()

    return TradeListResponse(
        trades=[
            TradeResponse(
                id=t.id,
                symbol=t.symbol,
                side=t.side,
                size=t.size,
                entry_price=t.entry_price,
                exit_price=t.exit_price,
                take_profit=t.take_profit,
                stop_loss=t.stop_loss,
                leverage=t.leverage,
                confidence=t.confidence,
                reason=t.reason,
                status=t.status,
                pnl=t.pnl,
                pnl_percent=t.pnl_percent,
                fees=t.fees or 0,
                funding_paid=t.funding_paid or 0,
                entry_time=t.entry_time.isoformat() if t.entry_time else "",
                exit_time=t.exit_time.isoformat() if t.exit_time else None,
                exit_reason=t.exit_reason,
                exchange=t.exchange,
            )
            for t in trades
        ],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific trade."""
    result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.id == trade_id, TradeRecord.user_id == user.id
        )
    )
    trade = result.scalar_one_or_none()
    if not trade:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trade not found")

    return TradeResponse(
        id=trade.id,
        symbol=trade.symbol,
        side=trade.side,
        size=trade.size,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        take_profit=trade.take_profit,
        stop_loss=trade.stop_loss,
        leverage=trade.leverage,
        confidence=trade.confidence,
        reason=trade.reason,
        status=trade.status,
        pnl=trade.pnl,
        pnl_percent=trade.pnl_percent,
        fees=trade.fees or 0,
        funding_paid=trade.funding_paid or 0,
        entry_time=trade.entry_time.isoformat() if trade.entry_time else "",
        exit_time=trade.exit_time.isoformat() if trade.exit_time else None,
        exit_reason=trade.exit_reason,
        exchange=trade.exchange,
    )
