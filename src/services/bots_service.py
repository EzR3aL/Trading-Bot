"""Bot management service (ARCH-C1 Phase 2b).

FastAPI-free business logic for ``/api/bots`` handlers. The router is a
thin HTTP adapter: it parses query params, calls the service, and maps
the returned plain dicts / ORM objects onto Pydantic response models.

Populated incrementally:

* PR-1 (#286) — ``list_strategies`` + ``list_data_sources`` (static reads)
* PR-2 (#293) — ``get_bot`` / ``delete_bot`` / ``duplicate_bot`` (single-bot CRUD)
* PR-3 (#295) — ``list_bots_with_status`` (bot list with runtime + batch stats)
"""

from __future__ import annotations

import json
from typing import Any, Optional, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.bots import BotRuntimeStatus
from src.constants import MAX_BOTS_PER_USER
from src.data.data_source_registry import DATA_SOURCES, DEFAULT_SOURCES
from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User
from src.models.enums import CEX_EXCHANGES
from src.services.exceptions import BotNotFound, MaxBotsReached
from src.strategy import StrategyRegistry
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
