"""Bot management service (ARCH-C1 Phase 2b).

FastAPI-free business logic for ``/api/bots`` handlers. The router is a
thin HTTP adapter: it parses query params, calls the service, and maps
the returned plain dicts / ORM objects onto Pydantic response models.

Populated incrementally:

* PR-1 (#286) — ``list_strategies`` + ``list_data_sources`` (static reads)
* PR-2 (#293) — ``get_bot`` / ``delete_bot`` / ``duplicate_bot`` (single-bot CRUD)
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import MAX_BOTS_PER_USER
from src.data.data_source_registry import DATA_SOURCES, DEFAULT_SOURCES
from src.models.database import BotConfig
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
