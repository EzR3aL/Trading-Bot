"""
Tests for the Composite Signal Scoring System.
"""

import pytest

from src.signals.composite import (
    SignalComposite,
    SignalResult,
    CompositeResult,
    DEFAULT_WEIGHTS,
)
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


class TestSignalComposite:
    """Tests for SignalComposite class."""

    @pytest.fixture
    def composite(self):
        """Create a test composite with default weights."""
        return SignalComposite()

    def test_initialization_default_weights(self, composite):
        """Test default weights are loaded."""
        weights = composite.get_weights()
        assert len(weights) == 8
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_initialization_custom_weights(self):
        """Test custom weights are normalized."""
        custom = {"fear_greed": 30, "funding_rate": 20, "rsi": 50}
        comp = SignalComposite(weights=custom)
        weights = comp.get_weights()
        assert abs(sum(weights.values()) - 1.0) < 0.01
        assert weights["rsi"] == pytest.approx(0.5)

    def test_calculate_all_long_signals(self, composite):
        """Test composite with all signals pointing long."""
        signals = {
            "fear_greed": normalize_fear_greed(10),  # Extreme fear -> long
            "funding_rate": normalize_funding_rate(-0.001),  # Negative -> long
            "long_short_ratio": normalize_long_short_ratio(0.3),  # Crowded shorts -> long
            "open_interest_change": normalize_open_interest_change(10),
            "price_momentum": normalize_price_momentum(8.0),
            "rsi": normalize_rsi(20),  # Oversold -> long
            "volume_profile": normalize_volume_profile(0.8),
            "liquidation_imbalance": normalize_liquidation_imbalance(800000, 200000),
        }

        result = composite.calculate(signals)

        assert result.direction == "long"
        assert result.score > 0.3
        assert result.confidence >= 60
        assert result.signal_count == 8

    def test_calculate_all_short_signals(self, composite):
        """Test composite with all signals pointing short."""
        signals = {
            "fear_greed": normalize_fear_greed(90),  # Extreme greed -> short
            "funding_rate": normalize_funding_rate(0.002),  # High positive -> short
            "long_short_ratio": normalize_long_short_ratio(3.0),  # Crowded longs -> short
            "open_interest_change": normalize_open_interest_change(-10),
            "price_momentum": normalize_price_momentum(-8.0),
            "rsi": normalize_rsi(85),  # Overbought -> short
            "volume_profile": normalize_volume_profile(0.2),
            "liquidation_imbalance": normalize_liquidation_imbalance(200000, 800000),
        }

        result = composite.calculate(signals)

        assert result.direction == "short"
        assert result.score < -0.3
        assert result.confidence >= 60

    def test_calculate_mixed_signals(self, composite):
        """Test composite with mixed signals."""
        signals = {
            "fear_greed": normalize_fear_greed(50),  # Neutral
            "funding_rate": normalize_funding_rate(0.001),  # Short
            "long_short_ratio": normalize_long_short_ratio(0.3),  # Long
            "rsi": normalize_rsi(50),  # Neutral
        }

        result = composite.calculate(signals)

        # Mixed signals -> lower confidence
        assert abs(result.score) < 0.5
        assert result.confidence <= 80

    def test_calculate_empty_signals(self, composite):
        """Test composite with no signals."""
        result = composite.calculate({})

        assert result.score == 0.0
        assert result.direction == "long"  # Default when score is 0
        assert result.signal_count == 0

    def test_calculate_unknown_signal_ignored(self, composite):
        """Test that signals not in weights are ignored."""
        signals = {
            "unknown_signal": SignalNormalizer(
                name="unknown", raw_value=1.0, normalized=1.0,
                strength="strong", description="Unknown signal",
            ),
            "fear_greed": normalize_fear_greed(10),
        }

        result = composite.calculate(signals)
        # Only fear_greed should contribute
        assert result.signal_count == 1

    def test_confidence_range(self, composite):
        """Test that confidence is always within bounds."""
        for fear in [5, 25, 50, 75, 95]:
            signals = {"fear_greed": normalize_fear_greed(fear)}
            result = composite.calculate(signals)
            assert 50 <= result.confidence <= 95

    def test_agreement_ratio_all_agree(self, composite):
        """Test agreement ratio when all signals agree."""
        signals = {
            "fear_greed": normalize_fear_greed(10),
            "rsi": normalize_rsi(20),
            "long_short_ratio": normalize_long_short_ratio(0.3),
        }

        result = composite.calculate(signals)
        assert result.agreement_ratio >= 0.8

    def test_agreement_ratio_mixed(self, composite):
        """Test agreement ratio with mixed signals."""
        signals = {
            "fear_greed": normalize_fear_greed(10),  # Long
            "rsi": normalize_rsi(80),  # Short
            "long_short_ratio": normalize_long_short_ratio(3.0),  # Short
        }

        result = composite.calculate(signals)
        # Not all signals agree
        assert result.agreement_ratio < 1.0

    def test_set_weight(self, composite):
        """Test dynamically setting a weight."""
        composite.set_weight("fear_greed", 0.5)
        weights = composite.get_weights()
        # After normalization, fear_greed should be the largest
        assert weights["fear_greed"] > 0.3

    def test_set_weight_normalizes(self, composite):
        """Test that set_weight re-normalizes all weights."""
        composite.set_weight("fear_greed", 100)
        weights = composite.get_weights()
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_get_signal_breakdown(self, composite):
        """Test signal breakdown sorting."""
        signals = {
            "fear_greed": normalize_fear_greed(10),
            "funding_rate": normalize_funding_rate(-0.001),
            "rsi": normalize_rsi(50),
        }

        result = composite.calculate(signals)
        breakdown = composite.get_signal_breakdown(result)

        assert len(breakdown) == 3
        # Should be sorted by absolute contribution
        contributions = [b["contribution"] for b in breakdown]
        assert contributions == sorted(contributions, reverse=True)

    def test_get_signal_breakdown_agreement(self, composite):
        """Test breakdown includes agreement info."""
        signals = {
            "fear_greed": normalize_fear_greed(10),
            "rsi": normalize_rsi(80),  # Disagrees with fear_greed
        }

        result = composite.calculate(signals)
        breakdown = composite.get_signal_breakdown(result)

        # At least one should disagree
        agreements = [b["agrees_with_composite"] for b in breakdown if b["direction"] != "neutral"]
        assert not all(agreements)


class TestCompositeResult:
    """Tests for CompositeResult dataclass."""

    def test_to_dict(self):
        """Test serialization."""
        result = CompositeResult(
            score=0.65,
            direction="long",
            confidence=78,
            signal_count=5,
            active_signals=4,
            agreement_ratio=0.75,
        )
        d = result.to_dict()
        assert d["score"] == 0.65
        assert d["direction"] == "long"
        assert d["confidence"] == 78
        assert "timestamp" in d


class TestDefaultWeights:
    """Tests for default weight configuration."""

    def test_default_weights_sum_to_one(self):
        """Default weights should sum to ~1.0."""
        total = sum(DEFAULT_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_default_weights_all_positive(self):
        """All default weights should be positive."""
        for name, weight in DEFAULT_WEIGHTS.items():
            assert weight > 0, f"Weight for {name} is not positive"

    def test_default_has_eight_signals(self):
        """Default should have 8 signals."""
        assert len(DEFAULT_WEIGHTS) == 8

    def test_fear_greed_highest_weight(self):
        """Fear/Greed and L/S ratio should be the highest weighted."""
        top_two = sorted(DEFAULT_WEIGHTS.values(), reverse=True)[:2]
        assert DEFAULT_WEIGHTS["fear_greed"] in top_two
        assert DEFAULT_WEIGHTS["long_short_ratio"] in top_two


class TestIntegration:
    """Integration tests combining normalizers with composite."""

    def test_full_stack_bullish(self):
        """Test full signal stack with bullish conditions."""
        composite = SignalComposite()
        signals = {
            "fear_greed": normalize_fear_greed(15),
            "funding_rate": normalize_funding_rate(-0.0005),
            "long_short_ratio": normalize_long_short_ratio(0.35),
            "open_interest_change": normalize_open_interest_change(8.0),
            "price_momentum": normalize_price_momentum(3.0),
            "rsi": normalize_rsi(25),
            "volume_profile": normalize_volume_profile(0.7),
            "liquidation_imbalance": normalize_liquidation_imbalance(700000, 300000),
        }

        result = composite.calculate(signals)

        assert result.direction == "long"
        assert result.confidence >= 70
        assert result.active_signals >= 6
        assert result.agreement_ratio >= 0.7

    def test_full_stack_bearish(self):
        """Test full signal stack with bearish conditions."""
        composite = SignalComposite()
        signals = {
            "fear_greed": normalize_fear_greed(85),
            "funding_rate": normalize_funding_rate(0.002),
            "long_short_ratio": normalize_long_short_ratio(3.5),
            "open_interest_change": normalize_open_interest_change(-8.0),
            "price_momentum": normalize_price_momentum(-6.0),
            "rsi": normalize_rsi(78),
            "volume_profile": normalize_volume_profile(0.25),
            "liquidation_imbalance": normalize_liquidation_imbalance(200000, 800000),
        }

        result = composite.calculate(signals)

        assert result.direction == "short"
        assert result.confidence >= 70
        assert result.active_signals >= 6

    def test_full_stack_neutral(self):
        """Test full signal stack with neutral conditions."""
        composite = SignalComposite()
        signals = {
            "fear_greed": normalize_fear_greed(50),
            "funding_rate": normalize_funding_rate(0.0001),
            "long_short_ratio": normalize_long_short_ratio(1.0),
            "open_interest_change": normalize_open_interest_change(0.5),
            "price_momentum": normalize_price_momentum(0.2),
            "rsi": normalize_rsi(50),
            "volume_profile": normalize_volume_profile(0.5),
            "liquidation_imbalance": normalize_liquidation_imbalance(500000, 500000),
        }

        result = composite.calculate(signals)

        assert abs(result.score) < 0.2
        assert result.confidence <= 70
