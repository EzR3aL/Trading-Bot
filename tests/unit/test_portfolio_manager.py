"""
Tests for the Portfolio Manager module.
"""

import pytest
from datetime import datetime

from src.portfolio.manager import (
    PortfolioManager,
    AssetAllocation,
    PortfolioState,
    DEFAULT_PORTFOLIO,
)


class TestAssetAllocation:
    """Tests for AssetAllocation dataclass."""

    def test_default_max_weight(self):
        """Test that max_weight auto-calculates from target_weight."""
        alloc = AssetAllocation(symbol="BTCUSDT", target_weight=0.40)
        assert alloc.max_weight == pytest.approx(0.60)  # 1.5x target

    def test_explicit_max_weight(self):
        """Test explicit max_weight overrides default."""
        alloc = AssetAllocation(symbol="BTCUSDT", target_weight=0.40, max_weight=0.50)
        assert alloc.max_weight == 0.50

    def test_max_weight_capped_at_1(self):
        """Test max_weight doesn't exceed 1.0."""
        alloc = AssetAllocation(symbol="BTCUSDT", target_weight=0.80)
        assert alloc.max_weight <= 1.0


class TestPortfolioManager:
    """Tests for PortfolioManager class."""

    @pytest.fixture
    def portfolio(self):
        """Create a test portfolio."""
        allocations = {
            "BTCUSDT": AssetAllocation(symbol="BTCUSDT", target_weight=0.40),
            "ETHUSDT": AssetAllocation(symbol="ETHUSDT", target_weight=0.30),
            "SOLUSDT": AssetAllocation(symbol="SOLUSDT", target_weight=0.15),
            "DOGEUSDT": AssetAllocation(symbol="DOGEUSDT", target_weight=0.15),
        }
        return PortfolioManager(
            allocations=allocations,
            starting_capital=10000.0,
        )

    def test_initialization(self, portfolio):
        """Test portfolio initializes correctly."""
        assert portfolio.total_value == 10000.0
        assert len(portfolio.symbols) == 4
        assert "BTCUSDT" in portfolio.symbols

    def test_weight_normalization(self):
        """Test weights are normalized if they don't sum to 1."""
        allocations = {
            "BTCUSDT": AssetAllocation(symbol="BTCUSDT", target_weight=0.50),
            "ETHUSDT": AssetAllocation(symbol="ETHUSDT", target_weight=0.50),
            "SOLUSDT": AssetAllocation(symbol="SOLUSDT", target_weight=0.50),
        }
        pm = PortfolioManager(allocations=allocations)

        total = sum(a.target_weight for a in pm.allocations.values())
        assert abs(total - 1.0) < 0.01

    def test_calculate_position_size_btc(self, portfolio):
        """Test position sizing for BTC (40% weight)."""
        size, value = portfolio.calculate_position_size(
            symbol="BTCUSDT",
            confidence=85,
            entry_price=50000.0,
            leverage=3,
        )

        assert value > 0
        assert value <= 10000 * 0.40  # Should not exceed target weight allocation
        assert size > 0

    def test_calculate_position_size_small_asset(self, portfolio):
        """Test position sizing for smaller weight asset."""
        btc_size, btc_value = portfolio.calculate_position_size(
            symbol="BTCUSDT",
            confidence=85,
            entry_price=50000.0,
        )

        doge_size, doge_value = portfolio.calculate_position_size(
            symbol="DOGEUSDT",
            confidence=85,
            entry_price=0.10,
        )

        # DOGE (15%) should get less value than BTC (40%)
        assert doge_value < btc_value

    def test_calculate_position_size_low_confidence(self, portfolio):
        """Test position sizing with low confidence."""
        high_size, high_value = portfolio.calculate_position_size(
            symbol="BTCUSDT",
            confidence=85,
            entry_price=50000.0,
        )

        low_size, low_value = portfolio.calculate_position_size(
            symbol="BTCUSDT",
            confidence=55,
            entry_price=50000.0,
        )

        assert low_value < high_value

    def test_calculate_position_size_unknown_symbol(self, portfolio):
        """Test position sizing for unknown symbol uses fallback."""
        size, value = portfolio.calculate_position_size(
            symbol="UNKNOWN",
            confidence=75,
            entry_price=100.0,
        )

        # Should use equal weight fallback
        assert value >= 0

    def test_record_entry(self, portfolio):
        """Test recording a position entry."""
        initial_cash = portfolio._cash_balance

        portfolio.record_entry("BTCUSDT", 2000.0, 50000.0)

        assert portfolio._cash_balance == initial_cash - 2000.0
        assert portfolio._asset_states["BTCUSDT"].open_position_value == 2000.0
        assert portfolio._asset_states["BTCUSDT"].trade_count == 1

    def test_record_exit(self, portfolio):
        """Test recording a position exit."""
        portfolio.record_entry("BTCUSDT", 2000.0, 50000.0)
        initial_cash = portfolio._cash_balance

        portfolio.record_exit("BTCUSDT", 2000.0, 100.0)  # $100 profit

        assert portfolio._cash_balance == initial_cash + 2000.0 + 100.0
        assert portfolio._asset_states["BTCUSDT"].daily_pnl == 100.0
        assert portfolio._asset_states["BTCUSDT"].total_pnl == 100.0

    def test_record_exit_loss(self, portfolio):
        """Test recording a losing exit."""
        portfolio.record_entry("ETHUSDT", 1500.0, 3000.0)

        portfolio.record_exit("ETHUSDT", 1500.0, -50.0)  # $50 loss

        assert portfolio._asset_states["ETHUSDT"].daily_pnl == -50.0
        assert portfolio._asset_states["ETHUSDT"].total_pnl == -50.0

    def test_can_trade_asset(self, portfolio):
        """Test trade permission check."""
        can_trade, reason = portfolio.can_trade_asset("BTCUSDT")
        assert can_trade is True
        assert reason == "OK"

    def test_can_trade_unknown_asset(self, portfolio):
        """Test trade permission for unknown asset."""
        can_trade, reason = portfolio.can_trade_asset("UNKNOWN")
        assert can_trade is False

    def test_can_trade_after_loss_limit(self, portfolio):
        """Test trade blocked after per-asset loss limit."""
        portfolio.record_entry("BTCUSDT", 2000.0, 50000.0)
        # Simulate a big loss
        portfolio.record_exit("BTCUSDT", 2000.0, -600.0)  # 6% loss on $10k

        can_trade, reason = portfolio.can_trade_asset("BTCUSDT")
        assert can_trade is False
        assert "loss limit" in reason.lower()

    def test_get_state(self, portfolio):
        """Test getting portfolio state."""
        portfolio.record_entry("BTCUSDT", 3000.0, 50000.0)

        state = portfolio.get_state()

        assert isinstance(state, PortfolioState)
        assert state.total_value == 10000.0  # Cash + position
        assert state.cash_balance == 7000.0
        assert state.allocated_value == 3000.0
        assert "BTCUSDT" in state.assets

    def test_get_state_to_dict(self, portfolio):
        """Test state serialization."""
        state = portfolio.get_state()
        state_dict = state.to_dict()

        assert "total_value" in state_dict
        assert "cash_balance" in state_dict
        assert "assets" in state_dict
        assert "daily_pnl" in state_dict

    def test_rebalance_recommendations_no_drift(self, portfolio):
        """Test rebalance when all cash (underweight all assets)."""
        recs = portfolio.get_rebalance_recommendations()
        # With all cash, all assets are underweight vs their targets
        # so we should get "increase" recommendations for each
        assert all(r["action"] == "increase" for r in recs)

    def test_rebalance_recommendations_with_drift(self, portfolio):
        """Test rebalance recommendations when overweight."""
        # Make BTC significantly overweight
        portfolio.record_entry("BTCUSDT", 6000.0, 50000.0)

        recs = portfolio.get_rebalance_recommendations()

        # Should have recommendations
        assert len(recs) > 0

        btc_rec = next((r for r in recs if r["symbol"] == "BTCUSDT"), None)
        if btc_rec:
            assert btc_rec["action"] == "reduce"

    def test_per_asset_stats(self, portfolio):
        """Test per-asset statistics."""
        portfolio.record_entry("BTCUSDT", 3000.0, 50000.0)
        portfolio.record_entry("ETHUSDT", 1500.0, 3000.0)

        stats = portfolio.get_per_asset_stats()

        assert "BTCUSDT" in stats
        assert "ETHUSDT" in stats
        assert stats["BTCUSDT"]["target_weight"] == 0.40
        assert stats["ETHUSDT"]["target_weight"] == 0.30
        assert stats["BTCUSDT"]["open_position_value"] == 3000.0

    def test_total_value_preserved(self, portfolio):
        """Test that total value is preserved through entries/exits."""
        initial_value = portfolio.total_value

        portfolio.record_entry("BTCUSDT", 2000.0, 50000.0)
        assert portfolio.total_value == initial_value

        portfolio.record_exit("BTCUSDT", 2000.0, 50.0)
        # Total should increase by profit
        assert portfolio.total_value == pytest.approx(initial_value + 50.0)


class TestPortfolioManagerFromConfig:
    """Tests for creating PortfolioManager from config."""

    def test_from_config_with_weights(self):
        """Test creating from pairs and weights."""
        pm = PortfolioManager.from_config(
            trading_pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            portfolio_weights="50,30,20",
        )

        assert len(pm.allocations) == 3
        assert pm.allocations["BTCUSDT"].target_weight == pytest.approx(0.50)
        assert pm.allocations["ETHUSDT"].target_weight == pytest.approx(0.30)
        assert pm.allocations["SOLUSDT"].target_weight == pytest.approx(0.20)

    def test_from_config_no_weights(self):
        """Test creating with equal weights."""
        pm = PortfolioManager.from_config(
            trading_pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"],
        )

        # Equal weights
        for alloc in pm.allocations.values():
            assert alloc.target_weight == pytest.approx(0.25)

    def test_from_config_mismatched_weights(self):
        """Test fallback when weight count doesn't match pairs."""
        pm = PortfolioManager.from_config(
            trading_pairs=["BTCUSDT", "ETHUSDT"],
            portfolio_weights="40,30,20,10",  # Too many weights
        )

        # Should fall back to equal weights
        for alloc in pm.allocations.values():
            assert alloc.target_weight == pytest.approx(0.50)


class TestDefaultPortfolio:
    """Tests for default portfolio configuration."""

    def test_default_weights_sum_to_one(self):
        """Test default portfolio weights sum to 1."""
        total = sum(a.target_weight for a in DEFAULT_PORTFOLIO.values())
        assert total == pytest.approx(1.0)

    def test_default_has_four_assets(self):
        """Test default portfolio has 4 assets."""
        assert len(DEFAULT_PORTFOLIO) == 4

    def test_default_btc_largest(self):
        """Test BTC has the largest weight in defaults."""
        btc_weight = DEFAULT_PORTFOLIO["BTCUSDT"].target_weight
        for symbol, alloc in DEFAULT_PORTFOLIO.items():
            if symbol != "BTCUSDT":
                assert btc_weight >= alloc.target_weight
