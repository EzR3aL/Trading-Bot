"""
Multibot management endpoints.

CRUD for bot configs, strategies, data sources.
Lifecycle (start/stop) and statistics live in sub-modules
(bots_lifecycle, bots_statistics) and are included via sub-routers.
"""

import asyncio
import json
import time as _time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.schemas.bots import (
    BotBudgetInfo,
    BotBudgetListResponse,
    BotConfigCreate,
    BotConfigResponse,
    BotConfigUpdate,
    BotListResponse,
    BotRuntimeStatus,
    ExchangeBalanceOverview,
    ExchangeBalancePreview,
    StrategiesListResponse,
    StrategyInfo,
    SymbolConflict,
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
from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User
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
from src.models.enums import CEX_EXCHANGES, EXCHANGE_NAMES, EXCHANGE_PATTERN
from src.utils.json_helpers import parse_json_field
from src.constants import MAX_BOTS_PER_USER
from src.utils.logger import get_logger

logger = get_logger(__name__)

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


# Mode overlap: which existing modes conflict with a new bot's mode
_MODE_CONFLICTS: dict[str, set[str]] = {
    "demo": {"demo", "both"},
    "live": {"live", "both"},
    "both": {"demo", "live", "both"},
}


async def _check_symbol_conflicts(
    db: AsyncSession,
    user_id: int,
    exchange_type: str,
    mode: str,
    trading_pairs: list[str],
    exclude_bot_id: int | None = None,
    strategy_type: str | None = None,
) -> list[SymbolConflict]:
    """Find enabled bots that already trade the same symbols on the same exchange/mode.

    Copy-trading bots are budget-isolated and may overlap freely with other bots,
    so we short-circuit when ``strategy_type == "copy_trading"``.
    """
    if strategy_type == "copy_trading":
        return []
    conflicting_modes = _MODE_CONFLICTS.get(mode, set())
    query = (
        select(BotConfig)
        .where(
            BotConfig.user_id == user_id,
            BotConfig.exchange_type == exchange_type,
            BotConfig.is_enabled.is_(True),
            BotConfig.mode.in_(conflicting_modes),
            # Skip soft-deleted bots (migration 027 / ARCH-M3). Rows with
            # deleted_at set are "alive but tombstoned" — they neither run
            # nor should block new bots from reusing their symbols.
            BotConfig.deleted_at.is_(None),
        )
    )
    if exclude_bot_id is not None:
        query = query.where(BotConfig.id != exclude_bot_id)

    result = await db.execute(query)
    existing_bots = result.scalars().all()

    # Case-normalize: symbols are stored uppercase in BotConfig.trading_pairs
    # (Pydantic validator on BotConfigCreate enforces ``^[A-Z0-9_-]{1,30}$``),
    # so we compare on the upper-cased set to catch ``btcusdt`` vs ``BTCUSDT``.
    requested_set = {p.upper() for p in trading_pairs}
    conflicts: list[SymbolConflict] = []
    for bot in existing_bots:
        existing_pairs = {
            p.upper()
            for p in parse_json_field(bot.trading_pairs, field_name="trading_pairs", context=f"bot {bot.id}", default=[])
        }
        overlap = requested_set & existing_pairs
        for symbol in sorted(overlap):
            conflicts.append(SymbolConflict(
                symbol=symbol,
                existing_bot_id=bot.id,
                existing_bot_name=bot.name,
                existing_bot_mode=bot.mode,
            ))
    return conflicts


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

    Defense-in-depth companion to the frontend probe on
    ``GET /api/bots/symbol-conflicts``. Uses a stable error code
    (``SYMBOL_ALREADY_IN_USE``) so the UI can map the response to the
    localized message regardless of language.
    """
    conflicts = await _check_symbol_conflicts(
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
    # Stable, machine-readable payload — the UI translates the code.
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
    import asyncio
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

    # For "both" mode, live balance is the limiting factor
    effective_mode = "live" if mode == "both" else mode

    # Check exchange connection
    conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user.id,
            ExchangeConnection.exchange_type == exchange_type,
        )
    )
    conn = conn_result.scalar_one_or_none()
    if not conn:
        return ExchangeBalancePreview(
            exchange_type=exchange_type, mode=mode, has_connection=False,
            error="no_connection",
        )

    is_demo = effective_mode == "demo"
    api_key_enc = conn.demo_api_key_encrypted if is_demo else conn.api_key_encrypted
    api_secret_enc = conn.demo_api_secret_encrypted if is_demo else conn.api_secret_encrypted
    passphrase_enc = conn.demo_passphrase_encrypted if is_demo else conn.passphrase_encrypted

    if not api_key_enc or not api_secret_enc:
        return ExchangeBalancePreview(
            exchange_type=exchange_type, mode=mode, has_connection=False,
            error="no_credentials",
        )

    # Fetch balance (reuse budget cache)
    cache_key = f"budget:{user.id}:{exchange_type}:{effective_mode}"
    cached = _budget_cache_get(cache_key)
    if cached:
        available, equity, currency = cached
    else:
        try:
            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=decrypt_value(api_key_enc),
                api_secret=decrypt_value(api_secret_enc),
                passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                demo_mode=is_demo,
            )
            balance = await asyncio.wait_for(client.get_account_balance(), timeout=10.0)
            available = balance.available
            equity = balance.total
            currency = balance.currency
            _budget_cache_set(cache_key, (available, equity, currency))
        except Exception as e:
            logger.warning("Balance preview fetch failed for %s/%s: %s", exchange_type, effective_mode, e)
            return ExchangeBalancePreview(
                exchange_type=exchange_type, mode=mode, has_connection=True,
                error=f"fetch_failed: {e}",
            )

    # Calculate already-allocated % from existing bots on this exchange/mode
    bot_filter = [
        BotConfig.user_id == user.id,
        BotConfig.exchange_type == exchange_type,
    ]
    if mode == "both":
        bot_filter.append(BotConfig.mode.in_(["live", "both"]))
    else:
        bot_filter.append(BotConfig.mode.in_([mode, "both"]))

    if exclude_bot_id:
        bot_filter.append(BotConfig.id != exclude_bot_id)

    bots_result = await db.execute(select(BotConfig).where(*bot_filter))
    existing_bots = bots_result.scalars().all()

    total_allocated_amount = 0.0
    total_allocated_pct = 0.0
    for bot in existing_bots:
        pac = parse_json_field(bot.per_asset_config, field_name="per_asset_config", context=f"bot {bot.id}", default={})
        try:
            pairs = json.loads(bot.trading_pairs) if isinstance(bot.trading_pairs, str) else (bot.trading_pairs or [])
        except (json.JSONDecodeError, TypeError):
            pairs = []
        for symbol in pairs:
            asset_cfg = pac.get(symbol) or {}
            usdt = asset_cfg.get("position_usdt")
            pct = asset_cfg.get("position_pct")
            if usdt and usdt > 0:
                total_allocated_amount += usdt
            elif pct and pct > 0:
                total_allocated_amount += equity * pct / 100 if equity > 0 else 0.0

    if equity > 0:
        total_allocated_pct = (total_allocated_amount / equity) * 100
    allocated_amount = total_allocated_amount
    remaining = max(0.0, equity - allocated_amount)

    return ExchangeBalancePreview(
        exchange_type=exchange_type,
        mode=mode,
        currency=currency,
        exchange_balance=round(available, 2),
        exchange_equity=round(equity, 2),
        existing_allocated_pct=round(total_allocated_pct, 1),
        existing_allocated_amount=round(allocated_amount, 2),
        remaining_balance=round(remaining, 2),
        has_connection=True,
    )


@router.get("/balance-overview", response_model=ExchangeBalanceOverview)
@limiter.limit("10/minute")
async def get_balance_overview(
    request: Request,
    exclude_bot_id: Optional[int] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Balance overview across ALL connected exchanges (demo + live)."""
    import asyncio
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

    # Load all exchange connections
    conn_result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)
    )
    connections = {c.exchange_type: c for c in conn_result.scalars().all()}

    # Load all bots for allocation calculation
    bot_filter = [BotConfig.user_id == user.id]
    if exclude_bot_id:
        bot_filter.append(BotConfig.id != exclude_bot_id)
    bots_result = await db.execute(select(BotConfig).where(*bot_filter))
    all_bots = bots_result.scalars().all()

    # Build (exchange, mode) pairs to query
    exchange_modes: list[tuple[str, str]] = []
    for ex_type in EXCHANGE_NAMES:
        conn = connections.get(ex_type)
        if not conn:
            continue
        if conn.demo_api_key_encrypted and conn.demo_api_secret_encrypted:
            exchange_modes.append((ex_type, "demo"))
        if conn.api_key_encrypted and conn.api_secret_encrypted:
            exchange_modes.append((ex_type, "live"))

    if not exchange_modes:
        return ExchangeBalanceOverview(exchanges=[])

    # Fetch balances in parallel
    results: list[ExchangeBalancePreview] = []

    async def _fetch(ex_type: str, mode: str):
        conn = connections[ex_type]
        is_demo = mode == "demo"
        api_key_enc = conn.demo_api_key_encrypted if is_demo else conn.api_key_encrypted
        api_secret_enc = conn.demo_api_secret_encrypted if is_demo else conn.api_secret_encrypted
        passphrase_enc = conn.demo_passphrase_encrypted if is_demo else conn.passphrase_encrypted

        # Fetch balance with cache
        cache_key = f"budget:{user.id}:{ex_type}:{mode}"
        cached = _budget_cache_get(cache_key)
        if cached:
            available, equity, currency = cached
        else:
            try:
                client = create_exchange_client(
                    exchange_type=ex_type,
                    api_key=decrypt_value(api_key_enc),
                    api_secret=decrypt_value(api_secret_enc),
                    passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                    demo_mode=is_demo,
                )
                balance = await asyncio.wait_for(client.get_account_balance(), timeout=10.0)
                available, equity, currency = balance.available, balance.total, balance.currency
                _budget_cache_set(cache_key, (available, equity, currency))
            except Exception as e:
                logger.warning("Balance overview fetch failed for %s/%s: %s", ex_type, mode, e)
                results.append(ExchangeBalancePreview(
                    exchange_type=ex_type, mode=mode, has_connection=True,
                    error="fetch_failed",
                ))
                return

        # Calculate allocated amount from existing bots on this exchange/mode
        total_alloc = 0.0
        for bot in all_bots:
            if bot.exchange_type != ex_type:
                continue
            if mode not in (["demo", "both"] if bot.mode == "both" else [bot.mode]):
                if not (bot.mode == "both" or bot.mode == mode):
                    continue
            pac = parse_json_field(bot.per_asset_config, field_name="per_asset_config", context=f"bot {bot.id}", default={})
            try:
                pairs = json.loads(bot.trading_pairs) if isinstance(bot.trading_pairs, str) else (bot.trading_pairs or [])
            except (json.JSONDecodeError, TypeError):
                pairs = []
            for symbol in pairs:
                asset_cfg = pac.get(symbol) or {}
                usdt = asset_cfg.get("position_usdt")
                pct = asset_cfg.get("position_pct")
                if usdt and usdt > 0:
                    total_alloc += usdt
                elif pct and pct > 0:
                    total_alloc += equity * pct / 100 if equity > 0 else 0.0

        total_pct = (total_alloc / equity * 100) if equity > 0 else 0.0
        results.append(ExchangeBalancePreview(
            exchange_type=ex_type,
            mode=mode,
            currency=currency,
            exchange_balance=round(available, 2),
            exchange_equity=round(equity, 2),
            existing_allocated_pct=round(total_pct, 1),
            existing_allocated_amount=round(total_alloc, 2),
            remaining_balance=round(max(0.0, equity - total_alloc), 2),
            has_connection=True,
        ))

    await asyncio.gather(*(_fetch(ex, m) for ex, m in exchange_modes), return_exceptions=True)

    return ExchangeBalanceOverview(exchanges=results)


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
    if not pairs:
        return SymbolConflictResponse()
    conflicts = await _check_symbol_conflicts(
        db, user.id, exchange_type, mode, pairs, exclude_bot_id, strategy_type=strategy_type
    )
    return SymbolConflictResponse(has_conflicts=len(conflicts) > 0, conflicts=conflicts)


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

_budget_cache: dict[str, tuple[float, any]] = {}
_BUDGET_CACHE_TTL = 30  # seconds


def _budget_cache_get(key: str):
    entry = _budget_cache.get(key)
    if entry and (_time.monotonic() - entry[0]) < _BUDGET_CACHE_TTL:
        return entry[1]
    return None


def _budget_cache_set(key: str, value):
    _budget_cache[key] = (_time.monotonic(), value)


@router.get("/budget-info", response_model=BotBudgetListResponse)
@limiter.limit("10/minute")
async def get_budget_info(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Budget allocation info per bot with overallocation warnings."""
    from src.exchanges.factory import create_exchange_client
    from src.utils.encryption import decrypt_value

    result = await db.execute(
        select(BotConfig).where(
            BotConfig.user_id == user.id,
            BotConfig.is_enabled == True,  # noqa: E712
        )
    )
    bot_configs = result.scalars().all()
    if not bot_configs:
        return BotBudgetListResponse(budgets=[])

    conn_result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user.id)
    )
    connections = {c.exchange_type: c for c in conn_result.scalars().all()}

    groups: dict[tuple[str, str], list[BotConfig]] = {}
    for bot in bot_configs:
        modes = ["demo", "live"] if bot.mode == "both" else [bot.mode]
        for m in modes:
            key = (bot.exchange_type, m)
            groups.setdefault(key, []).append(bot)

    balances: dict[tuple[str, str], tuple[float, float, str]] = {}

    async def _fetch_balance(exchange_type: str, mode: str):
        cache_key = f"budget:{user.id}:{exchange_type}:{mode}"
        cached = _budget_cache_get(cache_key)
        if cached is not None:
            balances[(exchange_type, mode)] = cached
            return

        conn = connections.get(exchange_type)
        if not conn:
            return

        is_demo = mode == "demo"
        if is_demo:
            api_key_enc = conn.demo_api_key_encrypted
            api_secret_enc = conn.demo_api_secret_encrypted
            passphrase_enc = conn.demo_passphrase_encrypted
        else:
            api_key_enc = conn.api_key_encrypted
            api_secret_enc = conn.api_secret_encrypted
            passphrase_enc = conn.passphrase_encrypted

        if not api_key_enc or not api_secret_enc:
            return

        try:
            client = create_exchange_client(
                exchange_type=exchange_type,
                api_key=decrypt_value(api_key_enc),
                api_secret=decrypt_value(api_secret_enc),
                passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
                demo_mode=is_demo,
            )
            balance = await asyncio.wait_for(client.get_account_balance(), timeout=10.0)
            val = (balance.available, balance.total, balance.currency)
            balances[(exchange_type, mode)] = val
            _budget_cache_set(cache_key, val)
        except Exception as e:
            logger.warning(f"Budget balance fetch failed for {exchange_type}/{mode}: {e}")

    await asyncio.gather(
        *(_fetch_balance(ex, m) for ex, m in groups.keys()),
        return_exceptions=True,
    )

    group_total_pct: dict[tuple[str, str], float] = {}
    bot_pct_map: dict[tuple[int, str], float] = {}

    for (exchange_type, mode), bots in groups.items():
        total_pct = 0.0
        for bot in bots:
            pac = parse_json_field(
                bot.per_asset_config,
                field_name="per_asset_config",
                context=f"bot {bot.id}",
                default={},
            )
            bot_pct = 0.0
            try:
                pairs = json.loads(bot.trading_pairs) if isinstance(bot.trading_pairs, str) else bot.trading_pairs
            except (json.JSONDecodeError, TypeError):
                pairs = []

            has_fixed = False
            for symbol in pairs:
                asset_cfg = pac.get(symbol, {})
                usdt_val = asset_cfg.get("position_usdt")
                pct_val = asset_cfg.get("position_pct")
                if usdt_val is not None and usdt_val > 0:
                    # Store as pseudo-pct for the budget calculation
                    eq = balances.get((exchange_type, mode), (0, 0, "USDT"))[1]
                    bot_pct += (usdt_val / eq * 100) if eq > 0 else 0.0
                    has_fixed = True
                elif pct_val is not None and pct_val > 0:
                    bot_pct += pct_val
                    has_fixed = True

            if not has_fixed:
                def _has_fixed_alloc(b):
                    _pac = parse_json_field(b.per_asset_config, default={})
                    try:
                        _pairs = json.loads(b.trading_pairs) if isinstance(b.trading_pairs, str) else []
                    except (json.JSONDecodeError, TypeError):
                        _pairs = []
                    return any(
                        (_pac.get(s, {}).get("position_usdt") or _pac.get(s, {}).get("position_pct"))
                        for s in _pairs
                    )
                bot_pct = 100.0 / max(len(bots), 1) if not any(_has_fixed_alloc(b) for b in bots) else 0.0

            bot_pct_map[(bot.id, mode)] = bot_pct
            total_pct += bot_pct

        group_total_pct[(exchange_type, mode)] = total_pct

    # Query open trades to calculate margin already in use per bot
    open_trades_result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.user_id == user.id,
            TradeRecord.status == "open",
        )
    )
    open_trades = open_trades_result.scalars().all()

    # Build map: bot_id -> total margin used by open positions
    bot_margin_used: dict[int, float] = {}
    for trade in open_trades:
        if trade.entry_price and trade.size and trade.leverage:
            margin = trade.entry_price * trade.size / trade.leverage
            bot_margin_used[trade.bot_config_id] = bot_margin_used.get(trade.bot_config_id, 0.0) + margin

    budgets: list[BotBudgetInfo] = []
    seen = set()

    for (exchange_type, mode), bots in groups.items():
        bal = balances.get((exchange_type, mode))
        available = bal[0] if bal else 0.0
        equity = bal[1] if bal else 0.0
        currency = bal[2] if bal else "USDT"
        total_pct = group_total_pct.get((exchange_type, mode), 0.0)

        for bot in bots:
            entry_key = (bot.id, mode)
            if entry_key in seen:
                continue
            seen.add(entry_key)

            pct = bot_pct_map.get((bot.id, mode), 0.0)
            allocated_budget = equity * pct / 100 if pct > 0 else 0.0

            # Account for margin already used by this bot's open positions
            margin_in_use = bot_margin_used.get(bot.id, 0.0)
            effective_available = available + margin_in_use
            has_funds = allocated_budget <= effective_available and total_pct <= 100.0

            warning = None
            if total_pct > 100.0:
                warning = f"Overallocated: {total_pct:.0f}% of 100% used on {exchange_type} ({mode})"
            elif allocated_budget > effective_available:
                warning = f"Insufficient balance: ${allocated_budget:,.2f} needed, ${effective_available:,.2f} available"

            budgets.append(BotBudgetInfo(
                bot_config_id=bot.id,
                bot_name=bot.name,
                exchange_type=exchange_type,
                mode=mode,
                currency=currency,
                exchange_balance=available,
                exchange_equity=equity,
                allocated_budget=allocated_budget,
                allocated_pct=pct,
                total_allocated_pct=total_pct,
                has_sufficient_funds=has_funds,
                warning_message=warning,
            ))

    return BotBudgetListResponse(budgets=budgets)


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
