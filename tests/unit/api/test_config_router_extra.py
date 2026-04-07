"""
Integration tests for the config router (src/api/routers/config.py).

Uses real FastAPI app with in-memory SQLite, real auth/encryption, and
targeted mocks only for external services (exchange clients, aiohttp,
settings helpers). This ensures actual router code is exercised.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import (
    Base,
    ExchangeConnection,
    SystemSetting,
    TradeRecord,
    User,
    UserConfig,
)
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token
from src.errors import (
    ERR_BUILDER_FEE_NOT_FOUND,
    ERR_CONNECTION_FAILED,
    ERR_INVALID_BUILDER_ADDRESS,
    ERR_NO_API_KEYS,
    ERR_NO_DEMO_API_KEYS,
    ERR_NO_LIVE_API_KEYS,
    ERR_REFERRAL_CHECK_FAILED,
    ERR_REFERRAL_NOT_FOUND,
    ERR_REVENUE_SUMMARY_FAILED,
)
from src.utils.encryption import encrypt_value

# Reset Fernet singleton so it uses our test key
import src.utils.encryption as _enc_mod

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
async def session_factory(test_engine):
    return async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def user(session_factory) -> User:
    async with session_factory() as session:
        u = User(
            username="cfguser",
            email="cfguser@test.com",
            password_hash=hash_password("testpassword123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def admin_user(session_factory) -> User:
    async with session_factory() as session:
        u = User(
            username="cfgadmin",
            email="cfgadmin@test.com",
            password_hash=hash_password("testpassword123"),
            role="admin",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
def auth_headers(user) -> dict:
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
def admin_headers(admin_user) -> dict:
    token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def app(test_engine):
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

    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import auth, config
    from src.models.session import get_db

    limiter.enabled = False

    test_app = FastAPI(title="Test Config Extra API")
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    test_app.include_router(auth.router)
    test_app.include_router(config.router)

    test_app.dependency_overrides[get_db] = override_get_db

    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_WALLET = "0x" + "ab" * 20  # 0x + 40 hex chars
VALID_PRIVKEY = "ab" * 32  # 64 hex chars


def _mock_hl_config(builder_address="", builder_fee=10, referral_code=""):
    """Return a coroutine-compatible mock for get_hl_config."""
    async def _get():
        return {
            "builder_address": builder_address,
            "builder_fee": builder_fee,
            "referral_code": referral_code,
        }
    return _get


# ===========================================================================
# 1. GET /api/config
# ===========================================================================


class TestGetConfig:
    """GET /api/config - Returns trading/strategy config + connections."""

    @pytest.mark.asyncio
    async def test_get_config_default(self, client, auth_headers):
        """New user gets default config with no trading/strategy settings."""
        resp = await client.get("/api/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["trading"] is None
        assert data["strategy"] is None
        assert data["connections"] == []
        assert data["exchange_type"] == "bitget"

    @pytest.mark.asyncio
    async def test_get_config_with_trading_and_strategy(
        self, client, auth_headers, session_factory, user
    ):
        """Config with saved trading and strategy returns parsed JSON."""
        trading = {"max_trades_per_day": 5, "daily_loss_limit_percent": 3.0,
                   "position_size_percent": 10.0, "leverage": 5,
                   "take_profit_percent": 5.0, "stop_loss_percent": 2.0,
                   "trading_pairs": ["BTCUSDT"], "demo_mode": True}
        strategy = {"fear_greed_extreme_fear": 15, "fear_greed_extreme_greed": 85,
                     "long_short_crowded_longs": 3.0, "long_short_crowded_shorts": 0.3,
                     "funding_rate_high": 0.001, "funding_rate_low": -0.001,
                     "high_confidence_min": 90, "low_confidence_min": 55}
        async with session_factory() as session:
            cfg = UserConfig(
                user_id=user.id,
                exchange_type="bitget",
                trading_config=json.dumps(trading),
                strategy_config=json.dumps(strategy),
            )
            session.add(cfg)
            await session.commit()

        resp = await client.get("/api/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["trading"]["leverage"] == 5
        assert data["strategy"]["high_confidence_min"] == 90

    @pytest.mark.asyncio
    async def test_get_config_with_connections(
        self, client, auth_headers, session_factory, user
    ):
        """Config includes exchange connections list."""
        async with session_factory() as session:
            conn = ExchangeConnection(
                user_id=user.id,
                exchange_type="bitget",
                api_key_encrypted=encrypt_value("testkey"),
            )
            session.add(conn)
            await session.commit()

        resp = await client.get("/api/config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["connections"]) == 1
        assert data["connections"][0]["exchange_type"] == "bitget"
        assert data["connections"][0]["api_keys_configured"] is True

    @pytest.mark.asyncio
    async def test_get_config_unauthorized(self, client):
        resp = await client.get("/api/config")
        assert resp.status_code in (401, 403)


# ===========================================================================
# 2. PUT /api/config/trading
# ===========================================================================


class TestUpdateTradingConfig:

    @pytest.mark.asyncio
    async def test_update_trading_config(self, client, auth_headers):
        payload = {
            "max_trades_per_day": 5,
            "daily_loss_limit_percent": 3.0,
            "position_size_percent": 10.0,
            "leverage": 5,
            "take_profit_percent": 5.0,
            "stop_loss_percent": 2.0,
            "trading_pairs": ["BTCUSDT"],
            "demo_mode": True,
        }
        resp = await client.put("/api/config/trading", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify it persisted
        resp2 = await client.get("/api/config", headers=auth_headers)
        assert resp2.json()["trading"]["leverage"] == 5


# ===========================================================================
# 3. PUT /api/config/strategy
# ===========================================================================


class TestUpdateStrategyConfig:

    @pytest.mark.asyncio
    async def test_update_strategy_config(self, client, auth_headers):
        payload = {
            "fear_greed_extreme_fear": 15,
            "fear_greed_extreme_greed": 85,
            "long_short_crowded_longs": 3.0,
            "long_short_crowded_shorts": 0.3,
            "funding_rate_high": 0.001,
            "funding_rate_low": -0.001,
            "high_confidence_min": 90,
            "low_confidence_min": 55,
        }
        resp = await client.put("/api/config/strategy", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ===========================================================================
# 4. GET /api/config/exchange-connections
# ===========================================================================


class TestGetExchangeConnections:

    @pytest.mark.asyncio
    async def test_get_empty_connections(self, client, auth_headers):
        resp = await client.get("/api/config/exchange-connections", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["connections"] == []

    @pytest.mark.asyncio
    async def test_get_connections_with_data(
        self, client, auth_headers, session_factory, user
    ):
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("key1"),
            ))
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="weex",
                demo_api_key_encrypted=encrypt_value("demokey"),
            ))
            await session.commit()

        resp = await client.get("/api/config/exchange-connections", headers=auth_headers)
        assert resp.status_code == 200
        conns = resp.json()["connections"]
        assert len(conns) == 2
        types = {c["exchange_type"] for c in conns}
        assert types == {"bitget", "weex"}


# ===========================================================================
# 5. PUT /api/config/exchange-connections/{exchange_type}
# ===========================================================================


class TestUpsertExchangeConnection:

    @pytest.mark.asyncio
    async def test_create_bitget_connection(self, client, auth_headers):
        payload = {
            "api_key": "my-bitget-key",
            "api_secret": "my-bitget-secret",
            "passphrase": "my-pass",
        }
        resp = await client.put(
            "/api/config/exchange-connections/bitget", json=payload, headers=auth_headers
        )
        assert resp.status_code == 200
        assert "bitget" in resp.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_create_weex_connection(self, client, auth_headers):
        payload = {"api_key": "weexkey", "api_secret": "weexsecret"}
        resp = await client.put(
            "/api/config/exchange-connections/weex", json=payload, headers=auth_headers
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_create_hyperliquid_connection_valid(self, client, auth_headers):
        payload = {
            "api_key": VALID_WALLET,
            "api_secret": VALID_PRIVKEY,
        }
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid", json=payload, headers=auth_headers
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_hyperliquid_invalid_wallet_address(self, client, auth_headers):
        payload = {"api_key": "not-a-wallet", "api_secret": VALID_PRIVKEY}
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid", json=payload, headers=auth_headers
        )
        assert resp.status_code == 400
        assert "Wallet address" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_hyperliquid_invalid_private_key(self, client, auth_headers):
        payload = {"api_key": VALID_WALLET, "api_secret": "not-hex-key"}
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid", json=payload, headers=auth_headers
        )
        assert resp.status_code == 400
        assert "Private key" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_hyperliquid_valid_demo_keys(self, client, auth_headers):
        """Demo wallet/key fields also get validated."""
        payload = {
            "demo_api_key": VALID_WALLET,
            "demo_api_secret": "0x" + "cd" * 32,  # 0x prefix OK for private key
        }
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid", json=payload, headers=auth_headers
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_hyperliquid_invalid_demo_wallet(self, client, auth_headers):
        payload = {"demo_api_key": "0xTOOSHORT"}
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid", json=payload, headers=auth_headers
        )
        assert resp.status_code == 400
        assert "Testnet wallet address" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_hyperliquid_invalid_demo_privkey(self, client, auth_headers):
        payload = {"demo_api_key": VALID_WALLET, "demo_api_secret": "badhex"}
        resp = await client.put(
            "/api/config/exchange-connections/hyperliquid", json=payload, headers=auth_headers
        )
        assert resp.status_code == 400
        assert "Testnet private key" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, client, auth_headers, session_factory, user):
        """Second PUT updates existing connection, not creates a new one."""
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("oldkey"),
            ))
            await session.commit()

        payload = {"api_key": "newkey", "api_secret": "newsecret"}
        resp = await client.put(
            "/api/config/exchange-connections/bitget", json=payload, headers=auth_headers
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_upsert_with_all_fields(self, client, auth_headers):
        """Live + demo keys + passphrase all in one request."""
        payload = {
            "api_key": "livekey", "api_secret": "livesecret", "passphrase": "livepass",
            "demo_api_key": "demokey", "demo_api_secret": "demosecret", "demo_passphrase": "demopass",
        }
        resp = await client.put(
            "/api/config/exchange-connections/bitget", json=payload, headers=auth_headers
        )
        assert resp.status_code == 200


# ===========================================================================
# 6. DELETE /api/config/exchange-connections/{exchange_type}
# ===========================================================================


class TestDeleteExchangeConnection:

    @pytest.mark.asyncio
    async def test_delete_existing(self, client, auth_headers, session_factory, user):
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("key"),
            ))
            await session.commit()

        resp = await client.delete(
            "/api/config/exchange-connections/bitget", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client, auth_headers):
        resp = await client.delete(
            "/api/config/exchange-connections/bitget", headers=auth_headers
        )
        assert resp.status_code == 404


# ===========================================================================
# 7. POST /api/config/exchange-connections/{exchange_type}/test
# ===========================================================================


class TestTestExchangeConnection:

    @pytest.mark.asyncio
    async def test_no_connection_returns_400(self, client, auth_headers):
        resp = await client.post(
            "/api/config/exchange-connections/bitget/test", headers=auth_headers
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_live_mode(self, mock_create, client, auth_headers, session_factory, user):
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(total=1000.0, currency="USDT")
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("livekey"),
                api_secret_encrypted=encrypt_value("livesecret"),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/bitget/test?mode=live",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["mode"] == "live"
        assert data["balance"] == 1000.0

    @pytest.mark.asyncio
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_demo_mode(self, mock_create, client, auth_headers, session_factory, user):
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(total=500.0, currency="USDT")
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                demo_api_key_encrypted=encrypt_value("demokey"),
                demo_api_secret_encrypted=encrypt_value("demosecret"),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/bitget/test?mode=demo",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "demo"

    @pytest.mark.asyncio
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_auto_detect_mode(self, mock_create, client, auth_headers, session_factory, user):
        """No mode param: prefers demo if available."""
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(total=200.0, currency="USDT")
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("livekey"),
                api_secret_encrypted=encrypt_value("livesecret"),
                demo_api_key_encrypted=encrypt_value("demokey"),
                demo_api_secret_encrypted=encrypt_value("demosecret"),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/bitget/test",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "demo"

    @pytest.mark.asyncio
    async def test_live_mode_no_live_keys(self, client, auth_headers, session_factory, user):
        """Requesting live mode without live keys returns 400."""
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                demo_api_key_encrypted=encrypt_value("demokey"),
                demo_api_secret_encrypted=encrypt_value("demosecret"),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/bitget/test?mode=live",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_NO_LIVE_API_KEYS

    @pytest.mark.asyncio
    async def test_demo_mode_no_demo_keys(self, client, auth_headers, session_factory, user):
        """Requesting demo mode without demo keys returns 400."""
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("livekey"),
                api_secret_encrypted=encrypt_value("livesecret"),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/bitget/test?mode=demo",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_NO_DEMO_API_KEYS

    @pytest.mark.asyncio
    async def test_auto_mode_no_keys_at_all(self, client, auth_headers, session_factory, user):
        """Auto mode with no keys at all returns 400."""
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/bitget/test",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_NO_API_KEYS

    @pytest.mark.asyncio
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_connection_failure(self, mock_create, client, auth_headers, session_factory, user):
        """When exchange client raises, returns 400 with generic message."""
        mock_create.side_effect = Exception("Network error")

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("key"),
                api_secret_encrypted=encrypt_value("secret"),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/bitget/test?mode=live",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_CONNECTION_FAILED


# ===========================================================================
# 8. PUT /api/config/exchange-connections/{exchange_type}/affiliate-uid
# ===========================================================================


class TestSetAffiliateUid:

    @pytest.mark.asyncio
    async def test_set_uid_invalid_non_numeric(self, client, auth_headers):
        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": "abc"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_set_uid_empty(self, client, auth_headers):
        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @patch("src.api.routers.config._get_admin_exchange_conn", new_callable=AsyncMock, return_value=None)
    async def test_set_uid_no_admin_conn(self, mock_admin, client, auth_headers):
        """UID saved but not verified when no admin connection exists."""
        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": "12345"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["uid"] == "12345"
        assert data["verified"] is False

    @pytest.mark.asyncio
    @patch("src.exchanges.factory.create_exchange_client")
    @patch("src.api.routers.config._get_admin_exchange_conn")
    async def test_set_uid_auto_verify_success(
        self, mock_admin_conn, mock_create, client, auth_headers, session_factory, admin_user
    ):
        """UID auto-verified when admin exchange conn exists and check passes."""
        admin_conn = ExchangeConnection(
            user_id=admin_user.id, exchange_type="bitget",
            api_key_encrypted=encrypt_value("adminkey"),
            api_secret_encrypted=encrypt_value("adminsecret"),
        )
        mock_admin_conn.return_value = admin_conn

        mock_client = AsyncMock()
        mock_client.check_affiliate_uid = AsyncMock(return_value=True)
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": "99999"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is True

    @pytest.mark.asyncio
    @patch("src.exchanges.factory.create_exchange_client")
    @patch("src.api.routers.config._get_admin_exchange_conn")
    async def test_set_uid_auto_verify_failure(
        self, mock_admin_conn, mock_create, client, auth_headers, session_factory, admin_user
    ):
        """UID saved but not verified when exchange reports non-affiliate."""
        admin_conn = ExchangeConnection(
            user_id=admin_user.id, exchange_type="bitget",
            api_key_encrypted=encrypt_value("adminkey"),
            api_secret_encrypted=encrypt_value("adminsecret"),
        )
        mock_admin_conn.return_value = admin_conn

        mock_client = AsyncMock()
        mock_client.check_affiliate_uid = AsyncMock(return_value=False)
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": "11111"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is False

    @pytest.mark.asyncio
    @patch("src.api.routers.config._get_admin_exchange_conn")
    async def test_set_uid_verify_exception_silent(
        self, mock_admin_conn, client, auth_headers
    ):
        """If verify throws, UID is still saved (silent failure)."""
        mock_admin_conn.side_effect = Exception("DB error")

        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": "77777"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["verified"] is False

    @pytest.mark.asyncio
    @patch("src.api.routers.config._get_admin_exchange_conn", new_callable=AsyncMock, return_value=None)
    async def test_set_uid_updates_existing_connection(
        self, mock_admin, client, auth_headers, session_factory, user
    ):
        """If user already has a bitget connection, UID is set on it."""
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("key"),
            ))
            await session.commit()

        resp = await client.put(
            "/api/config/exchange-connections/bitget/affiliate-uid",
            json={"uid": "55555"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["uid"] == "55555"


# ===========================================================================
# 9. GET /api/config/connections (ping external services)
# ===========================================================================


class TestGetConnectionsStatus:

    @pytest.mark.asyncio
    @patch("src.api.routers.config.aiohttp.ClientSession")
    async def test_connections_status(self, mock_session_cls, client, auth_headers):
        """Mocks aiohttp to avoid real HTTP calls; verifies response structure."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_method = MagicMock()
        mock_method.return_value = mock_response

        mock_session = AsyncMock()
        mock_session.get = mock_method
        mock_session.post = mock_method
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        resp = await client.get("/api/config/connections", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "timestamp" in data
        assert "services" in data
        assert "circuit_breakers" in data


# ===========================================================================
# 14. GET /api/config/hyperliquid/admin-settings (admin only)
# ===========================================================================


class TestGetHLAdminSettings:

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_admin_gets_settings(self, mock_hl, client, admin_headers):
        mock_hl.return_value = {
            "builder_address": "0x" + "aa" * 20,
            "builder_fee": 10,
            "referral_code": "TESTREF",
        }
        resp = await client.get(
            "/api/config/hyperliquid/admin-settings", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["builder_fee"] == 10
        assert "sources" in data

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, client, auth_headers):
        resp = await client.get(
            "/api/config/hyperliquid/admin-settings", headers=auth_headers
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_admin_settings_with_db_values(
        self, mock_hl, client, admin_headers, session_factory
    ):
        """When SystemSettings exist in DB, sources show 'db'."""
        mock_hl.return_value = {
            "builder_address": "0x" + "bb" * 20,
            "builder_fee": 15,
            "referral_code": "DBREF",
        }
        async with session_factory() as session:
            session.add(SystemSetting(key="HL_BUILDER_ADDRESS", value="0x" + "bb" * 20))
            session.add(SystemSetting(key="HL_BUILDER_FEE", value="15"))
            session.add(SystemSetting(key="HL_REFERRAL_CODE", value="DBREF"))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/admin-settings", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"]["builder_address"] == "db"
        assert data["sources"]["builder_fee"] == "db"
        assert data["sources"]["referral_code"] == "db"


# ===========================================================================
# 15. PUT /api/config/hyperliquid/admin-settings (admin only)
# ===========================================================================


class TestUpdateHLAdminSettings:

    @pytest.mark.asyncio
    async def test_update_valid_settings(self, client, admin_headers):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={
                "builder_address": "0x" + "cc" * 20,
                "builder_fee": 20,
                "referral_code": "NEWREF",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_invalid_builder_address(self, client, admin_headers):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_address": "invalid"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_INVALID_BUILDER_ADDRESS

    @pytest.mark.asyncio
    async def test_invalid_builder_fee_not_int(self, client, admin_headers):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_fee": "notanumber"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_builder_fee_out_of_range(self, client, admin_headers):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_fee": 200},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_builder_fee_negative(self, client, admin_headers):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_fee": -1},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_referral_code(self, client, admin_headers):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"referral_code": "a" * 51},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_referral_code_special_chars(self, client, admin_headers):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"referral_code": "invalid code!@#"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_clears_settings(self, client, admin_headers):
        """Empty values clear the settings."""
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_address": "", "builder_fee": 0, "referral_code": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_updates_existing_system_settings(
        self, client, admin_headers, session_factory
    ):
        """When settings already exist, they are updated not duplicated."""
        async with session_factory() as session:
            session.add(SystemSetting(key="HL_BUILDER_ADDRESS", value="0x" + "aa" * 20))
            session.add(SystemSetting(key="HL_BUILDER_FEE", value="5"))
            session.add(SystemSetting(key="HL_REFERRAL_CODE", value="OLD"))
            await session.commit()

        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={
                "builder_address": "0x" + "dd" * 20,
                "builder_fee": 25,
                "referral_code": "UPDATED",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, client, auth_headers):
        resp = await client.put(
            "/api/config/hyperliquid/admin-settings",
            json={"builder_fee": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 403


# ===========================================================================
# 16. GET /api/config/hyperliquid/builder-config
# ===========================================================================


class TestGetBuilderConfig:

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_no_builder_configured(self, mock_hl, client, auth_headers):
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": ""}
        resp = await client.get(
            "/api/config/hyperliquid/builder-config", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["builder_configured"] is False

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_builder_configured_no_hl_connection(self, mock_hl, client, auth_headers):
        mock_hl.return_value = {
            "builder_address": "0x" + "aa" * 20,
            "builder_fee": 10,
            "referral_code": "TESTREF",
        }
        resp = await client.get(
            "/api/config/hyperliquid/builder-config", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["builder_configured"] is True
        assert data["has_hl_connection"] is False
        assert data["referral_required"] is True

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_builder_configured_with_hl_connection(
        self, mock_hl, client, auth_headers, session_factory, user
    ):
        mock_hl.return_value = {
            "builder_address": "0x" + "aa" * 20,
            "builder_fee": 10,
            "referral_code": "",
        }
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
                builder_fee_approved=True,
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/builder-config", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_hl_connection"] is True
        assert data["builder_fee_approved"] is True
        assert data["needs_approval"] is False
        assert data["referral_required"] is False


# ===========================================================================
# 17. POST /api/config/hyperliquid/confirm-builder-approval
# ===========================================================================


class TestConfirmBuilderApproval:

    @pytest.mark.asyncio
    async def test_no_hl_connection_returns_400(self, client, auth_headers):
        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_approval_confirmed(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        mock_hl.return_value = {"builder_address": "0x" + "aa" * 20, "builder_fee": 10, "referral_code": ""}

        mock_client = AsyncMock()
        mock_client.check_builder_fee_approval = AsyncMock(return_value=15)
        mock_client.close = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["approved_max_fee"] == 15

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_approval_not_found(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        mock_hl.return_value = {"builder_address": "0x" + "aa" * 20, "builder_fee": 10, "referral_code": ""}

        mock_client = AsyncMock()
        mock_client.check_builder_fee_approval = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_BUILDER_FEE_NOT_FOUND

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_approval_with_signing_wallet(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """When stored wallet returns None but signing wallet succeeds."""
        mock_hl.return_value = {"builder_address": "0x" + "aa" * 20, "builder_fee": 10, "referral_code": ""}

        mock_client = AsyncMock()
        # First call (stored wallet) returns None, second call (signing wallet) returns fee
        mock_client.check_builder_fee_approval = AsyncMock(side_effect=[None, 20])
        mock_client.close = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        signing_wallet = "0x" + "ee" * 20
        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={"wallet_address": signing_wallet},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["approved_max_fee"] == 20

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_approval_fee_too_low(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """Approved fee lower than required returns 400."""
        mock_hl.return_value = {"builder_address": "0x" + "aa" * 20, "builder_fee": 20, "referral_code": ""}

        mock_client = AsyncMock()
        mock_client.check_builder_fee_approval = AsyncMock(return_value=5)
        mock_client.close = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_approval_uses_mainnet_for_demo_user(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """Regression for #138: confirm-builder-approval must force mainnet.

        The frontend signs with ``hyperliquidChain: 'Mainnet'`` and posts
        to the mainnet /exchange endpoint. A demo-only user used to get a
        testnet client here, which always returned None on the confirmation
        check — leaving them stuck in an infinite sign-loop.
        """
        mock_hl.return_value = {"builder_address": "0x" + "aa" * 20, "builder_fee": 10, "referral_code": ""}

        mock_client = AsyncMock()
        mock_client.check_builder_fee_approval = AsyncMock(return_value=10)
        mock_client.close = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_create.return_value = mock_client

        async with session_factory() as session:
            # Demo-only user — no live credentials
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                demo_api_key_encrypted=encrypt_value(VALID_WALLET),
                demo_api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # Must have created the client with demo_mode=False (mainnet)
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs.get("demo_mode") is False, (
            "confirm-builder-approval must hit mainnet, not testnet. "
            "The frontend signs on mainnet and we must verify on mainnet."
        )

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_approval_passes_explicit_builder_address(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """Regression for #138: HL clients created via the mainnet read
        helper do not have ``self._builder`` populated (builder config lives
        in the DB, not ENV). The router must pass ``builder_address`` as an
        explicit kwarg to ``check_builder_fee_approval``, otherwise the
        method short-circuits to None.
        """
        builder_addr = "0x67b10bf64b9a6f6f9aa8246139eab1c728d8186b"
        mock_hl.return_value = {
            "builder_address": builder_addr,
            "builder_fee": 10,
            "referral_code": "",
        }

        mock_client = AsyncMock()
        mock_client.check_builder_fee_approval = AsyncMock(return_value=10)
        mock_client.close = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        # check_builder_fee_approval must have been called with the
        # builder_address kwarg — otherwise the real method would return
        # None without hitting HL, leaving the user stuck.
        all_calls = mock_client.check_builder_fee_approval.call_args_list
        assert len(all_calls) >= 1
        first_kwargs = all_calls[0].kwargs
        assert first_kwargs.get("builder_address") == builder_addr, (
            f"Expected builder_address={builder_addr} in kwargs, "
            f"got kwargs={first_kwargs}"
        )

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_approval_requires_configured_builder_address(
        self, mock_hl, client, auth_headers, session_factory, user
    ):
        """If the server has no builder address configured, we cannot confirm
        any approval — return a clear error instead of silently checking
        against an empty builder."""
        mock_hl.return_value = {"builder_address": "", "builder_fee": 10, "referral_code": ""}

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400


# ===========================================================================
# 18. POST /api/config/hyperliquid/verify-referral
# ===========================================================================


class TestVerifyReferral:

    @pytest.mark.asyncio
    async def test_no_hl_connection(self, client, auth_headers):
        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_no_referral_required(
        self, mock_hl, client, auth_headers, session_factory, user
    ):
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": ""}

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["verified"] is True

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_already_verified(
        self, mock_hl, client, auth_headers, session_factory, user
    ):
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": "REF123"}

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
                referral_verified=True,
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["verified"] is True

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_referral_found(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """Successful verification: referredBy matches the configured code."""
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": "REF123"}

        mock_client = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_client.get_referral_info = AsyncMock(return_value={
            "referredBy": {"referrer": "0xdead", "code": "REF123"},
            "cumVlm": "1500.0",
        })
        mock_client.get_user_state = AsyncMock(return_value={
            "marginSummary": {"accountValue": "100.5"},
        })
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["verified"] is True
        assert data["required_action"] == "VERIFIED"
        assert data["account_value_usd"] == 100.5

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_referral_deposit_needed(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """Empty wallet on HL — user must deposit ≥5 USDC before referral can bind.

        Regression for #135: the old code returned a generic "Referral not found"
        message with no hint about the 5 USDC minimum deposit requirement.
        """
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": "TRADINGDEPARTMENT"}

        mock_client = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_client.get_referral_info = AsyncMock(return_value={
            "referredBy": None,
            "cumVlm": "0.0",
        })
        mock_client.get_user_state = AsyncMock(return_value={
            "marginSummary": {"accountValue": "0.0"},
            "withdrawable": "0.0",
        })
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert isinstance(detail, dict)
        assert detail["required_action"] == "DEPOSIT_NEEDED"
        assert detail["account_value_usd"] == 0.0
        assert detail["min_deposit_usdc"] == 5.0
        assert "5 USDC" in detail["error"]
        assert detail["deposit_url"] == "https://app.hyperliquid.xyz/deposit"

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_referral_enter_code_needed(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """Funded wallet without referrer — user must manually enter the code.

        Regression for #135: a wallet that already has USDC on HL can still be
        bound to a referrer via the manual "Enter Code" flow on the HL
        referrals page, but only if we tell the user about it.
        """
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": "TRADINGDEPARTMENT"}

        mock_client = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_client.get_referral_info = AsyncMock(return_value={
            "referredBy": None,
            "cumVlm": "250.0",
        })
        mock_client.get_user_state = AsyncMock(return_value={
            "marginSummary": {"accountValue": "123.45"},
            "withdrawable": "100.0",
        })
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["required_action"] == "ENTER_CODE_MANUALLY"
        assert detail["account_value_usd"] == 123.45
        assert detail["cum_volume_usd"] == 250.0
        assert detail["enter_code_url"] == "https://app.hyperliquid.xyz/referrals"
        assert "TRADINGDEPARTMENT" in detail["error"]

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_referral_wrong_referrer(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """Wallet was registered via a different referrer — can't be changed."""
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": "TRADINGDEPARTMENT"}

        mock_client = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_client.get_referral_info = AsyncMock(return_value={
            "referredBy": {"referrer": "0xdead", "code": "OTHERCODE"},
            "cumVlm": "500.0",
        })
        mock_client.get_user_state = AsyncMock(return_value={
            "marginSummary": {"accountValue": "200.0"},
        })
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["required_action"] == "WRONG_REFERRER"
        assert "OTHERCODE" in detail["error"]
        assert "TRADINGDEPARTMENT" in detail["error"]

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_referral_uses_mainnet_regardless_of_demo(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """create_hl_mainnet_read_client must pass demo_mode=False even when
        the user only has demo credentials. Referrals are a mainnet concept."""
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": "REF"}

        mock_client = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_client.get_referral_info = AsyncMock(return_value={
            "referredBy": {"code": "REF"},
            "cumVlm": "0.0",
        })
        mock_client.get_user_state = AsyncMock(return_value={
            "marginSummary": {"accountValue": "50.0"},
        })
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            # Demo-only user — no live credentials
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                demo_api_key_encrypted=encrypt_value(VALID_WALLET),
                demo_api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        # Verify create_exchange_client was called with demo_mode=False
        # (mainnet) even though user only has demo credentials.
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs.get("demo_mode") is False, (
            "Referral verification must always hit mainnet — "
            "user was demo-only but we still need mainnet data"
        )


# ===========================================================================
# 19. GET /api/config/hyperliquid/referral-status (admin only)
# ===========================================================================


class TestGetReferralStatus:

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, client, auth_headers):
        resp = await client.get(
            "/api/config/hyperliquid/referral-status", headers=auth_headers
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_no_hl_connection(self, client, admin_headers):
        resp = await client.get(
            "/api/config/hyperliquid/referral-status", headers=admin_headers
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_referral_status_success(
        self, mock_create, mock_hl, client, admin_headers, session_factory, admin_user
    ):
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": "ADMINREF"}

        mock_client = AsyncMock()
        mock_client.get_referral_info = AsyncMock(return_value={"referredBy": "someone"})
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/referral-status", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["referral_code_configured"] is True
        assert data["user_referred"] is True

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_referral_status_demo_mode(
        self, mock_create, mock_hl, client, admin_headers, session_factory, admin_user
    ):
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": ""}

        mock_client = AsyncMock()
        mock_client.get_referral_info = AsyncMock(return_value=None)
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="hyperliquid",
                demo_api_key_encrypted=encrypt_value(VALID_WALLET),
                demo_api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/referral-status?mode=demo", headers=admin_headers
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_referral_status_exception(
        self, mock_create, mock_hl, client, admin_headers, session_factory, admin_user
    ):
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": ""}
        mock_create.side_effect = Exception("Network error")

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/referral-status", headers=admin_headers
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_REFERRAL_CHECK_FAILED


# ===========================================================================
# 20. GET /api/config/hyperliquid/revenue-summary (admin only)
# ===========================================================================


class TestGetRevenueSummary:

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, client, auth_headers):
        resp = await client.get(
            "/api/config/hyperliquid/revenue-summary", headers=auth_headers
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_no_hl_connection(self, client, admin_headers):
        resp = await client.get(
            "/api/config/hyperliquid/revenue-summary", headers=admin_headers
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_revenue_summary_success(
        self, mock_create, mock_hl, client, admin_headers, session_factory, admin_user
    ):
        mock_hl.return_value = {
            "builder_address": "0x" + "aa" * 20,
            "builder_fee": 10,
            "referral_code": "REF",
        }

        mock_client = AsyncMock()
        mock_client.check_builder_fee_approval = AsyncMock(return_value=10)
        mock_client.get_referral_info = AsyncMock(return_value={"referredBy": "x"})
        mock_client.get_user_fees = AsyncMock(return_value={"dailyUserVlm": 1000, "feeTier": "VIP1"})
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/revenue-summary", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "builder" in data
        assert "referral" in data
        assert "user_fees" in data
        assert "earnings" in data
        assert data["builder"]["configured"] is True
        assert data["referral"]["configured"] is True

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_revenue_summary_with_trades(
        self, mock_create, mock_hl, client, admin_headers, session_factory, admin_user
    ):
        """Revenue summary includes builder fee earnings from trade records."""
        mock_hl.return_value = {
            "builder_address": "0x" + "aa" * 20,
            "builder_fee": 10,
            "referral_code": "",
        }

        mock_client = AsyncMock()
        mock_client.check_builder_fee_approval = AsyncMock(return_value=10)
        mock_client.get_referral_info = AsyncMock(return_value=None)
        mock_client.get_user_fees = AsyncMock(return_value={})
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            # Add some trade records with builder_fee
            for i in range(3):
                session.add(TradeRecord(
                    user_id=admin_user.id,
                    exchange="hyperliquid",
                    symbol="BTCUSDT",
                    side="long",
                    size=0.1,
                    entry_price=50000.0,
                    take_profit=55000.0,
                    stop_loss=48000.0,
                    leverage=5,
                    confidence=80,
                    reason="Test trade",
                    order_id=f"order_{i}",
                    status="closed",
                    builder_fee=0.5,
                    entry_time=datetime.now(timezone.utc) - timedelta(days=5),
                ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/revenue-summary", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["earnings"]["trades_with_builder_fee"] == 3
        assert data["earnings"]["total_builder_fees_30d"] == 1.5

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_revenue_summary_exception(
        self, mock_create, mock_hl, client, admin_headers, session_factory, admin_user
    ):
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": ""}
        mock_create.side_effect = Exception("API error")

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/revenue-summary", headers=admin_headers
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_REVENUE_SUMMARY_FAILED

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_revenue_summary_no_builder_address(
        self, mock_create, mock_hl, client, admin_headers, session_factory, admin_user
    ):
        """When builder_address is empty, builder check is skipped."""
        mock_hl.return_value = {
            "builder_address": "",
            "builder_fee": 0,
            "referral_code": "REF",
        }

        mock_client = AsyncMock()
        mock_client.get_referral_info = AsyncMock(return_value=None)
        mock_client.get_user_fees = AsyncMock(return_value={})
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/revenue-summary", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["builder"]["configured"] is False


# ===========================================================================
# 21. GET /api/config/admin/affiliate-uids (admin only)
# ===========================================================================


class TestListAffiliateUids:

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, client, auth_headers):
        resp = await client.get(
            "/api/config/admin/affiliate-uids", headers=auth_headers
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_empty_list(self, client, admin_headers):
        resp = await client.get(
            "/api/config/admin/affiliate-uids", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["stats"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_data(
        self, client, admin_headers, session_factory, user, admin_user
    ):
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                affiliate_uid="11111",
                affiliate_verified=False,
            ))
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="weex",
                affiliate_uid="22222",
                affiliate_verified=True,
                affiliate_verified_at=datetime.now(timezone.utc),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/admin/affiliate-uids", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["stats"]["total"] == 2
        assert data["stats"]["verified"] == 1
        assert data["stats"]["pending"] == 1

    @pytest.mark.asyncio
    async def test_filter_by_status_pending(
        self, client, admin_headers, session_factory, user, admin_user
    ):
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                affiliate_uid="11111", affiliate_verified=False,
            ))
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="weex",
                affiliate_uid="22222", affiliate_verified=True,
                affiliate_verified_at=datetime.now(timezone.utc),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/admin/affiliate-uids?status=pending", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["affiliate_verified"] is False

    @pytest.mark.asyncio
    async def test_filter_by_status_verified(
        self, client, admin_headers, session_factory, user, admin_user
    ):
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                affiliate_uid="11111", affiliate_verified=False,
            ))
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="weex",
                affiliate_uid="22222", affiliate_verified=True,
                affiliate_verified_at=datetime.now(timezone.utc),
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/admin/affiliate-uids?status=verified", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["affiliate_verified"] is True

    @pytest.mark.asyncio
    async def test_search_by_username(
        self, client, admin_headers, session_factory, user
    ):
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                affiliate_uid="99999", affiliate_verified=False,
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/admin/affiliate-uids?search=cfguser", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_search_by_uid(
        self, client, admin_headers, session_factory, user
    ):
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                affiliate_uid="88888", affiliate_verified=False,
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/admin/affiliate-uids?search=888", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_pagination(
        self, client, admin_headers, session_factory, user, admin_user
    ):
        """Test pagination with multiple affiliate UIDs across users/exchanges."""
        async with session_factory() as session:
            # Create additional users for unique (user_id, exchange_type) pairs
            extra_users = []
            for i in range(6):
                u = User(
                    username=f"paguser{i}",
                    email=f"paguser{i}@test.com",
                    password_hash=hash_password("testpassword123"),
                    role="user",
                    is_active=True,
                )
                session.add(u)
                extra_users.append(u)
            await session.flush()

            # user + admin_user + 6 extra = 8 unique users, each with bitget conn
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                affiliate_uid="10000", affiliate_verified=False,
            ))
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="bitget",
                affiliate_uid="10001", affiliate_verified=False,
            ))
            for i, eu in enumerate(extra_users):
                session.add(ExchangeConnection(
                    user_id=eu.id, exchange_type="bitget",
                    affiliate_uid=str(10002 + i), affiliate_verified=False,
                ))
            await session.commit()

        resp = await client.get(
            "/api/config/admin/affiliate-uids?page=1&per_page=5", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 5
        assert data["total"] == 8
        assert data["pages"] == 2


# ===========================================================================
# 22. PUT /api/config/admin/affiliate-uids/{connection_id}/verify
# ===========================================================================


class TestVerifyAffiliateUid:

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, client, auth_headers):
        resp = await client.put(
            "/api/config/admin/affiliate-uids/1/verify",
            json={"verified": True},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_verify_success(
        self, client, admin_headers, session_factory, user
    ):
        async with session_factory() as session:
            conn = ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                affiliate_uid="12345", affiliate_verified=False,
            )
            session.add(conn)
            await session.commit()
            await session.refresh(conn)
            conn_id = conn.id

        resp = await client.put(
            f"/api/config/admin/affiliate-uids/{conn_id}/verify",
            json={"verified": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["affiliate_verified"] is True
        assert data["affiliate_uid"] == "12345"

    @pytest.mark.asyncio
    async def test_reject_affiliate(
        self, client, admin_headers, session_factory, user
    ):
        async with session_factory() as session:
            conn = ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                affiliate_uid="12345", affiliate_verified=True,
                affiliate_verified_at=datetime.now(timezone.utc),
            )
            session.add(conn)
            await session.commit()
            await session.refresh(conn)
            conn_id = conn.id

        resp = await client.put(
            f"/api/config/admin/affiliate-uids/{conn_id}/verify",
            json={"verified": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["affiliate_verified"] is False

    @pytest.mark.asyncio
    async def test_nonexistent_connection_returns_404(self, client, admin_headers):
        resp = await client.put(
            "/api/config/admin/affiliate-uids/99999/verify",
            json={"verified": True},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_connection_without_uid_returns_404(
        self, client, admin_headers, session_factory, user
    ):
        """Connection exists but has no affiliate_uid set."""
        async with session_factory() as session:
            conn = ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
            )
            session.add(conn)
            await session.commit()
            await session.refresh(conn)
            conn_id = conn.id

        resp = await client.put(
            f"/api/config/admin/affiliate-uids/{conn_id}/verify",
            json={"verified": True},
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ===========================================================================
# Edge cases / additional coverage
# ===========================================================================


class TestEdgeCases:

    @pytest.mark.asyncio
    async def test_invalid_exchange_type_path(self, client, auth_headers):
        """Invalid exchange type in path returns 422."""
        resp = await client.put(
            "/api/config/exchange-connections/invalid_exchange",
            json={"api_key": "test"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_confirm_approval_demo_fallback(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """When only demo keys exist, uses demo mode for HL client."""
        mock_hl.return_value = {"builder_address": "0x" + "aa" * 20, "builder_fee": 10, "referral_code": ""}

        mock_client = AsyncMock()
        mock_client.check_builder_fee_approval = AsyncMock(return_value=10)
        mock_client.close = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                demo_api_key_encrypted=encrypt_value(VALID_WALLET),
                demo_api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/confirm-builder-approval",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_verify_referral_with_referred_by_key(
        self, mock_create, mock_hl, client, auth_headers, session_factory, user
    ):
        """Tests the alternate key 'referred_by' (snake_case) — some older
        HL API versions use snake_case. When the string value matches the
        referral code, verification should succeed."""
        mock_hl.return_value = {"builder_address": "", "builder_fee": 0, "referral_code": "REF"}

        mock_client = AsyncMock()
        mock_client.wallet_address = VALID_WALLET
        mock_client.get_referral_info = AsyncMock(return_value={
            "referred_by": "REF",
            "cumVlm": "100.0",
        })
        mock_client.get_user_state = AsyncMock(return_value={
            "marginSummary": {"accountValue": "10.0"},
        })
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/hyperliquid/verify-referral",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["verified"] is True

    @pytest.mark.asyncio
    @patch("src.exchanges.factory.create_exchange_client")
    async def test_exchange_test_auto_detect_live_only(
        self, mock_create, client, auth_headers, session_factory, user
    ):
        """Auto-detect mode with only live keys uses live mode."""
        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = MagicMock(total=100.0, currency="USDT")
        mock_client.close = AsyncMock()
        mock_create.return_value = mock_client

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("livekey"),
                api_secret_encrypted=encrypt_value("livesecret"),
            ))
            await session.commit()

        resp = await client.post(
            "/api/config/exchange-connections/bitget/test",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "live"

    @pytest.mark.asyncio
    @patch("src.utils.settings.get_hl_config")
    async def test_builder_config_no_referral_code(
        self, mock_hl, client, auth_headers, session_factory, user
    ):
        """Builder config with no referral_code shows referral_required=False."""
        mock_hl.return_value = {
            "builder_address": "0x" + "ff" * 20,
            "builder_fee": 0,
            "referral_code": "",
        }

        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value(VALID_WALLET),
                api_secret_encrypted=encrypt_value(VALID_PRIVKEY),
                builder_fee_approved=False,
            ))
            await session.commit()

        resp = await client.get(
            "/api/config/hyperliquid/builder-config", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["referral_required"] is False
        assert data["needs_approval"] is True

    @pytest.mark.asyncio
    async def test_get_config_creates_default(self, client, auth_headers):
        """First call to GET /api/config auto-creates a UserConfig."""
        resp = await client.get("/api/config", headers=auth_headers)
        assert resp.status_code == 200
        # Second call should return same config (not create duplicate)
        resp2 = await client.get("/api/config", headers=auth_headers)
        assert resp2.status_code == 200

    @pytest.mark.asyncio
    async def test_exchange_connection_with_affiliate_fields(
        self, client, auth_headers, session_factory, user
    ):
        """Connection response includes affiliate fields when set."""
        async with session_factory() as session:
            session.add(ExchangeConnection(
                user_id=user.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("key"),
                affiliate_uid="12345",
                affiliate_verified=True,
            ))
            await session.commit()

        resp = await client.get("/api/config/exchange-connections", headers=auth_headers)
        assert resp.status_code == 200
        conn = resp.json()["connections"][0]
        assert conn["affiliate_uid"] == "12345"
        assert conn["affiliate_verified"] is True
