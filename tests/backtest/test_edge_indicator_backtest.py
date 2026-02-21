"""
Backtest tests for the Edge Indicator strategy.

Tests cover:
- Backtest engine mechanics (kline-based)
- Edge Indicator performance across timeframes (15m, 30m, 1h, 4h)
- Signal quality validation
- Risk metrics (drawdown, profit factor, win rate)
"""

import random

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.backtest.kline_backtest_engine import (
    KlineBacktestConfig,
    KlineBacktestEngine,
    KlineTradeResult,
)
from src.strategy.edge_indicator import EdgeIndicatorStrategy


# ── Data Generators ──────────────────────────────────────────────────────

def _make_kline(timestamp_ms: int, o: float, h: float, low: float, c: float, v: float = 100.0):
    """Build a single kline row."""
    return [
        timestamp_ms, str(o), str(h), str(low), str(c), str(v),
        timestamp_ms + 3600000, str(c * v), 1000, str(v * 0.55), str(c * v * 0.55), "0",
    ]


def _generate_trending_market(
    n: int = 1000,
    start_price: float = 90000.0,
    trend_strength: float = 0.002,
    volatility: float = 0.008,
    seed: int = 42,
) -> list:
    """
    Generate realistic trending market klines with random walk + drift.

    Alternates between trending (70%) and ranging (30%) phases to simulate
    real BTC price action.
    """
    rng = random.Random(seed)
    klines = []
    price = start_price
    phase_len = 0
    is_trending = True
    trend_dir = 1.0

    for i in range(n):
        # Phase transitions
        if phase_len <= 0:
            if rng.random() < 0.7:
                is_trending = True
                trend_dir = 1.0 if rng.random() < 0.55 else -1.0
                phase_len = rng.randint(40, 120)
            else:
                is_trending = False
                phase_len = rng.randint(20, 60)

        phase_len -= 1

        # Price movement
        noise = rng.gauss(0, volatility)
        if is_trending:
            drift = trend_strength * trend_dir
        else:
            drift = 0.0

        change = drift + noise
        price *= (1 + change)
        price = max(price, 1000.0)  # Floor

        # Build OHLC
        intrabar_vol = abs(rng.gauss(0, volatility * 0.6))
        high = price * (1 + intrabar_vol)
        low = price * (1 - intrabar_vol)
        open_price = price * (1 + rng.gauss(0, volatility * 0.3))

        # Ensure OHLC consistency
        high = max(high, open_price, price)
        low = min(low, open_price, price)

        ts = 1700000000000 + i * 3600000
        volume = 50 + rng.random() * 200
        klines.append(_make_kline(ts, open_price, high, low, price, volume))

    return klines


def _generate_strong_uptrend(n: int = 800, seed: int = 100) -> list:
    return _generate_trending_market(n, 85000.0, trend_strength=0.004, volatility=0.006, seed=seed)


def _generate_strong_downtrend(n: int = 800, seed: int = 200) -> list:
    return _generate_trending_market(n, 100000.0, trend_strength=-0.004, volatility=0.006, seed=seed)


def _generate_sideways_market(n: int = 800, seed: int = 300) -> list:
    return _generate_trending_market(n, 95000.0, trend_strength=0.0, volatility=0.005, seed=seed)


def _generate_mixed_market(n: int = 2000, seed: int = 42) -> list:
    """Generate a realistic mixed market with multiple phases."""
    return _generate_trending_market(n, 92000.0, trend_strength=0.0015, volatility=0.007, seed=seed)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Engine Mechanics
# ═══════════════════════════════════════════════════════════════════════════════

class TestKlineBacktestEngine:
    """Tests for the kline backtest engine itself."""

    def test_empty_klines_returns_empty_result(self):
        engine = KlineBacktestEngine()
        result = engine.run([], EdgeIndicatorStrategy, interval="1h")

        assert result.total_trades == 0
        assert result.total_return_percent == 0

    def test_insufficient_klines_returns_empty_result(self):
        klines = _generate_trending_market(100)  # Less than lookback=200
        engine = KlineBacktestEngine()
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        assert result.total_trades == 0

    def test_engine_respects_min_confidence(self):
        klines = _generate_mixed_market(500, seed=55)
        config = KlineBacktestConfig(min_confidence=95)  # Very high bar
        engine = KlineBacktestEngine(config)
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        # With very high min_confidence, fewer or no trades should open
        assert result.total_trades <= 5

    def test_equity_curve_starts_at_starting_capital(self):
        klines = _generate_mixed_market(500)
        engine = KlineBacktestEngine()
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        assert result.equity_curve[0] == 10000.0

    def test_result_to_dict_serializable(self):
        klines = _generate_mixed_market(500)
        engine = KlineBacktestEngine()
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        d = result.to_dict()
        assert isinstance(d, dict)
        assert "interval" in d
        assert "total_return_percent" in d
        assert "sharpe_ratio" in d


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Strategy Performance (per timeframe)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeIndicatorBacktestPerformance:
    """
    Run the Edge Indicator across simulated timeframes.

    These tests validate that the strategy produces meaningful signals
    and doesn't catastrophically lose capital. They are NOT guarantees
    of future performance.
    """

    def _run_backtest(self, klines, interval="1h", params=None):
        config = KlineBacktestConfig(
            starting_capital=10000.0,
            leverage=3,
            position_size_percent=10.0,
            trading_fee_percent=0.06,
            max_bars_in_trade=50,
            cooldown_bars=2,
            min_confidence=40,
        )
        engine = KlineBacktestEngine(config)
        return engine.run(
            klines, EdgeIndicatorStrategy,
            strategy_params=params,
            interval=interval,
            lookback=200,
        )

    def test_1h_mixed_market(self):
        """1h timeframe on mixed market should produce trades."""
        klines = _generate_mixed_market(2000, seed=42)
        result = self._run_backtest(klines, "1h")

        assert result.total_trades > 0
        assert result.interval == "1h"
        # Should not lose more than 30% on simulated data
        assert result.total_return_percent > -30
        print(result.summary())

    def test_4h_mixed_market(self):
        """4h timeframe with adjusted lookback."""
        klines = _generate_mixed_market(1500, seed=43)
        result = self._run_backtest(klines, "4h")

        assert result.total_trades > 0
        assert result.interval == "4h"
        assert result.total_return_percent > -30
        print(result.summary())

    def test_15m_mixed_market(self):
        """15m timeframe (more noise)."""
        klines = _generate_mixed_market(2000, seed=44)
        result = self._run_backtest(klines, "15m")

        assert result.total_trades > 0
        assert result.interval == "15m"
        print(result.summary())

    def test_30m_mixed_market(self):
        """30m timeframe."""
        klines = _generate_mixed_market(2000, seed=45)
        result = self._run_backtest(klines, "30m")

        assert result.total_trades > 0
        assert result.interval == "30m"
        print(result.summary())

    def test_strong_uptrend_profitable(self):
        """In a strong uptrend, strategy should be profitable overall."""
        klines = _generate_strong_uptrend(800, seed=100)
        result = self._run_backtest(klines, "1h")

        # Strategy should be profitable in a strong trend
        assert result.total_return_percent > 0
        assert result.win_rate > 50

        long_wins = sum(1 for t in result.trades if t.direction == "long" and t.net_pnl > 0)
        short_wins = sum(1 for t in result.trades if t.direction == "short" and t.net_pnl > 0)
        print(f"Uptrend: {long_wins} long wins, {short_wins} short wins")
        print(result.summary())

    def test_strong_downtrend_favors_shorts(self):
        """In a strong downtrend, more winning shorts than longs."""
        klines = _generate_strong_downtrend(800, seed=200)
        result = self._run_backtest(klines, "1h")

        short_wins = sum(1 for t in result.trades if t.direction == "short" and t.net_pnl > 0)
        long_wins = sum(1 for t in result.trades if t.direction == "long" and t.net_pnl > 0)

        assert short_wins >= long_wins or result.total_trades < 3
        print(f"Downtrend: {short_wins} short wins, {long_wins} long wins")
        print(result.summary())

    def test_sideways_market_limited_losses(self):
        """In sideways market, strategy should limit losses via ADX filter."""
        klines = _generate_sideways_market(800, seed=300)
        result = self._run_backtest(klines, "1h")

        # ADX filter should reduce trades in choppy conditions
        # Even if it trades, losses should be limited
        assert result.max_drawdown_percent < 50
        print(f"Sideways: {result.total_trades} trades, DD={result.max_drawdown_percent:.1f}%")
        print(result.summary())


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Risk Metrics Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskMetrics:
    """Validate that risk metrics are correctly calculated."""

    def test_win_rate_between_0_and_100(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        if result.total_trades > 0:
            assert 0 <= result.win_rate <= 100

    def test_drawdown_non_negative(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        assert result.max_drawdown_percent >= 0

    def test_profit_factor_calculation(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        if result.total_trades > 0:
            assert result.profit_factor >= 0

    def test_trades_have_valid_results(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        for trade in result.trades:
            if trade.result is not None:
                assert trade.result in (
                    KlineTradeResult.TAKE_PROFIT,
                    KlineTradeResult.STOP_LOSS,
                    KlineTradeResult.TIME_EXIT,
                )
                assert trade.exit_price is not None
                assert trade.exit_price > 0

    def test_fees_are_always_positive(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)

        for trade in result.trades:
            if trade.result is not None:
                assert trade.fees >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Comprehensive Multi-Timeframe Report
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultiTimeframeReport:
    """Run all timeframes and output a comparison report."""

    def test_multi_timeframe_comparison(self):
        """Compare Edge Indicator across 15m, 30m, 1h, 4h."""
        klines = _generate_mixed_market(3000, seed=42)

        config = KlineBacktestConfig(
            starting_capital=10000.0,
            leverage=3,
            position_size_percent=10.0,
            trading_fee_percent=0.06,
            max_bars_in_trade=50,
            cooldown_bars=2,
            min_confidence=40,
        )
        engine = KlineBacktestEngine(config)

        results = {}
        for interval in ["15m", "30m", "1h", "4h"]:
            result = engine.run(
                klines, EdgeIndicatorStrategy,
                interval=interval, lookback=200,
            )
            results[interval] = result

        # Print comparison table
        print("\n" + "=" * 80)
        print("  EDGE INDICATOR - MULTI-TIMEFRAME BACKTEST COMPARISON")
        print("=" * 80)
        print(f"  {'Interval':<10} {'Return':>10} {'Win Rate':>10} {'Trades':>8} "
              f"{'Max DD':>10} {'PF':>8} {'Sharpe':>8} {'Avg Bars':>10}")
        print("-" * 80)

        for interval, r in results.items():
            sharpe_str = f"{r.sharpe_ratio:.2f}" if r.sharpe_ratio else "N/A"
            pf_str = f"{r.profit_factor:.2f}" if r.profit_factor < 999 else "inf"
            print(f"  {interval:<10} {r.total_return_percent:>+9.2f}% {r.win_rate:>9.1f}% "
                  f"{r.total_trades:>8} {r.max_drawdown_percent:>9.2f}% "
                  f"{pf_str:>8} {sharpe_str:>8} {r.avg_bars_held:>9.1f}")

        print("=" * 80)

        # All intervals should produce some trades
        for interval, r in results.items():
            assert r.total_trades > 0, f"{interval} produced no trades"
