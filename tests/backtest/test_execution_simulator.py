"""
Tests for ExecutionSimulator — realistic trade execution costs.

Validates:
1. Slippage model: volatility-based, direction-aware
2. Fee model: exchange-specific taker rates
3. Funding model: exact 8h window counting
4. Complete PnL calculation: all costs combined
"""

import pytest
from datetime import datetime, timezone

from src.backtest.execution_simulator import (
    ExecutionSimulator,
    FillResult,
    FEE_SCHEDULES,
    EIGHT_HOURS_SECONDS,
)


# ------------------------------------------------------------------ #
#  Fixtures                                                           #
# ------------------------------------------------------------------ #

@pytest.fixture
def bitget_sim():
    """Standard Bitget simulator."""
    return ExecutionSimulator(exchange="bitget", fee_tier="standard")


@pytest.fixture
def hyperliquid_sim():
    """Standard Hyperliquid simulator."""
    return ExecutionSimulator(exchange="hyperliquid", fee_tier="standard")


@pytest.fixture
def binance_sim():
    """Standard Binance simulator."""
    return ExecutionSimulator(exchange="binance", fee_tier="standard")


# ------------------------------------------------------------------ #
#  Initialization Tests                                               #
# ------------------------------------------------------------------ #

class TestInitialization:
    def test_default_exchange_is_bitget(self):
        sim = ExecutionSimulator()
        assert sim.exchange == "bitget"
        assert sim.taker_fee_rate == 0.0006  # 0.06%

    def test_hyperliquid_fees(self, hyperliquid_sim):
        assert hyperliquid_sim.taker_fee_rate == 0.00035  # 0.035%

    def test_binance_fees(self, binance_sim):
        assert binance_sim.taker_fee_rate == 0.0004  # 0.04%

    def test_unknown_exchange_falls_back_to_bitget(self):
        sim = ExecutionSimulator(exchange="unknown_exchange")
        assert sim.taker_fee_rate == 0.0006

    def test_unknown_tier_falls_back_to_standard(self):
        sim = ExecutionSimulator(exchange="bitget", fee_tier="unknown_tier")
        assert sim.taker_fee_rate == 0.0006

    def test_vip1_tier(self):
        sim = ExecutionSimulator(exchange="bitget", fee_tier="vip1")
        assert sim.taker_fee_rate == 0.0004

    def test_custom_slippage_params(self):
        sim = ExecutionSimulator(
            base_slippage=0.0005,
            volatility_slippage_factor=0.1,
            max_slippage=0.01,
        )
        assert sim.base_slippage == 0.0005
        assert sim.volatility_slippage_factor == 0.1
        assert sim.max_slippage == 0.01

    def test_builder_fee(self):
        sim = ExecutionSimulator(builder_fee_rate=0.0001)
        assert sim.builder_fee_rate == 0.0001


# ------------------------------------------------------------------ #
#  Slippage Model Tests                                               #
# ------------------------------------------------------------------ #

class TestSlippageModel:
    def test_calm_market_low_slippage(self, bitget_sim):
        # 0.2% candle range
        slip = bitget_sim.calculate_slippage_percent(0.002)
        assert slip == pytest.approx(0.0001 + 0.05 * 0.002, rel=1e-6)
        assert slip < 0.001  # Under 0.1%

    def test_normal_market_slippage(self, bitget_sim):
        # 1% candle range
        slip = bitget_sim.calculate_slippage_percent(0.01)
        expected = 0.0001 + 0.05 * 0.01  # 0.0006 = 0.06%
        assert slip == pytest.approx(expected, rel=1e-6)

    def test_volatile_market_higher_slippage(self, bitget_sim):
        # 3% candle range
        slip = bitget_sim.calculate_slippage_percent(0.03)
        expected = 0.0001 + 0.05 * 0.03  # 0.0016 = 0.16%
        assert slip == pytest.approx(expected, rel=1e-6)

    def test_extreme_volatility_capped(self, bitget_sim):
        # 20% candle range (extreme)
        slip = bitget_sim.calculate_slippage_percent(0.20)
        assert slip == 0.005  # Capped at 0.5%

    def test_zero_volatility(self, bitget_sim):
        slip = bitget_sim.calculate_slippage_percent(0.0)
        assert slip == 0.0001  # Base slippage only

    def test_entry_long_fills_higher(self, bitget_sim):
        fill = bitget_sim.apply_entry_slippage(50000.0, "long", 0.01)
        assert fill.effective_price > 50000.0

    def test_entry_short_fills_lower(self, bitget_sim):
        fill = bitget_sim.apply_entry_slippage(50000.0, "short", 0.01)
        assert fill.effective_price < 50000.0

    def test_exit_long_fills_lower(self, bitget_sim):
        fill = bitget_sim.apply_exit_slippage(55000.0, "long", 0.01)
        assert fill.effective_price < 55000.0

    def test_exit_short_fills_higher(self, bitget_sim):
        fill = bitget_sim.apply_exit_slippage(45000.0, "short", 0.01)
        assert fill.effective_price > 45000.0

    def test_trigger_exit_less_slippage(self, bitget_sim):
        market_fill = bitget_sim.apply_exit_slippage(50000.0, "long", 0.01, is_trigger=False)
        trigger_fill = bitget_sim.apply_exit_slippage(50000.0, "long", 0.01, is_trigger=True)
        # Trigger should have less slippage (closer to target)
        assert abs(trigger_fill.effective_price - 50000.0) < abs(market_fill.effective_price - 50000.0)

    def test_fill_result_has_correct_slippage_percent(self, bitget_sim):
        fill = bitget_sim.apply_entry_slippage(50000.0, "long", 0.01)
        expected_slip = 0.0001 + 0.05 * 0.01
        assert fill.slippage_percent == pytest.approx(expected_slip, rel=1e-6)


# ------------------------------------------------------------------ #
#  Fee Model Tests                                                    #
# ------------------------------------------------------------------ #

class TestFeeModel:
    def test_bitget_round_trip_fees(self, bitget_sim):
        fees = bitget_sim.calculate_fees(10000.0)
        # 0.06% taker x 2 = 0.12% round trip = $12
        assert fees == pytest.approx(12.0, rel=1e-6)

    def test_hyperliquid_round_trip_fees(self, hyperliquid_sim):
        fees = hyperliquid_sim.calculate_fees(10000.0)
        # 0.035% taker x 2 = 0.07% round trip = $7
        assert fees == pytest.approx(7.0, rel=1e-6)

    def test_binance_round_trip_fees(self, binance_sim):
        fees = binance_sim.calculate_fees(10000.0)
        # 0.04% taker x 2 = 0.08% round trip = $8
        assert fees == pytest.approx(8.0, rel=1e-6)

    def test_builder_fee_included(self):
        sim = ExecutionSimulator(exchange="hyperliquid", builder_fee_rate=0.0001)
        fees = sim.calculate_fees(10000.0)
        # Taker: 0.035% x 2 = $7, Builder: 0.01% x 2 = $2 → Total = $9
        assert fees == pytest.approx(9.0, rel=1e-6)

    def test_zero_position_zero_fees(self, bitget_sim):
        assert bitget_sim.calculate_fees(0.0) == 0.0

    def test_fees_scale_linearly(self, bitget_sim):
        fees_1k = bitget_sim.calculate_fees(1000.0)
        fees_10k = bitget_sim.calculate_fees(10000.0)
        assert fees_10k == pytest.approx(fees_1k * 10, rel=1e-6)


# ------------------------------------------------------------------ #
#  Funding Window Tests                                               #
# ------------------------------------------------------------------ #

class TestFundingWindows:
    def test_no_windows_short_hold(self):
        # 09:00 to 15:00 — no funding windows between
        entry = datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(entry, exit_dt) == 0

    def test_one_window_crosses_0800(self):
        # 07:30 to 08:30 — crosses 08:00
        entry = datetime(2024, 1, 15, 7, 30, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 8, 30, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(entry, exit_dt) == 1

    def test_two_windows_crosses_0800_and_1600(self):
        # 07:30 to 16:30 — crosses 08:00 and 16:00
        entry = datetime(2024, 1, 15, 7, 30, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 16, 30, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(entry, exit_dt) == 2

    def test_three_windows_full_day(self):
        # 00:01 to 23:59 — crosses 08:00, 16:00, and 00:00 next day? No.
        # Actually 00:01 Jan 15 to 23:59 Jan 15:
        # Windows: 08:00, 16:00 = 2 windows (00:00 is excluded since entry is after it)
        entry = datetime(2024, 1, 15, 0, 1, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 23, 59, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(entry, exit_dt) == 2

    def test_entry_exactly_on_boundary_excluded(self):
        # Entry at 08:00, exit at 16:00 — only 16:00 counts (entry boundary excluded)
        entry = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(entry, exit_dt) == 1

    def test_exit_exactly_on_boundary_included(self):
        # Entry at 07:00, exit at 08:00 — 08:00 is included (exit boundary included)
        entry = datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(entry, exit_dt) == 1

    def test_multi_day_hold(self):
        # Jan 15 10:00 to Jan 18 10:00 = 3 days
        # Windows: 16:00(15), 00:00(16), 08:00(16), 16:00(16), 00:00(17),
        #          08:00(17), 16:00(17), 00:00(18), 08:00(18) = 9 windows
        entry = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 18, 10, 0, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(entry, exit_dt) == 9

    def test_entry_equals_exit_returns_zero(self):
        ts = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(ts, ts) == 0

    def test_entry_after_exit_returns_zero(self):
        entry = datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 8, 0, 0, tzinfo=timezone.utc)
        assert ExecutionSimulator.count_funding_windows(entry, exit_dt) == 0


# ------------------------------------------------------------------ #
#  Funding Calculation Tests                                          #
# ------------------------------------------------------------------ #

class TestFundingCalculation:
    def test_no_funding_when_no_windows(self, bitget_sim):
        entry = datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
        funding = bitget_sim.calculate_funding(10000.0, 0.0001, entry, exit_dt)
        assert funding == 0.0

    def test_one_window_funding(self, bitget_sim):
        entry = datetime(2024, 1, 15, 7, 30, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 8, 30, 0, tzinfo=timezone.utc)
        # 1 window × $10000 × 0.01% = $1.0
        funding = bitget_sim.calculate_funding(10000.0, 0.0001, entry, exit_dt)
        assert funding == pytest.approx(1.0, rel=1e-6)

    def test_multi_window_funding(self, bitget_sim):
        entry = datetime(2024, 1, 15, 7, 30, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 16, 30, 0, tzinfo=timezone.utc)
        # 2 windows × $10000 × 0.01% = $2.0
        funding = bitget_sim.calculate_funding(10000.0, 0.0001, entry, exit_dt)
        assert funding == pytest.approx(2.0, rel=1e-6)

    def test_negative_funding_rate_uses_absolute(self, bitget_sim):
        entry = datetime(2024, 1, 15, 7, 30, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 15, 8, 30, 0, tzinfo=timezone.utc)
        funding = bitget_sim.calculate_funding(10000.0, -0.0001, entry, exit_dt)
        assert funding == pytest.approx(1.0, rel=1e-6)  # Absolute value

    def test_3_day_hold_9_windows(self, bitget_sim):
        entry = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 18, 10, 0, 0, tzinfo=timezone.utc)
        # 9 windows × $10000 × 0.01% = $9.0
        funding = bitget_sim.calculate_funding(10000.0, 0.0001, entry, exit_dt)
        assert funding == pytest.approx(9.0, rel=1e-6)


# ------------------------------------------------------------------ #
#  Complete PnL Tests                                                 #
# ------------------------------------------------------------------ #

class TestCompletePnL:
    def test_profitable_long_trade(self, bitget_sim):
        result = bitget_sim.calculate_trade_pnl(
            entry_price=50000.0,
            exit_price=52000.0,
            direction="long",
            position_value=1000.0,
            leverage=3,
            funding_rate=0.0001,
            entry_timestamp=datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc),
            exit_timestamp=datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc),
            entry_candle_range=0.01,  # 1% range
            exit_candle_range=0.01,
            exit_is_trigger=True,  # TP hit
        )

        assert result["pnl"] > 0
        assert result["pnl_percent"] > 0
        assert result["fees"] > 0
        assert result["funding_paid"] == 0.0  # No funding windows between 09:00-15:00
        assert result["net_pnl"] < result["pnl"]  # Fees reduce net PnL
        assert result["effective_entry"] > 50000.0  # Slippage makes entry worse
        assert result["effective_exit"] < 52000.0  # Slippage makes exit worse

    def test_losing_short_trade(self, bitget_sim):
        result = bitget_sim.calculate_trade_pnl(
            entry_price=50000.0,
            exit_price=52000.0,
            direction="short",
            position_value=1000.0,
            leverage=3,
            funding_rate=0.0001,
            entry_timestamp=datetime(2024, 1, 15, 7, 0, 0, tzinfo=timezone.utc),
            exit_timestamp=datetime(2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc),
            entry_candle_range=0.01,
            exit_candle_range=0.01,
            exit_is_trigger=True,  # SL hit
        )

        assert result["pnl"] < 0
        assert result["pnl_percent"] < 0
        assert result["fees"] > 0
        assert result["funding_paid"] > 0  # 1 window (08:00)
        assert result["net_pnl"] < result["pnl"]  # Fees + funding make it worse

    def test_fallback_when_no_timestamps(self, bitget_sim):
        result = bitget_sim.calculate_trade_pnl(
            entry_price=50000.0,
            exit_price=51000.0,
            direction="long",
            position_value=1000.0,
            leverage=3,
            funding_rate=0.0001,
            # No timestamps — triggers legacy fallback
            entry_candle_range=0.01,
            exit_candle_range=0.01,
        )

        assert result["funding_paid"] > 0  # Falls back to rate × 0.33
        assert result["fees"] > 0

    def test_leverage_amplifies_pnl(self, bitget_sim):
        base_result = bitget_sim.calculate_trade_pnl(
            entry_price=50000.0, exit_price=52000.0, direction="long",
            position_value=1000.0, leverage=1, funding_rate=0.0,
            entry_candle_range=0.0, exit_candle_range=0.0,
        )
        levered_result = bitget_sim.calculate_trade_pnl(
            entry_price=50000.0, exit_price=52000.0, direction="long",
            position_value=1000.0, leverage=3, funding_rate=0.0,
            entry_candle_range=0.0, exit_candle_range=0.0,
        )
        # With zero slippage/fees/funding, leverage should multiply PnL exactly
        assert levered_result["pnl"] == pytest.approx(base_result["pnl"] * 3, rel=1e-6)

    def test_fees_differ_by_exchange(self):
        bitget = ExecutionSimulator(exchange="bitget")
        hyper = ExecutionSimulator(exchange="hyperliquid")

        bitget_result = bitget.calculate_trade_pnl(
            entry_price=50000.0, exit_price=51000.0, direction="long",
            position_value=1000.0, leverage=3, funding_rate=0.0,
            entry_candle_range=0.0, exit_candle_range=0.0,
        )
        hyper_result = hyper.calculate_trade_pnl(
            entry_price=50000.0, exit_price=51000.0, direction="long",
            position_value=1000.0, leverage=3, funding_rate=0.0,
            entry_candle_range=0.0, exit_candle_range=0.0,
        )

        # Hyperliquid fees are lower, so net PnL should be higher
        assert hyper_result["fees"] < bitget_result["fees"]
        assert hyper_result["net_pnl"] > bitget_result["net_pnl"]


# ------------------------------------------------------------------ #
#  Comparison: Old vs New Cost Model                                  #
# ------------------------------------------------------------------ #

class TestOldVsNewComparison:
    """Verify that the new model produces more realistic costs than the old hardcoded model."""

    def test_old_model_underestimates_bitget_fees(self, bitget_sim):
        """Old model: 0.04% × 2 = 0.08%. Bitget actual: 0.06% × 2 = 0.12%."""
        position_value = 10000.0
        old_fees = position_value * (0.04 / 100) * 2  # $8
        new_fees = bitget_sim.calculate_fees(position_value)  # $12
        assert new_fees > old_fees
        assert new_fees == pytest.approx(12.0, rel=1e-6)

    def test_old_model_underestimates_multiday_funding(self, bitget_sim):
        """Old model charges rate × 1 for multi-day. Real: rate × 9 for 3 days."""
        position_value = 10000.0
        funding_rate = 0.0001  # 0.01% per 8h

        # Old model: multi-day = position × rate × 1 = $1
        old_funding = abs(position_value * funding_rate)

        # New model: 3-day hold = 9 windows × $1 = $9
        entry = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        exit_dt = datetime(2024, 1, 18, 10, 0, 0, tzinfo=timezone.utc)
        new_funding = bitget_sim.calculate_funding(position_value, funding_rate, entry, exit_dt)

        assert new_funding == pytest.approx(9.0, rel=1e-6)
        assert new_funding > old_funding  # 9× more accurate

    def test_volatile_market_higher_slippage_than_flat(self, bitget_sim):
        """Old model: flat 0.03%. New model: higher in volatile markets."""
        volatile_range = 0.03  # 3% candle range
        new_slip = bitget_sim.calculate_slippage_percent(volatile_range)
        old_slip = 0.0003  # 0.03%
        assert new_slip > old_slip

    def test_calm_market_lower_slippage_than_flat(self, bitget_sim):
        """New model: lower slippage in calm markets."""
        calm_range = 0.002  # 0.2% candle range
        new_slip = bitget_sim.calculate_slippage_percent(calm_range)
        old_slip = 0.0003  # 0.03%
        assert new_slip < old_slip
