"""Unit tests for ``config_service`` read-handler functions (ARCH-C1 Phase 3 PR-1, #289).

These tests exercise the three handler-level service functions extracted
in this PR directly — no FastAPI stack, no HTTP client. A fresh in-memory
SQLite engine is built per test, following the pattern used by
``tests/unit/services/test_portfolio_service.py`` and
``tests/unit/services/test_trades_service.py``.

What's covered
--------------
* ``get_user_config_response`` — empty user (auto-creates ``UserConfig``),
  populated user with stored trading+strategy JSON + two exchange
  connections
* ``list_exchange_connections`` — empty user returns ``{connections: []}``,
  populated user returns projected ``ExchangeConnectionResponse`` items
* ``list_config_changes`` — empty user, populated user (ordering, total
  count, filter-by-entity-type, malformed JSON falls back to ``None``,
  pagination)

What's intentionally *not* covered here
---------------------------------------
* HTTP shape / response-model mapping — owned by the router-level
  integration tests.
* The shared helpers (``get_or_create_config``, ``conn_to_response``,
  ``ping_service``, …) — already exercised indirectly via the handlers
  and via the existing router tests.
"""

from __future__ import annotations

import json
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

from src.api.schemas.config import ExchangeConnectionResponse  # noqa: E402
from src.auth.password import hash_password  # noqa: E402
from src.models.database import (  # noqa: E402
    Base,
    ConfigChangeLog,
    ExchangeConnection,
    User,
    UserConfig,
)
from src.services import config_service  # noqa: E402


# ``conn_to_response`` only tests truthiness on the encrypted columns,
# so the tests don't need to round-trip through the real Fernet cipher.
# A plain sentinel avoids depending on a valid ``ENCRYPTION_KEY`` in CI.
_ENCRYPTED_SENTINEL = "fake-encrypted-payload"


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


@pytest_asyncio.fixture
async def user(session_factory) -> User:
    """A realistic user row; used as the owner of all seeded fixtures."""
    async with session_factory() as s:
        u = User(
            username="cfg_user",
            email="cfg@example.com",
            password_hash=hash_password("pw"),
            role="user",
            is_active=True,
            language="en",
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


# ---------------------------------------------------------------------------
# get_user_config_response
# ---------------------------------------------------------------------------


class TestGetUserConfigResponse:
    @pytest.mark.asyncio
    async def test_empty_user_creates_default_config(
        self, session_factory, user
    ):
        """A user with no ``UserConfig`` row gets one auto-created and the
        response reflects the empty baseline (no trading/strategy, no
        connections, default exchange ``bitget``)."""
        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            payload = await config_service.get_user_config_response(
                fresh_user, s
            )
            await s.commit()

        assert payload["trading"] is None
        assert payload["strategy"] is None
        assert payload["connections"] == []
        assert payload["exchange_type"] == "bitget"
        assert payload["api_keys_configured"] is False
        assert payload["demo_api_keys_configured"] is False

    @pytest.mark.asyncio
    async def test_populated_user_projects_stored_json_and_connections(
        self, session_factory, user
    ):
        """Stored ``trading_config`` / ``strategy_config`` JSON decodes back
        to dicts, and each ``ExchangeConnection`` row projects through
        ``conn_to_response`` into the ``connections`` list."""
        trading_json = {
            "max_trades_per_day": 5,
            "daily_loss_limit_percent": 5.0,
            "position_size_percent": 7.5,
            "leverage": 4,
            "take_profit_percent": 4.0,
            "stop_loss_percent": 1.5,
            "trading_pairs": ["BTCUSDT"],
            "demo_mode": True,
        }
        strategy_json = {
            "fear_greed_extreme_fear": 20,
            "fear_greed_extreme_greed": 80,
            "long_short_crowded_longs": 2.5,
            "long_short_crowded_shorts": 0.4,
            "funding_rate_high": 0.0005,
            "funding_rate_low": -0.0002,
            "high_confidence_min": 85,
            "low_confidence_min": 60,
        }

        async with session_factory() as s:
            cfg = UserConfig(
                user_id=user.id,
                exchange_type="bitget",
                trading_config=json.dumps(trading_json),
                strategy_config=json.dumps(strategy_json),
                api_key_encrypted=_ENCRYPTED_SENTINEL,
            )
            s.add(cfg)
            s.add(ExchangeConnection(
                user_id=user.id,
                exchange_type="bitget",
                api_key_encrypted=_ENCRYPTED_SENTINEL,
            ))
            s.add(ExchangeConnection(
                user_id=user.id,
                exchange_type="hyperliquid",
                demo_api_key_encrypted=_ENCRYPTED_SENTINEL,
            ))
            await s.commit()

        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            payload = await config_service.get_user_config_response(
                fresh_user, s
            )

        assert payload["trading"] == trading_json
        assert payload["strategy"] == strategy_json
        assert payload["exchange_type"] == "bitget"
        assert payload["api_keys_configured"] is True
        assert payload["demo_api_keys_configured"] is False
        assert len(payload["connections"]) == 2
        for conn in payload["connections"]:
            assert isinstance(conn, ExchangeConnectionResponse)
        exchanges = {c.exchange_type for c in payload["connections"]}
        assert exchanges == {"bitget", "hyperliquid"}


# ---------------------------------------------------------------------------
# list_exchange_connections
# ---------------------------------------------------------------------------


class TestListExchangeConnections:
    @pytest.mark.asyncio
    async def test_empty_user_returns_empty_list(
        self, session_factory, user
    ):
        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            result = await config_service.list_exchange_connections(
                fresh_user, s
            )

        assert result == {"connections": []}

    @pytest.mark.asyncio
    async def test_populated_user_projects_connection_rows(
        self, session_factory, user
    ):
        async with session_factory() as s:
            s.add(ExchangeConnection(
                user_id=user.id,
                exchange_type="bitget",
                api_key_encrypted=_ENCRYPTED_SENTINEL,
                demo_api_key_encrypted=_ENCRYPTED_SENTINEL,
            ))
            s.add(ExchangeConnection(
                user_id=user.id,
                exchange_type="hyperliquid",
                affiliate_uid="0xdeadbeef",
                affiliate_verified=True,
            ))
            await s.commit()

        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            result = await config_service.list_exchange_connections(
                fresh_user, s
            )

        assert "connections" in result
        assert len(result["connections"]) == 2
        for conn in result["connections"]:
            assert isinstance(conn, ExchangeConnectionResponse)

        by_type = {c.exchange_type: c for c in result["connections"]}
        assert by_type["bitget"].api_keys_configured is True
        assert by_type["bitget"].demo_api_keys_configured is True
        assert by_type["hyperliquid"].affiliate_uid == "0xdeadbeef"
        assert by_type["hyperliquid"].affiliate_verified is True


# ---------------------------------------------------------------------------
# list_config_changes
# ---------------------------------------------------------------------------


class TestListConfigChanges:
    @pytest.mark.asyncio
    async def test_empty_user_returns_empty_paginated_payload(
        self, session_factory, user
    ):
        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            result = await config_service.list_config_changes(
                fresh_user, s
            )

        assert result == {"items": [], "total": 0, "page": 1, "page_size": 20}

    @pytest.mark.asyncio
    async def test_items_sorted_by_created_at_desc(
        self, session_factory, user
    ):
        now = datetime.now(timezone.utc)
        async with session_factory() as s:
            for i in range(3):
                s.add(ConfigChangeLog(
                    user_id=user.id,
                    entity_type="bot_config",
                    entity_id=100 + i,
                    action="update",
                    changes=json.dumps({"field": {"old": i, "new": i + 1}}),
                    created_at=now - timedelta(hours=i),
                ))
            await s.commit()

        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            result = await config_service.list_config_changes(
                fresh_user, s
            )

        assert result["total"] == 3
        assert len(result["items"]) == 3
        # Newest first: entity_id 100 (now), 101 (−1h), 102 (−2h)
        assert [item["entity_id"] for item in result["items"]] == [100, 101, 102]
        assert result["items"][0]["changes"] == {"field": {"old": 0, "new": 1}}

    @pytest.mark.asyncio
    async def test_filter_by_entity_type(
        self, session_factory, user
    ):
        async with session_factory() as s:
            s.add(ConfigChangeLog(
                user_id=user.id,
                entity_type="bot_config",
                entity_id=1,
                action="create",
            ))
            s.add(ConfigChangeLog(
                user_id=user.id,
                entity_type="exchange_connection",
                entity_id=2,
                action="update",
            ))
            await s.commit()

        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            only_bots = await config_service.list_config_changes(
                fresh_user, s, entity_type="bot_config"
            )
            only_exchanges = await config_service.list_config_changes(
                fresh_user, s, entity_type="exchange_connection"
            )

        assert only_bots["total"] == 1
        assert only_bots["items"][0]["entity_type"] == "bot_config"
        assert only_exchanges["total"] == 1
        assert only_exchanges["items"][0]["entity_type"] == "exchange_connection"

    @pytest.mark.asyncio
    async def test_malformed_changes_blob_surfaces_as_none(
        self, session_factory, user
    ):
        """A row with a non-JSON ``changes`` value must not crash the handler;
        it surfaces as ``None`` per the pre-extract behavior."""
        async with session_factory() as s:
            s.add(ConfigChangeLog(
                user_id=user.id,
                entity_type="bot_config",
                entity_id=1,
                action="update",
                changes="this is not json {{",
            ))
            await s.commit()

        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            result = await config_service.list_config_changes(
                fresh_user, s
            )

        assert result["total"] == 1
        assert result["items"][0]["changes"] is None

    @pytest.mark.asyncio
    async def test_pagination_slices_the_dataset(
        self, session_factory, user
    ):
        now = datetime.now(timezone.utc)
        async with session_factory() as s:
            for i in range(5):
                s.add(ConfigChangeLog(
                    user_id=user.id,
                    entity_type="bot_config",
                    entity_id=10 + i,
                    action="update",
                    created_at=now - timedelta(minutes=i),
                ))
            await s.commit()

        async with session_factory() as s:
            fresh_user = await s.get(User, user.id)
            page_one = await config_service.list_config_changes(
                fresh_user, s, page=1, page_size=2
            )
            page_two = await config_service.list_config_changes(
                fresh_user, s, page=2, page_size=2
            )
            page_three = await config_service.list_config_changes(
                fresh_user, s, page=3, page_size=2
            )

        assert page_one["total"] == 5
        assert len(page_one["items"]) == 2
        assert len(page_two["items"]) == 2
        assert len(page_three["items"]) == 1
        # No overlap across pages
        seen = {item["entity_id"] for page in (page_one, page_two, page_three)
                for item in page["items"]}
        assert seen == {10, 11, 12, 13, 14}
