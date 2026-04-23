"""Unit tests for ``bots_service`` (ARCH-C1 Phase 2b).

Covers the handlers extracted so far:

PR-1 (#286) — static reads
* ``list_strategies`` — returns the ``StrategyRegistry.list_available()`` catalog
* ``list_data_sources`` — returns ``{"sources": [...], "defaults": [...]}``

PR-2 (#293) — single-bot CRUD
* ``get_bot`` — single-bot read, raises ``BotNotFound`` if missing / foreign
* ``delete_bot`` — stop-if-running + delete, raises ``BotNotFound``
* ``duplicate_bot`` — clone with ``MaxBotsReached`` guard

PR-3 (#295) — list with runtime status
* ``list_bots_with_status`` — batch preloads HL/affiliate state + trade stats

PR-4 (#297) — write handlers
* ``create_bot`` — strategy/symbol validation + encryption + audit log
* ``update_bot`` — running guard + partial patch + audit log

The static-read tests are pure (no DB). The CRUD + list + write tests use
an in-memory SQLite engine, following the same pattern as
``test_trades_service.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Env bootstrapping must happen before any src imports.
os.environ.setdefault(
    "JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production",
)
os.environ.setdefault(
    "ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==",
)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from unittest.mock import AsyncMock  # noqa: E402

from src.api.schemas.bots import BotConfigCreate, BotConfigUpdate  # noqa: E402
from src.auth.password import hash_password  # noqa: E402
from src.models.database import Base, BotConfig, User  # noqa: E402
from src.services import bots_service  # noqa: E402
from src.services.exceptions import (  # noqa: E402
    BotIsRunning,
    BotNotFound,
    InvalidSymbols,
    MaxBotsReached,
    StrategyNotFound,
)


# ---------------------------------------------------------------------------
# Static-read tests (pure, no DB)
# ---------------------------------------------------------------------------


class TestListStrategies:
    def test_returns_a_non_empty_list(self) -> None:
        strategies = bots_service.list_strategies()

        assert isinstance(strategies, list)
        assert len(strategies) > 0

    def test_each_entry_has_expected_keys(self) -> None:
        strategies = bots_service.list_strategies()

        expected_keys = {"name", "description", "param_schema"}
        for strategy in strategies:
            assert expected_keys.issubset(strategy.keys()), (
                f"Missing keys in strategy entry: {strategy}"
            )

    def test_matches_strategy_registry_output(self) -> None:
        from src.strategy import StrategyRegistry

        assert bots_service.list_strategies() == StrategyRegistry.list_available()


class TestListDataSources:
    def test_returns_dict_with_sources_and_defaults(self) -> None:
        result = bots_service.list_data_sources()

        assert isinstance(result, dict)
        assert "sources" in result
        assert "defaults" in result
        assert isinstance(result["sources"], list)
        assert isinstance(result["defaults"], list)

    def test_sources_are_plain_dicts(self) -> None:
        result = bots_service.list_data_sources()

        assert len(result["sources"]) > 0
        for source in result["sources"]:
            assert isinstance(source, dict)
            assert "id" in source
            assert "name" in source

    def test_defaults_reference_existing_source_ids(self) -> None:
        result = bots_service.list_data_sources()

        source_ids = {src["id"] for src in result["sources"]}
        for default_id in result["defaults"]:
            assert default_id in source_ids, (
                f"Default source id '{default_id}' not in sources list"
            )


# ---------------------------------------------------------------------------
# CRUD test fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory SQLite engine per test (no cross-test contamination)."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    """An ``async_sessionmaker`` bound to the test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def user(session_factory) -> User:
    async with session_factory() as s:
        u = User(
            username="svc_bot_user",
            email="svc_bot@example.com",
            password_hash=hash_password("pw"),
            role="user",
            is_active=True,
            language="en",
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


@pytest_asyncio.fixture
async def other_user(session_factory) -> User:
    async with session_factory() as s:
        u = User(
            username="svc_bot_other",
            email="svc_bot_other@example.com",
            password_hash=hash_password("pw"),
            role="user",
            is_active=True,
            language="en",
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


def _make_bot(user_id: int, name: str = "TestBot") -> BotConfig:
    return BotConfig(
        user_id=user_id,
        name=name,
        description="unit-test bot",
        strategy_type="edge_indicator",
        exchange_type="bitget",
        mode="demo",
        trading_pairs='["BTCUSDT"]',
        leverage=3,
        position_size_percent=5.0,
        max_trades_per_day=1,
        take_profit_percent=2.0,
        stop_loss_percent=1.0,
        daily_loss_limit_percent=3.0,
        is_enabled=False,
    )


class _FakeOrchestrator:
    """Minimal orchestrator stub — tracks stop_bot calls for assertions."""

    def __init__(
        self,
        running_ids: set[int] | None = None,
        statuses: dict[int, dict] | None = None,
    ) -> None:
        self._running = running_ids or set()
        self._statuses = statuses or {}
        self.stopped: list[int] = []

    def is_running(self, bot_id: int) -> bool:
        return bot_id in self._running

    async def stop_bot(self, bot_id: int) -> None:
        self.stopped.append(bot_id)
        self._running.discard(bot_id)

    def get_bot_status(self, bot_id: int) -> dict | None:
        return self._statuses.get(bot_id)


# ---------------------------------------------------------------------------
# get_bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_bot_returns_row_when_owned(session_factory, user):
    async with session_factory() as s:
        bot = _make_bot(user.id, "Alpha")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    async with session_factory() as s:
        result = await bots_service.get_bot(s, user.id, bot_id)

    assert result.id == bot_id
    assert result.name == "Alpha"
    assert result.user_id == user.id


@pytest.mark.asyncio
async def test_get_bot_raises_when_missing(session_factory, user):
    async with session_factory() as s:
        with pytest.raises(BotNotFound):
            await bots_service.get_bot(s, user.id, 99999)


@pytest.mark.asyncio
async def test_get_bot_raises_when_owned_by_other_user(
    session_factory, user, other_user,
):
    """Foreign ownership collapses to BotNotFound (no tenant leak)."""
    async with session_factory() as s:
        bot = _make_bot(other_user.id, "ForeignBot")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    async with session_factory() as s:
        with pytest.raises(BotNotFound):
            await bots_service.get_bot(s, user.id, bot_id)


# ---------------------------------------------------------------------------
# delete_bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_bot_removes_row_and_returns_name(session_factory, user):
    async with session_factory() as s:
        bot = _make_bot(user.id, "ToDelete")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    orchestrator = _FakeOrchestrator()
    async with session_factory() as s:
        name = await bots_service.delete_bot(s, user.id, bot_id, orchestrator)
        await s.commit()

    assert name == "ToDelete"
    assert orchestrator.stopped == []  # not running → no stop_bot call

    async with session_factory() as s:
        with pytest.raises(BotNotFound):
            await bots_service.get_bot(s, user.id, bot_id)


@pytest.mark.asyncio
async def test_delete_bot_stops_if_running(session_factory, user):
    async with session_factory() as s:
        bot = _make_bot(user.id, "RunningBot")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    orchestrator = _FakeOrchestrator(running_ids={bot_id})
    async with session_factory() as s:
        await bots_service.delete_bot(s, user.id, bot_id, orchestrator)
        await s.commit()

    assert orchestrator.stopped == [bot_id]


@pytest.mark.asyncio
async def test_delete_bot_raises_when_missing(session_factory, user):
    orchestrator = _FakeOrchestrator()
    async with session_factory() as s:
        with pytest.raises(BotNotFound):
            await bots_service.delete_bot(s, user.id, 99999, orchestrator)


@pytest.mark.asyncio
async def test_delete_bot_raises_when_owned_by_other_user(
    session_factory, user, other_user,
):
    async with session_factory() as s:
        bot = _make_bot(other_user.id, "ForeignBot")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    orchestrator = _FakeOrchestrator()
    async with session_factory() as s:
        with pytest.raises(BotNotFound):
            await bots_service.delete_bot(s, user.id, bot_id, orchestrator)


# ---------------------------------------------------------------------------
# duplicate_bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_bot_creates_disabled_copy(session_factory, user):
    async with session_factory() as s:
        bot = _make_bot(user.id, "Original")
        bot.is_enabled = True  # original is on, copy should come out off
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    async with session_factory() as s:
        copy = await bots_service.duplicate_bot(s, user.id, bot_id)
        await s.commit()
        copy_id = copy.id
        copy_name = copy.name
        copy_enabled = copy.is_enabled

    assert copy_id != bot_id
    assert copy_name == "Original (Copy)"
    assert copy_enabled is False


@pytest.mark.asyncio
async def test_duplicate_bot_raises_when_missing(session_factory, user):
    async with session_factory() as s:
        with pytest.raises(BotNotFound):
            await bots_service.duplicate_bot(s, user.id, 99999)


@pytest.mark.asyncio
async def test_duplicate_bot_raises_on_max_bots(session_factory, user, monkeypatch):
    """With MAX_BOTS_PER_USER capped at 1, a second duplicate is rejected."""
    monkeypatch.setattr(bots_service, "MAX_BOTS_PER_USER", 1)

    async with session_factory() as s:
        bot = _make_bot(user.id, "OnlyOne")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    async with session_factory() as s:
        with pytest.raises(MaxBotsReached):
            await bots_service.duplicate_bot(s, user.id, bot_id)


# ---------------------------------------------------------------------------
# list_bots_with_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bots_with_status_empty(session_factory, user):
    """User with no bots → empty list (no crashes on empty bot_ids)."""
    orchestrator = _FakeOrchestrator()
    async with session_factory() as s:
        result = await bots_service.list_bots_with_status(s, user, orchestrator)

    assert result == []


@pytest.mark.asyncio
async def test_list_bots_with_status_returns_only_owned(
    session_factory, user, other_user,
):
    """Foreign bots never appear in the user's listing."""
    async with session_factory() as s:
        s.add(_make_bot(user.id, "Mine"))
        s.add(_make_bot(other_user.id, "Yours"))
        await s.commit()

    orchestrator = _FakeOrchestrator()
    async with session_factory() as s:
        result = await bots_service.list_bots_with_status(s, user, orchestrator)

    assert [b.name for b in result] == ["Mine"]
    assert result[0].exchange_type == "bitget"
    assert result[0].is_enabled is False
    # No runtime entry → idle for disabled bot
    assert result[0].status == "idle"


@pytest.mark.asyncio
async def test_list_bots_with_status_respects_demo_mode_filter(
    session_factory, user,
):
    """``demo_mode=True`` keeps demo/both bots only (live bot excluded)."""
    async with session_factory() as s:
        demo = _make_bot(user.id, "DemoBot")
        demo.mode = "demo"
        live = _make_bot(user.id, "LiveBot")
        live.mode = "live"
        both = _make_bot(user.id, "BothBot")
        both.mode = "both"
        s.add_all([demo, live, both])
        await s.commit()

    orchestrator = _FakeOrchestrator()

    async with session_factory() as s:
        demo_only = await bots_service.list_bots_with_status(
            s, user, orchestrator, demo_mode=True,
        )
    assert sorted(b.name for b in demo_only) == ["BothBot", "DemoBot"]

    async with session_factory() as s:
        live_only = await bots_service.list_bots_with_status(
            s, user, orchestrator, demo_mode=False,
        )
    assert sorted(b.name for b in live_only) == ["BothBot", "LiveBot"]


@pytest.mark.asyncio
async def test_list_bots_with_status_admin_bypasses_hl_gates(
    session_factory, user,
):
    """Admin role short-circuits HL/affiliate preloads to 'verified'."""
    user.role = "admin"
    async with session_factory() as s:
        bot = _make_bot(user.id, "HLBot")
        bot.exchange_type = "hyperliquid"
        s.add(bot)
        await s.commit()

    orchestrator = _FakeOrchestrator()
    async with session_factory() as s:
        # Re-attach the admin user under this session
        result = await bots_service.list_bots_with_status(s, user, orchestrator)

    assert len(result) == 1
    assert result[0].builder_fee_approved is True
    assert result[0].referral_verified is True


@pytest.mark.asyncio
async def test_list_bots_with_status_exposes_runtime_state(session_factory, user):
    """When orchestrator reports status, it overrides the config-derived default."""
    async with session_factory() as s:
        bot = _make_bot(user.id, "RunningBot")
        bot.is_enabled = True
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    orchestrator = _FakeOrchestrator(
        statuses={
            bot_id: {
                "status": "running",
                "trades_today": 3,
                "started_at": "2026-04-22T12:00:00Z",
                "last_analysis": "2026-04-22T12:05:00Z",
                "error_message": None,
            }
        }
    )

    async with session_factory() as s:
        result = await bots_service.list_bots_with_status(s, user, orchestrator)

    assert len(result) == 1
    assert result[0].status == "running"
    assert result[0].trades_today == 3
    assert result[0].started_at == "2026-04-22T12:00:00Z"


# ---------------------------------------------------------------------------
# create_bot
# ---------------------------------------------------------------------------


def _make_create_body(**overrides) -> BotConfigCreate:
    """Minimal valid ``BotConfigCreate`` body, overridable per-test."""
    data = {
        "name": "NewBot",
        "strategy_type": "edge_indicator",
        "exchange_type": "bitget",
        "mode": "demo",
        "trading_pairs": ["BTCUSDT"],
    }
    data.update(overrides)
    return BotConfigCreate(**data)


@pytest.mark.asyncio
async def test_create_bot_happy_path(session_factory, user, monkeypatch):
    """Validation passes, row is inserted disabled, name/strategy match the body."""
    monkeypatch.setattr(
        bots_service,
        "get_exchange_symbols",
        AsyncMock(return_value={"BTCUSDT"}),
    )

    body = _make_create_body()
    async with session_factory() as s:
        config = await bots_service.create_bot(s, user.id, body)
        await s.commit()
        new_id = config.id

    async with session_factory() as s:
        fetched = await bots_service.get_bot(s, user.id, new_id)

    assert fetched.name == "NewBot"
    assert fetched.strategy_type == "edge_indicator"
    assert fetched.is_enabled is False
    # trading_pairs is stored as JSON string
    import json as _json
    assert _json.loads(fetched.trading_pairs) == ["BTCUSDT"]


@pytest.mark.asyncio
async def test_create_bot_raises_strategy_not_found(
    session_factory, user, monkeypatch,
):
    monkeypatch.setattr(
        bots_service,
        "get_exchange_symbols",
        AsyncMock(return_value={"BTCUSDT"}),
    )
    body = _make_create_body(strategy_type="does_not_exist")

    async with session_factory() as s:
        with pytest.raises(StrategyNotFound) as excinfo:
            await bots_service.create_bot(s, user.id, body)
    assert excinfo.value.strategy_name == "does_not_exist"


@pytest.mark.asyncio
async def test_create_bot_raises_invalid_symbols(
    session_factory, user, monkeypatch,
):
    monkeypatch.setattr(
        bots_service,
        "get_exchange_symbols",
        AsyncMock(return_value={"ETHUSDT"}),  # no BTCUSDT
    )
    body = _make_create_body(trading_pairs=["BTCUSDT", "ETHUSDT"])

    async with session_factory() as s:
        with pytest.raises(InvalidSymbols) as excinfo:
            await bots_service.create_bot(s, user.id, body)
    assert excinfo.value.invalid_symbols == ["BTCUSDT"]
    assert excinfo.value.exchange == "bitget"
    assert excinfo.value.mode_label == "demo"


@pytest.mark.asyncio
async def test_create_bot_raises_max_bots(session_factory, user, monkeypatch):
    monkeypatch.setattr(bots_service, "MAX_BOTS_PER_USER", 1)
    monkeypatch.setattr(
        bots_service,
        "get_exchange_symbols",
        AsyncMock(return_value={"BTCUSDT"}),
    )
    # Pre-seed one bot so the count already equals the limit.
    async with session_factory() as s:
        s.add(_make_bot(user.id, "ExistingOne"))
        await s.commit()

    body = _make_create_body(name="SecondOne")
    async with session_factory() as s:
        with pytest.raises(MaxBotsReached):
            await bots_service.create_bot(s, user.id, body)


@pytest.mark.asyncio
async def test_create_bot_encrypts_webhook_and_telegram(
    session_factory, user, monkeypatch,
):
    """Discord webhook URL and Telegram token pass through encrypt_value."""
    monkeypatch.setattr(
        bots_service,
        "get_exchange_symbols",
        AsyncMock(return_value={"BTCUSDT"}),
    )
    # Replace real Fernet encryption with a deterministic tag so the test
    # doesn't depend on ENCRYPTION_KEY formatting.
    monkeypatch.setattr(bots_service, "encrypt_value", lambda v: f"ENC::{v}")

    body = _make_create_body(
        discord_webhook_url="https://discord.com/api/webhooks/1/abc",
        telegram_bot_token="123:secret",
        telegram_chat_id="42",
    )

    async with session_factory() as s:
        config = await bots_service.create_bot(s, user.id, body)
        await s.commit()
        new_id = config.id

    async with session_factory() as s:
        fetched = await bots_service.get_bot(s, user.id, new_id)

    assert fetched.discord_webhook_url == "ENC::https://discord.com/api/webhooks/1/abc"
    assert fetched.telegram_bot_token == "ENC::123:secret"
    assert fetched.telegram_chat_id == "ENC::42"


# ---------------------------------------------------------------------------
# update_bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_bot_applies_partial_patch(session_factory, user, monkeypatch):
    """Only fields present in the body are touched; others are preserved."""
    monkeypatch.setattr(
        bots_service,
        "get_exchange_symbols",
        AsyncMock(return_value={"BTCUSDT", "ETHUSDT"}),
    )
    async with session_factory() as s:
        bot = _make_bot(user.id, "BeforeUpdate")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    orchestrator = _FakeOrchestrator()
    body = BotConfigUpdate(name="AfterUpdate", leverage=7)

    async with session_factory() as s:
        config = await bots_service.update_bot(s, user.id, bot_id, body, orchestrator)
        await s.commit()
        new_name = config.name
        new_leverage = config.leverage
        old_lev_in_db = (await bots_service.get_bot(s, user.id, bot_id)).leverage

    assert new_name == "AfterUpdate"
    assert new_leverage == 7
    assert old_lev_in_db == 7


@pytest.mark.asyncio
async def test_update_bot_raises_bot_not_found(session_factory, user):
    orchestrator = _FakeOrchestrator()
    body = BotConfigUpdate(name="Whatever")

    async with session_factory() as s:
        with pytest.raises(BotNotFound):
            await bots_service.update_bot(s, user.id, 99999, body, orchestrator)


@pytest.mark.asyncio
async def test_update_bot_raises_when_running(session_factory, user):
    async with session_factory() as s:
        bot = _make_bot(user.id, "RunningBot")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    orchestrator = _FakeOrchestrator(running_ids={bot_id})
    body = BotConfigUpdate(name="CantEdit")

    async with session_factory() as s:
        with pytest.raises(BotIsRunning) as excinfo:
            await bots_service.update_bot(s, user.id, bot_id, body, orchestrator)
    assert excinfo.value.bot_id == bot_id


@pytest.mark.asyncio
async def test_update_bot_raises_invalid_symbols(session_factory, user, monkeypatch):
    monkeypatch.setattr(
        bots_service,
        "get_exchange_symbols",
        AsyncMock(return_value={"ETHUSDT"}),
    )
    async with session_factory() as s:
        bot = _make_bot(user.id, "Bot")
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    orchestrator = _FakeOrchestrator()
    body = BotConfigUpdate(trading_pairs=["NOSUCHUSDT"])

    async with session_factory() as s:
        with pytest.raises(InvalidSymbols) as excinfo:
            await bots_service.update_bot(s, user.id, bot_id, body, orchestrator)
    assert "NOSUCHUSDT" in excinfo.value.invalid_symbols


@pytest.mark.asyncio
async def test_update_bot_clears_webhook_on_empty_string(
    session_factory, user, monkeypatch,
):
    """An explicit empty-string for discord_webhook_url clears the stored value."""
    monkeypatch.setattr(
        bots_service,
        "get_exchange_symbols",
        AsyncMock(return_value={"BTCUSDT"}),
    )
    async with session_factory() as s:
        bot = _make_bot(user.id, "WithWebhook")
        bot.discord_webhook_url = "already-encrypted-blob"
        s.add(bot)
        await s.commit()
        await s.refresh(bot)
        bot_id = bot.id

    orchestrator = _FakeOrchestrator()
    body = BotConfigUpdate(discord_webhook_url="")

    async with session_factory() as s:
        config = await bots_service.update_bot(s, user.id, bot_id, body, orchestrator)
        await s.commit()
        after = config.discord_webhook_url

    assert after is None
