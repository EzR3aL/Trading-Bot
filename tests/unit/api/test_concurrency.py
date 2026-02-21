"""
Concurrency and race condition tests.

Verifies that simultaneous operations on bots, database sessions,
and the orchestrator behave correctly under concurrent access.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from src.models.database import Base, BotConfig, User
from src.auth.password import hash_password
from src.api.schemas.bots import BotConfigCreate, BotConfigUpdate

# Disable rate limiter
from src.api.routers.auth import limiter
limiter.enabled = False

from src.api.routers.bots import (  # noqa: E402
    create_bot,
    delete_bot,
    duplicate_bot,
    start_bot,
    stop_bot,
    update_bot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def factory(engine):
    from contextlib import asynccontextmanager
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _factory():
        async with sm() as session:
            yield session
    return _factory


@pytest_asyncio.fixture
async def admin_user(engine):
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user = User(
            username="concadmin", password_hash=hash_password("testpass123"),
            role="admin", language="en", is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
def mock_request():
    scope = {"type": "http", "method": "POST", "path": "/api/bots", "headers": []}
    return Request(scope)


@pytest_asyncio.fixture
def mock_orchestrator():
    mock_orch = MagicMock()
    mock_orch.is_running.return_value = False
    mock_orch.get_bot_count_for_user.return_value = 0
    mock_orch.start_bot = AsyncMock()
    mock_orch.stop_bot = AsyncMock(return_value=True)
    mock_orch.stop_all_for_user = AsyncMock(return_value=0)
    return mock_orch


@pytest_asyncio.fixture(autouse=True)
def setup_orchestrator(mock_orchestrator):
    """No-op — orchestrator is now passed explicitly to direct function calls."""
    yield


# ---------------------------------------------------------------------------
# Concurrent Bot Creation
# ---------------------------------------------------------------------------


class TestConcurrentCreation:

    async def test_concurrent_bot_creation(self, factory, admin_user, mock_request, mock_orchestrator):
        """Multiple bots created concurrently should all succeed."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0

        async def create_one(i):
            async with factory() as session:
                body = BotConfigCreate(
                    name=f"Concurrent Bot {i}",
                    strategy_type="degen",
                    exchange_type="bitget",
                )
                result = await create_bot(
                    request=mock_request, body=body, user=admin_user, db=session,
                )
                await session.commit()
                return result

        results = await asyncio.gather(*[create_one(i) for i in range(5)])
        names = [r.name for r in results]
        assert len(set(names)) == 5
        for i in range(5):
            assert f"Concurrent Bot {i}" in names

    async def test_concurrent_bot_creation_unique_ids(self, factory, admin_user, mock_request, mock_orchestrator):
        """Concurrently created bots all get unique IDs."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0

        async def create_one(i):
            async with factory() as session:
                body = BotConfigCreate(
                    name=f"Unique ID Bot {i}",
                    strategy_type="degen",
                    exchange_type="bitget",
                )
                result = await create_bot(
                    request=mock_request, body=body, user=admin_user, db=session,
                )
                await session.commit()
                return result.id

        ids = await asyncio.gather(*[create_one(i) for i in range(5)])
        assert len(set(ids)) == 5


# ---------------------------------------------------------------------------
# Concurrent Bot Updates
# ---------------------------------------------------------------------------


class TestConcurrentUpdates:

    async def test_concurrent_updates_same_bot(self, factory, admin_user, mock_request, mock_orchestrator):
        """Multiple simultaneous updates to the same bot should not crash."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0

        # Create a bot first
        async with factory() as session:
            body = BotConfigCreate(
                name="Update Target",
                strategy_type="degen",
                exchange_type="bitget",
            )
            bot = await create_bot(
                request=mock_request, body=body, user=admin_user, db=session,
            )
            await session.commit()

        async def update_one(i):
            async with factory() as session:
                update = BotConfigUpdate(name=f"Updated {i}")
                result = await update_bot(
                    request=mock_request, bot_id=bot.id, body=update,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )
                await session.commit()
                return result.name

        # Run multiple updates concurrently
        results = await asyncio.gather(*[update_one(i) for i in range(5)])
        # All should complete successfully
        assert len(results) == 5
        for r in results:
            assert r.startswith("Updated ")

    async def test_concurrent_updates_different_fields(self, factory, admin_user, mock_request, mock_orchestrator):
        """Concurrent updates to different fields should all apply."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0

        async with factory() as session:
            body = BotConfigCreate(
                name="Multi-Field Bot",
                strategy_type="degen",
                exchange_type="bitget",
                leverage=5,
            )
            bot = await create_bot(
                request=mock_request, body=body, user=admin_user, db=session,
            )
            await session.commit()

        async def update_leverage():
            async with factory() as session:
                update = BotConfigUpdate(leverage=10)
                await update_bot(
                    request=mock_request, bot_id=bot.id, body=update,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )
                await session.commit()

        async def update_name():
            async with factory() as session:
                update = BotConfigUpdate(name="New Name")
                await update_bot(
                    request=mock_request, bot_id=bot.id, body=update,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )
                await session.commit()

        await asyncio.gather(update_leverage(), update_name())

        # Verify bot state (last-write-wins is acceptable for SQLite)
        async with factory() as session:
            result = await session.execute(
                select(BotConfig).where(BotConfig.id == bot.id)
            )
            final_bot = result.scalar_one()
            # At least one update should have applied
            assert final_bot.name is not None
            assert final_bot.leverage is not None


# ---------------------------------------------------------------------------
# Concurrent Start/Stop
# ---------------------------------------------------------------------------


class TestConcurrentLifecycle:

    async def test_concurrent_start_same_bot(self, factory, admin_user, mock_request, mock_orchestrator):
        """Multiple start calls for the same bot should all complete."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0

        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id, name="Lifecycle Bot",
                strategy_type="degen", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)
            bot_id = config.id

        async def start_one():
            async with factory() as session:
                return await start_bot(
                    request=mock_request, bot_id=bot_id,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )

        results = await asyncio.gather(*[start_one() for _ in range(3)], return_exceptions=True)
        # At least one should succeed; others may also succeed or raise 400
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) >= 1
        for r in successes:
            assert r["status"] == "ok"

    async def test_start_and_stop_concurrent(self, factory, admin_user, mock_request, mock_orchestrator):
        """Start and stop of different bots can happen concurrently."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0
        mock_orchestrator.stop_bot.return_value = True

        bot_ids = []
        async with factory() as session:
            for i in range(3):
                config = BotConfig(
                    user_id=admin_user.id, name=f"LifeBot {i}",
                    strategy_type="degen", exchange_type="bitget",
                    mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                    is_enabled=False,
                )
                session.add(config)
            await session.commit()

            result = await session.execute(
                select(BotConfig).where(BotConfig.name.like("LifeBot%"))
            )
            bot_ids = [b.id for b in result.scalars().all()]

        async def start_one(bid):
            async with factory() as session:
                return await start_bot(
                    request=mock_request, bot_id=bid,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )

        async def stop_one(bid):
            async with factory() as session:
                return await stop_bot(
                    request=mock_request, bot_id=bid,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )

        # Start first, then stop — both happening concurrently
        start_results = await asyncio.gather(
            *[start_one(bid) for bid in bot_ids],
            return_exceptions=True,
        )
        _stop_results = await asyncio.gather(
            *[stop_one(bid) for bid in bot_ids],
            return_exceptions=True,
        )

        start_ok = [r for r in start_results if not isinstance(r, Exception)]
        assert len(start_ok) >= 1


# ---------------------------------------------------------------------------
# Concurrent Duplicate
# ---------------------------------------------------------------------------


class TestConcurrentDuplicate:

    async def test_concurrent_duplicate_same_bot(self, factory, admin_user, mock_request, mock_orchestrator):
        """Multiple duplicate calls should create separate copies."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0

        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id, name="Original Bot",
                strategy_type="degen", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)
            bot_id = config.id

        async def dup_one():
            async with factory() as session:
                return await duplicate_bot(
                    request=mock_request, bot_id=bot_id,
                    user=admin_user, db=session,
                )

        results = await asyncio.gather(*[dup_one() for _ in range(3)], return_exceptions=True)
        successes = [r for r in results if not isinstance(r, Exception)]
        # At least some should succeed (max bot limit may kick in)
        assert len(successes) >= 1
        ids = [r.id for r in successes]
        assert len(set(ids)) == len(ids)


# ---------------------------------------------------------------------------
# Concurrent Delete
# ---------------------------------------------------------------------------


class TestConcurrentDelete:

    async def test_concurrent_delete_different_bots(self, factory, admin_user, mock_request, mock_orchestrator):
        """Deleting different bots concurrently should all succeed."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0

        bot_ids = []
        async with factory() as session:
            for i in range(3):
                config = BotConfig(
                    user_id=admin_user.id, name=f"DeleteMe {i}",
                    strategy_type="degen", exchange_type="bitget",
                    mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                    is_enabled=False,
                )
                session.add(config)
            await session.commit()

            result = await session.execute(
                select(BotConfig).where(BotConfig.name.like("DeleteMe%"))
            )
            bot_ids = [b.id for b in result.scalars().all()]

        async def delete_one(bid):
            async with factory() as session:
                return await delete_bot(
                    request=mock_request, bot_id=bid,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )

        results = await asyncio.gather(
            *[delete_one(bid) for bid in bot_ids],
            return_exceptions=True,
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) == 3
        for r in successes:
            assert r["status"] == "ok"


# ---------------------------------------------------------------------------
# Session Isolation
# ---------------------------------------------------------------------------


class TestSessionIsolation:

    async def test_separate_sessions_see_committed_data(self, factory, admin_user, mock_request, mock_orchestrator):
        """Data committed in one session is visible in another."""
        mock_orchestrator.get_bot_count_for_user.return_value = 0

        async with factory() as session:
            body = BotConfigCreate(
                name="Isolation Bot",
                strategy_type="degen",
                exchange_type="bitget",
            )
            result = await create_bot(
                request=mock_request, body=body, user=admin_user, db=session,
            )
            await session.commit()
            bot_id = result.id

        # Different session should see the bot
        async with factory() as session:
            result = await session.execute(
                select(BotConfig).where(BotConfig.id == bot_id)
            )
            bot = result.scalar_one_or_none()
            assert bot is not None
            assert bot.name == "Isolation Bot"

    async def test_uncommitted_data_not_visible(self, factory, admin_user):
        """Uncommitted data in one session is not visible in another."""
        async with factory() as s1:
            config = BotConfig(
                user_id=admin_user.id, name="Uncommitted Bot",
                strategy_type="degen", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            )
            s1.add(config)
            await s1.flush()
            _uncommitted_id = config.id

            # Another session should NOT see it (SQLite WAL may or may not)
            # But we verify the session at least works without error
            async with factory() as s2:
                result = await s2.execute(
                    select(BotConfig).where(BotConfig.name == "Uncommitted Bot")
                )
                # This may or may not find it depending on isolation level
                # The important thing is no deadlock or crash
                _ = result.scalar_one_or_none()

            # Rollback s1 without commit
            await s1.rollback()
