"""Tests for selective data fetching in MarketDataFetcher."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.data.market_data import MarketDataFetcher


@pytest.fixture
def fetcher():
    f = MarketDataFetcher()
    f._session = MagicMock()
    return f


class TestFetchSelectedMetrics:
    """Test the fetch_selected_metrics dispatcher."""

    @pytest.mark.asyncio
    async def test_empty_sources_returns_empty(self, fetcher):
        result = await fetcher.fetch_selected_metrics([], "BTCUSDT")
        assert result == {}

    @pytest.mark.asyncio
    async def test_single_source_fear_greed(self, fetcher):
        with patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg:
            mock_fg.return_value = (75, "Greed")
            result = await fetcher.fetch_selected_metrics(["fear_greed"], "BTCUSDT")
            assert "fear_greed" in result
            assert result["fear_greed"] == (75, "Greed")
            mock_fg.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_source_funding_rate(self, fetcher):
        with patch.object(fetcher, "get_funding_rate_binance", new_callable=AsyncMock) as mock_fr:
            mock_fr.return_value = 0.0001
            result = await fetcher.fetch_selected_metrics(["funding_rate"], "BTCUSDT")
            assert "funding_rate" in result
            assert result["funding_rate"] == 0.0001
            mock_fr.assert_called_once_with("BTCUSDT")

    @pytest.mark.asyncio
    async def test_multiple_sources_parallel(self, fetcher):
        with (
            patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg,
            patch.object(fetcher, "get_long_short_ratio", new_callable=AsyncMock) as mock_ls,
            patch.object(fetcher, "get_open_interest", new_callable=AsyncMock) as mock_oi,
        ):
            mock_fg.return_value = (50, "Neutral")
            mock_ls.return_value = 1.2
            mock_oi.return_value = 50000.0

            result = await fetcher.fetch_selected_metrics(
                ["fear_greed", "long_short_ratio", "open_interest"], "BTCUSDT"
            )
            assert len(result) == 3
            assert result["fear_greed"] == (50, "Neutral")
            assert result["long_short_ratio"] == 1.2
            assert result["open_interest"] == 50000.0

    @pytest.mark.asyncio
    async def test_failed_source_omitted(self, fetcher):
        with (
            patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg,
            patch.object(fetcher, "get_long_short_ratio", new_callable=AsyncMock) as mock_ls,
        ):
            mock_fg.return_value = (50, "Neutral")
            mock_ls.side_effect = Exception("API timeout")

            result = await fetcher.fetch_selected_metrics(
                ["fear_greed", "long_short_ratio"], "BTCUSDT"
            )
            assert "fear_greed" in result
            assert "long_short_ratio" not in result  # Failed, omitted

    @pytest.mark.asyncio
    async def test_spot_price_ticker(self, fetcher):
        with patch.object(fetcher, "get_24h_ticker", new_callable=AsyncMock) as mock_ticker:
            mock_ticker.return_value = {"price": 100000.0, "price_change_percent": 2.5}
            result = await fetcher.fetch_selected_metrics(["spot_price"], "BTCUSDT")
            assert result["spot_price"]["price"] == 100000.0

    @pytest.mark.asyncio
    async def test_calculated_indicators_need_klines(self, fetcher):
        """VWAP and supertrend require klines to be fetched first."""
        mock_klines = [
            [0, "100", "110", "90", "105", "1000", 0, "0", 0, "500", "0", "0"]
            for _ in range(24)
        ]
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = mock_klines
            result = await fetcher.fetch_selected_metrics(["vwap", "supertrend"], "BTCUSDT")
            assert "vwap" in result
            assert "supertrend" in result
            mock_k.assert_called_once()

    @pytest.mark.asyncio
    async def test_options_sources_use_currency(self, fetcher):
        """Options sources should strip USDT from symbol."""
        with patch.object(fetcher, "get_options_oi_deribit", new_callable=AsyncMock) as mock_oi:
            mock_oi.return_value = {"total_oi": 1000.0, "num_instruments": 50, "currency": "BTC"}
            result = await fetcher.fetch_selected_metrics(["options_oi"], "BTCUSDT")
            mock_oi.assert_called_once_with("BTC")

    @pytest.mark.asyncio
    async def test_put_call_ratio(self, fetcher):
        with patch.object(fetcher, "get_put_call_ratio", new_callable=AsyncMock) as mock_pc:
            mock_pc.return_value = {"ratio": 0.8, "total_puts": 800, "total_calls": 1000}
            result = await fetcher.fetch_selected_metrics(["put_call_ratio"], "ETHUSDT")
            mock_pc.assert_called_once_with("ETH")
            assert result["put_call_ratio"]["ratio"] == 0.8

    @pytest.mark.asyncio
    async def test_coingecko_market(self, fetcher):
        with patch.object(fetcher, "get_coingecko_market", new_callable=AsyncMock) as mock_cg:
            mock_cg.return_value = {
                "total_market_cap_usd": 3e12,
                "btc_dominance_pct": 55.0,
                "active_cryptocurrencies": 10000,
            }
            result = await fetcher.fetch_selected_metrics(["coingecko_market"], "BTCUSDT")
            assert result["coingecko_market"]["btc_dominance_pct"] == 55.0

    @pytest.mark.asyncio
    async def test_cme_gap(self, fetcher):
        with patch.object(fetcher, "get_cme_gap", new_callable=AsyncMock) as mock_cme:
            mock_cme.return_value = {"gap_pct": 1.5, "friday_close": 98000, "current_price": 99470, "gap_direction": "up"}
            result = await fetcher.fetch_selected_metrics(["cme_gap"], "BTCUSDT")
            assert result["cme_gap"]["gap_direction"] == "up"

    @pytest.mark.asyncio
    async def test_trend_sma(self, fetcher):
        with patch.object(fetcher, "get_trend_direction", new_callable=AsyncMock) as mock_trend:
            mock_trend.return_value = "bullish"
            result = await fetcher.fetch_selected_metrics(["trend_sma"], "BTCUSDT")
            assert result["trend_sma"] == "bullish"

    @pytest.mark.asyncio
    async def test_unknown_source_ignored(self, fetcher):
        """Unknown source IDs should be silently ignored."""
        result = await fetcher.fetch_selected_metrics(["nonexistent_source"], "BTCUSDT")
        assert "nonexistent_source" not in result
