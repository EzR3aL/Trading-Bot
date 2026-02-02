"""
Unit tests for the Liquidation Hunter Strategy.

Tests cover:
- Leverage analysis (crowded longs/shorts detection)
- Sentiment analysis (fear/greed extremes)
- Funding rate analysis
- Signal generation with various market conditions
- Target calculation (TP/SL)
- Position size recommendations
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.liquidation_hunter import (
    LiquidationHunterStrategy,
    SignalDirection,
    TradeSignal,
)


@dataclass
class MockStrategyConfig:
    """Test configuration with known values."""
    fear_greed_extreme_fear: int = 25
    fear_greed_extreme_greed: int = 75
    long_short_crowded_longs: float = 2.0
    long_short_crowded_shorts: float = 0.5
    funding_rate_high: float = 0.0005
    funding_rate_low: float = -0.0002
    high_confidence_min: int = 85
    low_confidence_min: int = 55


class TestLeverageAnalysis:
    """Tests for leverage (L/S ratio) analysis."""

    def setup_method(self):
        """Set up test fixtures with known config values."""
        self.strategy = LiquidationHunterStrategy(data_fetcher=None)
        # Override config with test values for consistent behavior
        self.strategy.config = MockStrategyConfig()

    def test_crowded_longs_signals_short(self):
        """When L/S ratio > 2.5 (default threshold), signal should be SHORT."""
        # Use 2.6 which is > 2.5 (the default threshold)
        direction, confidence, reason = self.strategy._analyze_leverage(2.6)

        assert direction == SignalDirection.SHORT
        assert confidence > 0
        assert "Crowded Longs" in reason

    def test_crowded_shorts_signals_long(self):
        """When L/S ratio < 0.4, signal should be LONG."""
        direction, confidence, reason = self.strategy._analyze_leverage(0.3)

        assert direction == SignalDirection.LONG
        assert confidence > 0
        assert "Crowded Shorts" in reason

    def test_neutral_ratio_no_signal(self):
        """When L/S ratio is neutral (0.4-2.5), no direction signal."""
        direction, confidence, reason = self.strategy._analyze_leverage(1.0)

        assert direction is None
        assert confidence == 0
        assert "neutral" in reason.lower()

    def test_extreme_crowded_longs_high_confidence(self):
        """Very high L/S ratio should give higher confidence boost."""
        _, conf_moderate, _ = self.strategy._analyze_leverage(2.7)
        _, conf_extreme, _ = self.strategy._analyze_leverage(3.5)

        assert conf_extreme > conf_moderate

    def test_confidence_boost_capped_at_30(self):
        """Confidence boost should be capped at 30."""
        _, confidence, _ = self.strategy._analyze_leverage(10.0)

        assert confidence <= 30


class TestSentimentAnalysis:
    """Tests for Fear & Greed sentiment analysis."""

    def setup_method(self):
        """Set up test fixtures with known config values."""
        self.strategy = LiquidationHunterStrategy(data_fetcher=None)
        self.strategy.config = MockStrategyConfig()

    def test_extreme_greed_signals_short(self):
        """Fear & Greed > 80 (default threshold) should signal SHORT."""
        direction, confidence, reason = self.strategy._analyze_sentiment(85)

        assert direction == SignalDirection.SHORT
        assert confidence > 0
        assert "Extreme Greed" in reason

    def test_extreme_fear_signals_long(self):
        """Fear & Greed < 20 (default threshold) should signal LONG."""
        direction, confidence, reason = self.strategy._analyze_sentiment(15)

        assert direction == SignalDirection.LONG
        assert confidence > 0
        assert "Extreme Fear" in reason

    def test_neutral_sentiment_no_signal(self):
        """Neutral sentiment (20-80) should give no direction."""
        direction, confidence, reason = self.strategy._analyze_sentiment(50)

        assert direction is None
        assert confidence == 0
        assert "neutral" in reason.lower()

    def test_boundary_values_greed(self):
        """Test boundary at extreme greed threshold (80)."""
        # At 80 - should be neutral (threshold is >80)
        direction_at_80, _, _ = self.strategy._analyze_sentiment(80)
        # At 81 - should signal SHORT
        direction_at_81, _, _ = self.strategy._analyze_sentiment(81)

        assert direction_at_80 is None
        assert direction_at_81 == SignalDirection.SHORT

    def test_boundary_values_fear(self):
        """Test boundary at extreme fear threshold (20)."""
        # At 20 - should be neutral (threshold is <20)
        direction_at_20, _, _ = self.strategy._analyze_sentiment(20)
        # At 19 - should signal LONG
        direction_at_19, _, _ = self.strategy._analyze_sentiment(19)

        assert direction_at_20 is None
        assert direction_at_19 == SignalDirection.LONG


class TestFundingRateAnalysis:
    """Tests for funding rate analysis."""

    def setup_method(self):
        """Set up test fixtures with known config values."""
        self.strategy = LiquidationHunterStrategy(data_fetcher=None)
        self.strategy.config = MockStrategyConfig()

    def test_high_funding_strengthens_short(self):
        """High funding rate should strengthen SHORT signal."""
        adjustment, reason = self.strategy._analyze_funding_rate(
            0.001, SignalDirection.SHORT
        )

        assert adjustment == 20  # Strengthens SHORT
        assert "High Funding" in reason

    def test_high_funding_weakens_long(self):
        """High funding rate should weaken LONG signal."""
        adjustment, reason = self.strategy._analyze_funding_rate(
            0.001, SignalDirection.LONG
        )

        assert adjustment == -10  # Weakens LONG

    def test_negative_funding_strengthens_long(self):
        """Negative funding rate should strengthen LONG signal."""
        adjustment, reason = self.strategy._analyze_funding_rate(
            -0.0005, SignalDirection.LONG
        )

        assert adjustment == 20  # Strengthens LONG
        assert "Negative Funding" in reason

    def test_negative_funding_weakens_short(self):
        """Negative funding rate should weaken SHORT signal."""
        adjustment, reason = self.strategy._analyze_funding_rate(
            -0.0005, SignalDirection.SHORT
        )

        assert adjustment == -10  # Weakens SHORT

    def test_neutral_funding_no_adjustment(self):
        """Neutral funding rate should give no adjustment."""
        adjustment, reason = self.strategy._analyze_funding_rate(
            0.0001, SignalDirection.LONG
        )

        assert adjustment == 0
        assert "neutral" in reason.lower()


class TestTargetCalculation:
    """Tests for take profit and stop loss calculation."""

    def setup_method(self):
        """Set up test fixtures with known config values."""
        self.strategy = LiquidationHunterStrategy(data_fetcher=None)
        self.strategy.config = MockStrategyConfig()

    def test_long_targets_calculated_correctly(self):
        """LONG targets: TP above entry, SL below entry."""
        current_price = 95000.0
        tp, sl = self.strategy._calculate_targets(
            SignalDirection.LONG, current_price
        )

        assert tp > current_price  # Take profit above
        assert sl < current_price  # Stop loss below
        assert tp > sl  # TP always greater than SL for long

    def test_short_targets_calculated_correctly(self):
        """SHORT targets: TP below entry, SL above entry."""
        current_price = 95000.0
        tp, sl = self.strategy._calculate_targets(
            SignalDirection.SHORT, current_price
        )

        assert tp < current_price  # Take profit below
        assert sl > current_price  # Stop loss above
        assert tp < sl  # TP always less than SL for short

    def test_targets_are_rounded(self):
        """Targets should be rounded to 2 decimal places."""
        tp, sl = self.strategy._calculate_targets(
            SignalDirection.LONG, 95123.456789
        )

        # Check they're rounded (no more than 2 decimal places)
        assert tp == round(tp, 2)
        assert sl == round(sl, 2)


class TestSignalGeneration:
    """Tests for complete signal generation."""

    @pytest.fixture
    def strategy_with_mock_fetcher(self, mock_data_fetcher):
        """Create strategy with mocked data fetcher and test config."""
        strategy = LiquidationHunterStrategy(data_fetcher=mock_data_fetcher)
        strategy.config = MockStrategyConfig()
        return strategy

    @pytest.mark.asyncio
    async def test_crowded_longs_extreme_greed_generates_short(
        self, strategy_with_mock_fetcher, crowded_longs_extreme_greed
    ):
        """Crowded longs + extreme greed should generate SHORT with alignment."""
        strategy = strategy_with_mock_fetcher
        strategy.data_fetcher.fetch_all_metrics = AsyncMock(
            return_value=crowded_longs_extreme_greed
        )

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.SHORT
        assert signal.confidence >= 70  # Good confidence with alignment
        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price == 95000.0
        # Check for alignment indicators
        assert "Crowded Longs" in signal.reason or "Extreme Greed" in signal.reason

    @pytest.mark.asyncio
    async def test_crowded_shorts_extreme_fear_generates_long(
        self, strategy_with_mock_fetcher, crowded_shorts_extreme_fear
    ):
        """Crowded shorts + extreme fear should generate HIGH confidence LONG."""
        strategy = strategy_with_mock_fetcher
        strategy.data_fetcher.fetch_all_metrics = AsyncMock(
            return_value=crowded_shorts_extreme_fear
        )

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.LONG
        assert signal.confidence >= 85  # High confidence alignment
        assert "Crowded Shorts" in signal.reason
        assert "Extreme Fear" in signal.reason

    @pytest.mark.asyncio
    async def test_conflicting_signals_capped_confidence(
        self, strategy_with_mock_fetcher, conflicting_signals
    ):
        """When leverage and sentiment conflict, confidence should be capped."""
        strategy = strategy_with_mock_fetcher
        strategy.data_fetcher.fetch_all_metrics = AsyncMock(
            return_value=conflicting_signals
        )

        signal = await strategy.generate_signal("BTCUSDT")

        # With conflicting signals, confidence is capped at 70
        assert signal.confidence <= 70
        # The CONFLICT reason is added when both leverage and sentiment have directions
        # but they disagree

    @pytest.mark.asyncio
    async def test_neutral_conditions_follows_trend(
        self, strategy_with_mock_fetcher, neutral_metrics
    ):
        """Neutral conditions should follow 24h trend with low confidence."""
        strategy = strategy_with_mock_fetcher
        strategy.data_fetcher.fetch_all_metrics = AsyncMock(
            return_value=neutral_metrics
        )

        signal = await strategy.generate_signal("BTCUSDT")

        # Neutral metrics with +0.5% 24h change -> should follow trend (LONG)
        assert signal.direction == SignalDirection.LONG
        assert signal.confidence <= 65  # Low confidence for trend following
        assert "Following 24h trend" in signal.reason

    @pytest.mark.asyncio
    async def test_signal_has_valid_targets(
        self, strategy_with_mock_fetcher, crowded_longs_extreme_greed
    ):
        """Generated signal should have valid TP and SL targets."""
        strategy = strategy_with_mock_fetcher
        strategy.data_fetcher.fetch_all_metrics = AsyncMock(
            return_value=crowded_longs_extreme_greed
        )

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.target_price > 0
        assert signal.stop_loss > 0
        # For SHORT, TP < entry < SL
        assert signal.target_price < signal.entry_price
        assert signal.stop_loss > signal.entry_price

    @pytest.mark.asyncio
    async def test_signal_includes_metrics_snapshot(
        self, strategy_with_mock_fetcher, crowded_longs_extreme_greed
    ):
        """Signal should include a snapshot of market metrics."""
        strategy = strategy_with_mock_fetcher
        strategy.data_fetcher.fetch_all_metrics = AsyncMock(
            return_value=crowded_longs_extreme_greed
        )

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.metrics_snapshot is not None
        assert "fear_greed_index" in signal.metrics_snapshot
        assert "long_short_ratio" in signal.metrics_snapshot
        assert signal.metrics_snapshot["fear_greed_index"] == 85

    @pytest.mark.asyncio
    async def test_eth_uses_eth_metrics(
        self, strategy_with_mock_fetcher, mock_market_metrics
    ):
        """ETH signals should use ETH-specific metrics."""
        metrics = mock_market_metrics(
            btc_price=95000.0,
            eth_price=3500.0,
            funding_rate_btc=0.0001,
            funding_rate_eth=0.0005,  # Different from BTC
            btc_24h_change_percent=1.0,
            eth_24h_change_percent=-2.0,  # Different from BTC
        )

        strategy = strategy_with_mock_fetcher
        strategy.data_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)

        signal = await strategy.generate_signal("ETHUSDT")

        assert signal.symbol == "ETHUSDT"
        assert signal.entry_price == 3500.0  # ETH price


class TestShouldTrade:
    """Tests for trade decision logic."""

    @pytest.fixture
    def valid_signal(self):
        """Create a valid trade signal."""
        return TradeSignal(
            direction=SignalDirection.LONG,
            confidence=80,
            symbol="BTCUSDT",
            entry_price=95000.0,
            target_price=98000.0,
            stop_loss=93000.0,
            reason="Test signal",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )

    @pytest.mark.asyncio
    async def test_high_confidence_approved(self, valid_signal):
        """High confidence signal should be approved."""
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        strategy.config = MockStrategyConfig()
        valid_signal.confidence = 80

        should_trade, reason = await strategy.should_trade(valid_signal)

        assert should_trade is True
        assert "approved" in reason.lower()

    @pytest.mark.asyncio
    async def test_low_confidence_rejected(self, valid_signal):
        """Below minimum confidence should be rejected."""
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        strategy.config = MockStrategyConfig()
        valid_signal.confidence = 40  # Below minimum

        should_trade, reason = await strategy.should_trade(valid_signal)

        assert should_trade is False
        assert "below minimum" in reason.lower()

    @pytest.mark.asyncio
    async def test_invalid_price_rejected(self, valid_signal):
        """Signal with invalid entry price should be rejected."""
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        strategy.config = MockStrategyConfig()
        valid_signal.entry_price = 0

        should_trade, reason = await strategy.should_trade(valid_signal)

        assert should_trade is False
        assert "price" in reason.lower()


class TestPositionSizeRecommendation:
    """Tests for position size calculation."""

    def setup_method(self):
        """Set up test fixtures with known config values."""
        self.strategy = LiquidationHunterStrategy(data_fetcher=None)
        self.strategy.config = MockStrategyConfig()

    def test_high_confidence_larger_position(self):
        """High confidence should result in larger position."""
        high_conf_signal = TradeSignal(
            direction=SignalDirection.LONG,
            confidence=90,
            symbol="BTCUSDT",
            entry_price=95000.0,
            target_price=98000.0,
            stop_loss=93000.0,
            reason="High confidence",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )

        low_conf_signal = TradeSignal(
            direction=SignalDirection.LONG,
            confidence=55,
            symbol="BTCUSDT",
            entry_price=95000.0,
            target_price=98000.0,
            stop_loss=93000.0,
            reason="Low confidence",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )

        balance = 10000.0
        high_size = self.strategy.get_position_size_recommendation(
            high_conf_signal, balance
        )
        low_size = self.strategy.get_position_size_recommendation(
            low_conf_signal, balance
        )

        assert high_size > low_size

    def test_position_scales_with_confidence(self):
        """Position size should scale with confidence levels."""
        balance = 10000.0

        sizes = {}
        for confidence in [55, 65, 75, 85, 95]:
            signal = TradeSignal(
                direction=SignalDirection.LONG,
                confidence=confidence,
                symbol="BTCUSDT",
                entry_price=95000.0,
                target_price=98000.0,
                stop_loss=93000.0,
                reason="Test",
                metrics_snapshot={},
                timestamp=datetime.now(),
            )
            sizes[confidence] = self.strategy.get_position_size_recommendation(
                signal, balance
            )

        # Higher confidence = larger position
        assert sizes[95] > sizes[85] > sizes[75]
        assert sizes[55] < sizes[65]


class TestTradeSignalDataclass:
    """Tests for TradeSignal dataclass."""

    def test_is_high_confidence_property(self):
        """Test high confidence property."""
        high_conf = TradeSignal(
            direction=SignalDirection.LONG,
            confidence=90,
            symbol="BTCUSDT",
            entry_price=95000.0,
            target_price=98000.0,
            stop_loss=93000.0,
            reason="Test",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )

        low_conf = TradeSignal(
            direction=SignalDirection.LONG,
            confidence=60,
            symbol="BTCUSDT",
            entry_price=95000.0,
            target_price=98000.0,
            stop_loss=93000.0,
            reason="Test",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )

        assert high_conf.is_high_confidence is True
        assert low_conf.is_high_confidence is False

    def test_to_dict_serialization(self):
        """Test dictionary serialization."""
        signal = TradeSignal(
            direction=SignalDirection.SHORT,
            confidence=85,
            symbol="ETHUSDT",
            entry_price=3500.0,
            target_price=3400.0,
            stop_loss=3550.0,
            reason="Test reason",
            metrics_snapshot={"test": "data"},
            timestamp=datetime.now(),
        )

        result = signal.to_dict()

        assert result["direction"] == "short"
        assert result["confidence"] == 85
        assert result["symbol"] == "ETHUSDT"
        assert result["entry_price"] == 3500.0
        assert "timestamp" in result
        assert result["is_high_confidence"] is True
