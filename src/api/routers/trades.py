"""Trade history endpoints (user-scoped).

Thin FastAPI router: every handler parses query/body input, delegates to
:class:`TradesService`, and projects the domain result onto the pydantic
response model via helpers in ``_trades_mappers``. All business logic —
including the trailing-stop helper ``_compute_trailing_stop`` and the
``TRAILING_STOP_STRATEGIES`` constant — lives in
:mod:`src.services.trades_service`.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from src.api.dependencies.risk_state import (
    get_idempotency_cache,
    get_risk_state_manager,
)
from src.api.rate_limit import limiter
from src.api.routers._trades_mappers import (
    EXCHANGE_ERROR_HINTS,
    MUTEX_CONFLICT_REASONS,
    intent_from_body,
    invalid_intent_detail,
    leg_to_status,
    trade_response,
)
from src.api.schemas.trade import (
    TpSlResponse,
    TradeFilterBotOption,
    TradeFilterOptionsResponse,
    TradeListResponse,
    TradeResponse,
    UpdateTpSlRequest,
)
from src.auth.dependencies import get_current_user
from src.data.market_data import MarketDataFetcher
from src.errors import (
    ERR_TPSL_EXCHANGE_NOT_SUPPORTED,
    ERR_TPSL_UPDATE_FAILED,
    ERR_TRADE_NOT_FOUND,
    translate_exchange_error,
)
from src.exchanges.factory import create_exchange_client
from src.models.database import User
from src.models.session import get_db
from src.notifications import discord_notifier as _discord_notifier_module
from src.services.exceptions import (
    ExchangeConnectionMissing,
    InvalidTpSlIntent,
    TpSlExchangeNotSupported,
    TpSlUpdateFailed,
    TradeNotFound,
    TradeNotOpen,
)
from src.services.trades_service import Pagination, TradeFilters, TradesService
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/trades", tags=["trades"])


# ---------------------------------------------------------------------------
# Read handlers
# ---------------------------------------------------------------------------


@router.get("", response_model=TradeListResponse)
@limiter.limit("60/minute")
async def list_trades(
    request: Request,
    status: Optional[str] = Query(None, pattern="^(open|closed|cancelled)$"),
    symbol: Optional[str] = None,
    exchange: Optional[str] = None,
    bot_name: Optional[str] = None,
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    demo_mode: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List trades for the current user with filters."""
    filters = TradeFilters(
        status=status,
        symbol=symbol,
        exchange=exchange,
        bot_name=bot_name,
        date_from=date_from,
        date_to=date_to,
        demo_mode=demo_mode,
    )
    pagination = Pagination(page=page, per_page=per_page)

    service = TradesService(db=db, user=user)
    result = await service.list_trades(filters, pagination)

    return TradeListResponse(
        trades=[trade_response(item) for item in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
    )


@router.get("/filter-options", response_model=TradeFilterOptionsResponse)
@limiter.limit("30/minute")
async def get_trade_filter_options(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return distinct filter values available for the user's trades."""
    service = TradesService(db=db, user=user)
    result = await service.get_filter_options()

    return TradeFilterOptionsResponse(
        symbols=result.symbols,
        bots=[TradeFilterBotOption(id=b.id, name=b.name) for b in result.bots],
        exchanges=result.exchanges,
        statuses=result.statuses,
    )


@router.post("/sync")
@limiter.limit("5/minute")
async def sync_trades(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync open trades with the exchange.

    External dependencies are forwarded from this module so the Phase-0
    characterization-test patches (which patch the router's symbols)
    keep working.
    """
    service = TradesService(db=db, user=user)
    # Resolve DiscordNotifier dynamically so the characterization tests
    # (which patch ``src.notifications.discord_notifier.DiscordNotifier``
    # at call time) can override the real class with a mock.
    discord_notifier_cls = _discord_notifier_module.DiscordNotifier
    result = await service.sync_exchange_positions(
        rsm_enabled=settings.risk.risk_state_manager_enabled,
        decrypt_value=decrypt_value,
        create_exchange_client=create_exchange_client,
        get_risk_state_manager=get_risk_state_manager,
        discord_notifier_cls=discord_notifier_cls,
    )
    return {
        "synced": result.synced,
        "closed_trades": [
            {
                "id": ct.id,
                "symbol": ct.symbol,
                "side": ct.side,
                "exit_price": ct.exit_price,
                "pnl": ct.pnl,
                "exit_reason": ct.exit_reason,
            }
            for ct in result.closed_trades
        ],
    }


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific trade.

    A missing trade and another user's trade are deliberately
    indistinguishable (both raise :class:`TradeNotFound` → 404).
    """
    service = TradesService(db=db, user=user)
    try:
        detail = await service.get_trade(trade_id)
    except TradeNotFound:
        raise HTTPException(status_code=404, detail=ERR_TRADE_NOT_FOUND)

    return trade_response(detail)


@router.get("/{trade_id}/risk-state", response_model=TpSlResponse)
@limiter.limit("60/minute")
async def get_trade_risk_state(
    trade_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current post-readback risk-state snapshot for a trade.

    The response shape matches ``PUT /trades/{trade_id}/tp-sl`` so the
    frontend ``useRiskState`` hook and ``useUpdateTpSl`` mutation share one
    TypeScript type. Only active while ``risk_state_manager_enabled`` is on;
    the legacy path has no concept of a per-leg snapshot and returns 404.
    """
    if not settings.risk.risk_state_manager_enabled:
        raise HTTPException(
            status_code=404,
            detail="Risk-state endpoint is disabled (feature flag off)",
        )

    service = TradesService(db=db, user=user)
    manager = get_risk_state_manager()
    try:
        result = await service.get_risk_state_snapshot(trade_id, manager)
    except TradeNotFound as exc:
        # ``TradeNotFound`` carries either the trade id (ownership miss)
        # or the ``reconcile`` error message (row vanished). The pre-extract
        # handler surfaced the error message verbatim when available, and
        # the generic ``Trade not found`` string otherwise — preserve that.
        detail = str(exc) if str(exc) and not str(exc).isdigit() else ERR_TRADE_NOT_FOUND
        raise HTTPException(status_code=404, detail=detail) from exc

    return TpSlResponse(
        trade_id=result.trade_id,
        tp=leg_to_status(result.tp),
        sl=leg_to_status(result.sl),
        trailing=leg_to_status(result.trailing),
        applied_at=result.applied_at,
        overall_status=result.overall_status,
    )


# ---------------------------------------------------------------------------
# TP/SL write handler
# ---------------------------------------------------------------------------


@router.put("/{trade_id}/tp-sl")
@limiter.limit("10/minute")
async def update_trade_tpsl(
    trade_id: int,
    body: UpdateTpSlRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Update TP/SL on an open position — sets on exchange + updates DB.

    Branches on ``risk_state_manager_enabled`` and delegates to the
    appropriate :class:`TradesService` method. Domain errors are mapped
    to the same HTTP statuses the pre-extract handler produced (verified
    by the Phase-0 characterization tests).
    """
    intent = intent_from_body(body)
    service = TradesService(db=db, user=user)

    if settings.risk.risk_state_manager_enabled:
        # ── Manager path ───────────────────────────────────────────
        try:
            result = await service.update_tp_sl_via_manager(
                trade_id,
                intent,
                idempotency_key=idempotency_key,
                get_risk_state_manager=get_risk_state_manager,
                get_idempotency_cache=get_idempotency_cache,
                market_data_fetcher_cls=MarketDataFetcher,
            )
        except TradeNotFound:
            raise HTTPException(status_code=404, detail=ERR_TRADE_NOT_FOUND)
        except TradeNotOpen:
            raise HTTPException(status_code=400, detail="Trade is not open")
        except InvalidTpSlIntent as exc:
            reason = str(exc)
            status_code = 422 if reason in MUTEX_CONFLICT_REASONS else 400
            raise HTTPException(
                status_code=status_code,
                detail=invalid_intent_detail(reason),
            )

        return TpSlResponse(
            trade_id=result.trade_id,
            tp=leg_to_status(result.tp),
            sl=leg_to_status(result.sl),
            trailing=leg_to_status(result.trailing),
            applied_at=result.applied_at,
            overall_status=result.overall_status,
        )

    # ── Legacy path (flag off) ─────────────────────────────────────
    try:
        result = await service.update_tp_sl_legacy(
            trade_id,
            intent,
            decrypt_value=decrypt_value,
            create_exchange_client=create_exchange_client,
            market_data_fetcher_cls=MarketDataFetcher,
        )
    except TradeNotFound:
        raise HTTPException(status_code=404, detail=ERR_TRADE_NOT_FOUND)
    except TradeNotOpen:
        raise HTTPException(status_code=400, detail="Trade is not open")
    except InvalidTpSlIntent as exc:
        raise HTTPException(status_code=400, detail=invalid_intent_detail(str(exc)))
    except ExchangeConnectionMissing as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TpSlExchangeNotSupported as exc:
        raise HTTPException(
            status_code=400,
            detail=ERR_TPSL_EXCHANGE_NOT_SUPPORTED.format(exchange=exc.exchange),
        )
    except TpSlUpdateFailed as exc:
        # Surface exchange validation errors as 400 (user can fix), not 502.
        raw = exc.raw_error
        if any(hint in raw.lower() for hint in EXCHANGE_ERROR_HINTS):
            raise HTTPException(status_code=400, detail=translate_exchange_error(raw))
        raise HTTPException(status_code=502, detail=ERR_TPSL_UPDATE_FAILED)

    return {
        "status": "ok",
        "take_profit": result.take_profit,
        "stop_loss": result.stop_loss,
        "trailing_stop_placed": result.trailing_stop_placed,
        "trailing_stop_software": result.trailing_stop_software,
    }
