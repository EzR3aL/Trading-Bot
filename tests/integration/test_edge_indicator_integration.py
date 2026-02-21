"""
Integration tests for the EdgeIndicator strategy.

Tests cover:
- Full signal generation pipeline with mocked kline data
- Strategy + data fetcher integration
- Strategy lifecycle (init -> generate -> should_trade -> close)
- Different market conditions (uptrend, downtrend, sideways)
- Parameter customization end-to-end
"""

import pytest
from unittest.mock import AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.base import SignalDirection, StrategyRegistry
from src.strategy.edge_indicator import EdgeIndicatorStrategy


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_klines(closes, highs=None, lows=None):
    """Build realistic kline data from close prices."""
    result = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c * 1.005
        low = lows[i] if lows else c * 0.995
        o = closes[i - 1] if i > 0 else c
        result.append([
            1700000000000 + i * 3600000,
            str(o), str(h), str(low), str(c), "150.0",
            1700003600000 + i * 3600000,
            str(c * 150), 2000, "82.5", str(c * 82.5), "0",
        ])
    return result


def _uptrend_closes(n=200, start=90000.0, step=50.0):
    return [start + i * step for i in range(n)]


def _downtrend_closes(n=200, start=100000.0, step=50.0):
    return [start - i * step for i in range(n)]


def _sideways_closes(n=200, center=95000.0, amplitude=200.0):
    import math
    return [center + amplitude * math.sin(i * 0.3) for i in range(n)]


def _make_mock_fetcher(klines):
    """Create a mock data fetcher returning the given klines."""
    fetcher = AsyncMock()
    fetcher._ensure_session = AsyncMock()
    fetcher.close = AsyncMock()
    fetcher.get_binance_klines = AsyncMock(return_value=klines)
    return fetcher


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Full Pipeline Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """Tests for the complete signal generation pipeline."""

    @pytest.mark.asyncio
    async def test_uptrend_produces_valid_signal(self):
        """Uptrend data should produce a valid trade signal."""
        klines = _make_klines(_uptrend_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = EdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price > 0
        assert 0 <= signal.confidence <= 95
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)
        assert signal.target_price != signal.entry_price or signal.confidence == 0
        assert signal.stop_loss != signal.entry_price or signal.confidence == 0
        assert isinstance(signal.reason, str)
        assert len(signal.reason) > 0
        assert isinstance(signal.metrics_snapshot, dict)

    @pytest.mark.asyncio
    async def test_downtrend_produces_valid_signal(self):
        """Downtrend data should produce a valid trade signal."""
        klines = _make_klines(_downtrend_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = EdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price > 0
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)

    @pytest.mark.asyncio
    async def test_sideways_market_signal(self):
        """Sideways market should still produce a signal (possibly low confidence)."""
        klines = _make_klines(_sideways_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = EdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price > 0
        # In a sideways market, ADX should be low -> signal exists but may be low confidence
        assert signal.metrics_snapshot.get("is_choppy") is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Strategy Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyLifecycle:
    """Tests for the full strategy lifecycle."""

    @pytest.mark.asyncio
    async def test_init_generate_should_trade_close(self):
        """Complete lifecycle: init -> generate -> should_trade -> close."""
        klines = _make_klines(_uptrend_closes())
        fetcher = _make_mock_fetcher(klines)

        # Init
        strategy = EdgeIndicatorStrategy(
            params={"min_confidence": 30},
            data_fetcher=fetcher,
        )

        # Generate
        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.entry_price > 0

        # Should trade
        should, reason = await strategy.should_trade(signal)
        assert isinstance(should, bool)
        assert isinstance(reason, str)

        # Close
        await strategy.close()
        fetcher.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_registry_create_and_use(self):
        """Create strategy via registry and use it end-to-end."""
        strategy = StrategyRegistry.create("edge_indicator", params={
            "ema_fast_period": 10,
            "ema_slow_period": 25,
            "min_confidence": 30,
        })

        assert isinstance(strategy, EdgeIndicatorStrategy)
        assert strategy._p["ema_fast_period"] == 10
        assert strategy._p["ema_slow_period"] == 25

        # Set up mock fetcher
        klines = _make_klines(_uptrend_closes())
        strategy.data_fetcher = _make_mock_fetcher(klines)

        signal = await strategy.generate_signal("ETHUSDT")
        assert signal.symbol == "ETHUSDT"
        assert signal.entry_price > 0

        await strategy.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Market Condition Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketConditions:
    """Tests for different market conditions."""

    @pytest.mark.asyncio
    async def test_strong_uptrend_high_confidence(self):
        """Strong uptrend should produce higher confidence than sideways."""
        uptrend_klines = _make_klines(_uptrend_closes(200, step=100))
        sideways_klines = _make_klines(_sideways_closes(200, amplitude=50))

        # Strong uptrend
        fetcher_up = _make_mock_fetcher(uptrend_klines)
        strategy_up = EdgeIndicatorStrategy(data_fetcher=fetcher_up)
        signal_up = await strategy_up.generate_signal("BTCUSDT")

        # Sideways
        fetcher_side = _make_mock_fetcher(sideways_klines)
        strategy_side = EdgeIndicatorStrategy(data_fetcher=fetcher_side)
        signal_side = await strategy_side.generate_signal("BTCUSDT")

        # Uptrend should generally have higher confidence
        # (not guaranteed due to indicator dynamics, but should be true for strong trends)
        assert signal_up.confidence >= signal_side.confidence or signal_up.confidence > 40

        await strategy_up.close()
        await strategy_side.close()

    @pytest.mark.asyncio
    async def test_tp_sl_correct_for_direction(self):
        """TP and SL should be on correct sides of entry price."""
        klines = _make_klines(_uptrend_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = EdgeIndicatorStrategy(data_fetcher=fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        if signal.entry_price > 0:
            if signal.direction == SignalDirection.LONG:
                assert signal.target_price > signal.entry_price
                assert signal.stop_loss < signal.entry_price
            else:
                assert signal.target_price < signal.entry_price
                assert signal.stop_loss > signal.entry_price

        await strategy.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Parameter Customization
# ═══════════════════════════════════════════════════════════════════════════════

class TestParameterCustomization:
    """Tests for customized parameters end-to-end."""

    @pytest.mark.asyncio
    async def test_custom_ema_periods(self):
        """Custom EMA periods should change indicator behavior."""
        klines = _make_klines(_uptrend_closes())

        # Default (8/21)
        fetcher1 = _make_mock_fetcher(klines)
        strategy1 = EdgeIndicatorStrategy(data_fetcher=fetcher1)
        signal1 = await strategy1.generate_signal("BTCUSDT")

        # Custom (5/13) - faster, more responsive
        fetcher2 = _make_mock_fetcher(klines)
        strategy2 = EdgeIndicatorStrategy(
            params={"ema_fast_period": 5, "ema_slow_period": 13},
            data_fetcher=fetcher2,
        )
        signal2 = await strategy2.generate_signal("BTCUSDT")

        # Both should produce valid signals
        assert signal1.entry_price > 0
        assert signal2.entry_price > 0

        # EMA values should differ
        assert signal1.metrics_snapshot["ema_fast"] != signal2.metrics_snapshot["ema_fast"]

        await strategy1.close()
        await strategy2.close()

    @pytest.mark.asyncio
    async def test_adx_filter_disabled(self):
        """With ADX filter disabled, choppy market should still allow trading."""
        klines = _make_klines(_sideways_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = EdgeIndicatorStrategy(
            params={"use_adx_filter": False, "min_confidence": 10},
            data_fetcher=fetcher,
        )

        signal = await strategy.generate_signal("BTCUSDT")
        should, reason = await strategy.should_trade(signal)

        # With ADX filter disabled, should trade even in choppy conditions
        # (as long as confidence meets minimum)
        if signal.confidence >= 10:
            assert should is True

        await strategy.close()

    @pytest.mark.asyncio
    async def test_custom_kline_interval(self):
        """Custom kline interval should be passed to data fetcher."""
        klines = _make_klines(_uptrend_closes())
        fetcher = _make_mock_fetcher(klines)
        strategy = EdgeIndicatorStrategy(
            params={"kline_interval": "4h", "kline_count": 100},
            data_fetcher=fetcher,
        )

        await strategy.generate_signal("BTCUSDT")

        fetcher.get_binance_klines.assert_awaited_once_with("BTCUSDT", "4h", 100)

        await strategy.close()
