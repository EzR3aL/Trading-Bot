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

The static-read tests are pure (no DB). The CRUD + list tests use an
in-memory SQLite engine, following the same pattern as
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

from src.auth.password import hash_password  # noqa: E402
from src.models.database import Base, BotConfig, User  # noqa: E402
from src.services import bots_service  # noqa: E402
from src.services.exceptions import BotNotFound, MaxBotsReached  # noqa: E402


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
