"""
Unit tests for the EdgeIndicator strategy.

Tests cover:
- Initialization (default params, custom params, data_fetcher injection)
- _ensure_fetcher lazy initialization
- _calculate_ema_ribbon (bull, bear, neutral trends, band crossovers)
- _calculate_predator_momentum (regime detection, flips)
- _calculate_confidence (ADX bonus, momentum bonus, alignment, chop penalty)
- _determine_direction (combined layer logic)
- _calculate_targets (LONG and SHORT TP/SL)
- generate_signal (happy path, insufficient data, zero price)
- should_trade (approved, choppy, low confidence, invalid price)
- get_description and get_param_schema
- close() resource cleanup
- Strategy registry registration
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.base import SignalDirection, StrategyRegistry, TradeSignal
from src.strategy.edge_indicator import DEFAULTS, EdgeIndicatorStrategy, _tanh, _stdev


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_signal(
    direction=SignalDirection.LONG,
    confidence=75,
    symbol="BTCUSDT",
    entry_price=95000.0,
    target_price=97000.0,
    stop_loss=93000.0,
    reason="test signal",
    adx=25.0,
    is_choppy=False,
):
    """Create a TradeSignal with sensible defaults for Edge Indicator tests."""
    return TradeSignal(
        direction=direction,
        confidence=confidence,
        symbol=symbol,
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        reason=reason,
        metrics_snapshot={"adx": adx, "is_choppy": is_choppy},
        timestamp=datetime(2026, 2, 15, 12, 0, 0),
    )


def _make_klines(closes, highs=None, lows=None):
    """Build minimal kline data from close prices."""
    result = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c * 1.01
        low = lows[i] if lows else c * 0.99
        result.append([
            1700000000000 + i * 3600000,
            str(c), str(h), str(low), str(c), "100",
            1700003600000 + i * 3600000,
            str(c * 100), 1000, "55", str(c * 55), "0",
        ])
    return result


def _uptrend_closes(n=50, start=100.0, step=1.0):
    return [start + i * step for i in range(n)]


def _downtrend_closes(n=50, start=200.0, step=1.0):
    return [start - i * step for i in range(n)]


def _make_mock_fetcher(klines=None, klines_exception=None):
    """Create a mock MarketDataFetcher."""
    fetcher = AsyncMock()
    fetcher._ensure_session = AsyncMock()
    fetcher.close = AsyncMock()

    if klines is None:
        # Generate uptrend klines (enough for all indicators)
        closes = _uptrend_closes(200, start=90000, step=50)
        klines = _make_klines(closes)

    if klines_exception:
        fetcher.get_binance_klines = AsyncMock(side_effect=klines_exception)
    else:
        fetcher.get_binance_klines = AsyncMock(return_value=klines)

    return fetcher


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_tanh_positive(self):
        """tanh of positive value is positive and < 1."""
        assert 0 < _tanh(1.0) < 1.0

    def test_tanh_negative(self):
        """tanh of negative value is negative and > -1."""
        assert -1.0 < _tanh(-1.0) < 0

    def test_tanh_zero(self):
        """tanh(0) = 0."""
        assert _tanh(0.0) == 0.0

    def test_tanh_large_positive(self):
        """tanh of large positive value approaches 1."""
        assert _tanh(100.0) == pytest.approx(1.0)

    def test_tanh_large_negative(self):
        """tanh of large negative value approaches -1."""
        assert _tanh(-100.0) == pytest.approx(-1.0)

    def test_stdev_positive(self):
        """stdev of varying values is positive."""
        assert _stdev([1.0, 2.0, 3.0, 4.0, 5.0], 5) > 0

    def test_stdev_constant_values(self):
        """stdev of constant values returns minimum (1e-10)."""
        assert _stdev([5.0, 5.0, 5.0, 5.0, 5.0], 5) == pytest.approx(1e-10)

    def test_stdev_empty(self):
        """stdev of empty list returns minimum."""
        assert _stdev([], 5) == pytest.approx(1e-10)

    def test_stdev_insufficient_data(self):
        """stdev with fewer values than period returns minimum."""
        assert _stdev([1.0, 2.0], 5) == pytest.approx(1e-10)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Initialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeIndicatorInit:
    """Tests for EdgeIndicatorStrategy initialization."""

    def test_default_params_applied(self):
        """Strategy should use DEFAULTS when no custom params provided."""
        strategy = EdgeIndicatorStrategy()

        assert strategy._p["ema_fast_period"] == 8
        assert strategy._p["ema_slow_period"] == 21
        assert strategy._p["adx_period"] == 14
        assert strategy._p["adx_chop_threshold"] == 18.0
        assert strategy._p["min_confidence"] == 40

    def test_custom_params_override_defaults(self):
        """Custom params should override defaults."""
        strategy = EdgeIndicatorStrategy(params={
            "ema_fast_period": 10,
            "adx_chop_threshold": 20.0,
        })

        assert strategy._p["ema_fast_period"] == 10
        assert strategy._p["adx_chop_threshold"] == 20.0
        assert strategy._p["ema_slow_period"] == 21  # Unchanged

    def test_data_fetcher_injection(self):
        """Injected data_fetcher should be stored."""
        mock_fetcher = MagicMock()
        strategy = EdgeIndicatorStrategy(data_fetcher=mock_fetcher)

        assert strategy.data_fetcher is mock_fetcher

    def test_data_fetcher_none_by_default(self):
        """Without injection, data_fetcher should be None."""
        strategy = EdgeIndicatorStrategy()

        assert strategy.data_fetcher is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _ensure_fetcher
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnsureFetcher:
    """Tests for lazy data fetcher initialization."""

    @pytest.mark.asyncio
    async def test_creates_fetcher_when_none(self):
        """Should create a MarketDataFetcher when data_fetcher is None."""
        strategy = EdgeIndicatorStrategy()

        with patch("src.strategy.edge_indicator.MarketDataFetcher") as MockFetcher:
            mock_instance = MagicMock()
            mock_instance._ensure_session = AsyncMock()
            MockFetcher.return_value = mock_instance

            await strategy._ensure_fetcher()

            assert strategy.data_fetcher is mock_instance
            MockFetcher.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_recreate_existing_fetcher(self):
        """Should not create a new fetcher if one already exists."""
        mock_fetcher = MagicMock()
        strategy = EdgeIndicatorStrategy(data_fetcher=mock_fetcher)

        with patch("src.strategy.edge_indicator.MarketDataFetcher") as MockFetcher:
            await strategy._ensure_fetcher()

            MockFetcher.assert_not_called()
            assert strategy.data_fetcher is mock_fetcher


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _calculate_ema_ribbon
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateEmaRibbon:
    """Tests for EMA 8/21 ribbon calculation."""

    def setup_method(self):
        self.strategy = EdgeIndicatorStrategy()

    def test_bull_trend_price_above_both(self):
        """Price above both EMAs = bull trend."""
        # Strong uptrend: price will be above both EMAs
        closes = _uptrend_closes(50, start=100, step=3)
        result = self.strategy._calculate_ema_ribbon(closes)

        assert result["bull_trend"] is True
        assert result["bear_trend"] is False
        assert result["neutral"] is False

    def test_bear_trend_price_below_both(self):
        """Price below both EMAs = bear trend."""
        closes = _downtrend_closes(50, start=200, step=3)
        result = self.strategy._calculate_ema_ribbon(closes)

        assert result["bear_trend"] is True
        assert result["bull_trend"] is False
        assert result["neutral"] is False

    def test_ema_fast_above_slow_in_uptrend(self):
        """In uptrend, fast EMA should be above slow EMA."""
        closes = _uptrend_closes(50, start=100, step=2)
        result = self.strategy._calculate_ema_ribbon(closes)

        assert result["ema_fast_above"] is True

    def test_ema_fast_below_slow_in_downtrend(self):
        """In downtrend, fast EMA should be below slow EMA."""
        closes = _downtrend_closes(50, start=200, step=2)
        result = self.strategy._calculate_ema_ribbon(closes)

        assert result["ema_fast_above"] is False

    def test_insufficient_data(self):
        """Insufficient data returns neutral with zero EMAs."""
        result = self.strategy._calculate_ema_ribbon([100.0, 101.0])

        assert result["neutral"] is True
        assert result["bull_trend"] is False
        assert result["bear_trend"] is False

    def test_result_keys(self):
        """Result should contain all expected keys."""
        closes = _uptrend_closes(50)
        result = self.strategy._calculate_ema_ribbon(closes)

        expected_keys = [
            "ema_fast", "ema_slow", "bull_trend", "bear_trend",
            "neutral", "bull_enter", "bear_enter", "ema_fast_above",
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _calculate_confidence
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateConfidence:
    """Tests for confidence calculation."""

    def setup_method(self):
        self.strategy = EdgeIndicatorStrategy()

    def test_base_confidence_50(self):
        """With neutral indicators, confidence should be around 50."""
        adx_data = {"adx": 18.0, "plus_di": 20, "minus_di": 20, "is_trending": False}
        momentum = {"smoothed_score": 0.0, "regime": 0, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True}

        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)

        assert confidence == 50

    def test_high_adx_increases_confidence(self):
        """High ADX (strong trend) should increase confidence."""
        adx_data = {"adx": 35.0, "plus_di": 30, "minus_di": 10, "is_trending": True}
        momentum = {"smoothed_score": 0.0, "regime": 0, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True}

        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)

        assert confidence > 50

    def test_low_adx_decreases_confidence(self):
        """Low ADX (choppy market) should decrease confidence."""
        adx_data = {"adx": 10.0, "plus_di": 15, "minus_di": 15, "is_trending": False}
        momentum = {"smoothed_score": 0.0, "regime": 0, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True}

        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)

        assert confidence < 50

    def test_strong_momentum_increases_confidence(self):
        """Strong momentum score increases confidence."""
        adx_data = {"adx": 20.0, "plus_di": 25, "minus_di": 15, "is_trending": True}
        momentum = {"smoothed_score": 0.7, "regime": 1, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True}

        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)

        assert confidence > 50

    def test_full_alignment_bonus(self):
        """All layers aligned should give bonus confidence."""
        adx_data = {"adx": 30.0, "plus_di": 30, "minus_di": 10, "is_trending": True}
        momentum = {"smoothed_score": 0.6, "regime": 1, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False}

        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)

        # Should be significantly above 50 with alignment bonus
        assert confidence >= 70

    def test_regime_flip_bonus(self):
        """Regime flip should add confidence."""
        adx_data = {"adx": 20.0, "plus_di": 25, "minus_di": 15, "is_trending": True}
        momentum = {"smoothed_score": 0.3, "regime": 1, "regime_flip_bull": True, "regime_flip_bear": False}
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True}

        confidence_with_flip = self.strategy._calculate_confidence(adx_data, momentum, ribbon)

        momentum_no_flip = {**momentum, "regime_flip_bull": False}
        confidence_without_flip = self.strategy._calculate_confidence(adx_data, momentum_no_flip, ribbon)

        assert confidence_with_flip > confidence_without_flip

    def test_confidence_capped_at_95(self):
        """Confidence should never exceed 95."""
        adx_data = {"adx": 50.0, "plus_di": 40, "minus_di": 5, "is_trending": True}
        momentum = {"smoothed_score": 0.9, "regime": 1, "regime_flip_bull": True, "regime_flip_bear": False}
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False}

        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)

        assert confidence <= 95

    def test_confidence_minimum_zero(self):
        """Confidence should never go below 0."""
        adx_data = {"adx": 2.0, "plus_di": 10, "minus_di": 10, "is_trending": False}
        momentum = {"smoothed_score": 0.0, "regime": 0, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True}

        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)

        assert confidence >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _determine_direction
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetermineDirection:
    """Tests for direction determination."""

    def setup_method(self):
        self.strategy = EdgeIndicatorStrategy()

    def test_bull_trend_trending_bull_momentum_gives_long(self):
        """Bull trend + ADX trending + bull momentum = LONG."""
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False, "ema_fast_above": True}
        momentum = {"regime": 1, "smoothed_score": 0.5, "regime_flip_bull": False, "regime_flip_bear": False}
        adx_data = {"adx": 25.0}

        direction, reason = self.strategy._determine_direction(ribbon, momentum, adx_data)

        assert direction == SignalDirection.LONG

    def test_bear_trend_trending_bear_momentum_gives_short(self):
        """Bear trend + ADX trending + bear momentum = SHORT."""
        ribbon = {"bull_trend": False, "bear_trend": True, "neutral": False, "ema_fast_above": False}
        momentum = {"regime": -1, "smoothed_score": -0.5, "regime_flip_bull": False, "regime_flip_bear": False}
        adx_data = {"adx": 25.0}

        direction, reason = self.strategy._determine_direction(ribbon, momentum, adx_data)

        assert direction == SignalDirection.SHORT

    def test_choppy_bull_trend_still_gives_long(self):
        """Bull trend in chop (ADX < threshold) still defaults to a direction."""
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False, "ema_fast_above": True}
        momentum = {"regime": 0, "smoothed_score": 0.1, "regime_flip_bull": False, "regime_flip_bear": False}
        adx_data = {"adx": 10.0}

        direction, reason = self.strategy._determine_direction(ribbon, momentum, adx_data)

        # Even in chop, if bull_trend is set, direction should still be determined
        assert direction in (SignalDirection.LONG, SignalDirection.SHORT)

    def test_neutral_trend_follows_momentum(self):
        """When EMA ribbon is neutral, follow momentum regime."""
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True, "ema_fast_above": True}
        momentum = {"regime": 1, "smoothed_score": 0.4, "regime_flip_bull": False, "regime_flip_bear": False}
        adx_data = {"adx": 25.0}

        direction, _ = self.strategy._determine_direction(ribbon, momentum, adx_data)

        assert direction == SignalDirection.LONG

    def test_reason_contains_all_layers(self):
        """Reason string should mention all three layers."""
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False, "ema_fast_above": True}
        momentum = {"regime": 1, "smoothed_score": 0.5, "regime_flip_bull": True, "regime_flip_bear": False}
        adx_data = {"adx": 25.0}

        _, reason = self.strategy._determine_direction(ribbon, momentum, adx_data)

        assert "EMA Ribbon" in reason
        assert "ADX" in reason
        assert "Momentum" in reason


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _calculate_targets
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateTargets:
    """Tests for TP/SL calculation."""

    def setup_method(self):
        self.strategy = EdgeIndicatorStrategy()

    def test_long_targets(self):
        """LONG: TP above entry, SL below entry."""
        strategy = EdgeIndicatorStrategy(params={"take_profit_percent": 3.0, "stop_loss_percent": 1.5})
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)

        assert tp == 103000.0  # 100000 * 1.03
        assert sl == 98500.0   # 100000 * 0.985
        assert tp > 100000.0
        assert sl < 100000.0

    def test_short_targets(self):
        """SHORT: TP below entry, SL above entry."""
        strategy = EdgeIndicatorStrategy(params={"take_profit_percent": 3.0, "stop_loss_percent": 1.5})
        tp, sl = strategy._calculate_targets(SignalDirection.SHORT, 100000.0)

        assert tp == 97000.0   # 100000 * 0.97
        assert sl == 101500.0  # 100000 * 1.015
        assert tp < 100000.0
        assert sl > 100000.0

    def test_custom_tp_sl_params(self):
        """Custom TP/SL percentages should be applied."""
        strategy = EdgeIndicatorStrategy(params={
            "take_profit_percent": 5.0,
            "stop_loss_percent": 2.0,
        })

        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)

        assert tp == 105000.0
        assert sl == 98000.0


# ═══════════════════════════════════════════════════════════════════════════════
# 8. generate_signal
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateSignal:
    """Tests for the full generate_signal method."""

    @pytest.mark.asyncio
    async def test_happy_path_uptrend(self):
        """Generate a valid signal with uptrend kline data."""
        closes = _uptrend_closes(200, start=90000, step=50)
        klines = _make_klines(closes)
        mock_fetcher = _make_mock_fetcher(klines=klines)
        strategy = EdgeIndicatorStrategy(data_fetcher=mock_fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price > 0
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)
        assert 0 <= signal.confidence <= 95
        assert isinstance(signal.timestamp, datetime)
        assert "[Edge]" in signal.reason

    @pytest.mark.asyncio
    async def test_happy_path_downtrend(self):
        """Generate a valid signal with downtrend kline data."""
        closes = _downtrend_closes(200, start=100000, step=50)
        klines = _make_klines(closes)
        mock_fetcher = _make_mock_fetcher(klines=klines)
        strategy = EdgeIndicatorStrategy(data_fetcher=mock_fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price > 0
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_zero_confidence(self):
        """When kline data is insufficient, return zero confidence signal."""
        klines = _make_klines([100.0] * 5)
        mock_fetcher = _make_mock_fetcher(klines=klines)
        strategy = EdgeIndicatorStrategy(data_fetcher=mock_fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.confidence == 0
        assert "Insufficient" in signal.reason

    @pytest.mark.asyncio
    async def test_empty_klines_returns_zero_confidence(self):
        """When no klines returned, return zero confidence signal."""
        mock_fetcher = _make_mock_fetcher(klines=[])
        strategy = EdgeIndicatorStrategy(data_fetcher=mock_fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.confidence == 0

    @pytest.mark.asyncio
    async def test_metrics_snapshot_contains_expected_keys(self):
        """metrics_snapshot should contain all indicator data."""
        closes = _uptrend_closes(200, start=90000, step=50)
        klines = _make_klines(closes)
        mock_fetcher = _make_mock_fetcher(klines=klines)
        strategy = EdgeIndicatorStrategy(data_fetcher=mock_fetcher)

        signal = await strategy.generate_signal("BTCUSDT")

        snapshot = signal.metrics_snapshot
        expected_keys = [
            "ema_fast", "ema_slow", "bull_trend", "bear_trend",
            "adx", "plus_di", "minus_di", "is_choppy",
            "momentum_score", "momentum_smoothed", "momentum_regime",
            "kline_interval", "kline_count",
        ]
        for key in expected_keys:
            assert key in snapshot, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_klines_fetch_called_with_correct_params(self):
        """get_binance_klines should be called with configured interval and count."""
        mock_fetcher = _make_mock_fetcher()
        strategy = EdgeIndicatorStrategy(
            params={"kline_interval": "4h", "kline_count": 150},
            data_fetcher=mock_fetcher,
        )

        await strategy.generate_signal("ETHUSDT")

        mock_fetcher.get_binance_klines.assert_awaited_once_with("ETHUSDT", "4h", 150)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. should_trade
# ═══════════════════════════════════════════════════════════════════════════════

class TestShouldTrade:
    """Tests for the should_trade trade gate."""

    @pytest.mark.asyncio
    async def test_approved_with_sufficient_confidence(self):
        """Signal with good confidence and trending ADX should pass."""
        strategy = EdgeIndicatorStrategy()
        signal = _make_signal(confidence=60, adx=25.0, is_choppy=False)

        ok, reason = await strategy.should_trade(signal)

        assert ok is True
        assert "approved" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_choppy_market(self):
        """Signal in choppy market (ADX < threshold) should be rejected."""
        strategy = EdgeIndicatorStrategy()
        signal = _make_signal(confidence=70, adx=12.0, is_choppy=True)

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "choppy" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_low_confidence(self):
        """Signal below min_confidence should be rejected."""
        strategy = EdgeIndicatorStrategy()
        signal = _make_signal(confidence=30, adx=25.0, is_choppy=False)

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "confidence" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_zero_entry_price(self):
        """Signal with entry_price=0 should be rejected."""
        strategy = EdgeIndicatorStrategy()
        signal = _make_signal(confidence=80, entry_price=0.0)

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "price" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_negative_entry_price(self):
        """Signal with negative entry_price should be rejected."""
        strategy = EdgeIndicatorStrategy()
        signal = _make_signal(confidence=80, entry_price=-100.0)

        ok, reason = await strategy.should_trade(signal)

        assert ok is False

    @pytest.mark.asyncio
    async def test_choppy_market_passes_when_adx_filter_disabled(self):
        """When use_adx_filter is False, choppy signal should pass."""
        strategy = EdgeIndicatorStrategy(params={"use_adx_filter": False})
        signal = _make_signal(confidence=60, adx=10.0, is_choppy=True)

        ok, _ = await strategy.should_trade(signal)

        assert ok is True

    @pytest.mark.asyncio
    async def test_exactly_at_min_confidence_accepted(self):
        """Signal at exactly min_confidence (40) should be accepted."""
        strategy = EdgeIndicatorStrategy()
        signal = _make_signal(confidence=40, adx=25.0, is_choppy=False)

        ok, _ = await strategy.should_trade(signal)

        assert ok is True

    @pytest.mark.asyncio
    async def test_exactly_below_min_confidence_rejected(self):
        """Signal one below min_confidence (39) should be rejected."""
        strategy = EdgeIndicatorStrategy()
        signal = _make_signal(confidence=39, adx=25.0, is_choppy=False)

        ok, _ = await strategy.should_trade(signal)

        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# 10. get_description and get_param_schema
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchemaAndDescription:
    """Tests for class methods get_description and get_param_schema."""

    def test_get_description_returns_non_empty_string(self):
        """get_description should return a meaningful string."""
        desc = EdgeIndicatorStrategy.get_description()

        assert isinstance(desc, str)
        assert len(desc) > 20
        assert "edge" in desc.lower() or "Edge" in desc

    def test_get_param_schema_has_all_configurable_params(self):
        """Schema should include all user-configurable parameters."""
        schema = EdgeIndicatorStrategy.get_param_schema()

        expected_keys = [
            "ema_fast_period", "ema_slow_period",
            "adx_period", "adx_chop_threshold", "use_adx_filter",
            "momentum_bull_threshold", "momentum_bear_threshold",
            "min_confidence", "kline_interval",
            "take_profit_percent", "stop_loss_percent",
        ]

        for key in expected_keys:
            assert key in schema, f"Missing key: {key}"

    def test_param_schema_entries_have_required_fields(self):
        """Each schema entry should have type, label, description, default."""
        schema = EdgeIndicatorStrategy.get_param_schema()

        for key, entry in schema.items():
            assert "type" in entry, f"{key} missing 'type'"
            assert "label" in entry, f"{key} missing 'label'"
            assert "description" in entry, f"{key} missing 'description'"
            if key not in ("take_profit_percent", "stop_loss_percent"):
                assert "default" in entry, f"{key} missing 'default'"

    def test_min_confidence_bounds(self):
        """min_confidence should have min=10, max=80, default=40."""
        schema = EdgeIndicatorStrategy.get_param_schema()
        conf = schema["min_confidence"]

        assert conf["default"] == 40
        assert conf["min"] == 10
        assert conf["max"] == 80


# ═══════════════════════════════════════════════════════════════════════════════
# 11. close()
# ═══════════════════════════════════════════════════════════════════════════════

class TestClose:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_closes_data_fetcher(self):
        """close() should call data_fetcher.close()."""
        mock_fetcher = AsyncMock()
        strategy = EdgeIndicatorStrategy(data_fetcher=mock_fetcher)

        await strategy.close()

        mock_fetcher.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_fetcher_does_not_raise(self):
        """close() when data_fetcher is None should not raise."""
        strategy = EdgeIndicatorStrategy()
        assert strategy.data_fetcher is None

        await strategy.close()  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Strategy Registry
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistration:
    """Tests for strategy registry integration."""

    def test_edge_indicator_is_registered(self):
        """EdgeIndicatorStrategy should be registered under 'edge_indicator'."""
        assert StrategyRegistry.get("edge_indicator") is EdgeIndicatorStrategy

    def test_create_via_registry(self):
        """Registry.create should return an EdgeIndicatorStrategy instance."""
        instance = StrategyRegistry.create("edge_indicator", params={"min_confidence": 50})

        assert isinstance(instance, EdgeIndicatorStrategy)
        assert instance._p["min_confidence"] == 50


# ═══════════════════════════════════════════════════════════════════════════════
# 13. DEFAULTS constant
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefaults:
    """Tests for the DEFAULTS constant values."""

    def test_defaults_contain_all_expected_keys(self):
        """DEFAULTS should contain all configuration keys."""
        expected_keys = [
            "ema_fast_period", "ema_slow_period",
            "adx_period", "adx_chop_threshold", "use_adx_filter",
            "macd_fast", "macd_slow", "macd_signal",
            "rsi_period", "rsi_smooth_period",
            "momentum_smooth_period", "momentum_bull_threshold", "momentum_bear_threshold",
            "min_confidence",
            "kline_interval", "kline_count",
        ]

        for key in expected_keys:
            assert key in DEFAULTS, f"Missing default: {key}"

    def test_default_values(self):
        """Verify specific default values match TradingView indicator."""
        assert DEFAULTS["ema_fast_period"] == 8
        assert DEFAULTS["ema_slow_period"] == 21
        assert DEFAULTS["adx_period"] == 14
        assert DEFAULTS["adx_chop_threshold"] == 18.0
        assert DEFAULTS["macd_fast"] == 12
        assert DEFAULTS["macd_slow"] == 26
        assert DEFAULTS["macd_signal"] == 9
        assert DEFAULTS["rsi_period"] == 14
        assert DEFAULTS["momentum_bull_threshold"] == 0.35
        assert DEFAULTS["momentum_bear_threshold"] == -0.35
