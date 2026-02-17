"""
Unit tests for the Risk Manager.

Tests cover:
- Daily loss limit enforcement
- Trade count limits (global and per-symbol)
- Position sizing with confidence scaling
- Profit Lock-In feature (dynamic loss limits)
- DailyStats calculations and serialization
- Can trade checks (global and per-symbol)
- Trade entry and exit recording
- Remaining trades and risk budget
- Historical stats and performance summaries
- Error paths and edge cases
"""

import json
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.risk.risk_manager import RiskManager, DailyStats


# ---------------------------------------------------------------------------
# DailyStats dataclass tests
# ---------------------------------------------------------------------------


class TestDailyStats:
    """Tests for DailyStats dataclass."""

    def test_net_pnl_calculation(self):
        """Net PnL should be total PnL minus fees and absolute funding."""
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

        # Net PnL = 150 - 20 - abs(30) = 100
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

    def test_net_pnl_zero_values(self):
        """Net PnL with all zeros should be zero."""
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

        assert stats.net_pnl == 0.0

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

    def test_return_percent_negative(self):
        """Return percent should be negative for losses."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=9700.0,
            trades_executed=1,
            winning_trades=0,
            losing_trades=1,
            total_pnl=-300.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=3.0,
        )

        # Return = (-300 / 10000) * 100 = -3%
        assert stats.return_percent == -3.0

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

    def test_win_rate_all_winners(self):
        """Win rate should be 100 if all trades are winners."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=10500.0,
            trades_executed=5,
            winning_trades=5,
            losing_trades=0,
            total_pnl=500.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
        )

        assert stats.win_rate == 100.0

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
        assert result["current_balance"] == 10100.0
        assert result["trades_executed"] == 2
        assert result["winning_trades"] == 1
        assert result["losing_trades"] == 1
        assert result["total_pnl"] == 150.0
        assert result["total_fees"] == 20.0
        assert result["total_funding"] == 30.0
        assert result["net_pnl"] == 100.0
        assert result["return_percent"] == 1.0
        assert result["win_rate"] == 50.0
        assert result["max_drawdown"] == 50.0
        assert result["is_trading_halted"] is True
        assert result["halt_reason"] == "Daily loss limit reached"

    def test_to_dict_includes_symbol_tracking(self):
        """to_dict should include per-symbol tracking dictionaries."""
        stats = DailyStats(
            date="2024-01-01",
            starting_balance=10000.0,
            current_balance=10000.0,
            trades_executed=2,
            winning_trades=1,
            losing_trades=1,
            total_pnl=0.0,
            total_fees=0.0,
            total_funding=0.0,
            max_drawdown=0.0,
            symbol_trades={"BTCUSDT": 1, "ETHUSDT": 1},
            symbol_pnl={"BTCUSDT": 50.0, "ETHUSDT": -50.0},
            halted_symbols={"ETHUSDT": "Loss limit exceeded"},
        )

        result = stats.to_dict()

        assert result["symbol_trades"] == {"BTCUSDT": 1, "ETHUSDT": 1}
        assert result["symbol_pnl"] == {"BTCUSDT": 50.0, "ETHUSDT": -50.0}
        assert result["halted_symbols"] == {"ETHUSDT": "Loss limit exceeded"}

    def test_default_field_values(self):
        """Default fields should be empty dicts and False/empty string."""
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

        assert stats.is_trading_halted is False
        assert stats.halt_reason == ""
        assert stats.symbol_trades == {}
        assert stats.symbol_pnl == {}
        assert stats.halted_symbols == {}


# ---------------------------------------------------------------------------
# RiskManager initialization tests
# ---------------------------------------------------------------------------


class TestRiskManagerInitialization:
    """Tests for RiskManager initialization."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create a temporary directory for test data."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

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

    def test_per_symbol_limits_defaults_to_empty(self, temp_data_dir):
        """Per-symbol limits should default to empty dict."""
        rm = RiskManager(data_dir=temp_data_dir)

        assert rm.per_symbol_limits == {}

    def test_per_symbol_limits_stored(self, temp_data_dir):
        """Per-symbol limits should be stored when provided."""
        limits = {"BTCUSDT": {"max_trades": 5, "loss_limit": 3.0}}
        rm = RiskManager(data_dir=temp_data_dir, per_symbol_limits=limits)

        assert rm.per_symbol_limits == limits

    def test_profit_lock_settings(self, temp_data_dir):
        """Profit lock-in settings should be stored."""
        rm = RiskManager(
            data_dir=temp_data_dir,
            enable_profit_lock=False,
            profit_lock_percent=50.0,
            min_profit_floor=1.0,
        )

        assert rm.enable_profit_lock is False
        assert rm.profit_lock_percent == 50.0
        assert rm.min_profit_floor == 1.0


# ---------------------------------------------------------------------------
# Day initialization tests
# ---------------------------------------------------------------------------


class TestRiskManagerDayInitialization:
    """Tests for daily initialization."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_initialize_day_creates_stats(self, risk_manager):
        """initialize_day should create DailyStats."""
        stats = risk_manager.initialize_day(10000.0)

        assert stats is not None
        assert stats.starting_balance == 10000.0
        assert stats.current_balance == 10000.0
        assert stats.trades_executed == 0
        assert stats.total_pnl == 0.0
        assert stats.winning_trades == 0
        assert stats.losing_trades == 0

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

    def test_initialize_day_file_content(self, risk_manager):
        """Saved file should contain valid JSON with correct values."""
        risk_manager.initialize_day(10000.0)

        today = datetime.now().strftime("%Y-%m-%d")
        stats_file = risk_manager.data_dir / f"daily_stats_{today}.json"

        with open(stats_file, "r") as f:
            data = json.load(f)

        assert data["starting_balance"] == 10000.0
        assert data["trades_executed"] == 0
        assert data["date"] == today


# ---------------------------------------------------------------------------
# can_trade tests (global)
# ---------------------------------------------------------------------------


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
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_can_trade_initial(self, risk_manager):
        """Should be able to trade initially."""
        can_trade, reason = risk_manager.can_trade()

        assert can_trade is True
        assert reason == "Trading allowed"

    def test_cannot_trade_without_initialization(self):
        """Should not trade if daily stats are not initialized."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(data_dir=temp_dir)
            rm._daily_stats = None

            can_trade, reason = rm.can_trade()

            assert can_trade is False
            assert "initialize_day" in reason.lower() or "not initialized" in reason.lower()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cannot_trade_after_max_trades(self, risk_manager):
        """Should not be able to trade after reaching max trades."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 3  # Hit the limit

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is False
        assert "limit" in reason.lower()

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
        stats.total_pnl = -600.0  # -6% of 10000, exceeds 5% limit

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is False
        assert "loss limit" in reason.lower()

    def test_can_trade_at_loss_limit_boundary(self, risk_manager):
        """Should not trade when exactly at the loss limit."""
        stats = risk_manager.get_daily_stats()
        # Exactly 5% loss = 500 on 10000 balance
        stats.total_pnl = -500.0

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is False

    def test_can_trade_just_under_loss_limit(self, risk_manager):
        """Should allow trading just under the loss limit."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = -490.0  # 4.9% loss, under 5%

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is True

    def test_can_trade_with_no_max_trades_limit(self):
        """Should allow trading when max_trades is None."""
        temp_dir = tempfile.mkdtemp()
        try:
            with patch('src.risk.risk_manager.settings') as mock_settings:
                mock_settings.trading.max_trades_per_day = None
                mock_settings.trading.daily_loss_limit_percent = None
                mock_settings.trading.position_size_percent = 10.0

                rm = RiskManager(data_dir=temp_dir)
                rm.initialize_day(10000.0)
                rm.get_daily_stats().trades_executed = 100

                can_trade, reason = rm.can_trade()

                assert can_trade is True
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_can_trade_with_no_loss_limit(self):
        """Should allow trading when daily_loss_limit is None."""
        temp_dir = tempfile.mkdtemp()
        try:
            with patch('src.risk.risk_manager.settings') as mock_settings:
                mock_settings.trading.max_trades_per_day = None
                mock_settings.trading.daily_loss_limit_percent = None
                mock_settings.trading.position_size_percent = 10.0

                rm = RiskManager(data_dir=temp_dir)
                rm.initialize_day(10000.0)
                rm.get_daily_stats().total_pnl = -5000.0  # 50% loss

                can_trade, reason = rm.can_trade()

                assert can_trade is True
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_can_trade_at_max_trades_boundary(self, risk_manager):
        """Should not trade when trades_executed equals max_trades."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 3  # max_trades is 3

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is False

    def test_can_trade_one_below_max(self, risk_manager):
        """Should allow trading when one below max trades."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 2

        can_trade, reason = risk_manager.can_trade()

        assert can_trade is True


# ---------------------------------------------------------------------------
# can_trade tests (per-symbol)
# ---------------------------------------------------------------------------


class TestCanTradePerSymbol:
    """Tests for can_trade with per-symbol limits."""

    @pytest.fixture
    def risk_manager_per_symbol(self):
        """Create a risk manager with per-symbol limits."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            max_trades_per_day=10,
            daily_loss_limit_percent=5.0,
            data_dir=temp_dir,
            per_symbol_limits={
                "BTCUSDT": {"max_trades": 3, "loss_limit": 2.0},
                "ETHUSDT": {"max_trades": 2},
            },
        )
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_can_trade_symbol_initial(self, risk_manager_per_symbol):
        """Should allow trading for a symbol initially."""
        can_trade, reason = risk_manager_per_symbol.can_trade(symbol="BTCUSDT")

        assert can_trade is True

    def test_cannot_trade_symbol_after_per_symbol_max_trades(self, risk_manager_per_symbol):
        """Should block trading when per-symbol trade limit is reached."""
        stats = risk_manager_per_symbol.get_daily_stats()
        stats.symbol_trades["BTCUSDT"] = 3  # BTC limit is 3

        can_trade, reason = risk_manager_per_symbol.can_trade(symbol="BTCUSDT")

        assert can_trade is False
        assert "BTCUSDT" in reason
        assert "limit" in reason.lower()

    def test_can_trade_symbol_below_limit(self, risk_manager_per_symbol):
        """Should allow trading when under per-symbol trade limit."""
        stats = risk_manager_per_symbol.get_daily_stats()
        stats.symbol_trades["BTCUSDT"] = 2

        can_trade, reason = risk_manager_per_symbol.can_trade(symbol="BTCUSDT")

        assert can_trade is True

    def test_cannot_trade_symbol_after_per_symbol_loss_limit(self, risk_manager_per_symbol):
        """Should block symbol when per-symbol loss limit is exceeded."""
        stats = risk_manager_per_symbol.get_daily_stats()
        stats.symbol_pnl["BTCUSDT"] = -250.0  # 2.5% of 10000, exceeds 2% limit

        can_trade, reason = risk_manager_per_symbol.can_trade(symbol="BTCUSDT")

        assert can_trade is False
        assert "BTCUSDT" in reason
        assert "loss limit" in reason.lower() or "Loss limit" in reason

    def test_cannot_trade_halted_symbol(self, risk_manager_per_symbol):
        """Should block trading for a halted symbol."""
        stats = risk_manager_per_symbol.get_daily_stats()
        stats.halted_symbols["BTCUSDT"] = "Previously halted"

        can_trade, reason = risk_manager_per_symbol.can_trade(symbol="BTCUSDT")

        assert can_trade is False
        assert "halted" in reason.lower()

    def test_symbol_uses_global_fallback_when_no_per_symbol_limit(self, risk_manager_per_symbol):
        """Symbol without per-symbol config should use global fallback."""
        stats = risk_manager_per_symbol.get_daily_stats()
        # SOLUSDT has no per-symbol limits, so global max_trades=10 applies
        stats.symbol_trades["SOLUSDT"] = 10

        can_trade, reason = risk_manager_per_symbol.can_trade(symbol="SOLUSDT")

        assert can_trade is False
        assert "limit" in reason.lower()

    def test_symbol_with_partial_overrides_uses_global_loss_limit(self, risk_manager_per_symbol):
        """ETHUSDT has max_trades override but no loss_limit, so global 5% applies."""
        stats = risk_manager_per_symbol.get_daily_stats()
        stats.symbol_pnl["ETHUSDT"] = -600.0  # 6% of 10000, exceeds global 5%

        can_trade, reason = risk_manager_per_symbol.can_trade(symbol="ETHUSDT")

        assert can_trade is False

    def test_per_symbol_halt_persisted(self, risk_manager_per_symbol):
        """Halting a symbol via loss limit should be persisted in halted_symbols."""
        stats = risk_manager_per_symbol.get_daily_stats()
        stats.symbol_pnl["BTCUSDT"] = -250.0  # Exceeds 2% limit

        risk_manager_per_symbol.can_trade(symbol="BTCUSDT")

        assert "BTCUSDT" in stats.halted_symbols

    def test_globally_halted_blocks_symbol_trade(self, risk_manager_per_symbol):
        """Global halt should block symbol-specific checks."""
        stats = risk_manager_per_symbol.get_daily_stats()
        stats.is_trading_halted = True
        stats.halt_reason = "Global halt"

        can_trade, reason = risk_manager_per_symbol.can_trade(symbol="BTCUSDT")

        assert can_trade is False
        assert "halted" in reason.lower()


# ---------------------------------------------------------------------------
# _halt_trading tests
# ---------------------------------------------------------------------------


class TestHaltTrading:
    """Tests for the _halt_trading method."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_halt_trading_sets_flags(self, risk_manager):
        """Should set halt flags on daily stats."""
        risk_manager._halt_trading("Test halt reason")

        stats = risk_manager.get_daily_stats()
        assert stats.is_trading_halted is True
        assert stats.halt_reason == "Test halt reason"

    def test_halt_trading_without_stats(self):
        """Should not crash when daily stats are not initialized."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(data_dir=temp_dir)
            rm._daily_stats = None

            # Should not raise
            rm._halt_trading("Test reason")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_halt_trading_saves_to_file(self, risk_manager):
        """Halting should save stats to file."""
        risk_manager._halt_trading("Persisted halt")

        today = datetime.now().strftime("%Y-%m-%d")
        stats_file = risk_manager.data_dir / f"daily_stats_{today}.json"

        with open(stats_file, "r") as f:
            data = json.load(f)

        assert data["is_trading_halted"] is True
        assert data["halt_reason"] == "Persisted halt"


# ---------------------------------------------------------------------------
# Position sizing tests
# ---------------------------------------------------------------------------


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
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_calculate_position_size_base(self, risk_manager):
        """Position size should be percentage of balance."""
        position_usdt, position_base = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=95000.0,
            confidence=70,
            leverage=1,
        )

        # 10% base * 1.0 multiplier (65<=confidence<75) = 10%
        assert position_usdt > 0
        assert position_base > 0
        assert abs(position_base - position_usdt / 95000.0) < 1e-9

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

    def test_position_size_is_positive(self, risk_manager):
        """Position size should always be positive."""
        usdt, base = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=95000.0,
            confidence=70,
            leverage=10,
        )

        assert usdt > 0
        assert base > 0

    def test_confidence_below_55_uses_half_multiplier(self, risk_manager):
        """Confidence < 55 should use 0.5 multiplier."""
        usdt, _ = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=50000.0,
            confidence=40,
            leverage=1,
        )

        # 10% * 0.5 = 5% of 10000 = 500
        assert abs(usdt - 500.0) < 0.01

    def test_confidence_55_uses_075_multiplier(self, risk_manager):
        """Confidence 55-64 should use 0.75 multiplier."""
        usdt, _ = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=50000.0,
            confidence=60,
            leverage=1,
        )

        # 10% * 0.75 = 7.5% of 10000 = 750
        assert abs(usdt - 750.0) < 0.01

    def test_confidence_65_uses_1x_multiplier(self, risk_manager):
        """Confidence 65-74 should use 1.0 multiplier."""
        usdt, _ = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=50000.0,
            confidence=70,
            leverage=1,
        )

        # 10% * 1.0 = 10% of 10000 = 1000
        assert abs(usdt - 1000.0) < 0.01

    def test_confidence_75_uses_125_multiplier(self, risk_manager):
        """Confidence 75-84 should use 1.25 multiplier."""
        usdt, _ = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=50000.0,
            confidence=80,
            leverage=1,
        )

        # 10% * 1.25 = 12.5% of 10000 = 1250
        assert abs(usdt - 1250.0) < 0.01

    def test_confidence_85_uses_15_multiplier(self, risk_manager):
        """Confidence >= 85 should use 1.5 multiplier."""
        usdt, _ = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=50000.0,
            confidence=90,
            leverage=1,
        )

        # 10% * 1.5 = 15% of 10000 = 1500
        assert abs(usdt - 1500.0) < 0.01

    def test_position_size_capped_at_25_percent(self):
        """Position size should be capped at 25% of balance."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(
                position_size_percent=20.0,
                data_dir=temp_dir,
            )
            rm.initialize_day(10000.0)

            usdt, _ = rm.calculate_position_size(
                balance=10000.0,
                entry_price=50000.0,
                confidence=90,
                leverage=1,
            )

            # 20% * 1.5 = 30%, but capped at 25% = 2500
            assert abs(usdt - 2500.0) < 0.01
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_leverage_affects_base_amount(self, risk_manager):
        """Leverage should multiply the base amount."""
        _, base_1x = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=50000.0,
            confidence=70,
            leverage=1,
        )

        _, base_5x = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=50000.0,
            confidence=70,
            leverage=5,
        )

        assert abs(base_5x - base_1x * 5) < 1e-9


# ---------------------------------------------------------------------------
# Record trade entry tests
# ---------------------------------------------------------------------------


class TestRecordTradeEntry:
    """Tests for record_trade_entry."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            max_trades_per_day=5,
            data_dir=temp_dir,
        )
        rm.initialize_day(10000.0)
        # Mock trade_logger to avoid file I/O
        rm.trade_logger = MagicMock()
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_record_trade_entry_success(self, risk_manager):
        """Should record a trade entry and return True."""
        result = risk_manager.record_trade_entry(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=75,
            reason="Test trade",
            order_id="order_001",
        )

        assert result is True

    def test_record_trade_entry_increments_global_count(self, risk_manager):
        """Should increment global trade count."""
        risk_manager.record_trade_entry(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=75,
            reason="Test",
            order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()
        assert stats.trades_executed == 1

    def test_record_trade_entry_increments_symbol_count(self, risk_manager):
        """Should increment per-symbol trade count."""
        risk_manager.record_trade_entry(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=75,
            reason="Test",
            order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()
        assert stats.symbol_trades["BTCUSDT"] == 1

    def test_record_trade_entry_multiple_symbols(self, risk_manager):
        """Should track trades per symbol independently."""
        risk_manager.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, leverage=4, confidence=75,
            reason="BTC", order_id="order_001",
        )
        risk_manager.record_trade_entry(
            symbol="ETHUSDT", side="short", size=0.1,
            entry_price=3500.0, leverage=4, confidence=80,
            reason="ETH", order_id="order_002",
        )
        risk_manager.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.02,
            entry_price=96000.0, leverage=4, confidence=70,
            reason="BTC2", order_id="order_003",
        )

        stats = risk_manager.get_daily_stats()
        assert stats.trades_executed == 3
        assert stats.symbol_trades["BTCUSDT"] == 2
        assert stats.symbol_trades["ETHUSDT"] == 1

    def test_record_trade_entry_without_initialization(self):
        """Should return False if daily stats are not initialized."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(data_dir=temp_dir)
            rm._daily_stats = None
            rm.trade_logger = MagicMock()

            result = rm.record_trade_entry(
                symbol="BTCUSDT", side="long", size=0.01,
                entry_price=95000.0, leverage=4, confidence=75,
                reason="Test", order_id="order_001",
            )

            assert result is False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_record_trade_entry_calls_trade_logger(self, risk_manager):
        """Should call trade_logger.log_trade_entry with correct args."""
        risk_manager.record_trade_entry(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=75,
            reason="Test signal",
            order_id="order_001",
        )

        risk_manager.trade_logger.log_trade_entry.assert_called_once_with(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=75,
            reason="Test signal",
            order_id="order_001",
        )


# ---------------------------------------------------------------------------
# Record trade exit tests
# ---------------------------------------------------------------------------


class TestRecordTradeExit:
    """Tests for record_trade_exit."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            max_trades_per_day=10,
            daily_loss_limit_percent=5.0,
            data_dir=temp_dir,
        )
        rm.initialize_day(10000.0)
        # Mock trade_logger to avoid file I/O
        rm.trade_logger = MagicMock()
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_record_trade_exit_long_profit(self, risk_manager):
        """Should correctly calculate PnL for a profitable long trade."""
        result = risk_manager.record_trade_exit(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            fees=2.0,
            funding_paid=0.5,
            reason="TAKE_PROFIT",
            order_id="order_001",
        )

        assert result is True
        stats = risk_manager.get_daily_stats()

        # PnL = (96000 - 95000) * 0.01 = 10.0
        assert stats.total_pnl == 10.0
        assert stats.winning_trades == 1
        assert stats.losing_trades == 0

    def test_record_trade_exit_long_loss(self, risk_manager):
        """Should correctly calculate PnL for a losing long trade."""
        risk_manager.record_trade_exit(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=94000.0,
            fees=2.0,
            funding_paid=0.5,
            reason="STOP_LOSS",
            order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()

        # PnL = (94000 - 95000) * 0.01 = -10.0
        assert stats.total_pnl == -10.0
        assert stats.winning_trades == 0
        assert stats.losing_trades == 1

    def test_record_trade_exit_short_profit(self, risk_manager):
        """Should correctly calculate PnL for a profitable short trade."""
        risk_manager.record_trade_exit(
            symbol="BTCUSDT",
            side="short",
            size=0.01,
            entry_price=95000.0,
            exit_price=94000.0,
            fees=2.0,
            funding_paid=0.5,
            reason="TAKE_PROFIT",
            order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()

        # PnL = (95000 - 94000) * 0.01 = 10.0
        assert stats.total_pnl == 10.0
        assert stats.winning_trades == 1

    def test_record_trade_exit_short_loss(self, risk_manager):
        """Should correctly calculate PnL for a losing short trade."""
        risk_manager.record_trade_exit(
            symbol="BTCUSDT",
            side="short",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            fees=2.0,
            funding_paid=0.5,
            reason="STOP_LOSS",
            order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()

        # PnL = (95000 - 96000) * 0.01 = -10.0
        assert stats.total_pnl == -10.0
        assert stats.losing_trades == 1

    def test_record_trade_exit_updates_fees_and_funding(self, risk_manager):
        """Should accumulate fees and funding."""
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            fees=2.0, funding_paid=0.5,
            reason="TP", order_id="order_001",
        )
        risk_manager.record_trade_exit(
            symbol="ETHUSDT", side="short", size=0.1,
            entry_price=3500.0, exit_price=3400.0,
            fees=1.5, funding_paid=0.3,
            reason="TP", order_id="order_002",
        )

        stats = risk_manager.get_daily_stats()
        assert abs(stats.total_fees - 3.5) < 0.01
        assert abs(stats.total_funding - 0.8) < 0.01

    def test_record_trade_exit_updates_current_balance(self, risk_manager):
        """Should update current_balance correctly."""
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            fees=2.0, funding_paid=0.5,
            reason="TP", order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()
        # current_balance = 10000 + (10.0 - 2.0 - 0.5) = 10007.5
        assert abs(stats.current_balance - 10007.5) < 0.01

    def test_record_trade_exit_tracks_symbol_pnl(self, risk_manager):
        """Should track PnL per symbol."""
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            fees=0.0, funding_paid=0.0,
            reason="TP", order_id="order_001",
        )
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=96000.0, exit_price=95000.0,
            fees=0.0, funding_paid=0.0,
            reason="SL", order_id="order_002",
        )

        stats = risk_manager.get_daily_stats()
        # BTC: +10 - 10 = 0
        assert abs(stats.symbol_pnl["BTCUSDT"]) < 0.01

    def test_record_trade_exit_updates_max_drawdown(self, risk_manager):
        """Should update max_drawdown when losses increase."""
        # First losing trade
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=95000.0, exit_price=94000.0,
            fees=0.0, funding_paid=0.0,
            reason="SL", order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()
        # PnL = (94000 - 95000) * 0.1 = -100 -> return = -1%
        assert stats.max_drawdown > 0

    def test_record_trade_exit_without_initialization(self):
        """Should return False if daily stats are not initialized."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(data_dir=temp_dir)
            rm._daily_stats = None
            rm.trade_logger = MagicMock()

            result = rm.record_trade_exit(
                symbol="BTCUSDT", side="long", size=0.01,
                entry_price=95000.0, exit_price=96000.0,
                fees=0.0, funding_paid=0.0,
                reason="TP", order_id="order_001",
            )

            assert result is False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_record_trade_exit_halts_symbol_on_loss_limit(self):
        """Should halt a symbol when per-symbol loss limit is exceeded."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(
                daily_loss_limit_percent=5.0,
                data_dir=temp_dir,
                per_symbol_limits={
                    "BTCUSDT": {"max_trades": 10, "loss_limit": 1.0},
                },
            )
            rm.initialize_day(10000.0)
            rm.trade_logger = MagicMock()

            # Record a loss that exceeds BTC's 1% limit (100 on 10000)
            rm.record_trade_exit(
                symbol="BTCUSDT", side="long", size=0.1,
                entry_price=95000.0, exit_price=93800.0,
                fees=0.0, funding_paid=0.0,
                reason="SL", order_id="order_001",
            )

            stats = rm.get_daily_stats()
            # PnL = (93800 - 95000) * 0.1 = -120 -> 1.2% of 10000 > 1%
            assert "BTCUSDT" in stats.halted_symbols
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_record_trade_exit_uses_global_loss_limit_for_symbol_without_override(self):
        """Symbol without per-symbol loss_limit should use global limit."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(
                daily_loss_limit_percent=2.0,
                data_dir=temp_dir,
            )
            rm.initialize_day(10000.0)
            rm.trade_logger = MagicMock()

            # Record a loss that exceeds global 2% limit (200 on 10000)
            rm.record_trade_exit(
                symbol="ETHUSDT", side="long", size=1.0,
                entry_price=3500.0, exit_price=3200.0,
                fees=0.0, funding_paid=0.0,
                reason="SL", order_id="order_001",
            )

            stats = rm.get_daily_stats()
            # PnL = (3200 - 3500) * 1.0 = -300 -> 3% of 10000 > 2%
            assert "ETHUSDT" in stats.halted_symbols
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_record_trade_exit_calls_trade_logger(self, risk_manager):
        """Should call trade_logger.log_trade_exit with correct args."""
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            fees=2.0, funding_paid=0.5,
            reason="TAKE_PROFIT", order_id="order_001",
        )

        risk_manager.trade_logger.log_trade_exit.assert_called_once()
        call_kwargs = risk_manager.trade_logger.log_trade_exit.call_args[1]
        assert call_kwargs["symbol"] == "BTCUSDT"
        assert call_kwargs["side"] == "long"
        assert call_kwargs["pnl"] == 10.0  # (96000-95000)*0.01


# ---------------------------------------------------------------------------
# Profit Lock-In tests
# ---------------------------------------------------------------------------


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
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_dynamic_loss_limit_no_profit(self, risk_manager):
        """Without profit, loss limit should be the configured limit."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = 0.0

        dynamic_limit = risk_manager.get_dynamic_loss_limit()

        # Should be the configured limit (5%)
        assert dynamic_limit == 5.0

    def test_dynamic_loss_limit_with_profit(self, risk_manager):
        """With profit, loss limit should be reduced to lock in gains."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = 400.0  # 4% profit on 10000

        dynamic_limit = risk_manager.get_dynamic_loss_limit()

        # return_percent = 4%, max_allowed_loss = 4 - 0.5 = 3.5
        # new_limit = min(5.0, 3.5) = 3.5, max(3.5, 0.5) = 3.5
        assert dynamic_limit == 3.5

    def test_dynamic_loss_limit_no_limit_set(self):
        """Should return None if daily_loss_limit is None."""
        temp_dir = tempfile.mkdtemp()
        try:
            with patch('src.risk.risk_manager.settings') as mock_settings:
                mock_settings.trading.max_trades_per_day = None
                mock_settings.trading.daily_loss_limit_percent = None
                mock_settings.trading.position_size_percent = 10.0

                rm = RiskManager(data_dir=temp_dir)
                rm.initialize_day(10000.0)

                result = rm.get_dynamic_loss_limit()

                assert result is None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_dynamic_loss_limit_profit_lock_disabled(self):
        """Should return configured limit when profit lock is disabled."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(
                daily_loss_limit_percent=5.0,
                enable_profit_lock=False,
                data_dir=temp_dir,
            )
            rm.initialize_day(10000.0)
            rm.get_daily_stats().total_pnl = 400.0  # 4% profit

            result = rm.get_dynamic_loss_limit()

            assert result == 5.0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_dynamic_loss_limit_without_daily_stats(self):
        """Should return configured limit when daily stats not initialized."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(
                daily_loss_limit_percent=5.0,
                enable_profit_lock=True,
                data_dir=temp_dir,
            )
            rm._daily_stats = None

            result = rm.get_dynamic_loss_limit()

            assert result == 5.0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_dynamic_loss_limit_negative_return(self, risk_manager):
        """With negative return, should use configured limit."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = -200.0  # -2% return

        dynamic_limit = risk_manager.get_dynamic_loss_limit()

        assert dynamic_limit == 5.0

    def test_dynamic_loss_limit_small_profit_floors_at_minimum(self, risk_manager):
        """Small profit should floor at 0.5% (min_profit_floor)."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = 60.0  # 0.6% return

        dynamic_limit = risk_manager.get_dynamic_loss_limit()

        # max_allowed_loss = 0.6 - 0.5 = 0.1
        # new_limit = min(5.0, 0.1) = 0.1
        # max(0.1, 0.5) = 0.5 (floored)
        assert dynamic_limit == 0.5


# ---------------------------------------------------------------------------
# get_daily_stats tests
# ---------------------------------------------------------------------------


class TestGetDailyStats:
    """Tests for getting daily stats."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_daily_stats_returns_none_if_not_initialized(self, risk_manager):
        """Should return None if day not initialized."""
        risk_manager._daily_stats = None

        stats = risk_manager.get_daily_stats()

        assert stats is None

    def test_get_daily_stats_returns_stats(self, risk_manager):
        """Should return stats after initialization."""
        risk_manager.initialize_day(10000.0)

        stats = risk_manager.get_daily_stats()

        assert stats is not None
        assert stats.starting_balance == 10000.0


# ---------------------------------------------------------------------------
# get_remaining_trades tests
# ---------------------------------------------------------------------------


class TestGetRemainingTrades:
    """Tests for get_remaining_trades."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            max_trades_per_day=5,
            data_dir=temp_dir,
            per_symbol_limits={
                "BTCUSDT": {"max_trades": 3},
                "ETHUSDT": {"max_trades": 2},
            },
        )
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_remaining_trades_global_initial(self, risk_manager):
        """Should return max_trades when no trades executed."""
        remaining = risk_manager.get_remaining_trades()

        assert remaining == 5

    def test_remaining_trades_global_after_some_trades(self, risk_manager):
        """Should return correct remaining after some trades."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 3

        remaining = risk_manager.get_remaining_trades()

        assert remaining == 2  # 5 - 3

    def test_remaining_trades_global_all_used(self, risk_manager):
        """Should return 0 when all trades used."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 5

        remaining = risk_manager.get_remaining_trades()

        assert remaining == 0

    def test_remaining_trades_global_never_negative(self, risk_manager):
        """Should never return negative remaining trades."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 10  # Over limit

        remaining = risk_manager.get_remaining_trades()

        assert remaining == 0

    def test_remaining_trades_global_no_limit(self):
        """Should return 999 when max_trades is None (no limit)."""
        temp_dir = tempfile.mkdtemp()
        try:
            with patch('src.risk.risk_manager.settings') as mock_settings:
                mock_settings.trading.max_trades_per_day = None
                mock_settings.trading.daily_loss_limit_percent = None
                mock_settings.trading.position_size_percent = 10.0

                rm = RiskManager(data_dir=temp_dir)
                rm.initialize_day(10000.0)

                remaining = rm.get_remaining_trades()

                assert remaining == 999
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_remaining_trades_global_no_stats(self):
        """Should return max_trades when no stats initialized."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(max_trades_per_day=5, data_dir=temp_dir)
            rm._daily_stats = None

            remaining = rm.get_remaining_trades()

            assert remaining == 5
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_remaining_trades_per_symbol(self, risk_manager):
        """Should return per-symbol remaining trades."""
        stats = risk_manager.get_daily_stats()
        stats.symbol_trades["BTCUSDT"] = 1

        remaining = risk_manager.get_remaining_trades(symbol="BTCUSDT")

        assert remaining == 2  # 3 - 1

    def test_remaining_trades_per_symbol_no_trades_yet(self, risk_manager):
        """Should return full limit when no symbol trades yet."""
        remaining = risk_manager.get_remaining_trades(symbol="BTCUSDT")

        assert remaining == 3

    def test_remaining_trades_symbol_uses_global_fallback(self, risk_manager):
        """Symbol without per-symbol limit should use global max_trades."""
        stats = risk_manager.get_daily_stats()
        stats.symbol_trades["SOLUSDT"] = 2

        remaining = risk_manager.get_remaining_trades(symbol="SOLUSDT")

        assert remaining == 3  # 5 (global) - 2

    def test_remaining_trades_symbol_no_limit(self):
        """Should return 999 for symbol with no limit (global also None)."""
        temp_dir = tempfile.mkdtemp()
        try:
            with patch('src.risk.risk_manager.settings') as mock_settings:
                mock_settings.trading.max_trades_per_day = None
                mock_settings.trading.daily_loss_limit_percent = None
                mock_settings.trading.position_size_percent = 10.0

                rm = RiskManager(data_dir=temp_dir)
                rm.initialize_day(10000.0)

                remaining = rm.get_remaining_trades(symbol="BTCUSDT")

                assert remaining == 999
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_remaining_trades_symbol_no_stats(self):
        """Should return effective max for symbol when no stats initialized."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(
                max_trades_per_day=5,
                data_dir=temp_dir,
                per_symbol_limits={"BTCUSDT": {"max_trades": 3}},
            )
            rm._daily_stats = None

            remaining = rm.get_remaining_trades(symbol="BTCUSDT")

            assert remaining == 3
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# get_remaining_risk_budget tests
# ---------------------------------------------------------------------------


class TestGetRemainingRiskBudget:
    """Tests for get_remaining_risk_budget."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            daily_loss_limit_percent=5.0,
            data_dir=temp_dir,
        )
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_full_budget_at_start(self, risk_manager):
        """Should return full budget with no losses."""
        budget = risk_manager.get_remaining_risk_budget()

        assert budget == 5.0

    def test_budget_decreases_with_losses(self, risk_manager):
        """Should return reduced budget after losses."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = -200.0  # 2% loss

        budget = risk_manager.get_remaining_risk_budget()

        assert abs(budget - 3.0) < 0.01  # 5% - 2% = 3%

    def test_budget_zero_when_limit_reached(self, risk_manager):
        """Should return 0 when loss limit is reached."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = -600.0  # 6% loss, exceeds 5%

        budget = risk_manager.get_remaining_risk_budget()

        assert budget == 0

    def test_budget_none_when_no_limit(self):
        """Should return None when no loss limit is set."""
        temp_dir = tempfile.mkdtemp()
        try:
            with patch('src.risk.risk_manager.settings') as mock_settings:
                mock_settings.trading.max_trades_per_day = None
                mock_settings.trading.daily_loss_limit_percent = None
                mock_settings.trading.position_size_percent = 10.0

                rm = RiskManager(data_dir=temp_dir)
                rm.initialize_day(10000.0)

                budget = rm.get_remaining_risk_budget()

                assert budget is None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_budget_returns_limit_when_no_stats(self):
        """Should return full limit when no stats initialized."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(daily_loss_limit_percent=5.0, data_dir=temp_dir)
            rm._daily_stats = None

            budget = rm.get_remaining_risk_budget()

            assert budget == 5.0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_budget_unaffected_by_profits(self, risk_manager):
        """Positive PnL should not affect risk budget (loss budget stays full)."""
        stats = risk_manager.get_daily_stats()
        stats.total_pnl = 500.0  # 5% profit

        budget = risk_manager.get_remaining_risk_budget()

        # current_loss = abs(min(0, return_percent)) = abs(min(0, 5.0)) = 0
        assert budget == 5.0


# ---------------------------------------------------------------------------
# get_historical_stats tests
# ---------------------------------------------------------------------------


class TestGetHistoricalStats:
    """Tests for get_historical_stats."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_historical_stats_empty_when_no_data(self):
        """Should return empty list when no historical data exists."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(data_dir=temp_dir)
            rm._daily_stats = None

            stats = rm.get_historical_stats(days=7)

            assert stats == []
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_historical_stats_includes_today(self, risk_manager):
        """Should include today's stats if they exist."""
        stats = risk_manager.get_historical_stats(days=1)

        assert len(stats) == 1
        assert stats[0]["starting_balance"] == 10000.0

    def test_historical_stats_respects_days_parameter(self, risk_manager):
        """Should only look back the specified number of days."""
        stats = risk_manager.get_historical_stats(days=30)

        # Only today should exist
        assert len(stats) == 1

    def test_historical_stats_skips_corrupted_files(self, risk_manager):
        """Should skip files that contain invalid JSON."""
        # Create a corrupted stats file for yesterday
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        corrupted_file = risk_manager.data_dir / f"daily_stats_{yesterday}.json"
        with open(corrupted_file, "w") as f:
            f.write("not valid json {{{")

        stats = risk_manager.get_historical_stats(days=7)

        # Should only include today's valid data
        assert len(stats) == 1


# ---------------------------------------------------------------------------
# get_performance_summary tests
# ---------------------------------------------------------------------------


class TestGetPerformanceSummary:
    """Tests for get_performance_summary."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_performance_summary_no_data(self):
        """Should return zero values when no historical data."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(data_dir=temp_dir)
            rm._daily_stats = None

            summary = rm.get_performance_summary(days=30)

            assert summary["period_days"] == 0
            assert summary["total_trades"] == 0
            assert summary["total_pnl"] == 0.0
            assert summary["win_rate"] == 0.0
            assert summary["sharpe_estimate"] == 0.0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_performance_summary_with_data(self, risk_manager):
        """Should calculate correct summary from historical data."""
        # Modify today's stats to have some data
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 5
        stats.winning_trades = 3
        stats.losing_trades = 2
        stats.total_pnl = 200.0
        stats.total_fees = 10.0
        risk_manager._save_daily_stats()

        summary = risk_manager.get_performance_summary(days=1)

        assert summary["period_days"] == 1
        assert summary["total_trades"] == 5
        assert summary["winning_trades"] == 3
        assert summary["losing_trades"] == 2
        assert summary["win_rate"] == 60.0

    def test_performance_summary_win_rate_no_trades(self, risk_manager):
        """Win rate should be 0 when no winning or losing trades."""
        summary = risk_manager.get_performance_summary(days=1)

        assert summary["win_rate"] == 0.0

    def test_performance_summary_sharpe_zero_std(self, risk_manager):
        """Sharpe should be 0 when return std is 0."""
        # Only one day with 0 return -> std = 0
        summary = risk_manager.get_performance_summary(days=1)

        assert summary["sharpe_estimate"] == 0.0

    def test_performance_summary_includes_max_drawdown(self, risk_manager):
        """Should include max drawdown from historical data."""
        stats = risk_manager.get_daily_stats()
        stats.max_drawdown = 3.5
        risk_manager._save_daily_stats()

        summary = risk_manager.get_performance_summary(days=1)

        assert summary["max_drawdown"] == 3.5


# ---------------------------------------------------------------------------
# _get_stats_file tests
# ---------------------------------------------------------------------------


class TestGetStatsFile:
    """Tests for _get_stats_file path generation."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_stats_file_today(self, risk_manager):
        """Should return path with today's date."""
        today = datetime.now().strftime("%Y-%m-%d")

        path = risk_manager._get_stats_file()

        assert path.name == f"daily_stats_{today}.json"

    def test_get_stats_file_specific_date(self, risk_manager):
        """Should return path with specified date."""
        path = risk_manager._get_stats_file("2024-06-15")

        assert path.name == "daily_stats_2024-06-15.json"

    def test_get_stats_file_in_data_dir(self, risk_manager):
        """File should be in the data directory."""
        path = risk_manager._get_stats_file("2024-01-01")

        assert path.parent == risk_manager.data_dir


# ---------------------------------------------------------------------------
# _load_daily_stats tests
# ---------------------------------------------------------------------------


class TestLoadDailyStats:
    """Tests for _load_daily_stats."""

    def test_load_daily_stats_from_existing_file(self):
        """Should load stats from a valid JSON file."""
        temp_dir = tempfile.mkdtemp()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            stats_file = Path(temp_dir) / f"daily_stats_{today}.json"

            # Create valid stats file
            stats_data = {
                "date": today,
                "starting_balance": 10000.0,
                "current_balance": 10200.0,
                "trades_executed": 3,
                "winning_trades": 2,
                "losing_trades": 1,
                "total_pnl": 250.0,
                "total_fees": 30.0,
                "total_funding": 20.0,
                "net_pnl": 200.0,
                "return_percent": 2.0,
                "win_rate": 66.67,
                "max_drawdown": 1.5,
                "is_trading_halted": False,
                "halt_reason": "",
                "symbol_trades": {"BTCUSDT": 2},
                "symbol_pnl": {"BTCUSDT": 200.0},
                "halted_symbols": {},
            }
            with open(stats_file, "w") as f:
                json.dump(stats_data, f)

            rm = RiskManager(data_dir=temp_dir)

            stats = rm.get_daily_stats()
            assert stats is not None
            assert stats.trades_executed == 3
            assert stats.winning_trades == 2
            assert stats.starting_balance == 10000.0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_load_daily_stats_corrupted_file(self):
        """Should set stats to None when file is corrupted."""
        temp_dir = tempfile.mkdtemp()
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            stats_file = Path(temp_dir) / f"daily_stats_{today}.json"

            with open(stats_file, "w") as f:
                f.write("corrupted data {{{")

            rm = RiskManager(data_dir=temp_dir)

            stats = rm.get_daily_stats()
            assert stats is None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_load_daily_stats_no_file(self):
        """Should leave stats as None when no file exists."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(data_dir=temp_dir)

            stats = rm.get_daily_stats()
            assert stats is None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# _save_daily_stats tests
# ---------------------------------------------------------------------------


class TestSaveDailyStats:
    """Tests for _save_daily_stats."""

    @pytest.fixture
    def risk_manager(self):
        """Create a risk manager with temp directory."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(data_dir=temp_dir)
        rm.initialize_day(10000.0)
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_save_daily_stats_creates_file(self, risk_manager):
        """Should create a JSON file with correct content."""
        risk_manager._save_daily_stats()

        today = datetime.now().strftime("%Y-%m-%d")
        stats_file = risk_manager.data_dir / f"daily_stats_{today}.json"

        assert stats_file.exists()
        with open(stats_file, "r") as f:
            data = json.load(f)
        assert data["starting_balance"] == 10000.0

    def test_save_daily_stats_no_stats_is_noop(self):
        """Should not crash or create files when stats is None."""
        temp_dir = tempfile.mkdtemp()
        try:
            rm = RiskManager(data_dir=temp_dir)
            rm._daily_stats = None

            # Should not raise
            rm._save_daily_stats()

            # No files should be created (except the dir itself)
            json_files = list(Path(temp_dir).glob("*.json"))
            assert len(json_files) == 0
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_save_daily_stats_overwrites_existing(self, risk_manager):
        """Should overwrite existing file with new data."""
        stats = risk_manager.get_daily_stats()
        stats.trades_executed = 5
        risk_manager._save_daily_stats()

        today = datetime.now().strftime("%Y-%m-%d")
        stats_file = risk_manager.data_dir / f"daily_stats_{today}.json"
        with open(stats_file, "r") as f:
            data = json.load(f)

        assert data["trades_executed"] == 5


# ---------------------------------------------------------------------------
# Integration scenario tests (multiple methods combined)
# ---------------------------------------------------------------------------


class TestRiskManagerIntegrationScenarios:
    """Integration-style tests that exercise multiple methods together."""

    @pytest.fixture
    def risk_manager(self):
        """Create a fully configured risk manager."""
        temp_dir = tempfile.mkdtemp()
        rm = RiskManager(
            max_trades_per_day=5,
            daily_loss_limit_percent=5.0,
            position_size_percent=10.0,
            data_dir=temp_dir,
            per_symbol_limits={
                "BTCUSDT": {"max_trades": 3, "loss_limit": 2.0},
            },
        )
        rm.initialize_day(10000.0)
        rm.trade_logger = MagicMock()
        yield rm
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_full_trade_lifecycle(self, risk_manager):
        """Test recording entry, then exit, and stats update."""
        # Check we can trade
        can_trade, _ = risk_manager.can_trade(symbol="BTCUSDT")
        assert can_trade is True

        # Record entry
        risk_manager.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, leverage=4, confidence=75,
            reason="Bullish signal", order_id="order_001",
        )

        # Record exit with profit
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.01,
            entry_price=95000.0, exit_price=96000.0,
            fees=2.0, funding_paid=0.5,
            reason="TAKE_PROFIT", order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()
        assert stats.trades_executed == 1
        assert stats.winning_trades == 1
        assert stats.total_pnl == 10.0  # (96000-95000)*0.01

    def test_multiple_trades_then_halt(self, risk_manager):
        """Test that hitting per-symbol trade limit stops further trades."""
        for i in range(3):
            risk_manager.record_trade_entry(
                symbol="BTCUSDT", side="long", size=0.01,
                entry_price=95000.0, leverage=4, confidence=75,
                reason=f"Trade {i+1}", order_id=f"order_{i+1:03d}",
            )

        # BTC limit is 3 trades, should be blocked
        can_trade, reason = risk_manager.can_trade(symbol="BTCUSDT")
        assert can_trade is False

        # But other symbols should still be fine
        can_trade, _ = risk_manager.can_trade(symbol="ETHUSDT")
        assert can_trade is True

    def test_loss_triggers_global_halt(self, risk_manager):
        """Test that exceeding global loss limit halts all trading."""
        # Record a big loss: PnL = (90000 - 95000) * 0.1 = -500
        risk_manager.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=95000.0, exit_price=90000.0,
            fees=5.0, funding_paid=0.0,
            reason="STOP_LOSS", order_id="order_001",
        )

        stats = risk_manager.get_daily_stats()
        # total_pnl = -500 -> return = -5% which equals the limit

        # Global check (symbol=None) should halt trading
        can_trade, reason = risk_manager.can_trade()

        assert can_trade is False
        assert stats.is_trading_halted is True

    def test_position_sizing_and_remaining_budget(self, risk_manager):
        """Test position sizing respects risk budget."""
        # Check initial budget
        budget = risk_manager.get_remaining_risk_budget()
        assert budget == 5.0

        remaining = risk_manager.get_remaining_trades()
        assert remaining == 5

        # Calculate position size
        usdt, base = risk_manager.calculate_position_size(
            balance=10000.0,
            entry_price=95000.0,
            confidence=75,
            leverage=4,
        )

        assert usdt > 0
        assert base > 0


class TestStatsFileHelpers:
    """Tests for _read_stats_file / _write_stats_file static methods."""

    @pytest.fixture
    def temp_data_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_write_and_read_roundtrip(self, temp_data_dir):
        """_write_stats_file + _read_stats_file roundtrip."""
        path = Path(temp_data_dir) / "test_stats.json"
        data = {"date": "2026-02-17", "trades_executed": 5, "total_pnl": 42.5}

        RiskManager._write_stats_file(path, data)
        result = RiskManager._read_stats_file(path)

        assert result == data

    def test_read_nonexistent_file_raises(self, temp_data_dir):
        """_read_stats_file raises on missing file."""
        path = Path(temp_data_dir) / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            RiskManager._read_stats_file(path)

    def test_write_creates_file(self, temp_data_dir):
        """_write_stats_file creates the file."""
        path = Path(temp_data_dir) / "new_stats.json"
        assert not path.exists()
        RiskManager._write_stats_file(path, {"test": True})
        assert path.exists()
