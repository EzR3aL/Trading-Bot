"""
Comprehensive integration tests for src/api/routers/bots.py.

Uses direct async function calls to the router handlers with real
in-memory SQLite sessions, which ensures proper coverage tracking.
The orchestrator is mocked but all DB operations are real.

Targets: lines 56-1186 of bots.py (all endpoint function bodies).
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from src.models.database import (
    AffiliateLink,
    Base,
    BotConfig,
    ConfigPreset,
    ExchangeConnection,
    TradeRecord,
    User,
)
from src.auth.password import hash_password

# Disable rate limiter before importing bots
from src.api.routers.auth import limiter
limiter.enabled = False

from src.api.routers import bots as bots_module
from src.api.routers.bots import (
    _config_to_response,
    _enforce_affiliate_gate,
    _enforce_hl_gates,
    apply_preset_to_bot,
    compare_bots_performance,
    create_bot,
    delete_bot,
    duplicate_bot,
    get_bot,
    get_bot_statistics,
    get_orchestrator,
    list_bots,
    list_data_sources,
    list_strategies,
    restart_bot,
    set_orchestrator,
    start_bot,
    stop_all_bots,
    stop_bot,
    test_telegram as send_test_telegram,
    update_bot,
)
from src.api.schemas.bots import BotConfigCreate, BotConfigUpdate


# ---------------------------------------------------------------------------
# Strategy registration
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


_register_test_strategy()


# ---------------------------------------------------------------------------
# Fixtures
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
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def admin_user(factory):
    async with factory() as session:
        u = User(
            username="botadmin",
            email="botadmin@test.com",
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
async def regular_user(factory):
    async with factory() as session:
        u = User(
            username="botuser",
            email="botuser@test.com",
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
def mock_orchestrator():
    orch = MagicMock()
    orch.get_bot_status = MagicMock(return_value=None)
    orch.is_running = MagicMock(return_value=False)
    orch.start_bot = AsyncMock(return_value=True)
    orch.stop_bot = AsyncMock(return_value=True)
    orch.restart_bot = AsyncMock(return_value=True)
    orch.stop_all_for_user = AsyncMock(return_value=2)
    return orch


@pytest_asyncio.fixture(autouse=True)
async def setup_orchestrator(mock_orchestrator):
    """No-op — orchestrator is now passed explicitly to direct function calls."""
    yield


@pytest_asyncio.fixture
def mock_request():
    """Create a minimal Starlette Request for rate-limited endpoints."""
    scope = {"type": "http", "method": "POST", "path": "/api/bots", "headers": []}
    return Request(scope)


@pytest_asyncio.fixture
async def sample_bot(factory, admin_user):
    """Create a sample bot in the DB."""
    async with factory() as session:
        config = BotConfig(
            user_id=admin_user.id,
            name="Test Bot",
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
async def hl_bot(factory, regular_user):
    """Hyperliquid bot owned by regular user for gate testing."""
    async with factory() as session:
        config = BotConfig(
            user_id=regular_user.id,
            name="HL Bot",
            strategy_type="test_strategy",
            exchange_type="hyperliquid",
            mode="demo",
            trading_pairs=json.dumps(["BTC", "ETH"]),
            is_enabled=False,
        )
        session.add(config)
        await session.commit()
        await session.refresh(config)
        return config


@pytest_asyncio.fixture
async def bitget_bot_regular(factory, regular_user):
    """Bitget bot owned by regular user for affiliate gate testing."""
    async with factory() as session:
        config = BotConfig(
            user_id=regular_user.id,
            name="Bitget Regular Bot",
            strategy_type="test_strategy",
            exchange_type="bitget",
            mode="demo",
            trading_pairs=json.dumps(["BTCUSDT"]),
            is_enabled=False,
        )
        session.add(config)
        await session.commit()
        await session.refresh(config)
        return config


@pytest_asyncio.fixture
async def sample_preset(factory, admin_user):
    async with factory() as session:
        preset = ConfigPreset(
            user_id=admin_user.id,
            name="Aggressive Preset",
            description="High leverage aggressive settings",
            exchange_type="any",
            trading_config=json.dumps({
                "leverage": 10,
                "position_size_percent": 15.0,
                "max_trades_per_day": 5,
                "take_profit_percent": 6.0,
                "stop_loss_percent": 2.0,
                "daily_loss_limit_percent": 10.0,
            }),
            strategy_config=json.dumps({"threshold": 0.8}),
            trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
        )
        session.add(preset)
        await session.commit()
        await session.refresh(preset)
        return preset


# ---------------------------------------------------------------------------
# _config_to_response helper — lines 56-110
# ---------------------------------------------------------------------------


class TestConfigToResponse:
    """Test the _config_to_response helper function."""

    async def test_basic_config(self, sample_bot):
        """All fields populated correctly."""
        resp = _config_to_response(sample_bot)
        assert resp.id == sample_bot.id
        assert resp.name == "Test Bot"
        assert resp.trading_pairs == ["BTCUSDT", "ETHUSDT"]
        assert resp.leverage == 4
        assert resp.is_enabled is False
        assert resp.discord_webhook_configured is False
        assert resp.telegram_configured is False

    async def test_invalid_json_fields(self, factory, admin_user):
        """Handles invalid JSON gracefully (lines 60-80)."""
        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id,
                name="Bad JSON Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs="{invalid json",
                strategy_params="{broken",
                schedule_config="not json",
                per_asset_config="also bad",
                is_enabled=False,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)

        resp = _config_to_response(config)
        assert resp.trading_pairs == []
        assert resp.strategy_params is None
        assert resp.schedule_config is None
        assert resp.per_asset_config is None

    async def test_none_json_fields(self, admin_user):
        """Handles None JSON fields (lines 59, 65, 71, 77)."""
        # Build a BotConfig without persisting to avoid column defaults
        config = BotConfig(
            id=999,
            user_id=admin_user.id,
            name="None Fields Bot",
            strategy_type="test_strategy",
            exchange_type="bitget",
            mode="demo",
            trading_pairs=None,
            strategy_params=None,
            schedule_type="market_sessions",
            schedule_config=None,
            per_asset_config=None,
            is_enabled=False,
        )
        resp = _config_to_response(config)
        assert resp.trading_pairs == []
        assert resp.strategy_params is None
        assert resp.schedule_config is None
        assert resp.per_asset_config is None

    async def test_discord_and_telegram_flags(self, factory, admin_user):
        """discord_webhook_configured and telegram_configured (lines 104-105)."""
        from src.utils.encryption import encrypt_value

        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id,
                name="Notification Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                discord_webhook_url=encrypt_value("https://discord.com/webhook"),
                telegram_bot_token=encrypt_value("123:ABC"),
                telegram_chat_id="999",
                is_enabled=False,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)

        resp = _config_to_response(config)
        assert resp.discord_webhook_configured is True
        assert resp.telegram_configured is True

    async def test_rotation_fields(self, factory, admin_user):
        """rotation_enabled, rotation_interval_minutes, rotation_start_time (lines 100-102)."""
        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id,
                name="Rotation Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                rotation_enabled=True,
                rotation_interval_minutes=120,
                rotation_start_time="08:00",
                is_enabled=False,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)

        resp = _config_to_response(config)
        assert resp.rotation_enabled is True
        assert resp.rotation_interval_minutes == 120
        assert resp.rotation_start_time == "08:00"


# ---------------------------------------------------------------------------
# Strategies & Data Sources — lines 115-137
# ---------------------------------------------------------------------------


class TestStrategiesAndDataSources:

    async def test_list_strategies(self, admin_user):
        """List available strategies (lines 115-121)."""
        result = await list_strategies(user=admin_user)
        assert hasattr(result, "strategies")
        assert len(result.strategies) >= 1
        names = [s.name for s in result.strategies]
        assert "test_strategy" in names

    async def test_list_data_sources(self, admin_user):
        """List data sources (lines 124-137)."""
        result = await list_data_sources(user=admin_user)
        assert "sources" in result
        assert "defaults" in result
        assert isinstance(result["sources"], list)
        assert isinstance(result["defaults"], list)


# ---------------------------------------------------------------------------
# CREATE bot — lines 142-205
# ---------------------------------------------------------------------------


class TestCreateBot:

    async def test_create_minimal_bot(self, factory, admin_user, mock_request):
        """Create a bot with minimal fields (lines 142-205)."""
        async with factory() as session:
            body = BotConfigCreate(
                name="Minimal Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
            )
            result = await create_bot(request=mock_request, body=body, user=admin_user, db=session)
            await session.commit()

        assert result.name == "Minimal Bot"
        assert result.strategy_type == "test_strategy"
        assert result.exchange_type == "bitget"
        assert result.is_enabled is False
        assert result.trading_pairs == ["BTCUSDT"]

    async def test_create_bot_all_fields(self, factory, admin_user, mock_request):
        """Create a bot with all optional fields (lines 164-198)."""
        async with factory() as session:
            body = BotConfigCreate(
                name="Full Bot",
                description="Fully configured",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="live",
                trading_pairs=["BTCUSDT", "ETHUSDT"],
                leverage=5,
                position_size_percent=10.0,
                max_trades_per_day=3,
                take_profit_percent=5.0,
                stop_loss_percent=2.0,
                daily_loss_limit_percent=8.0,
                per_asset_config={"BTCUSDT": {"leverage": 3}},
                strategy_params={"window": 14, "threshold": 0.7},
                schedule_type="interval",
                schedule_config={"interval_minutes": 60},
                rotation_enabled=True,
                rotation_interval_minutes=120,
                rotation_start_time="08:00",
                discord_webhook_url="https://discord.com/api/webhooks/test/token",
                telegram_bot_token="123:ABCdef",
                telegram_chat_id="999888",
            )
            result = await create_bot(request=mock_request, body=body, user=admin_user, db=session)
            await session.commit()

        assert result.name == "Full Bot"
        assert result.description == "Fully configured"
        assert result.discord_webhook_configured is True
        assert result.telegram_configured is True
        assert result.per_asset_config == {"BTCUSDT": {"leverage": 3}}
        assert result.strategy_params == {"window": 14, "threshold": 0.7}
        assert result.schedule_config == {"interval_minutes": 60}
        assert result.rotation_enabled is True

    async def test_create_bot_invalid_strategy(self, factory, admin_user, mock_request):
        """Invalid strategy returns 400 (lines 152-155)."""
        from fastapi import HTTPException

        async with factory() as session:
            body = BotConfigCreate(
                name="Bad Strategy Bot",
                strategy_type="nonexistent_strategy",
                exchange_type="bitget",
            )
            with pytest.raises(HTTPException) as exc_info:
                await create_bot(request=mock_request, body=body, user=admin_user, db=session)
            assert exc_info.value.status_code == 400

    async def test_create_bot_max_limit(self, factory, admin_user, mock_request):
        """Exceed MAX_BOTS_PER_USER limit (lines 158-162)."""
        from fastapi import HTTPException

        # Pre-create 10 bots
        async with factory() as session:
            for i in range(10):
                session.add(BotConfig(
                    user_id=admin_user.id,
                    name=f"Limit Bot {i}",
                    strategy_type="test_strategy",
                    exchange_type="bitget",
                    mode="demo",
                    trading_pairs=json.dumps(["BTCUSDT"]),
                    is_enabled=False,
                ))
            await session.commit()

        async with factory() as session:
            body = BotConfigCreate(
                name="Bot 11",
                strategy_type="test_strategy",
                exchange_type="bitget",
            )
            with pytest.raises(HTTPException) as exc_info:
                await create_bot(request=mock_request, body=body, user=admin_user, db=session)
            assert exc_info.value.status_code == 400
            assert "Maximum" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# LIST bots — lines 208-441
# ---------------------------------------------------------------------------


class TestListBots:

    async def test_list_bots_empty(self, factory, admin_user, mock_orchestrator):
        """List bots for user with no bots (lines 208-441)."""
        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        assert result.bots == []

    async def test_list_bots_with_runtime_status(self, factory, admin_user, sample_bot, mock_orchestrator):
        """List bots with runtime status from orchestrator (lines 267-441)."""
        mock_orchestrator.get_bot_status.return_value = {
            "status": "running",
            "error_message": None,
            "started_at": "2025-01-01T00:00:00",
            "last_analysis": "2025-01-01T01:00:00",
            "trades_today": 3,
        }
        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        assert len(result.bots) >= 1
        bot = result.bots[0]
        assert bot.status == "running"
        assert bot.trades_today == 3

    async def test_list_bots_no_runtime_enabled(self, factory, admin_user, mock_orchestrator):
        """Enabled bot with no runtime shows 'stopped' (line 419)."""
        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id,
                name="Enabled Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=True,
            ))
            await session.commit()

        mock_orchestrator.get_bot_status.return_value = None
        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        enabled_bot = next((b for b in result.bots if b.name == "Enabled Bot"), None)
        assert enabled_bot is not None
        assert enabled_bot.status == "stopped"

    async def test_list_bots_no_runtime_disabled(self, factory, admin_user, mock_orchestrator):
        """Disabled bot with no runtime shows 'idle' (line 419)."""
        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id,
                name="Idle Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            ))
            await session.commit()

        mock_orchestrator.get_bot_status.return_value = None
        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        idle_bot = next((b for b in result.bots if b.name == "Idle Bot"), None)
        assert idle_bot is not None
        assert idle_bot.status == "idle"

    async def test_list_bots_demo_mode_filter(self, factory, admin_user, mock_orchestrator):
        """Filter by demo_mode (lines 255-258)."""
        async with factory() as session:
            session.add(BotConfig(user_id=admin_user.id, name="Demo Bot", strategy_type="test_strategy",
                                  exchange_type="bitget", mode="demo", trading_pairs=json.dumps(["BTCUSDT"]), is_enabled=False))
            session.add(BotConfig(user_id=admin_user.id, name="Live Bot", strategy_type="test_strategy",
                                  exchange_type="bitget", mode="live", trading_pairs=json.dumps(["BTCUSDT"]), is_enabled=False))
            await session.commit()

        async with factory() as session:
            demo_result = await list_bots(demo_mode=True, user=admin_user, db=session, orchestrator=mock_orchestrator)
        for b in demo_result.bots:
            assert b.mode in ["demo", "both"]

        async with factory() as session:
            live_result = await list_bots(demo_mode=False, user=admin_user, db=session, orchestrator=mock_orchestrator)
        for b in live_result.bots:
            assert b.mode in ["live", "both"]

    async def test_list_bots_with_trade_stats(self, factory, admin_user, sample_bot, mock_orchestrator):
        """Trade statistics aggregation (lines 273-297)."""
        now = datetime.utcnow()
        async with factory() as session:
            session.add_all([
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                    side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                    take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=75,
                    reason="Win", order_id="w001", status="closed", pnl=10.0, pnl_percent=1.05,
                    fees=0.5, funding_paid=0.1, entry_time=now - timedelta(days=2),
                    exit_time=now - timedelta(days=1), exit_reason="TAKE_PROFIT",
                    exchange="bitget", demo_mode=True,
                ),
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                    side="long", size=0.01, entry_price=95000.0, take_profit=97000.0,
                    stop_loss=94000.0, leverage=4, confidence=70, reason="Open",
                    order_id="o001", status="open", entry_time=now - timedelta(hours=1),
                    exchange="bitget", demo_mode=True,
                ),
            ])
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        bot = result.bots[0]
        assert bot.total_trades >= 1
        assert bot.open_trades >= 1
        assert bot.total_pnl >= 10.0
        assert bot.total_fees >= 0.5

    async def test_list_bots_with_trade_stats_demo_filter(self, factory, admin_user, sample_bot, mock_orchestrator):
        """Trade stats filtered by demo_mode (lines 274-276, 291-292)."""
        now = datetime.utcnow()
        async with factory() as session:
            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=75,
                reason="Demo trade", order_id="d001", status="closed", pnl=5.0,
                fees=0.2, funding_paid=0.05, entry_time=now - timedelta(days=1),
                exit_time=now, exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=True, user=admin_user, db=session, orchestrator=mock_orchestrator)
        assert len(result.bots) >= 1

    async def test_list_bots_with_llm_signal(self, factory, admin_user, mock_orchestrator):
        """LLM signal bot metrics (lines 301-410)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Bot", strategy_type="llm_signal",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                strategy_params=json.dumps({"llm_provider": "groq", "llm_model": "llama-3.3-70b"}),
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            session.add_all([
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                    side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                    take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                    reason="LLM signal", order_id="llm001", status="closed", pnl=10.0,
                    pnl_percent=1.05, fees=0.5, entry_time=now - timedelta(days=2),
                    exit_time=now - timedelta(days=1), exit_reason="TAKE_PROFIT",
                    exchange="bitget", demo_mode=True,
                    metrics_snapshot=json.dumps({
                        "llm_reasoning": "Strong bullish indicators",
                        "llm_provider": "groq", "llm_model": "llama-3.3-70b",
                        "llm_tokens_used": 1500,
                    }),
                ),
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                    side="short", size=0.01, entry_price=96000.0, exit_price=96500.0,
                    take_profit=95000.0, stop_loss=97000.0, leverage=4, confidence=65,
                    reason="LLM signal 2", order_id="llm002", status="closed", pnl=-5.0,
                    pnl_percent=-0.52, fees=0.3, entry_time=now - timedelta(days=1),
                    exit_time=now - timedelta(hours=12), exit_reason="STOP_LOSS",
                    exchange="bitget", demo_mode=True,
                    metrics_snapshot=json.dumps({
                        "llm_reasoning": "Bearish divergence",
                        "llm_provider": "groq", "llm_model": "llama-3.3-70b",
                        "llm_tokens_used": 1200,
                    }),
                ),
            ])
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        llm = next((b for b in result.bots if b.name == "LLM Bot"), None)
        assert llm is not None
        assert llm.llm_provider == "groq"
        assert llm.llm_model == "llama-3.3-70b"
        assert llm.llm_last_direction is not None
        assert llm.llm_accuracy is not None
        assert llm.llm_total_predictions == 2
        assert llm.llm_total_tokens_used == 2700
        assert llm.llm_avg_tokens_per_call is not None

    async def test_list_bots_llm_with_demo_filter(self, factory, admin_user, mock_orchestrator):
        """LLM metrics filtered by demo_mode (lines 303-360)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Demo Bot", strategy_type="llm_signal",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                strategy_params=json.dumps({"llm_provider": "openai", "llm_model": "gpt-4"}),
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                reason="LLM demo", order_id="llmd001", status="closed", pnl=10.0,
                fees=0.5, entry_time=now - timedelta(days=1), exit_time=now,
                exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
                metrics_snapshot=json.dumps({"llm_tokens_used": 1000}),
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=True, user=admin_user, db=session, orchestrator=mock_orchestrator)
        llm = next((b for b in result.bots if b.name == "LLM Demo Bot"), None)
        assert llm is not None

    async def test_list_bots_llm_bad_metrics_snapshot(self, factory, admin_user, mock_orchestrator):
        """LLM bot with invalid metrics_snapshot JSON (lines 324, 374)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Bad Metrics", strategy_type="llm_signal",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                reason="LLM bad", order_id="llmb001", status="closed", pnl=10.0,
                fees=0.5, entry_time=now - timedelta(days=1), exit_time=now,
                exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
                metrics_snapshot="{invalid json",
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        llm = next((b for b in result.bots if b.name == "LLM Bad Metrics"), None)
        assert llm is not None

    async def test_list_bots_llm_provider_from_strategy_params(self, factory, admin_user, mock_orchestrator):
        """LLM provider fallback from strategy_params (lines 384-393)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Params Bot", strategy_type="llm_signal",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                strategy_params=json.dumps({"llm_provider": "anthropic", "llm_model": "claude-3"}),
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            # Trade WITHOUT metrics_snapshot provider info
            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                reason="LLM params", order_id="llmp001", status="closed", pnl=10.0,
                fees=0.5, entry_time=now - timedelta(days=1), exit_time=now,
                exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
                metrics_snapshot=json.dumps({"llm_tokens_used": 500}),
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        llm = next((b for b in result.bots if b.name == "LLM Params Bot"), None)
        assert llm is not None
        assert llm.llm_provider == "anthropic"
        assert llm.llm_model == "claude-3"

    async def test_list_bots_with_hl_connection(self, factory, admin_user, mock_orchestrator):
        """HL exchange connection data (lines 224-236)."""
        async with factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="hyperliquid",
                builder_fee_approved=True, referral_verified=True,
            ))
            session.add(BotConfig(
                user_id=admin_user.id, name="HL Bot", strategy_type="test_strategy",
                exchange_type="hyperliquid", mode="demo",
                trading_pairs=json.dumps(["BTC"]), is_enabled=False,
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        hl = next((b for b in result.bots if b.exchange_type == "hyperliquid"), None)
        assert hl is not None
        assert hl.builder_fee_approved is True
        assert hl.referral_verified is True

    async def test_list_bots_with_affiliate_data(self, factory, admin_user, mock_orchestrator):
        """Affiliate UID data for Bitget/Weex (lines 238-251)."""
        async with factory() as session:
            session.add(ExchangeConnection(
                user_id=admin_user.id, exchange_type="bitget",
                affiliate_uid="BG123456", affiliate_verified=True,
            ))
            session.add(BotConfig(
                user_id=admin_user.id, name="Affiliate Bot", strategy_type="test_strategy",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]), is_enabled=False,
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        bg = next((b for b in result.bots if b.name == "Affiliate Bot"), None)
        assert bg is not None
        assert bg.affiliate_uid == "BG123456"
        assert bg.affiliate_verified is True

    async def test_list_bots_with_preset_name(self, factory, admin_user, sample_preset, mock_orchestrator):
        """Preset name lookup (lines 217-221, 433)."""
        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id, name="Preset Bot", strategy_type="test_strategy",
                exchange_type="bitget", mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                active_preset_id=sample_preset.id, is_enabled=False,
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        preset_bot = next((b for b in result.bots if b.name == "Preset Bot"), None)
        assert preset_bot is not None
        assert preset_bot.active_preset_id == sample_preset.id
        assert preset_bot.active_preset_name == "Aggressive Preset"


# ---------------------------------------------------------------------------
# GET bot — lines 444-458
# ---------------------------------------------------------------------------


class TestGetBot:

    async def test_get_bot_success(self, factory, admin_user, sample_bot):
        """Get a bot by ID (lines 444-458)."""
        async with factory() as session:
            result = await get_bot(bot_id=sample_bot.id, user=admin_user, db=session)
        assert result.id == sample_bot.id
        assert result.name == "Test Bot"

    async def test_get_bot_not_found(self, factory, admin_user):
        """Get nonexistent bot returns 404 (lines 456-457)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await get_bot(bot_id=99999, user=admin_user, db=session)
            assert exc_info.value.status_code == 404

    async def test_get_bot_wrong_user(self, factory, admin_user, regular_user, sample_bot):
        """Cannot get another user's bot (line 452)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await get_bot(bot_id=sample_bot.id, user=regular_user, db=session)
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# UPDATE bot — lines 461-524
# ---------------------------------------------------------------------------


class TestUpdateBot:

    async def test_update_bot_name(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Update bot name (lines 461-524)."""
        async with factory() as session:
            body = BotConfigUpdate(name="Updated Name")
            result = await update_bot(request=mock_request, bot_id=sample_bot.id, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result.name == "Updated Name"

    async def test_update_bot_multiple_fields(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Update multiple fields including JSON fields (lines 488-518)."""
        async with factory() as session:
            body = BotConfigUpdate(
                name="Updated Bot",
                trading_pairs=["SOLUSDT"],
                strategy_params={"window": 20},
                schedule_config={"hours": [1, 8, 14]},
                per_asset_config={"SOLUSDT": {"leverage": 2}},
                leverage=8,
                mode="live",
            )
            result = await update_bot(request=mock_request, bot_id=sample_bot.id, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()

        assert result.name == "Updated Bot"
        assert result.trading_pairs == ["SOLUSDT"]
        assert result.strategy_params == {"window": 20}
        assert result.schedule_config == {"hours": [1, 8, 14]}
        assert result.per_asset_config == {"SOLUSDT": {"leverage": 2}}
        assert result.leverage == 8
        assert result.mode == "live"

    async def test_update_bot_not_found(self, factory, admin_user, mock_orchestrator, mock_request):
        """Update nonexistent bot returns 404 (lines 472-474)."""
        from fastapi import HTTPException

        async with factory() as session:
            body = BotConfigUpdate(name="Ghost")
            with pytest.raises(HTTPException) as exc_info:
                await update_bot(request=mock_request, bot_id=99999, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 404

    async def test_update_bot_while_running(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Update running bot returns 400 (lines 477-479)."""
        from fastapi import HTTPException

        mock_orchestrator.is_running.return_value = True
        async with factory() as session:
            body = BotConfigUpdate(name="Should Fail")
            with pytest.raises(HTTPException) as exc_info:
                await update_bot(request=mock_request, bot_id=sample_bot.id, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400
            assert "Stop the bot" in str(exc_info.value.detail)
        mock_orchestrator.is_running.return_value = False

    async def test_update_bot_invalid_strategy(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Update with invalid strategy returns 400 (lines 482-486)."""
        from fastapi import HTTPException

        async with factory() as session:
            body = BotConfigUpdate(strategy_type="nonexistent_strategy")
            with pytest.raises(HTTPException) as exc_info:
                await update_bot(request=mock_request, bot_id=sample_bot.id, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400

    async def test_update_bot_discord_webhook_set_and_clear(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Set then clear discord webhook (lines 499-504)."""
        async with factory() as session:
            body = BotConfigUpdate(discord_webhook_url="https://discord.com/api/webhooks/new/tok")
            result = await update_bot(request=mock_request, bot_id=sample_bot.id, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result.discord_webhook_configured is True

        async with factory() as session:
            body = BotConfigUpdate(discord_webhook_url="")
            result = await update_bot(request=mock_request, bot_id=sample_bot.id, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result.discord_webhook_configured is False

    async def test_update_bot_telegram_set_and_clear(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Set then clear telegram (lines 505-516)."""
        async with factory() as session:
            body = BotConfigUpdate(telegram_bot_token="123:ABC", telegram_chat_id="999")
            result = await update_bot(request=mock_request, bot_id=sample_bot.id, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result.telegram_configured is True

        async with factory() as session:
            body = BotConfigUpdate(telegram_bot_token="", telegram_chat_id="")
            result = await update_bot(request=mock_request, bot_id=sample_bot.id, body=body, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result.telegram_configured is False


# ---------------------------------------------------------------------------
# DELETE bot — lines 527-548
# ---------------------------------------------------------------------------


class TestDeleteBot:

    async def test_delete_bot_success(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Delete a stopped bot (lines 527-548)."""
        async with factory() as session:
            result = await delete_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result["status"] == "ok"
        assert "Test Bot" in result["message"]

    async def test_delete_bot_not_found(self, factory, admin_user, mock_orchestrator, mock_request):
        """Delete nonexistent bot returns 404 (lines 537-539)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await delete_bot(request=mock_request, bot_id=99999, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 404

    async def test_delete_running_bot_stops_first(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Delete a running bot stops it first (lines 542-544)."""
        mock_orchestrator.is_running.return_value = True
        async with factory() as session:
            result = await delete_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result["status"] == "ok"
        mock_orchestrator.stop_bot.assert_called_with(sample_bot.id)
        mock_orchestrator.is_running.return_value = False


# ---------------------------------------------------------------------------
# DUPLICATE bot — lines 551-603
# ---------------------------------------------------------------------------


class TestDuplicateBot:

    async def test_duplicate_bot_success(self, factory, admin_user, sample_bot, mock_request):
        """Duplicate a bot (lines 551-603)."""
        async with factory() as session:
            result = await duplicate_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session)
            await session.commit()
        assert result.name == "Test Bot (Copy)"
        assert result.is_enabled is False
        assert result.id != sample_bot.id
        assert result.strategy_type == "test_strategy"

    async def test_duplicate_bot_not_found(self, factory, admin_user, mock_request):
        """Duplicate nonexistent bot returns 404 (lines 561-563)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await duplicate_bot(request=mock_request, bot_id=99999, user=admin_user, db=session)
            assert exc_info.value.status_code == 404

    async def test_duplicate_bot_at_max_limit(self, factory, admin_user, sample_bot, mock_request):
        """Duplicate at max limit returns 400 (lines 566-570)."""
        from fastapi import HTTPException

        # Create 9 more bots (total 10 with sample_bot)
        async with factory() as session:
            for i in range(9):
                session.add(BotConfig(
                    user_id=admin_user.id, name=f"Filler {i}",
                    strategy_type="test_strategy", exchange_type="bitget",
                    mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                    is_enabled=False,
                ))
            await session.commit()

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await duplicate_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session)
            assert exc_info.value.status_code == 400
            assert "Maximum" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# LIFECYCLE: start/stop/restart/stop-all — lines 688-794
# ---------------------------------------------------------------------------


class TestLifecycle:

    async def test_start_bot_success(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Start a bot (lines 688-722)."""
        async with factory() as session:
            result = await start_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result["status"] == "ok"
        mock_orchestrator.start_bot.assert_called_with(sample_bot.id)

    async def test_start_bot_not_found(self, factory, admin_user, mock_orchestrator, mock_request):
        """Start nonexistent bot returns 404 (lines 700-702)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await start_bot(request=mock_request, bot_id=99999, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 404

    async def test_start_bot_orchestrator_error(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Orchestrator ValueError returns 400 (lines 713-716)."""
        from fastapi import HTTPException

        mock_orchestrator.start_bot.side_effect = ValueError("Config invalid")
        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await start_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400
            assert "Config invalid" in str(exc_info.value.detail)
        mock_orchestrator.start_bot.side_effect = None

    async def test_stop_bot_success(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Stop a running bot (lines 725-750)."""
        mock_orchestrator.stop_bot.return_value = True
        async with factory() as session:
            result = await stop_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result["status"] == "ok"

    async def test_stop_bot_not_found(self, factory, admin_user, mock_orchestrator, mock_request):
        """Stop nonexistent bot returns 404 (lines 737-739)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await stop_bot(request=mock_request, bot_id=99999, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 404

    async def test_stop_bot_not_running(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Stop non-running bot returns 400 (lines 742-744)."""
        from fastapi import HTTPException

        mock_orchestrator.stop_bot.return_value = False
        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await stop_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400
            assert "not running" in str(exc_info.value.detail)
        mock_orchestrator.stop_bot.return_value = True

    async def test_restart_bot_success(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Restart a bot (lines 753-786)."""
        async with factory() as session:
            result = await restart_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result["status"] == "ok"
        mock_orchestrator.restart_bot.assert_called_with(sample_bot.id)

    async def test_restart_bot_not_found(self, factory, admin_user, mock_orchestrator, mock_request):
        """Restart nonexistent bot returns 404 (lines 765-767)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await restart_bot(request=mock_request, bot_id=99999, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 404

    async def test_restart_bot_orchestrator_error(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Restart with orchestrator error returns 400 (lines 778-781)."""
        from fastapi import HTTPException

        mock_orchestrator.restart_bot.side_effect = ValueError("Cannot restart")
        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await restart_bot(request=mock_request, bot_id=sample_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400
        mock_orchestrator.restart_bot.side_effect = None

    async def test_stop_all_bots(self, admin_user, mock_orchestrator, mock_request):
        """Stop all bots for user (lines 789-794)."""
        result = await stop_all_bots(request=mock_request, user=admin_user, orchestrator=mock_orchestrator)
        assert result["status"] == "ok"
        assert "2" in result["message"]
        mock_orchestrator.stop_all_for_user.assert_called_with(admin_user.id)


# ---------------------------------------------------------------------------
# HL gate enforcement — lines 609-644
# ---------------------------------------------------------------------------


class TestHyperliquidGates:

    async def test_hl_gate_no_connection(self, factory, regular_user):
        """No HL exchange connection raises 400 (lines 616-624)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_hl_gates(user=regular_user, db=session)
            assert exc_info.value.status_code == 400
            assert "Hyperliquid" in str(exc_info.value.detail)

    @patch("src.utils.settings.get_hl_config", new_callable=AsyncMock)
    async def test_hl_gate_referral_not_verified(self, mock_hl_config, factory, regular_user):
        """Referral not verified raises 400 (lines 629-636)."""
        from fastapi import HTTPException

        mock_hl_config.return_value = {
            "referral_code": "TESTREF",
            "builder_address": "0x" + "a" * 40,
            "builder_fee": 10,
        }
        async with factory() as session:
            session.add(ExchangeConnection(
                user_id=regular_user.id, exchange_type="hyperliquid",
                builder_fee_approved=True, referral_verified=False,
            ))
            await session.commit()

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_hl_gates(user=regular_user, db=session)
            assert exc_info.value.status_code == 400
            assert "Referral" in str(exc_info.value.detail)

    @patch("src.utils.settings.get_hl_config", new_callable=AsyncMock)
    async def test_hl_gate_builder_fee_not_approved(self, mock_hl_config, factory, regular_user):
        """Builder fee not approved raises 400 (lines 639-644)."""
        from fastapi import HTTPException

        mock_hl_config.return_value = {
            "referral_code": "",
            "builder_address": "0x" + "a" * 40,
            "builder_fee": 10,
        }
        async with factory() as session:
            session.add(ExchangeConnection(
                user_id=regular_user.id, exchange_type="hyperliquid",
                builder_fee_approved=False, referral_verified=True,
            ))
            await session.commit()

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_hl_gates(user=regular_user, db=session)
            assert exc_info.value.status_code == 400
            assert "Builder Fee" in str(exc_info.value.detail)

    @patch("src.utils.settings.get_hl_config", new_callable=AsyncMock)
    async def test_hl_gate_all_approved(self, mock_hl_config, factory, regular_user):
        """All gates pass when everything is approved (lines 609-644)."""
        mock_hl_config.return_value = {
            "referral_code": "TESTREF",
            "builder_address": "0x" + "a" * 40,
            "builder_fee": 10,
        }
        async with factory() as session:
            session.add(ExchangeConnection(
                user_id=regular_user.id, exchange_type="hyperliquid",
                builder_fee_approved=True, referral_verified=True,
            ))
            await session.commit()

        async with factory() as session:
            # Should not raise
            await _enforce_hl_gates(user=regular_user, db=session)

    async def test_start_hl_bot_admin_bypasses_gates(self, factory, admin_user, mock_orchestrator, mock_request):
        """Admin bypasses HL gates (line 705)."""
        async with factory() as session:
            hl_bot = BotConfig(
                user_id=admin_user.id, name="Admin HL Bot", strategy_type="test_strategy",
                exchange_type="hyperliquid", mode="demo",
                trading_pairs=json.dumps(["BTC"]), is_enabled=False,
            )
            session.add(hl_bot)
            await session.commit()
            await session.refresh(hl_bot)

        async with factory() as session:
            result = await start_bot(request=mock_request, bot_id=hl_bot.id, user=admin_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result["status"] == "ok"

    async def test_start_hl_bot_user_gate_enforced(self, factory, regular_user, hl_bot, mock_orchestrator, mock_request):
        """Non-admin user triggers HL gate (lines 705-707)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await start_bot(request=mock_request, bot_id=hl_bot.id, user=regular_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400

    async def test_restart_hl_bot_gates_enforced(self, factory, regular_user, hl_bot, mock_orchestrator, mock_request):
        """Restart also enforces HL gates (lines 770-772)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await restart_bot(request=mock_request, bot_id=hl_bot.id, user=regular_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Affiliate gate enforcement — lines 647-685
# ---------------------------------------------------------------------------


class TestAffiliateGates:

    async def test_affiliate_gate_no_requirement(self, factory, regular_user):
        """No AffiliateLink with uid_required passes (lines 657-659)."""
        async with factory() as session:
            # No AffiliateLink in DB
            await _enforce_affiliate_gate(exchange_type="bitget", user=regular_user, db=session)

    async def test_affiliate_gate_no_uid(self, factory, regular_user):
        """Affiliate required but no UID (lines 669-677)."""
        from fastapi import HTTPException

        async with factory() as session:
            session.add(AffiliateLink(
                exchange_type="bitget",
                affiliate_url="https://bitget.com/ref/test",
                label="Bitget Affiliate",
                is_active=True,
                uid_required=True,
            ))
            await session.commit()

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_affiliate_gate(exchange_type="bitget", user=regular_user, db=session)
            assert exc_info.value.status_code == 400
            detail = exc_info.value.detail
            assert detail["type"] == "affiliate_required"
            assert "affiliate_url" in detail

    async def test_affiliate_gate_uid_pending(self, factory, regular_user):
        """Affiliate UID submitted but not verified (lines 678-685)."""
        from fastapi import HTTPException

        async with factory() as session:
            session.add(AffiliateLink(
                exchange_type="bitget", affiliate_url="https://bitget.com/ref/test",
                label="Bitget", is_active=True, uid_required=True,
            ))
            session.add(ExchangeConnection(
                user_id=regular_user.id, exchange_type="bitget",
                affiliate_uid="BG111", affiliate_verified=False,
            ))
            await session.commit()

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await _enforce_affiliate_gate(exchange_type="bitget", user=regular_user, db=session)
            assert exc_info.value.status_code == 400
            assert exc_info.value.detail["type"] == "affiliate_pending"

    async def test_affiliate_gate_verified(self, factory, regular_user):
        """Verified affiliate passes (lines 647-685)."""
        async with factory() as session:
            session.add(AffiliateLink(
                exchange_type="bitget", affiliate_url="https://bitget.com/ref/test",
                label="Bitget", is_active=True, uid_required=True,
            ))
            session.add(ExchangeConnection(
                user_id=regular_user.id, exchange_type="bitget",
                affiliate_uid="BG111", affiliate_verified=True,
            ))
            await session.commit()

        async with factory() as session:
            # Should not raise
            await _enforce_affiliate_gate(exchange_type="bitget", user=regular_user, db=session)

    async def test_start_bitget_bot_affiliate_gate(self, factory, regular_user, bitget_bot_regular, mock_orchestrator, mock_request):
        """Start Bitget bot triggers affiliate gate (lines 708-709)."""
        from fastapi import HTTPException

        async with factory() as session:
            session.add(AffiliateLink(
                exchange_type="bitget", affiliate_url="https://bitget.com/ref/test",
                label="Bitget", is_active=True, uid_required=True,
            ))
            await session.commit()

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await start_bot(request=mock_request, bot_id=bitget_bot_regular.id, user=regular_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400

    async def test_start_bitget_bot_no_affiliate_requirement(self, factory, regular_user, bitget_bot_regular, mock_orchestrator, mock_request):
        """Start Bitget bot with no affiliate requirement succeeds (lines 657-659)."""
        async with factory() as session:
            result = await start_bot(request=mock_request, bot_id=bitget_bot_regular.id, user=regular_user, db=session, orchestrator=mock_orchestrator)
            await session.commit()
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# TEST TELEGRAM — lines 797-823
# ---------------------------------------------------------------------------


class TestTelegram:

    async def test_telegram_not_found(self, factory, admin_user, mock_request):
        """Test telegram on nonexistent bot (lines 807-809)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await send_test_telegram(request=mock_request, bot_id=99999, user=admin_user, session=session)
            assert exc_info.value.status_code == 404

    async def test_telegram_not_configured(self, factory, admin_user, sample_bot, mock_request):
        """Test telegram when not configured (lines 810-811)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await send_test_telegram(request=mock_request, bot_id=sample_bot.id, user=admin_user, session=session)
            assert exc_info.value.status_code == 400
            assert "Telegram not configured" in str(exc_info.value.detail)

    async def test_telegram_send_success(self, factory, admin_user, mock_request):
        """Telegram test message succeeds (lines 813-823)."""
        from src.utils.encryption import encrypt_value

        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id, name="Telegram Bot",
                strategy_type="test_strategy", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                telegram_bot_token=encrypt_value("123:ABCdef"),
                telegram_chat_id="999888", is_enabled=False,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)

        mock_notifier = MagicMock()
        mock_notifier.send_test_message = AsyncMock(return_value=True)

        with patch("src.notifications.telegram_notifier.TelegramNotifier", return_value=mock_notifier):
            async with factory() as session:
                result = await send_test_telegram(request=mock_request, bot_id=config.id, user=admin_user, session=session)
        assert result["status"] == "ok"

    async def test_telegram_send_failure(self, factory, admin_user, mock_request):
        """Telegram test message fails returns 502 (lines 821-822)."""
        from fastapi import HTTPException
        from src.utils.encryption import encrypt_value

        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id, name="Telegram Fail Bot",
                strategy_type="test_strategy", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                telegram_bot_token=encrypt_value("123:ABCdef"),
                telegram_chat_id="999888", is_enabled=False,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)

        mock_notifier = MagicMock()
        mock_notifier.send_test_message = AsyncMock(return_value=False)

        with patch("src.notifications.telegram_notifier.TelegramNotifier", return_value=mock_notifier):
            async with factory() as session:
                with pytest.raises(HTTPException) as exc_info:
                    await send_test_telegram(request=mock_request, bot_id=config.id, user=admin_user, session=session)
                assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# APPLY PRESET — lines 828-906
# ---------------------------------------------------------------------------


class TestApplyPreset:

    async def test_apply_preset_success(self, factory, admin_user, sample_bot, sample_preset, mock_orchestrator, mock_request):
        """Apply preset updates bot config (lines 828-906)."""
        async with factory() as session:
            result = await apply_preset_to_bot(
                request=mock_request, bot_id=sample_bot.id, preset_id=sample_preset.id,
                user=admin_user, db=session, orchestrator=mock_orchestrator,
            )
            await session.commit()

        assert result.leverage == 10
        assert result.position_size_percent == 15.0
        assert result.max_trades_per_day == 5
        assert result.take_profit_percent == 6.0
        assert result.stop_loss_percent == 2.0
        assert result.daily_loss_limit_percent == 10.0
        assert result.active_preset_id == sample_preset.id
        # Bitget keeps USDT suffix
        for pair in result.trading_pairs:
            assert pair.endswith("USDT")

    async def test_apply_preset_bot_not_found(self, factory, admin_user, sample_preset, mock_orchestrator, mock_request):
        """Apply preset to nonexistent bot (lines 839-841)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await apply_preset_to_bot(
                    request=mock_request, bot_id=99999, preset_id=sample_preset.id,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )
            assert exc_info.value.status_code == 404

    async def test_apply_preset_bot_running(self, factory, admin_user, sample_bot, sample_preset, mock_orchestrator, mock_request):
        """Apply preset to running bot returns 400 (lines 844-846)."""
        from fastapi import HTTPException

        mock_orchestrator.is_running.return_value = True
        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await apply_preset_to_bot(
                    request=mock_request, bot_id=sample_bot.id, preset_id=sample_preset.id,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )
            assert exc_info.value.status_code == 400
        mock_orchestrator.is_running.return_value = False

    async def test_apply_preset_not_found(self, factory, admin_user, sample_bot, mock_orchestrator, mock_request):
        """Nonexistent preset returns 404 (lines 852-854)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await apply_preset_to_bot(
                    request=mock_request, bot_id=sample_bot.id, preset_id=99999,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )
            assert exc_info.value.status_code == 404

    async def test_apply_preset_hl_strips_usdt(self, factory, admin_user, mock_orchestrator, mock_request):
        """HL bot strips USDT suffix from preset pairs (lines 885-887)."""
        async with factory() as session:
            hl_bot = BotConfig(
                user_id=admin_user.id, name="HL Preset Bot",
                strategy_type="test_strategy", exchange_type="hyperliquid",
                mode="demo", trading_pairs=json.dumps(["BTC"]), is_enabled=False,
            )
            session.add(hl_bot)
            preset = ConfigPreset(
                user_id=admin_user.id, name="HL Preset", exchange_type="any",
                trading_config=json.dumps({"leverage": 5}),
                strategy_config=json.dumps({"param": "val"}),
                trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT", "SOL"]),
            )
            session.add(preset)
            await session.commit()
            await session.refresh(hl_bot)
            await session.refresh(preset)

        async with factory() as session:
            result = await apply_preset_to_bot(
                request=mock_request, bot_id=hl_bot.id, preset_id=preset.id,
                user=admin_user, db=session, orchestrator=mock_orchestrator,
            )
            await session.commit()

        assert "BTC" in result.trading_pairs
        assert "ETH" in result.trading_pairs
        assert "SOL" in result.trading_pairs
        assert "BTCUSDT" not in result.trading_pairs
        assert "ETHUSDT" not in result.trading_pairs

    async def test_apply_preset_cex_adds_usdt(self, factory, admin_user, mock_orchestrator, mock_request):
        """CEX bot adds USDT suffix to preset pairs (lines 889-891)."""
        async with factory() as session:
            cex_bot = BotConfig(
                user_id=admin_user.id, name="CEX Preset Bot",
                strategy_type="test_strategy", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]), is_enabled=False,
            )
            session.add(cex_bot)
            preset = ConfigPreset(
                user_id=admin_user.id, name="CEX Preset", exchange_type="any",
                trading_config=json.dumps({"leverage": 3}),
                trading_pairs=json.dumps(["BTC", "ETH", "SOLUSDT"]),
            )
            session.add(preset)
            await session.commit()
            await session.refresh(cex_bot)
            await session.refresh(preset)

        async with factory() as session:
            result = await apply_preset_to_bot(
                request=mock_request, bot_id=cex_bot.id, preset_id=preset.id,
                user=admin_user, db=session, orchestrator=mock_orchestrator,
            )
            await session.commit()

        assert "BTCUSDT" in result.trading_pairs
        assert "ETHUSDT" in result.trading_pairs
        assert "SOLUSDT" in result.trading_pairs

    async def test_apply_preset_merges_strategy_preserves_data_sources(self, factory, admin_user, mock_orchestrator, mock_request):
        """Strategy config merges, data_sources preserved (lines 872-880)."""
        async with factory() as session:
            bot = BotConfig(
                user_id=admin_user.id, name="Merge Bot",
                strategy_type="test_strategy", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                strategy_params=json.dumps({
                    "threshold": 0.5,
                    "data_sources": ["fear_greed", "funding_rate"],
                }),
                is_enabled=False,
            )
            session.add(bot)
            preset = ConfigPreset(
                user_id=admin_user.id, name="Merge Preset", exchange_type="any",
                strategy_config=json.dumps({
                    "threshold": 0.9, "window": 20,
                    "data_sources": ["should_be_overridden"],
                }),
            )
            session.add(preset)
            await session.commit()
            await session.refresh(bot)
            await session.refresh(preset)

        async with factory() as session:
            result = await apply_preset_to_bot(
                request=mock_request, bot_id=bot.id, preset_id=preset.id,
                user=admin_user, db=session, orchestrator=mock_orchestrator,
            )
            await session.commit()

        assert result.strategy_params["threshold"] == 0.9
        assert result.strategy_params["window"] == 20
        assert result.strategy_params["data_sources"] == ["fear_greed", "funding_rate"]


# ---------------------------------------------------------------------------
# STATISTICS — lines 911-1050
# ---------------------------------------------------------------------------


class TestStatistics:

    async def test_statistics_not_found(self, factory, admin_user):
        """Statistics for nonexistent bot returns 404 (lines 923-925)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await get_bot_statistics(bot_id=99999, days=30, demo_mode=None, user=admin_user, db=session)
            assert exc_info.value.status_code == 404

    async def test_statistics_no_trades(self, factory, admin_user, sample_bot):
        """Statistics with no trades (lines 911-1050)."""
        async with factory() as session:
            result = await get_bot_statistics(
                bot_id=sample_bot.id, days=30, demo_mode=None,
                user=admin_user, db=session,
            )
        assert result["bot_id"] == sample_bot.id
        assert result["summary"]["total_trades"] == 0
        assert result["summary"]["win_rate"] == 0.0
        assert result["daily_series"] == []
        assert result["recent_trades"] == []

    async def test_statistics_with_trades(self, factory, admin_user, sample_bot):
        """Full statistics with trades (lines 928-1050)."""
        now = datetime.utcnow()
        async with factory() as session:
            session.add_all([
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                    side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                    take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                    reason="Win", order_id="s001", status="closed", pnl=10.0,
                    pnl_percent=1.05, fees=0.5, funding_paid=0.1,
                    entry_time=now - timedelta(days=3), exit_time=now - timedelta(days=2),
                    exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
                ),
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="ETHUSDT",
                    side="short", size=0.1, entry_price=3500.0, exit_price=3600.0,
                    take_profit=3300.0, stop_loss=3600.0, leverage=4, confidence=60,
                    reason="Loss", order_id="s002", status="closed", pnl=-10.0,
                    pnl_percent=-2.86, fees=0.3, funding_paid=0.05,
                    entry_time=now - timedelta(days=2), exit_time=now - timedelta(days=1),
                    exit_reason="STOP_LOSS", exchange="bitget", demo_mode=True,
                ),
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                    side="long", size=0.02, entry_price=94000.0, exit_price=95500.0,
                    take_profit=96000.0, stop_loss=93000.0, leverage=4, confidence=70,
                    reason="Win 2", order_id="s003", status="closed", pnl=30.0,
                    pnl_percent=1.6, fees=0.4, funding_paid=0.08,
                    entry_time=now - timedelta(days=1), exit_time=now - timedelta(hours=12),
                    exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
                ),
            ])
            await session.commit()

        async with factory() as session:
            result = await get_bot_statistics(
                bot_id=sample_bot.id, days=30, demo_mode=None,
                user=admin_user, db=session,
            )

        assert result["bot_id"] == sample_bot.id
        summary = result["summary"]
        assert summary["total_trades"] == 3
        assert summary["wins"] == 2
        assert summary["losses"] == 1
        assert summary["win_rate"] > 0
        assert summary["total_pnl"] == 30.0
        assert summary["total_fees"] > 0
        assert summary["total_funding"] > 0
        assert summary["best_trade"] == 30.0
        assert summary["worst_trade"] == -10.0

        assert len(result["daily_series"]) >= 1
        for entry in result["daily_series"]:
            assert "date" in entry
            assert "pnl" in entry
            assert "cumulative_pnl" in entry
            assert "trades" in entry
            assert "wins" in entry
            assert "fees" in entry
            assert "funding" in entry

        assert len(result["recent_trades"]) == 3
        for trade in result["recent_trades"]:
            assert "id" in trade
            assert "symbol" in trade
            assert "pnl" in trade
            assert "fees" in trade
            assert "funding_paid" in trade

    async def test_statistics_with_demo_filter(self, factory, admin_user, sample_bot):
        """Statistics with demo_mode filter (lines 935-936, 975-976, 999-1000)."""
        now = datetime.utcnow()
        async with factory() as session:
            session.add_all([
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                    side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                    take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=75,
                    reason="Demo", order_id="df001", status="closed", pnl=5.0,
                    fees=0.2, funding_paid=0.05, entry_time=now - timedelta(days=1),
                    exit_time=now, exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
                ),
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                    side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                    take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=75,
                    reason="Live", order_id="lf001", status="closed", pnl=15.0,
                    fees=0.3, funding_paid=0.08, entry_time=now - timedelta(days=1),
                    exit_time=now, exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=False,
                ),
            ])
            await session.commit()

        async with factory() as session:
            demo_result = await get_bot_statistics(
                bot_id=sample_bot.id, days=30, demo_mode=True,
                user=admin_user, db=session,
            )
        assert demo_result["summary"]["total_trades"] == 1
        assert demo_result["summary"]["total_pnl"] == 5.0

        async with factory() as session:
            live_result = await get_bot_statistics(
                bot_id=sample_bot.id, days=30, demo_mode=False,
                user=admin_user, db=session,
            )
        assert live_result["summary"]["total_trades"] == 1
        assert live_result["summary"]["total_pnl"] == 15.0

    async def test_statistics_custom_days(self, factory, admin_user, sample_bot):
        """Statistics with custom days parameter (line 927)."""
        async with factory() as session:
            result = await get_bot_statistics(
                bot_id=sample_bot.id, days=7, demo_mode=None,
                user=admin_user, db=session,
            )
        assert result["days"] == 7


# ---------------------------------------------------------------------------
# COMPARE PERFORMANCE — lines 1053-1185
# ---------------------------------------------------------------------------


class TestComparePerformance:

    async def test_compare_empty(self, factory, admin_user):
        """Compare with no bots (lines 1061-1069)."""
        async with factory() as session:
            result = await compare_bots_performance(
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        assert result["bots"] == []
        assert result["days"] == 30

    async def test_compare_with_trades(self, factory, admin_user, sample_bot):
        """Compare with trade data (lines 1074-1183)."""
        now = datetime.utcnow()
        async with factory() as session:
            session.add_all([
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                    side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                    take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                    reason="Comp 1", order_id="c001", status="closed", pnl=10.0,
                    fees=0.5, funding_paid=0.1, entry_time=now - timedelta(days=2),
                    exit_time=now - timedelta(days=1), exit_reason="TAKE_PROFIT",
                    exchange="bitget", demo_mode=True,
                ),
                TradeRecord(
                    user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                    side="short", size=0.01, entry_price=96000.0, exit_price=96500.0,
                    take_profit=95000.0, stop_loss=97000.0, leverage=4, confidence=65,
                    reason="Comp 2", order_id="c002", status="closed", pnl=-5.0,
                    fees=0.3, funding_paid=0.05, entry_time=now - timedelta(days=1),
                    exit_time=now - timedelta(hours=12), exit_reason="STOP_LOSS",
                    exchange="bitget", demo_mode=True,
                ),
            ])
            await session.commit()

        async with factory() as session:
            result = await compare_bots_performance(
                days=30, demo_mode=None, user=admin_user, db=session,
            )

        assert result["days"] == 30
        assert len(result["bots"]) >= 1
        bot = result["bots"][0]
        assert bot["bot_id"] == sample_bot.id
        assert bot["total_trades"] == 2
        assert bot["total_pnl"] == 5.0
        assert bot["wins"] == 1
        assert bot["win_rate"] == 50.0
        assert bot["total_fees"] > 0
        assert bot["total_funding"] > 0
        assert bot["last_direction"] is not None
        assert bot["last_confidence"] is not None
        assert "series" in bot

    async def test_compare_demo_mode_filter(self, factory, admin_user):
        """Compare with demo_mode filter (lines 1062-1065)."""
        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id, name="Demo Bot", strategy_type="test_strategy",
                exchange_type="bitget", mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            ))
            session.add(BotConfig(
                user_id=admin_user.id, name="Live Bot", strategy_type="test_strategy",
                exchange_type="bitget", mode="live", trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            ))
            await session.commit()

        async with factory() as session:
            demo_result = await compare_bots_performance(
                days=30, demo_mode=True, user=admin_user, db=session,
            )
        for b in demo_result["bots"]:
            assert b["mode"] in ["demo", "both"]

        async with factory() as session:
            live_result = await compare_bots_performance(
                days=30, demo_mode=False, user=admin_user, db=session,
            )
        for b in live_result["bots"]:
            assert b["mode"] in ["live", "both"]

    async def test_compare_llm_provider_from_strategy_params(self, factory, admin_user):
        """Compare detects LLM provider from strategy_params (lines 1141-1148)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Compare Bot",
                strategy_type="llm_signal", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                strategy_params=json.dumps({"llm_provider": "anthropic", "llm_model": "claude-3"}),
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                reason="LLM comp", order_id="lc001", status="closed", pnl=10.0,
                fees=0.5, entry_time=now - timedelta(days=1), exit_time=now,
                exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
            ))
            await session.commit()

        async with factory() as session:
            result = await compare_bots_performance(
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        llm = next((b for b in result["bots"] if b["name"] == "LLM Compare Bot"), None)
        assert llm is not None
        assert llm["llm_provider"] == "anthropic"
        assert llm["llm_model"] == "claude-3"

    async def test_compare_no_trades(self, factory, admin_user, sample_bot):
        """Compare with bot that has no trades (lines 1122-1124)."""
        async with factory() as session:
            result = await compare_bots_performance(
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        bot = next((b for b in result["bots"] if b["bot_id"] == sample_bot.id), None)
        assert bot is not None
        assert bot["total_trades"] == 0
        assert bot["total_pnl"] == 0.0
        assert bot["win_rate"] == 0.0
        assert bot["series"] == []

    async def test_compare_last_trade_direction(self, factory, admin_user, sample_bot):
        """Compare includes last trade direction and confidence (lines 1127-1136)."""
        now = datetime.utcnow()
        async with factory() as session:
            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=85,
                reason="Direction", order_id="dir001", status="closed", pnl=10.0,
                fees=0.5, entry_time=now - timedelta(hours=6),
                exit_time=now - timedelta(hours=3), exit_reason="TAKE_PROFIT",
                exchange="bitget", demo_mode=True,
            ))
            await session.commit()

        async with factory() as session:
            result = await compare_bots_performance(
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        bot = next((b for b in result["bots"] if b["bot_id"] == sample_bot.id), None)
        assert bot is not None
        assert bot["last_direction"] == "LONG"
        assert bot["last_confidence"] == 85

    async def test_compare_with_demo_filter_trades(self, factory, admin_user, sample_bot):
        """Compare with demo_mode filters trade stats (lines 1080-1081, 1110-1111, 1129)."""
        now = datetime.utcnow()
        async with factory() as session:
            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=sample_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=75,
                reason="Demo comp", order_id="dc001", status="closed", pnl=5.0,
                fees=0.2, funding_paid=0.05, entry_time=now - timedelta(days=1),
                exit_time=now, exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
            ))
            await session.commit()

        async with factory() as session:
            result = await compare_bots_performance(
                days=30, demo_mode=True, user=admin_user, db=session,
            )
        assert len(result["bots"]) >= 1


# ---------------------------------------------------------------------------
# Orchestrator not initialized — line 51-53
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Additional coverage: LLM legacy detection, restart affiliate, bad JSON
# ---------------------------------------------------------------------------


class TestLLMLegacyDetection:

    async def test_list_bots_llm_bad_strategy_params(self, factory, admin_user, mock_orchestrator):
        """LLM bot with bad strategy_params JSON (lines 392-393)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Bad SP", strategy_type="llm_signal",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                strategy_params="{invalid json",
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            # Trade with no provider in metrics, so fallback to strategy_params
            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                reason="LLM bad sp", order_id="llmbs001", status="closed", pnl=10.0,
                fees=0.5, entry_time=now - timedelta(days=1), exit_time=now,
                exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
                metrics_snapshot=json.dumps({"llm_tokens_used": 500}),
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        llm = next((b for b in result.bots if b.name == "LLM Bad SP"), None)
        assert llm is not None
        # Provider should be None because strategy_params is invalid JSON
        assert llm.llm_provider is None

    async def test_list_bots_llm_legacy_reason_detection(self, factory, admin_user, mock_orchestrator):
        """LLM bot with legacy reason-based provider detection (lines 396-410)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Legacy", strategy_type="llm_signal",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                # No strategy_params with llm_provider
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            # Simulate legacy trade with provider info in reason field
            # The detection code checks if cat["family_name"] is a substring of model_tag
            # So the bracket must contain the family_name (e.g. "Groq Llama 4 Maverick")
            from src.ai.providers import MODEL_CATALOG
            if MODEL_CATALOG:
                first_ptype = next(iter(MODEL_CATALOG))
                cat = MODEL_CATALOG[first_ptype]
                family_name = cat["family_name"]
                model_name = cat["models"][0]["name"] if cat["models"] else family_name
                reason_text = f"[{family_name} {model_name}] Bullish signal detected"
            else:
                reason_text = "[GPT-4] Bullish signal"

            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                reason=reason_text, order_id="llml001", status="closed", pnl=10.0,
                fees=0.5, entry_time=now - timedelta(days=1), exit_time=now,
                exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=admin_user, db=session, orchestrator=mock_orchestrator)
        llm = next((b for b in result.bots if b.name == "LLM Legacy"), None)
        assert llm is not None
        # Provider should be detected from the reason text
        if MODEL_CATALOG:
            assert llm.llm_provider is not None

    async def test_compare_llm_legacy_reason_detection(self, factory, admin_user, mock_orchestrator):
        """Compare endpoint legacy LLM provider from reason (lines 1149-1164)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Legacy Compare", strategy_type="llm_signal",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                # No strategy_params
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            from src.ai.providers import MODEL_CATALOG
            if MODEL_CATALOG:
                first_ptype = next(iter(MODEL_CATALOG))
                cat = MODEL_CATALOG[first_ptype]
                family_name = cat["family_name"]
                model_name = cat["models"][0]["name"] if cat["models"] else family_name
                reason_text = f"[{family_name} {model_name}] Bearish divergence"
            else:
                reason_text = "[GPT-4] Bearish divergence"

            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                side="short", size=0.01, entry_price=96000.0, exit_price=96500.0,
                take_profit=95000.0, stop_loss=97000.0, leverage=4, confidence=65,
                reason=reason_text, order_id="llmlc001", status="closed", pnl=-5.0,
                fees=0.3, entry_time=now - timedelta(days=1),
                exit_time=now - timedelta(hours=12), exit_reason="STOP_LOSS",
                exchange="bitget", demo_mode=True,
            ))
            await session.commit()

        async with factory() as session:
            result = await compare_bots_performance(
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        llm = next((b for b in result["bots"] if b["name"] == "LLM Legacy Compare"), None)
        assert llm is not None
        if MODEL_CATALOG:
            assert llm["llm_provider"] is not None

    async def test_compare_llm_bad_strategy_params(self, factory, admin_user, mock_orchestrator):
        """Compare LLM with bad strategy_params JSON (lines 1147-1148)."""
        now = datetime.utcnow()
        async with factory() as session:
            llm_bot = BotConfig(
                user_id=admin_user.id, name="LLM Bad SP Compare", strategy_type="llm_signal",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                strategy_params="{invalid",
                is_enabled=False,
            )
            session.add(llm_bot)
            await session.flush()

            session.add(TradeRecord(
                user_id=admin_user.id, bot_config_id=llm_bot.id, symbol="BTCUSDT",
                side="long", size=0.01, entry_price=95000.0, exit_price=96000.0,
                take_profit=97000.0, stop_loss=94000.0, leverage=4, confidence=80,
                reason="No brackets", order_id="llmbsc001", status="closed", pnl=10.0,
                fees=0.5, entry_time=now - timedelta(days=1), exit_time=now,
                exit_reason="TAKE_PROFIT", exchange="bitget", demo_mode=True,
            ))
            await session.commit()

        async with factory() as session:
            result = await compare_bots_performance(
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        llm = next((b for b in result["bots"] if b["name"] == "LLM Bad SP Compare"), None)
        assert llm is not None
        assert llm["llm_provider"] is None


class TestRestartAffiliateGate:

    async def test_restart_bitget_bot_affiliate_gate(self, factory, regular_user, bitget_bot_regular, mock_orchestrator, mock_request):
        """Restart Bitget bot triggers affiliate gate (lines 773-774)."""
        from fastapi import HTTPException

        async with factory() as session:
            session.add(AffiliateLink(
                exchange_type="bitget", affiliate_url="https://bitget.com/ref/test",
                label="Bitget", is_active=True, uid_required=True,
            ))
            await session.commit()

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await restart_bot(request=mock_request, bot_id=bitget_bot_regular.id, user=regular_user, db=session, orchestrator=mock_orchestrator)
            assert exc_info.value.status_code == 400


class TestOrchestratorNotInitialized:

    async def test_get_orchestrator_not_set(self):
        """Orchestrator not in app.state raises 503."""
        from fastapi import HTTPException

        mock_request = MagicMock()
        mock_request.app.state = MagicMock(spec=[])  # no 'orchestrator' attr
        with pytest.raises(HTTPException) as exc_info:
            get_orchestrator(mock_request)
        assert exc_info.value.status_code == 503
