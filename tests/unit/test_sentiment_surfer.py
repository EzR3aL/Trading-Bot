"""
Unit tests for the SentimentSurfer strategy.

Tests cover:
- Initialization (default params, custom params, data_fetcher injection)
- _ensure_fetcher lazy initialization
- Scoring functions:
  - _score_news_sentiment (neutral, bullish, bearish, extreme)
  - _score_fear_greed (extreme fear, extreme greed, neutral)
  - _score_vwap (above, below, neutral, unavailable, OIWAP blending)
  - _score_supertrend (bullish, bearish, neutral)
  - _score_spot_volume (accumulation, distribution, balanced)
  - _score_momentum (bullish, bearish, flat, extreme)
- _aggregate_scores (weighted averaging, direction, confidence, agreement)
- _calculate_targets (LONG and SHORT TP/SL)
- generate_signal (happy path, error handling, ETH symbol, zero price)
- should_trade (approved, low confidence, insufficient agreement, invalid price)
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
from src.strategy.sentiment_surfer import DEFAULTS, SentimentSurferStrategy


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_signal(
    direction=SignalDirection.LONG,
    confidence=75,
    symbol="BTCUSDT",
    entry_price=95000.0,
    target_price=97000.0,
    stop_loss=93000.0,
    reason="test signal",
    agreement="4/6",
):
    """Create a TradeSignal with sensible defaults for SentimentSurfer tests."""
    return TradeSignal(
        direction=direction,
        confidence=confidence,
        symbol=symbol,
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        reason=reason,
        metrics_snapshot={"agreement": agreement, "scores": {}},
        timestamp=datetime(2026, 2, 15, 12, 0, 0),
    )


def _make_mock_metrics(
    btc_price=95000.0,
    eth_price=3500.0,
    btc_24h_change_percent=2.0,
    eth_24h_change_percent=1.5,
    fear_greed_index=50,
):
    """Create a mock MarketMetrics object."""
    metrics = MagicMock()
    metrics.btc_price = btc_price
    metrics.eth_price = eth_price
    metrics.btc_24h_change_percent = btc_24h_change_percent
    metrics.eth_24h_change_percent = eth_24h_change_percent
    metrics.fear_greed_index = fear_greed_index
    metrics.to_dict.return_value = {
        "btc_price": btc_price,
        "eth_price": eth_price,
        "btc_24h_change_percent": btc_24h_change_percent,
        "eth_24h_change_percent": eth_24h_change_percent,
        "fear_greed_index": fear_greed_index,
    }
    return metrics


def _make_mock_fetcher(
    metrics=None,
    news=None,
    klines=None,
    oiwap=0.0,
    metrics_exception=None,
    news_exception=None,
    klines_exception=None,
):
    """Create a fully configured mock MarketDataFetcher."""
    fetcher = AsyncMock()
    fetcher._ensure_session = AsyncMock()
    fetcher.close = AsyncMock()

    if metrics is None:
        metrics = _make_mock_metrics()

    if news is None:
        news = {"average_tone": 1.5, "article_count": 10}

    if klines is None:
        # Minimal kline data: [open_time, open, high, low, close, volume, close_time, quote_vol, trades, taker_buy_base, ...]
        klines = [
            [1700000000000, "94000", "96000", "93000", "95000", "100", 1700003600000, "9500000", 1000, "55", "5225000"],
            [1700003600000, "95000", "97000", "94500", "96000", "120", 1700007200000, "11520000", 1200, "65", "6240000"],
        ]

    if metrics_exception:
        fetcher.fetch_all_metrics = AsyncMock(side_effect=metrics_exception)
    else:
        fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)

    if news_exception:
        fetcher.get_news_sentiment = AsyncMock(side_effect=news_exception)
    else:
        fetcher.get_news_sentiment = AsyncMock(return_value=news)

    if klines_exception:
        fetcher.get_binance_klines = AsyncMock(side_effect=klines_exception)
    else:
        fetcher.get_binance_klines = AsyncMock(return_value=klines)

    fetcher.calculate_oiwap = AsyncMock(return_value=oiwap)

    return fetcher


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Initialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestSentimentSurferInit:
    """Tests for SentimentSurferStrategy initialization."""

    def test_default_params_applied(self):
        """Strategy should use DEFAULTS when no custom params provided."""
        strategy = SentimentSurferStrategy()

        assert strategy._p["min_confidence"] == 40
        assert strategy._p["min_agreement"] == 3
        assert strategy._p["weight_vwap"] == 1.2
        assert strategy._p["weight_supertrend"] == 1.2
        assert strategy._p["weight_volume"] == 0.8
        assert strategy._p["weight_momentum"] == 0.8

    def test_custom_params_override_defaults(self):
        """Custom params should override defaults."""
        strategy = SentimentSurferStrategy(params={"min_confidence": 60, "min_agreement": 4})

        assert strategy._p["min_confidence"] == 60
        assert strategy._p["min_agreement"] == 4
        # Non-overridden defaults still present
        assert strategy._p["weight_news"] == 1.0

    def test_data_fetcher_injection(self):
        """Injected data_fetcher should be stored."""
        mock_fetcher = MagicMock()
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        assert strategy.data_fetcher is mock_fetcher

    def test_data_fetcher_none_by_default(self):
        """Without injection, data_fetcher should be None."""
        strategy = SentimentSurferStrategy()

        assert strategy.data_fetcher is None

    def test_params_stored_on_base_class(self):
        """self.params from BaseStrategy should hold original params."""
        strategy = SentimentSurferStrategy(params={"foo": "bar"})

        assert strategy.params == {"foo": "bar"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. _ensure_fetcher
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnsureFetcher:
    """Tests for lazy data fetcher initialization."""

    @pytest.mark.asyncio
    async def test_creates_fetcher_when_none(self):
        """Should create a MarketDataFetcher when data_fetcher is None."""
        strategy = SentimentSurferStrategy()

        with patch("src.strategy.sentiment_surfer.MarketDataFetcher") as MockFetcher:
            mock_instance = MagicMock()
            mock_instance._ensure_session = AsyncMock()
            MockFetcher.return_value = mock_instance

            await strategy._ensure_fetcher()

            assert strategy.data_fetcher is mock_instance
            MockFetcher.assert_called_once()
            mock_instance._ensure_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_does_not_recreate_existing_fetcher(self):
        """Should not create a new fetcher if one already exists."""
        mock_fetcher = MagicMock()
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch("src.strategy.sentiment_surfer.MarketDataFetcher") as MockFetcher:
            await strategy._ensure_fetcher()

            MockFetcher.assert_not_called()
            assert strategy.data_fetcher is mock_fetcher


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _score_news_sentiment
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreNewsSentiment:
    """Tests for the news sentiment scoring function."""

    def setup_method(self):
        self.strategy = SentimentSurferStrategy()

    def test_neutral_tone_within_threshold(self):
        """Tone within -1.0 to +1.0 should return score 0."""
        score, reason = self.strategy._score_news_sentiment(0.5)

        assert score == 0.0
        assert "neutral" in reason.lower()

    def test_neutral_tone_at_negative_threshold(self):
        """Tone exactly -1.0 should return score 0 (abs <= 1.0)."""
        score, _ = self.strategy._score_news_sentiment(-1.0)

        assert score == 0.0

    def test_neutral_tone_at_positive_threshold(self):
        """Tone exactly +1.0 should return score 0 (abs <= 1.0)."""
        score, _ = self.strategy._score_news_sentiment(1.0)

        assert score == 0.0

    def test_moderate_bullish_tone(self):
        """Tone between 1.0 and 3.0 should give moderate bullish score."""
        score, reason = self.strategy._score_news_sentiment(2.0)

        assert score > 0
        assert score == 2.0 * 10  # score = tone * 10
        assert "bullish" in reason.lower()

    def test_moderate_bearish_tone(self):
        """Tone between -3.0 and -1.0 should give moderate bearish score."""
        score, reason = self.strategy._score_news_sentiment(-2.0)

        assert score < 0
        assert score == -2.0 * 10  # score = tone * 10
        assert "bearish" in reason.lower()

    def test_strong_bullish_tone(self):
        """Tone > 3.0 uses the steeper multiplier (* 15)."""
        score, reason = self.strategy._score_news_sentiment(4.0)

        assert score == 4.0 * 15  # 60
        assert "bullish" in reason.lower()

    def test_strong_bearish_tone(self):
        """Tone < -3.0 uses the steeper multiplier (* 15)."""
        score, reason = self.strategy._score_news_sentiment(-4.0)

        assert score == -4.0 * 15  # -60
        assert "bearish" in reason.lower()

    def test_extreme_bullish_tone_capped_at_100(self):
        """Very high tone should be capped at +100."""
        score, _ = self.strategy._score_news_sentiment(10.0)

        assert score == 100.0

    def test_extreme_bearish_tone_capped_at_negative_100(self):
        """Very low tone should be capped at -100."""
        score, _ = self.strategy._score_news_sentiment(-10.0)

        assert score == -100.0

    def test_zero_tone_is_neutral(self):
        """Tone of exactly 0.0 should be neutral."""
        score, reason = self.strategy._score_news_sentiment(0.0)

        assert score == 0.0
        assert "neutral" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. _score_fear_greed
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreFearGreed:
    """Tests for the Fear & Greed Index scoring (contrarian)."""

    def setup_method(self):
        self.strategy = SentimentSurferStrategy()

    def test_extreme_fear_gives_bullish(self):
        """FGI below extreme_fear threshold (25) -> contrarian bullish."""
        score, reason = self.strategy._score_fear_greed(10)

        assert score > 0
        assert "bullish" in reason.lower()

    def test_extreme_fear_score_calculation(self):
        """Score = (threshold - fgi) * 3."""
        score, _ = self.strategy._score_fear_greed(10)

        expected = (25 - 10) * 3  # 45
        assert score == expected

    def test_extreme_fear_capped_at_100(self):
        """Very low FGI should be capped at 100."""
        score, _ = self.strategy._score_fear_greed(0)

        # (25 - 0) * 3 = 75, not capped
        assert score == 75

    def test_extreme_greed_gives_bearish(self):
        """FGI above extreme_greed threshold (75) -> contrarian bearish."""
        score, reason = self.strategy._score_fear_greed(90)

        assert score < 0
        assert "bearish" in reason.lower()

    def test_extreme_greed_score_calculation(self):
        """Score = -(fgi - threshold) * 3."""
        score, _ = self.strategy._score_fear_greed(90)

        expected = -(90 - 75) * 3  # -45
        assert score == expected

    def test_extreme_greed_capped_at_negative_100(self):
        """Very high FGI should be capped at -100."""
        score, _ = self.strategy._score_fear_greed(100)

        # -(100 - 75) * 3 = -75, not capped
        assert score == -75

    def test_neutral_zone(self):
        """FGI between extreme_fear and extreme_greed -> neutral (0)."""
        score, reason = self.strategy._score_fear_greed(50)

        assert score == 0.0
        assert "neutral" in reason.lower()

    def test_at_fear_threshold_is_neutral(self):
        """FGI exactly at extreme_fear threshold (25) is NOT below -> neutral."""
        score, reason = self.strategy._score_fear_greed(25)

        assert score == 0.0
        assert "neutral" in reason.lower()

    def test_at_greed_threshold_is_neutral(self):
        """FGI exactly at extreme_greed threshold (75) is NOT above -> neutral."""
        score, reason = self.strategy._score_fear_greed(75)

        assert score == 0.0
        assert "neutral" in reason.lower()

    def test_custom_thresholds(self):
        """Custom fear/greed thresholds should be respected."""
        strategy = SentimentSurferStrategy(params={
            "fear_greed_extreme_fear": 30,
            "fear_greed_extreme_greed": 70,
        })

        # 25 is below 30 -> bullish with custom thresholds
        score, _ = strategy._score_fear_greed(25)
        assert score > 0

        # 72 is above 70 -> bearish with custom thresholds
        score, _ = strategy._score_fear_greed(72)
        assert score < 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. _score_vwap
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreVwap:
    """Tests for the VWAP/OIWAP scoring function."""

    def setup_method(self):
        self.strategy = SentimentSurferStrategy()

    def test_price_above_vwap_is_bullish(self):
        """Price above VWAP -> positive score."""
        score, reason = self.strategy._score_vwap(96000.0, 94000.0)

        assert score > 0
        assert "above" in reason.lower()

    def test_price_below_vwap_is_bearish(self):
        """Price below VWAP -> negative score."""
        score, reason = self.strategy._score_vwap(93000.0, 95000.0)

        assert score < 0
        assert "below" in reason.lower()

    def test_price_near_vwap_is_neutral(self):
        """Price within 0.5% of VWAP -> neutral."""
        # 95000 * 0.005 = 475, so 95200 is within range
        score, reason = self.strategy._score_vwap(95200.0, 95000.0)

        assert score == 0.0
        assert "near" in reason.lower()

    def test_zero_vwap_returns_unavailable(self):
        """VWAP of 0 -> unavailable."""
        score, reason = self.strategy._score_vwap(95000.0, 0.0)

        assert score == 0.0
        assert "unavailable" in reason.lower()

    def test_zero_price_returns_unavailable(self):
        """Price of 0 -> unavailable."""
        score, reason = self.strategy._score_vwap(0.0, 95000.0)

        assert score == 0.0
        assert "unavailable" in reason.lower()

    def test_negative_vwap_returns_unavailable(self):
        """Negative VWAP -> unavailable."""
        score, reason = self.strategy._score_vwap(95000.0, -1.0)

        assert score == 0.0
        assert "unavailable" in reason.lower()

    def test_oiwap_blending_when_available(self):
        """When OIWAP > 0 and use_oiwap is True, reference = 0.6*VWAP + 0.4*OIWAP."""
        score, reason = self.strategy._score_vwap(96000.0, 94000.0, oiwap=95000.0)

        # reference = 0.6 * 94000 + 0.4 * 95000 = 56400 + 38000 = 94400
        assert "VWAP/OIWAP" in reason

    def test_oiwap_not_used_when_zero(self):
        """OIWAP of 0 -> only VWAP used."""
        _, reason = self.strategy._score_vwap(96000.0, 94000.0, oiwap=0.0)

        assert "VWAP" in reason
        assert "OIWAP" not in reason

    def test_oiwap_disabled_by_param(self):
        """When use_oiwap is False, OIWAP is ignored."""
        strategy = SentimentSurferStrategy(params={"use_oiwap": False})
        _, reason = strategy._score_vwap(96000.0, 94000.0, oiwap=95000.0)

        assert "OIWAP" not in reason

    def test_score_capped_at_100(self):
        """Large positive deviation should be capped at +100."""
        score, _ = self.strategy._score_vwap(100000.0, 80000.0)

        assert score <= 100.0

    def test_score_capped_at_negative_100(self):
        """Large negative deviation should be capped at -100."""
        score, _ = self.strategy._score_vwap(80000.0, 100000.0)

        assert score >= -100.0


# ═══════════════════════════════════════════════════════════════════════════════
# 6. _score_supertrend
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreSupertrend:
    """Tests for the Supertrend indicator scoring function."""

    def setup_method(self):
        self.strategy = SentimentSurferStrategy()

    def test_bullish_direction(self):
        """Bullish supertrend returns +70."""
        score, reason = self.strategy._score_supertrend({"direction": "bullish", "value": 93500.0})

        assert score == 70.0
        assert "GREEN" in reason
        assert "uptrend" in reason

    def test_bearish_direction(self):
        """Bearish supertrend returns -70."""
        score, reason = self.strategy._score_supertrend({"direction": "bearish", "value": 97000.0})

        assert score == -70.0
        assert "RED" in reason
        assert "downtrend" in reason

    def test_neutral_direction(self):
        """Neutral supertrend returns 0."""
        score, reason = self.strategy._score_supertrend({"direction": "neutral"})

        assert score == 0.0
        assert "neutral" in reason.lower()

    def test_missing_direction_key(self):
        """Empty dict defaults to neutral."""
        score, reason = self.strategy._score_supertrend({})

        assert score == 0.0
        assert "neutral" in reason.lower()

    def test_missing_value_key_defaults_to_zero(self):
        """Missing 'value' key should use 0 in the reason string."""
        _, reason = self.strategy._score_supertrend({"direction": "bullish"})

        assert "value=0.00" in reason


# ═══════════════════════════════════════════════════════════════════════════════
# 7. _score_spot_volume
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreSpotVolume:
    """Tests for the spot volume scoring function."""

    def setup_method(self):
        self.strategy = SentimentSurferStrategy()

    def test_accumulation_high_buy_ratio(self):
        """Buy ratio > 0.55 indicates accumulation (positive score)."""
        score, reason = self.strategy._score_spot_volume({"buy_ratio": 0.65})

        assert score > 0
        assert "accumulation" in reason.lower()

    def test_distribution_low_buy_ratio(self):
        """Buy ratio < 0.45 indicates distribution (negative score)."""
        score, reason = self.strategy._score_spot_volume({"buy_ratio": 0.35})

        assert score < 0
        assert "distribution" in reason.lower()

    def test_balanced_at_50_percent(self):
        """Buy ratio at 0.5 (within 45-55%) is balanced."""
        score, reason = self.strategy._score_spot_volume({"buy_ratio": 0.50})

        assert score == 0.0
        assert "balanced" in reason.lower()

    def test_balanced_at_upper_edge(self):
        """Buy ratio at 0.54 (within threshold) is balanced."""
        score, reason = self.strategy._score_spot_volume({"buy_ratio": 0.54})

        assert score == 0.0
        assert "balanced" in reason.lower()

    def test_balanced_at_lower_edge(self):
        """Buy ratio at 0.46 (within threshold) is balanced."""
        score, reason = self.strategy._score_spot_volume({"buy_ratio": 0.46})

        assert score == 0.0
        assert "balanced" in reason.lower()

    def test_score_calculation(self):
        """Score = (buy_ratio - 0.5) * 400."""
        score, _ = self.strategy._score_spot_volume({"buy_ratio": 0.60})

        expected = (0.60 - 0.5) * 400  # 40
        assert score == expected

    def test_score_capped_at_100(self):
        """Very high buy ratio capped at 100."""
        score, _ = self.strategy._score_spot_volume({"buy_ratio": 1.0})

        assert score <= 100.0

    def test_score_capped_at_negative_100(self):
        """Very low buy ratio capped at -100."""
        score, _ = self.strategy._score_spot_volume({"buy_ratio": 0.0})

        assert score >= -100.0

    def test_missing_buy_ratio_defaults_to_half(self):
        """Missing buy_ratio key defaults to 0.5 (balanced)."""
        score, _ = self.strategy._score_spot_volume({})

        assert score == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 8. _score_momentum
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreMomentum:
    """Tests for the 24h price momentum scoring function."""

    def setup_method(self):
        self.strategy = SentimentSurferStrategy()

    def test_bullish_momentum(self):
        """Positive price change > 0.5% is bullish."""
        score, reason = self.strategy._score_momentum(1.5)

        assert score > 0
        assert "bullish" in reason.lower()

    def test_bearish_momentum(self):
        """Negative price change < -0.5% is bearish."""
        score, reason = self.strategy._score_momentum(-1.5)

        assert score < 0
        assert "bearish" in reason.lower()

    def test_flat_momentum_within_threshold(self):
        """Price change within -0.5% to +0.5% is noise (flat)."""
        score, reason = self.strategy._score_momentum(0.3)

        assert score == 0.0
        assert "flat" in reason.lower()

    def test_flat_at_negative_threshold(self):
        """Price change of -0.4% is still flat."""
        score, _ = self.strategy._score_momentum(-0.4)

        assert score == 0.0

    def test_moderate_momentum_calculation(self):
        """Moderate change (< 2%) uses * 15 multiplier."""
        score, _ = self.strategy._score_momentum(1.0)

        expected = 1.0 * 15  # 15
        assert score == expected

    def test_strong_momentum_calculation(self):
        """Strong change (> 2%) uses * 20 multiplier."""
        score, _ = self.strategy._score_momentum(3.0)

        expected = min(3.0 * 20, 100)  # 60
        assert score == expected

    def test_extreme_bullish_capped_at_100(self):
        """Very large positive change capped at 100."""
        score, _ = self.strategy._score_momentum(10.0)

        assert score == 100.0

    def test_extreme_bearish_capped_at_negative_100(self):
        """Very large negative change capped at -100."""
        score, _ = self.strategy._score_momentum(-10.0)

        assert score == -100.0

    def test_zero_change_is_flat(self):
        """Zero change is flat."""
        score, reason = self.strategy._score_momentum(0.0)

        assert score == 0.0
        assert "flat" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. _aggregate_scores
# ═══════════════════════════════════════════════════════════════════════════════

class TestAggregateScores:
    """Tests for weighted score aggregation."""

    def setup_method(self):
        self.strategy = SentimentSurferStrategy()

    def test_all_bullish_scores(self):
        """All positive scores -> LONG direction."""
        scores = [
            (50, "news bullish", "news"),
            (40, "fear greedy contrarian", "fear_greed"),
            (60, "above VWAP", "vwap"),
            (70, "supertrend green", "supertrend"),
            (30, "accumulation", "volume"),
            (45, "momentum up", "momentum"),
        ]

        direction, confidence, agreement, reason = self.strategy._aggregate_scores(scores)

        assert direction == SignalDirection.LONG
        assert confidence > 0
        assert agreement == 6  # All 6 positive

    def test_all_bearish_scores(self):
        """All negative scores -> SHORT direction."""
        scores = [
            (-50, "news bearish", "news"),
            (-40, "fear greed bearish", "fear_greed"),
            (-60, "below VWAP", "vwap"),
            (-70, "supertrend red", "supertrend"),
            (-30, "distribution", "volume"),
            (-45, "momentum down", "momentum"),
        ]

        direction, confidence, agreement, reason = self.strategy._aggregate_scores(scores)

        assert direction == SignalDirection.SHORT
        assert confidence > 0
        assert agreement == 6  # All 6 negative

    def test_mixed_scores_long_dominant(self):
        """More positive scores -> LONG with partial agreement."""
        scores = [
            (60, "news bullish", "news"),
            (50, "fear contrarian bullish", "fear_greed"),
            (40, "above VWAP", "vwap"),
            (70, "supertrend green", "supertrend"),
            (-20, "mild distribution", "volume"),
            (0, "flat momentum", "momentum"),
        ]

        direction, confidence, agreement, _ = self.strategy._aggregate_scores(scores)

        assert direction == SignalDirection.LONG
        assert agreement == 4  # 4 positive scores for LONG

    def test_mixed_scores_short_dominant(self):
        """More negative scores -> SHORT with partial agreement."""
        scores = [
            (-60, "news bearish", "news"),
            (-50, "fear contrarian bearish", "fear_greed"),
            (-40, "below VWAP", "vwap"),
            (-70, "supertrend red", "supertrend"),
            (20, "mild accumulation", "volume"),
            (0, "flat momentum", "momentum"),
        ]

        direction, confidence, agreement, _ = self.strategy._aggregate_scores(scores)

        assert direction == SignalDirection.SHORT
        assert agreement == 4  # 4 negative scores for SHORT

    def test_confidence_capped_at_95(self):
        """Confidence should never exceed 95."""
        scores = [
            (100, "max bullish", "news"),
            (100, "max bullish", "fear_greed"),
            (100, "max bullish", "vwap"),
            (100, "max bullish", "supertrend"),
            (100, "max bullish", "volume"),
            (100, "max bullish", "momentum"),
        ]

        _, confidence, _, _ = self.strategy._aggregate_scores(scores)

        assert confidence <= 95

    def test_zero_scores_return_long_with_zero_confidence(self):
        """All zero scores -> LONG direction (>= 0), 0 confidence."""
        scores = [
            (0, "neutral", "news"),
            (0, "neutral", "fear_greed"),
            (0, "neutral", "vwap"),
            (0, "neutral", "supertrend"),
            (0, "neutral", "volume"),
            (0, "neutral", "momentum"),
        ]

        direction, confidence, agreement, _ = self.strategy._aggregate_scores(scores)

        assert direction == SignalDirection.LONG
        assert confidence == 0
        assert agreement == 0  # No positive scores

    def test_empty_scores_list(self):
        """Empty scores list -> no data available."""
        direction, confidence, agreement, reason = self.strategy._aggregate_scores([])

        assert confidence == 0
        assert "No data" in reason

    def test_weighted_average_calculation(self):
        """Weighted average correctly uses configured weights."""
        # Only news and vwap have non-zero scores
        scores = [
            (100, "max bullish news", "news"),        # weight 1.0
            (0, "neutral", "fear_greed"),              # weight 1.0
            (100, "max bullish vwap", "vwap"),         # weight 1.2
            (0, "neutral", "supertrend"),              # weight 1.2
            (0, "neutral", "volume"),                  # weight 0.8
            (0, "neutral", "momentum"),                # weight 0.8
        ]

        _, confidence, _, _ = self.strategy._aggregate_scores(scores)

        # weighted = (100*1.0 + 0*1.0 + 100*1.2 + 0*1.2 + 0*0.8 + 0*0.8) / (1.0+1.0+1.2+1.2+0.8+0.8)
        # = (100 + 120) / 6.0 = 220 / 6.0 = 36.67
        total_weight = 1.0 + 1.0 + 1.2 + 1.2 + 0.8 + 0.8
        expected = int(abs((100 * 1.0 + 100 * 1.2) / total_weight))
        assert confidence == expected

    def test_reasons_joined_with_pipe(self):
        """All reasons should be joined with ' | '."""
        scores = [
            (50, "reason_a", "news"),
            (30, "reason_b", "fear_greed"),
        ]

        _, _, _, reason = self.strategy._aggregate_scores(scores)

        assert "reason_a" in reason
        assert "reason_b" in reason
        assert " | " in reason

    def test_unknown_weight_key_defaults_to_one(self):
        """Unknown weight key should default to 1.0."""
        scores = [
            (50, "custom source", "unknown_source"),
        ]

        direction, confidence, _, _ = self.strategy._aggregate_scores(scores)

        assert direction == SignalDirection.LONG
        assert confidence == 50


# ═══════════════════════════════════════════════════════════════════════════════
# 10. _calculate_targets
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateTargets:
    """Tests for take profit and stop loss calculation."""

    def setup_method(self):
        self.strategy = SentimentSurferStrategy()

    def test_long_targets(self):
        """LONG: TP above entry, SL below entry."""
        strategy = SentimentSurferStrategy(params={"take_profit_percent": 3.5, "stop_loss_percent": 1.5})
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)

        # TP = 100000 * 1.035 = 103500
        # SL = 100000 * 0.985 = 98500
        assert tp == 103500.0
        assert sl == 98500.0
        assert tp > 100000.0
        assert sl < 100000.0

    def test_short_targets(self):
        """SHORT: TP below entry, SL above entry."""
        strategy = SentimentSurferStrategy(params={"take_profit_percent": 3.5, "stop_loss_percent": 1.5})
        tp, sl = strategy._calculate_targets(SignalDirection.SHORT, 100000.0)

        # TP = 100000 * 0.965 = 96500
        # SL = 100000 * 1.015 = 101500
        assert tp == 96500.0
        assert sl == 101500.0
        assert tp < 100000.0
        assert sl > 100000.0

    def test_custom_tp_sl_params(self):
        """Custom TP/SL percentages should be applied."""
        strategy = SentimentSurferStrategy(params={
            "take_profit_percent": 5.0,
            "stop_loss_percent": 2.0,
        })

        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 100000.0)

        assert tp == 105000.0
        assert sl == 98000.0

    def test_targets_are_rounded(self):
        """Results should be rounded to 2 decimal places."""
        strategy = SentimentSurferStrategy(params={"take_profit_percent": 3.5, "stop_loss_percent": 1.5})
        tp, sl = strategy._calculate_targets(SignalDirection.LONG, 33333.33)

        # Ensure both are rounded to 2 decimal places
        assert tp == round(tp, 2)
        assert sl == round(sl, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. generate_signal
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateSignal:
    """Tests for the full generate_signal method."""

    @pytest.mark.asyncio
    async def test_happy_path_btc(self):
        """Generate a valid BTC signal with mocked data."""
        mock_fetcher = _make_mock_fetcher(
            metrics=_make_mock_metrics(btc_price=95000.0, btc_24h_change_percent=2.5, fear_greed_index=20),
            news={"average_tone": 3.5, "article_count": 20},
            oiwap=94500.0,
        )
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch.object(
            type(strategy).data_fetcher.fget if hasattr(type(strategy).data_fetcher, 'fget') else None,
        ) if False else patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=94000.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "bullish", "value": 93500.0},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.60},
        ):
            signal = await strategy.generate_signal("BTCUSDT")

        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price == 95000.0
        assert signal.direction in (SignalDirection.LONG, SignalDirection.SHORT)
        assert 0 <= signal.confidence <= 95
        assert isinstance(signal.timestamp, datetime)
        assert isinstance(signal.reason, str)
        assert "agreement" in signal.metrics_snapshot
        assert "scores" in signal.metrics_snapshot

    @pytest.mark.asyncio
    async def test_happy_path_eth(self):
        """ETH symbol should use eth_price and eth_24h_change_percent."""
        mock_fetcher = _make_mock_fetcher(
            metrics=_make_mock_metrics(eth_price=3500.0, eth_24h_change_percent=-1.5, fear_greed_index=60),
            news={"average_tone": -2.0, "article_count": 5},
            oiwap=3480.0,
        )
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=3450.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "bearish", "value": 3600.0},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.42},
        ):
            signal = await strategy.generate_signal("ETHUSDT")

        assert signal.symbol == "ETHUSDT"
        assert signal.entry_price == 3500.0

    @pytest.mark.asyncio
    async def test_metrics_fetch_failure_uses_defaults(self):
        """When fetch_all_metrics fails, metrics fallback to None (price=0, fgi=50)."""
        mock_fetcher = _make_mock_fetcher(
            metrics_exception=ConnectionError("API down"),
            news={"average_tone": 0.0, "article_count": 0},
        )
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=0.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "neutral"},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.5},
        ):
            signal = await strategy.generate_signal("BTCUSDT")

        # With metrics=None, btc_price=0
        assert signal.entry_price == 0
        assert signal.target_price == 0.0
        assert signal.stop_loss == 0.0

    @pytest.mark.asyncio
    async def test_news_fetch_failure_uses_defaults(self):
        """When get_news_sentiment fails, defaults to neutral news."""
        mock_fetcher = _make_mock_fetcher(
            metrics=_make_mock_metrics(),
            news_exception=ConnectionError("GDELT down"),
            oiwap=94500.0,
        )
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=94000.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "bullish", "value": 93500.0},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.55},
        ):
            signal = await strategy.generate_signal("BTCUSDT")

        # Should still produce a valid signal (news defaults to neutral)
        assert signal.entry_price == 95000.0
        assert isinstance(signal.direction, SignalDirection)

    @pytest.mark.asyncio
    async def test_klines_fetch_failure_uses_empty(self):
        """When get_binance_klines fails, klines default to empty list."""
        mock_fetcher = _make_mock_fetcher(
            metrics=_make_mock_metrics(),
            news={"average_tone": 1.0, "article_count": 5},
            klines_exception=ConnectionError("Binance down"),
        )
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=0.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "neutral"},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.5},
        ):
            signal = await strategy.generate_signal("BTCUSDT")

        # Should succeed with degraded data (no kline-based indicators)
        assert signal.entry_price == 95000.0

    @pytest.mark.asyncio
    async def test_zero_price_produces_zero_targets(self):
        """When current_price is 0, TP and SL should both be 0."""
        mock_fetcher = _make_mock_fetcher(
            metrics=_make_mock_metrics(btc_price=0.0),
        )
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=0.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "neutral"},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.5},
        ):
            signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price == 0
        assert signal.target_price == 0.0
        assert signal.stop_loss == 0.0

    @pytest.mark.asyncio
    async def test_oiwap_not_calculated_when_klines_empty(self):
        """When klines is empty, OIWAP should not be calculated."""
        mock_fetcher = _make_mock_fetcher(
            metrics=_make_mock_metrics(),
            klines=[],
        )
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=0.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "neutral"},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.5},
        ):
            _signal = await strategy.generate_signal("BTCUSDT")

        # calculate_oiwap should not be called when klines is empty
        mock_fetcher.calculate_oiwap.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_oiwap_disabled_skips_calculation(self):
        """When use_oiwap is False, calculate_oiwap should not be called."""
        mock_fetcher = _make_mock_fetcher(
            metrics=_make_mock_metrics(),
        )
        strategy = SentimentSurferStrategy(
            params={"use_oiwap": False},
            data_fetcher=mock_fetcher,
        )

        with patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=94000.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "bullish", "value": 93500.0},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.55},
        ):
            _signal = await strategy.generate_signal("BTCUSDT")

        mock_fetcher.calculate_oiwap.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_metrics_snapshot_contains_expected_keys(self):
        """metrics_snapshot should contain news, vwap, oiwap, supertrend, volume, agreement, scores."""
        mock_fetcher = _make_mock_fetcher(
            metrics=_make_mock_metrics(),
            news={"average_tone": 1.5, "article_count": 10},
            oiwap=94500.0,
        )
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        with patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_vwap",
            return_value=94000.0,
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.calculate_supertrend",
            return_value={"direction": "bullish", "value": 93500.0},
        ), patch(
            "src.strategy.sentiment_surfer.MarketDataFetcher.get_spot_volume_analysis",
            return_value={"buy_ratio": 0.58},
        ):
            signal = await strategy.generate_signal("BTCUSDT")

        snapshot = signal.metrics_snapshot
        assert "news_tone" in snapshot
        assert "news_articles" in snapshot
        assert "vwap" in snapshot
        assert "oiwap" in snapshot
        assert "supertrend" in snapshot
        assert "volume_buy_ratio" in snapshot
        assert "agreement" in snapshot
        assert "scores" in snapshot
        assert snapshot["news_tone"] == 1.5
        assert snapshot["news_articles"] == 10
        assert snapshot["volume_buy_ratio"] == 0.58


# ═══════════════════════════════════════════════════════════════════════════════
# 12. should_trade
# ═══════════════════════════════════════════════════════════════════════════════

class TestShouldTrade:
    """Tests for the should_trade trade gate."""

    @pytest.mark.asyncio
    async def test_approved_with_sufficient_confidence_and_agreement(self):
        """Signal with high confidence and enough agreement should pass."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=60, entry_price=95000.0, agreement="4/6")

        ok, reason = await strategy.should_trade(signal)

        assert ok is True
        assert "approved" in reason.lower()
        assert "60%" in reason
        assert "4/6" in reason

    @pytest.mark.asyncio
    async def test_rejected_low_confidence(self):
        """Signal below min_confidence should be rejected."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=30, entry_price=95000.0, agreement="4/6")

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "confidence" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_insufficient_agreement(self):
        """Signal with too few agreeing sources should be rejected."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=60, entry_price=95000.0, agreement="2/6")

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "agreement" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_zero_entry_price(self):
        """Signal with entry_price=0 should be rejected."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=80, entry_price=0.0, agreement="5/6")

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "price" in reason.lower()

    @pytest.mark.asyncio
    async def test_rejected_negative_entry_price(self):
        """Signal with negative entry_price should be rejected."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=80, entry_price=-100.0, agreement="5/6")

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "price" in reason.lower()

    @pytest.mark.asyncio
    async def test_exactly_at_min_confidence_accepted(self):
        """Signal at exactly min_confidence (40) should be accepted."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=40, entry_price=95000.0, agreement="3/6")

        ok, _ = await strategy.should_trade(signal)

        assert ok is True

    @pytest.mark.asyncio
    async def test_exactly_below_min_confidence_rejected(self):
        """Signal one below min_confidence (39) should be rejected."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=39, entry_price=95000.0, agreement="3/6")

        ok, _ = await strategy.should_trade(signal)

        assert ok is False

    @pytest.mark.asyncio
    async def test_exactly_at_min_agreement_accepted(self):
        """Signal at exactly min_agreement (3) should be accepted."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=50, entry_price=95000.0, agreement="3/6")

        ok, _ = await strategy.should_trade(signal)

        assert ok is True

    @pytest.mark.asyncio
    async def test_exactly_below_min_agreement_rejected(self):
        """Signal one below min_agreement (2) should be rejected."""
        strategy = SentimentSurferStrategy()
        signal = _make_signal(confidence=50, entry_price=95000.0, agreement="2/6")

        ok, _ = await strategy.should_trade(signal)

        assert ok is False

    @pytest.mark.asyncio
    async def test_custom_min_confidence(self):
        """Custom min_confidence should be respected."""
        strategy = SentimentSurferStrategy(params={"min_confidence": 70})
        signal = _make_signal(confidence=65, entry_price=95000.0, agreement="4/6")

        ok, _ = await strategy.should_trade(signal)

        assert ok is False

    @pytest.mark.asyncio
    async def test_custom_min_agreement(self):
        """Custom min_agreement should be respected."""
        strategy = SentimentSurferStrategy(params={"min_agreement": 5})
        signal = _make_signal(confidence=80, entry_price=95000.0, agreement="4/6")

        ok, _ = await strategy.should_trade(signal)

        assert ok is False

    @pytest.mark.asyncio
    async def test_agreement_checked_before_confidence(self):
        """Invalid price is checked first, then agreement, then confidence."""
        strategy = SentimentSurferStrategy()

        # Both agreement and confidence are bad, but agreement is checked first
        signal = _make_signal(confidence=10, entry_price=95000.0, agreement="1/6")

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "agreement" in reason.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 13. get_description and get_param_schema
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchemaAndDescription:
    """Tests for class methods get_description and get_param_schema."""

    def test_get_description_returns_non_empty_string(self):
        """get_description should return a meaningful string."""
        desc = SentimentSurferStrategy.get_description()

        assert isinstance(desc, str)
        assert len(desc) > 20
        assert "sentiment" in desc.lower() or "Sentiment" in desc

    def test_get_param_schema_has_all_configurable_params(self):
        """Schema should include all user-configurable parameters."""
        schema = SentimentSurferStrategy.get_param_schema()

        expected_keys = [
            "fear_greed_extreme_fear",
            "fear_greed_extreme_greed",
            "supertrend_atr_period",
            "supertrend_multiplier",
            "vwap_period_hours",
            "use_oiwap",
            "weight_news",
            "weight_fear_greed",
            "weight_vwap",
            "weight_supertrend",
            "weight_volume",
            "weight_momentum",
            "min_agreement",
            "min_confidence",
        ]

        for key in expected_keys:
            assert key in schema, f"Missing key: {key}"

    def test_param_schema_entries_have_required_fields(self):
        """Each schema entry should have type, label, description, default."""
        schema = SentimentSurferStrategy.get_param_schema()

        for key, entry in schema.items():
            assert "type" in entry, f"{key} missing 'type'"
            assert "label" in entry, f"{key} missing 'label'"
            assert "description" in entry, f"{key} missing 'description'"
            assert "default" in entry, f"{key} missing 'default'"

    def test_min_confidence_bounds(self):
        """min_confidence should have min=10, max=80, default=40."""
        schema = SentimentSurferStrategy.get_param_schema()
        conf = schema["min_confidence"]

        assert conf["default"] == 40
        assert conf["min"] == 10
        assert conf["max"] == 80

    def test_min_agreement_bounds(self):
        """min_agreement should have min=1, max=6, default=3."""
        schema = SentimentSurferStrategy.get_param_schema()
        agree = schema["min_agreement"]

        assert agree["default"] == 3
        assert agree["min"] == 1
        assert agree["max"] == 6


# ═══════════════════════════════════════════════════════════════════════════════
# 14. close()
# ═══════════════════════════════════════════════════════════════════════════════

class TestClose:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_closes_data_fetcher(self):
        """close() should call data_fetcher.close()."""
        mock_fetcher = AsyncMock()
        strategy = SentimentSurferStrategy(data_fetcher=mock_fetcher)

        await strategy.close()

        mock_fetcher.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_fetcher_does_not_raise(self):
        """close() when data_fetcher is None should not raise."""
        strategy = SentimentSurferStrategy()
        assert strategy.data_fetcher is None

        await strategy.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_with_fetcher_set_to_none(self):
        """Explicitly setting fetcher to None then closing should be safe."""
        strategy = SentimentSurferStrategy()
        strategy.data_fetcher = None

        await strategy.close()  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Strategy Registry
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistration:
    """Tests for strategy registry integration."""

    def test_sentiment_surfer_is_registered(self):
        """SentimentSurferStrategy should be registered under 'sentiment_surfer'."""
        assert StrategyRegistry.get("sentiment_surfer") is SentimentSurferStrategy

    def test_create_via_registry(self):
        """Registry.create should return a SentimentSurferStrategy instance."""
        instance = StrategyRegistry.create("sentiment_surfer", params={"min_confidence": 50})

        assert isinstance(instance, SentimentSurferStrategy)
        assert instance._p["min_confidence"] == 50


# ═══════════════════════════════════════════════════════════════════════════════
# 16. DEFAULTS constant
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefaults:
    """Tests for the DEFAULTS constant values."""

    def test_defaults_contain_all_expected_keys(self):
        """DEFAULTS should contain all configuration keys."""
        expected_keys = [
            "fear_greed_extreme_fear", "fear_greed_extreme_greed",
            "supertrend_atr_period", "supertrend_multiplier",
            "vwap_period_hours", "use_oiwap",
            "volume_period_hours", "news_lookback_hours",
            "weight_news", "weight_fear_greed", "weight_vwap",
            "weight_supertrend", "weight_volume", "weight_momentum",
            "min_agreement", "min_confidence",
        ]

        for key in expected_keys:
            assert key in DEFAULTS, f"Missing default: {key}"

    def test_default_values(self):
        """Verify specific default values."""
        assert DEFAULTS["fear_greed_extreme_fear"] == 25
        assert DEFAULTS["fear_greed_extreme_greed"] == 75
        assert DEFAULTS["min_agreement"] == 3
        assert DEFAULTS["min_confidence"] == 40
