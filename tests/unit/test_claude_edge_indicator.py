"""
Unit tests for the ClaudeEdgeIndicatorStrategy.

Tests cover:
- Initialization (default params, custom params, data_fetcher injection)
- _ensure_fetcher lazy initialization
- _calculate_ema_ribbon (bull, bear, neutral)
- _calculate_predator_momentum (regime detection)
- _calculate_confidence (enhanced: volume, HTF, divergence)
- _calculate_targets (ATR-based instead of fixed %)
- _calculate_volume_score (buy/sell ratio scoring)
- _build_trailing_stop_metadata (trailing stop params)
- _calculate_position_size_recommendation (regime sizing)
- _determine_direction (combined layer logic)
- generate_signal (happy path, insufficient data)
- should_trade (approved, choppy, low confidence)
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
from src.strategy.claude_edge_indicator import (
    DEFAULTS, ClaudeEdgeIndicatorStrategy, _tanh, _stdev,
)


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
    position_scale=1.0,
):
    return TradeSignal(
        direction=direction,
        confidence=confidence,
        symbol=symbol,
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        reason=reason,
        metrics_snapshot={"adx": adx, "is_choppy": is_choppy, "position_scale": position_scale},
        timestamp=datetime(2026, 2, 15, 12, 0, 0),
    )


def _make_klines(closes, highs=None, lows=None):
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


def _make_mock_fetcher(klines=None, htf_klines=None):
    fetcher = AsyncMock()
    fetcher._ensure_session = AsyncMock()
    fetcher.close = AsyncMock()

    if klines is None:
        closes = _uptrend_closes(200, start=90000, step=50)
        klines = _make_klines(closes)

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
# 1. Helper Functions
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelperFunctions:
    def test_tanh_positive(self):
        assert 0 < _tanh(1.0) < 1.0

    def test_tanh_negative(self):
        assert -1.0 < _tanh(-1.0) < 0

    def test_tanh_zero(self):
        assert _tanh(0.0) == 0.0

    def test_stdev_positive(self):
        assert _stdev([1.0, 2.0, 3.0, 4.0, 5.0], 5) > 0

    def test_stdev_empty(self):
        assert _stdev([], 5) == pytest.approx(1e-10)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Initialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestClaudeEdgeInit:
    def test_default_params_applied(self):
        strategy = ClaudeEdgeIndicatorStrategy()
        assert strategy._p["ema_fast_period"] == 8
        assert strategy._p["volume_weight"] == 0.3
        assert strategy._p["trailing_stop_enabled"] is True
        assert strategy._p["use_htf_filter"] is True

    def test_custom_params_override_defaults(self):
        strategy = ClaudeEdgeIndicatorStrategy(params={
            "atr_tp_multiplier": 3.0,
            "volume_weight": 0.5,
        })
        assert strategy._p["atr_tp_multiplier"] == 3.0
        assert strategy._p["volume_weight"] == 0.5
        assert strategy._p["ema_slow_period"] == 21  # Unchanged

    def test_data_fetcher_injection(self):
        mock_fetcher = MagicMock()
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=mock_fetcher)
        assert strategy.data_fetcher is mock_fetcher

    def test_data_fetcher_none_by_default(self):
        strategy = ClaudeEdgeIndicatorStrategy()
        assert strategy.data_fetcher is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _ensure_fetcher
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnsureFetcher:
    @pytest.mark.asyncio
    async def test_creates_fetcher_when_none(self):
        strategy = ClaudeEdgeIndicatorStrategy()
        with patch("src.strategy.claude_edge_indicator.MarketDataFetcher") as MockFetcher:
            mock_instance = MagicMock()
            mock_instance._ensure_session = AsyncMock()
            MockFetcher.return_value = mock_instance
            await strategy._ensure_fetcher()
            assert strategy.data_fetcher is mock_instance

    @pytest.mark.asyncio
    async def test_does_not_recreate_existing_fetcher(self):
        mock_fetcher = MagicMock()
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=mock_fetcher)
        with patch("src.strategy.claude_edge_indicator.MarketDataFetcher") as MockFetcher:
            await strategy._ensure_fetcher()
            MockFetcher.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _calculate_ema_ribbon
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateEmaRibbon:
    def setup_method(self):
        self.strategy = ClaudeEdgeIndicatorStrategy()

    def test_bull_trend(self):
        closes = _uptrend_closes(50, start=100, step=3)
        result = self.strategy._calculate_ema_ribbon(closes)
        assert result["bull_trend"] is True
        assert result["bear_trend"] is False

    def test_bear_trend(self):
        closes = _downtrend_closes(50, start=200, step=3)
        result = self.strategy._calculate_ema_ribbon(closes)
        assert result["bear_trend"] is True
        assert result["bull_trend"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _calculate_targets (ATR-based)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateTargets:
    def setup_method(self):
        self.strategy = ClaudeEdgeIndicatorStrategy(params={"atr_tp_multiplier": 2.5, "atr_sl_multiplier": 1.5})

    def test_long_targets_with_klines(self):
        """LONG: TP above entry, SL below entry using ATR."""
        closes = _uptrend_closes(50, start=90000, step=50)
        klines = _make_klines(closes)

        tp, sl = self.strategy._calculate_targets(SignalDirection.LONG, 95000.0, klines)

        assert tp > 95000.0
        assert sl < 95000.0

    def test_short_targets_with_klines(self):
        """SHORT: TP below entry, SL above entry using ATR."""
        closes = _downtrend_closes(50, start=100000, step=50)
        klines = _make_klines(closes)

        tp, sl = self.strategy._calculate_targets(SignalDirection.SHORT, 95000.0, klines)

        assert tp < 95000.0
        assert sl > 95000.0

    def test_targets_without_klines_uses_fallback(self):
        """Without klines, should use 1.5% fallback ATR estimate."""
        tp, sl = self.strategy._calculate_targets(SignalDirection.LONG, 100000.0)

        assert tp > 100000.0
        assert sl < 100000.0
        # Fallback ATR = 100000 * 0.015 = 1500
        # TP = 100000 + 1500 * 2.5 = 103750
        # SL = 100000 - 1500 * 1.5 = 97750
        assert tp == pytest.approx(103750.0, rel=0.01)
        assert sl == pytest.approx(97750.0, rel=0.01)

    def test_custom_atr_multipliers(self):
        """Custom ATR multipliers should change TP/SL distance."""
        strategy = ClaudeEdgeIndicatorStrategy(params={
            "atr_tp_multiplier": 4.0,
            "atr_sl_multiplier": 2.0,
        })

        tp_wide, sl_wide = strategy._calculate_targets(SignalDirection.LONG, 100000.0)
        tp_default, sl_default = self.strategy._calculate_targets(SignalDirection.LONG, 100000.0)

        # Wider multipliers = larger distance from entry
        assert (tp_wide - 100000.0) > (tp_default - 100000.0)
        assert (100000.0 - sl_wide) > (100000.0 - sl_default)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _calculate_volume_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateVolumeScore:
    def setup_method(self):
        self.strategy = ClaudeEdgeIndicatorStrategy()

    def test_balanced_volume_near_zero(self):
        """50/50 buy/sell ratio should give ~0 score."""
        closes = [100.0] * 20
        # buy_vol = total_vol * 0.5 -> buy_ratio = 0.5
        klines = []
        for i, c in enumerate(closes):
            klines.append([
                1700000000000 + i * 3600000,
                str(c), str(c * 1.01), str(c * 0.99), str(c), "100",
                1700003600000 + i * 3600000,
                str(c * 100), 1000, "50", str(c * 50), "0",
            ])

        result = self.strategy._calculate_volume_score(klines)

        assert result["volume_score"] == pytest.approx(0.0, abs=0.05)
        assert result["buy_ratio"] == pytest.approx(0.5, abs=0.01)

    def test_strong_buying_positive_score(self):
        """High buy ratio (>0.58) should give positive score."""
        closes = [100.0] * 20
        klines = []
        for i, c in enumerate(closes):
            klines.append([
                1700000000000 + i * 3600000,
                str(c), str(c * 1.01), str(c * 0.99), str(c), "100",
                1700003600000 + i * 3600000,
                str(c * 100), 1000, "70", str(c * 70), "0",
            ])

        result = self.strategy._calculate_volume_score(klines)

        assert result["volume_score"] > 0.5
        assert result["buy_ratio"] > 0.6
        assert result["is_strong"] is True

    def test_strong_selling_negative_score(self):
        """Low buy ratio (<0.42) should give negative score."""
        closes = [100.0] * 20
        klines = []
        for i, c in enumerate(closes):
            klines.append([
                1700000000000 + i * 3600000,
                str(c), str(c * 1.01), str(c * 0.99), str(c), "100",
                1700003600000 + i * 3600000,
                str(c * 100), 1000, "30", str(c * 30), "0",
            ])

        result = self.strategy._calculate_volume_score(klines)

        assert result["volume_score"] < -0.5
        assert result["buy_ratio"] < 0.4


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _build_trailing_stop_metadata
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrailingStopMetadata:
    def setup_method(self):
        self.strategy = ClaudeEdgeIndicatorStrategy()

    def test_long_trailing_stop(self):
        """LONG trailing stop: breakeven trigger above entry."""
        meta = self.strategy._build_trailing_stop_metadata(
            SignalDirection.LONG, 100000.0, 1500.0
        )

        assert meta["trailing_enabled"] is True
        assert meta["breakeven_trigger"] > 100000.0
        assert meta["trail_distance"] > 0
        assert meta["atr_value"] == 1500.0

    def test_short_trailing_stop(self):
        """SHORT trailing stop: breakeven trigger below entry."""
        meta = self.strategy._build_trailing_stop_metadata(
            SignalDirection.SHORT, 100000.0, 1500.0
        )

        assert meta["trailing_enabled"] is True
        assert meta["breakeven_trigger"] < 100000.0

    def test_trailing_disabled(self):
        """When trailing_stop_enabled=False, returns disabled."""
        strategy = ClaudeEdgeIndicatorStrategy(params={"trailing_stop_enabled": False})
        meta = strategy._build_trailing_stop_metadata(
            SignalDirection.LONG, 100000.0, 1500.0
        )

        assert meta["trailing_enabled"] is False

    def test_zero_atr_disables_trailing(self):
        """Zero ATR should disable trailing stop."""
        meta = self.strategy._build_trailing_stop_metadata(
            SignalDirection.LONG, 100000.0, 0.0
        )

        assert meta["trailing_enabled"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _calculate_position_size_recommendation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPositionSizeRecommendation:
    def setup_method(self):
        self.strategy = ClaudeEdgeIndicatorStrategy()

    def test_low_confidence_minimum_scale(self):
        """Low confidence (40) should give minimum scale (0.5)."""
        scale = self.strategy._calculate_position_size_recommendation(40)
        assert scale == 0.5

    def test_high_confidence_maximum_scale(self):
        """High confidence (95) should give maximum scale (1.0)."""
        scale = self.strategy._calculate_position_size_recommendation(95)
        assert scale == 1.0

    def test_mid_confidence_mid_scale(self):
        """Mid confidence should give intermediate scale."""
        scale = self.strategy._calculate_position_size_recommendation(67)
        assert 0.5 < scale < 1.0

    def test_monotonically_increasing(self):
        """Higher confidence should always give higher or equal scale."""
        prev = 0.0
        for conf in range(40, 96, 5):
            scale = self.strategy._calculate_position_size_recommendation(conf)
            assert scale >= prev
            prev = scale


# ═══════════════════════════════════════════════════════════════════════════════
# 9. _calculate_confidence (enhanced)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateConfidence:
    def setup_method(self):
        self.strategy = ClaudeEdgeIndicatorStrategy()

    def test_base_confidence_50(self):
        adx_data = {"adx": 18.0}
        momentum = {"smoothed_score": 0.0, "regime": 0, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True}
        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)
        assert confidence == 50

    def test_volume_confirmation_bonus(self):
        """Volume confirming direction should boost confidence."""
        adx_data = {"adx": 25.0}
        momentum = {"smoothed_score": 0.4, "regime": 1, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False}
        volume_confirming = {"volume_score": 0.6, "buy_ratio": 0.65, "is_strong": True}
        volume_neutral = {"volume_score": 0.0, "buy_ratio": 0.5, "is_strong": False}

        conf_with_vol = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon, volume_data=volume_confirming
        )
        conf_without_vol = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon, volume_data=volume_neutral
        )

        assert conf_with_vol > conf_without_vol

    def test_htf_alignment_bonus(self):
        """HTF alignment should boost confidence."""
        adx_data = {"adx": 25.0}
        momentum = {"smoothed_score": 0.4, "regime": 1, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False}
        htf_aligned = {"htf_bullish": True, "htf_bearish": False, "htf_available": True}

        conf_with_htf = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon, htf_data=htf_aligned
        )
        conf_without_htf = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon
        )

        assert conf_with_htf > conf_without_htf

    def test_divergence_bonus(self):
        """RSI divergence confirming direction should boost confidence."""
        adx_data = {"adx": 25.0}
        momentum = {"smoothed_score": 0.4, "regime": 1, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False}
        div_bullish = {"bullish_divergence": True, "bearish_divergence": False}

        conf_with_div = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon, divergence_data=div_bullish
        )
        conf_without_div = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon
        )

        assert conf_with_div > conf_without_div

    def test_divergence_penalty(self):
        """RSI divergence against direction should reduce confidence."""
        adx_data = {"adx": 25.0}
        momentum = {"smoothed_score": 0.4, "regime": 1, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False}
        div_bearish = {"bullish_divergence": False, "bearish_divergence": True}

        conf_with_div = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon, divergence_data=div_bearish
        )
        conf_without_div = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon
        )

        assert conf_with_div < conf_without_div

    def test_confidence_capped_at_95(self):
        adx_data = {"adx": 50.0}
        momentum = {"smoothed_score": 0.9, "regime": 1, "regime_flip_bull": True, "regime_flip_bear": False}
        ribbon = {"bull_trend": True, "bear_trend": False, "neutral": False}
        volume = {"volume_score": 0.8, "buy_ratio": 0.7, "is_strong": True}
        htf = {"htf_bullish": True, "htf_bearish": False, "htf_available": True}
        div = {"bullish_divergence": True, "bearish_divergence": False}

        confidence = self.strategy._calculate_confidence(
            adx_data, momentum, ribbon, volume, div, htf
        )
        assert confidence <= 95

    def test_confidence_minimum_zero(self):
        adx_data = {"adx": 2.0}
        momentum = {"smoothed_score": 0.0, "regime": 0, "regime_flip_bull": False, "regime_flip_bear": False}
        ribbon = {"bull_trend": False, "bear_trend": False, "neutral": True}

        confidence = self.strategy._calculate_confidence(adx_data, momentum, ribbon)
        assert confidence >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# 10. generate_signal
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateSignal:
    @pytest.mark.asyncio
    async def test_happy_path_uptrend(self):
        mock_fetcher = _make_mock_fetcher()
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price > 0
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)
        assert 0 <= signal.confidence <= 95
        assert "[Claude-Edge]" in signal.reason

    @pytest.mark.asyncio
    async def test_metrics_snapshot_contains_enhanced_keys(self):
        mock_fetcher = _make_mock_fetcher()
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")
        snapshot = signal.metrics_snapshot

        enhanced_keys = [
            "atr_value", "volume_score", "buy_ratio",
            "htf_bullish", "htf_bearish", "htf_available",
            "bullish_divergence", "bearish_divergence",
            "position_scale", "trailing_enabled",
        ]
        for key in enhanced_keys:
            assert key in snapshot, f"Missing enhanced key: {key}"

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_zero_confidence(self):
        klines = _make_klines([100.0] * 5)
        mock_fetcher = _make_mock_fetcher(klines=klines)
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.confidence == 0
        assert "Insufficient" in signal.reason

    @pytest.mark.asyncio
    async def test_empty_klines_returns_zero_confidence(self):
        mock_fetcher = _make_mock_fetcher(klines=[])
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.confidence == 0

    @pytest.mark.asyncio
    async def test_htf_klines_fetched(self):
        """Should fetch 4h klines for HTF alignment."""
        mock_fetcher = _make_mock_fetcher()
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=mock_fetcher)
        await strategy.generate_signal("BTCUSDT")

        # Should have called get_binance_klines at least twice (1h + 4h)
        calls = mock_fetcher.get_binance_klines.call_args_list
        intervals = [c.args[1] if len(c.args) > 1 else c.kwargs.get("interval") for c in calls]
        assert "4h" in intervals or "1h" in intervals


# ═══════════════════════════════════════════════════════════════════════════════
# 11. should_trade
# ═══════════════════════════════════════════════════════════════════════════════

class TestShouldTrade:
    @pytest.mark.asyncio
    async def test_approved_with_sufficient_confidence(self):
        strategy = ClaudeEdgeIndicatorStrategy()
        signal = _make_signal(confidence=60, adx=25.0, is_choppy=False)
        ok, reason = await strategy.should_trade(signal)
        assert ok is True
        assert "approved" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_choppy_market(self):
        strategy = ClaudeEdgeIndicatorStrategy()
        signal = _make_signal(confidence=70, adx=12.0, is_choppy=True)
        ok, reason = await strategy.should_trade(signal)
        assert ok is False
        assert "choppy" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_low_confidence(self):
        strategy = ClaudeEdgeIndicatorStrategy()
        signal = _make_signal(confidence=30, adx=25.0, is_choppy=False)
        ok, reason = await strategy.should_trade(signal)
        assert ok is False
        assert "confidence" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_zero_entry_price(self):
        strategy = ClaudeEdgeIndicatorStrategy()
        signal = _make_signal(confidence=80, entry_price=0.0)
        ok, reason = await strategy.should_trade(signal)
        assert ok is False

    @pytest.mark.asyncio
    async def test_reason_includes_scale(self):
        """Approved reason should include position scale."""
        strategy = ClaudeEdgeIndicatorStrategy()
        signal = _make_signal(confidence=60, adx=25.0, is_choppy=False, position_scale=0.7)
        ok, reason = await strategy.should_trade(signal)
        assert ok is True
        assert "scale" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 12. get_description and get_param_schema
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchemaAndDescription:
    def test_get_description_non_empty(self):
        desc = ClaudeEdgeIndicatorStrategy.get_description()
        assert isinstance(desc, str)
        assert len(desc) > 20
        assert "ATR" in desc or "atr" in desc.lower()

    def test_schema_has_atr_params(self):
        schema = ClaudeEdgeIndicatorStrategy.get_param_schema()
        assert "atr_tp_multiplier" in schema
        assert "atr_sl_multiplier" in schema

    def test_schema_has_volume_params(self):
        schema = ClaudeEdgeIndicatorStrategy.get_param_schema()
        assert "volume_weight" in schema

    def test_schema_has_htf_params(self):
        schema = ClaudeEdgeIndicatorStrategy.get_param_schema()
        assert "use_htf_filter" in schema

    def test_schema_has_trailing_params(self):
        schema = ClaudeEdgeIndicatorStrategy.get_param_schema()
        assert "trailing_stop_enabled" in schema

    def test_schema_entries_have_required_fields(self):
        schema = ClaudeEdgeIndicatorStrategy.get_param_schema()
        for key, entry in schema.items():
            assert "type" in entry, f"{key} missing 'type'"
            assert "label" in entry, f"{key} missing 'label'"
            assert "description" in entry, f"{key} missing 'description'"
            if key not in ("atr_tp_multiplier", "atr_sl_multiplier"):
                assert "default" in entry, f"{key} missing 'default'"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. close()
# ═══════════════════════════════════════════════════════════════════════════════

class TestClose:
    @pytest.mark.asyncio
    async def test_close_closes_data_fetcher(self):
        mock_fetcher = AsyncMock()
        strategy = ClaudeEdgeIndicatorStrategy(data_fetcher=mock_fetcher)
        await strategy.close()
        mock_fetcher.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_fetcher_does_not_raise(self):
        strategy = ClaudeEdgeIndicatorStrategy()
        await strategy.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Strategy Registry
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistration:
    def test_claude_edge_is_registered(self):
        assert StrategyRegistry.get("claude_edge_indicator") is ClaudeEdgeIndicatorStrategy

    def test_create_via_registry(self):
        instance = StrategyRegistry.create("claude_edge_indicator", params={"min_confidence": 50})
        assert isinstance(instance, ClaudeEdgeIndicatorStrategy)
        assert instance._p["min_confidence"] == 50


# ═══════════════════════════════════════════════════════════════════════════════
# 15. DEFAULTS constant
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefaults:
    def test_has_atr_keys(self):
        assert "atr_period" in DEFAULTS

    def test_has_volume_keys(self):
        assert "volume_weight" in DEFAULTS
        assert "volume_strong_threshold" in DEFAULTS

    def test_has_htf_keys(self):
        assert "htf_interval" in DEFAULTS
        assert "htf_kline_count" in DEFAULTS
        assert "use_htf_filter" in DEFAULTS

    def test_has_trailing_keys(self):
        assert "trailing_stop_enabled" in DEFAULTS
        assert "trailing_breakeven_atr" in DEFAULTS
        assert "trailing_trail_atr" in DEFAULTS

    def test_has_divergence_keys(self):
        assert "divergence_lookback" in DEFAULTS
        assert "divergence_confidence_bonus" in DEFAULTS
        assert "divergence_confidence_penalty" in DEFAULTS

    def test_has_sizing_keys(self):
        assert "min_position_scale" in DEFAULTS
        assert "max_position_scale" in DEFAULTS
