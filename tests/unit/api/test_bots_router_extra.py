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
from datetime import datetime, timedelta, timezone
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
    ExchangeConnection,
    TradeRecord,
    User,
)
from src.auth.password import hash_password
from src.errors import (
    ERR_BOT_NOT_RUNNING,
    ERR_MAX_BOTS_REACHED,
    ERR_STOP_BOT_BEFORE_EDIT,
    ERR_TELEGRAM_NOT_CONFIGURED,
)

# Disable rate limiter before importing bots
from src.api.routers.auth import limiter
limiter.enabled = False

from src.api.routers.bots import (  # noqa: E402
    _config_to_response,
    _enforce_affiliate_gate,
    _enforce_hl_gates,
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
    start_bot,
    stop_all_bots,
    stop_bot,
    test_telegram as send_test_telegram,
    update_bot,
)
from src.api.schemas.bots import BotConfigCreate, BotConfigUpdate  # noqa: E402


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
            assert ERR_MAX_BOTS_REACHED.format(max_bots=10) in str(exc_info.value.detail)


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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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

    async def test_list_bots_with_affiliate_data(self, factory, regular_user, mock_orchestrator):
        """Affiliate UID data for Bitget/Weex (lines 238-251).

        Uses a non-admin user because admins bypass affiliate gates and
        affiliate_uid is not populated for admins.
        """
        async with factory() as session:
            session.add(ExchangeConnection(
                user_id=regular_user.id, exchange_type="bitget",
                affiliate_uid="BG123456", affiliate_verified=True,
            ))
            session.add(BotConfig(
                user_id=regular_user.id, name="Affiliate Bot", strategy_type="test_strategy",
                exchange_type="bitget", mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]), is_enabled=False,
            ))
            await session.commit()

        async with factory() as session:
            result = await list_bots(demo_mode=None, user=regular_user, db=session, orchestrator=mock_orchestrator)
        bg = next((b for b in result.bots if b.name == "Affiliate Bot"), None)
        assert bg is not None
        assert bg.affiliate_uid == "BG123456"
        assert bg.affiliate_verified is True


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
            assert ERR_STOP_BOT_BEFORE_EDIT in str(exc_info.value.detail)
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
            assert ERR_MAX_BOTS_REACHED.format(max_bots=10) in str(exc_info.value.detail)


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
            assert ERR_BOT_NOT_RUNNING in str(exc_info.value.detail)
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
        """Affiliate required but no UID raises 400."""
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
            assert "Bitget" in exc_info.value.detail

    async def test_affiliate_gate_uid_pending(self, factory, regular_user):
        """Affiliate UID submitted but not verified raises 400."""
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
            assert "Bitget" in exc_info.value.detail

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
            assert ERR_TELEGRAM_NOT_CONFIGURED in str(exc_info.value.detail)

    async def test_telegram_send_success(self, factory, admin_user, mock_request):
        """Telegram test message succeeds (lines 813-823)."""
        from src.utils.encryption import encrypt_value

        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id, name="Telegram Bot",
                strategy_type="test_strategy", exchange_type="bitget",
                mode="demo", trading_pairs=json.dumps(["BTCUSDT"]),
                telegram_bot_token=encrypt_value("123:ABCdef"),
                telegram_chat_id=encrypt_value("999888"), is_enabled=False,
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
                telegram_chat_id=encrypt_value("999888"), is_enabled=False,
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
# STATISTICS — lines 911-1050
# ---------------------------------------------------------------------------


class TestStatistics:

    async def test_statistics_not_found(self, factory, admin_user, mock_request):
        """Statistics for nonexistent bot returns 404 (lines 923-925)."""
        from fastapi import HTTPException

        async with factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await get_bot_statistics(request=mock_request, bot_id=99999, days=30, demo_mode=None, user=admin_user, db=session)
            assert exc_info.value.status_code == 404

    async def test_statistics_no_trades(self, factory, admin_user, sample_bot, mock_request):
        """Statistics with no trades (lines 911-1050)."""
        async with factory() as session:
            result = await get_bot_statistics(
                request=mock_request, bot_id=sample_bot.id, days=30, demo_mode=None,
                user=admin_user, db=session,
            )
        assert result["bot_id"] == sample_bot.id
        assert result["summary"]["total_trades"] == 0
        assert result["summary"]["win_rate"] == 0.0
        assert result["daily_series"] == []
        assert result["recent_trades"] == []

    async def test_statistics_with_trades(self, factory, admin_user, sample_bot, mock_request):
        """Full statistics with trades (lines 928-1050)."""
        now = datetime.now(timezone.utc)
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
                request=mock_request, bot_id=sample_bot.id, days=30, demo_mode=None,
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

    async def test_statistics_with_demo_filter(self, factory, admin_user, sample_bot, mock_request):
        """Statistics with demo_mode filter (lines 935-936, 975-976, 999-1000)."""
        now = datetime.now(timezone.utc)
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
                request=mock_request, bot_id=sample_bot.id, days=30, demo_mode=True,
                user=admin_user, db=session,
            )
        assert demo_result["summary"]["total_trades"] == 1
        assert demo_result["summary"]["total_pnl"] == 5.0

        async with factory() as session:
            live_result = await get_bot_statistics(
                request=mock_request, bot_id=sample_bot.id, days=30, demo_mode=False,
                user=admin_user, db=session,
            )
        assert live_result["summary"]["total_trades"] == 1
        assert live_result["summary"]["total_pnl"] == 15.0

    async def test_statistics_custom_days(self, factory, admin_user, sample_bot, mock_request):
        """Statistics with custom days parameter (line 927)."""
        async with factory() as session:
            result = await get_bot_statistics(
                request=mock_request, bot_id=sample_bot.id, days=7, demo_mode=None,
                user=admin_user, db=session,
            )
        assert result["days"] == 7


# ---------------------------------------------------------------------------
# COMPARE PERFORMANCE — lines 1053-1185
# ---------------------------------------------------------------------------


class TestComparePerformance:

    async def test_compare_empty(self, factory, admin_user, mock_request):
        """Compare with no bots (lines 1061-1069)."""
        async with factory() as session:
            result = await compare_bots_performance(request=mock_request,
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        assert result["bots"] == []
        assert result["days"] == 30

    async def test_compare_with_trades(self, factory, admin_user, sample_bot, mock_request):
        """Compare with trade data (lines 1074-1183)."""
        now = datetime.now(timezone.utc)
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
            result = await compare_bots_performance(request=mock_request,
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

    async def test_compare_demo_mode_filter(self, factory, admin_user, mock_request):
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
            demo_result = await compare_bots_performance(request=mock_request,
                days=30, demo_mode=True, user=admin_user, db=session,
            )
        for b in demo_result["bots"]:
            assert b["mode"] in ["demo", "both"]

        async with factory() as session:
            live_result = await compare_bots_performance(request=mock_request,
                days=30, demo_mode=False, user=admin_user, db=session,
            )
        for b in live_result["bots"]:
            assert b["mode"] in ["live", "both"]

    async def test_compare_no_trades(self, factory, admin_user, sample_bot, mock_request):
        """Compare with bot that has no trades (lines 1122-1124)."""
        async with factory() as session:
            result = await compare_bots_performance(request=mock_request,
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        bot = next((b for b in result["bots"] if b["bot_id"] == sample_bot.id), None)
        assert bot is not None
        assert bot["total_trades"] == 0
        assert bot["total_pnl"] == 0.0
        assert bot["win_rate"] == 0.0
        assert bot["series"] == []

    async def test_compare_last_trade_direction(self, factory, admin_user, sample_bot, mock_request):
        """Compare includes last trade direction and confidence (lines 1127-1136)."""
        now = datetime.now(timezone.utc)
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
            result = await compare_bots_performance(request=mock_request,
                days=30, demo_mode=None, user=admin_user, db=session,
            )
        bot = next((b for b in result["bots"] if b["bot_id"] == sample_bot.id), None)
        assert bot is not None
        assert bot["last_direction"] == "LONG"
        assert bot["last_confidence"] == 85

    async def test_compare_with_demo_filter_trades(self, factory, admin_user, sample_bot, mock_request):
        """Compare with demo_mode filters trade stats (lines 1080-1081, 1110-1111, 1129)."""
        now = datetime.now(timezone.utc)
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
            result = await compare_bots_performance(request=mock_request,
                days=30, demo_mode=True, user=admin_user, db=session,
            )
        assert len(result["bots"]) >= 1


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


@pytest.mark.asyncio
async def test_copy_trading_bot_does_not_conflict(factory, regular_user):
    """Copy bots may overlap with existing bots on the same symbols."""
    from src.services.bots_service import _check_symbol_conflicts

    async with factory() as session:
        existing = BotConfig(
            user_id=regular_user.id,
            exchange_type="bitget",
            mode="demo",
            strategy_type="edge_indicator",
            trading_pairs='["BTCUSDT"]',
            name="edge",
            is_enabled=True,
        )
        session.add(existing)
        await session.commit()

        # Without strategy_type, the existing bot conflicts
        conflicts_normal = await _check_symbol_conflicts(
            session, regular_user.id, "bitget", "demo", ["BTCUSDT"],
        )
        assert len(conflicts_normal) == 1

        # With strategy_type="copy_trading", conflicts are suppressed
        conflicts_copy = await _check_symbol_conflicts(
            session, regular_user.id, "bitget", "demo", ["BTCUSDT"],
            strategy_type="copy_trading",
        )
        assert conflicts_copy == []


# ---------------------------------------------------------------------------
# Symbol-conflict enforcement on create/update (UX-C5 / issue #247)
#
# Source-of-truth is the backend 409 — the frontend probe is UX sugar. These
# tests lock in the behavioural contract for the handler:
#   - CREATE: clashing symbol on an enabled bot → 409 SYMBOL_ALREADY_IN_USE
#   - CREATE: no clash → 200
#   - UPDATE: editing the same bot doesn't self-conflict
#   - UPDATE: clash against *another* enabled bot → 409
#   - Disabled (stopped) and soft-deleted rows are ignored
# ---------------------------------------------------------------------------


class TestSymbolConflictBlocking:
    """409 when creating/updating collides with an enabled bot's symbol."""

    async def test_create_blocks_when_symbol_in_use(self, factory, admin_user, mock_request):
        """Second bot on the same symbol while the first is enabled → 409."""
        from fastapi import HTTPException

        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id,
                name="Running BTC Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=True,
            ))
            await session.commit()

        async with factory() as session:
            body = BotConfigCreate(
                name="Duplicate BTC Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=["BTCUSDT"],
            )
            with pytest.raises(HTTPException) as exc_info:
                await create_bot(request=mock_request, body=body, user=admin_user, db=session)
            assert exc_info.value.status_code == 409
            detail = exc_info.value.detail
            assert isinstance(detail, dict)
            assert detail["code"] == "SYMBOL_ALREADY_IN_USE"
            assert "Running BTC Bot" in detail["conflicts"][0]["existing_bot_name"]

    async def test_create_succeeds_when_no_conflict(self, factory, admin_user, mock_request):
        """Different symbol → allowed."""
        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id,
                name="Running BTC Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=True,
            ))
            await session.commit()

        async with factory() as session:
            body = BotConfigCreate(
                name="ETH Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=["ETHUSDT"],
            )
            result = await create_bot(request=mock_request, body=body, user=admin_user, db=session)
            await session.commit()
        assert result.name == "ETH Bot"

    async def test_create_ignores_disabled_bot(self, factory, admin_user, mock_request):
        """A stopped (is_enabled=False) bot does not reserve its symbol."""
        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id,
                name="Stopped BTC Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            ))
            await session.commit()

        async with factory() as session:
            body = BotConfigCreate(
                name="New BTC Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=["BTCUSDT"],
            )
            result = await create_bot(request=mock_request, body=body, user=admin_user, db=session)
            await session.commit()
        assert result.name == "New BTC Bot"

    async def test_create_ignores_soft_deleted_bot(self, factory, admin_user, mock_request):
        """Soft-deleted bots (deleted_at != NULL) no longer block symbols."""
        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id,
                name="Deleted BTC Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=True,
                deleted_at=datetime.now(timezone.utc),
            ))
            await session.commit()

        async with factory() as session:
            body = BotConfigCreate(
                name="New BTC Bot",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=["BTCUSDT"],
            )
            result = await create_bot(request=mock_request, body=body, user=admin_user, db=session)
            await session.commit()
        assert result.name == "New BTC Bot"

    async def test_update_same_bot_does_not_self_conflict(self, factory, admin_user, mock_request, mock_orchestrator):
        """Editing an enabled bot's own symbol list must not trip the check."""
        async with factory() as session:
            config = BotConfig(
                user_id=admin_user.id,
                name="Edit Me",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=True,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)
            bot_id = config.id

        async with factory() as session:
            body = BotConfigUpdate(trading_pairs=["BTCUSDT", "ETHUSDT"])
            result = await update_bot(
                request=mock_request, bot_id=bot_id, body=body,
                user=admin_user, db=session, orchestrator=mock_orchestrator,
            )
            await session.commit()
        assert set(result.trading_pairs) == {"BTCUSDT", "ETHUSDT"}

    async def test_update_blocks_when_other_bot_has_symbol(self, factory, admin_user, mock_request, mock_orchestrator):
        """Adding a symbol another enabled bot already trades → 409."""
        from fastapi import HTTPException

        async with factory() as session:
            other = BotConfig(
                user_id=admin_user.id,
                name="Owns ETH",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["ETHUSDT"]),
                is_enabled=True,
            )
            editable = BotConfig(
                user_id=admin_user.id,
                name="Owns BTC",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=False,
            )
            session.add_all([other, editable])
            await session.commit()
            await session.refresh(editable)
            bot_id = editable.id

        async with factory() as session:
            body = BotConfigUpdate(trading_pairs=["BTCUSDT", "ETHUSDT"])
            with pytest.raises(HTTPException) as exc_info:
                await update_bot(
                    request=mock_request, bot_id=bot_id, body=body,
                    user=admin_user, db=session, orchestrator=mock_orchestrator,
                )
            assert exc_info.value.status_code == 409
            assert exc_info.value.detail["code"] == "SYMBOL_ALREADY_IN_USE"

    async def test_conflict_check_case_insensitive(self, factory, admin_user, mock_request):
        """btcusdt from the request must collide with stored BTCUSDT."""

        async with factory() as session:
            session.add(BotConfig(
                user_id=admin_user.id,
                name="Running Upper",
                strategy_type="test_strategy",
                exchange_type="bitget",
                mode="demo",
                trading_pairs=json.dumps(["BTCUSDT"]),
                is_enabled=True,
            ))
            await session.commit()

        # Pydantic enforces uppercase for BotConfigCreate, but the underlying
        # helper (used by the GET /symbol-conflicts endpoint) must still match
        # case-insensitively for any direct callers.
        from src.services.bots_service import _check_symbol_conflicts

        async with factory() as session:
            conflicts = await _check_symbol_conflicts(
                session, admin_user.id, "bitget", "demo", ["btcusdt"],
            )
            assert len(conflicts) == 1
            assert conflicts[0].symbol == "BTCUSDT"
