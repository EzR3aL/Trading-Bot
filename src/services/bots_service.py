"""Bot management service (ARCH-C1 Phase 2b).

FastAPI-free business logic for ``/api/bots`` handlers. The router is a
thin HTTP adapter: it parses query params, calls the service, and maps
the returned plain dicts / ORM objects onto Pydantic response models.

Populated incrementally:

* PR-1 (#286) — ``list_strategies`` + ``list_data_sources`` (static reads)
* PR-2 (#293) — ``get_bot`` / ``delete_bot`` / ``duplicate_bot`` (single-bot CRUD)
* PR-3 (#295) — ``list_bots_with_status`` (bot list with runtime + batch stats)
* PR-4 (#297) — ``create_bot`` / ``update_bot`` (validation + encryption)
* PR-5 (#299) — ``balance_preview`` / ``balance_overview`` / ``symbol_conflicts``
  / ``budget_info`` (exchange-client-coupled reads with 30s budget cache)
"""

from __future__ import annotations

import asyncio
import json
import time as _time
from typing import Any, Optional, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.bots import (
    BotBudgetInfo,
    BotBudgetListResponse,
    BotConfigCreate,
    BotConfigUpdate,
    BotRuntimeStatus,
    ExchangeBalanceOverview,
    ExchangeBalancePreview,
    SymbolConflict,
    SymbolConflictResponse,
)
from src.constants import MAX_BOTS_PER_USER
from src.data.data_source_registry import DATA_SOURCES, DEFAULT_SOURCES
from src.exchanges.factory import create_exchange_client
from src.exchanges.symbol_fetcher import get_exchange_symbols
from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User
from src.models.enums import CEX_EXCHANGES, EXCHANGE_NAMES
from src.services.exceptions import (
    BotIsRunning,
    BotNotFound,
    InvalidSymbols,
    MaxBotsReached,
    StrategyNotFound,
)
from src.strategy import StrategyRegistry
from src.utils.encryption import decrypt_value, encrypt_value
from src.utils.json_helpers import parse_json_field
from src.utils.logger import get_logger

logger = get_logger(__name__)


class _OrchestratorLike(Protocol):
    """Minimal surface the service needs from the orchestrator.

    Declared as a Protocol so the service module doesn't import the
    concrete ``BotOrchestrator`` (which pulls in the full bot stack).
    """

    def is_running(self, bot_id: int) -> bool: ...

    async def stop_bot(self, bot_id: int) -> Any: ...

    def get_bot_status(self, bot_id: int) -> dict | None: ...


# ── Static reads ────────────────────────────────────────────────────


def list_strategies() -> list[dict[str, Any]]:
    """Return the registry of available trading strategies.

    Each entry is the plain-dict shape that ``StrategyInfo`` serializes
    from. The router wraps the list in ``StrategiesListResponse``.
    """
    return StrategyRegistry.list_available()


def list_data_sources() -> dict[str, Any]:
    """Return the catalog of market data sources + defaults.

    Mirrors the router-level response verbatim:
    ``{"sources": [<DataSource.to_dict()>, ...], "defaults": [...]}``.
    The router returns this dict directly (no Pydantic model wrapping).
    """
    return {
        "sources": [ds.to_dict() for ds in DATA_SOURCES],
        "defaults": DEFAULT_SOURCES,
    }


# ── Single-bot CRUD ─────────────────────────────────────────────────


async def get_bot(db: AsyncSession, user_id: int, bot_id: int) -> BotConfig:
    """Return the ``BotConfig`` if it exists and belongs to ``user_id``.

    Raises ``BotNotFound`` when the row is missing or owned by a
    different user (collapsed to the same error to avoid leaking
    existence across tenants).
    """
    result = await db.execute(
        select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == user_id)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise BotNotFound(bot_id)
    return config


async def delete_bot(
    db: AsyncSession,
    user_id: int,
    bot_id: int,
    orchestrator: _OrchestratorLike,
) -> str:
    """Delete a bot; stop it first if it is currently running.

    Returns the deleted bot name (used by the router in its response
    message). Side effects: audit log + event log, same as before the
    extract. Raises ``BotNotFound`` when the row is missing / owned by
    a different user.
    """
    config = await get_bot(db, user_id, bot_id)

    if orchestrator.is_running(bot_id):
        await orchestrator.stop_bot(bot_id)

    bot_name = config.name
    await db.delete(config)
    logger.info(f"Bot deleted: {bot_name} (id={bot_id})")

    # Late imports keep the service module FastAPI-free and avoid
    # pulling the audit/event subsystems into unit-test environments
    # that don't need them.
    from src.utils.config_audit import log_config_change
    from src.utils.event_logger import log_event

    await log_event(
        "bot_deleted",
        f"Bot '{bot_name}' deleted",
        user_id=user_id,
        bot_id=bot_id,
    )
    await log_config_change(
        user_id=user_id,
        entity_type="bot_config",
        entity_id=bot_id,
        action="delete",
        old_data={"name": bot_name},
    )

    return bot_name


async def duplicate_bot(
    db: AsyncSession,
    user_id: int,
    bot_id: int,
) -> BotConfig:
    """Clone a bot as a disabled copy named ``"{original} (Copy)"``.

    Enforces ``MAX_BOTS_PER_USER`` before creating the copy. Raises
    ``BotNotFound`` if the source bot is missing and ``MaxBotsReached``
    if the user would exceed the limit.
    """
    original = await get_bot(db, user_id, bot_id)

    count_result = await db.execute(
        select(func.count(BotConfig.id)).where(BotConfig.user_id == user_id)
    )
    if count_result.scalar() >= MAX_BOTS_PER_USER:
        raise MaxBotsReached(MAX_BOTS_PER_USER)

    copy = BotConfig(
        user_id=user_id,
        name=f"{original.name} (Copy)",
        description=original.description,
        strategy_type=original.strategy_type,
        exchange_type=original.exchange_type,
        mode=original.mode,
        trading_pairs=original.trading_pairs,
        leverage=original.leverage,
        position_size_percent=original.position_size_percent,
        max_trades_per_day=original.max_trades_per_day,
        take_profit_percent=original.take_profit_percent,
        stop_loss_percent=original.stop_loss_percent,
        daily_loss_limit_percent=original.daily_loss_limit_percent,
        per_asset_config=original.per_asset_config,
        strategy_params=original.strategy_params,
        schedule_type=original.schedule_type,
        schedule_config=original.schedule_config,
        discord_webhook_url=original.discord_webhook_url,
        telegram_bot_token=original.telegram_bot_token,
        telegram_chat_id=original.telegram_chat_id,
        is_enabled=False,
    )
    db.add(copy)
    await db.flush()
    await db.refresh(copy)

    logger.info(
        f"Bot duplicated: {original.name} -> {copy.name} "
        f"(id={copy.id}) by user {user_id}"
    )

    from src.utils.event_logger import log_event
    await log_event(
        "bot_duplicated",
        f"Bot '{original.name}' duplicated as '{copy.name}'",
        user_id=user_id,
        bot_id=copy.id,
    )

    return copy


# ── List with runtime status ────────────────────────────────────────


async def list_bots_with_status(
    db: AsyncSession,
    user: User,
    orchestrator: _OrchestratorLike,
    demo_mode: Optional[bool] = None,
) -> list[BotRuntimeStatus]:
    """Return all bots for ``user`` with runtime state + aggregated stats.

    Preloads HL gate flags, CEX affiliate UIDs, and batch-aggregates
    trade / open-position / orphaned-trade counts so the response builds
    with a bounded number of queries regardless of bot count.
    """
    is_admin = user.role == "admin"

    hl_approved = False
    hl_referral_verified = False
    if is_admin:
        hl_approved = True
        hl_referral_verified = True
    else:
        hl_conn_result = await db.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user.id,
                ExchangeConnection.exchange_type == "hyperliquid",
            )
        )
        hl_conn = hl_conn_result.scalar_one_or_none()
        if hl_conn:
            hl_approved = getattr(hl_conn, "builder_fee_approved", False)
            hl_referral_verified = getattr(hl_conn, "referral_verified", False)

    affiliate_data: dict[str, dict] = {}
    if not is_admin:
        aff_result = await db.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user.id,
                ExchangeConnection.exchange_type.in_(CEX_EXCHANGES),
            )
        )
        for aff_conn in aff_result.scalars().all():
            affiliate_data[aff_conn.exchange_type] = {
                "uid": getattr(aff_conn, "affiliate_uid", None),
                "verified": getattr(aff_conn, "affiliate_verified", False),
            }

    bot_query = select(BotConfig).where(BotConfig.user_id == user.id)
    if demo_mode is True:
        bot_query = bot_query.where(BotConfig.mode.in_(["demo", "both"]))
    elif demo_mode is False:
        bot_query = bot_query.where(BotConfig.mode.in_(["live", "both"]))
    bot_query = bot_query.order_by(BotConfig.created_at.desc())

    result = await db.execute(bot_query)
    configs = result.scalars().all()

    bot_ids = [c.id for c in configs]

    trade_stats: dict[int, tuple] = {}
    open_counts: dict[int, int] = {}
    orphaned_counts: dict[int, int] = {}

    if bot_ids:
        stats_filters = [TradeRecord.bot_config_id.in_(bot_ids)]
        if demo_mode is not None:
            stats_filters.append(TradeRecord.demo_mode == demo_mode)

        stats_result = await db.execute(
            select(
                TradeRecord.bot_config_id,
                func.count(TradeRecord.id),
                func.coalesce(func.sum(TradeRecord.pnl), 0),
                func.coalesce(func.sum(TradeRecord.fees), 0),
                func.coalesce(func.sum(TradeRecord.funding_paid), 0),
            ).where(*stats_filters)
            .group_by(TradeRecord.bot_config_id)
        )
        for bid, cnt, pnl, fees, funding in stats_result.all():
            trade_stats[bid] = (cnt, pnl, fees, funding)

        open_filters = [
            TradeRecord.bot_config_id.in_(bot_ids),
            TradeRecord.status == "open",
        ]
        if demo_mode is not None:
            open_filters.append(TradeRecord.demo_mode == demo_mode)

        open_result = await db.execute(
            select(
                TradeRecord.bot_config_id,
                func.count(TradeRecord.id),
            ).where(*open_filters)
            .group_by(TradeRecord.bot_config_id)
        )
        open_counts = dict(open_result.all())

        # Local import: PendingTrade lives in the same model module but
        # keeping it lazy mirrors the router's original structure and
        # avoids a cycle when lightweight callers only need BotConfig.
        from src.models.database import PendingTrade
        orphaned_result = await db.execute(
            select(
                PendingTrade.bot_config_id,
                func.count(PendingTrade.id),
            ).where(
                PendingTrade.bot_config_id.in_(bot_ids),
                PendingTrade.status == "orphaned",
            ).group_by(PendingTrade.bot_config_id)
        )
        orphaned_counts = dict(orphaned_result.all())

    bots: list[BotRuntimeStatus] = []

    for config in configs:
        runtime = orchestrator.get_bot_status(config.id)
        trading_pairs = json.loads(config.trading_pairs) if config.trading_pairs else []

        total_trades, total_pnl, total_fees, total_funding = trade_stats.get(
            config.id, (0, 0, 0, 0)
        )
        open_trades = open_counts.get(config.id, 0)
        orphaned_trade_count = orphaned_counts.get(config.id, 0)

        _sched_config = None
        if config.schedule_config:
            try:
                _sched_config = (
                    json.loads(config.schedule_config)
                    if isinstance(config.schedule_config, str)
                    else config.schedule_config
                )
            except (json.JSONDecodeError, TypeError):
                pass

        _risk_profile = None
        _copy_source_wallet = None
        _copy_max_slots = None
        _copy_budget_usdt = None
        if config.strategy_params:
            try:
                _sp = (
                    json.loads(config.strategy_params)
                    if isinstance(config.strategy_params, str)
                    else config.strategy_params
                )
                _risk_profile = _sp.get("risk_profile")
                if config.strategy_type == "copy_trading":
                    _copy_source_wallet = _sp.get("source_wallet")
                    _copy_max_slots = _sp.get("max_slots")
                    _copy_budget_usdt = _sp.get("budget_usdt")
            except (json.JSONDecodeError, TypeError):
                pass

        is_hl = config.exchange_type == "hyperliquid"
        is_cex = config.exchange_type in CEX_EXCHANGES
        aff_entry = affiliate_data.get(config.exchange_type, {})

        bots.append(BotRuntimeStatus(
            bot_config_id=config.id,
            name=config.name,
            strategy_type=config.strategy_type,
            exchange_type=config.exchange_type,
            mode=config.mode,
            margin_mode=getattr(config, "margin_mode", None) or "cross",
            trading_pairs=trading_pairs,
            risk_profile=_risk_profile,
            copy_source_wallet=_copy_source_wallet,
            copy_max_slots=_copy_max_slots,
            copy_budget_usdt=_copy_budget_usdt,
            status=runtime["status"] if runtime else ("idle" if not config.is_enabled else "stopped"),
            error_message=runtime.get("error_message") if runtime else None,
            started_at=runtime.get("started_at") if runtime else None,
            last_analysis=runtime.get("last_analysis") if runtime else None,
            trades_today=runtime.get("trades_today", 0) if runtime else 0,
            is_enabled=config.is_enabled,
            schedule_type=config.schedule_type,
            schedule_config=_sched_config,
            total_trades=total_trades,
            total_pnl=round(float(total_pnl), 2),
            total_fees=round(float(total_fees), 2),
            total_funding=round(float(total_funding), 2),
            open_trades=open_trades,
            orphaned_trades=orphaned_trade_count,
            discord_webhook_configured=bool(config.discord_webhook_url),
            telegram_configured=bool(config.telegram_bot_token and config.telegram_chat_id),
            builder_fee_approved=hl_approved if is_hl else None,
            referral_verified=hl_referral_verified if is_hl else None,
            affiliate_uid=aff_entry.get("uid") if is_cex else None,
            affiliate_verified=(True if is_admin else aff_entry.get("verified")) if is_cex else None,
        ))

    return bots


# ── Write handlers ──────────────────────────────────────────────────


async def _validate_strategy(strategy_type: str) -> None:
    """Raise ``StrategyNotFound`` if the strategy isn't registered."""
    try:
        StrategyRegistry.get(strategy_type)
    except KeyError:
        raise StrategyNotFound(strategy_type)


async def _validate_symbols(
    exchange: str,
    mode: str,
    trading_pairs: list[str],
) -> None:
    """Raise ``InvalidSymbols`` if any pair isn't listed on the exchange.

    Queries ``symbol_fetcher`` with the demo-or-live flag derived from ``mode``.
    A short-circuits when the fetcher returns an empty set (cached-miss /
    unreachable exchange) — validation degrades open in that case, mirroring
    the original router behavior.
    """
    is_demo = mode in ("demo", "both")
    available = await get_exchange_symbols(exchange, demo_mode=is_demo)
    if not available:
        return
    invalid = [p for p in trading_pairs if p not in available]
    if invalid:
        mode_label = "demo" if is_demo else "live"
        raise InvalidSymbols(exchange, mode_label, invalid)


async def create_bot(
    db: AsyncSession,
    user_id: int,
    body: BotConfigCreate,
) -> BotConfig:
    """Create a new bot configuration.

    Validates strategy + symbols, enforces ``MAX_BOTS_PER_USER``, encrypts
    the optional Discord / Telegram credentials, persists the row, and
    writes audit + event log entries. Returns the refreshed ``BotConfig``
    ORM object — the router maps it onto ``BotConfigResponse``.
    """
    await _validate_strategy(body.strategy_type)
    await _validate_symbols(body.exchange_type, body.mode, body.trading_pairs)

    count_result = await db.execute(
        select(func.count(BotConfig.id)).where(BotConfig.user_id == user_id)
    )
    if count_result.scalar() >= MAX_BOTS_PER_USER:
        raise MaxBotsReached(MAX_BOTS_PER_USER)

    encrypted_webhook = encrypt_value(body.discord_webhook_url) if body.discord_webhook_url else None
    encrypted_telegram_token = encrypt_value(body.telegram_bot_token) if body.telegram_bot_token else None
    encrypted_chat_id = encrypt_value(body.telegram_chat_id) if body.telegram_chat_id else None

    config = BotConfig(
        user_id=user_id,
        name=body.name,
        description=body.description,
        strategy_type=body.strategy_type,
        exchange_type=body.exchange_type,
        mode=body.mode,
        margin_mode=body.margin_mode,
        trading_pairs=json.dumps(body.trading_pairs),
        leverage=body.leverage,
        position_size_percent=body.position_size_percent,
        max_trades_per_day=body.max_trades_per_day,
        take_profit_percent=body.take_profit_percent,
        stop_loss_percent=body.stop_loss_percent,
        daily_loss_limit_percent=body.daily_loss_limit_percent,
        per_asset_config=json.dumps(body.per_asset_config) if body.per_asset_config else None,
        strategy_params=json.dumps(body.strategy_params) if body.strategy_params else None,
        schedule_type=body.schedule_type,
        schedule_config=json.dumps(body.schedule_config) if body.schedule_config else None,
        discord_webhook_url=encrypted_webhook,
        telegram_bot_token=encrypted_telegram_token,
        telegram_chat_id=encrypted_chat_id,
        pnl_alert_settings=(
            json.dumps(body.pnl_alert_settings.model_dump())
            if body.pnl_alert_settings else None
        ),
        is_enabled=False,
    )
    db.add(config)
    await db.flush()
    await db.refresh(config)

    logger.info(f"Bot created: {config.name} (id={config.id}) by user {user_id}")

    from src.utils.config_audit import log_config_change
    from src.utils.event_logger import log_event
    await log_event(
        "bot_created",
        f"Bot '{config.name}' created",
        user_id=user_id,
        bot_id=config.id,
    )
    await log_config_change(
        user_id=user_id,
        entity_type="bot_config",
        entity_id=config.id,
        action="create",
        new_data=body.model_dump(),
    )

    return config


# Fields where an empty-string value means "clear" and a non-empty value
# means "replace with encrypted(value)". Centralizes the write-time rule
# the router previously duplicated across three if-branches.
_ENCRYPTED_CLEAR_ON_EMPTY_FIELDS: frozenset[str] = frozenset({
    "discord_webhook_url",
    "telegram_bot_token",
    "telegram_chat_id",
})

# Fields that must be JSON-dumped before hitting the ORM column (string col).
_JSON_DUMPED_FIELDS: frozenset[str] = frozenset({
    "trading_pairs",
    "strategy_params",
    "schedule_config",
    "per_asset_config",
    "pnl_alert_settings",
})


async def update_bot(
    db: AsyncSession,
    user_id: int,
    bot_id: int,
    body: BotConfigUpdate,
    orchestrator: _OrchestratorLike,
) -> BotConfig:
    """Update a bot configuration; the bot must not be running.

    Raises ``BotNotFound``/``BotIsRunning``/``StrategyNotFound``/
    ``InvalidSymbols``. Applies only fields present in ``body`` (uses
    ``model_dump(exclude_unset=True)`` as the patch set) and writes the
    diff to the config audit log.
    """
    config = await get_bot(db, user_id, bot_id)

    if orchestrator.is_running(bot_id):
        raise BotIsRunning(bot_id)

    if body.strategy_type:
        await _validate_strategy(body.strategy_type)

    if body.trading_pairs is not None:
        exchange = body.exchange_type or config.exchange_type
        mode = body.mode or config.mode
        await _validate_symbols(exchange, mode, body.trading_pairs)

    update_data = body.model_dump(exclude_unset=True)
    audit_old = {f: getattr(config, f, None) for f in update_data}

    for field, value in update_data.items():
        if field in _ENCRYPTED_CLEAR_ON_EMPTY_FIELDS:
            setattr(config, field, encrypt_value(value) if value else None)
        elif field in _JSON_DUMPED_FIELDS and value is not None:
            setattr(config, field, json.dumps(value))
        elif value is not None:
            setattr(config, field, value)

    await db.flush()
    await db.refresh(config)

    logger.info(f"Bot updated: {config.name} (id={bot_id})")

    from src.utils.config_audit import log_config_change
    await log_config_change(
        user_id=user_id,
        entity_type="bot_config",
        entity_id=bot_id,
        action="update",
        old_data=audit_old,
        new_data=update_data,
    )

    return config


# ── Balance / budget / symbol-conflict reads ────────────────────────


# Mode overlap map: which existing-bot modes conflict with a new bot's mode.
# A bot in "both" overlaps with everything; demo overlaps with demo+both; etc.
_MODE_CONFLICTS: dict[str, set[str]] = {
    "demo": {"demo", "both"},
    "live": {"live", "both"},
    "both": {"demo", "live", "both"},
}

# 30-second in-memory cache keyed by (user, exchange, mode). Populated by all
# three balance handlers so rapid successive calls during a BotBuilder session
# don't hammer the exchange API.
_budget_cache: dict[str, tuple[float, tuple[float, float, str]]] = {}
_BUDGET_CACHE_TTL: float = 30.0


def _budget_cache_get(key: str) -> Optional[tuple[float, float, str]]:
    entry = _budget_cache.get(key)
    if entry and (_time.monotonic() - entry[0]) < _BUDGET_CACHE_TTL:
        return entry[1]
    return None


def _budget_cache_set(key: str, value: tuple[float, float, str]) -> None:
    _budget_cache[key] = (_time.monotonic(), value)


def _pick_credentials(
    conn: ExchangeConnection,
    is_demo: bool,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (api_key_enc, api_secret_enc, passphrase_enc) for the chosen mode."""
    if is_demo:
        return (
            conn.demo_api_key_encrypted,
            conn.demo_api_secret_encrypted,
            conn.demo_passphrase_encrypted,
        )
    return (
        conn.api_key_encrypted,
        conn.api_secret_encrypted,
        conn.passphrase_encrypted,
    )


async def _fetch_balance_live(
    exchange_type: str,
    is_demo: bool,
    api_key_enc: str,
    api_secret_enc: str,
    passphrase_enc: Optional[str],
) -> tuple[float, float, str]:
    """Fetch (available, equity, currency) from the exchange. Raises on any failure."""
    client = create_exchange_client(
        exchange_type=exchange_type,
        api_key=decrypt_value(api_key_enc),
        api_secret=decrypt_value(api_secret_enc),
        passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
        demo_mode=is_demo,
    )
    balance = await asyncio.wait_for(client.get_account_balance(), timeout=10.0)
    return (balance.available, balance.total, balance.currency)


def _bot_alloc_pairs(bot: BotConfig) -> list[str]:
    """Return parsed ``trading_pairs`` for allocation math (empty on parse error)."""
    try:
        return json.loads(bot.trading_pairs) if isinstance(bot.trading_pairs, str) else (bot.trading_pairs or [])
    except (json.JSONDecodeError, TypeError):
        return []


def _bot_allocated_amount(bot: BotConfig, equity: float) -> float:
    """Sum the USDT allocation a bot pulls from ``equity`` based on per-asset config."""
    pac = parse_json_field(bot.per_asset_config, field_name="per_asset_config", context=f"bot {bot.id}", default={})
    total = 0.0
    for symbol in _bot_alloc_pairs(bot):
        cfg = pac.get(symbol) or {}
        usdt = cfg.get("position_usdt")
        pct = cfg.get("position_pct")
        if usdt and usdt > 0:
            total += usdt
        elif pct and pct > 0:
            total += equity * pct / 100 if equity > 0 else 0.0
    return total


async def _check_symbol_conflicts(
    db: AsyncSession,
    user_id: int,
    exchange_type: str,
    mode: str,
    trading_pairs: list[str],
    exclude_bot_id: Optional[int] = None,
    strategy_type: Optional[str] = None,
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
        )
    )
    if exclude_bot_id is not None:
        query = query.where(BotConfig.id != exclude_bot_id)

    result = await db.execute(query)
    existing_bots = result.scalars().all()

    requested_set = set(trading_pairs)
    conflicts: list[SymbolConflict] = []
    for bot in existing_bots:
        existing_pairs = set(parse_json_field(
            bot.trading_pairs, field_name="trading_pairs", context=f"bot {bot.id}", default=[]
        ))
        overlap = requested_set & existing_pairs
        for symbol in sorted(overlap):
            conflicts.append(SymbolConflict(
                symbol=symbol,
                existing_bot_id=bot.id,
                existing_bot_name=bot.name,
                existing_bot_mode=bot.mode,
            ))
    return conflicts


async def symbol_conflicts(
    db: AsyncSession,
    user_id: int,
    exchange_type: str,
    mode: str,
    trading_pairs: list[str],
    exclude_bot_id: Optional[int] = None,
    strategy_type: Optional[str] = None,
) -> SymbolConflictResponse:
    """Public wrapper — returns ``SymbolConflictResponse`` with ``has_conflicts`` flag set."""
    if not trading_pairs:
        return SymbolConflictResponse()
    conflicts = await _check_symbol_conflicts(
        db, user_id, exchange_type, mode, trading_pairs, exclude_bot_id, strategy_type,
    )
    return SymbolConflictResponse(has_conflicts=len(conflicts) > 0, conflicts=conflicts)


async def balance_preview(
    db: AsyncSession,
    user_id: int,
    exchange_type: str,
    mode: str,
    exclude_bot_id: Optional[int] = None,
) -> ExchangeBalancePreview:
    """Balance + allocation preview for a single (exchange, mode) pair.

    Returns a populated ``ExchangeBalancePreview``. Error paths set the
    ``error`` field (``"no_connection"`` / ``"no_credentials"`` /
    ``"fetch_failed: ..."``) rather than raising — the Bot Builder uses
    the error string to render a fallback message.
    """
    # For "both" mode, live balance is the limiting factor
    effective_mode = "live" if mode == "both" else mode

    conn_result = await db.execute(
        select(ExchangeConnection).where(
            ExchangeConnection.user_id == user_id,
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
    api_key_enc, api_secret_enc, passphrase_enc = _pick_credentials(conn, is_demo)

    if not api_key_enc or not api_secret_enc:
        return ExchangeBalancePreview(
            exchange_type=exchange_type, mode=mode, has_connection=False,
            error="no_credentials",
        )

    cache_key = f"budget:{user_id}:{exchange_type}:{effective_mode}"
    cached = _budget_cache_get(cache_key)
    if cached:
        available, equity, currency = cached
    else:
        try:
            available, equity, currency = await _fetch_balance_live(
                exchange_type, is_demo, api_key_enc, api_secret_enc, passphrase_enc,
            )
            _budget_cache_set(cache_key, (available, equity, currency))
        except Exception as e:
            logger.warning("Balance preview fetch failed for %s/%s: %s", exchange_type, effective_mode, e)
            return ExchangeBalancePreview(
                exchange_type=exchange_type, mode=mode, has_connection=True,
                error=f"fetch_failed: {e}",
            )

    bot_filter = [
        BotConfig.user_id == user_id,
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

    total_allocated_amount = sum(_bot_allocated_amount(b, equity) for b in existing_bots)
    total_allocated_pct = (total_allocated_amount / equity * 100) if equity > 0 else 0.0
    remaining = max(0.0, equity - total_allocated_amount)

    return ExchangeBalancePreview(
        exchange_type=exchange_type,
        mode=mode,
        currency=currency,
        exchange_balance=round(available, 2),
        exchange_equity=round(equity, 2),
        existing_allocated_pct=round(total_allocated_pct, 1),
        existing_allocated_amount=round(total_allocated_amount, 2),
        remaining_balance=round(remaining, 2),
        has_connection=True,
    )


async def balance_overview(
    db: AsyncSession,
    user_id: int,
    exclude_bot_id: Optional[int] = None,
) -> ExchangeBalanceOverview:
    """Balance + allocation across ALL connected (exchange, mode) pairs.

    Fetches balances in parallel via ``asyncio.gather``. Exchanges with
    missing connections / credentials are silently omitted; fetch failures
    appear in the response with ``error="fetch_failed"``.
    """
    conn_result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
    )
    connections = {c.exchange_type: c for c in conn_result.scalars().all()}

    bot_filter = [BotConfig.user_id == user_id]
    if exclude_bot_id:
        bot_filter.append(BotConfig.id != exclude_bot_id)
    bots_result = await db.execute(select(BotConfig).where(*bot_filter))
    all_bots = bots_result.scalars().all()

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

    results: list[ExchangeBalancePreview] = []

    async def _fetch(ex_type: str, mode: str) -> None:
        conn = connections[ex_type]
        is_demo = mode == "demo"
        api_key_enc, api_secret_enc, passphrase_enc = _pick_credentials(conn, is_demo)

        cache_key = f"budget:{user_id}:{ex_type}:{mode}"
        cached = _budget_cache_get(cache_key)
        if cached:
            available, equity, currency = cached
        else:
            try:
                available, equity, currency = await _fetch_balance_live(
                    ex_type, is_demo, api_key_enc, api_secret_enc, passphrase_enc,
                )
                _budget_cache_set(cache_key, (available, equity, currency))
            except Exception as e:
                logger.warning("Balance overview fetch failed for %s/%s: %s", ex_type, mode, e)
                results.append(ExchangeBalancePreview(
                    exchange_type=ex_type, mode=mode, has_connection=True,
                    error="fetch_failed",
                ))
                return

        total_alloc = 0.0
        for bot in all_bots:
            if bot.exchange_type != ex_type:
                continue
            # Preserve original mode-inclusion test: treat "both" bots as hitting
            # both demo and live budgets, others only their own mode.
            if not (bot.mode == "both" or bot.mode == mode):
                continue
            total_alloc += _bot_allocated_amount(bot, equity)

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


async def budget_info(
    db: AsyncSession,
    user_id: int,
) -> BotBudgetListResponse:
    """Per-bot budget allocation with overallocation + insufficient-funds warnings.

    Groups enabled bots by (exchange, mode) — a ``both``-mode bot counts
    in both demo and live groups. Within each group, the allocated percent
    per bot comes from ``per_asset_config`` (``position_usdt`` or
    ``position_pct``); bots without fixed allocations split the group
    evenly. Open-position margin is credited back into "effective available"
    so the has-sufficient-funds check doesn't double-count tied-up capital.
    """
    result = await db.execute(
        select(BotConfig).where(
            BotConfig.user_id == user_id,
            BotConfig.is_enabled == True,  # noqa: E712
        )
    )
    bot_configs = result.scalars().all()
    if not bot_configs:
        return BotBudgetListResponse(budgets=[])

    conn_result = await db.execute(
        select(ExchangeConnection).where(ExchangeConnection.user_id == user_id)
    )
    connections = {c.exchange_type: c for c in conn_result.scalars().all()}

    groups: dict[tuple[str, str], list[BotConfig]] = {}
    for bot in bot_configs:
        modes = ["demo", "live"] if bot.mode == "both" else [bot.mode]
        for m in modes:
            key = (bot.exchange_type, m)
            groups.setdefault(key, []).append(bot)

    balances: dict[tuple[str, str], tuple[float, float, str]] = {}

    async def _fetch_for_group(exchange_type: str, mode: str) -> None:
        cache_key = f"budget:{user_id}:{exchange_type}:{mode}"
        cached = _budget_cache_get(cache_key)
        if cached is not None:
            balances[(exchange_type, mode)] = cached
            return

        conn = connections.get(exchange_type)
        if not conn:
            return

        is_demo = mode == "demo"
        api_key_enc, api_secret_enc, passphrase_enc = _pick_credentials(conn, is_demo)
        if not api_key_enc or not api_secret_enc:
            return

        try:
            val = await _fetch_balance_live(
                exchange_type, is_demo, api_key_enc, api_secret_enc, passphrase_enc,
            )
            balances[(exchange_type, mode)] = val
            _budget_cache_set(cache_key, val)
        except Exception as e:
            logger.warning(f"Budget balance fetch failed for {exchange_type}/{mode}: {e}")

    await asyncio.gather(
        *(_fetch_for_group(ex, m) for ex, m in groups.keys()),
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
            pairs = _bot_alloc_pairs(bot)

            has_fixed = False
            for symbol in pairs:
                asset_cfg = pac.get(symbol, {})
                usdt_val = asset_cfg.get("position_usdt")
                pct_val = asset_cfg.get("position_pct")
                if usdt_val is not None and usdt_val > 0:
                    eq = balances.get((exchange_type, mode), (0, 0, "USDT"))[1]
                    bot_pct += (usdt_val / eq * 100) if eq > 0 else 0.0
                    has_fixed = True
                elif pct_val is not None and pct_val > 0:
                    bot_pct += pct_val
                    has_fixed = True

            if not has_fixed:
                def _has_fixed_alloc(b: BotConfig) -> bool:
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

    open_trades_result = await db.execute(
        select(TradeRecord).where(
            TradeRecord.user_id == user_id,
            TradeRecord.status == "open",
        )
    )
    open_trades = open_trades_result.scalars().all()

    bot_margin_used: dict[int, float] = {}
    for trade in open_trades:
        if trade.entry_price and trade.size and trade.leverage:
            margin = trade.entry_price * trade.size / trade.leverage
            bot_margin_used[trade.bot_config_id] = bot_margin_used.get(trade.bot_config_id, 0.0) + margin

    budgets: list[BotBudgetInfo] = []
    seen: set[tuple[int, str]] = set()

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
