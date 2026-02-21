"""Multi-exchange portfolio view endpoints."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.portfolio import (
    ExchangeSummary,
    PortfolioAllocation,
    PortfolioDaily,
    PortfolioPosition,
    PortfolioSummary,
)
from src.auth.dependencies import get_current_user
from src.models.database import ExchangeConnection, TradeRecord, User
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(
    days: int = Query(30, ge=1, le=365),
    demo_mode: Optional[str] = Query(None, description="all | true | false"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated PnL summary grouped by exchange."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)

    filters = [
        TradeRecord.user_id == user.id,
        TradeRecord.status == "closed",
        TradeRecord.entry_time >= since,
    ]
    if demo_mode and demo_mode != "all":
        filters.append(TradeRecord.demo_mode == (demo_mode == "true"))

    result = await db.execute(
        select(
            TradeRecord.exchange,
            func.count().label("total_trades"),
            func.sum(case((TradeRecord.pnl > 0, 1), else_=0)).label("winning_trades"),
            func.sum(TradeRecord.pnl).label("total_pnl"),
            func.sum(TradeRecord.fees).label("total_fees"),
            func.sum(TradeRecord.funding_paid).label("total_funding"),
        )
        .where(*filters)
        .group_by(TradeRecord.exchange)
    )
    rows = result.all()

    exchanges = []
    grand_pnl = 0.0
    grand_trades = 0
    grand_wins = 0
    grand_fees = 0.0
    grand_funding = 0.0

    for row in rows:
        total = row.total_trades or 0
        wins = row.winning_trades or 0
        pnl = row.total_pnl or 0
        fees = row.total_fees or 0
        funding = row.total_funding or 0

        exchanges.append(ExchangeSummary(
            exchange=row.exchange,
            total_pnl=pnl,
            total_trades=total,
            winning_trades=wins,
            win_rate=(wins / total * 100) if total > 0 else 0,
            total_fees=fees,
            total_funding=funding,
        ))

        grand_pnl += pnl
        grand_trades += total
        grand_wins += wins
        grand_fees += fees
        grand_funding += funding

    return PortfolioSummary(
        total_pnl=grand_pnl,
        total_trades=grand_trades,
        overall_win_rate=(grand_wins / grand_trades * 100) if grand_trades > 0 else 0,
        total_fees=grand_fees,
        total_funding=grand_funding,
        exchanges=exchanges,
    )


@router.get("/positions", response_model=list[PortfolioPosition])
async def get_portfolio_positions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch live positions from all connected exchanges."""
    clients = await _get_all_user_clients(user.id, db)
    if not clients:
        return []

    positions: list[PortfolioPosition] = []

    async def fetch_positions(exchange_type: str, client):
        try:
            open_positions = await asyncio.wait_for(
                client.get_open_positions(), timeout=10.0
            )
            for pos in open_positions:
                positions.append(PortfolioPosition(
                    exchange=exchange_type,
                    symbol=pos.symbol,
                    side=pos.side,
                    size=pos.size,
                    entry_price=pos.entry_price,
                    current_price=pos.current_price,
                    unrealized_pnl=pos.unrealized_pnl,
                    leverage=pos.leverage,
                    margin=pos.margin,
                ))
        except asyncio.TimeoutError:
            logger.warning(f"Position fetch timeout for {exchange_type}")
        except Exception as e:
            logger.warning(f"Position fetch failed for {exchange_type}: {e}")

    await asyncio.gather(
        *(fetch_positions(ex, cl) for ex, cl in clients.items())
    )

    return positions


@router.get("/daily", response_model=list[PortfolioDaily])
async def get_portfolio_daily(
    days: int = Query(30, ge=1, le=365),
    demo_mode: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily PnL breakdown per exchange for stacked charts."""
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=days)

    filters = [
        TradeRecord.user_id == user.id,
        TradeRecord.status == "closed",
        TradeRecord.entry_time >= since,
    ]
    if demo_mode and demo_mode != "all":
        filters.append(TradeRecord.demo_mode == (demo_mode == "true"))

    result = await db.execute(
        select(
            func.date(TradeRecord.entry_time).label("date"),
            TradeRecord.exchange,
            func.sum(TradeRecord.pnl).label("pnl"),
            func.count().label("trades"),
            func.sum(TradeRecord.fees).label("fees"),
        )
        .where(*filters)
        .group_by(func.date(TradeRecord.entry_time), TradeRecord.exchange)
        .order_by(func.date(TradeRecord.entry_time))
    )

    return [
        PortfolioDaily(
            date=str(row.date),
            exchange=row.exchange,
            pnl=row.pnl or 0,
            trades=row.trades,
            fees=row.fees or 0,
        )
        for row in result.all()
    ]


@router.get("/allocation", response_model=list[PortfolioAllocation])
async def get_portfolio_allocation(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Balance distribution per exchange (for pie/donut chart)."""
    clients = await _get_all_user_clients(user.id, db)
    if not clients:
        return []

    allocations: list[PortfolioAllocation] = []

    async def fetch_balance(exchange_type: str, client):
        try:
            balance = await asyncio.wait_for(
                client.get_account_balance(), timeout=10.0
            )
            allocations.append(PortfolioAllocation(
                exchange=exchange_type,
                balance=balance.total,
                currency=balance.currency,
            ))
        except asyncio.TimeoutError:
            logger.warning(f"Balance fetch timeout for {exchange_type}")
        except Exception as e:
            logger.warning(f"Balance fetch failed for {exchange_type}: {e}")

    await asyncio.gather(
        *(fetch_balance(ex, cl) for ex, cl in clients.items())
    )

    return allocations


async def _get_all_user_clients(user_id: int, db: AsyncSession) -> dict:
    """Load all exchange connections and create clients."""
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

    result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
    )
    connections = result.scalars().all()

    clients = {}
    for conn in connections:
        try:
            # Prefer live keys, fall back to demo
            api_key_enc = conn.api_key_encrypted or conn.demo_api_key_encrypted
            api_secret_enc = conn.api_secret_encrypted or conn.demo_api_secret_encrypted
            passphrase_enc = conn.passphrase_encrypted or conn.demo_passphrase_encrypted

            if not api_key_enc or not api_secret_enc:
                continue

            api_key = decrypt_value(api_key_enc)
            api_secret = decrypt_value(api_secret_enc)
            passphrase = decrypt_value(passphrase_enc) if passphrase_enc else ""

            demo_mode = not conn.api_key_encrypted  # demo if no live keys

            client = create_exchange_client(
                exchange_type=conn.exchange_type,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=passphrase,
                demo_mode=demo_mode,
            )
            clients[conn.exchange_type] = client
        except Exception as e:
            logger.warning(f"Failed to create client for {conn.exchange_type}: {e}")

    return clients
