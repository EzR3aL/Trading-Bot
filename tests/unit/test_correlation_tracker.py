"""
Tests for the Correlation Tracker module.
"""

import pytest
from datetime import datetime, timedelta

from src.portfolio.correlation import CorrelationTracker


class TestCorrelationTracker:
    """Tests for CorrelationTracker class."""

    @pytest.fixture
    def tracker(self):
        """Create a test tracker."""
        return CorrelationTracker(window=30)

    @pytest.fixture
    def tracker_with_data(self, tracker):
        """Create a tracker with sample price data."""
        base = datetime.now() - timedelta(days=30)

        for i in range(30):
            ts = base + timedelta(days=i)
            # BTC and ETH move together (high correlation)
            btc_price = 50000 + (i * 100) + ((-1) ** i * 200)
            eth_price = 3000 + (i * 6) + ((-1) ** i * 15)
            # DOGE moves more independently
            doge_price = 0.10 + (i * 0.001) + ((-1) ** (i + 1) * 0.005)

            tracker.record_price("BTCUSDT", btc_price, ts)
            tracker.record_price("ETHUSDT", eth_price, ts)
            tracker.record_price("DOGEUSDT", doge_price, ts)

        return tracker

    def test_record_price(self, tracker):
        """Test recording a price observation."""
        tracker.record_price("BTCUSDT", 50000.0)

        assert "BTCUSDT" in tracker._price_history
        assert len(tracker._price_history["BTCUSDT"]) == 1

    def test_price_history_trimming(self, tracker):
        """Test old price data is removed."""
        base = datetime.now() - timedelta(days=100)

        for i in range(100):
            ts = base + timedelta(days=i)
            tracker.record_price("BTCUSDT", 50000 + i, ts)

        # Should keep only ~60 days (2x window)
        assert len(tracker._price_history["BTCUSDT"]) <= 61

    def test_correlation_matrix(self, tracker_with_data):
        """Test correlation matrix calculation."""
        matrix = tracker_with_data.calculate_correlation_matrix()

        assert not matrix.empty
        assert "BTCUSDT" in matrix.columns
        assert "ETHUSDT" in matrix.columns

        # Self-correlation should be 1.0
        assert matrix.loc["BTCUSDT", "BTCUSDT"] == pytest.approx(1.0)

    def test_get_correlation_pair(self, tracker_with_data):
        """Test getting correlation between two assets."""
        corr = tracker_with_data.get_correlation("BTCUSDT", "ETHUSDT")

        assert corr is not None
        assert -1.0 <= corr <= 1.0

    def test_get_correlation_unknown(self, tracker):
        """Test getting correlation for unknown pair."""
        corr = tracker.get_correlation("UNKNOWN1", "UNKNOWN2")

        assert corr is None

    def test_get_matrix_dict(self, tracker_with_data):
        """Test getting matrix as nested dict."""
        matrix_dict = tracker_with_data.get_matrix()

        assert isinstance(matrix_dict, dict)
        assert "BTCUSDT" in matrix_dict
        assert "ETHUSDT" in matrix_dict["BTCUSDT"]

    def test_diversification_score(self, tracker_with_data):
        """Test diversification score calculation."""
        score = tracker_with_data.get_portfolio_diversification_score()

        assert 0.0 <= score <= 1.0

    def test_diversification_score_no_data(self, tracker):
        """Test diversification score with no data."""
        score = tracker.get_portfolio_diversification_score()

        assert score == 0.5  # Neutral default

    def test_high_correlation_pairs(self, tracker_with_data):
        """Test finding highly correlated pairs."""
        pairs = tracker_with_data.get_high_correlation_pairs(threshold=0.5)

        # Should return list of dicts
        assert isinstance(pairs, list)
        for pair in pairs:
            assert "symbol_a" in pair
            assert "symbol_b" in pair
            assert "correlation" in pair

    def test_needs_update(self, tracker):
        """Test update check."""
        assert tracker._needs_update() is True

        # After calculation, should not need update
        tracker._last_update = datetime.now()
        assert tracker._needs_update() is False

    def test_matrix_with_insufficient_data(self, tracker):
        """Test matrix calculation with insufficient data."""
        tracker.record_price("BTCUSDT", 50000.0)

        matrix = tracker.calculate_correlation_matrix()

        assert matrix.empty
