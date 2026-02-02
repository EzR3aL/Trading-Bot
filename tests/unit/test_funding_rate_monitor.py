"""
Tests for the Funding Rate Monitor module.
"""

import pytest
from datetime import datetime, timedelta

from src.arbitrage.funding_rate import (
    FundingRateMonitor,
    FundingOpportunity,
    OpportunityStatus,
)


class TestFundingRateMonitor:
    """Tests for FundingRateMonitor class."""

    @pytest.fixture
    def monitor(self):
        """Create a test monitor with low thresholds for testing."""
        return FundingRateMonitor(
            min_rate=0.0005,
            exit_rate=0.0001,
            lookback_periods=6,
            min_consecutive=2,
        )

    def test_initialization(self, monitor):
        """Test monitor initializes with correct defaults."""
        assert monitor.min_rate == 0.0005
        assert monitor.exit_rate == 0.0001
        assert monitor.min_consecutive == 2
        assert len(monitor.get_all_opportunities()) == 0

    def test_record_rate(self, monitor):
        """Test recording funding rate observations."""
        monitor.record_rate("BTCUSDT", 0.001)
        monitor.record_rate("BTCUSDT", 0.0008)

        history = monitor.get_rate_history("BTCUSDT")
        assert len(history) == 2

    def test_record_rate_trims_old_data(self, monitor):
        """Test that old rate history is trimmed."""
        old_time = datetime.utcnow() - timedelta(days=30)
        monitor.record_rate("BTCUSDT", 0.001, old_time)
        monitor.record_rate("BTCUSDT", 0.001)

        history = monitor.get_rate_history("BTCUSDT")
        # Old entry should be trimmed
        assert len(history) == 1

    def test_scan_opportunities_above_threshold(self, monitor):
        """Test scanning identifies opportunities above threshold."""
        # Record enough consecutive periods above threshold
        for _ in range(3):
            monitor.record_rate("BTCUSDT", 0.001)

        opps = monitor.scan_opportunities({"BTCUSDT": 0.001}, position_value=10000.0)

        assert len(opps) == 1
        assert opps[0].symbol == "BTCUSDT"
        assert opps[0].funding_rate == 0.001
        assert opps[0].direction == "long_spot_short_perp"
        assert opps[0].expected_profit_per_cycle == 10.0  # 10000 * 0.001

    def test_scan_opportunities_below_threshold(self, monitor):
        """Test scanning skips rates below threshold."""
        opps = monitor.scan_opportunities({"BTCUSDT": 0.0001})
        assert len(opps) == 0

    def test_scan_opportunities_negative_rate(self, monitor):
        """Test scanning with negative funding rate."""
        for _ in range(3):
            monitor.record_rate("ETHUSDT", -0.001)

        opps = monitor.scan_opportunities({"ETHUSDT": -0.001})

        assert len(opps) == 1
        assert opps[0].direction == "short_spot_long_perp"

    def test_scan_opportunities_insufficient_consecutive(self, monitor):
        """Test that insufficient consecutive periods blocks entry."""
        # Only one period above threshold (need 2)
        monitor.record_rate("BTCUSDT", 0.001)

        opps = monitor.scan_opportunities({"BTCUSDT": 0.001})
        # First call records the rate, now we have 2 records but scan only
        # uses history before the current rate is added to scan
        # Actually: scan_opportunities calls record_rate, so after 2 calls
        # to record_rate + 1 scan, we have 3 entries
        # Let's test with min_consecutive=3 instead
        monitor2 = FundingRateMonitor(min_rate=0.0005, min_consecutive=4)
        monitor2.record_rate("BTCUSDT", 0.001)
        monitor2.record_rate("BTCUSDT", 0.001)
        # scan adds one more = 3, but need 4
        opps = monitor2.scan_opportunities({"BTCUSDT": 0.001})
        assert len(opps) == 0

    def test_scan_sorted_by_profit(self, monitor):
        """Test opportunities sorted by expected daily profit."""
        # Pre-load history
        for _ in range(3):
            monitor.record_rate("BTCUSDT", 0.002)
            monitor.record_rate("ETHUSDT", 0.001)

        opps = monitor.scan_opportunities(
            {"BTCUSDT": 0.002, "ETHUSDT": 0.001},
            position_value=10000.0,
        )

        assert len(opps) == 2
        assert opps[0].symbol == "BTCUSDT"  # Higher rate = more profit
        assert opps[0].expected_daily_profit > opps[1].expected_daily_profit

    def test_should_enter_active_opportunity(self, monitor):
        """Test entry check for active opportunity."""
        for _ in range(3):
            monitor.record_rate("BTCUSDT", 0.001)

        monitor.scan_opportunities({"BTCUSDT": 0.001})

        should, reason = monitor.should_enter("BTCUSDT")
        assert should is True
        assert "0.1000%" in reason

    def test_should_enter_no_opportunity(self, monitor):
        """Test entry check when no opportunity exists."""
        should, reason = monitor.should_enter("UNKNOWN")
        assert should is False
        assert "No opportunity" in reason

    def test_should_exit_below_threshold(self, monitor):
        """Test exit when rate drops below threshold."""
        should, reason = monitor.should_exit("BTCUSDT", 0.00005)
        assert should is True
        assert "below exit threshold" in reason

    def test_should_exit_still_profitable(self, monitor):
        """Test no exit when still profitable."""
        should, reason = monitor.should_exit("BTCUSDT", 0.001)
        assert should is False
        assert "still profitable" in reason

    def test_should_exit_direction_flip(self, monitor):
        """Test exit when rate direction flips."""
        for _ in range(3):
            monitor.record_rate("BTCUSDT", 0.001)
        monitor.scan_opportunities({"BTCUSDT": 0.001})

        should, reason = monitor.should_exit("BTCUSDT", -0.001)
        assert should is True
        assert "direction flipped" in reason

    def test_get_average_rate(self, monitor):
        """Test average rate calculation."""
        monitor.record_rate("BTCUSDT", 0.001)
        monitor.record_rate("BTCUSDT", 0.002)
        monitor.record_rate("BTCUSDT", 0.003)

        avg = monitor.get_average_rate("BTCUSDT", periods=3)
        assert avg == pytest.approx(0.002)

    def test_get_average_rate_no_data(self, monitor):
        """Test average rate with no data."""
        avg = monitor.get_average_rate("UNKNOWN")
        assert avg is None

    def test_opportunity_annualized_rate(self, monitor):
        """Test annualized rate calculation."""
        for _ in range(3):
            monitor.record_rate("BTCUSDT", 0.001)

        opps = monitor.scan_opportunities({"BTCUSDT": 0.001})

        assert len(opps) == 1
        # 0.1% per 8h * 3 periods/day * 365 days = 109.5%
        expected_annual = 0.001 * 3 * 365
        assert opps[0].annualized_rate == pytest.approx(expected_annual)

    def test_opportunity_to_dict(self, monitor):
        """Test opportunity serialization."""
        for _ in range(3):
            monitor.record_rate("BTCUSDT", 0.001)

        opps = monitor.scan_opportunities({"BTCUSDT": 0.001})
        d = opps[0].to_dict()

        assert d["symbol"] == "BTCUSDT"
        assert "funding_rate_pct" in d
        assert "annualized_rate" in d
        assert d["status"] == "active"

    def test_expired_opportunity(self, monitor):
        """Test opportunity expires when rate drops below exit."""
        for _ in range(3):
            monitor.record_rate("BTCUSDT", 0.001)
        monitor.scan_opportunities({"BTCUSDT": 0.001})

        # Rate drops below exit threshold
        monitor.scan_opportunities({"BTCUSDT": 0.00005})

        opp = monitor.get_opportunity("BTCUSDT")
        assert opp.status == OpportunityStatus.EXPIRED

    def test_get_summary(self, monitor):
        """Test summary output."""
        summary = monitor.get_summary()
        assert "tracked_symbols" in summary
        assert "active_opportunities" in summary
        assert "min_rate_threshold" in summary
        assert summary["tracked_symbols"] == 0


class TestFundingOpportunity:
    """Tests for FundingOpportunity dataclass."""

    def test_creation(self):
        """Test creating an opportunity."""
        opp = FundingOpportunity(
            symbol="BTCUSDT",
            funding_rate=0.001,
            annualized_rate=1.095,
            direction="long_spot_short_perp",
            expected_profit_per_cycle=10.0,
            expected_daily_profit=30.0,
        )
        assert opp.status == OpportunityStatus.ACTIVE
        assert opp.consecutive_periods == 1

    def test_to_dict_format(self):
        """Test serialization format."""
        opp = FundingOpportunity(
            symbol="ETHUSDT",
            funding_rate=-0.0008,
            annualized_rate=0.876,
            direction="short_spot_long_perp",
            expected_profit_per_cycle=8.0,
            expected_daily_profit=24.0,
            consecutive_periods=5,
        )
        d = opp.to_dict()
        assert d["funding_rate_pct"] == "-0.0800%"
        assert d["consecutive_periods"] == 5
