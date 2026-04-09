"""
Comprehensive unit tests for MarketDataFetcher and related classes.

Tests cover:
- DataFetchError custom exception
- DataQuality tracking (success, failure, reliability, success rate)
- MarketMetrics dataclass (to_dict, is_reliable)
- MarketDataFetcher initialization and session management
- HTTP request handling (_get method)
- Fear & Greed Index fetching
- Long/Short Ratio (global + top trader)
- Funding Rates (Binance current + predicted, Bitget)
- 24h Ticker data
- Open Interest (current + history)
- Liquidations
- Order Book Depth analysis
- Price Volatility calculation
- Trend Direction (SMA-based)
- News Sentiment (GDELT)
- Kline / Candlestick data
- VWAP calculation (static)
- Supertrend indicator (static)
- Spot Volume Analysis (static)
- OIWAP calculation
- Deribit Options (OI, Max Pain, Put/Call Ratio)
- CoinGecko global market data
- Stablecoin Flows (DefiLlama)
- BTC Hashrate (Blockchain.info)
- FRED macro data
- CME Gap detection
- fetch_all_metrics aggregation
- Edge cases: empty data, malformed responses, timeouts, circuit breaker errors
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import aiohttp

from src.data.market_data import (
    DataFetchError,
    DataQuality,
    MarketDataFetcher,
    MarketMetrics,
)
from src.utils.circuit_breaker import CircuitBreakerError, CircuitState


# Helper for mocking circuit breaker .call() that awaits the passed async function
async def _passthrough_call(fn, *args, **kwargs):
    """Simulate circuit breaker call by awaiting the passed function."""
    return await fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fetcher():
    """Create a MarketDataFetcher with a mocked session."""
    f = MarketDataFetcher()
    f._session = MagicMock()
    return f


@pytest.fixture
def sample_klines():
    """Return sample kline data (24 candles)."""
    # [open_time, open, high, low, close, volume, close_time,
    #  quote_volume, num_trades, taker_buy_base_vol, taker_buy_quote_vol, ignore]
    return [
        [1700000000000 + i * 3600000, "100", "110", "90", "105", "1000", 0, "0", 0, "500", "0", "0"]
        for i in range(24)
    ]


@pytest.fixture
def bullish_klines():
    """Return kline data with a clear uptrend for trend tests."""
    klines = []
    for i in range(24):
        price = 90000 + i * 500  # steadily rising
        klines.append([
            1700000000000 + i * 3600000,
            str(price - 200),  # open
            str(price + 300),  # high
            str(price - 300),  # low
            str(price),        # close
            "1000",            # volume
            0, "0", 0,
            "500",             # taker buy
            "0", "0",
        ])
    return klines


@pytest.fixture
def bearish_klines():
    """Return kline data with a clear downtrend for trend tests."""
    klines = []
    for i in range(24):
        price = 100000 - i * 500  # steadily falling
        klines.append([
            1700000000000 + i * 3600000,
            str(price + 200),
            str(price + 300),
            str(price - 300),
            str(price),
            "1000",
            0, "0", 0, "500", "0", "0",
        ])
    return klines


# ---------------------------------------------------------------------------
# DataFetchError tests
# ---------------------------------------------------------------------------

class TestDataFetchError:
    """Tests for the DataFetchError custom exception."""

    def test_error_with_source_and_message(self):
        err = DataFetchError("binance", "connection timeout")
        assert err.source == "binance"
        assert err.message == "connection timeout"
        assert err.original_error is None
        assert "[binance]" in str(err)
        assert "connection timeout" in str(err)

    def test_error_with_original_exception(self):
        original = ConnectionError("refused")
        err = DataFetchError("gdelt", "network error", original_error=original)
        assert err.original_error is original
        assert err.source == "gdelt"

    def test_error_is_exception(self):
        err = DataFetchError("api", "fail")
        assert isinstance(err, Exception)

    def test_error_can_be_caught_as_exception(self):
        with pytest.raises(DataFetchError):
            raise DataFetchError("test", "test error")


# ---------------------------------------------------------------------------
# DataQuality tests
# ---------------------------------------------------------------------------

class TestDataQuality:
    """Tests for the DataQuality tracker."""

    def test_initial_state(self):
        dq = DataQuality()
        assert dq.failed_sources == []
        assert dq.successful_sources == []
        assert dq.warnings == []
        assert dq.fetch_timestamps == {}

    def test_mark_success(self):
        dq = DataQuality()
        dq.mark_success("fear_greed")
        assert "fear_greed" in dq.successful_sources
        assert "fear_greed" in dq.fetch_timestamps
        assert isinstance(dq.fetch_timestamps["fear_greed"], float)

    def test_mark_failure(self):
        dq = DataQuality()
        dq.mark_failure("binance_api", "timeout")
        assert "binance_api" in dq.failed_sources
        assert any("binance_api" in w and "timeout" in w for w in dq.warnings)

    def test_is_reliable_when_all_critical_succeed(self):
        dq = DataQuality()
        dq.mark_success("fear_greed")
        dq.mark_success("long_short_ratio")
        dq.mark_success("ticker_btc")
        assert dq.is_reliable is True

    def test_is_reliable_when_critical_source_missing(self):
        dq = DataQuality()
        dq.mark_success("fear_greed")
        dq.mark_success("long_short_ratio")
        # ticker_btc missing
        assert dq.is_reliable is False

    def test_is_reliable_when_non_critical_fails(self):
        dq = DataQuality()
        dq.mark_success("fear_greed")
        dq.mark_success("long_short_ratio")
        dq.mark_success("ticker_btc")
        dq.mark_failure("news_sentiment", "timeout")
        assert dq.is_reliable is True

    def test_success_rate_no_data(self):
        dq = DataQuality()
        assert dq.success_rate == 0.0

    def test_success_rate_all_success(self):
        dq = DataQuality()
        dq.mark_success("a")
        dq.mark_success("b")
        dq.mark_success("c")
        assert dq.success_rate == 100.0

    def test_success_rate_mixed(self):
        dq = DataQuality()
        dq.mark_success("a")
        dq.mark_failure("b", "err")
        assert dq.success_rate == 50.0

    def test_success_rate_all_failed(self):
        dq = DataQuality()
        dq.mark_failure("a", "err1")
        dq.mark_failure("b", "err2")
        assert dq.success_rate == 0.0

    def test_to_dict(self):
        dq = DataQuality()
        dq.mark_success("fear_greed")
        dq.mark_failure("news", "timeout")
        result = dq.to_dict()
        assert "is_reliable" in result
        assert "success_rate" in result
        assert "failed_sources" in result
        assert "warnings" in result
        assert result["failed_sources"] == ["news"]


# ---------------------------------------------------------------------------
# MarketMetrics tests
# ---------------------------------------------------------------------------

class TestMarketMetrics:
    """Tests for the MarketMetrics dataclass."""

    def _make_metrics(self, **kwargs):
        defaults = dict(
            fear_greed_index=50,
            fear_greed_classification="Neutral",
            long_short_ratio=1.0,
            funding_rate_btc=0.0001,
            funding_rate_eth=0.0001,
            btc_24h_change_percent=1.5,
            eth_24h_change_percent=-0.5,
            btc_price=95000.0,
            eth_price=3500.0,
            btc_open_interest=100000.0,
            eth_open_interest=50000.0,
            timestamp=datetime(2025, 1, 15, 12, 0, 0),
        )
        defaults.update(kwargs)
        return MarketMetrics(**defaults)

    def test_to_dict_contains_all_fields(self):
        m = self._make_metrics()
        d = m.to_dict()
        assert d["fear_greed_index"] == 50
        assert d["fear_greed_classification"] == "Neutral"
        assert d["long_short_ratio"] == 1.0
        assert d["funding_rate_btc"] == 0.0001
        assert d["funding_rate_eth"] == 0.0001
        assert d["btc_24h_change_percent"] == 1.5
        assert d["eth_24h_change_percent"] == -0.5
        assert d["btc_price"] == 95000.0
        assert d["eth_price"] == 3500.0
        assert d["btc_open_interest"] == 100000.0
        assert d["eth_open_interest"] == 50000.0
        assert "timestamp" in d

    def test_to_dict_with_data_quality(self):
        dq = DataQuality()
        dq.mark_success("fear_greed")
        m = self._make_metrics(data_quality=dq)
        d = m.to_dict()
        assert "data_quality" in d
        assert d["data_quality"]["success_rate"] == 100.0

    def test_to_dict_without_data_quality(self):
        m = self._make_metrics()
        d = m.to_dict()
        assert "data_quality" not in d

    def test_is_reliable_no_quality(self):
        m = self._make_metrics()
        assert m.is_reliable is True  # Assume reliable if no tracking

    def test_is_reliable_with_quality_true(self):
        dq = DataQuality()
        dq.mark_success("fear_greed")
        dq.mark_success("long_short_ratio")
        dq.mark_success("ticker_btc")
        m = self._make_metrics(data_quality=dq)
        assert m.is_reliable is True

    def test_is_reliable_with_quality_false(self):
        dq = DataQuality()
        dq.mark_failure("fear_greed", "timeout")
        m = self._make_metrics(data_quality=dq)
        assert m.is_reliable is False

    def test_timestamp_serialized_as_isoformat(self):
        ts = datetime(2025, 6, 15, 10, 30, 0)
        m = self._make_metrics(timestamp=ts)
        d = m.to_dict()
        assert d["timestamp"] == ts.isoformat()


# ---------------------------------------------------------------------------
# MarketDataFetcher initialization tests
# ---------------------------------------------------------------------------

class TestMarketDataFetcherInit:
    """Tests for MarketDataFetcher initialization and session management."""

    def test_initial_session_is_none(self):
        f = MarketDataFetcher()
        assert f._session is None

    @pytest.mark.asyncio
    async def test_ensure_session_creates_session(self):
        f = MarketDataFetcher()
        with patch("src.data.market_data.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = MagicMock()
            await f._ensure_session()
            mock_cls.assert_called_once()
            assert f._session is not None

    @pytest.mark.asyncio
    async def test_ensure_session_reuses_open_session(self):
        f = MarketDataFetcher()
        mock_session = MagicMock()
        mock_session.closed = False
        f._session = mock_session
        with patch("src.data.market_data.aiohttp.ClientSession") as mock_cls:
            await f._ensure_session()
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_session_replaces_closed_session(self):
        f = MarketDataFetcher()
        closed_session = MagicMock()
        closed_session.closed = True
        f._session = closed_session
        with patch("src.data.market_data.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = MagicMock()
            await f._ensure_session()
            mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_closes_open_session(self):
        f = MarketDataFetcher()
        mock_session = AsyncMock()
        mock_session.closed = False
        f._session = mock_session
        await f.close()
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_does_not_fail_when_no_session(self):
        f = MarketDataFetcher()
        await f.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_does_not_close_already_closed(self):
        f = MarketDataFetcher()
        mock_session = AsyncMock()
        mock_session.closed = True
        f._session = mock_session
        await f.close()
        mock_session.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_manager_enter_exit(self):
        f = MarketDataFetcher()
        with patch.object(f, "_ensure_session", new_callable=AsyncMock) as mock_ensure:
            with patch.object(f, "close", new_callable=AsyncMock) as mock_close:
                async with f as fetcher:
                    assert fetcher is f
                    mock_ensure.assert_called_once()
                mock_close.assert_called_once()


# ---------------------------------------------------------------------------
# HTTP _get method tests
# ---------------------------------------------------------------------------

class TestGet:
    """Tests for the _get HTTP request method."""

    @pytest.mark.asyncio
    async def test_get_success_returns_json(self, fetcher):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": "ok"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        fetcher._session.get = MagicMock(return_value=mock_response)
        with patch.object(fetcher, "_ensure_session", new_callable=AsyncMock):
            result = await fetcher._get("https://api.test.com/data")
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_get_429_raises_rate_limit(self, fetcher):
        mock_response = AsyncMock()
        mock_response.status = 429
        mock_response.request_info = MagicMock()
        mock_response.history = ()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        fetcher._session.get = MagicMock(return_value=mock_response)
        with patch.object(fetcher, "_ensure_session", new_callable=AsyncMock):
            with pytest.raises(aiohttp.ClientResponseError):
                await fetcher._get("https://api.test.com/data")

    @pytest.mark.asyncio
    async def test_get_non_200_returns_empty(self, fetcher):
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        fetcher._session.get = MagicMock(return_value=mock_response)
        with patch.object(fetcher, "_ensure_session", new_callable=AsyncMock):
            result = await fetcher._get("https://api.test.com/data")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_client_error_raises(self, fetcher):
        fetcher._session.get = MagicMock(side_effect=aiohttp.ClientError("conn refused"))
        with patch.object(fetcher, "_ensure_session", new_callable=AsyncMock):
            with pytest.raises(aiohttp.ClientError):
                await fetcher._get("https://api.test.com/data")

    @pytest.mark.asyncio
    async def test_get_timeout_raises(self, fetcher):
        fetcher._session.get = MagicMock(side_effect=asyncio.TimeoutError())
        with patch.object(fetcher, "_ensure_session", new_callable=AsyncMock):
            with pytest.raises(asyncio.TimeoutError):
                await fetcher._get("https://api.test.com/data")

    @pytest.mark.asyncio
    async def test_get_generic_exception_returns_empty(self, fetcher):
        fetcher._session.get = MagicMock(side_effect=ValueError("unexpected"))
        with patch.object(fetcher, "_ensure_session", new_callable=AsyncMock):
            result = await fetcher._get("https://api.test.com/data")
        assert result == {}


# ---------------------------------------------------------------------------
# Fear & Greed Index tests
# ---------------------------------------------------------------------------

class TestFearGreedIndex:
    """Tests for get_fear_greed_index."""

    @pytest.mark.asyncio
    async def test_returns_value_and_classification(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "data": [{"value": "25", "value_classification": "Extreme Fear"}]
            }
            with patch("src.data.sources.breakers.alternative_me_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                value, classification = await fetcher.get_fear_greed_index()
        assert value == 25
        assert classification == "Extreme Fear"

    @pytest.mark.asyncio
    async def test_empty_data_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"data": []}
            with patch("src.data.sources.breakers.alternative_me_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                value, classification = await fetcher.get_fear_greed_index()
        assert value == 50
        assert classification == "Neutral"

    @pytest.mark.asyncio
    async def test_no_data_key_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.alternative_me_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                value, classification = await fetcher.get_fear_greed_index()
        assert value == 50
        assert classification == "Neutral"

    @pytest.mark.asyncio
    async def test_circuit_breaker_error_returns_default(self, fetcher):
        with patch("src.data.sources.breakers.alternative_me_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("alt_me", CircuitState.OPEN))
            value, classification = await fetcher.get_fear_greed_index()
        assert value == 50
        assert classification == "Neutral"

    @pytest.mark.asyncio
    async def test_exception_returns_default(self, fetcher):
        with patch("src.data.sources.breakers.alternative_me_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=Exception("unknown"))
            value, classification = await fetcher.get_fear_greed_index()
        assert value == 50
        assert classification == "Neutral"

    @pytest.mark.asyncio
    async def test_missing_value_defaults_to_50(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"data": [{"value_classification": "Neutral"}]}
            with patch("src.data.sources.breakers.alternative_me_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                value, classification = await fetcher.get_fear_greed_index()
        assert value == 50


# ---------------------------------------------------------------------------
# Long/Short Ratio tests
# ---------------------------------------------------------------------------

class TestLongShortRatio:
    """Tests for get_long_short_ratio and get_top_trader_long_short_ratio."""

    @pytest.mark.asyncio
    async def test_returns_ratio(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [{"longShortRatio": "1.35"}]
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_long_short_ratio("BTCUSDT")
        assert result == 1.35

    @pytest.mark.asyncio
    async def test_empty_response_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_long_short_ratio()
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_circuit_breaker_error_returns_default(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("binance", CircuitState.OPEN))
            result = await fetcher.get_long_short_ratio()
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_top_trader_returns_ratio(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [{"longShortRatio": "2.1"}]
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_top_trader_long_short_ratio("BTCUSDT")
        assert result == 2.1

    @pytest.mark.asyncio
    async def test_top_trader_empty_returns_default(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_top_trader_long_short_ratio()
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_top_trader_exception_returns_default(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=Exception("unexpected"))
            result = await fetcher.get_top_trader_long_short_ratio()
        assert result == 1.0


# ---------------------------------------------------------------------------
# Funding Rate tests
# ---------------------------------------------------------------------------

class TestFundingRate:
    """Tests for funding rate methods (Binance and predicted)."""

    @pytest.mark.asyncio
    async def test_binance_funding_rate_success(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"lastFundingRate": "0.0002"}
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_funding_rate_binance("BTCUSDT")
        assert result == 0.0002

    @pytest.mark.asyncio
    async def test_binance_funding_rate_empty_returns_zero(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_funding_rate_binance()
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_binance_funding_rate_circuit_breaker(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("b", CircuitState.OPEN))
            result = await fetcher.get_funding_rate_binance()
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_predicted_funding_rate_success(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"interestRate": "0.0001"}
            result = await fetcher.get_predicted_funding_rate("BTCUSDT")
        assert result == 0.0001

    @pytest.mark.asyncio
    async def test_predicted_funding_rate_empty(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            result = await fetcher.get_predicted_funding_rate()
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_predicted_funding_rate_exception(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("fail")
            result = await fetcher.get_predicted_funding_rate()
        assert result == 0.0


# ---------------------------------------------------------------------------
# 24h Ticker tests
# ---------------------------------------------------------------------------

class TestTicker24h:
    """Tests for get_24h_ticker."""

    @pytest.mark.asyncio
    async def test_returns_parsed_ticker(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "lastPrice": "95000.50",
                "priceChangePercent": "2.35",
                "highPrice": "96000",
                "lowPrice": "93000",
                "volume": "50000",
                "quoteVolume": "4750000000",
            }
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_24h_ticker("BTCUSDT")

        assert result["symbol"] == "BTCUSDT"
        assert result["price"] == 95000.50
        assert result["price_change_percent"] == 2.35
        assert result["high_24h"] == 96000.0
        assert result["low_24h"] == 93000.0

    @pytest.mark.asyncio
    async def test_empty_response_returns_defaults(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_24h_ticker("ETHUSDT")

        assert result["symbol"] == "ETHUSDT"
        assert result["price"] == 0
        assert result["price_change_percent"] == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_defaults(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("b", CircuitState.OPEN))
            result = await fetcher.get_24h_ticker()
        assert result["price"] == 0
        assert result["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# Open Interest tests
# ---------------------------------------------------------------------------

class TestOpenInterest:
    """Tests for get_open_interest and get_open_interest_history."""

    @pytest.mark.asyncio
    async def test_open_interest_success(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"openInterest": "12345.67"}
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_open_interest("BTCUSDT")
        assert result == 12345.67

    @pytest.mark.asyncio
    async def test_open_interest_empty_returns_zero(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_open_interest()
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_open_interest_circuit_breaker(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("b", CircuitState.OPEN))
            result = await fetcher.get_open_interest()
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_open_interest_history_success(self, fetcher):
        history_data = [
            {"timestamp": 1700000000000, "sumOpenInterest": "10000"},
            {"timestamp": 1700003600000, "sumOpenInterest": "10500"},
        ]
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = history_data
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_open_interest_history("BTCUSDT", "1h", 24)
        assert result == history_data

    @pytest.mark.asyncio
    async def test_open_interest_history_empty(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_open_interest_history()
        assert result == []

    @pytest.mark.asyncio
    async def test_open_interest_history_circuit_breaker(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("b", CircuitState.OPEN))
            result = await fetcher.get_open_interest_history()
        assert result == []


# ---------------------------------------------------------------------------
# Liquidations tests
# ---------------------------------------------------------------------------

class TestLiquidations:
    """Tests for get_recent_liquidations."""

    @pytest.mark.asyncio
    async def test_returns_liquidation_data(self, fetcher):
        liq_data = [{"symbol": "BTCUSDT", "side": "BUY", "qty": "1.5"}]
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = liq_data
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_recent_liquidations("BTCUSDT", 50)
        assert result == liq_data

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_recent_liquidations()
        assert result == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_empty(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("b", CircuitState.OPEN))
            result = await fetcher.get_recent_liquidations()
        assert result == []


# ---------------------------------------------------------------------------
# Order Book Depth tests
# ---------------------------------------------------------------------------

class TestOrderBookDepth:
    """Tests for get_order_book_depth with imbalance calculations."""

    @pytest.mark.asyncio
    async def test_balanced_order_book(self, fetcher):
        data = {
            "bids": [["95000", "1.0"], ["94999", "1.0"], ["94998", "1.0"]] * 4,
            "asks": [["95001", "1.0"], ["95002", "1.0"], ["95003", "1.0"]] * 4,
        }
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = data
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_order_book_depth("BTCUSDT")
        assert "midPrice" in result
        assert "spreadBps" in result
        assert "imbalanceTop10" in result
        assert "interpretation" in result
        assert abs(result["imbalanceTop10"]) < 0.1
        assert "Balanced" in result["interpretation"]

    @pytest.mark.asyncio
    async def test_strong_bid_imbalance(self, fetcher):
        data = {
            "bids": [["95000", "10.0"]] * 10,
            "asks": [["95001", "1.0"]] * 10,
        }
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = data
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_order_book_depth("BTCUSDT")
        assert result["imbalanceTop10"] > 0.3
        assert "bid-side" in result["interpretation"].lower() or "bullish" in result["interpretation"].lower()

    @pytest.mark.asyncio
    async def test_strong_ask_imbalance(self, fetcher):
        data = {
            "bids": [["95000", "1.0"]] * 10,
            "asks": [["95001", "10.0"]] * 10,
        }
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = data
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_order_book_depth("BTCUSDT")
        assert result["imbalanceTop10"] < -0.3
        assert "ask-side" in result["interpretation"].lower() or "bearish" in result["interpretation"].lower()

    @pytest.mark.asyncio
    async def test_moderate_bid_imbalance(self, fetcher):
        # imbalance between 0.1 and 0.3
        data = {
            "bids": [["95000", "3.0"]] * 10,
            "asks": [["95001", "2.0"]] * 10,
        }
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = data
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_order_book_depth("BTCUSDT")
        assert 0.1 < result["imbalanceTop10"] <= 0.3
        assert "Moderate bid" in result["interpretation"]

    @pytest.mark.asyncio
    async def test_moderate_ask_imbalance(self, fetcher):
        data = {
            "bids": [["95000", "2.0"]] * 10,
            "asks": [["95001", "3.0"]] * 10,
        }
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = data
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_order_book_depth("BTCUSDT")
        assert -0.3 <= result["imbalanceTop10"] < -0.1
        assert "Moderate ask" in result["interpretation"]

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_order_book_depth()
        assert result == {}

    @pytest.mark.asyncio
    async def test_missing_bids_returns_empty(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"bids": [], "asks": [["95001", "1.0"]]}
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_order_book_depth()
        assert result == {}

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_empty(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("b", CircuitState.OPEN))
            result = await fetcher.get_order_book_depth()
        assert result == {}


# ---------------------------------------------------------------------------
# VWAP Calculation tests (static method)
# ---------------------------------------------------------------------------

class TestCalculateVwap:
    """Tests for the static VWAP calculation."""

    def test_vwap_with_valid_data(self, sample_klines):
        vwap = MarketDataFetcher.calculate_vwap(sample_klines)
        # typical_price = (110 + 90 + 105) / 3 = 101.667 for each candle
        expected_tp = (110 + 90 + 105) / 3
        assert abs(vwap - expected_tp) < 0.01

    def test_vwap_empty_klines(self):
        assert MarketDataFetcher.calculate_vwap([]) == 0.0

    def test_vwap_zero_volume(self):
        klines = [
            [0, "100", "110", "90", "105", "0", 0, "0", 0, "0", "0", "0"]
        ]
        assert MarketDataFetcher.calculate_vwap(klines) == 0.0

    def test_vwap_malformed_data_skips_bad_entries(self):
        klines = [
            [0, "100", "110", "90", "105", "1000", 0, "0", 0, "500", "0", "0"],
            [0, "bad"],  # malformed - should be skipped
            [0, "100", "115", "95", "110", "2000", 0, "0", 0, "800", "0", "0"],
        ]
        vwap = MarketDataFetcher.calculate_vwap(klines)
        assert vwap > 0

    def test_vwap_varying_volumes(self):
        klines = [
            [0, "100", "120", "80", "100", "1000", 0, "0", 0, "500", "0", "0"],
            [0, "100", "200", "100", "150", "3000", 0, "0", 0, "1500", "0", "0"],
        ]
        vwap = MarketDataFetcher.calculate_vwap(klines)
        tp1 = (120 + 80 + 100) / 3
        tp2 = (200 + 100 + 150) / 3
        expected = (tp1 * 1000 + tp2 * 3000) / (1000 + 3000)
        assert abs(vwap - expected) < 0.01


# ---------------------------------------------------------------------------
# Supertrend Indicator tests (static method)
# ---------------------------------------------------------------------------

class TestCalculateSupertrend:
    """Tests for the static Supertrend calculation."""

    def test_supertrend_with_enough_data(self, sample_klines):
        result = MarketDataFetcher.calculate_supertrend(sample_klines, atr_period=10, multiplier=3.0)
        assert result["direction"] in ("bullish", "bearish")
        assert result["value"] > 0
        assert result["atr"] > 0

    def test_supertrend_empty_klines(self):
        result = MarketDataFetcher.calculate_supertrend([])
        assert result == {"direction": "neutral", "value": 0.0, "atr": 0.0}

    def test_supertrend_insufficient_data(self):
        klines = [
            [0, "100", "110", "90", "105", "1000", 0, "0", 0, "500", "0", "0"]
            for _ in range(5)
        ]
        result = MarketDataFetcher.calculate_supertrend(klines, atr_period=10)
        assert result["direction"] == "neutral"

    def test_supertrend_exactly_minimum_data(self):
        # atr_period + 1 candles needed
        klines = [
            [0, "100", str(110 + i), str(90 - i), str(100 + i * 2), "1000", 0, "0", 0, "500", "0", "0"]
            for i in range(12)
        ]
        result = MarketDataFetcher.calculate_supertrend(klines, atr_period=10, multiplier=3.0)
        assert result["direction"] in ("bullish", "bearish")

    def test_supertrend_malformed_entries_skipped(self):
        klines = [
            [0, "100", "110", "90", "105", "1000", 0, "0", 0, "500", "0", "0"]
            for _ in range(20)
        ]
        klines.insert(5, [0, "bad"])  # malformed entry
        result = MarketDataFetcher.calculate_supertrend(klines, atr_period=10)
        assert result["direction"] in ("bullish", "bearish", "neutral")

    def test_supertrend_bullish_on_rising_prices(self):
        klines = []
        for i in range(24):
            base = 90000 + i * 1000  # strongly rising
            klines.append([
                0, str(base), str(base + 200), str(base - 200), str(base + 100),
                "1000", 0, "0", 0, "500", "0", "0",
            ])
        result = MarketDataFetcher.calculate_supertrend(klines, atr_period=10, multiplier=2.0)
        assert result["direction"] == "bullish"

    def test_supertrend_bearish_on_falling_prices(self):
        klines = []
        for i in range(24):
            base = 100000 - i * 1000  # strongly falling
            klines.append([
                0, str(base), str(base + 200), str(base - 200), str(base - 100),
                "1000", 0, "0", 0, "500", "0", "0",
            ])
        result = MarketDataFetcher.calculate_supertrend(klines, atr_period=10, multiplier=2.0)
        assert result["direction"] == "bearish"


# ---------------------------------------------------------------------------
# Spot Volume Analysis tests (static method)
# ---------------------------------------------------------------------------

class TestSpotVolumeAnalysis:
    """Tests for the static spot volume analysis."""

    def test_volume_analysis_normal(self, sample_klines):
        result = MarketDataFetcher.get_spot_volume_analysis(sample_klines)
        assert result["buy_ratio"] == 0.5  # 500/1000 for each candle
        assert result["sell_ratio"] == 0.5
        assert result["total_volume"] == 24000.0
        assert result["buy_volume"] == 12000.0
        assert result["sell_volume"] == 12000.0

    def test_volume_analysis_empty(self):
        result = MarketDataFetcher.get_spot_volume_analysis([])
        assert result["buy_ratio"] == 0.5
        assert result["sell_ratio"] == 0.5
        assert result["total_volume"] == 0.0

    def test_volume_analysis_high_buy_ratio(self):
        klines = [
            [0, "100", "110", "90", "105", "1000", 0, "0", 0, "800", "0", "0"]
            for _ in range(10)
        ]
        result = MarketDataFetcher.get_spot_volume_analysis(klines)
        assert result["buy_ratio"] == 0.8
        assert result["sell_ratio"] == pytest.approx(0.2)

    def test_volume_analysis_zero_volume(self):
        klines = [
            [0, "100", "110", "90", "105", "0", 0, "0", 0, "0", "0", "0"]
        ]
        result = MarketDataFetcher.get_spot_volume_analysis(klines)
        assert result["buy_ratio"] == 0.5
        assert result["total_volume"] == 0.0

    def test_volume_analysis_malformed_skipped(self):
        klines = [
            [0, "100", "110", "90", "105", "1000", 0, "0", 0, "600", "0", "0"],
            [0, "bad"],  # skipped
        ]
        result = MarketDataFetcher.get_spot_volume_analysis(klines)
        assert result["total_volume"] == 1000.0
        assert result["buy_volume"] == 600.0


# ---------------------------------------------------------------------------
# Price Volatility tests
# ---------------------------------------------------------------------------

class TestPriceVolatility:
    """Tests for get_price_volatility."""

    @pytest.mark.asyncio
    async def test_volatility_calculated(self, fetcher, sample_klines):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = sample_klines
            result = await fetcher.get_price_volatility("BTCUSDT", 24)
        # (110 - 90) / 90 * 100 = 22.22% for each candle
        expected = (110 - 90) / 90 * 100
        assert abs(result - expected) < 0.01

    @pytest.mark.asyncio
    async def test_volatility_empty_returns_default(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            result = await fetcher.get_price_volatility()
        assert result == 3.0

    @pytest.mark.asyncio
    async def test_volatility_exception_returns_default(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("fail")
            result = await fetcher.get_price_volatility()
        assert result == 3.0


# ---------------------------------------------------------------------------
# Trend Direction tests
# ---------------------------------------------------------------------------

class TestTrendDirection:
    """Tests for get_trend_direction (SMA-based)."""

    @pytest.mark.asyncio
    async def test_bullish_trend(self, fetcher, bullish_klines):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = bullish_klines
            result = await fetcher.get_trend_direction("BTCUSDT")
        assert result == "bullish"

    @pytest.mark.asyncio
    async def test_bearish_trend(self, fetcher, bearish_klines):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = bearish_klines
            result = await fetcher.get_trend_direction("BTCUSDT")
        assert result == "bearish"

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_neutral(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [[0, "0", "0", "0", str(100), "0"]] * 10  # < 24
            result = await fetcher.get_trend_direction()
        assert result == "neutral"

    @pytest.mark.asyncio
    async def test_empty_data_returns_neutral(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            result = await fetcher.get_trend_direction()
        assert result == "neutral"

    @pytest.mark.asyncio
    async def test_exception_returns_neutral(self, fetcher):
        with patch.object(fetcher, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("fail")
            result = await fetcher.get_trend_direction()
        assert result == "neutral"


# ---------------------------------------------------------------------------
# News Sentiment (GDELT) tests
# ---------------------------------------------------------------------------

class TestNewsSentiment:
    """Tests for get_news_sentiment."""

    @pytest.mark.asyncio
    async def test_returns_sentiment_data(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "tonechart": [
                    {"tone": "2.5"},
                    {"tone": "-1.0"},
                    {"tone": "1.5"},
                ]
            }
            with patch("src.data.sources.breakers.gdelt_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_news_sentiment()

        assert abs(result["average_tone"] - 1.0) < 0.01
        assert result["article_count"] == 3

    @pytest.mark.asyncio
    async def test_empty_tonechart_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"tonechart": []}
            with patch("src.data.sources.breakers.gdelt_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_news_sentiment()
        assert result["average_tone"] == 0.0
        assert result["article_count"] == 0

    @pytest.mark.asyncio
    async def test_no_tonechart_key_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.gdelt_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_news_sentiment()
        assert result["average_tone"] == 0.0

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_default(self, fetcher):
        with patch("src.data.sources.breakers.gdelt_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("gdelt", CircuitState.OPEN))
            result = await fetcher.get_news_sentiment()
        assert result["average_tone"] == 0.0


# ---------------------------------------------------------------------------
# Binance Klines tests
# ---------------------------------------------------------------------------

class TestBinanceKlines:
    """Tests for get_binance_klines."""

    @pytest.mark.asyncio
    async def test_returns_kline_list(self, fetcher, sample_klines):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = sample_klines
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_binance_klines("BTCUSDT", "1h", 24)
        assert len(result) == 24

    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_list(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_binance_klines()
        assert result == []

    @pytest.mark.asyncio
    async def test_non_list_data_returns_empty_list(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"error": "invalid"}
            with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_binance_klines()
        assert result == []

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_empty_list(self, fetcher):
        with patch("src.data.sources.breakers.binance_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("b", CircuitState.OPEN))
            result = await fetcher.get_binance_klines()
        assert result == []


# ---------------------------------------------------------------------------
# OIWAP Calculation tests
# ---------------------------------------------------------------------------

class TestOIWAP:
    """Tests for calculate_oiwap."""

    @pytest.mark.asyncio
    async def test_oiwap_with_provided_klines(self, fetcher, sample_klines):
        oi_history = [
            {"timestamp": 1700000000000 + i * 3600000, "sumOpenInterest": str(10000 + i * 100)}
            for i in range(24)
        ]
        with patch.object(fetcher, "get_open_interest_history", new_callable=AsyncMock) as mock_oi:
            mock_oi.return_value = oi_history
            result = await fetcher.calculate_oiwap("BTCUSDT", klines=sample_klines)
        assert result > 0

    @pytest.mark.asyncio
    async def test_oiwap_fetches_klines_when_not_provided(self, fetcher, sample_klines):
        oi_history = [
            {"timestamp": 1700000000000 + i * 3600000, "sumOpenInterest": str(10000 + i * 100)}
            for i in range(24)
        ]
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = sample_klines
            with patch.object(fetcher, "get_open_interest_history", new_callable=AsyncMock) as mock_oi:
                mock_oi.return_value = oi_history
                result = await fetcher.calculate_oiwap("BTCUSDT")
        mock_k.assert_called_once()
        assert result > 0

    @pytest.mark.asyncio
    async def test_oiwap_no_klines_returns_zero(self, fetcher):
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = []
            result = await fetcher.calculate_oiwap("BTCUSDT")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_oiwap_insufficient_oi_history(self, fetcher, sample_klines):
        with patch.object(fetcher, "get_open_interest_history", new_callable=AsyncMock) as mock_oi:
            mock_oi.return_value = [{"timestamp": 0, "sumOpenInterest": "1000"}]
            result = await fetcher.calculate_oiwap("BTCUSDT", klines=sample_klines)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_oiwap_exception_returns_zero(self, fetcher):
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_k:
            mock_k.side_effect = Exception("fail")
            result = await fetcher.calculate_oiwap("BTCUSDT")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_oiwap_no_oi_changes_returns_zero(self, fetcher, sample_klines):
        # All OI values the same -> no changes -> total_weight = 0
        oi_history = [
            {"timestamp": 1700000000000 + i * 3600000, "sumOpenInterest": "10000"}
            for i in range(24)
        ]
        with patch.object(fetcher, "get_open_interest_history", new_callable=AsyncMock) as mock_oi:
            mock_oi.return_value = oi_history
            result = await fetcher.calculate_oiwap("BTCUSDT", klines=sample_klines)
        assert result == 0.0


# ---------------------------------------------------------------------------
# Deribit Options tests
# ---------------------------------------------------------------------------

class TestDeribitOptions:
    """Tests for Deribit options methods."""

    @pytest.mark.asyncio
    async def test_options_oi_success(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "result": [
                    {"open_interest": 100},
                    {"open_interest": 200},
                    {"open_interest": 300},
                ]
            }
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_options_oi_deribit("BTC")
        assert result["total_oi"] == 600
        assert result["num_instruments"] == 3
        assert result["currency"] == "BTC"

    @pytest.mark.asyncio
    async def test_options_oi_empty_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_options_oi_deribit("BTC")
        assert result["total_oi"] == 0.0

    @pytest.mark.asyncio
    async def test_options_oi_circuit_breaker(self, fetcher):
        with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("d", CircuitState.OPEN))
            result = await fetcher.get_options_oi_deribit()
        assert result["total_oi"] == 0.0

    @pytest.mark.asyncio
    async def test_put_call_ratio_success(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "result": [
                    {"instrument_name": "BTC-100000-C", "open_interest": 500},
                    {"instrument_name": "BTC-100000-P", "open_interest": 300},
                    {"instrument_name": "BTC-95000-C", "open_interest": 200},
                    {"instrument_name": "BTC-95000-P", "open_interest": 100},
                ]
            }
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_put_call_ratio("BTC")
        assert result["total_calls"] == 700
        assert result["total_puts"] == 400
        assert abs(result["ratio"] - 400 / 700) < 0.001

    @pytest.mark.asyncio
    async def test_put_call_ratio_no_calls_returns_zero(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "result": [
                    {"instrument_name": "BTC-100000-P", "open_interest": 300},
                ]
            }
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_put_call_ratio("BTC")
        assert result["ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_put_call_ratio_empty(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_put_call_ratio("BTC")
        assert result == {"ratio": 0.0, "total_puts": 0.0, "total_calls": 0.0}

    @pytest.mark.asyncio
    async def test_max_pain_success(self, fetcher):
        future_ts = (datetime.now() + timedelta(days=7)).timestamp() * 1000
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "result": [
                    {"strike": 90000, "option_type": "call", "expiration_timestamp": future_ts, "open_interest": 100},
                    {"strike": 90000, "option_type": "put", "expiration_timestamp": future_ts, "open_interest": 50},
                    {"strike": 95000, "option_type": "call", "expiration_timestamp": future_ts, "open_interest": 200},
                    {"strike": 95000, "option_type": "put", "expiration_timestamp": future_ts, "open_interest": 150},
                    {"strike": 100000, "option_type": "call", "expiration_timestamp": future_ts, "open_interest": 50},
                    {"strike": 100000, "option_type": "put", "expiration_timestamp": future_ts, "open_interest": 300},
                ]
            }
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_max_pain("BTC")
        assert result["max_pain_price"] > 0
        assert result["nearest_expiry"] != ""

    @pytest.mark.asyncio
    async def test_max_pain_no_instruments(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"result": []}
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_max_pain("BTC")
        assert result["max_pain_price"] == 0.0

    @pytest.mark.asyncio
    async def test_max_pain_no_result_key(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_max_pain("BTC")
        assert result["max_pain_price"] == 0.0

    @pytest.mark.asyncio
    async def test_max_pain_all_expired(self, fetcher):
        past_ts = (datetime.now() - timedelta(days=7)).timestamp() * 1000
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "result": [
                    {"strike": 90000, "option_type": "call", "expiration_timestamp": past_ts, "open_interest": 100},
                ]
            }
            with patch("src.data.sources.breakers.deribit_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_max_pain("BTC")
        assert result["max_pain_price"] == 0.0


# ---------------------------------------------------------------------------
# CoinGecko tests
# ---------------------------------------------------------------------------

class TestCoinGecko:
    """Tests for get_coingecko_market."""

    @pytest.mark.asyncio
    async def test_returns_global_market_data(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "data": {
                    "total_market_cap": {"usd": 3e12},
                    "market_cap_percentage": {"btc": 55.0},
                    "active_cryptocurrencies": 10000,
                    "market_cap_change_percentage_24h_usd": 1.5,
                }
            }
            with patch("src.data.sources.breakers.coingecko_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_coingecko_market()
        assert result["total_market_cap_usd"] == 3e12
        assert result["btc_dominance_pct"] == 55.0
        assert result["active_cryptocurrencies"] == 10000

    @pytest.mark.asyncio
    async def test_empty_returns_defaults(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.coingecko_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_coingecko_market()
        assert result["total_market_cap_usd"] == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_defaults(self, fetcher):
        with patch("src.data.sources.breakers.coingecko_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("cg", CircuitState.OPEN))
            result = await fetcher.get_coingecko_market()
        assert result["total_market_cap_usd"] == 0


# ---------------------------------------------------------------------------
# Stablecoin Flows tests
# ---------------------------------------------------------------------------

class TestStablecoinFlows:
    """Tests for get_stablecoin_flows."""

    @pytest.mark.asyncio
    async def test_returns_usdt_mcap(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "peggedAssets": [
                    {
                        "symbol": "USDT",
                        "chainCirculating": {
                            "Ethereum": {"current": {"peggedUSD": 50e9}},
                            "Tron": {"current": {"peggedUSD": 60e9}},
                        },
                    }
                ]
            }
            with patch("src.data.sources.breakers.defillama_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_stablecoin_flows()
        assert result["usdt_market_cap"] == 110e9
        assert result["symbol"] == "USDT"

    @pytest.mark.asyncio
    async def test_fallback_to_circulating(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "peggedAssets": [
                    {
                        "symbol": "USDT",
                        "chainCirculating": {},
                        "circulating": {"peggedUSD": 100e9},
                    }
                ]
            }
            with patch("src.data.sources.breakers.defillama_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_stablecoin_flows()
        assert result["usdt_market_cap"] == 100e9

    @pytest.mark.asyncio
    async def test_empty_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.defillama_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_stablecoin_flows()
        assert result["usdt_market_cap"] == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_default(self, fetcher):
        with patch("src.data.sources.breakers.defillama_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("dl", CircuitState.OPEN))
            result = await fetcher.get_stablecoin_flows()
        assert result["usdt_market_cap"] == 0


# ---------------------------------------------------------------------------
# BTC Hashrate tests
# ---------------------------------------------------------------------------

class TestBTCHashrate:
    """Tests for get_btc_hashrate."""

    @pytest.mark.asyncio
    async def test_returns_hashrate_and_difficulty(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"hash_rate": 600000000, "difficulty": 80000000000000}
            with patch("src.data.sources.breakers.blockchain_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_btc_hashrate()
        assert result["hashrate_ths"] == 600000000
        assert result["difficulty"] == 80000000000000

    @pytest.mark.asyncio
    async def test_empty_returns_defaults(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            with patch("src.data.sources.breakers.blockchain_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_btc_hashrate()
        assert result["hashrate_ths"] == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_defaults(self, fetcher):
        with patch("src.data.sources.breakers.blockchain_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("bc", CircuitState.OPEN))
            result = await fetcher.get_btc_hashrate()
        assert result["hashrate_ths"] == 0


# ---------------------------------------------------------------------------
# Bitget Funding Rate tests
# ---------------------------------------------------------------------------

class TestBitgetFundingRate:
    """Tests for get_bitget_funding_rate."""

    @pytest.mark.asyncio
    async def test_returns_funding_rate(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "code": "00000",
                "data": [{"fundingRate": "0.0003"}],
            }
            with patch("src.data.sources.breakers.bitget_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_bitget_funding_rate("BTCUSDT")
        assert result["funding_rate"] == 0.0003
        assert result["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_non_success_code_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"code": "40001", "data": []}
            with patch("src.data.sources.breakers.bitget_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_bitget_funding_rate()
        assert result["funding_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_empty_data_returns_default(self, fetcher):
        with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"code": "00000", "data": []}
            with patch("src.data.sources.breakers.bitget_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                result = await fetcher.get_bitget_funding_rate()
        assert result["funding_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_default(self, fetcher):
        with patch("src.data.sources.breakers.bitget_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("bg", CircuitState.OPEN))
            result = await fetcher.get_bitget_funding_rate()
        assert result["funding_rate"] == 0.0


# ---------------------------------------------------------------------------
# FRED Macro Data tests
# ---------------------------------------------------------------------------

class TestFredSeries:
    """Tests for get_fred_series."""

    @pytest.mark.asyncio
    async def test_returns_value_with_api_key(self, fetcher):
        with patch.dict("os.environ", {"FRED_API_KEY": "test-key-123"}):
            with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "observations": [{"value": "103.5", "date": "2025-01-10"}]
                }
                with patch("src.data.sources.breakers.fred_breaker") as mock_breaker:
                    mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                    result = await fetcher.get_fred_series("DTWEXBGS")
        assert result["value"] == 103.5
        assert result["date"] == "2025-01-10"
        assert result["series_id"] == "DTWEXBGS"

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_default(self, fetcher):
        with patch.dict("os.environ", {}, clear=True):
            # Also need to handle FRED_API_KEY not being in environ
            import os
            original = os.environ.get("FRED_API_KEY")
            if "FRED_API_KEY" in os.environ:
                del os.environ["FRED_API_KEY"]
            try:
                result = await fetcher.get_fred_series("DFF")
            finally:
                if original is not None:
                    os.environ["FRED_API_KEY"] = original
        assert result["value"] == 0.0
        assert result["series_id"] == "DFF"

    @pytest.mark.asyncio
    async def test_dot_value_returns_zero(self, fetcher):
        with patch.dict("os.environ", {"FRED_API_KEY": "test-key"}):
            with patch.object(fetcher, "_get_with_retry", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "observations": [{"value": ".", "date": "2025-01-10"}]
                }
                with patch("src.data.sources.breakers.fred_breaker") as mock_breaker:
                    mock_breaker.call = AsyncMock(side_effect=_passthrough_call)
                    result = await fetcher.get_fred_series("DFF")
        assert result["value"] == 0.0

    @pytest.mark.asyncio
    async def test_circuit_breaker_returns_default(self, fetcher):
        with patch.dict("os.environ", {"FRED_API_KEY": "test-key"}):
            with patch("src.data.sources.breakers.fred_breaker") as mock_breaker:
                mock_breaker.call = AsyncMock(side_effect=CircuitBreakerError("fred", CircuitState.OPEN))
                result = await fetcher.get_fred_series("DTWEXBGS")
        assert result["value"] == 0.0


# ---------------------------------------------------------------------------
# CME Gap Detection tests
# ---------------------------------------------------------------------------

class TestCMEGap:
    """Tests for get_cme_gap."""

    @pytest.mark.asyncio
    async def test_detects_upward_gap(self, fetcher):
        # Create klines where the last Friday candle has a lower close than current
        klines = []
        now = datetime(2025, 1, 17, 12, 0, 0)  # Friday
        for i in range(42):
            ts = now - timedelta(hours=(42 - i) * 4)
            ts_ms = int(ts.timestamp() * 1000)
            close = "95000" if ts.weekday() == 4 and ts.hour >= 20 else "96500"
            klines.append([ts_ms, "95000", "96500", "94500", close, "1000", 0, "0", 0, "500", "0", "0"])

        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = klines
            result = await fetcher.get_cme_gap("BTCUSDT")
        assert "gap_pct" in result
        assert "friday_close" in result
        assert "current_price" in result

    @pytest.mark.asyncio
    async def test_no_klines_returns_default(self, fetcher):
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = []
            result = await fetcher.get_cme_gap()
        assert result["gap_pct"] == 0.0
        assert result["gap_direction"] == "none"

    @pytest.mark.asyncio
    async def test_no_friday_close_returns_default(self, fetcher):
        # All klines are on a Monday
        klines = []
        for i in range(42):
            ts = datetime(2025, 1, 13, 0, 0, 0) + timedelta(hours=i * 4)  # Monday
            ts_ms = int(ts.timestamp() * 1000)
            klines.append([ts_ms, "95000", "96000", "94000", "95500", "1000", 0, "0", 0, "500", "0", "0"])
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_k:
            mock_k.return_value = klines
            result = await fetcher.get_cme_gap("BTCUSDT")
        assert result["gap_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_exception_returns_default(self, fetcher):
        with patch.object(fetcher, "get_binance_klines", new_callable=AsyncMock) as mock_k:
            mock_k.side_effect = Exception("fail")
            result = await fetcher.get_cme_gap()
        assert result["gap_pct"] == 0.0


# ---------------------------------------------------------------------------
# fetch_all_metrics tests
# ---------------------------------------------------------------------------

class TestFetchAllMetrics:
    """Tests for the aggregate fetch_all_metrics method."""

    @pytest.mark.asyncio
    async def test_all_sources_succeed(self, fetcher):
        with (
            patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg,
            patch.object(fetcher, "get_long_short_ratio", new_callable=AsyncMock) as mock_ls,
            patch.object(fetcher, "get_funding_rate_binance", new_callable=AsyncMock) as mock_fr,
            patch.object(fetcher, "get_24h_ticker", new_callable=AsyncMock) as mock_ticker,
            patch.object(fetcher, "get_open_interest", new_callable=AsyncMock) as mock_oi,
        ):
            mock_fg.return_value = (75, "Greed")
            mock_ls.return_value = 1.5
            mock_fr.return_value = 0.0002
            mock_ticker.return_value = {"price": 95000, "price_change_percent": 2.5}
            mock_oi.return_value = 50000.0

            metrics = await fetcher.fetch_all_metrics(require_reliable=False)

        assert isinstance(metrics, MarketMetrics)
        assert metrics.fear_greed_index == 75
        assert metrics.fear_greed_classification == "Greed"
        assert metrics.long_short_ratio == 1.5
        assert metrics.btc_price == 95000
        assert metrics.data_quality is not None

    @pytest.mark.asyncio
    async def test_critical_failure_raises_when_required(self, fetcher):
        with (
            patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg,
            patch.object(fetcher, "get_long_short_ratio", new_callable=AsyncMock) as mock_ls,
            patch.object(fetcher, "get_funding_rate_binance", new_callable=AsyncMock) as mock_fr,
            patch.object(fetcher, "get_24h_ticker", new_callable=AsyncMock) as mock_ticker,
            patch.object(fetcher, "get_open_interest", new_callable=AsyncMock) as mock_oi,
        ):
            mock_fg.return_value = (75, "Greed")
            mock_ls.return_value = 1.5
            mock_fr.return_value = 0.0
            # ticker_btc returns price=0, which triggers failure
            mock_ticker.return_value = {"price": 0, "price_change_percent": 0}
            mock_oi.return_value = 0.0

            with pytest.raises(DataFetchError):
                await fetcher.fetch_all_metrics(require_reliable=True)

    @pytest.mark.asyncio
    async def test_non_critical_failure_does_not_raise(self, fetcher):
        with (
            patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg,
            patch.object(fetcher, "get_long_short_ratio", new_callable=AsyncMock) as mock_ls,
            patch.object(fetcher, "get_funding_rate_binance", new_callable=AsyncMock) as mock_fr,
            patch.object(fetcher, "get_24h_ticker", new_callable=AsyncMock) as mock_ticker,
            patch.object(fetcher, "get_open_interest", new_callable=AsyncMock) as mock_oi,
        ):
            mock_fg.return_value = (75, "Greed")
            mock_ls.return_value = 1.5
            mock_fr.return_value = 0.0002
            mock_ticker.return_value = {"price": 95000, "price_change_percent": 2.5}
            mock_oi.return_value = 50000.0

            # This should not raise even with require_reliable=True
            metrics = await fetcher.fetch_all_metrics(require_reliable=True)
        assert isinstance(metrics, MarketMetrics)

    @pytest.mark.asyncio
    async def test_exception_result_uses_fallback_values(self, fetcher):
        with (
            patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg,
            patch.object(fetcher, "get_long_short_ratio", new_callable=AsyncMock) as mock_ls,
            patch.object(fetcher, "get_funding_rate_binance", new_callable=AsyncMock) as mock_fr,
            patch.object(fetcher, "get_24h_ticker", new_callable=AsyncMock) as mock_ticker,
            patch.object(fetcher, "get_open_interest", new_callable=AsyncMock) as mock_oi,
        ):
            mock_fg.side_effect = Exception("fail")
            mock_ls.side_effect = Exception("fail")
            mock_fr.return_value = 0.0002
            mock_ticker.return_value = {"price": 95000, "price_change_percent": 2.5}
            mock_oi.return_value = 50000.0

            metrics = await fetcher.fetch_all_metrics(require_reliable=False)
        # Failed sources should use fallback values
        assert metrics.fear_greed_index == 50
        assert metrics.long_short_ratio == 1.0

    @pytest.mark.asyncio
    async def test_none_result_uses_fallback(self, fetcher):
        with (
            patch.object(fetcher, "get_fear_greed_index", new_callable=AsyncMock) as mock_fg,
            patch.object(fetcher, "get_long_short_ratio", new_callable=AsyncMock) as mock_ls,
            patch.object(fetcher, "get_funding_rate_binance", new_callable=AsyncMock) as mock_fr,
            patch.object(fetcher, "get_24h_ticker", new_callable=AsyncMock) as mock_ticker,
            patch.object(fetcher, "get_open_interest", new_callable=AsyncMock) as mock_oi,
        ):
            mock_fg.return_value = None
            mock_ls.return_value = None
            mock_fr.return_value = None
            mock_ticker.return_value = None
            mock_oi.return_value = None

            metrics = await fetcher.fetch_all_metrics(require_reliable=False)
        assert metrics.fear_greed_index == 50
        assert metrics.long_short_ratio == 1.0
        assert metrics.funding_rate_btc == 0.0


# ---------------------------------------------------------------------------
# API Endpoints constants tests
# ---------------------------------------------------------------------------

class TestAPIEndpoints:
    """Tests for API URL constants."""

    def test_fear_greed_url(self):
        assert "alternative.me" in MarketDataFetcher.FEAR_GREED_URL

    def test_binance_futures_url(self):
        assert "binance.com" in MarketDataFetcher.BINANCE_FUTURES_URL

    def test_deribit_url(self):
        assert "deribit.com" in MarketDataFetcher.DERIBIT_URL

    def test_coingecko_url(self):
        assert "coingecko.com" in MarketDataFetcher.COINGECKO_URL

    def test_defillama_url(self):
        assert "llama.fi" in MarketDataFetcher.DEFILLAMA_URL

    def test_blockchain_url(self):
        assert "blockchain.info" in MarketDataFetcher.BLOCKCHAIN_URL

    def test_bitget_url(self):
        assert "bitget.com" in MarketDataFetcher.BITGET_URL

    def test_fred_url(self):
        assert "stlouisfed.org" in MarketDataFetcher.FRED_URL


class TestToBinanceSymbol:
    """Test _to_binance_symbol normalizes all exchange formats to Binance."""

    def test_bitget_passthrough(self):
        from src.data.market_data import _to_binance_symbol
        assert _to_binance_symbol("BTCUSDT") == "BTCUSDT"
        assert _to_binance_symbol("ETHUSDT") == "ETHUSDT"
        assert _to_binance_symbol("SOLUSDT") == "SOLUSDT"

    def test_hyperliquid_bare_coin(self):
        from src.data.market_data import _to_binance_symbol
        assert _to_binance_symbol("BTC") == "BTCUSDT"
        assert _to_binance_symbol("ETH") == "ETHUSDT"
        assert _to_binance_symbol("SOL") == "SOLUSDT"
        assert _to_binance_symbol("DOGE") == "DOGEUSDT"
        assert _to_binance_symbol("XRP") == "XRPUSDT"

    def test_bingx_dash_format(self):
        from src.data.market_data import _to_binance_symbol
        assert _to_binance_symbol("BTC-USDT") == "BTCUSDT"
        assert _to_binance_symbol("ETH-USDT") == "ETHUSDT"
        assert _to_binance_symbol("SOL-USDT") == "SOLUSDT"

    def test_usdc_pair(self):
        from src.data.market_data import _to_binance_symbol
        assert _to_binance_symbol("BTCUSDC") == "BTCUSDT"

    def test_case_insensitive(self):
        from src.data.market_data import _to_binance_symbol
        assert _to_binance_symbol("btcusdt") == "BTCUSDT"
        assert _to_binance_symbol("btc") == "BTCUSDT"
        assert _to_binance_symbol("Eth") == "ETHUSDT"

    def test_meme_coins_with_prefix(self):
        from src.data.market_data import _to_binance_symbol
        assert _to_binance_symbol("1000PEPEUSDT") == "1000PEPEUSDT"
        assert _to_binance_symbol("1000PEPE") == "1000PEPEUSDT"
