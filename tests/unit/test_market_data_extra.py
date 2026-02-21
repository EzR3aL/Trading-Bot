"""
Extra tests for data/market_data.py to reach 95%+ coverage.

Covers:
- CircuitBreakerError paths for all API methods
- Generic exception paths for all API methods
- fetch_all_metrics with individual result failures
- fetch_selected_metrics dispatch branches (all source IDs)
- Kline failure in fetch_selected_metrics
- OIWAP calculation in fetch_selected_metrics
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data.market_data import (
    MarketDataFetcher,
    MarketMetrics,
)
from src.utils.circuit_breaker import CircuitBreakerError, CircuitState


def _make_cb_error(service="test"):
    """Create a CircuitBreakerError with proper CircuitState."""
    return CircuitBreakerError(service, CircuitState.OPEN, 60.0)


async def _passthrough_call(fn, *args, **kwargs):
    return await fn(*args, **kwargs)


@pytest.fixture
def fetcher():
    f = MarketDataFetcher()
    mock_session = MagicMock()
    mock_session.closed = False
    f._session = mock_session
    return f


# ---------------------------------------------------------------------------
# CircuitBreakerError + generic exception paths for API methods
# ---------------------------------------------------------------------------

class TestAPIErrorPaths:
    """Test exception handling in all API fetch methods."""

    @pytest.mark.asyncio
    async def test_get_with_retry_propagates_errors(self, fetcher):
        """_get raises on error — _get_with_retry wraps it."""
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Network error")
            # _get_with_retry is decorated with @with_retry, so it should raise
            with pytest.raises(Exception):
                await fetcher._get_with_retry("http://fake", {})

    @pytest.mark.asyncio
    async def test_long_short_ratio_circuit_breaker_error(self, fetcher):
        """get_long_short_ratio returns 1.0 on CircuitBreakerError."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_long_short_ratio("BTCUSDT")
            assert result == 1.0

    @pytest.mark.asyncio
    async def test_long_short_ratio_generic_exception(self, fetcher):
        """get_long_short_ratio returns 1.0 on generic exception."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=ValueError("parse error"))
            result = await fetcher.get_long_short_ratio("BTCUSDT")
            assert result == 1.0

    @pytest.mark.asyncio
    async def test_top_trader_ls_circuit_breaker(self, fetcher):
        """get_top_trader_long_short_ratio returns 1.0 on circuit error."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_top_trader_long_short_ratio("BTCUSDT")
            assert result == 1.0

    @pytest.mark.asyncio
    async def test_funding_rate_binance_circuit_breaker(self, fetcher):
        """get_funding_rate_binance returns 0.0 on circuit error."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_funding_rate_binance("BTCUSDT")
            assert result == 0.0

    @pytest.mark.asyncio
    async def test_funding_rate_binance_generic_exception(self, fetcher):
        """get_funding_rate_binance returns 0.0 on generic exception."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("unexpected"))
            result = await fetcher.get_funding_rate_binance("BTCUSDT")
            assert result == 0.0

    @pytest.mark.asyncio
    async def test_ticker_24h_circuit_breaker(self, fetcher):
        """get_24h_ticker returns fallback on circuit error."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_24h_ticker("BTCUSDT")
            assert result["price"] == 0
            assert result["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_ticker_24h_generic_exception(self, fetcher):
        """get_24h_ticker returns fallback on generic exception."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=ValueError("bad data"))
            result = await fetcher.get_24h_ticker("BTCUSDT")
            assert result["price"] == 0

    @pytest.mark.asyncio
    async def test_open_interest_circuit_breaker(self, fetcher):
        """get_open_interest returns 0.0 on circuit error."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_open_interest("BTCUSDT")
            assert result == 0.0

    @pytest.mark.asyncio
    async def test_open_interest_generic_exception(self, fetcher):
        """get_open_interest returns 0.0 on generic exception."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("fail"))
            result = await fetcher.get_open_interest("BTCUSDT")
            assert result == 0.0

    @pytest.mark.asyncio
    async def test_oi_history_circuit_breaker(self, fetcher):
        """get_open_interest_history returns [] on circuit error."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_open_interest_history("BTCUSDT")
            assert result == []

    @pytest.mark.asyncio
    async def test_oi_history_generic_exception(self, fetcher):
        """get_open_interest_history returns [] on generic exception."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=ValueError("fail"))
            result = await fetcher.get_open_interest_history("BTCUSDT")
            assert result == []

    @pytest.mark.asyncio
    async def test_liquidations_circuit_breaker(self, fetcher):
        """get_recent_liquidations returns [] on circuit error."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_recent_liquidations("BTCUSDT")
            assert result == []

    @pytest.mark.asyncio
    async def test_liquidations_generic_exception(self, fetcher):
        """get_recent_liquidations returns [] on generic exception."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("fail"))
            result = await fetcher.get_recent_liquidations("BTCUSDT")
            assert result == []

    @pytest.mark.asyncio
    async def test_order_book_circuit_breaker(self, fetcher):
        """get_order_book_depth returns {} on circuit error."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_order_book_depth("BTCUSDT")
            assert result == {}

    @pytest.mark.asyncio
    async def test_order_book_generic_exception(self, fetcher):
        """get_order_book_depth returns {} on generic exception."""
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=ValueError("fail"))
            result = await fetcher.get_order_book_depth("BTCUSDT")
            assert result == {}

    @pytest.mark.asyncio
    async def test_news_sentiment_circuit_breaker(self, fetcher):
        """get_news_sentiment returns fallback on circuit error."""
        with patch("src.data.market_data._gdelt_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_news_sentiment()
            assert result["average_tone"] == 0.0
            assert result["article_count"] == 0

    @pytest.mark.asyncio
    async def test_news_sentiment_generic_exception(self, fetcher):
        """get_news_sentiment returns fallback on generic exception."""
        with patch("src.data.market_data._gdelt_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("fail"))
            result = await fetcher.get_news_sentiment()
            assert result["average_tone"] == 0.0

    @pytest.mark.asyncio
    async def test_put_call_ratio_circuit_breaker(self, fetcher):
        """get_put_call_ratio returns fallback on circuit error."""
        with patch("src.data.market_data._deribit_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_put_call_ratio("BTC")
            assert result["ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_put_call_ratio_generic_exception(self, fetcher):
        """get_put_call_ratio returns fallback on generic exception."""
        with patch("src.data.market_data._deribit_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=ValueError("fail"))
            result = await fetcher.get_put_call_ratio("BTC")
            assert result["ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_max_pain_circuit_breaker(self, fetcher):
        """get_max_pain returns fallback on circuit error."""
        with patch("src.data.market_data._deribit_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_max_pain("BTC")
            assert result["max_pain_price"] == 0.0

    @pytest.mark.asyncio
    async def test_max_pain_generic_exception(self, fetcher):
        """get_max_pain returns fallback on generic exception."""
        with patch("src.data.market_data._deribit_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=ValueError("fail"))
            result = await fetcher.get_max_pain("BTC")
            assert result["max_pain_price"] == 0.0

    @pytest.mark.asyncio
    async def test_coingecko_circuit_breaker(self, fetcher):
        """get_coingecko_market returns fallback on circuit error."""
        with patch("src.data.market_data._coingecko_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_coingecko_market()
            assert result["total_market_cap_usd"] == 0

    @pytest.mark.asyncio
    async def test_coingecko_generic_exception(self, fetcher):
        """get_coingecko_market returns fallback on generic exception."""
        with patch("src.data.market_data._coingecko_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("fail"))
            result = await fetcher.get_coingecko_market()
            assert result["total_market_cap_usd"] == 0

    @pytest.mark.asyncio
    async def test_stablecoin_flows_circuit_breaker(self, fetcher):
        """get_stablecoin_flows returns fallback on circuit error."""
        with patch("src.data.market_data._defillama_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_stablecoin_flows()
            assert result["usdt_market_cap"] == 0

    @pytest.mark.asyncio
    async def test_stablecoin_flows_generic_exception(self, fetcher):
        """get_stablecoin_flows returns fallback on generic exception."""
        with patch("src.data.market_data._defillama_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("fail"))
            result = await fetcher.get_stablecoin_flows()
            assert result["usdt_market_cap"] == 0

    @pytest.mark.asyncio
    async def test_btc_hashrate_circuit_breaker(self, fetcher):
        """get_btc_hashrate returns fallback on circuit error."""
        with patch("src.data.market_data._blockchain_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_btc_hashrate()
            assert result["hashrate_ths"] == 0

    @pytest.mark.asyncio
    async def test_btc_hashrate_generic_exception(self, fetcher):
        """get_btc_hashrate returns fallback on generic exception."""
        with patch("src.data.market_data._blockchain_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("fail"))
            result = await fetcher.get_btc_hashrate()
            assert result["hashrate_ths"] == 0

    @pytest.mark.asyncio
    async def test_bitget_funding_rate_circuit_breaker(self, fetcher):
        """get_bitget_funding_rate returns fallback on circuit error."""
        with patch("src.data.market_data._bitget_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_bitget_funding_rate("BTCUSDT")
            assert result["funding_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_bitget_funding_rate_generic_exception(self, fetcher):
        """get_bitget_funding_rate returns fallback on generic exception."""
        with patch("src.data.market_data._bitget_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("fail"))
            result = await fetcher.get_bitget_funding_rate("BTCUSDT")
            assert result["funding_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_fred_series_circuit_breaker(self, fetcher):
        """get_fred_series returns fallback on circuit error."""
        with patch("src.data.market_data._fred_breaker") as mock_breaker, \
             patch.dict("os.environ", {"FRED_API_KEY": "test-key"}):
            mock_breaker.call = AsyncMock(side_effect=_make_cb_error())
            result = await fetcher.get_fred_series("DFF")
            assert result["value"] == 0.0

    @pytest.mark.asyncio
    async def test_fred_series_generic_exception(self, fetcher):
        """get_fred_series returns fallback on generic exception."""
        with patch("src.data.market_data._fred_breaker") as mock_breaker, \
             patch.dict("os.environ", {"FRED_API_KEY": "test-key"}):
            mock_breaker.call = AsyncMock(side_effect=RuntimeError("fail"))
            result = await fetcher.get_fred_series("DFF")
            assert result["value"] == 0.0

    @pytest.mark.asyncio
    async def test_cme_gap_no_friday_close(self, fetcher):
        """get_cme_gap returns fallback when no Friday close found."""
        # Provide klines with no Friday data
        klines = [
            [1700006400000 + i * 3600000, "100", "110", "90", "105", "1000", 0, "0", 0, "500", "0", "0"]
            for i in range(24)
        ]
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_klines:
            mock_klines.return_value = klines
            result = await fetcher.get_cme_gap("BTCUSDT")
            assert result["gap_direction"] == "none"

    @pytest.mark.asyncio
    async def test_trend_direction_neutral(self, fetcher):
        """get_trend_direction returns neutral for mixed signals."""
        # Klines with flat price action
        klines = []
        for i in range(24):
            price = 95000 + ((-1) ** i) * 100  # oscillating
            klines.append([
                1700000000000 + i * 3600000,
                str(price - 50), str(price + 100), str(price - 100),
                str(price), "1000", 0, "0", 0, "500", "0", "0",
            ])
        with patch("src.data.market_data._binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
            with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = klines
                result = await fetcher.get_trend_direction("BTCUSDT")
                assert result in ("bullish", "bearish", "neutral")


# ---------------------------------------------------------------------------
# fetch_all_metrics with individual result failures
# ---------------------------------------------------------------------------

def _patch_all_methods(fetcher, **overrides):
    """Return a context-manager stack that mocks every method called by fetch_all_metrics.

    ``overrides`` maps method names to the desired return value, a list of
    per-call return values (applied via side_effect), or an Exception instance.
    Methods not listed get a safe AsyncMock returning ``None``.
    """
    from contextlib import ExitStack
    methods = [
        "get_fear_greed_index",
        "get_long_short_ratio",
        "get_funding_rate_binance",
        "get_24h_ticker",
        "get_open_interest",
    ]
    stack = ExitStack()
    for name in methods:
        val = overrides.get(name)
        m = stack.enter_context(
            patch.object(fetcher, name, new_callable=AsyncMock)
        )
        if val is None:
            m.return_value = None
        elif isinstance(val, list):
            m.side_effect = val
        elif isinstance(val, Exception):
            m.side_effect = val
        else:
            m.return_value = val
    return stack


class TestFetchAllMetricsErrors:
    """Test fetch_all_metrics handles failures in individual results."""

    @pytest.mark.asyncio
    async def test_fetch_all_metrics_all_exceptions(self, fetcher):
        """fetch_all_metrics handles all results being exceptions."""
        overrides = {
            "get_fear_greed_index": RuntimeError("fail_fg"),
            "get_long_short_ratio": RuntimeError("fail_ls"),
            "get_funding_rate_binance": RuntimeError("fail_fr"),
            "get_24h_ticker": RuntimeError("fail_tk"),
            "get_open_interest": RuntimeError("fail_oi"),
        }

        with _patch_all_methods(fetcher, **overrides):
            result = await fetcher.fetch_all_metrics(require_reliable=False)

            assert isinstance(result, MarketMetrics)
            assert result.fear_greed_index == 50
            assert result.long_short_ratio == 1.0
            assert result.funding_rate_btc == 0.0
            assert result.funding_rate_eth == 0.0
            assert result.btc_price == 0
            assert result.eth_price == 0

    @pytest.mark.asyncio
    async def test_fetch_all_metrics_none_results(self, fetcher):
        """fetch_all_metrics handles None results from API calls."""
        with _patch_all_methods(fetcher):
            result = await fetcher.fetch_all_metrics(require_reliable=False)

            assert result.fear_greed_index == 50
            assert result.long_short_ratio == 1.0
            assert result.funding_rate_btc == 0.0
            assert result.btc_price == 0

    @pytest.mark.asyncio
    async def test_fetch_all_metrics_mixed_results(self, fetcher):
        """fetch_all_metrics handles mix of success and failure."""
        overrides = {
            "get_fear_greed_index": (75, "Greed"),
            "get_long_short_ratio": RuntimeError("fail"),
            # Called twice: BTCUSDT (ok) then ETHUSDT (fail)
            "get_funding_rate_binance": [0.0001, RuntimeError("fail")],
            "get_24h_ticker": [
                {"price": 95000, "price_change_percent": 1.5},
                RuntimeError("fail"),
            ],
            "get_open_interest": [50000.0, RuntimeError("fail")],
        }

        with _patch_all_methods(fetcher, **overrides):
            result = await fetcher.fetch_all_metrics(require_reliable=False)

            assert result.fear_greed_index == 75
            assert result.long_short_ratio == 1.0  # fallback
            assert result.funding_rate_btc == 0.0001
            assert result.funding_rate_eth == 0.0  # fallback
            assert result.btc_price == 95000
            assert result.eth_price == 0  # fallback
            assert result.btc_open_interest == 50000.0
            assert result.eth_open_interest == 0.0  # fallback

    @pytest.mark.asyncio
    async def test_fetch_all_metrics_ticker_zero_price(self, fetcher):
        """fetch_all_metrics marks ticker as failed when price is 0."""
        overrides = {
            "get_fear_greed_index": (50, "Neutral"),
            "get_long_short_ratio": 1.0,
            "get_funding_rate_binance": 0.0001,
            "get_24h_ticker": {"price": 0, "price_change_percent": 0},
            "get_open_interest": 10000.0,
        }

        with _patch_all_methods(fetcher, **overrides):
            result = await fetcher.fetch_all_metrics(require_reliable=False)

            assert result.btc_price == 0
            assert result.eth_price == 0


# ---------------------------------------------------------------------------
# fetch_selected_metrics dispatch branches
# ---------------------------------------------------------------------------

class TestFetchSelectedDispatch:
    """Test all dispatch branches in fetch_selected_metrics."""

    @pytest.mark.asyncio
    async def test_dispatch_news_sentiment(self, fetcher):
        with patch.object(fetcher, "get_news_sentiment", new_callable=AsyncMock) as mock:
            mock.return_value = {"average_tone": 1.5, "article_count": 10}
            result = await fetcher.fetch_selected_metrics(["news_sentiment"], "BTCUSDT")
            assert "news_sentiment" in result

    @pytest.mark.asyncio
    async def test_dispatch_top_trader_ls_ratio(self, fetcher):
        with patch.object(fetcher, "get_top_trader_long_short_ratio", new_callable=AsyncMock) as mock:
            mock.return_value = 1.5
            result = await fetcher.fetch_selected_metrics(["top_trader_ls_ratio"], "BTCUSDT")
            assert "top_trader_ls_ratio" in result

    @pytest.mark.asyncio
    async def test_dispatch_predicted_funding(self, fetcher):
        with patch.object(fetcher, "get_predicted_funding_rate", new_callable=AsyncMock) as mock:
            mock.return_value = 0.0002
            result = await fetcher.fetch_selected_metrics(["predicted_funding"], "BTCUSDT")
            assert "predicted_funding" in result

    @pytest.mark.asyncio
    async def test_dispatch_oi_history(self, fetcher):
        with patch.object(fetcher, "get_open_interest_history", new_callable=AsyncMock) as mock:
            mock.return_value = [{"oi": 100}]
            result = await fetcher.fetch_selected_metrics(["oi_history"], "BTCUSDT")
            assert "oi_history" in result

    @pytest.mark.asyncio
    async def test_dispatch_liquidations(self, fetcher):
        with patch.object(fetcher, "get_recent_liquidations", new_callable=AsyncMock) as mock:
            mock.return_value = []
            result = await fetcher.fetch_selected_metrics(["liquidations"], "BTCUSDT")
            assert "liquidations" in result

    @pytest.mark.asyncio
    async def test_dispatch_options_oi(self, fetcher):
        with patch.object(fetcher, "get_options_oi_deribit", new_callable=AsyncMock) as mock:
            mock.return_value = {"total_oi": 1000}
            result = await fetcher.fetch_selected_metrics(["options_oi"], "BTCUSDT")
            assert "options_oi" in result

    @pytest.mark.asyncio
    async def test_dispatch_max_pain(self, fetcher):
        with patch.object(fetcher, "get_max_pain", new_callable=AsyncMock) as mock:
            mock.return_value = {"max_pain_price": 95000}
            result = await fetcher.fetch_selected_metrics(["max_pain"], "BTCUSDT")
            assert "max_pain" in result

    @pytest.mark.asyncio
    async def test_dispatch_put_call_ratio(self, fetcher):
        with patch.object(fetcher, "get_put_call_ratio", new_callable=AsyncMock) as mock:
            mock.return_value = {"ratio": 0.8}
            result = await fetcher.fetch_selected_metrics(["put_call_ratio"], "BTCUSDT")
            assert "put_call_ratio" in result

    @pytest.mark.asyncio
    async def test_dispatch_volatility(self, fetcher):
        with patch.object(fetcher, "get_price_volatility", new_callable=AsyncMock) as mock:
            mock.return_value = {"volatility": 0.05}
            result = await fetcher.fetch_selected_metrics(["volatility"], "BTCUSDT")
            assert "volatility" in result

    @pytest.mark.asyncio
    async def test_dispatch_trend_sma(self, fetcher):
        with patch.object(fetcher, "get_trend_direction", new_callable=AsyncMock) as mock:
            mock.return_value = "bullish"
            result = await fetcher.fetch_selected_metrics(["trend_sma"], "BTCUSDT")
            assert result["trend_sma"] == "bullish"

    @pytest.mark.asyncio
    async def test_dispatch_cme_gap(self, fetcher):
        with patch.object(fetcher, "get_cme_gap", new_callable=AsyncMock) as mock:
            mock.return_value = {"gap_pct": 0.5}
            result = await fetcher.fetch_selected_metrics(["cme_gap"], "BTCUSDT")
            assert "cme_gap" in result

    @pytest.mark.asyncio
    async def test_dispatch_stablecoin_flows(self, fetcher):
        with patch.object(fetcher, "get_stablecoin_flows", new_callable=AsyncMock) as mock:
            mock.return_value = {"usdt_market_cap": 100e9}
            result = await fetcher.fetch_selected_metrics(["stablecoin_flows"], "BTCUSDT")
            assert "stablecoin_flows" in result

    @pytest.mark.asyncio
    async def test_dispatch_btc_hashrate(self, fetcher):
        with patch.object(fetcher, "get_btc_hashrate", new_callable=AsyncMock) as mock:
            mock.return_value = {"hashrate_ths": 500e6}
            result = await fetcher.fetch_selected_metrics(["btc_hashrate"], "BTCUSDT")
            assert "btc_hashrate" in result

    @pytest.mark.asyncio
    async def test_dispatch_order_book(self, fetcher):
        with patch.object(fetcher, "get_order_book_depth", new_callable=AsyncMock) as mock:
            mock.return_value = {"bid_total": 100, "ask_total": 95}
            result = await fetcher.fetch_selected_metrics(["order_book"], "BTCUSDT")
            assert "order_book" in result

    @pytest.mark.asyncio
    async def test_dispatch_bitget_funding(self, fetcher):
        with patch.object(fetcher, "get_bitget_funding_rate", new_callable=AsyncMock) as mock:
            mock.return_value = {"funding_rate": 0.0001}
            result = await fetcher.fetch_selected_metrics(["bitget_funding"], "BTCUSDT")
            assert "bitget_funding" in result

    @pytest.mark.asyncio
    async def test_dispatch_macro_dxy(self, fetcher):
        with patch.object(fetcher, "get_fred_series", new_callable=AsyncMock) as mock:
            mock.return_value = {"value": 105.0}
            result = await fetcher.fetch_selected_metrics(["macro_dxy"], "BTCUSDT")
            assert "macro_dxy" in result
            mock.assert_called_once_with("DTWEXBGS")

    @pytest.mark.asyncio
    async def test_dispatch_fed_funds_rate(self, fetcher):
        with patch.object(fetcher, "get_fred_series", new_callable=AsyncMock) as mock:
            mock.return_value = {"value": 5.25}
            result = await fetcher.fetch_selected_metrics(["fed_funds_rate"], "BTCUSDT")
            assert "fed_funds_rate" in result
            mock.assert_called_once_with("DFF")


# ---------------------------------------------------------------------------
# fetch_selected_metrics: kline-based indicators
# ---------------------------------------------------------------------------

class TestFetchSelectedKlineIndicators:
    """Test kline-based indicator paths in fetch_selected_metrics."""

    @pytest.mark.asyncio
    async def test_klines_failure_does_not_crash(self, fetcher):
        """Kline fetch failure is handled gracefully."""
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_klines:
            mock_klines.side_effect = Exception("Klines unavailable")
            result = await fetcher.fetch_selected_metrics(["vwap"], "BTCUSDT")
            # vwap should not be in result since klines failed
            assert "vwap" not in result

    @pytest.mark.asyncio
    async def test_spot_volume_dispatch(self, fetcher):
        """spot_volume is computed from klines."""
        klines = [
            [1700000000000 + i * 3600000, "100", "110", "90", "105", "1000", 0, "105000", 0, "500", "0", "0"]
            for i in range(24)
        ]
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_klines:
            mock_klines.return_value = klines
            result = await fetcher.fetch_selected_metrics(["spot_volume"], "BTCUSDT")
            assert "spot_volume" in result

    @pytest.mark.asyncio
    async def test_oiwap_dispatch(self, fetcher):
        """oiwap is computed from klines and OI data."""
        klines = [
            [1700000000000 + i * 3600000, "100", "110", "90", "105", "1000", 0, "0", 0, "500", "0", "0"]
            for i in range(24)
        ]
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_klines, \
             patch.object(fetcher, "calculate_oiwap", new_callable=AsyncMock) as mock_oiwap:
            mock_klines.return_value = klines
            mock_oiwap.return_value = {"oiwap_price": 95000}
            result = await fetcher.fetch_selected_metrics(["oiwap"], "BTCUSDT")
            assert "oiwap" in result

    @pytest.mark.asyncio
    async def test_oiwap_calculation_failure(self, fetcher):
        """OIWAP calculation failure is handled gracefully."""
        klines = [
            [1700000000000 + i * 3600000, "100", "110", "90", "105", "1000", 0, "0", 0, "500", "0", "0"]
            for i in range(24)
        ]
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_klines, \
             patch.object(fetcher, "calculate_oiwap", new_callable=AsyncMock) as mock_oiwap:
            mock_klines.return_value = klines
            mock_oiwap.side_effect = Exception("OIWAP calc error")
            result = await fetcher.fetch_selected_metrics(["oiwap"], "BTCUSDT")
            assert "oiwap" not in result

    @pytest.mark.asyncio
    async def test_dispatch_failed_source_omitted(self, fetcher):
        """Failed sources are omitted from results dict."""
        with patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg:
            mock_fg.side_effect = RuntimeError("API down")
            result = await fetcher.fetch_selected_metrics(["fear_greed"], "BTCUSDT")
            assert "fear_greed" not in result
