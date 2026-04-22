"""Unit tests for ``users_service`` (ARCH-C1 Phase 3 PR-2).

Exercises the two handlers extracted from the users / auth routers:

* ``get_profile`` — pure ``User`` → ``UserProfileResult`` transform.
* ``list_users`` — admin listing with batched exchange / bot / trade
  aggregates against an in-memory SQLite DB.

These tests run the service directly — no FastAPI stack, no HTTP
client — mirroring the pattern used in
``tests/unit/services/test_portfolio_service.py``.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
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
from src.models.database import (  # noqa: E402
    Base,
    BotConfig,
    ExchangeConnection,
    TradeRecord,
    User,
)
from src.services import users_service  # noqa: E402
from src.services.users_service import (  # noqa: E402
    AdminUserListItem,
    UserProfileResult,
)


# ---------------------------------------------------------------------------
# Fixtures
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


def _make_user(**overrides) -> User:
    """Build a ``User`` ORM instance with sensible defaults for tests.

    The ``email`` field has a UNIQUE constraint, so callers that seed
    multiple users in one test must pass an explicit ``email=`` per user
    (or ``email=None`` to rely on the nullable path).
    """
    username = overrides.get("username", "tester")
    defaults = dict(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("pw"),
        role="user",
        is_active=True,
        language="de",
        auth_provider="local",
    )
    defaults.update(overrides)
    return User(**defaults)


# ---------------------------------------------------------------------------
# get_profile
# ---------------------------------------------------------------------------


class TestGetProfile:
    """``get_profile`` is a pure transform — no DB interactions."""

    def test_returns_userprofileresult_with_expected_fields(self) -> None:
        user = _make_user(id=42, username="alice", email="alice@example.com",
                          role="admin", language="en", is_active=True)

        result = users_service.get_profile(user)

        assert isinstance(result, UserProfileResult)
        assert result.id == 42
        assert result.username == "alice"
        assert result.email == "alice@example.com"
        assert result.role == "admin"
        assert result.language == "en"
        assert result.is_active is True

    def test_preserves_null_email_and_language(self) -> None:
        """A user with NULL email / language must surface those as ``None``."""
        user = _make_user(id=1, username="bob", email=None, language=None)

        result = users_service.get_profile(user)

        assert result.email is None
        assert result.language is None

    def test_inactive_user_is_active_false(self) -> None:
        user = _make_user(id=1, username="deactivated", is_active=False)

        result = users_service.get_profile(user)

        assert result.is_active is False


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_empty_db_returns_empty_list(session_factory):
    """No users at all → empty list, no crashes on the batched queries."""
    async with session_factory() as s:
        result = await users_service.list_users(s)

    assert result == []


@pytest.mark.asyncio
async def test_list_users_excludes_soft_deleted(session_factory):
    """A row with ``is_deleted=True`` must be filtered out."""
    async with session_factory() as s:
        s.add_all([
            _make_user(username="alive", email="alive@example.com"),
            _make_user(
                username="ghost",
                email="ghost@example.com",
                is_deleted=True,
                deleted_at=datetime.now(timezone.utc),
            ),
        ])
        await s.commit()

    async with session_factory() as s:
        result = await users_service.list_users(s)

    assert len(result) == 1
    assert result[0].username == "alive"


@pytest.mark.asyncio
async def test_list_users_orders_by_id_ascending(session_factory):
    """Ordering must be stable and ascending on id so the admin panel is deterministic."""
    async with session_factory() as s:
        s.add_all([
            _make_user(username="u1"),
            _make_user(username="u2"),
            _make_user(username="u3"),
        ])
        await s.commit()

    async with session_factory() as s:
        result = await users_service.list_users(s)

    assert [item.username for item in result] == ["u1", "u2", "u3"]
    assert [item.id for item in result] == sorted(item.id for item in result)


@pytest.mark.asyncio
async def test_list_users_surfaces_supabase_auth_provider(session_factory):
    """``auth_provider`` is surfaced verbatim when set (supabase bridge users).

    The service also coalesces a missing value to ``"local"`` via
    ``u.auth_provider or "local"`` — the DB enforces NOT NULL so that
    branch only fires for in-memory user instances, but it guards
    against regressions if the column ever loses its server default.
    """
    async with session_factory() as s:
        s.add_all([
            _make_user(username="local_user"),
            _make_user(username="supabase_user", auth_provider="supabase"),
        ])
        await s.commit()

    async with session_factory() as s:
        result = await users_service.list_users(s)

    provider_by_username = {item.username: item.auth_provider for item in result}
    assert provider_by_username == {
        "local_user": "local",
        "supabase_user": "supabase",
    }


@pytest.mark.asyncio
async def test_list_users_aggregates_exchanges_bots_and_trades(session_factory):
    """Full happy path: one user has two exchange connections, two enabled
    bots (one disabled — not counted), and three trade records."""
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        u = _make_user(
            username="aggregator",
            email="agg@example.com",
            last_login_at=now - timedelta(hours=2),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)

        # Note: ExchangeConnection has a unique constraint on
        # (user_id, exchange_type) so there is naturally at most one
        # row per (user, exchange). The service still runs the query
        # through distinct() as a belt-and-braces guard.
        s.add_all([
            ExchangeConnection(user_id=u.id, exchange_type="bitget"),
            ExchangeConnection(user_id=u.id, exchange_type="hyperliquid"),
        ])

        s.add_all([
            BotConfig(
                user_id=u.id,
                name="bot-a",
                strategy_type="edge_indicator",
                exchange_type="bitget",
                is_enabled=True,
            ),
            BotConfig(
                user_id=u.id,
                name="bot-b",
                strategy_type="edge_indicator",
                exchange_type="bitget",
                is_enabled=True,
            ),
            # Disabled bot — must NOT be counted.
            BotConfig(
                user_id=u.id,
                name="bot-c",
                strategy_type="edge_indicator",
                exchange_type="bitget",
                is_enabled=False,
            ),
        ])

        s.add_all([
            TradeRecord(
                user_id=u.id,
                symbol="BTCUSDT",
                side="long",
                size=0.01,
                entry_price=95000.0,
                leverage=4,
                confidence=70,
                reason="t1",
                order_id="trade_1",
                status="closed",
                exchange="bitget",
                entry_time=now - timedelta(days=3),
            ),
            TradeRecord(
                user_id=u.id,
                symbol="ETHUSDT",
                side="short",
                size=0.1,
                entry_price=3500.0,
                leverage=4,
                confidence=65,
                reason="t2",
                order_id="trade_2",
                status="closed",
                exchange="bitget",
                entry_time=now - timedelta(days=2),
            ),
            TradeRecord(
                user_id=u.id,
                symbol="SOLUSDT",
                side="long",
                size=1.0,
                entry_price=150.0,
                leverage=4,
                confidence=60,
                reason="t3",
                order_id="trade_3",
                status="open",
                exchange="hyperliquid",
                entry_time=now - timedelta(days=1),
            ),
        ])
        await s.commit()

    async with session_factory() as s:
        result = await users_service.list_users(s)

    assert len(result) == 1
    item = result[0]
    assert isinstance(item, AdminUserListItem)
    assert item.username == "aggregator"
    assert item.email == "agg@example.com"
    assert set(item.exchanges) == {"bitget", "hyperliquid"}
    assert item.active_bots == 2  # disabled bot excluded
    assert item.total_trades == 3  # all trades counted (open + closed)
    # last_login_at / created_at are ISO-8601 strings (not datetime objects)
    assert item.last_login_at is not None
    assert "T" in item.last_login_at
    assert item.created_at is not None


@pytest.mark.asyncio
async def test_list_users_zero_defaults_for_user_with_no_relations(session_factory):
    """A user with no exchanges / bots / trades gets the zero-shaped defaults."""
    async with session_factory() as s:
        s.add(_make_user(username="lonely", email="lonely@example.com"))
        await s.commit()

    async with session_factory() as s:
        result = await users_service.list_users(s)

    assert len(result) == 1
    item = result[0]
    assert item.exchanges == []
    assert item.active_bots == 0
    assert item.total_trades == 0
    assert item.last_login_at is None
