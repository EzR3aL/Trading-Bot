"""Unit tests for :mod:`src.api.dependencies.risk_state`.

Covers:
- IdempotencyCache: get/set, TTL expiry, eviction, clear
- _make_exchange_client_factory: missing conn raises, missing keys raises, success
- get_risk_state_manager: returns singleton, calling twice gives same instance
- set_risk_state_manager: overrides singleton (test helper)
- get_idempotency_cache / set_idempotency_cache: accessor/override
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "8P5tm7omM-7rNyRwE0VT2HQjZ08Q5Q-IgOyfTnf8_Ts="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

import src.api.dependencies.risk_state as risk_state_mod
from src.api.dependencies.risk_state import (
    IdempotencyCache,
    get_idempotency_cache,
    get_risk_state_manager,
    set_idempotency_cache,
    set_risk_state_manager,
)
from src.bot.risk_state_manager import RiskStateManager
from src.models.database import Base, ExchangeConnection, User
from src.auth.password import hash_password
from src.utils.encryption import encrypt_value


# ---------------------------------------------------------------------------
# IdempotencyCache tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_cache_get_returns_none_for_missing_key():
    cache = IdempotencyCache()
    result = await cache.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_idempotency_cache_set_and_get_returns_value():
    cache = IdempotencyCache()
    await cache.set("key1", {"status": "ok"})
    result = await cache.get("key1")
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_idempotency_cache_ttl_expiry():
    cache = IdempotencyCache(ttl_seconds=1)
    await cache.set("key1", "value")

    # Not expired yet
    result = await cache.get("key1")
    assert result == "value"

    # Simulate expiry by manipulating internal state
    cache._store["key1"] = (time.monotonic() - 2, "value")
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_idempotency_cache_evicts_expired_on_set():
    cache = IdempotencyCache(ttl_seconds=1)
    await cache.set("stale", "old")
    # Age the stale entry
    cache._store["stale"] = (time.monotonic() - 2, "old")

    await cache.set("fresh", "new")
    assert "stale" not in cache._store
    assert "fresh" in cache._store


@pytest.mark.asyncio
async def test_idempotency_cache_clear_empties_store():
    cache = IdempotencyCache()
    await cache.set("k1", "v1")
    await cache.set("k2", "v2")
    cache.clear()
    assert len(cache._store) == 0


@pytest.mark.asyncio
async def test_idempotency_cache_concurrent_access():
    """Concurrent get/set must not raise (Lock prevents race conditions)."""
    cache = IdempotencyCache()

    async def writer(i):
        await cache.set(f"key{i}", f"val{i}")

    async def reader(i):
        return await cache.get(f"key{i}")

    tasks = [writer(i) for i in range(20)] + [reader(i) for i in range(20)]
    await asyncio.gather(*tasks)  # must not raise


# ---------------------------------------------------------------------------
# _make_exchange_client_factory
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _factory():
        async with maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    return _factory


@pytest.mark.asyncio
async def test_exchange_client_factory_raises_when_no_connection(session_factory):
    factory = risk_state_mod._make_exchange_client_factory()
    with patch.object(risk_state_mod, "get_session", return_value=session_factory()):
        with pytest.raises(RuntimeError, match="No ExchangeConnection"):
            await factory(user_id=999, exchange="bitget", demo_mode=False)


@pytest.mark.asyncio
async def test_exchange_client_factory_raises_when_keys_missing(engine, session_factory):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user = User(
            username="u1", email="u1@t.com",
            password_hash=hash_password("x"), role="user", is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        conn = ExchangeConnection(
            user_id=user.id, exchange_type="bitget",
            api_key_encrypted=None,
            api_secret_encrypted=None,
        )
        session.add(conn)
        await session.commit()

    factory = risk_state_mod._make_exchange_client_factory()
    with patch.object(risk_state_mod, "get_session", return_value=session_factory()):
        with pytest.raises(RuntimeError, match="Missing API credentials"):
            await factory(user_id=user.id, exchange="bitget", demo_mode=False)


@pytest.mark.asyncio
async def test_exchange_client_factory_success(engine, session_factory):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user = User(
            username="u2", email="u2@t.com",
            password_hash=hash_password("x"), role="user", is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        conn = ExchangeConnection(
            user_id=user.id, exchange_type="bitget",
            api_key_encrypted=encrypt_value("mykey"),
            api_secret_encrypted=encrypt_value("mysecret"),
            passphrase_encrypted=encrypt_value("mypass"),
        )
        session.add(conn)
        await session.commit()

    factory = risk_state_mod._make_exchange_client_factory()
    mock_client = MagicMock()
    with patch.object(risk_state_mod, "get_session", return_value=session_factory()):
        with patch("src.api.dependencies.risk_state.create_exchange_client", return_value=mock_client):
            result = await factory(user_id=user.id, exchange="bitget", demo_mode=False)

    assert result is mock_client


# ---------------------------------------------------------------------------
# get_risk_state_manager / set_risk_state_manager
# ---------------------------------------------------------------------------


def test_get_risk_state_manager_returns_singleton():
    # Reset singleton first
    set_risk_state_manager(None)

    mgr1 = get_risk_state_manager()
    mgr2 = get_risk_state_manager()

    assert isinstance(mgr1, RiskStateManager)
    assert mgr1 is mgr2

    # Cleanup
    set_risk_state_manager(None)


def test_set_risk_state_manager_overrides_singleton():
    mock_mgr = MagicMock(spec=RiskStateManager)
    set_risk_state_manager(mock_mgr)

    result = get_risk_state_manager()
    assert result is mock_mgr

    # Cleanup
    set_risk_state_manager(None)


def test_set_risk_state_manager_none_triggers_recreation():
    set_risk_state_manager(None)
    mgr = get_risk_state_manager()
    assert isinstance(mgr, RiskStateManager)
    set_risk_state_manager(None)


# ---------------------------------------------------------------------------
# get_idempotency_cache / set_idempotency_cache
# ---------------------------------------------------------------------------


def test_get_idempotency_cache_returns_instance():
    cache = get_idempotency_cache()
    assert isinstance(cache, IdempotencyCache)


def test_set_idempotency_cache_overrides():
    new_cache = IdempotencyCache(ttl_seconds=999)
    old_cache = get_idempotency_cache()

    set_idempotency_cache(new_cache)
    assert get_idempotency_cache() is new_cache

    # Restore original
    set_idempotency_cache(old_cache)
