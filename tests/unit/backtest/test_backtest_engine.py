"""
Comprehensive unit tests for the Backtest Engine and Strategy Adapter.

Covers:
- BacktestEngine initialization and reset
- Signal analysis components (leverage, sentiment, funding, OI, taker, etc.)
- Signal generation and direction logic
- Position sizing and target calculation
- Trade lifecycle (open, check exit, close)
- Daily stats and loss limits
- Profit Lock-In feature
- Full backtest run with various scenarios
- Strategy adapter (run_backtest_for_strategy, _calculate_sharpe)
- Error handling and edge cases
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import math
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestTrade,
    DailyBacktestStats,
    TradeDirection,
    TradeResult,
)
from src.backtest.historical_data import HistoricalDataPoint
from src.backtest.strategy_adapter import _calculate_sharpe, run_backtest_for_strategy


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _make_data_point(
    date_str="2024-06-01",
    fear_greed=50,
    long_short_ratio=1.0,
    funding_btc=0.0001,
    funding_eth=0.0001,
    btc_price=60000.0,
    eth_price=3000.0,
    btc_high=61000.0,
    btc_low=59000.0,
    eth_high=3100.0,
    eth_low=2900.0,
    btc_24h_change=0.0,
    eth_24h_change=0.0,
    open_interest_change_24h=0.0,
    taker_buy_sell_ratio=1.0,
    top_trader_long_short_ratio=1.0,
    funding_rate_bitget=0.0,
    stablecoin_flow_7d=0.0,
    dxy_index=103.0,
    historical_volatility=50.0,
) -> HistoricalDataPoint:
    """Create a HistoricalDataPoint with sane defaults for testing."""
    return HistoricalDataPoint(
        timestamp=datetime.strptime(date_str, "%Y-%m-%d"),
        date_str=date_str,
        fear_greed_index=fear_greed,
        fear_greed_classification="Neutral",
        long_short_ratio=long_short_ratio,
        funding_rate_btc=funding_btc,
        funding_rate_eth=funding_eth,
        btc_price=btc_price,
        eth_price=eth_price,
        btc_open=btc_price,
        eth_open=eth_price,
        btc_high=btc_high,
        btc_low=btc_low,
        eth_high=eth_high,
        eth_low=eth_low,
        btc_24h_change=btc_24h_change,
        eth_24h_change=eth_24h_change,
        open_interest_change_24h=open_interest_change_24h,
        taker_buy_sell_ratio=taker_buy_sell_ratio,
        top_trader_long_short_ratio=top_trader_long_short_ratio,
        funding_rate_bitget=funding_rate_bitget,
        stablecoin_flow_7d=stablecoin_flow_7d,
        dxy_index=dxy_index,
        historical_volatility=historical_volatility,
    )


# ---------------------------------------------------------------------------
#  BacktestConfig Tests
# ---------------------------------------------------------------------------


class TestBacktestConfig:
    """Tests for BacktestConfig defaults."""

    def test_default_values(self):
        config = BacktestConfig()
        assert config.starting_capital == 10000.0
        assert config.leverage == 3
        assert config.take_profit_percent == 3.5
        assert config.stop_loss_percent == 2.0
        assert config.max_trades_per_day == 3
        assert config.daily_loss_limit_percent == 5.0
        assert config.position_size_percent == 10.0
        assert config.trading_fee_percent == 0.04

    def test_custom_values(self):
        config = BacktestConfig(
            starting_capital=50000.0,
            leverage=5,
            take_profit_percent=5.0,
            stop_loss_percent=3.0,
        )
        assert config.starting_capital == 50000.0
        assert config.leverage == 5
        assert config.take_profit_percent == 5.0
        assert config.stop_loss_percent == 3.0


# ---------------------------------------------------------------------------
#  BacktestTrade Tests
# ---------------------------------------------------------------------------


class TestBacktestTrade:
    """Tests for BacktestTrade dataclass."""

    def test_to_dict(self):
        trade = BacktestTrade(
            id=1,
            symbol="BTC",
            direction=TradeDirection.LONG,
            entry_date="2024-01-01",
            entry_price=50000.0,
            position_size=0.1,
            position_value=1000.0,
            leverage=3,
            confidence=80,
            reason="Test reason",
            take_profit_price=51750.0,
            stop_loss_price=49000.0,
        )
        d = trade.to_dict()
        assert d["id"] == 1
        assert d["symbol"] == "BTC"
        assert d["direction"] == "long"
        assert d["entry_price"] == 50000.0
        assert d["result"] == "open"
        assert d["take_profit_price"] == 51750.0

    def test_default_values(self):
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.SHORT,
            entry_date="2024-01-01", entry_price=50000.0,
            position_size=0.1, position_value=1000.0,
            leverage=3, confidence=70, reason="test",
        )
        assert trade.result == TradeResult.OPEN
        assert trade.pnl == 0.0
        assert trade.net_pnl == 0.0
        assert trade.exit_date is None
        assert trade.exit_price is None


# ---------------------------------------------------------------------------
#  BacktestEngine Initialization Tests
# ---------------------------------------------------------------------------


class TestBacktestEngineInit:
    """Tests for BacktestEngine initialization and reset."""

    def test_init_default_config(self):
        engine = BacktestEngine()
        assert engine.config.starting_capital == 10000.0
        assert engine.capital == 10000.0
        assert engine.trades == []
        assert engine.open_positions == {}
        assert engine.trade_counter == 0

    def test_init_custom_config(self):
        config = BacktestConfig(starting_capital=25000.0, leverage=5)
        engine = BacktestEngine(config)
        assert engine.config.starting_capital == 25000.0
        assert engine.config.leverage == 5
        assert engine.capital == 25000.0

    def test_reset_clears_state(self):
        engine = BacktestEngine()
        engine.capital = 5000.0
        engine.trade_counter = 10
        engine.daily_pnl = 200.0
        engine.current_date = "2024-01-15"
        engine.open_positions = {"BTC": MagicMock()}
        engine.daily_stats = [MagicMock()]

        engine.reset()

        assert engine.capital == 10000.0
        assert engine.trade_counter == 0
        assert engine.daily_pnl == 0.0
        assert engine.current_date == ""
        assert engine.open_positions == {}
        assert engine.daily_stats == []


# ---------------------------------------------------------------------------
#  Leverage Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeLeverage:
    """Tests for _analyze_leverage."""

    def test_crowded_longs_returns_short(self):
        engine = BacktestEngine()
        direction, confidence, reason = engine._analyze_leverage(3.0)
        assert direction == TradeDirection.SHORT
        assert confidence > 0
        assert "Crowded Longs" in reason

    def test_crowded_shorts_returns_long(self):
        engine = BacktestEngine()
        direction, confidence, reason = engine._analyze_leverage(0.3)
        assert direction == TradeDirection.LONG
        assert confidence > 0
        assert "Crowded Shorts" in reason

    def test_neutral_ratio_returns_none(self):
        engine = BacktestEngine()
        direction, confidence, reason = engine._analyze_leverage(1.0)
        assert direction is None
        assert confidence == 0
        assert "Neutral" in reason

    def test_confidence_capped_at_30(self):
        engine = BacktestEngine()
        # Extremely high ratio to test cap
        direction, confidence, _ = engine._analyze_leverage(100.0)
        assert confidence <= 30


# ---------------------------------------------------------------------------
#  Sentiment Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeSentiment:
    """Tests for _analyze_sentiment."""

    def test_extreme_greed_returns_short(self):
        engine = BacktestEngine()
        direction, confidence, reason = engine._analyze_sentiment(90)
        assert direction == TradeDirection.SHORT
        assert confidence > 0
        assert "Extreme Greed" in reason

    def test_extreme_fear_returns_long(self):
        engine = BacktestEngine()
        direction, confidence, reason = engine._analyze_sentiment(10)
        assert direction == TradeDirection.LONG
        assert confidence > 0
        assert "Extreme Fear" in reason

    def test_neutral_sentiment(self):
        engine = BacktestEngine()
        direction, confidence, reason = engine._analyze_sentiment(50)
        assert direction is None
        assert confidence == 0
        assert "Neutral" in reason

    def test_confidence_capped_at_20(self):
        engine = BacktestEngine()
        _, confidence, _ = engine._analyze_sentiment(100)
        assert confidence <= 20


# ---------------------------------------------------------------------------
#  Funding Rate Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeFundingRate:
    """Tests for _analyze_funding_rate."""

    def test_high_funding_short_direction_boosts(self):
        engine = BacktestEngine()
        adj, reason = engine._analyze_funding_rate(0.001, TradeDirection.SHORT)
        assert adj == 20
        assert "High Funding" in reason

    def test_high_funding_long_direction_penalizes(self):
        engine = BacktestEngine()
        adj, reason = engine._analyze_funding_rate(0.001, TradeDirection.LONG)
        assert adj == -10

    def test_negative_funding_long_direction_boosts(self):
        engine = BacktestEngine()
        adj, reason = engine._analyze_funding_rate(-0.001, TradeDirection.LONG)
        assert adj == 20
        assert "Negative Funding" in reason

    def test_negative_funding_short_direction_penalizes(self):
        engine = BacktestEngine()
        adj, reason = engine._analyze_funding_rate(-0.001, TradeDirection.SHORT)
        assert adj == -10

    def test_neutral_funding(self):
        engine = BacktestEngine()
        adj, reason = engine._analyze_funding_rate(0.0001, TradeDirection.LONG)
        assert adj == 0
        assert "Neutral" in reason


# ---------------------------------------------------------------------------
#  Open Interest Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeOpenInterest:
    """Tests for _analyze_open_interest."""

    def test_flat_oi_returns_zero(self):
        engine = BacktestEngine()
        data = _make_data_point(open_interest_change_24h=0.5, btc_24h_change=1.0)
        adj, reason = engine._analyze_open_interest(data, TradeDirection.LONG)
        assert adj == 0
        assert "Flat" in reason

    def test_rising_oi_price_up_short_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(open_interest_change_24h=5.0, btc_24h_change=2.0)
        adj, reason = engine._analyze_open_interest(data, TradeDirection.SHORT)
        assert adj == 10
        assert "crowded longs" in reason

    def test_rising_oi_price_down_long_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(open_interest_change_24h=5.0, btc_24h_change=-2.0)
        adj, reason = engine._analyze_open_interest(data, TradeDirection.LONG)
        assert adj == 10
        assert "crowded shorts" in reason

    def test_falling_oi_reduces_confidence(self):
        engine = BacktestEngine()
        data = _make_data_point(open_interest_change_24h=-5.0, btc_24h_change=0.0)
        adj, reason = engine._analyze_open_interest(data, TradeDirection.LONG)
        assert adj == -5
        assert "deleveraging" in reason


# ---------------------------------------------------------------------------
#  Taker Volume Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeTakerVolume:
    """Tests for _analyze_taker_volume."""

    def test_heavy_buying_short_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(taker_buy_sell_ratio=1.5)
        adj, _ = engine._analyze_taker_volume(data, TradeDirection.SHORT)
        assert adj == 8

    def test_heavy_buying_long_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(taker_buy_sell_ratio=1.5)
        adj, _ = engine._analyze_taker_volume(data, TradeDirection.LONG)
        assert adj == -5

    def test_heavy_selling_long_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(taker_buy_sell_ratio=0.5)
        adj, _ = engine._analyze_taker_volume(data, TradeDirection.LONG)
        assert adj == 8

    def test_balanced_taker(self):
        engine = BacktestEngine()
        data = _make_data_point(taker_buy_sell_ratio=1.0)
        adj, reason = engine._analyze_taker_volume(data, TradeDirection.LONG)
        assert adj == 0
        assert "Balanced" in reason

    def test_mild_buy_short_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(taker_buy_sell_ratio=1.15)
        adj, reason = engine._analyze_taker_volume(data, TradeDirection.SHORT)
        assert adj == 3
        assert "Mild Buy" in reason

    def test_mild_sell_long_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(taker_buy_sell_ratio=0.85)
        adj, reason = engine._analyze_taker_volume(data, TradeDirection.LONG)
        assert adj == 3
        assert "Mild Sell" in reason


# ---------------------------------------------------------------------------
#  Top Traders Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeTopTraders:
    """Tests for _analyze_top_traders."""

    def test_top_traders_heavily_long_confirms_long(self):
        engine = BacktestEngine()
        data = _make_data_point(top_trader_long_short_ratio=2.0)
        adj, reason = engine._analyze_top_traders(data, TradeDirection.LONG)
        assert adj == 5
        assert "Long" in reason

    def test_top_traders_heavily_long_warns_short(self):
        engine = BacktestEngine()
        data = _make_data_point(top_trader_long_short_ratio=2.0)
        adj, _ = engine._analyze_top_traders(data, TradeDirection.SHORT)
        assert adj == -5

    def test_top_traders_heavily_short_confirms_short(self):
        engine = BacktestEngine()
        data = _make_data_point(top_trader_long_short_ratio=0.5)
        adj, _ = engine._analyze_top_traders(data, TradeDirection.SHORT)
        assert adj == 5

    def test_top_traders_neutral(self):
        engine = BacktestEngine()
        data = _make_data_point(top_trader_long_short_ratio=1.0)
        adj, reason = engine._analyze_top_traders(data, TradeDirection.LONG)
        assert adj == 0
        assert "Neutral" in reason


# ---------------------------------------------------------------------------
#  Funding Divergence Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeFundingDivergence:
    """Tests for _analyze_funding_divergence."""

    def test_both_zero_returns_na(self):
        engine = BacktestEngine()
        data = _make_data_point(funding_btc=0.0, funding_rate_bitget=0.0)
        adj, reason = engine._analyze_funding_divergence(data, TradeDirection.LONG)
        assert adj == 0
        assert "N/A" in reason

    def test_large_divergence(self):
        engine = BacktestEngine()
        data = _make_data_point(funding_btc=0.001, funding_rate_bitget=0.0001)
        adj, reason = engine._analyze_funding_divergence(data, TradeDirection.LONG)
        assert adj == 5
        assert "Divergence" in reason

    def test_aligned_funding(self):
        engine = BacktestEngine()
        data = _make_data_point(funding_btc=0.0001, funding_rate_bitget=0.0001)
        adj, reason = engine._analyze_funding_divergence(data, TradeDirection.LONG)
        assert adj == 0
        assert "Aligned" in reason


# ---------------------------------------------------------------------------
#  Stablecoin Flows Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeStablecoinFlows:
    """Tests for _analyze_stablecoin_flows."""

    def test_neutral_flow(self):
        engine = BacktestEngine()
        data = _make_data_point(stablecoin_flow_7d=100_000_000)
        adj, reason = engine._analyze_stablecoin_flows(data, TradeDirection.LONG)
        assert adj == 0
        assert "Neutral" in reason

    def test_large_inflow_long_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(stablecoin_flow_7d=3_000_000_000)
        adj, reason = engine._analyze_stablecoin_flows(data, TradeDirection.LONG)
        assert adj == 5
        assert "Inflow" in reason

    def test_large_inflow_short_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(stablecoin_flow_7d=3_000_000_000)
        adj, _ = engine._analyze_stablecoin_flows(data, TradeDirection.SHORT)
        assert adj == -3

    def test_large_outflow_short_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(stablecoin_flow_7d=-3_000_000_000)
        adj, reason = engine._analyze_stablecoin_flows(data, TradeDirection.SHORT)
        assert adj == 5
        assert "Outflow" in reason

    def test_mild_inflow_long(self):
        engine = BacktestEngine()
        data = _make_data_point(stablecoin_flow_7d=800_000_000)
        adj, reason = engine._analyze_stablecoin_flows(data, TradeDirection.LONG)
        assert adj == 3
        assert "Mild Inflow" in reason

    def test_mild_outflow_short(self):
        engine = BacktestEngine()
        data = _make_data_point(stablecoin_flow_7d=-800_000_000)
        adj, reason = engine._analyze_stablecoin_flows(data, TradeDirection.SHORT)
        assert adj == 3
        assert "Mild Outflow" in reason


# ---------------------------------------------------------------------------
#  Volatility Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeVolatility:
    """Tests for _analyze_volatility."""

    def test_extreme_volatility(self):
        engine = BacktestEngine()
        data = _make_data_point(historical_volatility=120)
        adj, reason = engine._analyze_volatility(data)
        assert adj == -10
        assert "Extreme" in reason

    def test_high_volatility(self):
        engine = BacktestEngine()
        data = _make_data_point(historical_volatility=80)
        adj, reason = engine._analyze_volatility(data)
        assert adj == -5
        assert "High" in reason

    def test_low_volatility(self):
        engine = BacktestEngine()
        data = _make_data_point(historical_volatility=20)
        adj, reason = engine._analyze_volatility(data)
        assert adj == 3
        assert "Low" in reason

    def test_normal_volatility(self):
        engine = BacktestEngine()
        data = _make_data_point(historical_volatility=50)
        adj, reason = engine._analyze_volatility(data)
        assert adj == 0
        assert "Normal" in reason


# ---------------------------------------------------------------------------
#  Macro Analysis Tests
# ---------------------------------------------------------------------------


class TestAnalyzeMacro:
    """Tests for _analyze_macro."""

    def test_dxy_zero_returns_na(self):
        engine = BacktestEngine()
        data = _make_data_point(dxy_index=0)
        adj, reason = engine._analyze_macro(data, TradeDirection.LONG)
        assert adj == 0
        assert "N/A" in reason

    def test_strong_usd_short_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(dxy_index=110)
        adj, reason = engine._analyze_macro(data, TradeDirection.SHORT)
        assert adj == 3
        assert "Strong USD" in reason

    def test_strong_usd_long_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(dxy_index=110)
        adj, _ = engine._analyze_macro(data, TradeDirection.LONG)
        assert adj == -3

    def test_weak_usd_long_direction(self):
        engine = BacktestEngine()
        data = _make_data_point(dxy_index=98)
        adj, reason = engine._analyze_macro(data, TradeDirection.LONG)
        assert adj == 3
        assert "Weak USD" in reason

    def test_neutral_usd(self):
        engine = BacktestEngine()
        data = _make_data_point(dxy_index=103)
        adj, reason = engine._analyze_macro(data, TradeDirection.LONG)
        assert adj == 0
        assert "Neutral" in reason


# ---------------------------------------------------------------------------
#  Signal Generation Tests
# ---------------------------------------------------------------------------


class TestGenerateSignal:
    """Tests for _generate_signal."""

    def test_alignment_of_leverage_and_sentiment_long(self):
        """Both leverage and sentiment agree on LONG -> high confidence."""
        engine = BacktestEngine()
        data = _make_data_point(
            long_short_ratio=0.3,  # crowded shorts -> LONG
            fear_greed=10,         # extreme fear -> LONG
        )
        direction, confidence, reason = engine._generate_signal(data, "BTC")
        assert direction == TradeDirection.LONG
        assert confidence >= engine.config.high_confidence_min
        assert "ALIGNMENT" in reason

    def test_alignment_of_leverage_and_sentiment_short(self):
        """Both leverage and sentiment agree on SHORT -> high confidence."""
        engine = BacktestEngine()
        data = _make_data_point(
            long_short_ratio=3.0,  # crowded longs -> SHORT
            fear_greed=90,         # extreme greed -> SHORT
        )
        direction, confidence, reason = engine._generate_signal(data, "BTC")
        assert direction == TradeDirection.SHORT
        assert confidence >= engine.config.high_confidence_min
        assert "ALIGNMENT" in reason

    def test_conflict_follows_leverage(self):
        """Leverage and sentiment disagree -> follow leverage, cap confidence."""
        engine = BacktestEngine()
        data = _make_data_point(
            long_short_ratio=3.0,  # crowded longs -> SHORT
            fear_greed=10,         # extreme fear -> LONG
        )
        direction, confidence, reason = engine._generate_signal(data, "BTC")
        assert direction == TradeDirection.SHORT
        assert confidence <= 70
        assert "CONFLICT" in reason

    def test_only_leverage_signal(self):
        engine = BacktestEngine()
        data = _make_data_point(
            long_short_ratio=3.0,  # crowded longs -> SHORT
            fear_greed=50,         # neutral
        )
        direction, _, _ = engine._generate_signal(data, "BTC")
        assert direction == TradeDirection.SHORT

    def test_only_sentiment_signal(self):
        engine = BacktestEngine()
        data = _make_data_point(
            long_short_ratio=1.0,  # neutral
            fear_greed=10,         # extreme fear -> LONG
        )
        direction, _, _ = engine._generate_signal(data, "BTC")
        assert direction == TradeDirection.LONG

    def test_no_primary_signal_uses_trend(self):
        """Neither leverage nor sentiment signal -> fall back to price trend."""
        engine = BacktestEngine()
        data = _make_data_point(
            long_short_ratio=1.0,
            fear_greed=50,
            btc_24h_change=2.0,
        )
        direction, confidence, reason = engine._generate_signal(data, "BTC")
        assert direction == TradeDirection.LONG
        assert "Trend" in reason

    def test_no_primary_signal_negative_trend(self):
        engine = BacktestEngine()
        data = _make_data_point(
            long_short_ratio=1.0,
            fear_greed=50,
            btc_24h_change=-2.0,
        )
        direction, _, _ = engine._generate_signal(data, "BTC")
        assert direction == TradeDirection.SHORT

    def test_confidence_clamped_to_range(self):
        engine = BacktestEngine()
        data = _make_data_point(
            long_short_ratio=0.1,
            fear_greed=5,
            funding_btc=-0.01,
            taker_buy_sell_ratio=0.3,
            stablecoin_flow_7d=5_000_000_000,
            historical_volatility=20,
            dxy_index=95,
        )
        _, confidence, _ = engine._generate_signal(data, "BTC")
        assert engine.config.low_confidence_min <= confidence <= 95

    def test_eth_symbol_uses_eth_fields(self):
        engine = BacktestEngine()
        data = _make_data_point(
            funding_eth=0.002,
            eth_24h_change=5.0,
            long_short_ratio=1.0,
            fear_greed=50,
        )
        direction, _, _ = engine._generate_signal(data, "ETH")
        # Should still produce a valid direction
        assert direction in (TradeDirection.LONG, TradeDirection.SHORT)


# ---------------------------------------------------------------------------
#  Position Sizing Tests
# ---------------------------------------------------------------------------


class TestCalculatePositionSize:
    """Tests for _calculate_position_size."""

    def test_high_confidence_multiplier(self):
        engine = BacktestEngine()
        pct, usdt = engine._calculate_position_size(90)
        assert pct == 10.0 * 1.5  # 15.0
        assert usdt == 10000.0 * (15.0 / 100)

    def test_medium_high_confidence_multiplier(self):
        engine = BacktestEngine()
        pct, _ = engine._calculate_position_size(80)
        assert pct == 10.0 * 1.25

    def test_medium_confidence_multiplier(self):
        engine = BacktestEngine()
        pct, _ = engine._calculate_position_size(70)
        assert pct == 10.0 * 1.0

    def test_low_confidence_multiplier(self):
        engine = BacktestEngine()
        pct, _ = engine._calculate_position_size(60)
        assert pct == 10.0 * 0.75

    def test_very_low_confidence_multiplier(self):
        engine = BacktestEngine()
        pct, _ = engine._calculate_position_size(40)
        assert pct == 10.0 * 0.5

    def test_position_capped_at_25_percent(self):
        config = BacktestConfig(position_size_percent=20.0)
        engine = BacktestEngine(config)
        pct, _ = engine._calculate_position_size(90)
        assert pct == 25.0


# ---------------------------------------------------------------------------
#  Target Calculation Tests
# ---------------------------------------------------------------------------


class TestCalculateTargets:
    """Tests for _calculate_targets."""

    def test_long_take_profit_above_entry(self):
        engine = BacktestEngine()
        tp, sl = engine._calculate_targets(TradeDirection.LONG, 50000.0)
        assert tp > 50000.0
        assert sl < 50000.0

    def test_short_take_profit_below_entry(self):
        engine = BacktestEngine()
        tp, sl = engine._calculate_targets(TradeDirection.SHORT, 50000.0)
        assert tp < 50000.0
        assert sl > 50000.0

    def test_long_values_match_config(self):
        engine = BacktestEngine()
        tp, sl = engine._calculate_targets(TradeDirection.LONG, 100000.0)
        expected_tp = 100000.0 * (1 + 3.5 / 100)
        expected_sl = 100000.0 * (1 - 2.0 / 100)
        assert tp == pytest.approx(expected_tp, rel=1e-9)
        assert sl == pytest.approx(expected_sl, rel=1e-9)

    def test_short_values_match_config(self):
        engine = BacktestEngine()
        tp, sl = engine._calculate_targets(TradeDirection.SHORT, 100000.0)
        expected_tp = 100000.0 * (1 - 3.5 / 100)
        expected_sl = 100000.0 * (1 + 2.0 / 100)
        assert tp == pytest.approx(expected_tp, rel=1e-9)
        assert sl == pytest.approx(expected_sl, rel=1e-9)


# ---------------------------------------------------------------------------
#  Dynamic Loss Limit / Profit Lock-In Tests
# ---------------------------------------------------------------------------


class TestDynamicLossLimit:
    """Tests for _get_dynamic_loss_limit."""

    def test_profit_lock_disabled(self):
        config = BacktestConfig(enable_profit_lock=False)
        engine = BacktestEngine(config)
        engine.daily_pnl = 500.0
        assert engine._get_dynamic_loss_limit() == config.daily_loss_limit_percent

    def test_no_daily_profit(self):
        engine = BacktestEngine()
        engine.daily_pnl = 0.0
        assert engine._get_dynamic_loss_limit() == engine.config.daily_loss_limit_percent

    def test_negative_daily_pnl(self):
        engine = BacktestEngine()
        engine.daily_pnl = -100.0
        assert engine._get_dynamic_loss_limit() == engine.config.daily_loss_limit_percent

    def test_with_positive_daily_pnl_locks_profit(self):
        engine = BacktestEngine()
        # 2% daily return on $10,000 -> max_allowed_loss = 2.0 - 0.5 = 1.5
        # new_limit = min(5.0, 1.5) = 1.5 which is < 5.0
        engine.daily_pnl = 200.0
        limit = engine._get_dynamic_loss_limit()
        assert limit < engine.config.daily_loss_limit_percent
        assert limit >= 0.5  # minimum floor


# ---------------------------------------------------------------------------
#  Can Trade Tests
# ---------------------------------------------------------------------------


class TestCanTrade:
    """Tests for _can_trade."""

    def test_can_trade_initially(self):
        engine = BacktestEngine()
        can, reason = engine._can_trade()
        assert can is True
        assert reason == "OK"

    def test_cannot_trade_daily_limit_reached(self):
        engine = BacktestEngine()
        engine.daily_trades_count = engine.config.max_trades_per_day
        can, reason = engine._can_trade()
        assert can is False
        assert "Daily trade limit" in reason

    def test_cannot_trade_loss_limit_reached(self):
        engine = BacktestEngine()
        engine.daily_pnl = -600.0  # -6% on $10,000
        can, reason = engine._can_trade()
        assert can is False
        assert "Loss limit" in reason


# ---------------------------------------------------------------------------
#  Check Exit Tests
# ---------------------------------------------------------------------------


class TestCheckExit:
    """Tests for _check_exit."""

    def test_long_take_profit_hit(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=60000.0,
            position_size=0.1, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
            take_profit_price=62000.0, stop_loss_price=58000.0,
        )
        data = _make_data_point(btc_high=63000.0, btc_low=59500.0)
        next_data = _make_data_point(date_str="2024-06-02")

        should_exit, result, exit_price = engine._check_exit(trade, data, next_data)
        assert should_exit is True
        assert result == TradeResult.TAKE_PROFIT
        assert exit_price == 62000.0

    def test_long_stop_loss_hit(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=60000.0,
            position_size=0.1, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
            take_profit_price=62000.0, stop_loss_price=58000.0,
        )
        data = _make_data_point(btc_high=61000.0, btc_low=57000.0)
        next_data = _make_data_point(date_str="2024-06-02")

        should_exit, result, exit_price = engine._check_exit(trade, data, next_data)
        assert should_exit is True
        assert result == TradeResult.STOP_LOSS
        assert exit_price == 58000.0

    def test_short_take_profit_hit(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.SHORT,
            entry_date="2024-01-01", entry_price=60000.0,
            position_size=0.1, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
            take_profit_price=57000.0, stop_loss_price=63000.0,
        )
        data = _make_data_point(btc_high=60500.0, btc_low=56000.0)
        next_data = _make_data_point(date_str="2024-06-02")

        should_exit, result, exit_price = engine._check_exit(trade, data, next_data)
        assert should_exit is True
        assert result == TradeResult.TAKE_PROFIT
        assert exit_price == 57000.0

    def test_short_stop_loss_hit(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.SHORT,
            entry_date="2024-01-01", entry_price=60000.0,
            position_size=0.1, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
            take_profit_price=57000.0, stop_loss_price=63000.0,
        )
        data = _make_data_point(btc_high=64000.0, btc_low=59000.0)
        next_data = _make_data_point(date_str="2024-06-02")

        should_exit, result, exit_price = engine._check_exit(trade, data, next_data)
        assert should_exit is True
        assert result == TradeResult.STOP_LOSS
        assert exit_price == 63000.0

    def test_no_exit_within_range(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=60000.0,
            position_size=0.1, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
            take_profit_price=62000.0, stop_loss_price=58000.0,
        )
        data = _make_data_point(btc_high=61500.0, btc_low=58500.0)
        next_data = _make_data_point(date_str="2024-06-02")

        should_exit, result, _ = engine._check_exit(trade, data, next_data)
        assert should_exit is False
        assert result == TradeResult.OPEN

    def test_time_exit_when_no_next_data(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=60000.0,
            position_size=0.1, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
            take_profit_price=62000.0, stop_loss_price=58000.0,
        )
        data = _make_data_point(btc_price=60500.0, btc_high=61000.0, btc_low=59500.0)

        should_exit, result, exit_price = engine._check_exit(trade, data, None)
        assert should_exit is True
        assert result == TradeResult.TIME_EXIT
        assert exit_price == 60500.0

    def test_eth_symbol_uses_eth_prices(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="ETH", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=3000.0,
            position_size=1.0, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
            take_profit_price=3200.0, stop_loss_price=2800.0,
        )
        data = _make_data_point(eth_high=3300.0, eth_low=2900.0)
        next_data = _make_data_point(date_str="2024-06-02")

        should_exit, result, exit_price = engine._check_exit(trade, data, next_data)
        assert should_exit is True
        assert result == TradeResult.TAKE_PROFIT
        assert exit_price == 3200.0


# ---------------------------------------------------------------------------
#  Close Trade Tests
# ---------------------------------------------------------------------------


class TestCloseTrade:
    """Tests for _close_trade."""

    def test_close_long_trade_profit(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=50000.0,
            position_size=0.06, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
        )
        engine.open_positions["BTC"] = trade

        engine._close_trade(trade, "2024-01-02", 52000.0, TradeResult.TAKE_PROFIT, 0.0001)

        assert trade.exit_date == "2024-01-02"
        assert trade.exit_price == 52000.0
        assert trade.result == TradeResult.TAKE_PROFIT
        assert trade.pnl > 0
        assert trade.pnl_percent > 0
        assert trade.fees > 0
        assert trade.net_pnl > 0  # pnl should exceed fees in this case
        assert "BTC" not in engine.open_positions

    def test_close_short_trade_profit(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.SHORT,
            entry_date="2024-01-01", entry_price=50000.0,
            position_size=0.06, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
        )
        engine.open_positions["BTC"] = trade

        engine._close_trade(trade, "2024-01-02", 48000.0, TradeResult.TAKE_PROFIT, 0.0001)

        assert trade.pnl > 0
        assert trade.pnl_percent > 0
        assert "BTC" not in engine.open_positions

    def test_close_trade_loss(self):
        engine = BacktestEngine()
        initial_capital = engine.capital
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=50000.0,
            position_size=0.06, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
        )
        engine.open_positions["BTC"] = trade

        engine._close_trade(trade, "2024-01-02", 48000.0, TradeResult.STOP_LOSS, 0.0001)

        assert trade.pnl < 0
        assert trade.net_pnl < 0
        assert engine.capital < initial_capital
        assert engine.daily_pnl < 0

    def test_close_trade_updates_capital_and_daily_pnl(self):
        engine = BacktestEngine()
        trade = BacktestTrade(
            id=1, symbol="ETH", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=3000.0,
            position_size=1.0, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
        )
        engine.open_positions["ETH"] = trade

        initial_capital = engine.capital
        engine._close_trade(trade, "2024-01-02", 3100.0, TradeResult.TAKE_PROFIT, 0.0001)

        assert engine.capital != initial_capital
        assert engine.daily_pnl == trade.net_pnl

    def test_fees_calculated_correctly(self):
        config = BacktestConfig(trading_fee_percent=0.06)
        engine = BacktestEngine(config)
        trade = BacktestTrade(
            id=1, symbol="BTC", direction=TradeDirection.LONG,
            entry_date="2024-01-01", entry_price=50000.0,
            position_size=0.06, position_value=1000.0,
            leverage=3, confidence=80, reason="test",
        )
        engine.open_positions["BTC"] = trade

        engine._close_trade(trade, "2024-01-02", 50000.0, TradeResult.TIME_EXIT, 0.0)

        # Fees = position_value * fee_pct * 2 (entry + exit)
        expected_fees = 1000.0 * (0.06 / 100) * 2
        assert trade.fees == pytest.approx(expected_fees)


# ---------------------------------------------------------------------------
#  Save Daily Stats Tests
# ---------------------------------------------------------------------------


class TestSaveDailyStats:
    """Tests for _save_daily_stats."""

    def test_save_daily_stats_no_date_skips(self):
        engine = BacktestEngine()
        engine.current_date = ""
        engine._save_daily_stats()
        assert len(engine.daily_stats) == 0

    def test_save_daily_stats_records(self):
        engine = BacktestEngine()
        engine.current_date = "2024-06-01"
        engine.daily_pnl = 50.0
        engine.daily_trades_count = 2

        engine._save_daily_stats()

        assert len(engine.daily_stats) == 1
        stats = engine.daily_stats[0]
        assert stats.date == "2024-06-01"
        assert stats.trades_opened == 2
        assert stats.ending_balance == engine.capital
        assert stats.daily_pnl == 50.0


# ---------------------------------------------------------------------------
#  Full Backtest Run Tests
# ---------------------------------------------------------------------------


class TestBacktestRun:
    """Tests for the full run() method."""

    @patch("src.backtest.engine.logger")
    def test_run_empty_data_returns_empty_result(self, mock_logger):
        engine = BacktestEngine()
        result = engine.run([])
        assert result.total_trades == 0
        assert result.starting_capital == 0

    @patch("src.backtest.engine.logger")
    def test_run_single_data_point(self, mock_logger):
        engine = BacktestEngine()
        data = [_make_data_point(
            date_str="2024-06-01",
            long_short_ratio=3.0,
            fear_greed=90,
            btc_price=60000.0,
            btc_high=62000.0,
            btc_low=58000.0,
        )]
        result = engine.run(data)
        # With a single data point, all open trades get time-exited
        assert result is not None
        assert result.starting_capital == 10000.0

    @patch("src.backtest.engine.logger")
    def test_run_multiple_days_creates_daily_stats(self, mock_logger):
        engine = BacktestEngine()
        data = [
            _make_data_point(date_str="2024-06-01"),
            _make_data_point(date_str="2024-06-02"),
            _make_data_point(date_str="2024-06-03"),
        ]
        result = engine.run(data)
        assert len(result.daily_stats) >= 2

    @patch("src.backtest.engine.logger")
    def test_run_opens_and_closes_trades(self, mock_logger):
        """Create conditions that generate a trade and then trigger its exit."""
        config = BacktestConfig(
            take_profit_percent=5.0,
            stop_loss_percent=3.0,
        )
        engine = BacktestEngine(config)

        data = [
            _make_data_point(
                date_str="2024-06-01",
                long_short_ratio=3.0,
                fear_greed=90,
                btc_price=60000.0,
                btc_high=62000.0,
                btc_low=58000.0,
                eth_price=3000.0,
                eth_high=3100.0,
                eth_low=2900.0,
            ),
            _make_data_point(
                date_str="2024-06-02",
                btc_price=56000.0,
                btc_high=60500.0,
                btc_low=55000.0,
                eth_price=2800.0,
                eth_high=3050.0,
                eth_low=2700.0,
            ),
            _make_data_point(
                date_str="2024-06-03",
                btc_price=55000.0,
                btc_high=56000.0,
                btc_low=54000.0,
                eth_price=2700.0,
                eth_high=2850.0,
                eth_low=2600.0,
            ),
        ]
        result = engine.run(data)
        assert result.total_trades >= 0
        # All trades should be closed by end
        assert len(engine.open_positions) == 0

    @patch("src.backtest.engine.logger")
    def test_run_skips_zero_price_entries(self, mock_logger):
        engine = BacktestEngine()
        data = [
            _make_data_point(date_str="2024-06-01", btc_price=0.0, eth_price=0.0),
            _make_data_point(date_str="2024-06-02", btc_price=60000.0, eth_price=3000.0),
        ]
        result = engine.run(data)
        assert result is not None

    @patch("src.backtest.engine.logger")
    def test_run_respects_max_trades_per_day(self, mock_logger):
        config = BacktestConfig(max_trades_per_day=1)
        engine = BacktestEngine(config)
        data = [
            _make_data_point(
                date_str="2024-06-01",
                long_short_ratio=3.0,
                fear_greed=90,
            ),
        ]
        engine.run(data)
        # Should have opened at most 1 trade on that day
        day_trades = [t for t in engine.trades if t.entry_date == "2024-06-01"]
        assert len(day_trades) <= 1

    @patch("src.backtest.engine.logger")
    def test_run_skips_when_position_too_small(self, mock_logger):
        """When capital is too low, position_usdt < 10 and trades are skipped."""
        config = BacktestConfig(
            starting_capital=50.0,
            position_size_percent=1.0,  # 1% of $50 = $0.50, well below $10 minimum
        )
        engine = BacktestEngine(config)
        data = [
            _make_data_point(
                date_str="2024-06-01",
                long_short_ratio=3.0,
                fear_greed=90,
            ),
            _make_data_point(
                date_str="2024-06-02",
                long_short_ratio=3.0,
                fear_greed=90,
            ),
        ]
        result = engine.run(data)
        assert result.total_trades == 0

    @patch("src.backtest.engine.logger")
    def test_run_doesnt_open_when_position_exists(self, mock_logger):
        """Should not open a second BTC position if one is already open."""
        engine = BacktestEngine()
        data = [
            _make_data_point(
                date_str="2024-06-01",
                long_short_ratio=3.0,
                fear_greed=90,
                btc_high=61000.0,
                btc_low=59000.0,
            ),
            # Price stays in range so TP/SL not hit
            _make_data_point(
                date_str="2024-06-01",
                long_short_ratio=3.0,
                fear_greed=90,
                btc_high=61000.0,
                btc_low=59000.0,
            ),
            _make_data_point(
                date_str="2024-06-02",
                btc_price=60000.0,
                btc_high=61000.0,
                btc_low=59000.0,
            ),
        ]
        engine.run(data)
        btc_trades = [t for t in engine.trades if t.symbol == "BTC"]
        # There should be at most 2 BTC trades across 2 days
        # (1 opened on day 1, closed on last day, possibly another)
        assert len(btc_trades) <= 2

    @patch("src.backtest.engine.logger")
    def test_run_closes_remaining_positions_at_end(self, mock_logger):
        engine = BacktestEngine()
        data = [
            _make_data_point(
                date_str="2024-06-01",
                long_short_ratio=3.0,
                fear_greed=90,
                btc_high=61000.0,
                btc_low=59000.0,
            ),
        ]
        engine.run(data)
        assert len(engine.open_positions) == 0


# ---------------------------------------------------------------------------
#  Generate Result Tests
# ---------------------------------------------------------------------------


class TestGenerateResult:
    """Tests for _generate_result."""

    @patch("src.backtest.engine.logger")
    def test_generate_result_calculates_metrics(self, mock_logger):
        engine = BacktestEngine()
        data = [
            _make_data_point(
                date_str="2024-06-01",
                long_short_ratio=3.0,
                fear_greed=90,
            ),
            _make_data_point(
                date_str="2024-06-02",
                btc_price=57000.0,
                btc_high=60000.0,
                btc_low=56000.0,
                eth_price=2800.0,
                eth_high=3000.0,
                eth_low=2700.0,
            ),
        ]
        result = engine.run(data)
        assert hasattr(result, "win_rate")
        assert hasattr(result, "profit_factor")
        assert hasattr(result, "max_drawdown_percent")
        assert hasattr(result, "total_fees")
        assert hasattr(result, "monthly_returns")
        assert result.starting_capital == 10000.0

    @patch("src.backtest.engine.logger")
    def test_max_drawdown_calculation(self, mock_logger):
        """Drawdown should be >= 0."""
        engine = BacktestEngine()
        data = [
            _make_data_point(date_str="2024-06-01", long_short_ratio=3.0, fear_greed=90),
            _make_data_point(
                date_str="2024-06-02",
                btc_price=55000.0, btc_high=60000.0, btc_low=54000.0,
                eth_price=2700.0, eth_high=3000.0, eth_low=2600.0,
            ),
        ]
        result = engine.run(data)
        assert result.max_drawdown_percent >= 0.0


# ---------------------------------------------------------------------------
#  Strategy Adapter Tests - _calculate_sharpe
# ---------------------------------------------------------------------------


class TestCalculateSharpe:
    """Tests for _calculate_sharpe helper."""

    def test_empty_returns(self):
        assert _calculate_sharpe([]) is None

    def test_single_return(self):
        assert _calculate_sharpe([0.01]) is None

    def test_zero_std_returns_none(self):
        result = _calculate_sharpe([0.01, 0.01, 0.01, 0.01])
        assert result is None

    def test_positive_sharpe(self):
        returns = [0.01, 0.02, 0.015, 0.012, 0.018, 0.011, 0.013]
        result = _calculate_sharpe(returns)
        assert result is not None
        assert result > 0

    def test_negative_sharpe(self):
        returns = [-0.01, -0.02, -0.015, -0.012, -0.018, 0.001, -0.013]
        result = _calculate_sharpe(returns)
        assert result is not None
        assert result < 0

    def test_custom_risk_free_rate(self):
        returns = [0.01, 0.02, 0.015, 0.012, 0.018, 0.011, 0.013]
        result_default = _calculate_sharpe(returns, risk_free_rate=0.0)
        result_custom = _calculate_sharpe(returns, risk_free_rate=0.05)
        assert result_default is not None
        assert result_custom is not None
        # Higher risk-free rate should yield lower Sharpe
        assert result_custom < result_default


# ---------------------------------------------------------------------------
#  Strategy Adapter Tests - run_backtest_for_strategy
# ---------------------------------------------------------------------------


class TestRunBacktestForStrategy:
    """Tests for run_backtest_for_strategy."""

    async def test_period_too_short_raises_error(self):
        start = datetime(2024, 6, 1)
        end = datetime(2024, 6, 1)
        with pytest.raises(ValueError, match="at least 1 day"):
            await run_backtest_for_strategy(
                strategy_type="liquidation_hunter",
                symbol="BTC",
                timeframe="1d",
                start_date=start,
                end_date=end,
                initial_capital=10000.0,
            )

    @patch("src.backtest.strategy_adapter.HistoricalDataFetcher")
    async def test_successful_backtest_returns_expected_keys(self, MockFetcher):
        mock_fetcher = AsyncMock()
        MockFetcher.return_value = mock_fetcher
        mock_fetcher.data_sources = ["Mock Source"]

        # Generate some minimal mock data
        days = 5
        data_points = []
        for i in range(days):
            data_points.append(_make_data_point(
                date_str=f"2024-06-{i+1:02d}",
                long_short_ratio=2.5,
                fear_greed=85,
                btc_price=60000.0 + i * 100,
                btc_high=61000.0 + i * 100,
                btc_low=59000.0 + i * 100,
                eth_price=3000.0 + i * 10,
                eth_high=3100.0 + i * 10,
                eth_low=2900.0 + i * 10,
            ))

        mock_fetcher.fetch_all_historical_data = AsyncMock(return_value=data_points)

        start = datetime(2024, 6, 1)
        end = datetime(2024, 6, 6)

        result = await run_backtest_for_strategy(
            strategy_type="liquidation_hunter",
            symbol="BTC",
            timeframe="1d",
            start_date=start,
            end_date=end,
            initial_capital=10000.0,
        )

        assert "trades" in result
        assert "equity_curve" in result
        assert "metrics" in result
        assert "total_return_percent" in result["metrics"]
        assert "win_rate" in result["metrics"]
        assert "sharpe_ratio" in result["metrics"]
        assert "data_sources" in result["metrics"]

    @patch("src.backtest.mock_data.generate_mock_historical_data")
    @patch("src.backtest.strategy_adapter.HistoricalDataFetcher")
    async def test_fetcher_failure_falls_back_to_mock_data(self, MockFetcher, mock_gen):
        mock_fetcher = AsyncMock()
        MockFetcher.return_value = mock_fetcher
        mock_fetcher.fetch_all_historical_data = AsyncMock(
            side_effect=Exception("Network error")
        )
        mock_fetcher.data_sources = []

        mock_data = [
            _make_data_point(date_str=f"2024-06-{i+1:02d}")
            for i in range(9)
        ]
        mock_gen.return_value = mock_data

        start = datetime(2024, 6, 1)
        end = datetime(2024, 6, 10)

        result = await run_backtest_for_strategy(
            strategy_type="liquidation_hunter",
            symbol="BTC",
            timeframe="1d",
            start_date=start,
            end_date=end,
            initial_capital=10000.0,
        )

        assert result is not None
        assert "metrics" in result

    @patch("src.backtest.strategy_adapter.HistoricalDataFetcher")
    async def test_strategy_params_applied_to_config(self, MockFetcher):
        mock_fetcher = AsyncMock()
        MockFetcher.return_value = mock_fetcher
        mock_fetcher.data_sources = ["Test"]

        data_points = [
            _make_data_point(date_str=f"2024-06-{i+1:02d}")
            for i in range(3)
        ]
        mock_fetcher.fetch_all_historical_data = AsyncMock(return_value=data_points)

        start = datetime(2024, 6, 1)
        end = datetime(2024, 6, 4)

        result = await run_backtest_for_strategy(
            strategy_type="liquidation_hunter",
            symbol="BTC",
            timeframe="1d",
            start_date=start,
            end_date=end,
            initial_capital=20000.0,
            strategy_params={"leverage": 5, "take_profit_percent": 4.0},
        )

        assert result["metrics"]["starting_capital"] == 20000.0

    @patch("src.backtest.mock_data.generate_mock_historical_data")
    @patch("src.backtest.strategy_adapter.HistoricalDataFetcher")
    async def test_empty_filtered_data_uses_mock(self, MockFetcher, mock_gen):
        """When date filtering empties the list, mock data should be used."""
        mock_fetcher = AsyncMock()
        MockFetcher.return_value = mock_fetcher
        mock_fetcher.data_sources = ["Test"]

        # Data outside the requested range
        data_points = [
            _make_data_point(date_str="2023-01-01"),
        ]
        # Set timestamp to far past
        data_points[0].timestamp = datetime(2023, 1, 1)
        mock_fetcher.fetch_all_historical_data = AsyncMock(return_value=data_points)

        mock_data = [
            _make_data_point(date_str=f"2024-06-{i+1:02d}")
            for i in range(9)
        ]
        mock_gen.return_value = mock_data

        start = datetime(2024, 6, 1)
        end = datetime(2024, 6, 10)

        result = await run_backtest_for_strategy(
            strategy_type="liquidation_hunter",
            symbol="BTC",
            timeframe="1d",
            start_date=start,
            end_date=end,
            initial_capital=10000.0,
        )
        assert result is not None

    @patch("src.backtest.strategy_adapter.HistoricalDataFetcher")
    async def test_profit_factor_infinity_handled(self, MockFetcher):
        """When profit_factor is inf, metrics should cap it at 999.99."""
        mock_fetcher = AsyncMock()
        MockFetcher.return_value = mock_fetcher
        mock_fetcher.data_sources = ["Test"]

        # All neutral -> no trades -> profit_factor from BacktestResult will be 0 (empty)
        data_points = [
            _make_data_point(
                date_str=f"2024-06-{i+1:02d}",
                long_short_ratio=1.0,
                fear_greed=50,
            )
            for i in range(3)
        ]
        mock_fetcher.fetch_all_historical_data = AsyncMock(return_value=data_points)

        start = datetime(2024, 6, 1)
        end = datetime(2024, 6, 4)

        # Force high confidence threshold so no trades are made
        result = await run_backtest_for_strategy(
            strategy_type="liquidation_hunter",
            symbol="BTC",
            timeframe="1d",
            start_date=start,
            end_date=end,
            initial_capital=10000.0,
            strategy_params={"low_confidence_min": 99},
        )
        pf = result["metrics"]["profit_factor"]
        assert pf <= 999.99


# ---------------------------------------------------------------------------
#  Enums Tests
# ---------------------------------------------------------------------------


class TestEnums:
    """Tests for TradeResult and TradeDirection enums."""

    def test_trade_result_values(self):
        assert TradeResult.TAKE_PROFIT.value == "take_profit"
        assert TradeResult.STOP_LOSS.value == "stop_loss"
        assert TradeResult.TIME_EXIT.value == "time_exit"
        assert TradeResult.OPEN.value == "open"

    def test_trade_direction_values(self):
        assert TradeDirection.LONG.value == "long"
        assert TradeDirection.SHORT.value == "short"
