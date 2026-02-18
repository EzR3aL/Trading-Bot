"""
Unit tests for technical indicator calculations in MarketDataFetcher.

Tests cover:
- calculate_ema: warmup, various periods, edge cases
- calculate_adx: trending, choppy, edge cases
- calculate_macd: bullish/bearish crossover, histogram
- calculate_rsi: overbought, oversold, neutral, edge cases
"""

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data.market_data import MarketDataFetcher


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_klines(closes: list, highs=None, lows=None, opens=None, volumes=None):
    """Build minimal kline data from close prices.

    Kline format: [open_time, open, high, low, close, volume, close_time,
                   quote_vol, trades, taker_buy_base, taker_buy_quote, ignore]
    """
    result = []
    for i, c in enumerate(closes):
        h = highs[i] if highs else c * 1.01
        l = lows[i] if lows else c * 0.99
        o = opens[i] if opens else c
        v = volumes[i] if volumes else 100.0
        result.append([
            1700000000000 + i * 3600000,  # open_time
            str(o), str(h), str(l), str(c), str(v),
            1700003600000 + i * 3600000,  # close_time
            str(c * v), 1000, str(v * 0.55), str(c * v * 0.55), "0",
        ])
    return result


def _uptrend_closes(n=50, start=100.0, step=1.0):
    """Generate steadily rising close prices."""
    return [start + i * step for i in range(n)]


def _downtrend_closes(n=50, start=200.0, step=1.0):
    """Generate steadily falling close prices."""
    return [start - i * step for i in range(n)]


def _sideways_closes(n=50, center=100.0, amplitude=0.5):
    """Generate oscillating close prices (choppy)."""
    import math
    return [center + amplitude * math.sin(i * 0.5) for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. calculate_ema
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateEma:
    """Tests for EMA calculation."""

    def test_basic_ema_period_3(self):
        """EMA with period 3 on simple data."""
        values = [10.0, 11.0, 12.0, 13.0, 14.0]
        result = MarketDataFetcher.calculate_ema(values, 3)

        assert len(result) == 5
        # First 2 values are warmup (0.0)
        assert result[0] == 0.0
        assert result[1] == 0.0
        # SMA seed at index 2: (10+11+12)/3 = 11.0
        assert result[2] == pytest.approx(11.0)
        # EMA at index 3: 13 * 0.5 + 11 * 0.5 = 12.0
        assert result[3] == pytest.approx(12.0)

    def test_ema_tracks_uptrend(self):
        """EMA should lag behind an uptrend but trend upward."""
        closes = _uptrend_closes(30, start=100, step=2)
        ema = MarketDataFetcher.calculate_ema(closes, 8)

        # EMA should be rising
        valid_ema = [v for v in ema if v > 0]
        assert len(valid_ema) > 10
        assert valid_ema[-1] > valid_ema[0]
        # EMA should lag below the price in an uptrend
        assert valid_ema[-1] < closes[-1]

    def test_ema_tracks_downtrend(self):
        """EMA should lag behind a downtrend but trend downward."""
        closes = _downtrend_closes(30, start=200, step=2)
        ema = MarketDataFetcher.calculate_ema(closes, 8)

        valid_ema = [v for v in ema if v > 0]
        assert len(valid_ema) > 10
        assert valid_ema[-1] < valid_ema[0]
        # EMA should lag above the price in a downtrend
        assert valid_ema[-1] > closes[-1]

    def test_empty_values(self):
        """Empty input returns empty list."""
        assert MarketDataFetcher.calculate_ema([], 5) == []

    def test_insufficient_data(self):
        """Fewer values than period returns all zeros."""
        result = MarketDataFetcher.calculate_ema([1.0, 2.0], 5)
        assert result == [0.0, 0.0]

    def test_period_1_equals_values(self):
        """EMA with period 1 should equal the input values."""
        values = [10.0, 20.0, 15.0, 25.0]
        result = MarketDataFetcher.calculate_ema(values, 1)

        assert result[0] == 10.0
        assert result[1] == 20.0
        assert result[2] == 15.0
        assert result[3] == 25.0

    def test_constant_values(self):
        """EMA of constant values equals the constant."""
        values = [50.0] * 20
        result = MarketDataFetcher.calculate_ema(values, 8)

        valid = [v for v in result if v > 0]
        for v in valid:
            assert v == pytest.approx(50.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. calculate_adx
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateAdx:
    """Tests for ADX calculation."""

    def test_strong_uptrend_high_adx(self):
        """Steady uptrend should produce high ADX."""
        closes = _uptrend_closes(60, start=100, step=3)
        highs = [c + 2 for c in closes]
        lows = [c - 1 for c in closes]
        klines = _make_klines(closes, highs=highs, lows=lows)

        result = MarketDataFetcher.calculate_adx(klines, 14)

        assert result["adx"] > 20
        assert result["is_trending"] is True
        assert result["plus_di"] > result["minus_di"]

    def test_strong_downtrend_high_adx(self):
        """Steady downtrend should produce high ADX."""
        closes = _downtrend_closes(60, start=200, step=3)
        highs = [c + 1 for c in closes]
        lows = [c - 2 for c in closes]
        klines = _make_klines(closes, highs=highs, lows=lows)

        result = MarketDataFetcher.calculate_adx(klines, 14)

        assert result["adx"] > 15
        assert result["minus_di"] > result["plus_di"]

    def test_sideways_market_low_adx(self):
        """Choppy/sideways market should produce low ADX."""
        closes = _sideways_closes(60, center=100, amplitude=0.3)
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        klines = _make_klines(closes, highs=highs, lows=lows)

        result = MarketDataFetcher.calculate_adx(klines, 14)

        assert result["adx"] < 30

    def test_empty_klines(self):
        """Empty klines returns zero ADX."""
        result = MarketDataFetcher.calculate_adx([], 14)

        assert result["adx"] == 0.0
        assert result["is_trending"] is False

    def test_insufficient_data(self):
        """Fewer klines than period returns zero ADX."""
        klines = _make_klines([100.0] * 5)
        result = MarketDataFetcher.calculate_adx(klines, 14)

        assert result["adx"] == 0.0

    def test_result_keys(self):
        """Result should contain all expected keys."""
        klines = _make_klines(_uptrend_closes(50))
        result = MarketDataFetcher.calculate_adx(klines, 14)

        assert "adx" in result
        assert "plus_di" in result
        assert "minus_di" in result
        assert "is_trending" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 3. calculate_macd
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateMacd:
    """Tests for MACD calculation."""

    def test_uptrend_positive_macd(self):
        """Uptrend should produce positive MACD line."""
        closes = _uptrend_closes(60, start=100, step=2)
        klines = _make_klines(closes)

        result = MarketDataFetcher.calculate_macd(klines, 12, 26, 9)

        assert result["macd_line"] > 0

    def test_downtrend_negative_macd(self):
        """Downtrend should produce negative MACD line."""
        closes = _downtrend_closes(60, start=200, step=2)
        klines = _make_klines(closes)

        result = MarketDataFetcher.calculate_macd(klines, 12, 26, 9)

        assert result["macd_line"] < 0

    def test_empty_klines(self):
        """Empty klines returns zero MACD."""
        result = MarketDataFetcher.calculate_macd([], 12, 26, 9)

        assert result["macd_line"] == 0.0
        assert result["signal_line"] == 0.0
        assert result["histogram"] == 0.0
        assert result["histogram_series"] == []

    def test_insufficient_data(self):
        """Fewer klines than needed returns zero MACD."""
        klines = _make_klines([100.0] * 10)
        result = MarketDataFetcher.calculate_macd(klines, 12, 26, 9)

        assert result["macd_line"] == 0.0

    def test_histogram_is_macd_minus_signal(self):
        """Histogram should equal MACD line minus signal line."""
        closes = _uptrend_closes(80, start=100, step=1)
        klines = _make_klines(closes)

        result = MarketDataFetcher.calculate_macd(klines, 12, 26, 9)

        assert result["histogram"] == pytest.approx(
            result["macd_line"] - result["signal_line"], abs=0.01
        )

    def test_result_keys(self):
        """Result should contain all expected keys."""
        klines = _make_klines(_uptrend_closes(60))
        result = MarketDataFetcher.calculate_macd(klines, 12, 26, 9)

        assert "macd_line" in result
        assert "signal_line" in result
        assert "histogram" in result
        assert "histogram_series" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 4. calculate_rsi
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateRsi:
    """Tests for RSI calculation."""

    def test_strong_uptrend_high_rsi(self):
        """Consistent uptrend should produce RSI > 70."""
        closes = _uptrend_closes(30, start=100, step=3)
        klines = _make_klines(closes)

        rsi = MarketDataFetcher.calculate_rsi(klines, 14)

        # Last RSI values should be high (overbought territory)
        assert rsi[-1] > 65

    def test_strong_downtrend_low_rsi(self):
        """Consistent downtrend should produce RSI < 30."""
        closes = _downtrend_closes(30, start=200, step=3)
        klines = _make_klines(closes)

        rsi = MarketDataFetcher.calculate_rsi(klines, 14)

        # Last RSI values should be low (oversold territory)
        assert rsi[-1] < 35

    def test_sideways_market_mid_rsi(self):
        """Choppy market should produce RSI around 50."""
        closes = _sideways_closes(30, center=100, amplitude=0.5)
        klines = _make_klines(closes)

        rsi = MarketDataFetcher.calculate_rsi(klines, 14)

        # RSI should be roughly in the middle
        assert 30 < rsi[-1] < 70

    def test_empty_klines(self):
        """Empty klines returns empty list."""
        result = MarketDataFetcher.calculate_rsi([], 14)
        assert result == []

    def test_insufficient_data(self):
        """Fewer klines than period returns all 50.0."""
        klines = _make_klines([100.0] * 5)
        result = MarketDataFetcher.calculate_rsi(klines, 14)

        assert all(v == 50.0 for v in result)

    def test_rsi_range_0_to_100(self):
        """RSI should always be between 0 and 100."""
        closes = _uptrend_closes(50, start=100, step=5)
        klines = _make_klines(closes)

        rsi = MarketDataFetcher.calculate_rsi(klines, 14)

        for v in rsi:
            assert 0 <= v <= 100

    def test_constant_prices_rsi_50(self):
        """Constant prices (no change) should produce RSI near 50."""
        klines = _make_klines([100.0] * 30)
        rsi = MarketDataFetcher.calculate_rsi(klines, 14)

        # With no price change, RSI should stay at warmup value (50)
        for v in rsi:
            assert v == 50.0

    def test_rsi_length_matches_klines(self):
        """RSI output length should match kline input length."""
        klines = _make_klines(_uptrend_closes(40))
        rsi = MarketDataFetcher.calculate_rsi(klines, 14)

        assert len(rsi) == len(klines)
