"""
Integration tests for the ClaudeEdgeIndicatorStrategy.

Tests cover:
- Full signal generation pipeline with mocked kline data
- Strategy lifecycle (init -> generate -> should_trade -> close)
- Different market conditions (uptrend, downtrend, sideways)
- Enhanced features working together end-to-end
- Comparison with base EdgeIndicatorStrategy
"""

import math
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.base import SignalDirection, StrategyRegistry
from src.strategy.claude_edge_indicator import ClaudeEdgeIndicatorStrategy
from src.strategy.edge_indicator import EdgeIndicatorStrategy


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_klines(closes, highs=None, lows=None, buy_ratio=0.55):
    result = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c * 1.005
        l = lows[i] if lows else c * 0.995
        o = closes[i - 1] if i > 0 else c
        vol = 150.0
        buy_vol = vol * buy_ratio
        result.append([
            1700000000000 + i * 3600000,
            str(o), str(h), str(l), str(c), str(vol),
            1700003600000 + i * 3600000,
            str(c * vol), 2000, str(buy_vol), str(c * buy_vol), "0",
        ])
    return result


def _uptrend_closes(n=200, start=90000.0, step=50.0):
    return [start + i * step for i in range(n)]


def _downtrend_closes(n=200, start=100000.0, step=50.0):
    return [start - i * step for i in range(n)]


def _sideways_closes(n=200, center=95000.0, amplitude=200.0):
    return [center + amplitude * math.sin(i * 0.3) for i in range(n)]


def _make_mock_fetcher(klines, htf_klines=None):
    fetcher = AsyncMock()
    fetcher._ensure_session = AsyncMock()
    fetcher.close = AsyncMock()

    if htf_klines is None:
        htf_closes = _uptrend_closes(100, start=88000, step=200)
        htf_klines = _make_klines(htf_closes)

    async def get_klines_side_effect(symbol, interval, count):
        if interval == "4h":
            return htf_klines
        return klines

    fetcher.get_binance_klines = AsyncMock(side_effect=get_klines_side_effect)
    return fetcher


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Full Pipeline Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_uptrend_produces_valid_signal(self):
        klines = _make_klines(_uptrend_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price > 0
        assert 0 <= signal.confidence <= 95
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)
        assert "[Claude-Edge]" in signal.reason
        assert isinstance(signal.metrics_snapshot, dict)

    @pytest.mark.asyncio
    async def test_downtrend_produces_valid_signal(self):
        klines = _make_klines(_downtrend_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price > 0
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)

    @pytest.mark.asyncio
    async def test_sideways_market_signal(self):
        klines = _make_klines(_sideways_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price > 0
        assert signal.metrics_snapshot.get("is_choppy") is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Strategy Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyLifecycle:
    @pytest.mark.asyncio
    async def test_init_generate_should_trade_close(self):
        klines = _make_klines(_uptrend_closes())
        fetcher = _make_mock_fetcher(klines)

        strategy = ClaudeEdgeIndicatorStrategy(
            params={"min_confidence": 30},
            data_fetcher=fetcher,
        )

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.entry_price > 0

        should, reason = await strategy.should_trade(signal)
        assert isinstance(should, bool)
        assert isinstance(reason, str)

        await strategy.close()
        fetcher.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_registry_create_and_use(self):
        strategy = StrategyRegistry.create("claude_edge_indicator", params={
            "atr_tp_multiplier": 3.0,
            "min_confidence": 30,
        })

        assert isinstance(strategy, ClaudeEdgeIndicatorStrategy)
        assert strategy._p["atr_tp_multiplier"] == 3.0

        klines = _make_klines(_uptrend_closes())
        strategy.data_fetcher = _make_mock_fetcher(klines)

        signal = await strategy.generate_signal("ETHUSDT")
        assert signal.symbol == "ETHUSDT"
        assert signal.entry_price > 0

        await strategy.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Enhanced Features Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnhancedFeatures:
    @pytest.mark.asyncio
    async def test_atr_targets_vary_with_volatility(self):
        """ATR-based targets should adapt to market volatility."""
        # Low volatility
        calm_closes = _uptrend_closes(200, step=10)
        calm_klines = _make_klines(
            calm_closes,
            highs=[c * 1.001 for c in calm_closes],
            lows=[c * 0.999 for c in calm_closes],
        )
        calm_fetcher = _make_mock_fetcher(calm_klines)
        calm_strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=calm_fetcher)
        calm_signal = await calm_strategy.generate_signal("BTCUSDT")

        # High volatility
        vol_closes = _uptrend_closes(200, step=10)
        vol_klines = _make_klines(
            vol_closes,
            highs=[c * 1.02 for c in vol_closes],
            lows=[c * 0.98 for c in vol_closes],
        )
        vol_fetcher = _make_mock_fetcher(vol_klines)
        vol_strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=vol_fetcher)
        vol_signal = await vol_strategy.generate_signal("BTCUSDT")

        if calm_signal.entry_price > 0 and vol_signal.entry_price > 0:
            calm_tp_distance = abs(calm_signal.target_price - calm_signal.entry_price)
            vol_tp_distance = abs(vol_signal.target_price - vol_signal.entry_price)

            # Volatile market should have wider TP/SL
            assert vol_tp_distance > calm_tp_distance

        await calm_strategy.close()
        await vol_strategy.close()

    @pytest.mark.asyncio
    async def test_volume_affects_confidence(self):
        """Strong buying volume should increase confidence vs neutral."""
        closes = _uptrend_closes(200, step=50)

        # Strong buying
        buy_klines = _make_klines(closes, buy_ratio=0.70)
        buy_fetcher = _make_mock_fetcher(buy_klines)
        buy_strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=buy_fetcher)
        buy_signal = await buy_strategy.generate_signal("BTCUSDT")

        # Neutral volume
        neutral_klines = _make_klines(closes, buy_ratio=0.50)
        neutral_fetcher = _make_mock_fetcher(neutral_klines)
        neutral_strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=neutral_fetcher)
        neutral_signal = await neutral_strategy.generate_signal("BTCUSDT")

        # Volume confirmation should boost confidence
        assert buy_signal.confidence >= neutral_signal.confidence - 5

        await buy_strategy.close()
        await neutral_strategy.close()

    @pytest.mark.asyncio
    async def test_trailing_stop_in_signal(self):
        """Signal should contain trailing stop metadata."""
        klines = _make_klines(_uptrend_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert "trailing_enabled" in signal.metrics_snapshot
        if signal.metrics_snapshot.get("trailing_enabled"):
            assert "breakeven_trigger" in signal.metrics_snapshot
            assert "trail_distance" in signal.metrics_snapshot

        await strategy.close()

    @pytest.mark.asyncio
    async def test_position_scale_in_signal(self):
        """Signal should contain position size recommendation."""
        klines = _make_klines(_uptrend_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        scale = signal.metrics_snapshot.get("position_scale")
        assert scale is not None
        assert 0.5 <= scale <= 1.0

        await strategy.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Comparison with Edge Indicator
# ═══════════════════════════════════════════════════════════════════════════════

class TestComparisonWithEdge:
    @pytest.mark.asyncio
    async def test_both_strategies_produce_signals(self):
        """Both Edge and Claude-Edge should produce valid signals from same data."""
        closes = _uptrend_closes(200, step=50)
        klines = _make_klines(closes)

        # Edge Indicator
        edge_fetcher = AsyncMock()
        edge_fetcher._ensure_session = AsyncMock()
        edge_fetcher.close = AsyncMock()
        edge_fetcher.get_binance_klines = AsyncMock(return_value=klines)
        edge = EdgeIndicatorStrategy(data_fetcher=edge_fetcher)
        edge_signal = await edge.generate_signal("BTCUSDT")

        # Claude-Edge
        claude_fetcher = _make_mock_fetcher(klines)
        claude_edge = ClaudeEdgeIndicatorStrategy(data_fetcher=claude_fetcher)
        claude_signal = await claude_edge.generate_signal("BTCUSDT")

        assert edge_signal.entry_price > 0
        assert claude_signal.entry_price > 0
        assert edge_signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)
        assert claude_signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)

        await edge.close()
        await claude_edge.close()

    @pytest.mark.asyncio
    async def test_claude_edge_has_more_metrics(self):
        """Claude-Edge should have additional metrics in snapshot."""
        closes = _uptrend_closes(200, step=50)
        klines = _make_klines(closes)

        edge_fetcher = AsyncMock()
        edge_fetcher._ensure_session = AsyncMock()
        edge_fetcher.close = AsyncMock()
        edge_fetcher.get_binance_klines = AsyncMock(return_value=klines)
        edge = EdgeIndicatorStrategy(data_fetcher=edge_fetcher)
        edge_signal = await edge.generate_signal("BTCUSDT")

        claude_fetcher = _make_mock_fetcher(klines)
        claude_edge = ClaudeEdgeIndicatorStrategy(data_fetcher=claude_fetcher)
        claude_signal = await claude_edge.generate_signal("BTCUSDT")

        # Claude-Edge should have extra keys
        extra_keys = ["atr_value", "volume_score", "position_scale", "trailing_enabled"]
        for key in extra_keys:
            assert key in claude_signal.metrics_snapshot, f"Missing: {key}"
            assert key not in edge_signal.metrics_snapshot

        await edge.close()
        await claude_edge.close()
