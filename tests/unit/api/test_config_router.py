"""
Unit tests for the config router (src/api/routers/config.py).

Tests endpoint functions directly with mocked database sessions and
dependencies. Covers user config CRUD, exchange connections,
Hyperliquid builder/referral, affiliate UID management, and admin endpoints.
"""

import os
import sys
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Generate a valid Fernet key for tests
from cryptography.fernet import Fernet as _Fernet
_TEST_FERNET_KEY = _Fernet.generate_key().decode()
os.environ["ENCRYPTION_KEY"] = _TEST_FERNET_KEY

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from src.models.database import (  # noqa: E402
    Base,
    ExchangeConnection,
    User,
)
from src.auth.password import hash_password  # noqa: E402
from src.auth.jwt_handler import create_access_token  # noqa: E402
from src.errors import (  # noqa: E402
    ERR_NO_DEMO_API_KEYS,
    ERR_NO_HL_CONNECTION_PLAIN,
    ERR_NO_LIVE_API_KEYS,
)

# Reset Fernet singleton so it uses our test key
import src.utils.encryption as _enc_mod  # noqa: E402
_enc_mod._fernet = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


@pytest.fixture
def mock_orchestrator():
    orch = MagicMock()
    orch.get_bot_status = MagicMock(return_value=None)
    orch.is_running = MagicMock(return_value=False)
    orch.start_bot = AsyncMock(return_value=True)
    orch.stop_bot = AsyncMock(return_value=True)
    orch.restart_bot = AsyncMock(return_value=True)
    orch.stop_all_for_user = AsyncMock(return_value=0)
    return orch


@pytest_asyncio.fixture
async def app(test_engine, mock_orchestrator):
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Register test strategy (needed if bots router is included)
    from src.strategy.base import BaseStrategy, StrategyRegistry, TradeSignal

    if "test_strategy" not in StrategyRegistry._strategies:
        class TestStrategy(BaseStrategy):
            async def generate_signal(self, symbol: str) -> TradeSignal:
                raise NotImplementedError

            async def should_trade(self, signal) -> tuple:
                return False, "Test strategy never trades"

            @classmethod
            def get_param_schema(cls) -> dict:
                return {"test_param": {"type": "int", "default": 42}}

            @classmethod
            def get_description(cls) -> str:
                return "Test strategy"

        StrategyRegistry.register("test_strategy", TestStrategy)

    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import auth, bots, config, status, users
    from src.models.session import get_db

    limiter.enabled = False

    test_app = FastAPI(title="Test Config API")
    test_app.state.limiter = limiter
    test_app.state.orchestrator = mock_orchestrator
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    test_app.include_router(auth.router)
    test_app.include_router(status.router)
    test_app.include_router(config.router)
    test_app.include_router(bots.router)
    test_app.include_router(users.router)

    test_app.dependency_overrides[get_db] = override_get_db

    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_user(test_engine) -> User:
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        user = User(
            username="adminuser",
            email="admin@test.com",
            password_hash=hash_password("testpassword123"),
            role="admin",
            is_active=True,
            language="en",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def regular_user(test_engine) -> User:
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        user = User(
            username="regularuser",
            email="regular@test.com",
            password_hash=hash_password("testpassword123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def admin_headers(admin_user) -> dict:
    token_data = {"sub": str(admin_user.id), "role": admin_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def user_headers(regular_user) -> dict:
    token_data = {"sub": str(regular_user.id), "role": regular_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def exchange_conn_bitget(test_engine, regular_user) -> ExchangeConnection:
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    from src.utils.encryption import encrypt_value

    async with factory() as session:
        conn = ExchangeConnection(
            user_id=regular_user.id,
            exchange_type="bitget",
            api_key_encrypted=encrypt_value("test-api-key"),
            api_secret_encrypted=encrypt_value("test-api-secret"),
            passphrase_encrypted=encrypt_value("test-passphrase"),
        )
        session.add(conn)
        await session.commit()
        await session.refresh(conn)
        return conn


@pytest_asyncio.fixture
async def exchange_conn_hl(test_engine, regular_user) -> ExchangeConnection:
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    from src.utils.encryption import encrypt_value

    async with factory() as session:
        conn = ExchangeConnection(
            user_id=regular_user.id,
            exchange_type="hyperliquid",
            api_key_encrypted=encrypt_value("0x" + "a" * 40),
            api_secret_encrypted=encrypt_value("b" * 64),
        )
        session.add(conn)
        await session.commit()
        await session.refresh(conn)
        return conn


VALID_TRADING_CONFIG = {
    "leverage": 4,
    "position_size_percent": 7.5,
    "max_trades_per_day": 3,
    "take_profit_percent": 4.0,
    "stop_loss_percent": 1.5,
    "daily_loss_limit_percent": 5.0,
    "trading_pairs": ["BTCUSDT"],
    "demo_mode": True,
}

VALID_STRATEGY_CONFIG = {
    "fear_greed_extreme_fear": 20,
    "fear_greed_extreme_greed": 80,
    "long_short_crowded_longs": 2.5,
    "long_short_crowded_shorts": 0.4,
    "funding_rate_high": 0.0005,
    "funding_rate_low": -0.0002,
    "high_confidence_min": 85,
    "low_confidence_min": 60,
}


# ---------------------------------------------------------------------------
# Helper: _conn_to_response
# ---------------------------------------------------------------------------


class TestConnToResponse:

    def test_conn_to_response_basic(self):
        from src.api.routers.config import _conn_to_response

        conn = MagicMock()
        conn.exchange_type = "bitget"
        conn.api_key_encrypted = "encrypted_key"
        conn.demo_api_key_encrypted = None
        conn.affiliate_uid = None
        conn.affiliate_verified = None

        result = _conn_to_response(conn)
        assert result.exchange_type == "bitget"
        assert result.api_keys_configured is True
        assert result.demo_api_keys_configured is False
        assert result.affiliate_uid is None

    def test_conn_to_response_with_affiliate(self):
        from src.api.routers.config import _conn_to_response

        conn = MagicMock()
        conn.exchange_type = "bitget"
        conn.api_key_encrypted = None
        conn.demo_api_key_encrypted = "demo_key"
        conn.affiliate_uid = "12345"
        conn.affiliate_verified = True

        result = _conn_to_response(conn)
        assert result.api_keys_configured is False
        assert result.demo_api_keys_configured is True
        assert result.affiliate_uid == "12345"
        assert result.affiliate_verified is True

    def test_conn_to_response_no_keys(self):
        from src.api.routers.config import _conn_to_response

        conn = MagicMock()
        conn.exchange_type = "weex"
        conn.api_key_encrypted = None
        conn.demo_api_key_encrypted = None
        conn.affiliate_uid = None
        conn.affiliate_verified = None

        result = _conn_to_response(conn)
        assert result.api_keys_configured is False
        assert result.demo_api_keys_configured is False


# ---------------------------------------------------------------------------
# Helper: _get_or_create_config
# ---------------------------------------------------------------------------


class TestGetOrCreateConfig:

    async def test_creates_default_config(self, client, user_headers, regular_user):
        resp = await client.get("/api/config", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["exchange_type"] == "bitget"
        assert data["api_keys_configured"] is False

    async def test_returns_existing_config(self, client, user_headers, regular_user):
        # First call creates
        resp1 = await client.get("/api/config", headers=user_headers)
        assert resp1.status_code == 200

        # Second call returns existing
        resp2 = await client.get("/api/config", headers=user_headers)
        assert resp2.status_code == 200
        assert resp2.json()["exchange_type"] == "bitget"


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------


class TestGetConfig:

    async def test_get_config_success(self, client, user_headers, regular_user):
        resp = await client.get("/api/config", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "exchange_type" in data
        assert "connections" in data
        assert "trading" in data
        assert "strategy" in data

    async def test_get_config_requires_auth(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code == 401

    async def test_get_config_with_trading_config(self, client, user_headers, regular_user):
        # Set trading config first
        await client.put(
            "/api/config/trading",
            json=VALID_TRADING_CONFIG,
            headers=user_headers,
        )
        resp = await client.get("/api/config", headers=user_headers)
        assert resp.status_code == 200
        trading = resp.json()["trading"]
        assert trading is not None
        assert trading["leverage"] == 4

    async def test_get_config_with_strategy_config(self, client, user_headers, regular_user):
        await client.put(
            "/api/config/strategy",
            json=VALID_STRATEGY_CONFIG,
            headers=user_headers,
        )
        resp = await client.get("/api/config", headers=user_headers)
        assert resp.status_code == 200
        strategy = resp.json()["strategy"]
        assert strategy is not None
        assert strategy["fear_greed_extreme_fear"] == 20

    async def test_get_config_includes_connections(self, client, user_headers, regular_user, exchange_conn_bitget):
        resp = await client.get("/api/config", headers=user_headers)
        assert resp.status_code == 200
        conns = resp.json()["connections"]
        assert len(conns) >= 1
        assert any(c["exchange_type"] == "bitget" for c in conns)


# ---------------------------------------------------------------------------
# PUT /api/config/trading
# ---------------------------------------------------------------------------


class TestUpdateTradingConfig:

    async def test_update_trading_config_success(self, client, user_headers, regular_user):
        resp = await client.put(
            "/api/config/trading",
            json=VALID_TRADING_CONFIG,
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_trading_config_requires_auth(self, client):
        resp = await client.put(
            "/api/config/trading",
            json=VALID_TRADING_CONFIG,
        )
        assert resp.status_code == 401

    async def test_update_trading_leverage_too_high(self, client, user_headers, regular_user):
        bad = {**VALID_TRADING_CONFIG, "leverage": 50}
        resp = await client.put(
            "/api/config/trading",
            json=bad,
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_update_trading_leverage_zero(self, client, user_headers, regular_user):
        bad = {**VALID_TRADING_CONFIG, "leverage": 0}
        resp = await client.put(
            "/api/config/trading",
            json=bad,
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_update_trading_position_size_too_high(self, client, user_headers, regular_user):
        bad = {**VALID_TRADING_CONFIG, "position_size_percent": 30.0}
        resp = await client.put(
            "/api/config/trading",
            json=bad,
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_update_trading_stop_loss_too_high(self, client, user_headers, regular_user):
        bad = {**VALID_TRADING_CONFIG, "stop_loss_percent": 15.0}
        resp = await client.put(
            "/api/config/trading",
            json=bad,
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_update_trading_take_profit_too_high(self, client, user_headers, regular_user):
        bad = {**VALID_TRADING_CONFIG, "take_profit_percent": 25.0}
        resp = await client.put(
            "/api/config/trading",
            json=bad,
            headers=user_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/config/strategy
# ---------------------------------------------------------------------------


class TestUpdateStrategyConfig:

    async def test_update_strategy_config_success(self, client, user_headers, regular_user):
        resp = await client.put(
            "/api/config/strategy",
            json=VALID_STRATEGY_CONFIG,
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_strategy_config_requires_auth(self, client):
        resp = await client.put(
            "/api/config/strategy",
            json=VALID_STRATEGY_CONFIG,
        )
        assert resp.status_code == 401

    async def test_update_strategy_fear_greed_out_of_range(self, client, user_headers, regular_user):
        bad = {**VALID_STRATEGY_CONFIG, "fear_greed_extreme_fear": 60}
        resp = await client.put(
            "/api/config/strategy",
            json=bad,
            headers=user_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Exchange Connection CRUD
# ---------------------------------------------------------------------------


class TestExchangeConnections:

    async def test_get_exchange_connections(self, client, user_headers, regular_user, exchange_conn_bitget):
        resp = await client.get(
            "/api/config/exchange-connections", headers=user_headers
        )
        assert resp.status_code == 200
        conns = resp.json()["connections"]
        assert len(conns) >= 1
        assert any(c["exchange_type"] == "bitget" for c in conns)

    async def test_get_exchange_connections_empty(self, client, user_headers, regular_user):
        resp = await client.get(
            "/api/config/exchange-connections", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["connections"] == []

    async def test_upsert_exchange_connection_bitget(self, client, user_headers, regular_user):
        body = {
            "api_key": "new-key",
            "api_secret": "new-secret",
            "passphrase": "new-pass",
        }
        resp = await client.put(
            "/api/config/exchange-connections/bitget",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_upsert_exchange_connection_weex(self, client, user_headers, regular_user):
        body = {
            "api_key": "weex-key",
            "api_secret": "weex-secret",
        }
        resp = await client.put(
            "/api/config/exchange-connections/weex",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 200

    async def test_upsert_exchange_connection_hl_valid(self, client, user_headers, regular_user):
        body = {
            "api_key": "0x" + "a" * 40,
            "api_secret": "b" * 64,
        }
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 200

    async def test_upsert_exchange_connection_hl_invalid_address(self, client, user_headers, regular_user):
        body = {
            "api_key": "not-a-valid-address",
            "api_secret": "b" * 64,
        }
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 400
        assert "Ethereum" in resp.json()["detail"]

    async def test_upsert_exchange_connection_hl_invalid_key(self, client, user_headers, regular_user):
        body = {
            "api_key": "0x" + "a" * 40,
            "api_secret": "not-hex",
        }
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 400
        assert "Hex" in resp.json()["detail"]

    async def test_upsert_exchange_connection_invalid_exchange(self, client, user_headers, regular_user):
        body = {"api_key": "key", "api_secret": "secret"}
        resp = await client.put(
            "/api/config/exchange-connections/invalid",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_upsert_updates_existing(self, client, user_headers, regular_user, exchange_conn_bitget):
        body = {"api_key": "updated-key", "api_secret": "updated-secret"}
        resp = await client.put(
            "/api/config/exchange-connections/bitget",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 200

    async def test_delete_exchange_connection(self, client, user_headers, regular_user, exchange_conn_bitget):
        resp = await client.delete(
            "/api/config/exchange-connections/bitget",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_delete_exchange_connection_not_found(self, client, user_headers, regular_user):
        resp = await client.delete(
            "/api/config/exchange-connections/bitget",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_delete_exchange_connection_invalid_type(self, client, user_headers, regular_user):
        resp = await client.delete(
            "/api/config/exchange-connections/invalid",
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_upsert_exchange_connection_demo_keys(self, client, user_headers, regular_user):
        body = {
            "demo_api_key": "demo-key",
            "demo_api_secret": "demo-secret",
            "demo_passphrase": "demo-pass",
        }
        resp = await client.put(
            "/api/config/exchange-connections/bitget",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 200

    async def test_upsert_rejects_same_key_in_both_fields_same_request(
        self, client, user_headers, regular_user,
    ):
        """Regression for #143: a user submitting the same key in both live
        and demo fields in a single request must be rejected."""
        body = {
            "api_key": "shared-key",
            "api_secret": "shared-secret",
            "passphrase": "shared-pass",
            "demo_api_key": "shared-key",
            "demo_api_secret": "shared-secret",
            "demo_passphrase": "shared-pass",
        }
        resp = await client.put(
            "/api/config/exchange-connections/bitget",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 400
        assert "Demo" in resp.json()["detail"] or "demo" in resp.json()["detail"]

    async def test_upsert_rejects_live_key_matching_existing_demo(
        self, client, user_headers, regular_user,
    ):
        """Regression for #143: user already saved the key as demo, then
        submits the same key as live in a follow-up request → reject."""
        # First save as demo only
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "demo_api_key": "duplicate-key",
                "demo_api_secret": "duplicate-secret",
                "demo_passphrase": "duplicate-pass",
            },
            headers=user_headers,
        )
        # Now try to save the SAME key as live → must be rejected
        resp = await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "api_key": "duplicate-key",
                "api_secret": "live-secret-different",
                "passphrase": "live-pass-different",
            },
            headers=user_headers,
        )
        assert resp.status_code == 400
        # Error mentions that a demo key is already stored
        assert "Demo" in resp.json()["detail"] or "demo" in resp.json()["detail"]

    async def test_upsert_rejects_demo_key_matching_existing_live(
        self, client, user_headers, regular_user,
    ):
        """Mirror of the previous test: live first, then demo with the
        same key → reject."""
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "api_key": "another-duplicate",
                "api_secret": "live-secret",
                "passphrase": "live-pass",
            },
            headers=user_headers,
        )
        resp = await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "demo_api_key": "another-duplicate",
                "demo_api_secret": "demo-secret",
                "demo_passphrase": "demo-pass",
            },
            headers=user_headers,
        )
        assert resp.status_code == 400
        assert "Live" in resp.json()["detail"] or "live" in resp.json()["detail"]

    # ─── #145: DELETE per-mode keys endpoint ─────────────────────────

    async def test_delete_keys_live_only(
        self, client, user_headers, regular_user,
    ):
        """DELETE ?mode=live clears only the live columns, demo intact."""
        # Seed both modes
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "api_key": "live-key",
                "api_secret": "live-secret",
                "passphrase": "live-pass",
            },
            headers=user_headers,
        )
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "demo_api_key": "demo-key",
                "demo_api_secret": "demo-secret",
                "demo_passphrase": "demo-pass",
            },
            headers=user_headers,
        )

        resp = await client.delete(
            "/api/config/exchange-connections/bitget/keys?mode=live",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["fully_empty"] is False

        # Connection still exists with demo creds
        get_resp = await client.get(
            "/api/config/exchange-connections", headers=user_headers,
        )
        bitget_conn = next(
            c for c in get_resp.json()["connections"] if c["exchange_type"] == "bitget"
        )
        assert bitget_conn["api_keys_configured"] is False
        assert bitget_conn["demo_api_keys_configured"] is True

    async def test_delete_keys_demo_only(
        self, client, user_headers, regular_user,
    ):
        """DELETE ?mode=demo clears only the demo columns, live intact."""
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "api_key": "live-key-2",
                "api_secret": "live-secret-2",
                "passphrase": "live-pass-2",
            },
            headers=user_headers,
        )
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "demo_api_key": "demo-key-2",
                "demo_api_secret": "demo-secret-2",
                "demo_passphrase": "demo-pass-2",
            },
            headers=user_headers,
        )

        resp = await client.delete(
            "/api/config/exchange-connections/bitget/keys?mode=demo",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["fully_empty"] is False

        get_resp = await client.get(
            "/api/config/exchange-connections", headers=user_headers,
        )
        bitget_conn = next(
            c for c in get_resp.json()["connections"] if c["exchange_type"] == "bitget"
        )
        assert bitget_conn["api_keys_configured"] is True
        assert bitget_conn["demo_api_keys_configured"] is False

    async def test_delete_keys_drops_row_when_both_empty(
        self, client, user_headers, regular_user,
    ):
        """When the only-stored mode is deleted, the connection row vanishes
        so the UI doesn't show a stale 'configured' badge."""
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "demo_api_key": "demo-only",
                "demo_api_secret": "demo-only-secret",
                "demo_passphrase": "demo-only-pass",
            },
            headers=user_headers,
        )

        resp = await client.delete(
            "/api/config/exchange-connections/bitget/keys?mode=demo",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["fully_empty"] is True

        get_resp = await client.get(
            "/api/config/exchange-connections", headers=user_headers,
        )
        bitget_present = any(
            c["exchange_type"] == "bitget"
            for c in get_resp.json()["connections"]
        )
        assert bitget_present is False

    async def test_delete_keys_no_connection_404(
        self, client, user_headers, regular_user,
    ):
        """Deleting keys for an exchange the user never configured returns 404."""
        resp = await client.delete(
            "/api/config/exchange-connections/bitget/keys?mode=live",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_delete_keys_wrong_mode_returns_404(
        self, client, user_headers, regular_user,
    ):
        """If the requested mode has no credentials, return 404 instead of
        silently succeeding (the user should know nothing was deleted)."""
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "demo_api_key": "demo-only-3",
                "demo_api_secret": "demo-only-secret-3",
                "demo_passphrase": "demo-only-pass-3",
            },
            headers=user_headers,
        )
        # No live keys exist → DELETE ?mode=live should fail
        resp = await client.delete(
            "/api/config/exchange-connections/bitget/keys?mode=live",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_delete_keys_invalid_mode_422(
        self, client, user_headers, regular_user,
    ):
        """Invalid mode query param → FastAPI returns 422 (Literal validation)."""
        await client.put(
            "/api/config/exchange-connections/bitget",
            json={
                "api_key": "key",
                "api_secret": "secret",
                "passphrase": "pass",
            },
            headers=user_headers,
        )
        resp = await client.delete(
            "/api/config/exchange-connections/bitget/keys?mode=both",
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_upsert_exchange_connection_hl_demo_valid(self, client, user_headers, regular_user):
        body = {
            "demo_api_key": "0x" + "c" * 40,
            "demo_api_secret": "d" * 64,
        }
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 200

    async def test_upsert_exchange_connection_hl_invalid_demo_address(self, client, user_headers, regular_user):
        body = {
            "demo_api_key": "bad-address",
            "demo_api_secret": "d" * 64,
        }
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 400

    async def test_upsert_exchange_connection_hl_invalid_demo_key(self, client, user_headers, regular_user):
        body = {
            "demo_api_key": "0x" + "c" * 40,
            "demo_api_secret": "not-hex-key",
        }
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid",
            json=body,
            headers=user_headers,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Test Exchange Connection
# ---------------------------------------------------------------------------


class TestExchangeConnectionTest:

    async def test_test_connection_no_keys(self, client, user_headers, regular_user):
        resp = await client.post(
            "/api/config/exchange-connections/bitget/test",
            headers=user_headers,
        )
        assert resp.status_code == 400

    async def test_test_connection_no_live_keys(self, client, user_headers, regular_user, test_engine):
        factory = async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False
        )
        from src.utils.encryption import encrypt_value

        async with factory() as session:
            conn = ExchangeConnection(
                user_id=regular_user.id,
                exchange_type="weex",
                demo_api_key_encrypted=encrypt_value("demo-key"),
                demo_api_secret_encrypted=encrypt_value("demo-secret"),
            )
            session.add(conn)
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/weex/test",
            headers=user_headers,
            params={"mode": "live"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_NO_LIVE_API_KEYS

    async def test_test_connection_no_demo_keys(self, client, user_headers, regular_user, exchange_conn_bitget):
        resp = await client.post(
            "/api/config/exchange-connections/bitget/test",
            headers=user_headers,
            params={"mode": "demo"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_NO_DEMO_API_KEYS

    async def test_test_connection_invalid_exchange(self, client, user_headers, regular_user):
        resp = await client.post(
            "/api/config/exchange-connections/invalid/test",
            headers=user_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Affiliate UID
# ---------------------------------------------------------------------------


class TestAffiliateUID:

    async def test_set_affiliate_uid_success(self, client, user_headers, regular_user):
        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": "123456"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["uid"] == "123456"

    async def test_set_affiliate_uid_invalid(self, client, user_headers, regular_user):
        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": "not-a-number"},
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_set_affiliate_uid_empty(self, client, user_headers, regular_user):
        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": ""},
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_set_affiliate_uid_creates_connection(self, client, user_headers, regular_user):
        """Should create an ExchangeConnection if none exists."""
        resp = await client.put(
            "/api/config/exchange-connections/weex/affiliate-uid",
            json={"uid": "789012"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["uid"] == "789012"

    async def test_set_affiliate_uid_invalid_exchange(self, client, user_headers, regular_user):
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid/affiliate-uid",
            json={"uid": "123456"},
            headers=user_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Hyperliquid Builder Config
# ---------------------------------------------------------------------------


class TestHyperliquidBuilderConfig:

    async def test_get_builder_config(self, client, user_headers, regular_user):
        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {
                "builder_address": "",
                "builder_fee": 10,
                "referral_code": "",
            }
            resp = await client.get(
                "/api/config/hyperliquid/builder-config",
                headers=user_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["builder_configured"] is False

    async def test_get_builder_config_with_address(self, client, user_headers, regular_user, exchange_conn_hl):
        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {
                "builder_address": "0x" + "a" * 40,
                "builder_fee": 10,
                "referral_code": "TESTREF",
            }
            resp = await client.get(
                "/api/config/hyperliquid/builder-config",
                headers=user_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["builder_configured"] is True
            assert data["referral_required"] is True
            assert data["has_hl_connection"] is True


# ---------------------------------------------------------------------------
# Hyperliquid Admin Settings
# ---------------------------------------------------------------------------


class TestHyperliquidAdminSettings:

    async def test_get_hl_admin_settings_requires_admin(self, client, user_headers, regular_user):
        resp = await client.get(
            "/api/config/hyperliquid/admin-settings",
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_get_hl_admin_settings_success(self, client, admin_headers, admin_user):
        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {
                "builder_address": "0x" + "a" * 40,
                "builder_fee": 10,
                "referral_code": "REF123",
            }
            resp = await client.get(
                "/api/config/hyperliquid/admin-settings",
                headers=admin_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "builder_address" in data
            assert "builder_fee" in data
            assert "referral_code" in data
            assert "sources" in data

    async def test_update_hl_admin_settings_requires_admin(self, client, user_headers, regular_user):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_address": "0x" + "a" * 40},
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_update_hl_admin_settings_success(self, client, admin_headers, admin_user):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={
                "builder_address": "0x" + "b" * 40,
                "builder_fee": 15,
                "referral_code": "NEWREF",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_hl_admin_settings_invalid_address(self, client, admin_headers, admin_user):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_address": "invalid-addr"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_update_hl_admin_settings_invalid_fee(self, client, admin_headers, admin_user):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_fee": 150},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_update_hl_admin_settings_invalid_referral(self, client, admin_headers, admin_user):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"referral_code": "a" * 51},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_update_hl_admin_settings_clear_values(self, client, admin_headers, admin_user):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={
                "builder_address": "",
                "builder_fee": 0,
                "referral_code": "",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200

    async def test_update_hl_admin_settings_non_numeric_fee(self, client, admin_headers, admin_user):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_fee": "abc"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_update_hl_admin_settings_negative_fee(self, client, admin_headers, admin_user):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_fee": -5},
            headers=admin_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Hyperliquid Confirm Builder Approval
# ---------------------------------------------------------------------------


class TestConfirmBuilderApproval:

    async def test_confirm_no_connection(self, client, user_headers, regular_user):
        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            headers=user_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_NO_HL_CONNECTION_PLAIN


# ---------------------------------------------------------------------------
# Hyperliquid Verify Referral
# ---------------------------------------------------------------------------


class TestVerifyReferral:

    async def test_verify_referral_no_connection(self, client, user_headers, regular_user):
        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            headers=user_headers,
        )
        assert resp.status_code == 400

    async def test_verify_referral_no_code_required(self, client, user_headers, regular_user, exchange_conn_hl):
        with patch("src.utils.settings.get_hl_config", new_callable=AsyncMock) as mock_cfg:
            mock_cfg.return_value = {
                "builder_address": "",
                "builder_fee": 10,
                "referral_code": "",
            }
            resp = await client.post(
                "/api/config/hyperliquid/verify-referral",
                headers=user_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["verified"] is True


# ---------------------------------------------------------------------------
# Hyperliquid Referral Status (admin)
# ---------------------------------------------------------------------------


class TestReferralStatus:

    async def test_referral_status_requires_admin(self, client, user_headers, regular_user):
        resp = await client.get(
            "/api/config/hyperliquid/referral-status",
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Hyperliquid Revenue Summary (admin)
# ---------------------------------------------------------------------------


class TestRevenueSummary:

    async def test_revenue_summary_requires_admin(self, client, user_headers, regular_user):
        resp = await client.get(
            "/api/config/hyperliquid/revenue-summary",
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin Affiliate UID Management
# ---------------------------------------------------------------------------


class TestAdminAffiliateUIDs:

    async def test_list_affiliate_uids_requires_admin(self, client, user_headers, regular_user):
        resp = await client.get(
            "/api/config/admin/affiliate-uids",
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_list_affiliate_uids_success(self, client, admin_headers, admin_user):
        resp = await client.get(
            "/api/config/admin/affiliate-uids",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert "stats" in data

    async def test_list_affiliate_uids_with_pagination(self, client, admin_headers, admin_user):
        resp = await client.get(
            "/api/config/admin/affiliate-uids",
            headers=admin_headers,
            params={"page": 1, "per_page": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["per_page"] == 5

    async def test_list_affiliate_uids_with_status_filter(self, client, admin_headers, admin_user):
        resp = await client.get(
            "/api/config/admin/affiliate-uids",
            headers=admin_headers,
            params={"status": "pending"},
        )
        assert resp.status_code == 200

    async def test_list_affiliate_uids_with_search(self, client, admin_headers, admin_user):
        resp = await client.get(
            "/api/config/admin/affiliate-uids",
            headers=admin_headers,
            params={"search": "testuser"},
        )
        assert resp.status_code == 200

    async def test_verify_affiliate_uid_requires_admin(self, client, user_headers, regular_user):
        resp = await client.put(
            "/api/config/admin/affiliate-uids/1/verify",
            json={"verified": True},
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_verify_affiliate_uid_not_found(self, client, admin_headers, admin_user):
        resp = await client.put(
            "/api/config/admin/affiliate-uids/99999/verify",
            json={"verified": True},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_verify_affiliate_uid_success(self, client, admin_headers, admin_user, test_engine):
        """Create an exchange connection with affiliate UID, then verify it."""
        factory = async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            # Create a separate user for the affiliate UID
            user = User(
                username="affiliateuser",
                email="affiliate@test.com",
                password_hash=hash_password("testpassword123"),
                role="user",
                is_active=True,
                language="en",
            )
            session.add(user)
            await session.flush()

            conn = ExchangeConnection(
                user_id=user.id,
                exchange_type="bitget",
                affiliate_uid="999888",
                affiliate_verified=False,
            )
            session.add(conn)
            await session.commit()
            conn_id = conn.id

        resp = await client.put(
            f"/api/config/admin/affiliate-uids/{conn_id}/verify",
            json={"verified": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["affiliate_verified"] is True
        assert data["affiliate_uid"] == "999888"

    async def test_reject_affiliate_uid(self, client, admin_headers, admin_user, test_engine):
        """Admin can reject an affiliate UID."""
        factory = async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            user = User(
                username="rejectuser",
                email="reject@test.com",
                password_hash=hash_password("testpassword123"),
                role="user",
                is_active=True,
                language="en",
            )
            session.add(user)
            await session.flush()

            conn = ExchangeConnection(
                user_id=user.id,
                exchange_type="weex",
                affiliate_uid="111222",
                affiliate_verified=True,
            )
            session.add(conn)
            await session.commit()
            conn_id = conn.id

        resp = await client.put(
            f"/api/config/admin/affiliate-uids/{conn_id}/verify",
            json={"verified": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["affiliate_verified"] is False


# ---------------------------------------------------------------------------
# _async_none helper
# ---------------------------------------------------------------------------


class TestAsyncNoneHelper:

    async def test_async_none_returns_none(self):
        from src.api.routers.config import _async_none
        result = await _async_none()
        assert result is None


# ---------------------------------------------------------------------------
# _ping_service helper
# ---------------------------------------------------------------------------


class TestPingService:

    async def test_ping_service_timeout(self):
        import aiohttp
        from src.api.routers.config import _ping_service

        async with aiohttp.ClientSession() as session:
            result = await _ping_service(
                session,
                "http://127.0.0.1:1",  # Non-routable, will timeout
                timeout=0.1,
            )
            assert result["reachable"] is False

    async def test_ping_service_invalid_url(self):
        import aiohttp
        from src.api.routers.config import _ping_service

        async with aiohttp.ClientSession() as session:
            result = await _ping_service(
                session,
                "http://definitely-not-a-real-host-xyz.invalid",
                timeout=0.5,
            )
            assert result["reachable"] is False
            assert "error" in result
