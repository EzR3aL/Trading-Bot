"""
Unit tests for TradingBot (legacy standalone bot).

Tests cover:
- TradingBot initialization (__init__)
- initialize() method with component setup
- _initialize_daily_session() balance handling
- _setup_scheduled_jobs() scheduler configuration
- start() lifecycle
- stop() graceful shutdown
- analyze_and_trade() main analysis loop
- _analyze_symbol() single symbol analysis
- _execute_trade() trade execution in demo and live modes
- monitor_positions() position monitoring
- _record_funding_payments() funding payment tracking
- _check_position() individual position checking
- _handle_closed_position() closed position handling
- send_daily_summary() daily summary generation
- close_all_positions() emergency close
- run_once() single analysis cycle
- Error handling and recovery across all methods
- Configuration validation flows
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_trade_signal(
    direction="long",
    confidence=75,
    symbol="BTCUSDT",
    entry_price=95000.0,
    target_price=97000.0,
    stop_loss=94000.0,
    reason="Test signal",
    metrics_snapshot=None,
):
    """Create a mock TradeSignal with sensible defaults."""
    from src.strategy.base import SignalDirection, TradeSignal

    if direction == "long":
        sig_dir = SignalDirection.LONG
    else:
        sig_dir = SignalDirection.SHORT

    return TradeSignal(
        direction=sig_dir,
        confidence=confidence,
        symbol=symbol,
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        reason=reason,
        metrics_snapshot=metrics_snapshot or {"test": True},
        timestamp=datetime.utcnow(),
    )


def _make_mock_trade(
    trade_id=1,
    symbol="BTCUSDT",
    side="long",
    size=0.01,
    entry_price=95000.0,
    take_profit=97000.0,
    stop_loss=94000.0,
    order_id="order_001",
    entry_time=None,
):
    """Create a mock Trade object."""
    trade = MagicMock()
    trade.id = trade_id
    trade.symbol = symbol
    trade.side = side
    trade.size = size
    trade.entry_price = entry_price
    trade.take_profit = take_profit
    trade.stop_loss = stop_loss
    trade.order_id = order_id
    trade.entry_time = entry_time or datetime.utcnow() - timedelta(hours=2)
    trade.reason = "Test trade reason"
    return trade


def _make_mock_settings():
    """Create a mock settings object matching config.settings.Settings."""
    mock_settings = MagicMock()
    mock_settings.logging.level = "INFO"
    mock_settings.logging.file = "logs/test.log"
    mock_settings.is_demo_mode = True
    mock_settings.trading.trading_pairs = ["BTCUSDT", "ETHUSDT"]
    mock_settings.trading.max_trades_per_day = 2
    mock_settings.trading.daily_loss_limit_percent = 5.0
    mock_settings.trading.leverage = 4
    mock_settings.trading.position_size_percent = 7.5
    return mock_settings


@pytest.fixture
def mock_settings():
    """Provide a mock settings object for patching."""
    return _make_mock_settings()


@pytest.fixture
def bot_patches(mock_settings):
    """
    Context manager that patches all external dependencies for TradingBot
    so it can be instantiated safely.
    """
    with patch("src.bot.trading_bot.settings", mock_settings), \
         patch("src.bot.trading_bot.setup_logging"):
        yield mock_settings


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestTradingBotInit:
    """Tests for TradingBot.__init__."""

    def test_initial_state_components_are_none(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        assert bot.bitget_client is None
        assert bot.data_fetcher is None
        assert bot.strategy is None
        assert bot.risk_manager is None
        assert bot.discord is None
        assert bot.trade_db is None
        assert bot.funding_tracker is None
        assert bot.scheduler is None

    def test_initial_state_flags(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        assert bot._running is False
        assert bot._initialized is False

    def test_calls_setup_logging(self, mock_settings):
        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging") as mock_setup:
            from src.bot.trading_bot import TradingBot
            _bot = TradingBot()

            mock_setup.assert_called_once_with(
                log_level=mock_settings.logging.level,
                log_file=mock_settings.logging.file,
            )


# ---------------------------------------------------------------------------
# initialize() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestInitialize:
    """Tests for TradingBot.initialize()."""

    async def test_initialize_success_demo_mode(self, mock_settings):
        mock_settings.is_demo_mode = True

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"), \
             patch("src.bot.trading_bot.BitgetClient") as MockBitget, \
             patch("src.bot.trading_bot.MarketDataFetcher") as MockDataFetcher, \
             patch("src.bot.trading_bot.LiquidationHunterStrategy") as MockStrategy, \
             patch("src.bot.trading_bot.RiskManager") as MockRisk, \
             patch("src.bot.trading_bot.DiscordNotifier") as MockDiscord, \
             patch("src.bot.trading_bot.TradeDatabase") as MockTradeDB, \
             patch("src.bot.trading_bot.FundingTracker") as MockFunding, \
             patch("src.bot.trading_bot.AsyncIOScheduler") as MockScheduler:

            # Configure mocks
            mock_settings.validate_strict = MagicMock(return_value=(True, []))

            mock_bitget = AsyncMock()
            MockBitget.return_value = mock_bitget

            mock_data = AsyncMock()
            MockDataFetcher.return_value = mock_data

            mock_strategy = MagicMock()
            MockStrategy.return_value = mock_strategy

            mock_risk = MagicMock()
            MockRisk.return_value = mock_risk

            mock_discord = AsyncMock()
            MockDiscord.return_value = mock_discord

            mock_trade_db = AsyncMock()
            MockTradeDB.return_value = mock_trade_db

            mock_funding = AsyncMock()
            MockFunding.return_value = mock_funding

            mock_scheduler = MagicMock()
            MockScheduler.return_value = mock_scheduler

            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialize_daily_session = AsyncMock()

            result = await bot.initialize()

            assert result is True
            assert bot._initialized is True
            assert bot.bitget_client is mock_bitget
            assert bot.data_fetcher is mock_data
            assert bot.risk_manager is mock_risk
            assert bot.discord is mock_discord
            assert bot.trade_db is mock_trade_db
            assert bot.funding_tracker is mock_funding

    async def test_initialize_returns_false_on_config_validation_failure(self, mock_settings):
        mock_settings.validate_strict = MagicMock(return_value=(False, ["Bad config"]))

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()

            result = await bot.initialize()

            assert result is False
            assert bot._initialized is False

    async def test_initialize_returns_false_on_config_validation_error_exception(self, mock_settings):
        from config.settings import ConfigValidationError
        mock_settings.validate_strict = MagicMock(
            side_effect=ConfigValidationError(["critical error"])
        )

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()

            result = await bot.initialize()

            assert result is False

    async def test_initialize_returns_false_on_unexpected_exception(self, mock_settings):
        mock_settings.validate_strict = MagicMock(side_effect=RuntimeError("boom"))

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()

            result = await bot.initialize()

            assert result is False

    async def test_initialize_logs_warnings_for_optional_config_errors(self, mock_settings):
        mock_settings.validate_strict = MagicMock(
            return_value=(True, ["optional: Discord not configured"])
        )

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"), \
             patch("src.bot.trading_bot.BitgetClient") as MockBitget, \
             patch("src.bot.trading_bot.MarketDataFetcher") as MockDataFetcher, \
             patch("src.bot.trading_bot.LiquidationHunterStrategy"), \
             patch("src.bot.trading_bot.RiskManager"), \
             patch("src.bot.trading_bot.DiscordNotifier") as MockDiscord, \
             patch("src.bot.trading_bot.TradeDatabase") as MockTradeDB, \
             patch("src.bot.trading_bot.FundingTracker") as MockFunding, \
             patch("src.bot.trading_bot.AsyncIOScheduler"):

            MockBitget.return_value = AsyncMock()
            MockDataFetcher.return_value = AsyncMock()
            MockDiscord.return_value = AsyncMock()
            MockTradeDB.return_value = AsyncMock()
            MockFunding.return_value = AsyncMock()

            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialize_daily_session = AsyncMock()

            result = await bot.initialize()

            # Should succeed even with optional warnings
            assert result is True

    async def test_initialize_live_mode_logging(self, mock_settings):
        mock_settings.is_demo_mode = False
        mock_settings.validate_strict = MagicMock(return_value=(True, []))

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"), \
             patch("src.bot.trading_bot.BitgetClient") as MockBitget, \
             patch("src.bot.trading_bot.MarketDataFetcher") as MockDataFetcher, \
             patch("src.bot.trading_bot.LiquidationHunterStrategy"), \
             patch("src.bot.trading_bot.RiskManager"), \
             patch("src.bot.trading_bot.DiscordNotifier") as MockDiscord, \
             patch("src.bot.trading_bot.TradeDatabase") as MockTradeDB, \
             patch("src.bot.trading_bot.FundingTracker") as MockFunding, \
             patch("src.bot.trading_bot.AsyncIOScheduler"), \
             patch("src.bot.trading_bot.logger") as mock_logger:

            MockBitget.return_value = AsyncMock()
            MockDataFetcher.return_value = AsyncMock()
            MockDiscord.return_value = AsyncMock()
            MockTradeDB.return_value = AsyncMock()
            MockFunding.return_value = AsyncMock()

            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialize_daily_session = AsyncMock()

            result = await bot.initialize()

            assert result is True
            # Live mode should call logger.warning
            mock_logger.warning.assert_called()


# ---------------------------------------------------------------------------
# _initialize_daily_session() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestInitializeDailySession:
    """Tests for _initialize_daily_session()."""

    async def test_initializes_with_balance(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_account_balance.return_value = {
            "available": "5000.0",
            "usdtEquity": "5500.0",
        }
        bot.risk_manager = MagicMock()

        await bot._initialize_daily_session()

        bot.risk_manager.initialize_day.assert_called_once_with(5500.0)

    async def test_initializes_with_available_when_no_equity(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_account_balance.return_value = {
            "available": "3000.0",
        }
        bot.risk_manager = MagicMock()

        await bot._initialize_daily_session()

        bot.risk_manager.initialize_day.assert_called_once_with(3000.0)

    async def test_initializes_with_zero_when_no_balance(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_account_balance.return_value = None
        bot.risk_manager = MagicMock()

        await bot._initialize_daily_session()

        bot.risk_manager.initialize_day.assert_called_once_with(0)

    async def test_handles_exception_gracefully(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_account_balance.side_effect = RuntimeError("API down")
        bot.risk_manager = MagicMock()

        # Should not raise
        await bot._initialize_daily_session()


# ---------------------------------------------------------------------------
# _setup_scheduled_jobs() tests
# ---------------------------------------------------------------------------

class TestSetupScheduledJobs:
    """Tests for _setup_scheduled_jobs()."""

    def test_adds_three_scheduled_jobs(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.scheduler = MagicMock()
        bot._setup_scheduled_jobs()

        assert bot.scheduler.add_job.call_count == 3

    def test_adds_main_analysis_job(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.scheduler = MagicMock()
        bot._setup_scheduled_jobs()

        call_kwargs_list = [call.kwargs for call in bot.scheduler.add_job.call_args_list]
        job_ids = [kw.get("id") for kw in call_kwargs_list]

        assert "main_analysis" in job_ids
        assert "position_monitor" in job_ids
        assert "daily_summary" in job_ids

    def test_jobs_replace_existing(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.scheduler = MagicMock()
        bot._setup_scheduled_jobs()

        for call in bot.scheduler.add_job.call_args_list:
            assert call.kwargs.get("replace_existing") is True


# ---------------------------------------------------------------------------
# start() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStart:
    """Tests for start() lifecycle."""

    async def test_start_calls_initialize_when_not_initialized(self, mock_settings):
        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialized = False
            bot.initialize = AsyncMock(return_value=False)

            await bot.start()

            bot.initialize.assert_awaited_once()

    async def test_start_returns_early_if_init_fails(self, mock_settings):
        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialized = False
            bot.initialize = AsyncMock(return_value=False)

            await bot.start()

            assert bot._running is False

    async def test_start_sends_discord_notification_and_starts_scheduler(self, mock_settings):
        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialized = True
            bot.discord = AsyncMock()
            bot.scheduler = MagicMock()
            bot.analyze_and_trade = AsyncMock()

            # Simulate the while loop terminating immediately
            bot._running = True

            async def stop_after_start():
                bot._running = False

            bot.analyze_and_trade = AsyncMock(side_effect=stop_after_start)
            bot.stop = AsyncMock()

            await bot.start()

            bot.discord.send_bot_status.assert_awaited_once()
            bot.scheduler.start.assert_called_once()


# ---------------------------------------------------------------------------
# stop() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStop:
    """Tests for stop() graceful shutdown."""

    async def test_stop_sets_running_false(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot._running = True
        bot.scheduler = None
        bot.bitget_client = None
        bot.data_fetcher = None
        bot.strategy = None
        bot.discord = None

        await bot.stop()

        assert bot._running is False

    async def test_stop_shuts_down_running_scheduler(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.scheduler = MagicMock()
        bot.scheduler.running = True
        bot.bitget_client = None
        bot.data_fetcher = None
        bot.strategy = None
        bot.discord = None

        await bot.stop()

        bot.scheduler.shutdown.assert_called_once()

    async def test_stop_does_not_shutdown_if_scheduler_not_running(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.scheduler = MagicMock()
        bot.scheduler.running = False
        bot.bitget_client = None
        bot.data_fetcher = None
        bot.strategy = None
        bot.discord = None

        await bot.stop()

        bot.scheduler.shutdown.assert_not_called()

    async def test_stop_closes_all_clients(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.scheduler = None
        bot.bitget_client = AsyncMock()
        bot.data_fetcher = AsyncMock()
        bot.strategy = AsyncMock()
        bot.discord = AsyncMock()

        await bot.stop()

        bot.bitget_client.close.assert_awaited_once()
        bot.data_fetcher.close.assert_awaited_once()
        bot.strategy.close.assert_awaited_once()
        bot.discord.send_bot_status.assert_awaited_once()
        bot.discord.close.assert_awaited_once()

    async def test_stop_sends_stopped_status_via_discord(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.scheduler = None
        bot.bitget_client = None
        bot.data_fetcher = None
        bot.strategy = None
        bot.discord = AsyncMock()

        await bot.stop()

        bot.discord.send_bot_status.assert_awaited_once_with(
            "STOPPED", "Trading bot has been stopped."
        )

    async def test_stop_skips_none_components(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.scheduler = None
        bot.bitget_client = None
        bot.data_fetcher = None
        bot.strategy = None
        bot.discord = None

        # Should not raise
        await bot.stop()
        assert bot._running is False


# ---------------------------------------------------------------------------
# analyze_and_trade() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeAndTrade:
    """Tests for the main analyze_and_trade() method."""

    async def test_skips_when_risk_manager_disallows(self, mock_settings):
        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.can_trade.return_value = (False, "Daily loss limit reached")
            bot._analyze_symbol = AsyncMock()

            await bot.analyze_and_trade()

            bot._analyze_symbol.assert_not_awaited()

    async def test_analyzes_each_trading_pair(self, mock_settings):
        mock_settings.trading.trading_pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.can_trade.return_value = (True, "")
            bot.risk_manager.get_remaining_trades.return_value = 5
            bot._analyze_symbol = AsyncMock()
            bot.discord = AsyncMock()

            await bot.analyze_and_trade()

            assert bot._analyze_symbol.await_count == 3

    async def test_stops_when_no_remaining_trades(self, mock_settings):
        mock_settings.trading.trading_pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.can_trade.return_value = (True, "")
            bot.risk_manager.get_remaining_trades.side_effect = [1, 0]
            bot._analyze_symbol = AsyncMock()
            bot.discord = AsyncMock()

            await bot.analyze_and_trade()

            # Should only analyze first symbol
            assert bot._analyze_symbol.await_count == 1

    async def test_handles_data_fetch_error(self, mock_settings):
        from src.data.market_data import DataFetchError

        mock_settings.trading.trading_pairs = ["BTCUSDT"]

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.can_trade.return_value = (True, "")
            bot.risk_manager.get_remaining_trades.return_value = 5
            bot._analyze_symbol = AsyncMock(
                side_effect=DataFetchError("CoinGlass", "API timeout")
            )
            bot.discord = AsyncMock()

            # Should not raise
            await bot.analyze_and_trade()

            bot.discord.send_error.assert_awaited_once()

    async def test_handles_general_exception_during_analysis(self, mock_settings):
        mock_settings.trading.trading_pairs = ["BTCUSDT"]

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.can_trade.return_value = (True, "")
            bot.risk_manager.get_remaining_trades.return_value = 5
            bot._analyze_symbol = AsyncMock(side_effect=RuntimeError("unexpected"))
            bot.discord = AsyncMock()

            # Should not raise
            await bot.analyze_and_trade()

            bot.discord.send_error.assert_awaited_once()

    async def test_continues_to_next_symbol_after_error(self, mock_settings):
        mock_settings.trading.trading_pairs = ["BTCUSDT", "ETHUSDT"]

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.can_trade.return_value = (True, "")
            bot.risk_manager.get_remaining_trades.return_value = 5

            call_count = [0]
            async def analyze_side_effect(symbol):
                call_count[0] += 1
                if symbol == "BTCUSDT":
                    raise RuntimeError("BTC error")
                # ETHUSDT succeeds

            bot._analyze_symbol = AsyncMock(side_effect=analyze_side_effect)
            bot.discord = AsyncMock()

            await bot.analyze_and_trade()

            # Both symbols should have been attempted
            assert bot._analyze_symbol.await_count == 2


# ---------------------------------------------------------------------------
# _analyze_symbol() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAnalyzeSymbol:
    """Tests for _analyze_symbol()."""

    async def test_skips_symbol_with_open_position(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.trade_db = AsyncMock()
        bot.trade_db.get_open_trades.return_value = [_make_mock_trade()]
        bot.strategy = AsyncMock()

        await bot._analyze_symbol("BTCUSDT")

        bot.strategy.generate_signal.assert_not_awaited()

    async def test_skips_when_should_not_trade(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.trade_db = AsyncMock()
        bot.trade_db.get_open_trades.return_value = []

        signal = _make_trade_signal()
        bot.strategy = AsyncMock()
        bot.strategy.generate_signal.return_value = signal
        bot.strategy.should_trade.return_value = (False, "Confidence too low")

        bot.discord = AsyncMock()
        bot._execute_trade = AsyncMock()

        await bot._analyze_symbol("BTCUSDT")

        bot._execute_trade.assert_not_awaited()
        bot.discord.send_signal_alert.assert_not_awaited()

    async def test_sends_signal_alert_and_executes_trade(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.trade_db = AsyncMock()
        bot.trade_db.get_open_trades.return_value = []

        signal = _make_trade_signal()
        bot.strategy = AsyncMock()
        bot.strategy.generate_signal.return_value = signal
        bot.strategy.should_trade.return_value = (True, "Strong signal")

        bot.discord = AsyncMock()
        bot._execute_trade = AsyncMock()

        await bot._analyze_symbol("BTCUSDT")

        bot.discord.send_signal_alert.assert_awaited_once()
        bot._execute_trade.assert_awaited_once_with(signal)


# ---------------------------------------------------------------------------
# _execute_trade() tests - demo mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExecuteTradeDemoMode:
    """Tests for _execute_trade() in demo mode."""

    async def test_demo_mode_uses_simulated_balance(self, mock_settings):
        mock_settings.is_demo_mode = True

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (1000.0, 0.01)
            bot.bitget_client = AsyncMock()
            bot.trade_db = AsyncMock()
            bot.trade_db.create_trade.return_value = 1
            bot.discord = AsyncMock()

            signal = _make_trade_signal()
            await bot._execute_trade(signal)

            # Should NOT call bitget_client.get_account_balance in demo mode
            bot.bitget_client.get_account_balance.assert_not_awaited()
            bot.trade_db.create_trade.assert_awaited_once()
            bot.risk_manager.record_trade_entry.assert_called_once()
            bot.discord.send_trade_entry.assert_awaited_once()

    async def test_demo_mode_skips_small_position(self, mock_settings):
        mock_settings.is_demo_mode = True

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (5.0, 0.00005)
            bot.bitget_client = AsyncMock()
            bot.trade_db = AsyncMock()
            bot.discord = AsyncMock()

            signal = _make_trade_signal()
            await bot._execute_trade(signal)

            bot.trade_db.create_trade.assert_not_awaited()

    async def test_demo_mode_generates_demo_order_id(self, mock_settings):
        mock_settings.is_demo_mode = True

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (500.0, 0.005)
            bot.bitget_client = AsyncMock()
            bot.trade_db = AsyncMock()
            bot.trade_db.create_trade.return_value = 42
            bot.discord = AsyncMock()

            signal = _make_trade_signal()
            await bot._execute_trade(signal)

            # The order_id passed to create_trade should start with DEMO_
            call_kwargs = bot.trade_db.create_trade.call_args
            assert call_kwargs.kwargs.get("order_id", "").startswith("DEMO_") or \
                   (len(call_kwargs.args) > 7 and str(call_kwargs.args[7]).startswith("DEMO_"))


# ---------------------------------------------------------------------------
# _execute_trade() tests - live mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExecuteTradeLiveMode:
    """Tests for _execute_trade() in live mode."""

    async def test_live_mode_calls_exchange_api(self, mock_settings):
        mock_settings.is_demo_mode = False

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (1000.0, 0.01)
            bot.bitget_client = AsyncMock()
            bot.bitget_client.get_account_balance.return_value = {"available": "10000"}
            bot.bitget_client.place_market_order.return_value = {"orderId": "live_001"}
            bot.bitget_client.get_fill_price.return_value = 95100.0
            bot.trade_db = AsyncMock()
            bot.trade_db.create_trade.return_value = 1
            bot.discord = AsyncMock()

            signal = _make_trade_signal()
            await bot._execute_trade(signal)

            bot.bitget_client.get_account_balance.assert_awaited_once()
            bot.bitget_client.set_leverage.assert_awaited_once()
            bot.bitget_client.place_market_order.assert_awaited_once()
            bot.bitget_client.get_fill_price.assert_awaited_once()

    async def test_live_mode_returns_when_order_fails(self, mock_settings):
        mock_settings.is_demo_mode = False

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (1000.0, 0.01)
            bot.bitget_client = AsyncMock()
            bot.bitget_client.get_account_balance.return_value = {"available": "10000"}
            bot.bitget_client.place_market_order.return_value = None
            bot.trade_db = AsyncMock()
            bot.discord = AsyncMock()

            signal = _make_trade_signal()
            await bot._execute_trade(signal)

            bot.trade_db.create_trade.assert_not_awaited()

    async def test_live_mode_uses_signal_price_when_fill_unavailable(self, mock_settings):
        mock_settings.is_demo_mode = False

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (1000.0, 0.01)
            bot.bitget_client = AsyncMock()
            bot.bitget_client.get_account_balance.return_value = {"available": "10000"}
            bot.bitget_client.place_market_order.return_value = {"orderId": "live_002"}
            bot.bitget_client.get_fill_price.return_value = None
            bot.trade_db = AsyncMock()
            bot.trade_db.create_trade.return_value = 1
            bot.discord = AsyncMock()

            signal = _make_trade_signal(entry_price=95000.0)
            await bot._execute_trade(signal)

            # Should use signal entry price
            create_kwargs = bot.trade_db.create_trade.call_args.kwargs
            assert create_kwargs["entry_price"] == 95000.0

    async def test_live_mode_short_trade_side(self, mock_settings):
        mock_settings.is_demo_mode = False

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (1000.0, 0.01)
            bot.bitget_client = AsyncMock()
            bot.bitget_client.get_account_balance.return_value = {"available": "10000"}
            bot.bitget_client.place_market_order.return_value = {"orderId": "short_001"}
            bot.bitget_client.get_fill_price.return_value = 94900.0
            bot.trade_db = AsyncMock()
            bot.trade_db.create_trade.return_value = 1
            bot.discord = AsyncMock()

            signal = _make_trade_signal(direction="short")
            await bot._execute_trade(signal)

            call_kwargs = bot.bitget_client.place_market_order.call_args.kwargs
            assert call_kwargs["side"] == "sell"

    async def test_handles_bitget_client_error(self, mock_settings):
        from src.exchanges.bitget.client import BitgetClientError

        mock_settings.is_demo_mode = False

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (1000.0, 0.01)
            bot.bitget_client = AsyncMock()
            bot.bitget_client.get_account_balance.return_value = {"available": "10000"}
            bot.bitget_client.set_leverage.side_effect = BitgetClientError("Rate limited")
            bot.trade_db = AsyncMock()
            bot.discord = AsyncMock()

            signal = _make_trade_signal()
            # Should not raise
            await bot._execute_trade(signal)

            bot.discord.send_error.assert_awaited_once()

    async def test_handles_unexpected_error(self, mock_settings):
        mock_settings.is_demo_mode = False

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.side_effect = RuntimeError("crash")
            bot.bitget_client = AsyncMock()
            bot.bitget_client.get_account_balance.return_value = {"available": "10000"}
            bot.trade_db = AsyncMock()
            bot.discord = AsyncMock()

            signal = _make_trade_signal()
            await bot._execute_trade(signal)

            bot.discord.send_error.assert_awaited_once()


# ---------------------------------------------------------------------------
# monitor_positions() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMonitorPositions:
    """Tests for monitor_positions()."""

    async def test_returns_early_when_no_open_trades(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.trade_db = AsyncMock()
        bot.trade_db.get_open_trades.return_value = []
        bot._check_position = AsyncMock()

        await bot.monitor_positions()

        bot._check_position.assert_not_awaited()

    async def test_checks_each_open_position(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        trade1 = _make_mock_trade(trade_id=1)
        trade2 = _make_mock_trade(trade_id=2, symbol="ETHUSDT")

        bot.trade_db = AsyncMock()
        bot.trade_db.get_open_trades.return_value = [trade1, trade2]
        bot.funding_tracker = MagicMock()
        bot.funding_tracker.is_funding_time.return_value = False
        bot._check_position = AsyncMock()

        await bot.monitor_positions()

        assert bot._check_position.await_count == 2

    async def test_records_funding_at_funding_time(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        trade1 = _make_mock_trade()

        bot.trade_db = AsyncMock()
        bot.trade_db.get_open_trades.return_value = [trade1]
        bot.funding_tracker = MagicMock()
        bot.funding_tracker.is_funding_time.return_value = True
        bot._record_funding_payments = AsyncMock()
        bot._check_position = AsyncMock()

        await bot.monitor_positions()

        bot._record_funding_payments.assert_awaited_once_with([trade1])

    async def test_handles_exception_gracefully(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.trade_db = AsyncMock()
        bot.trade_db.get_open_trades.side_effect = RuntimeError("DB error")

        # Should not raise
        await bot.monitor_positions()


# ---------------------------------------------------------------------------
# _record_funding_payments() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRecordFundingPayments:
    """Tests for _record_funding_payments()."""

    async def test_records_funding_for_each_trade(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade1 = _make_mock_trade(trade_id=1, symbol="BTCUSDT")
        trade2 = _make_mock_trade(trade_id=2, symbol="ETHUSDT")

        bot.data_fetcher = AsyncMock()
        bot.data_fetcher.get_funding_rate.return_value = 0.0005
        bot.data_fetcher.get_ticker.return_value = {"last": 96000.0}
        bot.funding_tracker = AsyncMock()

        await bot._record_funding_payments([trade1, trade2])

        assert bot.funding_tracker.record_funding_payment.await_count == 2
        assert bot.funding_tracker.record_funding_rate.await_count == 2

    async def test_skips_when_funding_rate_is_none(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade()
        bot.data_fetcher = AsyncMock()
        bot.data_fetcher.get_funding_rate.return_value = None
        bot.funding_tracker = AsyncMock()

        await bot._record_funding_payments([trade])

        bot.funding_tracker.record_funding_payment.assert_not_awaited()

    async def test_uses_entry_price_when_ticker_unavailable(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade(entry_price=95000.0, size=0.01)
        bot.data_fetcher = AsyncMock()
        bot.data_fetcher.get_funding_rate.return_value = 0.0003
        bot.data_fetcher.get_ticker.return_value = None
        bot.funding_tracker = AsyncMock()

        await bot._record_funding_payments([trade])

        call_kwargs = bot.funding_tracker.record_funding_payment.call_args.kwargs
        assert call_kwargs["position_value"] == 0.01 * 95000.0

    async def test_handles_exception_per_trade(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade1 = _make_mock_trade(trade_id=1)
        trade2 = _make_mock_trade(trade_id=2)

        bot.data_fetcher = AsyncMock()
        bot.data_fetcher.get_funding_rate.side_effect = [
            RuntimeError("fail"),
            0.0005,
        ]
        bot.data_fetcher.get_ticker.return_value = {"last": 96000.0}
        bot.funding_tracker = AsyncMock()

        # Should not raise, and should process second trade
        await bot._record_funding_payments([trade1, trade2])

        # Only the second trade should have recorded funding
        assert bot.funding_tracker.record_funding_payment.await_count == 1


# ---------------------------------------------------------------------------
# _check_position() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCheckPosition:
    """Tests for _check_position()."""

    async def test_calls_handle_closed_when_no_positions(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_position.return_value = None
        bot._handle_closed_position = AsyncMock()

        trade = _make_mock_trade()
        await bot._check_position(trade)

        bot._handle_closed_position.assert_awaited_once_with(trade)

    async def test_calls_handle_closed_when_position_not_found(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_position.return_value = [
            {"holdSide": "short", "unrealizedPL": "10.0"}
        ]
        bot._handle_closed_position = AsyncMock()

        trade = _make_mock_trade(side="long")
        await bot._check_position(trade)

        bot._handle_closed_position.assert_awaited_once_with(trade)

    async def test_does_not_close_when_position_still_open(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_position.return_value = [
            {"holdSide": "long", "unrealizedPL": "50.0"}
        ]
        bot._handle_closed_position = AsyncMock()

        trade = _make_mock_trade(side="long")
        await bot._check_position(trade)

        bot._handle_closed_position.assert_not_awaited()

    async def test_handles_single_position_dict(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.bitget_client = AsyncMock()
        # Return a single dict instead of a list
        bot.bitget_client.get_position.return_value = {
            "holdSide": "long", "unrealizedPL": "25.0"
        }
        bot._handle_closed_position = AsyncMock()

        trade = _make_mock_trade(side="long")
        await bot._check_position(trade)

        bot._handle_closed_position.assert_not_awaited()

    async def test_handles_exception_gracefully(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_position.side_effect = RuntimeError("API error")

        trade = _make_mock_trade()
        # Should not raise
        await bot._check_position(trade)


# ---------------------------------------------------------------------------
# _handle_closed_position() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHandleClosedPosition:
    """Tests for _handle_closed_position()."""

    async def test_handles_take_profit_exit(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade(
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            side="long",
            size=0.01,
        )

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = [
            {
                "tradeSide": "close",
                "priceAvg": "97000.0",
                "fee": "1.5",
            }
        ]

        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.5

        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        bot.trade_db.close_trade.assert_awaited_once()
        close_kwargs = bot.trade_db.close_trade.call_args.kwargs
        assert close_kwargs["exit_reason"] == "TAKE_PROFIT"
        assert close_kwargs["exit_price"] == 97000.0

        bot.risk_manager.record_trade_exit.assert_called_once()
        bot.discord.send_trade_exit.assert_awaited_once()

    async def test_handles_stop_loss_exit(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade(
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            side="long",
            size=0.01,
        )

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = [
            {
                "tradeSide": "close",
                "priceAvg": "94000.0",
                "fee": "1.0",
            }
        ]

        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.0

        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        close_kwargs = bot.trade_db.close_trade.call_args.kwargs
        assert close_kwargs["exit_reason"] == "STOP_LOSS"

    async def test_handles_manual_close(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade(
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            side="long",
            size=0.01,
        )

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = [
            {
                "tradeSide": "close",
                "priceAvg": "95500.0",
                "fee": "0.5",
            }
        ]

        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.0

        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        close_kwargs = bot.trade_db.close_trade.call_args.kwargs
        assert close_kwargs["exit_reason"] == "MANUAL_CLOSE"

    async def test_calculates_long_pnl_correctly(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade(
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            side="long",
            size=0.01,
        )

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = [
            {"tradeSide": "close", "priceAvg": "96000.0", "fee": "1.0"}
        ]
        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.0
        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        close_kwargs = bot.trade_db.close_trade.call_args.kwargs
        expected_pnl = (96000.0 - 95000.0) * 0.01  # 10.0
        assert abs(close_kwargs["pnl"] - expected_pnl) < 0.001

    async def test_calculates_short_pnl_correctly(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade(
            entry_price=95000.0,
            take_profit=93000.0,
            stop_loss=96000.0,
            side="short",
            size=0.01,
        )

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = [
            {"tradeSide": "close", "priceAvg": "93000.0", "fee": "1.0"}
        ]
        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.0
        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        close_kwargs = bot.trade_db.close_trade.call_args.kwargs
        expected_pnl = (95000.0 - 93000.0) * 0.01  # 20.0
        assert abs(close_kwargs["pnl"] - expected_pnl) < 0.001

    async def test_handles_no_order_history(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade()
        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = None
        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.0
        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        close_kwargs = bot.trade_db.close_trade.call_args.kwargs
        assert close_kwargs["exit_reason"] == "UNKNOWN"

    async def test_calculates_duration(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        entry_time = datetime.now() - timedelta(hours=3)
        trade = _make_mock_trade(entry_time=entry_time)

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = []
        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.0
        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        discord_kwargs = bot.discord.send_trade_exit.call_args.kwargs
        assert discord_kwargs["duration_minutes"] is not None
        # Should be approximately 180 minutes (3 hours)
        assert 170 <= discord_kwargs["duration_minutes"] <= 190

    async def test_handles_no_entry_time(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade()
        trade.entry_time = None

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = []
        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.0
        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        discord_kwargs = bot.discord.send_trade_exit.call_args.kwargs
        assert discord_kwargs["duration_minutes"] is None

    async def test_handles_exception_gracefully(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade()
        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.side_effect = RuntimeError("API error")

        # Should not raise
        await bot._handle_closed_position(trade)


# ---------------------------------------------------------------------------
# send_daily_summary() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendDailySummary:
    """Tests for send_daily_summary()."""

    async def test_sends_summary_when_stats_available(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        mock_stats = MagicMock()
        mock_stats.date = "2025-01-15"
        mock_stats.starting_balance = 10000.0
        mock_stats.current_balance = 10200.0
        mock_stats.trades_executed = 3
        mock_stats.winning_trades = 2
        mock_stats.losing_trades = 1
        mock_stats.total_pnl = 200.0
        mock_stats.total_fees = 5.0
        mock_stats.total_funding = 1.0
        mock_stats.max_drawdown = 50.0

        bot.risk_manager = MagicMock()
        bot.risk_manager.get_daily_stats.return_value = mock_stats
        bot.discord = AsyncMock()

        await bot.send_daily_summary()

        bot.discord.send_daily_summary.assert_awaited_once()

    async def test_skips_summary_when_no_stats(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.risk_manager = MagicMock()
        bot.risk_manager.get_daily_stats.return_value = None
        bot.discord = AsyncMock()

        await bot.send_daily_summary()

        bot.discord.send_daily_summary.assert_not_awaited()

    async def test_handles_exception_gracefully(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.risk_manager = MagicMock()
        bot.risk_manager.get_daily_stats.side_effect = RuntimeError("stats error")

        # Should not raise
        await bot.send_daily_summary()


# ---------------------------------------------------------------------------
# close_all_positions() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCloseAllPositions:
    """Tests for close_all_positions() emergency close."""

    async def test_closes_all_open_positions(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_all_positions.return_value = [
            {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.01"},
            {"symbol": "ETHUSDT", "holdSide": "short", "total": "0.1"},
        ]
        bot.discord = AsyncMock()

        await bot.close_all_positions()

        assert bot.bitget_client.close_position.await_count == 2
        bot.discord.send_bot_status.assert_awaited_once()

    async def test_skips_zero_size_positions(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_all_positions.return_value = [
            {"symbol": "BTCUSDT", "holdSide": "long", "total": "0"},
            {"symbol": "ETHUSDT", "holdSide": "short", "total": "0.1"},
        ]
        bot.discord = AsyncMock()

        await bot.close_all_positions()

        assert bot.bitget_client.close_position.await_count == 1

    async def test_handles_no_positions(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_all_positions.return_value = None
        bot.discord = AsyncMock()

        await bot.close_all_positions()

        bot.bitget_client.close_position.assert_not_awaited()
        bot.discord.send_bot_status.assert_awaited_once()

    async def test_handles_exception_and_sends_error(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_all_positions.side_effect = RuntimeError("exchange down")
        bot.discord = AsyncMock()

        await bot.close_all_positions()

        bot.discord.send_error.assert_awaited_once()


# ---------------------------------------------------------------------------
# run_once() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRunOnce:
    """Tests for run_once() single analysis cycle."""

    async def test_initializes_if_not_initialized(self, mock_settings):
        mock_settings.trading.trading_pairs = ["BTCUSDT"]

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialized = False
            bot.initialize = AsyncMock(return_value=True)

            signal = _make_trade_signal()
            bot.strategy = AsyncMock()
            bot.strategy.generate_signal.return_value = signal

            # Set initialized after mock call
            async def set_init():
                bot._initialized = True
                return True

            bot.initialize = AsyncMock(side_effect=set_init)

            signals = await bot.run_once()

            bot.initialize.assert_awaited_once()
            assert len(signals) == 1

    async def test_returns_signals_for_all_pairs(self, mock_settings):
        mock_settings.trading.trading_pairs = ["BTCUSDT", "ETHUSDT"]

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialized = True

            signal1 = _make_trade_signal(symbol="BTCUSDT")
            signal2 = _make_trade_signal(symbol="ETHUSDT")

            bot.strategy = AsyncMock()
            bot.strategy.generate_signal.side_effect = [signal1, signal2]

            signals = await bot.run_once()

            assert len(signals) == 2
            assert signals[0].symbol == "BTCUSDT"
            assert signals[1].symbol == "ETHUSDT"

    async def test_skips_init_when_already_initialized(self, mock_settings):
        mock_settings.trading.trading_pairs = ["BTCUSDT"]

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot._initialized = True
            bot.initialize = AsyncMock()

            signal = _make_trade_signal()
            bot.strategy = AsyncMock()
            bot.strategy.generate_signal.return_value = signal

            signals = await bot.run_once()

            bot.initialize.assert_not_awaited()
            assert len(signals) == 1


# ---------------------------------------------------------------------------
# Edge cases and integration scenarios
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEdgeCases:
    """Edge cases and integration-like scenarios."""

    async def test_execute_trade_records_metrics_snapshot_as_json(self, mock_settings):
        mock_settings.is_demo_mode = True

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (500.0, 0.005)
            bot.bitget_client = AsyncMock()
            bot.trade_db = AsyncMock()
            bot.trade_db.create_trade.return_value = 1
            bot.discord = AsyncMock()

            metrics = {"fear_greed": 85, "funding_rate": 0.001}
            signal = _make_trade_signal(metrics_snapshot=metrics)
            await bot._execute_trade(signal)

            create_kwargs = bot.trade_db.create_trade.call_args.kwargs
            assert create_kwargs["metrics_snapshot"] == json.dumps(metrics)

    async def test_live_mode_slippage_logging_with_fill_price(self, mock_settings):
        mock_settings.is_demo_mode = False

        with patch("src.bot.trading_bot.settings", mock_settings), \
             patch("src.bot.trading_bot.setup_logging"):
            from src.bot.trading_bot import TradingBot
            bot = TradingBot()
            bot.risk_manager = MagicMock()
            bot.risk_manager.calculate_position_size.return_value = (1000.0, 0.01)
            bot.bitget_client = AsyncMock()
            bot.bitget_client.get_account_balance.return_value = {"available": "10000"}
            bot.bitget_client.place_market_order.return_value = {"orderId": "slip_001"}
            # Fill price differs from signal price
            bot.bitget_client.get_fill_price.return_value = 95200.0
            bot.trade_db = AsyncMock()
            bot.trade_db.create_trade.return_value = 1
            bot.discord = AsyncMock()

            signal = _make_trade_signal(entry_price=95000.0)
            await bot._execute_trade(signal)

            # Entry price should be the fill price, not the signal price
            create_kwargs = bot.trade_db.create_trade.call_args.kwargs
            assert create_kwargs["entry_price"] == 95200.0

    async def test_position_check_handles_empty_positions_list(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()
        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_position.return_value = []
        bot._handle_closed_position = AsyncMock()

        trade = _make_mock_trade()
        await bot._check_position(trade)

        # Empty list is falsy, so it should call handle_closed_position
        bot._handle_closed_position.assert_awaited_once()

    async def test_handle_closed_position_includes_funding_paid(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade(side="long", entry_price=95000.0, size=0.01)

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = [
            {"tradeSide": "close", "priceAvg": "96000.0", "fee": "1.0"}
        ]
        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 2.5
        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        close_kwargs = bot.trade_db.close_trade.call_args.kwargs
        assert close_kwargs["funding_paid"] == 2.5

        risk_kwargs = bot.risk_manager.record_trade_exit.call_args.kwargs
        assert risk_kwargs["funding_paid"] == 2.5

    async def test_handle_closed_position_passes_strategy_reason(self, bot_patches):
        from src.bot.trading_bot import TradingBot
        bot = TradingBot()

        trade = _make_mock_trade()
        trade.reason = "Crowded longs detected"

        bot.bitget_client = AsyncMock()
        bot.bitget_client.get_order_history.return_value = []
        bot.funding_tracker = AsyncMock()
        bot.funding_tracker.get_total_funding_for_trade.return_value = 0.0
        bot.trade_db = AsyncMock()
        bot.risk_manager = MagicMock()
        bot.discord = AsyncMock()

        await bot._handle_closed_position(trade)

        discord_kwargs = bot.discord.send_trade_exit.call_args.kwargs
        assert discord_kwargs["strategy_reason"] == "Crowded longs detected"
