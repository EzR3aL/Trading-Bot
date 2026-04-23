"""
Multibot management endpoints.

CRUD for bot configs, strategies, data sources.
Lifecycle (start/stop) and statistics live in sub-modules
(bots_lifecycle, bots_statistics) and are included via sub-routers.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.schemas.bots import (
    BotBudgetListResponse,
    BotConfigCreate,
    BotConfigResponse,
    BotConfigUpdate,
    BotListResponse,
    ExchangeBalanceOverview,
    ExchangeBalancePreview,
    StrategiesListResponse,
    StrategyInfo,
    SymbolConflictResponse,
)
from src.auth.dependencies import get_current_user
from src.errors import (
    ERR_BOT_NOT_FOUND,
    ERR_MAX_BOTS_REACHED,
    ERR_ORCHESTRATOR_NOT_INITIALIZED,
    ERR_STOP_BOT_BEFORE_EDIT,
    ERR_STRATEGY_NOT_FOUND,
    ERR_SYMBOL_CONFLICT,
)
from src.models.database import BotConfig, User
from src.models.session import get_db
from src.services import bots_service
from src.services.exceptions import (
    BotIsRunning,
    BotNotFound,
    InvalidSymbols,
    MaxBotsReached,
    StrategyNotFound,
)
from src.api.rate_limit import limiter
from src.models.enums import EXCHANGE_PATTERN
from src.utils.json_helpers import parse_json_field
from src.constants import MAX_BOTS_PER_USER

router = APIRouter(prefix="/api/bots", tags=["bots"])


def get_orchestrator(request: Request):
    """FastAPI dependency: retrieve orchestrator from app.state."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail=ERR_ORCHESTRATOR_NOT_INITIALIZED)
    return orchestrator


def _config_to_response(config: BotConfig) -> BotConfigResponse:
    """Convert a BotConfig ORM object to a response schema."""
    ctx = f"bot {config.id}"
    trading_pairs = parse_json_field(config.trading_pairs, field_name="trading_pairs", context=ctx, default=[])
    strategy_params = parse_json_field(config.strategy_params, field_name="strategy_params", context=ctx)
    schedule_config = parse_json_field(config.schedule_config, field_name="schedule_config", context=ctx)
    per_asset_config = parse_json_field(config.per_asset_config, field_name="per_asset_config", context=ctx)
    pnl_alert_settings = parse_json_field(config.pnl_alert_settings, field_name="pnl_alert_settings", context=ctx)

    return BotConfigResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        strategy_type=config.strategy_type,
        exchange_type=config.exchange_type,
        mode=config.mode,
        margin_mode=getattr(config, "margin_mode", None) or "cross",
        trading_pairs=trading_pairs,
        leverage=config.leverage,
        position_size_percent=config.position_size_percent,
        max_trades_per_day=config.max_trades_per_day,
        take_profit_percent=config.take_profit_percent,
        stop_loss_percent=config.stop_loss_percent,
        daily_loss_limit_percent=config.daily_loss_limit_percent,
        per_asset_config=per_asset_config,
        strategy_params=strategy_params,
        schedule_type=config.schedule_type,
        schedule_config=schedule_config,
        is_enabled=config.is_enabled,
        discord_webhook_configured=bool(config.discord_webhook_url),
        telegram_configured=bool(config.telegram_bot_token and config.telegram_chat_id),
        pnl_alert_settings=pnl_alert_settings,
        created_at=config.created_at.isoformat() if config.created_at else None,
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


async def _raise_if_symbol_conflict(
    db: AsyncSession,
    user_id: int,
    exchange_type: str,
    mode: str,
    trading_pairs: list[str],
    exclude_bot_id: int | None = None,
    strategy_type: str | None = None,
) -> None:
    """Raise 409 CONFLICT when the user already runs a bot on the same
    exchange/mode/symbol combination.

    Thin wrapper around ``bots_service._check_symbol_conflicts`` — kept in
    the router because the HTTP error envelope (stable ``SYMBOL_ALREADY_IN_USE``
    code, localized message) is a transport concern, not a service concern.
    """
    conflicts = await bots_service._check_symbol_conflicts(
        db,
        user_id,
        exchange_type,
        mode,
        trading_pairs,
        exclude_bot_id=exclude_bot_id,
        strategy_type=strategy_type,
    )
    if not conflicts:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "SYMBOL_ALREADY_IN_USE",
            "message": ERR_SYMBOL_CONFLICT.format(
                symbols=", ".join(sorted({c.symbol for c in conflicts}))
            ),
            "conflicts": [c.model_dump() for c in conflicts],
        },
    )



# ─── Strategies ───────────────────────────────────────────────

@router.get("/strategies", response_model=StrategiesListResponse)
async def list_strategies(user: User = Depends(get_current_user)):
    """List all available trading strategies with their parameter schemas."""
    strategies = bots_service.list_strategies()
    return StrategiesListResponse(
        strategies=[StrategyInfo(**s) for s in strategies]
    )


@router.get("/data-sources")
async def list_data_sources(user: User = Depends(get_current_user)):
    """Return the catalog of all available market data sources.

    Returns {sources: [...], defaults: [...]} where each source has
    id, name, description, category, provider, free, default fields.
    Used by the Bot Builder to render selectable data source cards.
    """
    return bots_service.list_data_sources()


# ─── Balance Preview (for BotBuilder) ────────────────────────

@router.get("/balance-preview", response_model=ExchangeBalancePreview)
@limiter.limit("15/minute")
async def get_balance_preview(
    request: Request,
    exchange_type: str = Query(..., pattern=EXCHANGE_PATTERN),
    mode: str = Query(..., pattern="^(demo|live|both)$"),
    exclude_bot_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Balance preview for the BotBuilder — shows equity, allocated %, and remaining."""
    return await bots_service.balance_preview(db, user.id, exchange_type, mode, exclude_bot_id)


@router.get("/balance-overview", response_model=ExchangeBalanceOverview)
@limiter.limit("10/minute")
async def get_balance_overview(
    request: Request,
    exclude_bot_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Balance overview across ALL connected exchanges (demo + live)."""
    return await bots_service.balance_overview(db, user.id, exclude_bot_id)


# ─── Symbol Conflict Check ────────────────────────────────────

@router.get("/symbol-conflicts", response_model=SymbolConflictResponse)
@limiter.limit("30/minute")
async def check_symbol_conflicts(
    request: Request,
    exchange_type: str = Query(..., pattern=EXCHANGE_PATTERN),
    mode: str = Query(..., pattern="^(demo|live|both)$"),
    trading_pairs: str = Query(..., description="Comma-separated list of trading pairs"),
    exclude_bot_id: Optional[int] = Query(None),
    strategy_type: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if trading pairs conflict with existing enabled bots."""
    pairs = [p.strip() for p in trading_pairs.split(",") if p.strip()]
    return await bots_service.symbol_conflicts(
        db, user.id, exchange_type, mode, pairs, exclude_bot_id, strategy_type,
    )


# ─── CRUD ─────────────────────────────────────────────────────

@router.post("", response_model=BotConfigResponse)
@limiter.limit("10/minute")
async def create_bot(
    request: Request,
    body: BotConfigCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new bot configuration."""
    # Block if another enabled bot of this user already trades one of the
    # requested symbols on the same exchange/mode. Defense-in-depth — the
    # frontend also probes ``GET /symbol-conflicts`` before save.
    await _raise_if_symbol_conflict(
        db,
        user_id=user.id,
        exchange_type=body.exchange_type,
        mode=body.mode,
        trading_pairs=body.trading_pairs,
        strategy_type=body.strategy_type,
    )

    try:
        config = await bots_service.create_bot(db, user.id, body)
    except StrategyNotFound as e:
        raise HTTPException(status_code=400, detail=ERR_STRATEGY_NOT_FOUND.format(name=e.strategy_name))
    except InvalidSymbols as e:
        raise HTTPException(
            status_code=400,
            detail=f"Symbol(s) not available on {e.exchange} ({e.mode_label}): {', '.join(e.invalid_symbols)}",
        )
    except MaxBotsReached:
        raise HTTPException(status_code=400, detail=ERR_MAX_BOTS_REACHED.format(max_bots=MAX_BOTS_PER_USER))

    return _config_to_response(config)


@router.get("", response_model=BotListResponse)
async def list_bots(
    demo_mode: Optional[bool] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """List all bots for the current user with runtime status."""
    bots = await bots_service.list_bots_with_status(db, user, orchestrator, demo_mode)
    return BotListResponse(bots=bots)


# ─── Budget / Balance Info (must be before /{bot_id} to avoid route conflict) ──


@router.get("/budget-info", response_model=BotBudgetListResponse)
@limiter.limit("10/minute")
async def get_budget_info(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Budget allocation info per bot with overallocation warnings."""
    return await bots_service.budget_info(db, user.id)


@router.get("/{bot_id}", response_model=BotConfigResponse)
async def get_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific bot configuration."""
    try:
        config = await bots_service.get_bot(db, user.id, bot_id)
    except BotNotFound:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
    return _config_to_response(config)


@router.put("/{bot_id}", response_model=BotConfigResponse)
@limiter.limit("10/minute")
async def update_bot(
    request: Request,
    bot_id: int,
    body: BotConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Update a bot configuration. Bot must be stopped to update."""
    # Pre-fetch the existing config so we can run the cross-bot symbol
    # conflict check before the service mutates state. The service calls
    # get_bot again internally — an extra read is acceptable here because
    # the check must run on the *current* on-disk values.
    try:
        existing = await bots_service.get_bot(db, user.id, bot_id)
    except BotNotFound:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)

    # Block when the update would collide with another enabled bot's symbol.
    # We only probe when pairs/exchange/mode are being modified — a pure rename
    # or webhook change shouldn't cost a conflict query.
    touches_symbol = any(
        getattr(body, f, None) is not None
        for f in ("trading_pairs", "exchange_type", "mode")
    )
    if touches_symbol:
        pairs_for_check = body.trading_pairs if body.trading_pairs is not None else parse_json_field(
            existing.trading_pairs, field_name="trading_pairs", context=f"bot {existing.id}", default=[]
        )
        await _raise_if_symbol_conflict(
            db,
            user_id=user.id,
            exchange_type=body.exchange_type or existing.exchange_type,
            mode=body.mode or existing.mode,
            trading_pairs=pairs_for_check,
            exclude_bot_id=bot_id,
            strategy_type=body.strategy_type or existing.strategy_type,
        )

    try:
        config = await bots_service.update_bot(db, user.id, bot_id, body, orchestrator)
    except BotNotFound:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
    except BotIsRunning:
        raise HTTPException(status_code=400, detail=ERR_STOP_BOT_BEFORE_EDIT)
    except StrategyNotFound as e:
        raise HTTPException(status_code=400, detail=ERR_STRATEGY_NOT_FOUND.format(name=e.strategy_name))
    except InvalidSymbols as e:
        raise HTTPException(
            status_code=400,
            detail=f"Symbol(s) not available on {e.exchange} ({e.mode_label}): {', '.join(e.invalid_symbols)}",
        )

    return _config_to_response(config)


@router.delete("/{bot_id}")
@limiter.limit("10/minute")
async def delete_bot(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    """Delete a bot configuration. Bot must be stopped first."""
    try:
        bot_name = await bots_service.delete_bot(db, user.id, bot_id, orchestrator)
    except BotNotFound:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
    return {"status": "ok", "message": f"Bot '{bot_name}' deleted"}


@router.post("/{bot_id}/duplicate", response_model=BotConfigResponse)
@limiter.limit("10/minute")
async def duplicate_bot(
    request: Request,
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Duplicate an existing bot configuration (stopped, disabled copy)."""
    try:
        copy = await bots_service.duplicate_bot(db, user.id, bot_id)
    except BotNotFound:
        raise HTTPException(status_code=404, detail=ERR_BOT_NOT_FOUND)
    except MaxBotsReached:
        raise HTTPException(
            status_code=400,
            detail=ERR_MAX_BOTS_REACHED.format(max_bots=MAX_BOTS_PER_USER),
        )
    return _config_to_response(copy)


# ─── Include sub-routers ─────────────────────────────────────

from src.api.routers.bots_lifecycle import lifecycle_router  # noqa: E402
from src.api.routers.bots_statistics import statistics_router  # noqa: E402

router.include_router(lifecycle_router)
router.include_router(statistics_router)

# ─── Re-exports for backward compatibility (tests import from here) ──

from src.api.routers.bots_lifecycle import (  # noqa: E402, F401
    _enforce_affiliate_gate,
    _enforce_hl_gates,
    restart_bot,
    start_bot,
    stop_all_bots,
    stop_bot,
    test_telegram,
)
from src.api.routers.bots_statistics import (  # noqa: E402, F401
    compare_bots_performance,
    get_bot_statistics,
)
