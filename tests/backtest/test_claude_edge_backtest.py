"""
Backtest tests for the Claude-Edge Indicator strategy.

Tests cover:
- Backtest engine with ClaudeEdgeIndicatorStrategy
- Performance across timeframes (15m, 30m, 1h, 4h)
- Comparison with base EdgeIndicatorStrategy
- Risk metrics validation
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
from src.strategy.claude_edge_indicator import ClaudeEdgeIndicatorStrategy
from src.strategy.edge_indicator import EdgeIndicatorStrategy


# ── Data Generators ──────────────────────────────────────────────────────

def _make_kline(timestamp_ms: int, o: float, h: float, low: float, c: float, v: float = 100.0):
    buy_vol = v * 0.55
    return [
        timestamp_ms, str(o), str(h), str(low), str(c), str(v),
        timestamp_ms + 3600000, str(c * v), 1000, str(buy_vol), str(c * buy_vol), "0",
    ]


def _generate_trending_market(
    n: int = 1000,
    start_price: float = 90000.0,
    trend_strength: float = 0.002,
    volatility: float = 0.008,
    seed: int = 42,
) -> list:
    rng = random.Random(seed)
    klines = []
    price = start_price
    phase_len = 0
    is_trending = True
    trend_dir = 1.0

    for i in range(n):
        if phase_len <= 0:
            if rng.random() < 0.7:
                is_trending = True
                trend_dir = 1.0 if rng.random() < 0.55 else -1.0
                phase_len = rng.randint(40, 120)
            else:
                is_trending = False
                phase_len = rng.randint(20, 60)

        phase_len -= 1
        noise = rng.gauss(0, volatility)
        drift = trend_strength * trend_dir if is_trending else 0.0
        change = drift + noise
        price *= (1 + change)
        price = max(price, 1000.0)

        intrabar_vol = abs(rng.gauss(0, volatility * 0.6))
        high = price * (1 + intrabar_vol)
        low = price * (1 - intrabar_vol)
        open_price = price * (1 + rng.gauss(0, volatility * 0.3))

        high = max(high, open_price, price)
        low = min(low, open_price, price)

        ts = 1700000000000 + i * 3600000
        volume = 50 + rng.random() * 200
        klines.append(_make_kline(ts, open_price, high, low, price, volume))

    return klines


def _generate_strong_uptrend(n=800, seed=100):
    return _generate_trending_market(n, 85000.0, 0.004, 0.006, seed)


def _generate_strong_downtrend(n=800, seed=200):
    return _generate_trending_market(n, 100000.0, -0.004, 0.006, seed)


def _generate_sideways_market(n=800, seed=300):
    return _generate_trending_market(n, 95000.0, 0.0, 0.005, seed)


def _generate_mixed_market(n=2000, seed=42):
    return _generate_trending_market(n, 92000.0, 0.0015, 0.007, seed)


def _get_config():
    return KlineBacktestConfig(
        starting_capital=10000.0,
        leverage=3,
        position_size_percent=10.0,
        trading_fee_percent=0.06,
        max_bars_in_trade=50,
        cooldown_bars=2,
        min_confidence=40,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Engine Mechanics with Claude-Edge
# ═══════════════════════════════════════════════════════════════════════════════

class TestKlineBacktestEngineWithClaudeEdge:
    def test_empty_klines_returns_empty(self):
        engine = KlineBacktestEngine()
        result = engine.run([], ClaudeEdgeIndicatorStrategy, interval="1h")
        assert result.total_trades == 0

    def test_insufficient_klines_returns_empty(self):
        klines = _generate_trending_market(100)
        engine = KlineBacktestEngine()
        result = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)
        assert result.total_trades == 0

    def test_engine_respects_min_confidence(self):
        klines = _generate_mixed_market(500, seed=55)
        config = KlineBacktestConfig(min_confidence=95)
        engine = KlineBacktestEngine(config)
        result = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)
        assert result.total_trades <= 5

    def test_equity_curve_starts_at_capital(self):
        klines = _generate_mixed_market(500)
        engine = KlineBacktestEngine()
        result = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)
        assert result.equity_curve[0] == 10000.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Claude-Edge Performance (per timeframe)
# ═══════════════════════════════════════════════════════════════════════════════

class TestClaudeEdgeBacktestPerformance:
    def _run_backtest(self, klines, interval="1h", params=None):
        engine = KlineBacktestEngine(_get_config())
        return engine.run(
            klines, ClaudeEdgeIndicatorStrategy,
            strategy_params=params,
            interval=interval,
            lookback=200,
        )

    def test_1h_mixed_market(self):
        klines = _generate_mixed_market(2000, seed=42)
        result = self._run_backtest(klines, "1h")
        assert result.total_trades > 0
        assert result.interval == "1h"
        assert result.total_return_percent > -30
        print(result.summary())

    def test_4h_mixed_market(self):
        klines = _generate_mixed_market(1500, seed=43)
        result = self._run_backtest(klines, "4h")
        assert result.total_trades > 0
        assert result.total_return_percent > -30
        print(result.summary())

    def test_15m_mixed_market(self):
        klines = _generate_mixed_market(2000, seed=44)
        result = self._run_backtest(klines, "15m")
        assert result.total_trades > 0
        print(result.summary())

    def test_30m_mixed_market(self):
        klines = _generate_mixed_market(2000, seed=45)
        result = self._run_backtest(klines, "30m")
        assert result.total_trades > 0
        print(result.summary())

    def test_strong_uptrend(self):
        klines = _generate_strong_uptrend(800, seed=100)
        result = self._run_backtest(klines, "1h")
        assert result.total_return_percent > 0
        assert result.win_rate > 50
        print(result.summary())

    def test_strong_downtrend(self):
        klines = _generate_strong_downtrend(800, seed=200)
        result = self._run_backtest(klines, "1h")
        short_wins = sum(1 for t in result.trades if t.direction == "short" and t.net_pnl > 0)
        long_wins = sum(1 for t in result.trades if t.direction == "long" and t.net_pnl > 0)
        assert short_wins >= long_wins or result.total_trades < 3
        print(result.summary())

    def test_sideways_limited_losses(self):
        klines = _generate_sideways_market(800, seed=300)
        result = self._run_backtest(klines, "1h")
        assert result.max_drawdown_percent < 50
        print(result.summary())


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Risk Metrics Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskMetrics:
    def test_win_rate_between_0_and_100(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)
        if result.total_trades > 0:
            assert 0 <= result.win_rate <= 100

    def test_drawdown_non_negative(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)
        assert result.max_drawdown_percent >= 0

    def test_profit_factor_calculation(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)
        if result.total_trades > 0:
            assert result.profit_factor >= 0

    def test_trades_have_valid_results(self):
        klines = _generate_mixed_market(1000)
        engine = KlineBacktestEngine()
        result = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)
        for trade in result.trades:
            if trade.result is not None:
                assert trade.result in (
                    KlineTradeResult.TAKE_PROFIT,
                    KlineTradeResult.STOP_LOSS,
                    KlineTradeResult.TIME_EXIT,
                )
                assert trade.exit_price > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Edge vs Claude-Edge Comparison
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeVsClaudeEdgeComparison:
    """Compare both strategies side-by-side across all timeframes."""

    def test_multi_timeframe_comparison(self):
        """Compare Edge vs Claude-Edge across 15m, 30m, 1h, 4h."""
        klines = _generate_mixed_market(3000, seed=42)

        config = _get_config()
        engine = KlineBacktestEngine(config)

        edge_results = {}
        claude_results = {}

        for interval in ["15m", "30m", "1h", "4h"]:
            edge_results[interval] = engine.run(
                klines, EdgeIndicatorStrategy,
                interval=interval, lookback=200,
            )
            claude_results[interval] = engine.run(
                klines, ClaudeEdgeIndicatorStrategy,
                interval=interval, lookback=200,
            )

        # Print comparison table
        print("\n" + "=" * 110)
        print("  EDGE INDICATOR vs CLAUDE-EDGE — MULTI-TIMEFRAME COMPARISON")
        print("=" * 110)
        print(f"  {'Metric':<20} ", end="")
        for interval in ["1h", "4h"]:
            print(f"{'Edge (' + interval + ')':>14} {'C-Edge (' + interval + ')':>16} ", end="")
        print()
        print("-" * 110)

        for interval in ["1h", "4h"]:
            e = edge_results[interval]
            c = claude_results[interval]

            if interval == "1h":
                print(f"  {'Return %':<20} {e.total_return_percent:>+13.2f}% {c.total_return_percent:>+15.2f}%", end="")
            else:
                print(f" {e.total_return_percent:>+13.2f}% {c.total_return_percent:>+15.2f}%")

        print()

        # Detailed per-interval
        for interval in ["15m", "30m", "1h", "4h"]:
            e = edge_results[interval]
            c = claude_results[interval]

            e_sharpe = f"{e.sharpe_ratio:.2f}" if e.sharpe_ratio else "N/A"
            c_sharpe = f"{c.sharpe_ratio:.2f}" if c.sharpe_ratio else "N/A"
            e_pf = f"{e.profit_factor:.2f}" if e.profit_factor < 999 else "inf"
            c_pf = f"{c.profit_factor:.2f}" if c.profit_factor < 999 else "inf"

            print(f"\n  === {interval} ===")
            print(f"  {'Metric':<20} {'Edge':>12} {'Claude-Edge':>14}")
            print(f"  {'-' * 48}")
            print(f"  {'Return %':<20} {e.total_return_percent:>+11.2f}% {c.total_return_percent:>+13.2f}%")
            print(f"  {'Win Rate':<20} {e.win_rate:>11.1f}% {c.win_rate:>13.1f}%")
            print(f"  {'Trades':<20} {e.total_trades:>12} {c.total_trades:>14}")
            print(f"  {'Max Drawdown':<20} {e.max_drawdown_percent:>11.2f}% {c.max_drawdown_percent:>13.2f}%")
            print(f"  {'Profit Factor':<20} {e_pf:>12} {c_pf:>14}")
            print(f"  {'Sharpe Ratio':<20} {e_sharpe:>12} {c_sharpe:>14}")
            print(f"  {'Avg Bars Held':<20} {e.avg_bars_held:>11.1f} {c.avg_bars_held:>14.1f}")

        print("\n" + "=" * 110)

        # Both should produce trades
        for interval in ["15m", "30m", "1h", "4h"]:
            assert edge_results[interval].total_trades > 0, f"Edge {interval} no trades"
            assert claude_results[interval].total_trades > 0, f"Claude-Edge {interval} no trades"

    def test_strong_uptrend_comparison(self):
        """Compare in strong uptrend."""
        klines = _generate_strong_uptrend(800, seed=100)
        config = _get_config()
        engine = KlineBacktestEngine(config)

        edge = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)
        claude = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)

        print("\n  STRONG UPTREND COMPARISON (1h)")
        print(f"  Edge:       Return={edge.total_return_percent:+.2f}% WR={edge.win_rate:.1f}% Trades={edge.total_trades}")
        print(f"  Claude-Edge: Return={claude.total_return_percent:+.2f}% WR={claude.win_rate:.1f}% Trades={claude.total_trades}")

        assert edge.total_trades > 0
        assert claude.total_trades > 0

    def test_sideways_comparison(self):
        """Compare in sideways market (ATR-based targets may help)."""
        klines = _generate_sideways_market(800, seed=300)
        config = _get_config()
        engine = KlineBacktestEngine(config)

        edge = engine.run(klines, EdgeIndicatorStrategy, interval="1h", lookback=200)
        claude = engine.run(klines, ClaudeEdgeIndicatorStrategy, interval="1h", lookback=200)

        print("\n  SIDEWAYS MARKET COMPARISON (1h)")
        print(f"  Edge:       Return={edge.total_return_percent:+.2f}% DD={edge.max_drawdown_percent:.2f}% Trades={edge.total_trades}")
        print(f"  Claude-Edge: Return={claude.total_return_percent:+.2f}% DD={claude.max_drawdown_percent:.2f}% Trades={claude.total_trades}")

        # Both should limit losses in sideways
        assert edge.max_drawdown_percent < 50
        assert claude.max_drawdown_percent < 50
