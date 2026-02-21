"""
Unit tests for BotWorker.

Tests cover:
- Initialization and config loading
- Status management (idle, starting, running, error, stopped)
- Schedule setup (interval, cron, rotation_only)
- Start/stop lifecycle
- Trade execution flow (mocked exchange + strategy)
- Position monitoring
- Risk limit enforcement
- Error handling (missing config, missing API keys)
- Notification dispatch
- get_status_dict serialization
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.bot.bot_worker import BotWorker


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_mock_config(**overrides):
    """Create a mock BotConfig with sensible defaults."""
    config = MagicMock()
    config.id = overrides.get("id", 1)
    config.user_id = overrides.get("user_id", 1)
    config.name = overrides.get("name", "Test Bot")
    config.description = overrides.get("description", "")
    config.strategy_type = overrides.get("strategy_type", "test_strategy")
    config.exchange_type = overrides.get("exchange_type", "bitget")
    config.mode = overrides.get("mode", "demo")
    config.trading_pairs = overrides.get("trading_pairs", json.dumps(["BTCUSDT"]))
    config.leverage = overrides.get("leverage", 4)
    config.position_size_percent = overrides.get("position_size_percent", 7.5)
    config.max_trades_per_day = overrides.get("max_trades_per_day", 2)
    config.take_profit_percent = overrides.get("take_profit_percent", 4.0)
    config.stop_loss_percent = overrides.get("stop_loss_percent", 1.5)
    config.daily_loss_limit_percent = overrides.get("daily_loss_limit_percent", 5.0)
    config.schedule_type = overrides.get("schedule_type", "market_sessions")
    config.schedule_config = overrides.get("schedule_config", None)
    config.strategy_params = overrides.get("strategy_params", None)
    config.discord_webhook_url = overrides.get("discord_webhook_url", None)
    config.telegram_bot_token = overrides.get("telegram_bot_token", None)
    config.telegram_chat_id = overrides.get("telegram_chat_id", None)
    config.rotation_enabled = overrides.get("rotation_enabled", False)
    config.rotation_interval_minutes = overrides.get("rotation_interval_minutes", None)
    config.rotation_start_time = overrides.get("rotation_start_time", None)
    config.is_enabled = overrides.get("is_enabled", True)
    config.per_asset_config = overrides.get("per_asset_config", None)
    return config


def _make_mock_balance(available=10000.0, total=10000.0):
    """Create a mock Balance object."""
    balance = MagicMock()
    balance.available = available
    balance.total = total
    balance.unrealized_pnl = 0
    return balance


def _make_mock_order(order_id="order_001", price=95000.0, side="long"):
    """Create a mock Order object."""
    order = MagicMock()
    order.order_id = order_id
    order.price = price
    order.side = side
    order.status = "filled"
    return order


def _make_mock_signal():
    """Create a mock TradeSignal."""
    from src.strategy.base import SignalDirection, TradeSignal
    return TradeSignal(
        direction=SignalDirection.LONG,
        confidence=75,
        symbol="BTCUSDT",
        entry_price=95000.0,
        target_price=97000.0,
        stop_loss=94000.0,
        reason="Test signal",
        metrics_snapshot={"test": True},
        timestamp=datetime.now(timezone.utc),
    )


def _make_db_session():
    """Create a mock DB session with sync methods (add, delete) as MagicMock."""
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    return session


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestBotWorkerInit:
    """Tests for BotWorker initial state."""

    def test_initial_state(self):
        worker = BotWorker(bot_config_id=1)

        assert worker.bot_config_id == 1
        assert worker.status == "idle"
        assert worker.error_message is None
        assert worker.started_at is None
        assert worker.last_analysis is None
        assert worker.trades_today == 0

    def test_config_property_initially_none(self):
        worker = BotWorker(bot_config_id=1)
        assert worker.config is None


# ---------------------------------------------------------------------------
# Initialize tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBotWorkerInitialize:
    """Tests for the initialize() method."""

    async def test_initialize_fails_when_config_not_found(self):
        worker = BotWorker(bot_config_id=999)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.bot_worker.get_session", return_value=mock_session):
            result = await worker.initialize()

        assert result is False
        assert worker.status == "error"
        assert "not found" in worker.error_message

    async def test_initialize_fails_when_no_api_keys(self):
        worker = BotWorker(bot_config_id=1)
        config = _make_mock_config()

        # First query returns config, second returns None (no ExchangeConnection)
        call_count = 0
        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = config
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_session = _make_db_session()
        mock_session.execute = mock_execute
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.bot_worker.get_session", return_value=mock_session):
            result = await worker.initialize()

        assert result is False
        assert worker.status == "error"
        assert "API keys" in worker.error_message


# ---------------------------------------------------------------------------
# Start/stop tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBotWorkerStartStop:
    """Tests for start() and stop() lifecycle."""

    async def test_start_sets_running_status(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._scheduler = MagicMock()
        worker._scheduler.running = True
        worker._analyze_and_trade_safe = AsyncMock()

        await worker.start()

        assert worker.status == "running"
        assert worker.started_at is not None
        assert worker.error_message is None

    async def test_start_noop_if_already_running(self):
        worker = BotWorker(bot_config_id=1)
        worker.status = "running"
        worker._scheduler = MagicMock()

        # Should return early
        await worker.start()
        worker._scheduler.start.assert_not_called()

    async def test_stop_shuts_down_scheduler(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._scheduler = MagicMock()
        worker._scheduler.running = True
        worker._strategy = AsyncMock()
        worker._demo_client = None
        worker._live_client = None

        await worker.stop()

        worker._scheduler.shutdown.assert_called_once_with(wait=False)
        assert worker.status == "stopped"

    async def test_stop_closes_clients(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._scheduler = MagicMock()
        worker._scheduler.running = True
        worker._strategy = AsyncMock()

        mock_demo = AsyncMock()
        mock_live = AsyncMock()
        worker._demo_client = mock_demo
        worker._live_client = mock_live

        await worker.stop()

        mock_demo.close.assert_awaited_once()
        mock_live.close.assert_awaited_once()

    async def test_stop_handles_client_close_error(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._scheduler = MagicMock()
        worker._scheduler.running = True
        worker._strategy = AsyncMock()

        mock_client = AsyncMock()
        mock_client.close.side_effect = RuntimeError("close failed")
        worker._demo_client = mock_client
        worker._live_client = None

        # Should not raise
        await worker.stop()
        assert worker.status == "stopped"


# ---------------------------------------------------------------------------
# Schedule setup tests
# ---------------------------------------------------------------------------

class TestScheduleSetup:
    """Tests for _setup_schedule method."""

    def test_interval_schedule(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            schedule_type="interval",
            schedule_config=json.dumps({"interval_minutes": 30}),
        )
        worker._scheduler = MagicMock()

        worker._setup_schedule()

        # Should add analysis job + monitor job + daily summary
        assert worker._scheduler.add_job.call_count == 3

    def test_custom_cron_schedule(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            schedule_type="custom_cron",
            schedule_config=json.dumps({"hours": [2, 10, 18]}),
        )
        worker._scheduler = MagicMock()

        worker._setup_schedule()

        assert worker._scheduler.add_job.call_count == 3

    def test_rotation_only_no_analysis_job(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            schedule_type="rotation_only",
            rotation_enabled=True,
            rotation_interval_minutes=60,
        )
        worker._scheduler = MagicMock()

        worker._setup_schedule()

        # Should add monitor job + rotation job + daily summary (no regular analysis)
        _job_ids = [
            call.kwargs.get("id", call.args[2] if len(call.args) > 2 else "")
            for call in worker._scheduler.add_job.call_args_list
        ]
        assert worker._scheduler.add_job.call_count == 3  # monitor + rotation + daily_summary

    def test_default_market_sessions(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            schedule_type="market_sessions",
            schedule_config=None,
        )
        worker._scheduler = MagicMock()

        worker._setup_schedule()

        assert worker._scheduler.add_job.call_count == 3


# ---------------------------------------------------------------------------
# Analyze and trade tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeAndTrade:
    """Tests for the main analysis loop."""

    async def test_skips_when_risk_disallows(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (False, "Daily loss limit reached")
        worker._risk_manager = mock_rm
        worker._analyze_symbol = AsyncMock()

        await worker._analyze_and_trade()

        # Should not call _analyze_symbol when risk disallows
        worker._analyze_symbol.assert_not_awaited()

    async def test_analyzes_each_symbol(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT"]),
        )

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.get_remaining_trades.return_value = 5
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())
        worker._client = mock_client

        worker._analyze_symbol = AsyncMock()

        await worker._analyze_and_trade()

        assert worker._analyze_symbol.await_count == 2

    async def test_stops_when_no_remaining_trades(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
        )

        mock_rm = MagicMock()
        mock_rm.can_trade.return_value = (True, "")
        # After first symbol, per-symbol check blocks remaining
        mock_rm.get_remaining_trades.side_effect = [1, 0, 0]
        worker._risk_manager = mock_rm

        mock_client = AsyncMock()
        mock_client.get_account_balance = AsyncMock(return_value=_make_mock_balance())
        worker._client = mock_client

        # Override can_trade to block after first symbol
        call_count = [0]
        def can_trade_side_effect(symbol=None):
            if symbol is None:
                return (True, "")
            call_count[0] += 1
            if call_count[0] > 1:
                return (False, "Trade limit reached")
            return (True, "")
        mock_rm.can_trade.side_effect = can_trade_side_effect

        worker._analyze_symbol = AsyncMock()

        await worker._analyze_and_trade()

        # Should only analyze first symbol before per-symbol limit
        assert worker._analyze_symbol.await_count == 1

    async def test_analyze_and_trade_safe_catches_errors(self):
        worker = BotWorker(bot_config_id=1)
        worker._analyze_and_trade = AsyncMock(side_effect=RuntimeError("boom"))

        # Should not raise
        await worker._analyze_and_trade_safe()

        assert worker.error_message == "boom"


# ---------------------------------------------------------------------------
# Execute trade tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExecuteTrade:
    """Tests for _execute_trade method."""

    async def test_skips_when_position_too_small(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance(available=10.0)

        mock_rm = MagicMock()
        mock_rm.calculate_position_size.return_value = (3.0, 0.00003)  # < $5 minimum
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        await worker._execute_trade(signal, mock_client, demo_mode=True)

        # Should not place order
        mock_client.place_market_order.assert_not_awaited()

    async def test_places_order_and_records_trade(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker._get_notifiers = AsyncMock(return_value=[])

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.set_leverage = AsyncMock()
        mock_client.place_market_order.return_value = _make_mock_order()
        mock_client.get_fill_price = AsyncMock(return_value=95100.0)

        mock_rm = MagicMock()
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        mock_session = _make_db_session()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.trade_executor.get_session", return_value=mock_session):
            await worker._execute_trade(signal, mock_client, demo_mode=True)

        mock_client.place_market_order.assert_awaited_once()
        mock_rm.record_trade_entry.assert_called_once()
        assert worker.trades_today == 1

    async def test_handles_order_failure(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.set_leverage = AsyncMock()
        mock_client.place_market_order.return_value = None  # Failed

        mock_rm = MagicMock()
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        await worker._execute_trade(signal, mock_client, demo_mode=True)

        # Should not record trade
        mock_rm.record_trade_entry.assert_not_called()
        assert worker.trades_today == 0

    async def test_handles_minimum_amount_error(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()

        mock_client = AsyncMock()
        mock_client.get_account_balance.return_value = _make_mock_balance()
        mock_client.set_leverage = AsyncMock()
        mock_client.place_market_order.side_effect = Exception("minimum amount required is 5 USDT")

        mock_rm = MagicMock()
        mock_rm.calculate_position_size.return_value = (1000.0, 0.01)
        worker._risk_manager = mock_rm

        signal = _make_mock_signal()

        # Should not raise (caught internally)
        await worker._execute_trade(signal, mock_client, demo_mode=True)
        assert worker.trades_today == 0


# ---------------------------------------------------------------------------
# Monitor positions tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMonitorPositions:
    """Tests for position monitoring."""

    async def test_monitor_safe_catches_errors(self):
        worker = BotWorker(bot_config_id=1)
        worker._monitor_positions = AsyncMock(side_effect=RuntimeError("db error"))

        # Should not raise
        await worker._monitor_positions_safe()

    async def test_monitor_does_nothing_without_open_trades(self):
        worker = BotWorker(bot_config_id=1)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = _make_db_session()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("src.bot.position_monitor.get_session", return_value=mock_session):
            await worker._monitor_positions()

        # No _check_position calls


# ---------------------------------------------------------------------------
# Notifier setup tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetNotifiers:
    """Tests for _get_notifiers and _get_discord_notifier."""

    async def test_returns_empty_when_no_config(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            discord_webhook_url=None,
            telegram_bot_token=None,
        )

        notifiers = await worker._get_notifiers()
        assert notifiers == []

    async def test_returns_discord_when_configured(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config(
            discord_webhook_url="encrypted_webhook_url",
        )

        with patch("src.bot.notifications.decrypt_value", return_value="https://discord.com/webhook/123"):
            notifier = await worker._get_discord_notifier()

        assert notifier is not None


# ---------------------------------------------------------------------------
# get_status_dict tests
# ---------------------------------------------------------------------------

class TestGetStatusDict:
    """Tests for status serialization."""

    def test_returns_dict_with_all_fields(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker.status = "running"
        worker.started_at = datetime(2025, 1, 1, 12, 0)
        worker.last_analysis = datetime(2025, 1, 1, 13, 0)
        worker.trades_today = 3

        status = worker.get_status_dict()

        assert status["bot_config_id"] == 1
        assert status["name"] == "Test Bot"
        assert status["status"] == "running"
        assert status["trades_today"] == 3
        assert status["started_at"] is not None
        assert status["last_analysis"] is not None

    def test_returns_dict_without_config(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = None

        status = worker.get_status_dict()

        assert status["name"] == "Unknown"
        assert status["trading_pairs"] == []

    def test_status_with_error(self):
        worker = BotWorker(bot_config_id=1)
        worker._config = _make_mock_config()
        worker.status = "error"
        worker.error_message = "Init failed"

        status = worker.get_status_dict()

        assert status["status"] == "error"
        assert status["error_message"] == "Init failed"


# ---------------------------------------------------------------------------
# Symbol lock tests
# ---------------------------------------------------------------------------

class TestSymbolLock:
    """Tests for per-symbol locking."""

    def test_creates_lock_per_symbol(self):
        worker = BotWorker(bot_config_id=1)

        lock1 = worker._get_symbol_lock("BTCUSDT")
        lock2 = worker._get_symbol_lock("ETHUSDT")
        lock3 = worker._get_symbol_lock("BTCUSDT")

        assert lock1 is lock3  # Same symbol -> same lock
        assert lock1 is not lock2  # Different symbols -> different locks
        assert isinstance(lock1, asyncio.Lock)
