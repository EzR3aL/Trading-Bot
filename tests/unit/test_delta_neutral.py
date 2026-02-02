"""
Tests for the Delta-Neutral Position Manager module.
"""

import pytest
from datetime import datetime

from src.arbitrage.delta_neutral import (
    DeltaNeutralManager,
    ArbitragePosition,
    ArbitrageStatus,
    PositionLeg,
)


class TestPositionLeg:
    """Tests for PositionLeg dataclass."""

    def test_long_leg_pnl(self):
        """Test P&L calculation for long leg."""
        leg = PositionLeg(side="long", market_type="spot", entry_price=50000, size=0.1)
        leg.update_price(51000)
        assert leg.unrealized_pnl == pytest.approx(100.0)  # (51000-50000)*0.1

    def test_short_leg_pnl(self):
        """Test P&L calculation for short leg."""
        leg = PositionLeg(side="short", market_type="perpetual", entry_price=50000, size=0.1)
        leg.update_price(49000)
        assert leg.unrealized_pnl == pytest.approx(100.0)  # (50000-49000)*0.1

    def test_long_leg_loss(self):
        """Test loss calculation for long leg."""
        leg = PositionLeg(side="long", market_type="spot", entry_price=50000, size=0.1)
        leg.update_price(49000)
        assert leg.unrealized_pnl == pytest.approx(-100.0)

    def test_value_update(self):
        """Test value updates on price change."""
        leg = PositionLeg(side="long", market_type="spot", entry_price=50000, size=0.2)
        leg.update_price(55000)
        assert leg.value == pytest.approx(11000.0)  # 55000 * 0.2

    def test_to_dict(self):
        """Test serialization."""
        leg = PositionLeg(side="long", market_type="spot", entry_price=50000, size=0.1, value=5000)
        d = leg.to_dict()
        assert d["side"] == "long"
        assert d["market_type"] == "spot"


class TestArbitragePosition:
    """Tests for ArbitragePosition dataclass."""

    @pytest.fixture
    def position(self):
        """Create a test position."""
        spot = PositionLeg(
            side="long", market_type="spot",
            entry_price=50000, current_price=50000, size=0.2, value=10000,
        )
        perp = PositionLeg(
            side="short", market_type="perpetual",
            entry_price=50000, current_price=50000, size=0.2, value=10000,
        )
        return ArbitragePosition(
            id="ARB-0001", symbol="BTCUSDT",
            spot_leg=spot, perp_leg=perp,
            status=ArbitrageStatus.OPEN,
            entry_time=datetime.utcnow(),
            entry_funding_rate=0.001,
        )

    def test_net_delta_hedged(self, position):
        """Test net delta is zero when perfectly hedged."""
        # Long 0.2 + Short 0.2 = 0 net
        assert position.net_delta == pytest.approx(0.0)

    def test_delta_ratio_hedged(self, position):
        """Test delta ratio is zero when perfectly hedged."""
        assert position.delta_ratio == pytest.approx(0.0)

    def test_net_delta_drifted(self, position):
        """Test net delta when legs drift."""
        position.spot_leg.size = 0.22  # Spot grew
        position.perp_leg.size = 0.20
        # Long 0.22 + Short 0.20 = 0.02 net
        assert position.net_delta == pytest.approx(0.02)

    def test_delta_ratio_drifted(self, position):
        """Test delta ratio calculation with drift."""
        position.spot_leg.size = 0.22
        position.perp_leg.size = 0.20
        # abs(0.02) / (0.42/2) = 0.02/0.21 ≈ 0.0952
        assert position.delta_ratio == pytest.approx(0.02 / 0.21, rel=0.01)

    def test_total_pnl_breakeven(self, position):
        """Test total P&L at breakeven (no price movement)."""
        assert position.total_pnl == pytest.approx(0.0)

    def test_total_pnl_with_funding(self, position):
        """Test total P&L includes funding."""
        position.record_funding(15.0)
        assert position.total_pnl == pytest.approx(15.0)

    def test_total_pnl_with_fees(self, position):
        """Test total P&L subtracts fees."""
        position.record_funding(15.0)
        position.total_fees = 5.0
        assert position.total_pnl == pytest.approx(10.0)

    def test_total_pnl_delta_neutral(self, position):
        """Test P&L stays near zero during price movement (delta neutral)."""
        # Price goes up - spot gains, perp loses
        position.spot_leg.update_price(52000)
        position.perp_leg.update_price(52000)

        # Spot PnL = (52000-50000)*0.2 = 400
        # Perp PnL = (50000-52000)*0.2 = -400
        # Net price PnL = 0
        assert position.total_pnl == pytest.approx(0.0, abs=0.01)

    def test_record_funding(self, position):
        """Test funding recording."""
        position.record_funding(10.0)
        position.record_funding(12.0)
        assert position.funding_collected == pytest.approx(22.0)
        assert position.funding_payments == 2

    def test_total_value(self, position):
        """Test total value calculation."""
        assert position.total_value == pytest.approx(20000.0)

    def test_duration_hours(self, position):
        """Test duration calculation."""
        assert position.duration_hours >= 0.0

    def test_to_dict(self, position):
        """Test serialization."""
        d = position.to_dict()
        assert d["id"] == "ARB-0001"
        assert d["symbol"] == "BTCUSDT"
        assert d["status"] == "open"
        assert "spot_leg" in d
        assert "perp_leg" in d
        assert "net_delta" in d
        assert "total_pnl" in d


class TestDeltaNeutralManager:
    """Tests for DeltaNeutralManager class."""

    @pytest.fixture
    def manager(self):
        """Create a test manager."""
        return DeltaNeutralManager(
            max_positions=3,
            max_position_value=10000.0,
            delta_threshold=0.05,
            max_total_exposure=50000.0,
        )

    def test_initialization(self, manager):
        """Test manager initializes correctly."""
        assert manager.max_positions == 3
        assert len(manager.get_open_positions()) == 0

    def test_open_position_positive_rate(self, manager):
        """Test opening position with positive funding rate."""
        pos, reason = manager.open_position(
            symbol="BTCUSDT",
            funding_rate=0.001,
            spot_price=50000,
            perp_price=50000,
            position_value=5000,
        )

        assert pos is not None
        assert pos.spot_leg.side == "long"
        assert pos.perp_leg.side == "short"
        assert pos.status == ArbitrageStatus.OPEN
        assert pos.spot_leg.value == pytest.approx(5000)

    def test_open_position_negative_rate(self, manager):
        """Test opening position with negative funding rate."""
        pos, reason = manager.open_position(
            symbol="ETHUSDT",
            funding_rate=-0.001,
            spot_price=3000,
            perp_price=3000,
            position_value=5000,
        )

        assert pos is not None
        assert pos.spot_leg.side == "short"
        assert pos.perp_leg.side == "long"

    def test_open_position_max_reached(self, manager):
        """Test opening position when max is reached."""
        for i, sym in enumerate(["BTCUSDT", "ETHUSDT", "SOLUSDT"]):
            manager.open_position(sym, 0.001, 100, 100, 1000)

        pos, reason = manager.open_position("DOGEUSDT", 0.001, 1, 1, 1000)
        assert pos is None
        assert "Max positions" in reason

    def test_open_position_exceeds_max_value(self, manager):
        """Test rejecting position exceeding max value."""
        pos, reason = manager.open_position(
            "BTCUSDT", 0.001, 50000, 50000, 20000  # Exceeds 10000 max
        )
        assert pos is None
        assert "exceeds max" in reason

    def test_open_position_exceeds_total_exposure(self, manager):
        """Test rejecting position that would exceed total exposure."""
        # Open positions using most of the exposure
        manager.open_position("BTCUSDT", 0.001, 100, 100, 10000)
        manager.open_position("ETHUSDT", 0.001, 100, 100, 10000)

        # This would push total to 60k (3 * 10000 * 2 sides) > 50k
        pos, reason = manager.open_position("SOLUSDT", 0.001, 100, 100, 10000)
        assert pos is None
        assert "Total exposure" in reason

    def test_open_position_duplicate_symbol(self, manager):
        """Test rejecting duplicate symbol."""
        manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)

        pos, reason = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)
        assert pos is None
        assert "Already have" in reason

    def test_close_position(self, manager):
        """Test closing a position."""
        pos, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)
        pos.record_funding(15.0)

        closed, reason = manager.close_position(pos.id, 51000, 51000, fees=10.0)

        assert closed is not None
        assert closed.status == ArbitrageStatus.CLOSED
        assert closed.exit_time is not None
        assert closed.funding_collected == pytest.approx(15.0)
        assert closed.total_fees == pytest.approx(10.0)
        assert len(manager.get_open_positions()) == 0
        assert len(manager.get_closed_positions()) == 1

    def test_close_position_not_found(self, manager):
        """Test closing non-existent position."""
        closed, reason = manager.close_position("FAKE", 100, 100)
        assert closed is None
        assert "not found" in reason

    def test_update_prices(self, manager):
        """Test price updates and delta monitoring."""
        pos, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)

        # Small move - shouldn't need rebalance
        needs_rebalance = manager.update_prices("BTCUSDT", 50100, 50100)
        assert len(needs_rebalance) == 0

    def test_update_prices_triggers_rebalance(self, manager):
        """Test large price move triggers rebalance flag."""
        pos, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)

        # Manually create a delta imbalance by adjusting sizes
        pos.spot_leg.size = 0.12
        pos.perp_leg.size = 0.10
        pos.spot_leg.update_price(50000)
        pos.perp_leg.update_price(50000)

        needs_rebalance = manager.update_prices("BTCUSDT", 50000, 50000)
        # delta_ratio = |0.02| / 0.11 = 0.182 > 0.05
        assert len(needs_rebalance) == 1

    def test_record_funding_payment(self, manager):
        """Test recording funding payment."""
        pos, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)

        result = manager.record_funding_payment(pos.id, 5.0)
        assert result is True
        assert pos.funding_collected == pytest.approx(5.0)

    def test_record_funding_payment_not_found(self, manager):
        """Test recording funding for non-existent position."""
        result = manager.record_funding_payment("FAKE", 5.0)
        assert result is False

    def test_rebalance_position(self, manager):
        """Test rebalance calculation."""
        pos, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)

        # Create imbalance
        pos.spot_leg.size = 0.12
        pos.spot_leg.value = 6000
        pos.perp_leg.size = 0.10
        pos.perp_leg.value = 5000

        adj, reason = manager.rebalance_position(pos.id, 50000, 50000)

        assert adj is not None
        assert "Rebalance calculated" in reason
        assert pos.rebalance_count == 1
        # After rebalance, sizes should be equalized
        assert pos.spot_leg.size == pytest.approx(pos.perp_leg.size, rel=0.01)

    def test_rebalance_not_needed(self, manager):
        """Test rebalance skipped when delta is within threshold."""
        pos, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)

        adj, reason = manager.rebalance_position(pos.id, 50000, 50000)
        assert adj is None
        assert "no rebalance needed" in reason

    def test_get_total_funding_collected(self, manager):
        """Test total funding across positions."""
        pos1, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)
        pos2, _ = manager.open_position("ETHUSDT", 0.001, 3000, 3000, 5000)

        manager.record_funding_payment(pos1.id, 10.0)
        manager.record_funding_payment(pos2.id, 8.0)

        assert manager.get_total_funding_collected() == pytest.approx(18.0)

    def test_get_total_pnl(self, manager):
        """Test total P&L calculation."""
        pos, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)
        manager.record_funding_payment(pos.id, 15.0)

        assert manager.get_total_pnl() == pytest.approx(15.0)

    def test_get_summary(self, manager):
        """Test summary output."""
        manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)

        summary = manager.get_summary()
        assert summary["open_positions"] == 1
        assert summary["closed_positions"] == 0
        assert "total_funding_collected" in summary
        assert "positions" in summary
        assert len(summary["positions"]) == 1

    def test_position_id_increments(self, manager):
        """Test position IDs increment correctly."""
        pos1, _ = manager.open_position("BTCUSDT", 0.001, 50000, 50000, 5000)
        pos2, _ = manager.open_position("ETHUSDT", 0.001, 3000, 3000, 5000)

        assert pos1.id == "ARB-0001"
        assert pos2.id == "ARB-0002"

    def test_can_open_position_checks(self, manager):
        """Test can_open_position validation."""
        can, reason = manager.can_open_position("BTCUSDT", 5000)
        assert can is True
        assert reason == "OK"

        can, reason = manager.can_open_position("BTCUSDT", 15000)
        assert can is False
