"""Multi-exchange portfolio view endpoints.

Thin HTTP adapter: parse query params → call ``PortfolioService`` → map
domain results onto pydantic response models. Business logic lives in
``src.services.portfolio_service``. See ARCH-C1 Phase 2a PR-5.

The in-memory TTL cache stays module-scoped here: it's shared across
requests and we don't want per-request caching semantics in the service.
"""

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.portfolio import (
    ExchangeSummary,
    PortfolioAllocation,
    PortfolioDaily,
    PortfolioPosition,
    PortfolioSummary,
)
from src.auth.dependencies import get_current_user
from src.models.database import User
from src.models.session import get_db
from src.services.portfolio_service import PortfolioService
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

# --- In-memory cache for exchange API responses (positions, allocation) ---
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 10  # seconds


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.monotonic(), value)


async def _get_all_user_clients(
    user_id: int, db: AsyncSession,
) -> list[tuple[str, bool, object]]:
    """Load all exchange connections and create clients.

    Returns a list of ``(exchange_type, demo_mode, client)`` tuples — one
    entry per mode the user has credentials for. See
    ``src.exchanges.factory.get_all_user_clients`` for the construction
    rules, especially around header-based demo for Bitget / BingX.

    Kept on the router module (not inlined into the service) so the
    characterization tests can monkeypatch it — they inject fake exchange
    clients via ``monkeypatch.setattr(portfolio_router, "_get_all_user_clients", ...)``.
    """
    from src.exchanges.factory import get_all_user_clients
    return await get_all_user_clients(user_id, db)


def _build_service(db: AsyncSession, user: User) -> PortfolioService:
    """Construct the service with the router's clients-loader injected.

    Using a lambda so that monkeypatching ``_get_all_user_clients`` on this
    module keeps working — the closure resolves the attribute lazily at
    call time, not at service-construction time.
    """
    async def loader(user_id: int, db_: AsyncSession):
        return await _get_all_user_clients(user_id, db_)

    return PortfolioService(db=db, user=user, clients_loader=loader)


@router.get("/summary", response_model=PortfolioSummary)
@limiter.limit("30/minute")
async def get_portfolio_summary(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    demo_mode: Optional[str] = Query(None, description="all | true | false"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated PnL summary grouped by exchange."""
    service = _build_service(db, user)
    result = await service.get_summary(days=days, demo_mode=demo_mode)

    return PortfolioSummary(
        total_pnl=result.total_pnl,
        total_trades=result.total_trades,
        overall_win_rate=result.overall_win_rate,
        total_fees=result.total_fees,
        total_funding=result.total_funding,
        exchanges=[
            ExchangeSummary(
                exchange=e.exchange,
                total_pnl=e.total_pnl,
                total_trades=e.total_trades,
                winning_trades=e.winning_trades,
                win_rate=e.win_rate,
                total_fees=e.total_fees,
                total_funding=e.total_funding,
            )
            for e in result.exchanges
        ],
    )


@router.get("/positions", response_model=list[PortfolioPosition])
@limiter.limit("20/minute")
async def get_portfolio_positions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch live positions from all connected exchanges."""
    cache_key = f"positions:{user.id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    service = _build_service(db, user)
    items = await service.list_positions()

    positions = [
        PortfolioPosition(
            trade_id=p.trade_id,
            exchange=p.exchange,
            symbol=p.symbol,
            side=p.side,
            size=p.size,
            entry_price=p.entry_price,
            current_price=p.current_price,
            unrealized_pnl=p.unrealized_pnl,
            leverage=p.leverage,
            margin=p.margin,
            bot_name=p.bot_name,
            demo_mode=p.demo_mode,
            take_profit=p.take_profit,
            stop_loss=p.stop_loss,
            trailing_stop_active=p.trailing_stop_active,
            trailing_stop_price=p.trailing_stop_price,
            trailing_stop_distance_pct=p.trailing_stop_distance_pct,
            trailing_atr_override=p.trailing_atr_override,
            native_trailing_stop=p.native_trailing_stop,
            can_close_at_loss=p.can_close_at_loss,
        )
        for p in items
    ]

    _cache_set(cache_key, positions)
    return positions


@router.get("/daily", response_model=list[PortfolioDaily])
@limiter.limit("30/minute")
async def get_portfolio_daily(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    demo_mode: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily PnL breakdown per exchange for stacked charts."""
    service = _build_service(db, user)
    items = await service.get_daily(days=days, demo_mode=demo_mode)

    return [
        PortfolioDaily(
            date=item.date,
            exchange=item.exchange,
            pnl=item.pnl,
            trades=item.trades,
            fees=item.fees,
        )
        for item in items
    ]


@router.get("/allocation", response_model=list[PortfolioAllocation])
@limiter.limit("20/minute")
async def get_portfolio_allocation(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Balance distribution per exchange (for pie/donut chart)."""
    cache_key = f"allocation:{user.id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    service = _build_service(db, user)
    items = await service.get_allocation()

    allocations = [
        PortfolioAllocation(
            exchange=item.exchange,
            balance=item.balance,
            currency=item.currency,
        )
        for item in items
    ]

    _cache_set(cache_key, allocations)
    return allocations
