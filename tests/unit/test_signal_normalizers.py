"""
Tests for the Signal Normalizers module.
"""

import pytest

from src.signals.normalizers import (
    SignalNormalizer,
    normalize_fear_greed,
    normalize_funding_rate,
    normalize_long_short_ratio,
    normalize_open_interest_change,
    normalize_price_momentum,
    normalize_rsi,
    normalize_volume_profile,
    normalize_liquidation_imbalance,
)


class TestNormalizeFearGreed:
    """Tests for Fear & Greed normalizer."""

    def test_extreme_fear_gives_long_signal(self):
        """Extreme fear should produce a strong long signal (contrarian)."""
        result = normalize_fear_greed(10)
        assert result.normalized > 0.5
        assert result.strength in ("strong", "moderate")
        assert "fear" in result.description.lower()

    def test_extreme_greed_gives_short_signal(self):
        """Extreme greed should produce a strong short signal (contrarian)."""
        result = normalize_fear_greed(90)
        assert result.normalized < -0.5
        assert result.strength in ("strong", "moderate")
        assert "greed" in result.description.lower()

    def test_neutral_gives_near_zero(self):
        """Neutral sentiment (50) should give near-zero signal."""
        result = normalize_fear_greed(50)
        assert abs(result.normalized) < 0.1

    def test_output_range(self):
        """All outputs should be in [-1, 1]."""
        for i in range(0, 101, 10):
            result = normalize_fear_greed(i)
            assert -1.0 <= result.normalized <= 1.0

    def test_clamped_input(self):
        """Out-of-range inputs should be clamped."""
        r1 = normalize_fear_greed(-10)
        r2 = normalize_fear_greed(0)
        assert r1.normalized == r2.normalized

    def test_returns_signal_normalizer(self):
        """Should return proper dataclass."""
        result = normalize_fear_greed(50)
        assert isinstance(result, SignalNormalizer)
        assert result.name == "fear_greed"


class TestNormalizeFundingRate:
    """Tests for Funding Rate normalizer."""

    def test_high_positive_rate_gives_short(self):
        """High funding rate -> contrarian short."""
        result = normalize_funding_rate(0.001)
        assert result.normalized < 0
        assert "contrarian short" in result.description

    def test_negative_rate_gives_long(self):
        """Negative funding rate -> contrarian long."""
        result = normalize_funding_rate(-0.0005)
        assert result.normalized > 0
        assert "contrarian long" in result.description

    def test_neutral_rate(self):
        """Small rate near zero should be weak/neutral."""
        result = normalize_funding_rate(0.0001)
        assert abs(result.normalized) < 0.3

    def test_output_range(self):
        """Output should be in [-1, 1]."""
        for rate in [-0.01, -0.001, 0, 0.001, 0.01]:
            result = normalize_funding_rate(rate)
            assert -1.0 <= result.normalized <= 1.0


class TestNormalizeLongShortRatio:
    """Tests for Long/Short Ratio normalizer."""

    def test_crowded_longs_gives_short(self):
        """Crowded longs should produce short signal (contrarian)."""
        result = normalize_long_short_ratio(3.0)
        assert result.normalized < -0.5
        assert "crowded longs" in result.description.lower()

    def test_crowded_shorts_gives_long(self):
        """Crowded shorts should produce long signal (contrarian)."""
        result = normalize_long_short_ratio(0.3)
        assert result.normalized > 0.5
        assert "crowded shorts" in result.description.lower()

    def test_balanced_ratio(self):
        """Balanced ratio (~1.0) should be near neutral."""
        result = normalize_long_short_ratio(1.0)
        assert abs(result.normalized) < 0.1

    def test_output_range(self):
        """Output should be in [-1, 1]."""
        for ratio in [0.1, 0.5, 1.0, 2.0, 5.0]:
            result = normalize_long_short_ratio(ratio)
            assert -1.0 <= result.normalized <= 1.0


class TestNormalizeOpenInterestChange:
    """Tests for Open Interest change normalizer."""

    def test_rising_oi(self):
        """Rising OI should indicate conviction (positive signal)."""
        result = normalize_open_interest_change(10.0)
        assert result.normalized > 0
        assert "rising" in result.description.lower()

    def test_falling_oi(self):
        """Falling OI should indicate unwinding (negative signal)."""
        result = normalize_open_interest_change(-10.0)
        assert result.normalized < 0
        assert "falling" in result.description.lower()

    def test_stable_oi(self):
        """Stable OI should be near neutral."""
        result = normalize_open_interest_change(1.0)
        assert abs(result.normalized) < 0.3

    def test_output_range(self):
        """Output should be in [-1, 1]."""
        for pct in [-20, -5, 0, 5, 20]:
            result = normalize_open_interest_change(pct)
            assert -1.0 <= result.normalized <= 1.0


class TestNormalizePriceMomentum:
    """Tests for Price Momentum normalizer."""

    def test_strong_upward(self):
        """Strong upward move should give long signal."""
        result = normalize_price_momentum(8.0)
        assert result.normalized > 0.5
        assert "upward" in result.description.lower()

    def test_strong_downward(self):
        """Strong downward move should give short signal."""
        result = normalize_price_momentum(-8.0)
        assert result.normalized < -0.5
        assert "downward" in result.description.lower()

    def test_flat(self):
        """Flat price should be near neutral."""
        result = normalize_price_momentum(0.5)
        assert abs(result.normalized) < 0.3

    def test_output_range(self):
        for pct in [-15, -5, 0, 5, 15]:
            result = normalize_price_momentum(pct)
            assert -1.0 <= result.normalized <= 1.0


class TestNormalizeRSI:
    """Tests for RSI normalizer."""

    def test_oversold_gives_long(self):
        """Oversold RSI should give long signal."""
        result = normalize_rsi(20)
        assert result.normalized > 0.5
        assert "oversold" in result.description.lower()

    def test_overbought_gives_short(self):
        """Overbought RSI should give short signal."""
        result = normalize_rsi(80)
        assert result.normalized < -0.5
        assert "overbought" in result.description.lower()

    def test_neutral_rsi(self):
        """Neutral RSI should be near zero."""
        result = normalize_rsi(50)
        assert abs(result.normalized) < 0.1

    def test_clamped_input(self):
        """Out-of-range inputs should be clamped."""
        r1 = normalize_rsi(-10)
        r2 = normalize_rsi(0)
        assert r1.normalized == r2.normalized

    def test_output_range(self):
        for rsi in [0, 20, 30, 50, 70, 80, 100]:
            result = normalize_rsi(rsi)
            assert -1.0 <= result.normalized <= 1.0


class TestNormalizeVolumeProfile:
    """Tests for Volume Profile normalizer."""

    def test_high_buy_volume(self):
        """High buy volume ratio should be bullish."""
        result = normalize_volume_profile(0.75)
        assert result.normalized > 0.3
        assert "buy" in result.description.lower()

    def test_high_sell_volume(self):
        """High sell volume ratio should be bearish."""
        result = normalize_volume_profile(0.25)
        assert result.normalized < -0.3
        assert "sell" in result.description.lower()

    def test_balanced_volume(self):
        """Balanced volume should be near neutral."""
        result = normalize_volume_profile(0.50)
        assert abs(result.normalized) < 0.1

    def test_output_range(self):
        for ratio in [0.0, 0.25, 0.5, 0.75, 1.0]:
            result = normalize_volume_profile(ratio)
            assert -1.0 <= result.normalized <= 1.0


class TestNormalizeLiquidationImbalance:
    """Tests for Liquidation Imbalance normalizer."""

    def test_long_liquidation_cascade(self):
        """More long liquidations -> contrarian long signal."""
        result = normalize_liquidation_imbalance(800000, 200000)
        assert result.normalized > 0.3
        assert "long liquidation" in result.description.lower()

    def test_short_liquidation_cascade(self):
        """More short liquidations -> contrarian short signal."""
        result = normalize_liquidation_imbalance(200000, 800000)
        assert result.normalized < -0.3
        assert "short liquidation" in result.description.lower()

    def test_balanced_liquidations(self):
        """Equal liquidations should be neutral."""
        result = normalize_liquidation_imbalance(500000, 500000)
        assert abs(result.normalized) < 0.1

    def test_no_liquidations(self):
        """No liquidation data should be neutral."""
        result = normalize_liquidation_imbalance(0, 0)
        assert result.normalized == 0.0
        assert result.strength == "neutral"

    def test_output_range(self):
        for l, s in [(1000, 0), (0, 1000), (500, 500), (700, 300)]:
            result = normalize_liquidation_imbalance(l, s)
            assert -1.0 <= result.normalized <= 1.0


class TestSignalNormalizerDataclass:
    """Tests for SignalNormalizer dataclass."""

    def test_to_dict(self):
        """Test serialization."""
        sn = SignalNormalizer(
            name="test",
            raw_value=42.0,
            normalized=0.5,
            strength="moderate",
            description="Test signal",
        )
        d = sn.to_dict()
        assert d["name"] == "test"
        assert d["raw_value"] == 42.0
        assert d["normalized"] == 0.5
        assert d["strength"] == "moderate"
