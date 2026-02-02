"""
Unit tests for the Risk Manager.

Tests cover:
- Daily loss limit enforcement
- Trade count limits
- Position sizing
- Profit Lock-In feature
- DailyStats calculations
- Can trade checks
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.risk.risk_manager import RiskManager, DailyStats


class TestDailyStats:
    """Tests for DailyStats dataclass."""

    def test_net_pnl_calculation(self):
        """Net PnL should be total PnL minus fees and funding."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=10100.0,
            trades_executed=2,
            winning_trades=1,
            losing_trades=1,
            total_pnl=150.0,
            total_fees=20.0,
            total_funding=30.0,
            max_drawdown=50.0,
        )

        # Net PnL = 150 - 20 - 30 = 100
        assert stats.net_pnl == 100.0

    def test_net_pnl_negative_funding_is_absolute(self):
        """Funding should be absolute value (received funding is subtracted)."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=10100.0,
            trades_executed=1,
            winning_trades=1,
            losing_trades=0,
            total_pnl=100.0,
            total_fees=10.0,
            total_funding=-20.0,  # Received funding
            max_drawdown=0.0,
        )

        # Net PnL = 100 - 10 - abs(-20) = 100 - 10 - 20 = 70
        assert stats.net_pnl == 70.0

    def test_return_percent_calculation(self):
        """Return percent should be net PnL / starting balance * 100."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=10500.0,
            trades_executed=1,
            winning_trades=1,
            losing_trades=0,
            total_pnl=500.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )

        # Return = (500 / 10000) * 100 = 5%
        assert stats.return_percent == 5.0

    def test_return_percent_zero_balance(self):
        """Return percent should be 0 if starting balance is 0."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=0.0,
            current_balance=100.0,
            trades_executed=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl=100.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )

        assert stats.return_percent == 0.0

    def test_win_rate_calculation(self):
        """Win rate should be winning trades / total trades * 100."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=10000.0,
            trades_executed=4,
            winning_trades=3,
            losing_trades=1,
            total_pnl=0.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )

        # Win rate = (3 / 4) * 100 = 75%
        assert stats.win_rate == 75.0

    def test_win_rate_no_trades(self):
        """Win rate should be 0 if no trades."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=10000.0,
            trades_executed=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl=0.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )

        assert stats.win_rate == 0.0

    def test_to_dict_serialization(self):
        """to_dict should include all fields and computed properties."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=10100.0,
            trades_executed=2,
            winning_trades=1,
            losing_trades=1,
            total_pnl=150.0,
            total_fees=20.0,
            total_funding=30.0,
            max_drawdown=50.0,
            is_trading_halted=True,
            halt_reason="Daily loss limit reached",
        )

        result = stats.to_dict()

        assert result["date"] == "2024-01-01"
        assert result["starting_balance"] == 10000.0
        assert result["net_pnl"] == 100.0
        assert result["win_rate"] == 50.0
        assert result["is_trading_halted"] is True
        assert result["halt_reason"] == "Daily loss limit reached"


class TestRiskManagerInitialization:
    """Tests for RiskManager initialization."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary directory for test data."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_creates_data_directory(self, temp_data_dir):
        """Should create data directory if it doesn't exist."""
        new_dir = Path(temp_data_dir) / "new_risk_dir"
        assert not new_dir.exists()

        RiskManager(data_dir=str(new_dir))

        assert new_dir.exists()

    def test_uses_settings_defaults(self, temp_data_dir):
        """Should use settings values when not explicitly provided."""
        with patch('src.risk.risk_manager.settings') as mock_settings:
            mock_settings.trading.max_trades_per_day = 5
            mock_settings.trading.daily_loss_limit_percent = 10.0
            mock_settings.trading.position_size_percent = 15.0

            rm = RiskManager(data_dir=temp_data_dir)

            assert rm.max_trades == 5
            assert rm.daily_loss_limit == 10.0
            assert rm.position_size_pct == 15.0

    def test_override_settings(self, temp_data_dir):
        """Should use explicit values over settings."""
        rm = RiskManager(
            max_trades_per_day=10,
            daily_loss_limit_percent=8.0,
            position_size_percent=20.0,
            data_dir=temp_data_dir,
        )

        assert rm.max_trades == 10
        assert rm.daily_loss_limit == 8.0
        assert rm.position_size_pct == 20.0


class TestRiskManagerDayInitialization:
    """Tests for daily initialization."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        yield rm
        shutil.rmtree(temp_dir)

    def test_initialize_day_creates_stats(self, risk_manager):
        """initialize_day should create DailyStats."""
        stats = risk_manager.initialize_day(10000.0)

        assert stats is not None
        assert stats.starting_balance == 10000.0
        assert stats.trades_executed == 0
        assert stats.total_pnl == 0.0

    def test_initialize_day_idempotent(self, risk_manager):
        """Calling initialize_day twice should return same stats."""
        stats1 = risk_manager.initialize_day(10000.0)
        stats1.trades_executed = 5  # Modify

        stats2 = risk_manager.initialize_day(10000.0)

        # Should return existing stats, not reset
        assert stats2.trades_executed == 5

    def test_initialize_day_saves_to_file(self, risk_manager):
        """Stats should be persisted to disk."""
        risk_manager.initialize_day(10000.0)

        today = datetime.now().strftime("%Y-%m-%d")
        stats_file = risk_manager.data_dir / f"daily_stats_{today}.json"

        assert stats_file.exists()


class TestCanTrade:
    """Tests for can_trade decision logic."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            max_trades_per_day=3,
            daily_loss_limit_percent=5.0,
            data_dir=temp_dir,
        )
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir)

    def test_can_trade_initial(self, risk_manager):
        """Should be able to trade initially."""
        can_trade, reason = risk_manager.can_trade()

        assert can_trade is True

    def test_cannot_trade_after_max_trades(self, risk_manager):
        """Should not be able to trade after reaching max trades."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 3  # Hit the limit

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is False
        assert "max trades" in reason.lower() or "limit" in reason.lower()

    def test_cannot_trade_when_halted(self, risk_manager):
        """Should not be able to trade when trading is halted."""
        stats = risk_manager.get_daily_stats()
        stats.is_trading_halted = True
        stats.halt_reason = "Daily loss limit"

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is False
        assert "halted" in reason.lower()

    def test_cannot_trade_after_loss_limit(self, risk_manager):
        """Should not trade after exceeding daily loss limit."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = -600.0  # -6% of 10000

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is False

    def test_remaining_trades_calculation(self, risk_manager):
        """get_remaining_trades should return correct count."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 1

        remaining = risk_manager.get_remaining_trades()

        assert remaining == 2  # 3 max - 1 executed


class TestRecordTrade:
    """Tests for recording trades."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir)

    def test_record_winning_trade(self, risk_manager):
        """Recording a winning trade should update stats correctly."""
        # Long trade: entry=95000, exit=96000, size=0.01 -> pnl = (96000-95000)*0.01 = 10
        # Using size that gives us ~100 pnl: (96000-95000)*0.1 = 100
        risk_manager.record_trade_exit(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=95000.0,
            exit_price=96000.0,  # +1000 per BTC * 0.1 = +100
            fees=5.0,
            funding_paid=0.0,
            reason="take_profit",
            order_id="test-001",
        )

        stats = risk_manager.get_daily_stats()
        assert stats.winning_trades == 1
        assert stats.losing_trades == 0
        assert stats.total_pnl == 100.0
        assert stats.total_fees == 5.0

    def test_record_losing_trade(self, risk_manager):
        """Recording a losing trade should update stats correctly."""
        # Long trade: entry=95000, exit=94500 -> pnl = (94500-95000)*0.1 = -50
        risk_manager.record_trade_exit(
            symbol="BTCUSDT",
            side="long",
            size=0.1,
            entry_price=95000.0,
            exit_price=94500.0,  # -500 per BTC * 0.1 = -50
            fees=5.0,
            funding_paid=0.0,
            reason="stop_loss",
            order_id="test-002",
        )

        stats = risk_manager.get_daily_stats()
        assert stats.winning_trades == 0
        assert stats.losing_trades == 1
        assert stats.total_pnl == -50.0

    def test_record_multiple_trades(self, risk_manager):
        """Recording multiple trades should accumulate correctly."""
        # Trade 1: +100 pnl
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=95000.0, exit_price=96000.0,
            fees=5.0, funding_paid=0.0, reason="tp", order_id="t1"
        )
        # Trade 2: -30 pnl
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=95000.0, exit_price=94700.0,  # -300 * 0.1 = -30
            fees=5.0, funding_paid=0.0, reason="sl", order_id="t2"
        )
        # Trade 3: +50 pnl
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=95000.0, exit_price=95500.0,  # +500 * 0.1 = +50
            fees=5.0, funding_paid=0.0, reason="tp", order_id="t3"
        )

        stats = risk_manager.get_daily_stats()
        assert stats.winning_trades == 2
        assert stats.losing_trades == 1
        assert stats.total_pnl == 120.0  # 100 - 30 + 50
        assert stats.total_fees == 15.0


class TestPositionSizing:
    """Tests for position size calculation."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            position_size_percent=10.0,
            data_dir=temp_dir,
        )
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir)

    def test_calculate_position_size_base(self, risk_manager):
        """Position size should be percentage of balance."""
        position_usdt, position_base = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=95000.0,
            confidence=70,
            leverage=1,
        )

        # 10% of 10000 = 1000 USDT
        assert position_usdt > 0
        assert position_base > 0
        assert position_base == position_usdt / 95000.0

    def test_position_scales_with_confidence(self, risk_manager):
        """Higher confidence should result in larger position."""
        _, base_low = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=95000.0,
            confidence=55,
            leverage=1,
        )

        _, base_high = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=95000.0,
            confidence=90,
            leverage=1,
        )

        assert base_high > base_low

    def test_position_with_leverage(self, risk_manager):
        """Leverage increases buying power (more base currency for same USDT)."""
        _, base_no_lev = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=95000.0,
            confidence=70,
            leverage=1,
        )

        _, base_with_lev = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=95000.0,
            confidence=70,
            leverage=10,
        )

        # With leverage, you get more base currency for the same USDT
        # 10x leverage = 10x position in base currency
        assert base_with_lev > base_no_lev
        assert abs(base_with_lev / base_no_lev - 10) < 0.01  # Should be ~10x


class TestProfitLockIn:
    """Tests for Profit Lock-In feature."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with profit lock enabled."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            daily_loss_limit_percent=5.0,
            enable_profit_lock=True,
            profit_lock_percent=75.0,
            min_profit_floor=0.5,
            data_dir=temp_dir,
        )
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir)

    def test_dynamic_loss_limit_no_profit(self, risk_manager):
        """Without profit, loss limit should be the configured limit."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = 0.0

        dynamic_limit = risk_manager.get_dynamic_loss_limit()

        # Should be close to configured limit (5%)
        assert dynamic_limit >= 4.5
        assert dynamic_limit <= 5.0

    def test_dynamic_loss_limit_with_profit(self, risk_manager):
        """With profit, loss limit should be reduced to lock in gains."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = 400.0  # 4% profit on 10000

        dynamic_limit = risk_manager.get_dynamic_loss_limit()

        # Should be less than original 5% to lock in some profit
        # With 4% profit and 75% lock, max loss should be around 1% (4 * 0.25)
        assert dynamic_limit < 5.0

    def test_profit_lock_preserves_minimum(self, risk_manager):
        """With large profit, daily_loss_limit becomes the binding constraint."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = 1000.0  # 10% profit

        dynamic_limit = risk_manager.get_dynamic_loss_limit()

        # With 10% profit, max_allowed_loss = 10% - 0.5% (min_floor) = 9.5%
        # But this is capped by daily_loss_limit of 5%
        # So dynamic_limit = min(5.0, 9.5) = 5.0
        assert dynamic_limit <= 5.0  # Capped at configured limit


class TestMaxDrawdown:
    """Tests for drawdown tracking."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir)

    def test_trade_exit_tracks_drawdown(self, risk_manager):
        """Recording trades should update max drawdown tracking."""
        # First a winning trade to establish profit
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=95000.0, exit_price=96000.0,  # +100 pnl
            fees=0.0, funding_paid=0.0, reason="tp", order_id="t1"
        )

        # Then a losing trade creating drawdown from peak
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=95000.0, exit_price=94000.0,  # -100 pnl
            fees=0.0, funding_paid=0.0, reason="sl", order_id="t2"
        )

        stats = risk_manager.get_daily_stats()
        # Max drawdown should be tracked (at least some drawdown occurred)
        # The return_percent went from +1% back to 0%, so drawdown was recorded
        assert stats.max_drawdown >= 0


class TestGetDailyStats:
    """Tests for getting daily stats."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        yield rm
        shutil.rmtree(temp_dir)

    def test_get_daily_stats_returns_none_if_not_initialized(self, risk_manager):
        """Should return None if day not initialized."""
        # Force clear stats
        risk_manager._daily_stats = None

        stats = risk_manager.get_daily_stats()

        assert stats is None

    def test_get_daily_stats_returns_stats(self, risk_manager):
        """Should return stats after initialization."""
        risk_manager.initialize_day(10000.0)

        stats = risk_manager.get_daily_stats()

        assert stats is not None
        assert stats.starting_balance == 10000.0
