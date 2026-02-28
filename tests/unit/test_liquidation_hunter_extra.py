"""
Extra tests for Liquidation Hunter Strategy to cover remaining gaps.

Covers:
- _ensure_fetcher creating new fetcher when None
- Non-BTC/ETH symbol handling (generic symbol branch)
- Leverage-only signal (no sentiment extreme)
- Sentiment-only signal (no leverage extreme)
- Invalid price (0) -> TP/SL = 0
- should_trade TP/SL validation for LONG and SHORT
- close() method
- get_description / get_param_schema class methods
- Custom params override defaults
"""

from unittest.mock import AsyncMock, patch
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.liquidation_hunter import (
    LiquidationHunterStrategy,
    SignalDirection,
    TradeSignal,
    DEFAULTS,
)


class TestEnsureFetcher:
    """Tests for _ensure_fetcher creating a MarketDataFetcher when None."""

    async def test_creates_fetcher_when_none(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        assert strategy.data_fetcher is None

        with patch("src.strategy.liquidation_hunter.MarketDataFetcher") as MockFetcher:
            mock_instance = AsyncMock()
            MockFetcher.return_value = mock_instance

            await strategy._ensure_fetcher()

            MockFetcher.assert_called_once()
            mock_instance._ensure_session.assert_awaited_once()
            assert strategy.data_fetcher is mock_instance

    async def test_does_not_recreate_if_already_set(self):
        mock_fetcher = AsyncMock()
        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)

        with patch("src.strategy.liquidation_hunter.MarketDataFetcher") as MockFetcher:
            await strategy._ensure_fetcher()
            MockFetcher.assert_not_called()


class TestNonBtcEthSymbol:
    """Tests for generating signals on non-BTC/ETH symbols."""

    async def test_generic_symbol_fetches_funding_and_ticker(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=50,
            long_short_ratio=1.0,
            funding_rate_btc=0.0001,
            btc_price=95000.0,
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)
        mock_fetcher.get_funding_rate_binance = AsyncMock(return_value=0.0003)
        mock_fetcher.get_24h_ticker = AsyncMock(return_value={
            "price": 150.0,
            "price_change_percent": 2.5,
        })

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("SOLUSDT")

        assert signal.symbol == "SOLUSDT"
        assert signal.entry_price == 150.0
        mock_fetcher.get_funding_rate_binance.assert_awaited_once_with("SOLUSDT")
        mock_fetcher.get_24h_ticker.assert_awaited_once_with("SOLUSDT")

    async def test_generic_symbol_funding_rate_error_defaults_to_zero(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=50,
            long_short_ratio=1.0,
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)
        mock_fetcher.get_funding_rate_binance = AsyncMock(side_effect=Exception("API down"))
        mock_fetcher.get_24h_ticker = AsyncMock(return_value={
            "price": 100.0,
            "price_change_percent": 1.0,
        })

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("SOLUSDT")

        assert signal.entry_price == 100.0

    async def test_generic_symbol_ticker_error_defaults_to_zero(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=50,
            long_short_ratio=1.0,
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)
        mock_fetcher.get_funding_rate_binance = AsyncMock(return_value=0.0001)
        mock_fetcher.get_24h_ticker = AsyncMock(side_effect=Exception("timeout"))

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("SOLUSDT")

        assert signal.entry_price == 0
        assert signal.target_price == 0.0
        assert signal.stop_loss == 0.0

    async def test_generic_symbol_funding_rate_none_defaults_to_zero(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=50,
            long_short_ratio=1.0,
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)
        mock_fetcher.get_funding_rate_binance = AsyncMock(return_value=None)
        mock_fetcher.get_24h_ticker = AsyncMock(return_value=None)

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("SOLUSDT")

        assert signal.entry_price == 0


class TestLeverageOnlySignal:
    """Test when only leverage is extreme (no sentiment extreme)."""

    async def test_leverage_only_long(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=50,  # neutral
            long_short_ratio=0.3,  # crowded shorts
            btc_price=90000.0,
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.LONG
        assert "Leverage-driven signal" in signal.reason

    async def test_leverage_only_short(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=50,  # neutral
            long_short_ratio=3.0,  # crowded longs
            btc_price=90000.0,
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.SHORT
        assert "Leverage-driven signal" in signal.reason


class TestSentimentOnlySignal:
    """Test when only sentiment is extreme (no leverage extreme)."""

    async def test_sentiment_only_long(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=10,  # extreme fear
            long_short_ratio=1.0,  # neutral
            btc_price=90000.0,
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.LONG
        assert "Sentiment-driven signal" in signal.reason

    async def test_sentiment_only_short(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=95,  # extreme greed
            long_short_ratio=1.0,  # neutral
            btc_price=90000.0,
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.SHORT
        assert "Sentiment-driven signal" in signal.reason


class TestInvalidPriceHandling:
    """Test signal generation when price is 0 or invalid."""

    async def test_zero_price_sets_tp_sl_to_zero(self, mock_market_metrics):
        metrics = mock_market_metrics(
            fear_greed_index=85,
            long_short_ratio=3.0,
            btc_price=0.0,  # Invalid price
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_all_metrics = AsyncMock(return_value=metrics)

        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)
        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.target_price == 0.0
        assert signal.stop_loss == 0.0


class TestShouldTradeValidation:
    """Tests for TP/SL validation in should_trade."""

    def _make_signal(self, direction, entry, tp, sl, confidence=80):
        return TradeSignal(
            direction=direction,
            confidence=confidence,
            symbol="BTCUSDT",
            entry_price=entry,
            target_price=tp,
            stop_loss=sl,
            reason="test",
            metrics_snapshot={},
            timestamp=datetime.now(),
        )

    async def test_long_tp_below_entry_rejected(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        signal = self._make_signal(SignalDirection.LONG, 100.0, 90.0, 95.0)  # TP < entry

        ok, reason = await strategy.should_trade(signal)
        assert ok is False
        assert "TP" in reason

    async def test_long_sl_above_entry_rejected(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        signal = self._make_signal(SignalDirection.LONG, 100.0, 110.0, 105.0)  # SL > entry

        ok, reason = await strategy.should_trade(signal)
        assert ok is False
        assert "SL" in reason

    async def test_short_tp_above_entry_rejected(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        signal = self._make_signal(SignalDirection.SHORT, 100.0, 110.0, 105.0)  # TP > entry

        ok, reason = await strategy.should_trade(signal)
        assert ok is False
        assert "TP" in reason

    async def test_short_sl_below_entry_rejected(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        signal = self._make_signal(SignalDirection.SHORT, 100.0, 90.0, 95.0)  # SL < entry

        ok, reason = await strategy.should_trade(signal)
        assert ok is False
        assert "SL" in reason

    async def test_zero_tp_rejected(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        signal = self._make_signal(SignalDirection.LONG, 100.0, 0.0, 95.0)

        ok, reason = await strategy.should_trade(signal)
        assert ok is False
        assert "TP" in reason

    async def test_zero_sl_for_long_accepted(self):
        """SL=0.0 for LONG is directionally valid (below entry) so it passes validation."""
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        signal = self._make_signal(SignalDirection.LONG, 100.0, 110.0, 0.0)

        ok, reason = await strategy.should_trade(signal)
        # SL=0.0 is below entry=100.0, which is the correct direction for LONG
        assert ok is True

    async def test_valid_short_approved(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        signal = self._make_signal(SignalDirection.SHORT, 100.0, 90.0, 110.0)

        ok, reason = await strategy.should_trade(signal)
        assert ok is True


class TestCloseMethod:
    """Tests for the close() cleanup method."""

    async def test_close_calls_fetcher_close(self):
        mock_fetcher = AsyncMock()
        strategy = LiquidationHunterStrategy(data_fetcher=mock_fetcher)

        await strategy.close()

        mock_fetcher.close.assert_awaited_once()

    async def test_close_with_no_fetcher(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        await strategy.close()  # Should not raise


class TestClassMethods:
    """Tests for class-level methods."""

    def test_get_description_returns_string(self):
        desc = LiquidationHunterStrategy.get_description()
        assert isinstance(desc, str)
        assert "contrarian" in desc.lower() or "liquidation" in desc.lower()

    def test_get_param_schema_contains_all_params(self):
        schema = LiquidationHunterStrategy.get_param_schema()
        expected_keys = [
            "fear_greed_extreme_fear", "fear_greed_extreme_greed",
            "long_short_crowded_longs", "long_short_crowded_shorts",
            "funding_rate_high", "funding_rate_low",
            "high_confidence_min", "low_confidence_min",
        ]
        for key in expected_keys:
            assert key in schema
            assert "type" in schema[key]
            assert "default" in schema[key]


class TestCustomParams:
    """Tests for custom parameter overrides."""

    def test_custom_params_override_defaults(self):
        strategy = LiquidationHunterStrategy(params={"fear_greed_extreme_fear": 30})
        assert strategy._p["fear_greed_extreme_fear"] == 30
        # Other defaults remain
        assert strategy._p["fear_greed_extreme_greed"] == DEFAULTS["fear_greed_extreme_greed"]

    def test_trend_direction_positive_is_long(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        assert strategy._get_trend_direction(2.5) == SignalDirection.LONG

    def test_trend_direction_negative_is_short(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        assert strategy._get_trend_direction(-1.5) == SignalDirection.SHORT

    def test_trend_direction_zero_is_short(self):
        strategy = LiquidationHunterStrategy(data_fetcher=None)
        assert strategy._get_trend_direction(0.0) == SignalDirection.SHORT
