"""
Unit tests for the bots router (src/api/routers/bots.py).

Tests endpoint functions directly with mocked database sessions and
dependencies. Covers CRUD, lifecycle, statistics,
comparison, helper functions, and edge cases.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
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
    BotConfig,
    ExchangeConnection,
    TradeRecord,
    User,
)
from src.auth.password import hash_password  # noqa: E402
from src.auth.jwt_handler import create_access_token  # noqa: E402
from src.errors import (  # noqa: E402
    ERR_BOT_NOT_FOUND,
    ERR_BOT_NOT_RUNNING,
    ERR_MAX_BOTS_REACHED,
    ERR_STOP_BOT_BEFORE_EDIT,
    ERR_TELEGRAM_NOT_CONFIGURED,
)

# Reset Fernet singleton so it uses our test key
import src.utils.encryption as _enc_mod  # noqa: E402
_enc_mod._fernet = None


# ---------------------------------------------------------------------------
# Strategy registration helper
# ---------------------------------------------------------------------------

def _register_test_strategy():
    """Register a minimal test strategy so bot CRUD works."""
    from src.strategy.base import BaseStrategy, StrategyRegistry, TradeSignal

    if "test_strategy" in StrategyRegistry._strategies:
        return

    class TestStrategy(BaseStrategy):
        async def generate_signal(self, symbol: str) -> TradeSignal:
            raise NotImplementedError

        async def should_trade(self, signal) -> tuple:
            return False, "Test strategy never trades"

        @classmethod
        def get_param_schema(cls) -> dict:
            return {
                "test_param": {
                    "type": "int",
                    "label": "Test Parameter",
                    "description": "A test parameter",
                    "default": 42,
                }
            }

        @classmethod
        def get_description(cls) -> str:
            return "Test strategy for unit testing"

    StrategyRegistry.register("test_strategy", TestStrategy)


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

    _register_test_strategy()

    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import auth, bots, config, status
    from src.models.session import get_db

    limiter.enabled = False

    test_app = FastAPI(title="Test Bots API")
    test_app.state.limiter = limiter
    test_app.state.orchestrator = mock_orchestrator
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    test_app.include_router(auth.router)
    test_app.include_router(status.router)
    test_app.include_router(config.router)
    test_app.include_router(bots.router)

    test_app.dependency_overrides[get_db] = override_get_db

    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_user(test_engine) -> User:
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        user = User(
            username="botuser",
            email="botuser@test.com",
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
    """Non-admin user for testing gate enforcement."""
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
async def auth_headers(test_user) -> dict:
    token_data = {"sub": str(test_user.id), "role": test_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def regular_auth_headers(regular_user) -> dict:
    token_data = {"sub": str(regular_user.id), "role": regular_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def sample_bot(test_engine, test_user) -> BotConfig:
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        config = BotConfig(
            user_id=test_user.id,
            name="Test Bot Alpha",
            description="A test bot",
            strategy_type="test_strategy",
            exchange_type="bitget",
            mode="demo",
            trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT"]),
            leverage=4,
            position_size_percent=7.5,
            max_trades_per_day=2,
            take_profit_percent=4.0,
            stop_loss_percent=1.5,
            daily_loss_limit_percent=5.0,
            is_enabled=False,
        )
        session.add(config)
        await session.commit()
        await session.refresh(config)
        return config


@pytest_asyncio.fixture
async def sample_bot_with_trades(test_engine, test_user, sample_bot) -> BotConfig:
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    now = datetime.now(timezone.utc)
    trades = [
        TradeRecord(
            user_id=test_user.id,
            bot_config_id=sample_bot.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Bot trade 1",
            order_id="bot_001",
            status="closed",
            pnl=10.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            entry_time=now - timedelta(days=5),
            exit_time=now - timedelta(days=4),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=test_user.id,
            bot_config_id=sample_bot.id,
            symbol="BTCUSDT",
            side="short",
            size=0.01,
            entry_price=96000.0,
            exit_price=96500.0,
            take_profit=95000.0,
            stop_loss=97000.0,
            leverage=4,
            confidence=65,
            reason="Bot trade 2",
            order_id="bot_002",
            status="closed",
            pnl=-5.0,
            pnl_percent=-0.52,
            fees=0.3,
            funding_paid=0.05,
            entry_time=now - timedelta(days=3),
            exit_time=now - timedelta(days=2),
            exit_reason="STOP_LOSS",
            exchange="bitget",
            demo_mode=True,
        ),
    ]
    async with factory() as session:
        session.add_all(trades)
        await session.commit()
    return sample_bot


# ---------------------------------------------------------------------------
# Helper: _config_to_response
# ---------------------------------------------------------------------------


class TestConfigToResponse:
    """Tests for the _config_to_response helper function."""

    def test_config_to_response_basic(self):
        from src.api.routers.bots import _config_to_response

        config = MagicMock()
        config.id = 1
        config.name = "Test Bot"
        config.description = "Description"
        config.strategy_type = "test_strategy"
        config.exchange_type = "bitget"
        config.mode = "demo"
        config.margin_mode = "cross"
        config.trading_pairs = json.dumps(["BTCUSDT"])
        config.leverage = 4
        config.position_size_percent = 7.5
        config.max_trades_per_day = 2
        config.take_profit_percent = 4.0
        config.stop_loss_percent = 1.5
        config.daily_loss_limit_percent = 5.0
        config.per_asset_config = None
        config.strategy_params = None
        config.schedule_type = "market_sessions"
        config.schedule_config = None
        config.rotation_enabled = False
        config.rotation_interval_minutes = None
        config.rotation_start_time = None
        config.is_enabled = False
        config.discord_webhook_url = None
        config.telegram_bot_token = None
        config.telegram_chat_id = None
        config.created_at = datetime(2025, 1, 1)
        config.updated_at = datetime(2025, 1, 2)

        result = _config_to_response(config)
        assert result.id == 1
        assert result.name == "Test Bot"
        assert result.trading_pairs == ["BTCUSDT"]
        assert result.is_enabled is False
        assert result.discord_webhook_configured is False
        assert result.telegram_configured is False

    def test_config_to_response_invalid_trading_pairs_json(self):
        from src.api.routers.bots import _config_to_response

        config = MagicMock()
        config.id = 2
        config.name = "Bad JSON Bot"
        config.description = None
        config.strategy_type = "test_strategy"
        config.exchange_type = "bitget"
        config.mode = "demo"
        config.margin_mode = "cross"
        config.trading_pairs = "not-valid-json"
        config.leverage = None
        config.position_size_percent = None
        config.max_trades_per_day = None
        config.take_profit_percent = None
        config.stop_loss_percent = None
        config.daily_loss_limit_percent = None
        config.per_asset_config = None
        config.strategy_params = "{bad json"
        config.schedule_type = "market_sessions"
        config.schedule_config = "also bad"
        config.rotation_enabled = None
        config.rotation_interval_minutes = None
        config.rotation_start_time = None
        config.is_enabled = False
        config.discord_webhook_url = None
        config.telegram_bot_token = None
        config.telegram_chat_id = None
        config.created_at = None
        config.updated_at = None

        result = _config_to_response(config)
        assert result.trading_pairs == []
        assert result.strategy_params is None
        assert result.schedule_config is None
        assert result.created_at is None

    def test_config_to_response_with_discord_and_telegram(self):
        from src.api.routers.bots import _config_to_response

        config = MagicMock()
        config.id = 3
        config.name = "Notified Bot"
        config.description = None
        config.strategy_type = "test_strategy"
        config.exchange_type = "bitget"
        config.mode = "live"
        config.margin_mode = "cross"
        config.trading_pairs = json.dumps(["ETHUSDT"])
        config.leverage = 5
        config.position_size_percent = 10.0
        config.max_trades_per_day = 3
        config.take_profit_percent = 5.0
        config.stop_loss_percent = 2.0
        config.daily_loss_limit_percent = 8.0
        config.per_asset_config = json.dumps({"ETHUSDT": {"leverage": 3}})
        config.strategy_params = json.dumps({"threshold": 0.7})
        config.schedule_type = "interval"
        config.schedule_config = json.dumps({"interval_minutes": 60})
        config.rotation_enabled = True
        config.rotation_interval_minutes = 120
        config.rotation_start_time = "08:00"
        config.is_enabled = True
        config.discord_webhook_url = "encrypted_webhook"
        config.telegram_bot_token = "encrypted_token"
        config.telegram_chat_id = "12345"
        config.created_at = datetime(2025, 3, 1)
        config.updated_at = datetime(2025, 3, 2)

        result = _config_to_response(config)
        assert result.discord_webhook_configured is True
        assert result.telegram_configured is True
        assert result.per_asset_config == {"ETHUSDT": {"leverage": 3}}
        assert result.strategy_params == {"threshold": 0.7}
        assert result.schedule_config == {"interval_minutes": 60}

    def test_config_to_response_invalid_per_asset_json(self):
        from src.api.routers.bots import _config_to_response

        config = MagicMock()
        config.id = 4
        config.name = "Bad Asset Config"
        config.description = None
        config.strategy_type = "test_strategy"
        config.exchange_type = "bitget"
        config.mode = "demo"
        config.margin_mode = "cross"
        config.trading_pairs = json.dumps([])
        config.leverage = None
        config.position_size_percent = None
        config.max_trades_per_day = None
        config.take_profit_percent = None
        config.stop_loss_percent = None
        config.daily_loss_limit_percent = None
        config.per_asset_config = "bad json"
        config.strategy_params = None
        config.schedule_type = "market_sessions"
        config.schedule_config = None
        config.rotation_enabled = False
        config.rotation_interval_minutes = None
        config.rotation_start_time = None
        config.is_enabled = False
        config.discord_webhook_url = None
        config.telegram_bot_token = None
        config.telegram_chat_id = None
        config.created_at = None
        config.updated_at = None

        result = _config_to_response(config)
        assert result.per_asset_config is None


# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------


class TestOrchestratorHelpers:
    """Tests for get_orchestrator dependency."""

    def test_get_orchestrator_not_initialized(self):
        from src.api.routers.bots import get_orchestrator
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.app.state = MagicMock(spec=[])  # no 'orchestrator' attr
        with pytest.raises(HTTPException) as exc_info:
            get_orchestrator(mock_request)
        assert exc_info.value.status_code == 503

    def test_get_orchestrator_returns_from_app_state(self, mock_orchestrator):
        from src.api.routers.bots import get_orchestrator

        mock_request = MagicMock()
        mock_request.app.state.orchestrator = mock_orchestrator
        result = get_orchestrator(mock_request)
        assert result is mock_orchestrator


# ---------------------------------------------------------------------------
# CREATE bot
# ---------------------------------------------------------------------------


class TestCreateBot:

    async def test_create_bot_success(self, client, auth_headers, test_user):
        body = {
            "name": "New Test Bot",
            "description": "Testing create",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
            "trading_pairs": ["BTCUSDT"],
            "leverage": 4,
            "position_size_percent": 7.5,
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Test Bot"
        assert data["strategy_type"] == "test_strategy"
        assert data["is_enabled"] is False
        assert data["id"] > 0

    async def test_create_bot_invalid_strategy(self, client, auth_headers, test_user):
        body = {
            "name": "Bad Strategy",
            "strategy_type": "nonexistent",
            "exchange_type": "bitget",
            "mode": "demo",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 400

    async def test_create_bot_invalid_exchange(self, client, auth_headers, test_user):
        body = {
            "name": "Bad Exchange",
            "strategy_type": "test_strategy",
            "exchange_type": "invalid_exchange",
            "mode": "demo",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 422

    async def test_create_bot_invalid_mode(self, client, auth_headers, test_user):
        body = {
            "name": "Bad Mode",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "invalid_mode",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 422

    async def test_create_bot_with_discord_webhook(self, client, auth_headers, test_user):
        body = {
            "name": "Discord Bot",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
            "discord_webhook_url": "https://discord.com/api/webhooks/test",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["discord_webhook_configured"] is True

    async def test_create_bot_with_telegram(self, client, auth_headers, test_user):
        body = {
            "name": "Telegram Bot",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
            "telegram_bot_token": "123:ABC",
            "telegram_chat_id": "456",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["telegram_configured"] is True

    async def test_create_bot_with_strategy_params(self, client, auth_headers, test_user):
        body = {
            "name": "Params Bot",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
            "strategy_params": {"threshold": 0.8, "window": 14},
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy_params"]["threshold"] == 0.8

    async def test_create_bot_with_schedule(self, client, auth_headers, test_user):
        body = {
            "name": "Scheduled Bot",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
            "schedule_type": "interval",
            "schedule_config": {"interval_minutes": 60},
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["schedule_type"] == "interval"
        assert data["schedule_config"]["interval_minutes"] == 60

    async def test_create_bot_with_per_asset_config(self, client, auth_headers, test_user):
        body = {
            "name": "Per Asset Bot",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
            "per_asset_config": {"BTCUSDT": {"position_pct": 10, "leverage": 5}},
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["per_asset_config"]["BTCUSDT"]["position_pct"] == 10

    async def test_create_bot_max_limit(self, client, auth_headers, test_user):
        """Creating more than MAX_BOTS_PER_USER bots returns 400."""
        for i in range(10):
            body = {
                "name": f"Bot {i}",
                "strategy_type": "test_strategy",
                "exchange_type": "bitget",
                "mode": "demo",
            }
            resp = await client.post("/api/bots", json=body, headers=auth_headers)
            assert resp.status_code == 200

        body = {
            "name": "Bot 11 - over limit",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_MAX_BOTS_REACHED.format(max_bots=10)

    async def test_create_bot_requires_auth(self, client, test_user):
        body = {
            "name": "No Auth Bot",
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
        }
        resp = await client.post("/api/bots", json=body)
        assert resp.status_code == 401

    async def test_create_bot_hyperliquid(self, client, auth_headers, test_user, monkeypatch):
        from unittest.mock import AsyncMock
        monkeypatch.setattr(
            "src.api.routers.bots.get_exchange_symbols",
            AsyncMock(return_value=["BTCUSDT"]),
        )
        body = {
            "name": "HL Bot",
            "strategy_type": "test_strategy",
            "exchange_type": "hyperliquid",
            "mode": "demo",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["exchange_type"] == "hyperliquid"

    async def test_create_bot_weex(self, client, auth_headers, test_user):
        body = {
            "name": "Weex Bot",
            "strategy_type": "test_strategy",
            "exchange_type": "weex",
            "mode": "demo",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["exchange_type"] == "weex"

    async def test_create_bot_missing_name(self, client, auth_headers, test_user):
        body = {
            "strategy_type": "test_strategy",
            "exchange_type": "bitget",
            "mode": "demo",
        }
        resp = await client.post("/api/bots", json=body, headers=auth_headers)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# LIST bots
# ---------------------------------------------------------------------------


class TestListBots:

    async def test_list_bots_success(self, client, auth_headers, sample_bot):
        resp = await client.get("/api/bots", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "bots" in data
        assert len(data["bots"]) >= 1
        bot = data["bots"][0]
        assert bot["name"] == "Test Bot Alpha"

    async def test_list_bots_empty(self, client, auth_headers, test_user):
        resp = await client.get("/api/bots", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["bots"] == []

    async def test_list_bots_demo_mode_filter(self, client, auth_headers, sample_bot):
        resp = await client.get(
            "/api/bots", headers=auth_headers, params={"demo_mode": True}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["bots"]) >= 1
        for bot in data["bots"]:
            assert bot["mode"] in ["demo", "both"]

    async def test_list_bots_live_mode_filter(self, client, auth_headers, sample_bot):
        resp = await client.get(
            "/api/bots", headers=auth_headers, params={"demo_mode": False}
        )
        assert resp.status_code == 200
        data = resp.json()
        for bot in data["bots"]:
            assert bot["mode"] in ["live", "both"]

    async def test_list_bots_requires_auth(self, client, test_user):
        resp = await client.get("/api/bots")
        assert resp.status_code == 401

    async def test_list_bots_includes_trade_stats(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get("/api/bots", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        bot = data["bots"][0]
        assert bot["total_trades"] == 2
        assert bot["total_pnl"] == 5.0  # 10 + (-5)
        assert bot["total_fees"] == 0.8  # 0.5 + 0.3

    async def test_list_bots_runtime_status_fields(self, client, auth_headers, sample_bot):
        resp = await client.get("/api/bots", headers=auth_headers)
        assert resp.status_code == 200
        bot = resp.json()["bots"][0]
        assert "status" in bot
        assert "trades_today" in bot
        assert "is_enabled" in bot
        assert "open_trades" in bot


# ---------------------------------------------------------------------------
# GET bot by ID
# ---------------------------------------------------------------------------


class TestGetBot:

    async def test_get_bot_success(self, client, auth_headers, sample_bot):
        resp = await client.get(f"/api/bots/{sample_bot.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sample_bot.id
        assert data["name"] == "Test Bot Alpha"
        assert data["trading_pairs"] == ["BTCUSDT", "ETHUSDT"]

    async def test_get_bot_not_found(self, client, auth_headers, test_user):
        resp = await client.get("/api/bots/99999", headers=auth_headers)
        assert resp.status_code == 404
        assert ERR_BOT_NOT_FOUND in resp.json()["detail"]

    async def test_get_bot_requires_auth(self, client, test_user):
        resp = await client.get("/api/bots/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# UPDATE bot
# ---------------------------------------------------------------------------


class TestUpdateBot:

    async def test_update_bot_name(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"name": "Updated Name"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    async def test_update_bot_leverage(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"leverage": 8},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["leverage"] == 8

    async def test_update_bot_trading_pairs(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"trading_pairs": ["SOLUSDT"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["trading_pairs"] == ["SOLUSDT"]

    async def test_update_bot_not_found(self, client, auth_headers, test_user):
        resp = await client.put(
            "/api/bots/99999",
            json={"name": "Ghost"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_update_bot_while_running(self, client, auth_headers, sample_bot, mock_orchestrator):
        mock_orchestrator.is_running.return_value = True
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"name": "Should Fail"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert ERR_STOP_BOT_BEFORE_EDIT in resp.json()["detail"]
        mock_orchestrator.is_running.return_value = False

    async def test_update_bot_invalid_strategy(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"strategy_type": "nonexistent_strategy"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    async def test_update_bot_strategy_params(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"strategy_params": {"window": 20}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["strategy_params"]["window"] == 20

    async def test_update_bot_discord_webhook(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"discord_webhook_url": "https://discord.com/api/webhooks/new"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["discord_webhook_configured"] is True

    async def test_update_bot_clear_discord_webhook(self, client, auth_headers, sample_bot):
        # First set a webhook
        await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"discord_webhook_url": "https://discord.com/api/webhooks/new"},
            headers=auth_headers,
        )
        # Then clear it
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"discord_webhook_url": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["discord_webhook_configured"] is False

    async def test_update_bot_schedule_config(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"schedule_config": {"hours": [1, 8, 14, 21]}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["schedule_config"]["hours"] == [1, 8, 14, 21]

    async def test_update_bot_per_asset_config(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"per_asset_config": {"BTCUSDT": {"leverage": 3}}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["per_asset_config"]["BTCUSDT"]["leverage"] == 3

    async def test_update_bot_telegram(self, client, auth_headers, sample_bot):
        resp = await client.put(
            f"/api/bots/{sample_bot.id}",
            json={"telegram_bot_token": "123:ABC", "telegram_chat_id": "999"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["telegram_configured"] is True


# ---------------------------------------------------------------------------
# DELETE bot
# ---------------------------------------------------------------------------


class TestDeleteBot:

    async def test_delete_bot_success(self, client, auth_headers, sample_bot):
        resp = await client.delete(f"/api/bots/{sample_bot.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Verify gone
        resp2 = await client.get(f"/api/bots/{sample_bot.id}", headers=auth_headers)
        assert resp2.status_code == 404

    async def test_delete_bot_not_found(self, client, auth_headers, test_user):
        resp = await client.delete("/api/bots/99999", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_running_bot_stops_first(self, client, auth_headers, sample_bot, mock_orchestrator):
        mock_orchestrator.is_running.return_value = True
        resp = await client.delete(f"/api/bots/{sample_bot.id}", headers=auth_headers)
        assert resp.status_code == 200
        mock_orchestrator.stop_bot.assert_called_once_with(sample_bot.id)
        mock_orchestrator.is_running.return_value = False


# ---------------------------------------------------------------------------
# DUPLICATE bot
# ---------------------------------------------------------------------------


class TestDuplicateBot:

    async def test_duplicate_bot_success(self, client, auth_headers, sample_bot):
        resp = await client.post(
            f"/api/bots/{sample_bot.id}/duplicate", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Bot Alpha (Copy)"
        assert data["is_enabled"] is False
        assert data["id"] != sample_bot.id

    async def test_duplicate_bot_not_found(self, client, auth_headers, test_user):
        resp = await client.post("/api/bots/99999/duplicate", headers=auth_headers)
        assert resp.status_code == 404

    async def test_duplicate_bot_respects_limit(self, client, auth_headers, test_user):
        """Cannot duplicate if at max bots."""
        for i in range(10):
            body = {
                "name": f"Limit Bot {i}",
                "strategy_type": "test_strategy",
                "exchange_type": "bitget",
                "mode": "demo",
            }
            await client.post("/api/bots", json=body, headers=auth_headers)

        # Create one more via create to get an ID, but we already hit the limit
        # The 10th bot exists, try to duplicate it
        list_resp = await client.get("/api/bots", headers=auth_headers)
        first_bot_id = list_resp.json()["bots"][-1]["bot_config_id"]

        resp = await client.post(
            f"/api/bots/{first_bot_id}/duplicate", headers=auth_headers
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == ERR_MAX_BOTS_REACHED.format(max_bots=10)


# ---------------------------------------------------------------------------
# LIFECYCLE: start / stop / restart / stop-all
# ---------------------------------------------------------------------------


class TestBotLifecycle:

    async def test_start_bot_success(self, client, auth_headers, sample_bot):
        resp = await client.post(
            f"/api/bots/{sample_bot.id}/start", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_start_bot_not_found(self, client, auth_headers, test_user):
        resp = await client.post("/api/bots/99999/start", headers=auth_headers)
        assert resp.status_code == 404

    async def test_start_bot_orchestrator_error(self, client, auth_headers, sample_bot, mock_orchestrator):
        mock_orchestrator.start_bot.side_effect = ValueError("Already running")
        resp = await client.post(
            f"/api/bots/{sample_bot.id}/start", headers=auth_headers
        )
        assert resp.status_code == 400
        assert "Already running" in resp.json()["detail"]
        mock_orchestrator.start_bot.side_effect = None

    async def test_stop_bot_success(self, client, auth_headers, sample_bot):
        resp = await client.post(
            f"/api/bots/{sample_bot.id}/stop", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_stop_bot_not_found(self, client, auth_headers, test_user):
        resp = await client.post("/api/bots/99999/stop", headers=auth_headers)
        assert resp.status_code == 404

    async def test_stop_bot_not_running(self, client, auth_headers, sample_bot, mock_orchestrator):
        mock_orchestrator.stop_bot.return_value = False
        resp = await client.post(
            f"/api/bots/{sample_bot.id}/stop", headers=auth_headers
        )
        assert resp.status_code == 400
        assert ERR_BOT_NOT_RUNNING in resp.json()["detail"]
        mock_orchestrator.stop_bot.return_value = True

    async def test_restart_bot_success(self, client, auth_headers, sample_bot):
        resp = await client.post(
            f"/api/bots/{sample_bot.id}/restart", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_restart_bot_not_found(self, client, auth_headers, test_user):
        resp = await client.post("/api/bots/99999/restart", headers=auth_headers)
        assert resp.status_code == 404

    async def test_restart_bot_orchestrator_error(self, client, auth_headers, sample_bot, mock_orchestrator):
        mock_orchestrator.restart_bot.side_effect = ValueError("Cannot restart")
        resp = await client.post(
            f"/api/bots/{sample_bot.id}/restart", headers=auth_headers
        )
        assert resp.status_code == 400
        mock_orchestrator.restart_bot.side_effect = None

    async def test_stop_all_bots(self, client, auth_headers, test_user, mock_orchestrator):
        mock_orchestrator.stop_all_for_user.return_value = 3
        resp = await client.post("/api/bots/stop-all", headers=auth_headers)
        assert resp.status_code == 200
        assert "3" in resp.json()["message"]


# ---------------------------------------------------------------------------
# STRATEGIES endpoint
# ---------------------------------------------------------------------------


class TestStrategies:

    async def test_list_strategies(self, client, auth_headers, test_user):
        resp = await client.get("/api/bots/strategies", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "strategies" in data
        names = [s["name"] for s in data["strategies"]]
        assert "test_strategy" in names

    async def test_list_strategies_requires_auth(self, client, test_user):
        resp = await client.get("/api/bots/strategies")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DATA SOURCES endpoint
# ---------------------------------------------------------------------------


class TestDataSources:

    async def test_list_data_sources(self, client, auth_headers, test_user):
        resp = await client.get("/api/bots/data-sources", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "sources" in data
        assert "defaults" in data
        assert isinstance(data["sources"], list)

    async def test_list_data_sources_requires_auth(self, client, test_user):
        resp = await client.get("/api/bots/data-sources")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# STATISTICS
# ---------------------------------------------------------------------------


class TestBotStatistics:

    async def test_get_bot_statistics(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            f"/api/bots/{sample_bot_with_trades.id}/statistics",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bot_id"] == sample_bot_with_trades.id
        assert "summary" in data
        assert "daily_series" in data
        assert "recent_trades" in data
        assert data["summary"]["total_trades"] == 2
        assert data["summary"]["wins"] == 1
        assert data["summary"]["losses"] == 1

    async def test_get_bot_statistics_not_found(self, client, auth_headers, test_user):
        resp = await client.get("/api/bots/99999/statistics", headers=auth_headers)
        assert resp.status_code == 404

    async def test_get_bot_statistics_demo_filter(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            f"/api/bots/{sample_bot_with_trades.id}/statistics",
            headers=auth_headers,
            params={"demo_mode": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_trades"] == 2

    async def test_get_bot_statistics_custom_days(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            f"/api/bots/{sample_bot_with_trades.id}/statistics",
            headers=auth_headers,
            params={"days": 7},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["days"] == 7

    async def test_get_bot_statistics_cumulative_pnl(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            f"/api/bots/{sample_bot_with_trades.id}/statistics",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        series = resp.json()["daily_series"]
        if len(series) > 0:
            for entry in series:
                assert "cumulative_pnl" in entry
                assert "pnl" in entry
                assert "date" in entry
                assert "fees" in entry
                assert "funding" in entry

    async def test_get_bot_statistics_recent_trades(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            f"/api/bots/{sample_bot_with_trades.id}/statistics",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        trades = resp.json()["recent_trades"]
        assert len(trades) == 2
        for trade in trades:
            assert "id" in trade
            assert "symbol" in trade
            assert "pnl" in trade
            assert "fees" in trade

    async def test_get_bot_statistics_no_trades(self, client, auth_headers, sample_bot):
        resp = await client.get(
            f"/api/bots/{sample_bot.id}/statistics",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_trades"] == 0
        assert data["summary"]["win_rate"] == 0.0


# ---------------------------------------------------------------------------
# COMPARE performance
# ---------------------------------------------------------------------------


class TestComparePerformance:

    async def test_compare_bots(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            "/api/bots/compare/performance", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "days" in data
        assert "bots" in data
        assert len(data["bots"]) >= 1
        bot = data["bots"][0]
        assert "total_trades" in bot
        assert "total_pnl" in bot
        assert "win_rate" in bot
        assert "series" in bot

    async def test_compare_bots_empty(self, client, auth_headers, test_user):
        resp = await client.get(
            "/api/bots/compare/performance", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["bots"] == []

    async def test_compare_bots_demo_filter(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            "/api/bots/compare/performance",
            headers=auth_headers,
            params={"demo_mode": True},
        )
        assert resp.status_code == 200
        assert len(resp.json()["bots"]) >= 1

    async def test_compare_bots_live_filter(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            "/api/bots/compare/performance",
            headers=auth_headers,
            params={"demo_mode": False},
        )
        assert resp.status_code == 200
        # sample_bot is mode=demo, should not appear with demo_mode=False
        for bot in resp.json()["bots"]:
            assert bot["mode"] in ["live", "both"]

    async def test_compare_bots_custom_days(self, client, auth_headers, sample_bot_with_trades):
        resp = await client.get(
            "/api/bots/compare/performance",
            headers=auth_headers,
            params={"days": 7},
        )
        assert resp.status_code == 200
        assert resp.json()["days"] == 7


# ---------------------------------------------------------------------------
# TEST TELEGRAM
# ---------------------------------------------------------------------------


class TestTelegramTest:

    async def test_telegram_bot_not_found(self, client, auth_headers, test_user):
        resp = await client.post("/api/bots/99999/test-telegram", headers=auth_headers)
        assert resp.status_code == 404

    async def test_telegram_not_configured(self, client, auth_headers, sample_bot):
        resp = await client.post(
            f"/api/bots/{sample_bot.id}/test-telegram", headers=auth_headers
        )
        assert resp.status_code == 400
        assert ERR_TELEGRAM_NOT_CONFIGURED in resp.json()["detail"]


# ---------------------------------------------------------------------------
# CLOSE POSITION: RSM classify_close wiring (ARCH-C1a manual — Issue #245)
# ---------------------------------------------------------------------------


class TestClosePositionClassifyClose:
    """Manual-close endpoint must route through RiskStateManager.classify_close
    when the feature flag is on, mirroring the sync_trades path (PR #244)."""

    @pytest_asyncio.fixture
    async def open_trade_and_conn(self, test_engine, test_user, sample_bot):
        """Insert an open TradeRecord for BTCUSDT plus a bitget ExchangeConnection."""
        factory = async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False
        )
        now = datetime.now(timezone.utc)
        async with factory() as session:
            conn = ExchangeConnection(
                user_id=test_user.id,
                exchange_type="bitget",
                demo_api_key_encrypted="encrypted_key",
                demo_api_secret_encrypted="encrypted_secret",
            )
            trade = TradeRecord(
                user_id=test_user.id,
                bot_config_id=sample_bot.id,
                symbol="BTCUSDT",
                side="long",
                size=0.01,
                entry_price=95000.0,
                take_profit=97000.0,
                stop_loss=94000.0,
                leverage=4,
                confidence=70,
                reason="open manual-close test",
                order_id="manual_close_001",
                status="open",
                entry_time=now - timedelta(hours=2),
                exchange="bitget",
                demo_mode=True,
            )
            session.add_all([conn, trade])
            await session.commit()
            await session.refresh(trade)
            return trade

    async def _build_mock_client(self):
        """Exchange-client double: close succeeds, position is gone afterwards."""
        mock_client = AsyncMock()
        mock_client.close_position = AsyncMock(return_value=MagicMock())
        mock_client.get_position = AsyncMock(return_value=None)
        mock_client.get_close_fill_price = AsyncMock(return_value=96500.0)
        mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96500.0))
        return mock_client

    async def test_close_position_invokes_classify_close_when_rsm_enabled(
        self, client, auth_headers, sample_bot, open_trade_and_conn,
    ):
        """With the RSM flag on, classify_close is awaited after the close
        succeeds and its return value becomes the trade's exit_reason.
        The close must be verified before classify_close is consulted."""
        mock_client = await self._build_mock_client()

        fake_manager = MagicMock()
        fake_manager.classify_close = AsyncMock(return_value="MANUAL_CLOSE_UI")

        fake_settings = MagicMock()
        fake_settings.risk.risk_state_manager_enabled = True

        with patch(
            "src.exchanges.factory.create_exchange_client",
            return_value=mock_client,
        ), patch(
            "src.utils.encryption.decrypt_value",
            return_value="decrypted",
        ), patch(
            "src.api.routers.bots_lifecycle.settings",
            fake_settings,
        ), patch(
            "src.api.routers.bots_lifecycle.get_risk_state_manager",
            return_value=fake_manager,
        ):
            resp = await client.post(
                f"/api/bots/{sample_bot.id}/close-position/BTCUSDT",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # classify_close was invoked exactly once with (trade_id, exit_price, exit_time)
        fake_manager.classify_close.assert_awaited_once()
        call_args = fake_manager.classify_close.await_args
        # Positional args: (trade_id, exit_price, exit_time)
        assert call_args.args[0] == open_trade_and_conn.id
        assert call_args.args[1] == 96500.0

        # The position was cleared: a follow-up close on the same symbol
        # now returns 404 (no open trade), confirming the close path ran.
        resp_again = await client.post(
            f"/api/bots/{sample_bot.id}/close-position/BTCUSDT",
            headers=auth_headers,
        )
        assert resp_again.status_code == 404

    async def test_close_position_legacy_reason_when_rsm_disabled(
        self, client, auth_headers, sample_bot, open_trade_and_conn,
    ):
        """With the RSM flag off, classify_close is never called and
        exit_reason falls back to the legacy ``MANUAL_CLOSE`` literal."""
        mock_client = await self._build_mock_client()

        fake_manager = MagicMock()
        fake_manager.classify_close = AsyncMock(return_value="SHOULD_NOT_BE_USED")

        fake_settings = MagicMock()
        fake_settings.risk.risk_state_manager_enabled = False

        with patch(
            "src.exchanges.factory.create_exchange_client",
            return_value=mock_client,
        ), patch(
            "src.utils.encryption.decrypt_value",
            return_value="decrypted",
        ), patch(
            "src.api.routers.bots_lifecycle.settings",
            fake_settings,
        ), patch(
            "src.api.routers.bots_lifecycle.get_risk_state_manager",
            return_value=fake_manager,
        ):
            resp = await client.post(
                f"/api/bots/{sample_bot.id}/close-position/BTCUSDT",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        fake_manager.classify_close.assert_not_awaited()

    async def test_close_position_falls_back_on_classify_close_error(
        self, client, auth_headers, sample_bot, open_trade_and_conn,
    ):
        """If classify_close raises, the close still succeeds and
        exit_reason falls back to the legacy ``MANUAL_CLOSE`` literal."""
        mock_client = await self._build_mock_client()

        fake_manager = MagicMock()
        fake_manager.classify_close = AsyncMock(side_effect=RuntimeError("boom"))

        fake_settings = MagicMock()
        fake_settings.risk.risk_state_manager_enabled = True

        with patch(
            "src.exchanges.factory.create_exchange_client",
            return_value=mock_client,
        ), patch(
            "src.utils.encryption.decrypt_value",
            return_value="decrypted",
        ), patch(
            "src.api.routers.bots_lifecycle.settings",
            fake_settings,
        ), patch(
            "src.api.routers.bots_lifecycle.get_risk_state_manager",
            return_value=fake_manager,
        ):
            resp = await client.post(
                f"/api/bots/{sample_bot.id}/close-position/BTCUSDT",
                headers=auth_headers,
            )

        # Close still succeeded (200), classify_close failure is swallowed
        assert resp.status_code == 200
        fake_manager.classify_close.assert_awaited_once()
