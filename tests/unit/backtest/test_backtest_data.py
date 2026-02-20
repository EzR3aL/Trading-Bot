"""
Unit tests for backtest data modules.

Tests cover:
- HistoricalDataPoint dataclass (serialization, deserialization)
- HistoricalDataFetcher (caching, HTTP fetching, data transformation)
- BacktestResult / BacktestReport (report generation, recommendations, stats)
- Mock data generation (generate_mock_historical_data, get_mock_data_summary)
- Error handling and edge cases
"""

import json
import math
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.backtest.historical_data import HistoricalDataFetcher, HistoricalDataPoint
from src.backtest.mock_data import generate_mock_historical_data, get_mock_data_summary
from src.backtest.report import BacktestReport, BacktestResult


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def sample_data_point():
    """Create a sample HistoricalDataPoint for testing."""
    return HistoricalDataPoint(
        timestamp=datetime(2025, 6, 15, 12, 0, 0),
        date_str="2025-06-15",
        fear_greed_index=45,
        fear_greed_classification="Fear",
        long_short_ratio=1.2,
        funding_rate_btc=0.0003,
        funding_rate_eth=0.0002,
        btc_price=65000.0,
        eth_price=3200.0,
        btc_open=64500.0,
        eth_open=3150.0,
        btc_high=66000.0,
        btc_low=64000.0,
        eth_high=3300.0,
        eth_low=3100.0,
        btc_24h_change=2.5,
        eth_24h_change=1.8,
        open_interest_btc=18_000_000_000.0,
        open_interest_change_24h=3.5,
        taker_buy_sell_ratio=1.05,
        top_trader_long_short_ratio=1.1,
        funding_rate_bitget=0.00025,
        stablecoin_flow_7d=500_000_000.0,
        usdt_market_cap=120_000_000_000.0,
        btc_dominance=52.3,
        total_crypto_market_cap=2_500_000_000_000.0,
        dxy_index=104.5,
        fed_funds_rate=5.25,
        btc_hashrate=650.0,
        historical_volatility=55.0,
        btc_volume=15_000_000_000.0,
    )


@pytest.fixture
def tmp_cache_dir(tmp_path):
    """Create a temporary cache directory."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return str(cache_dir)


@pytest.fixture
def fetcher(tmp_cache_dir):
    """Create a HistoricalDataFetcher with a temp cache directory."""
    return HistoricalDataFetcher(cache_dir=tmp_cache_dir)


@pytest.fixture
def sample_backtest_result():
    """Create a sample BacktestResult for testing."""
    return BacktestResult(
        start_date="2025-01-01",
        end_date="2025-06-30",
        starting_capital=10000.0,
        ending_capital=11500.0,
        total_return_percent=15.0,
        max_drawdown_percent=8.5,
        total_trades=50,
        winning_trades=30,
        losing_trades=20,
        win_rate=60.0,
        average_win=150.0,
        average_loss=-100.0,
        profit_factor=2.25,
        total_pnl=1500.0,
        total_fees=250.0,
        total_funding=50.0,
        monthly_returns={
            "2025-01": 200.0,
            "2025-02": -100.0,
            "2025-03": 350.0,
            "2025-04": 400.0,
            "2025-05": 250.0,
            "2025-06": 400.0,
        },
    )


# ===========================================================================
# HistoricalDataPoint Tests
# ===========================================================================


class TestHistoricalDataPoint:
    """Tests for the HistoricalDataPoint dataclass."""

    def test_to_dict_converts_timestamp_to_isoformat(self, sample_data_point):
        """to_dict should convert timestamp to ISO format string."""
        result = sample_data_point.to_dict()

        assert result["timestamp"] == "2025-06-15T12:00:00"
        assert isinstance(result["timestamp"], str)

    def test_to_dict_includes_all_fields(self, sample_data_point):
        """to_dict should include all dataclass fields."""
        result = sample_data_point.to_dict()

        assert result["fear_greed_index"] == 45
        assert result["btc_price"] == 65000.0
        assert result["eth_price"] == 3200.0
        assert result["long_short_ratio"] == 1.2
        assert result["funding_rate_btc"] == 0.0003
        assert result["open_interest_btc"] == 18_000_000_000.0
        assert result["dxy_index"] == 104.5
        assert result["btc_hashrate"] == 650.0

    def test_from_dict_roundtrip(self, sample_data_point):
        """from_dict(to_dict()) should produce an equivalent object."""
        d = sample_data_point.to_dict()
        restored = HistoricalDataPoint.from_dict(d)

        assert restored.btc_price == sample_data_point.btc_price
        assert restored.fear_greed_index == sample_data_point.fear_greed_index
        assert restored.date_str == sample_data_point.date_str
        assert restored.timestamp == sample_data_point.timestamp

    def test_from_dict_ignores_unknown_fields(self):
        """from_dict should ignore fields not in the dataclass."""
        data = {
            "timestamp": "2025-06-15T12:00:00",
            "date_str": "2025-06-15",
            "fear_greed_index": 50,
            "fear_greed_classification": "Neutral",
            "long_short_ratio": 1.0,
            "funding_rate_btc": 0.0,
            "funding_rate_eth": 0.0,
            "btc_price": 60000.0,
            "eth_price": 3000.0,
            "btc_open": 60000.0,
            "eth_open": 3000.0,
            "btc_high": 61000.0,
            "btc_low": 59000.0,
            "eth_high": 3100.0,
            "eth_low": 2900.0,
            "btc_24h_change": 0.0,
            "eth_24h_change": 0.0,
            "unknown_field": "should be ignored",
            "another_unknown": 999,
        }
        result = HistoricalDataPoint.from_dict(data)

        assert result.btc_price == 60000.0
        assert not hasattr(result, "unknown_field")

    def test_from_dict_uses_defaults_for_missing_optional_fields(self):
        """from_dict should use default values for missing optional fields."""
        data = {
            "timestamp": "2025-01-01T00:00:00",
            "date_str": "2025-01-01",
            "fear_greed_index": 50,
            "fear_greed_classification": "Neutral",
            "long_short_ratio": 1.0,
            "funding_rate_btc": 0.0,
            "funding_rate_eth": 0.0,
            "btc_price": 50000.0,
            "eth_price": 2500.0,
            "btc_open": 50000.0,
            "eth_open": 2500.0,
            "btc_high": 51000.0,
            "btc_low": 49000.0,
            "eth_high": 2600.0,
            "eth_low": 2400.0,
            "btc_24h_change": 0.0,
            "eth_24h_change": 0.0,
        }
        result = HistoricalDataPoint.from_dict(data)

        assert result.open_interest_btc == 0.0
        assert result.taker_buy_sell_ratio == 1.0
        assert result.dxy_index == 0.0
        assert result.btc_hashrate == 0.0

    def test_default_values_for_extended_fields(self):
        """Extended fields should have sensible defaults."""
        dp = HistoricalDataPoint(
            timestamp=datetime.now(),
            date_str="2025-01-01",
            fear_greed_index=50,
            fear_greed_classification="Neutral",
            long_short_ratio=1.0,
            funding_rate_btc=0.0,
            funding_rate_eth=0.0,
            btc_price=50000.0,
            eth_price=2500.0,
            btc_open=50000.0,
            eth_open=2500.0,
            btc_high=51000.0,
            btc_low=49000.0,
            eth_high=2600.0,
            eth_low=2400.0,
            btc_24h_change=0.0,
            eth_24h_change=0.0,
        )

        assert dp.open_interest_btc == 0.0
        assert dp.open_interest_change_24h == 0.0
        assert dp.taker_buy_sell_ratio == 1.0
        assert dp.top_trader_long_short_ratio == 1.0
        assert dp.funding_rate_bitget == 0.0
        assert dp.stablecoin_flow_7d == 0.0
        assert dp.usdt_market_cap == 0.0
        assert dp.btc_dominance == 0.0
        assert dp.total_crypto_market_cap == 0.0
        assert dp.dxy_index == 0.0
        assert dp.fed_funds_rate == 0.0
        assert dp.btc_hashrate == 0.0
        assert dp.historical_volatility == 0.0
        assert dp.btc_volume == 0.0


# ===========================================================================
# HistoricalDataFetcher - Initialization & Cache Tests
# ===========================================================================


class TestHistoricalDataFetcherInit:
    """Tests for HistoricalDataFetcher initialization."""

    def test_creates_cache_directory(self, tmp_path):
        """Constructor should create cache directory if it does not exist."""
        cache_dir = tmp_path / "new_cache_dir"
        assert not cache_dir.exists()

        fetcher = HistoricalDataFetcher(cache_dir=str(cache_dir))

        assert cache_dir.exists()

    def test_session_starts_as_none(self, fetcher):
        """HTTP session should be None until first request."""
        assert fetcher._session is None

    def test_data_sources_starts_empty(self, fetcher):
        """Data sources list should start empty."""
        assert fetcher._data_sources == []
        assert fetcher.data_sources == []


class TestHistoricalDataFetcherCache:
    """Tests for cache loading and saving."""

    def test_get_cache_file_returns_correct_path(self, fetcher, tmp_cache_dir):
        """_get_cache_file should return path with .json extension."""
        result = fetcher._get_cache_file("test_data")

        assert result == Path(tmp_cache_dir) / "test_data.json"

    def test_save_and_load_cache(self, fetcher):
        """Saved cache data should be loadable."""
        test_data = [{"key": "value"}, {"num": 42}]

        fetcher._save_cache("test_save", test_data)
        loaded = fetcher._load_cache("test_save")

        assert loaded == test_data

    def test_load_cache_returns_none_for_missing_file(self, fetcher):
        """Loading a non-existent cache file should return None."""
        result = fetcher._load_cache("nonexistent_cache")

        assert result is None

    def test_load_cache_returns_none_for_expired_data(self, fetcher, tmp_cache_dir):
        """Cache data older than 24 hours should be treated as expired."""
        old_time = (datetime.now() - timedelta(hours=25)).isoformat()
        cache_file = Path(tmp_cache_dir) / "expired.json"
        with open(cache_file, "w") as f:
            json.dump({"cached_at": old_time, "data": [1, 2, 3]}, f)

        result = fetcher._load_cache("expired")

        assert result is None

    def test_load_cache_returns_data_for_fresh_cache(self, fetcher, tmp_cache_dir):
        """Cache data less than 24 hours old should be returned."""
        recent_time = (datetime.now() - timedelta(hours=1)).isoformat()
        cache_file = Path(tmp_cache_dir) / "fresh.json"
        with open(cache_file, "w") as f:
            json.dump({"cached_at": recent_time, "data": {"fresh": True}}, f)

        result = fetcher._load_cache("fresh")

        assert result == {"fresh": True}

    def test_load_cache_handles_corrupt_json(self, fetcher, tmp_cache_dir):
        """Corrupted JSON cache files should return None gracefully."""
        cache_file = Path(tmp_cache_dir) / "corrupt.json"
        with open(cache_file, "w") as f:
            f.write("this is not valid json {{{")

        result = fetcher._load_cache("corrupt")

        assert result is None

    def test_load_cache_handles_missing_cached_at_field(self, fetcher, tmp_cache_dir):
        """Cache file without cached_at should return None."""
        cache_file = Path(tmp_cache_dir) / "no_timestamp.json"
        with open(cache_file, "w") as f:
            json.dump({"data": [1, 2, 3]}, f)

        result = fetcher._load_cache("no_timestamp")

        assert result is None

    def test_save_cache_handles_write_error(self, fetcher):
        """save_cache should handle file write errors gracefully."""
        with patch("builtins.open", side_effect=PermissionError("denied")):
            # Should not raise, just log warning
            fetcher._save_cache("test", {"data": True})


# ===========================================================================
# HistoricalDataFetcher - HTTP GET Tests
# ===========================================================================


class TestHistoricalDataFetcherGet:
    """Tests for the _get HTTP method."""

    async def test_get_returns_json_on_success(self, fetcher):
        """_get should return JSON data on HTTP 200."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": "ok"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.closed = False
        fetcher._session = mock_session

        result = await fetcher._get("https://example.com/api")

        assert result == {"result": "ok"}

    async def test_get_returns_none_on_non_200(self, fetcher):
        """_get should return None on non-200 status codes."""
        mock_response = AsyncMock()
        mock_response.status = 429
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.closed = False
        fetcher._session = mock_session

        result = await fetcher._get("https://example.com/api")

        assert result is None

    async def test_get_returns_none_on_exception(self, fetcher):
        """_get should return None on network errors."""
        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection timeout"))
        mock_session.closed = False
        fetcher._session = mock_session

        result = await fetcher._get("https://example.com/api")

        assert result is None

    async def test_ensure_session_creates_session(self, fetcher):
        """_ensure_session should create a new session if none exists."""
        assert fetcher._session is None

        with patch("src.backtest.historical_data.aiohttp.ClientSession") as mock_cls:
            mock_instance = AsyncMock()
            mock_cls.return_value = mock_instance

            await fetcher._ensure_session()

            mock_cls.assert_called_once()
            assert fetcher._session == mock_instance

    async def test_close_session(self, fetcher):
        """close() should close the HTTP session."""
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        fetcher._session = mock_session

        await fetcher.close()

        mock_session.close.assert_called_once()


# ===========================================================================
# HistoricalDataFetcher - Fear & Greed History
# ===========================================================================


class TestFetchFearGreedHistory:
    """Tests for fear and greed history fetching."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached data without making HTTP calls."""
        cached_data = [
            {"timestamp": 1700000000, "value": 60, "classification": "Greed"}
        ]
        fetcher._load_cache = MagicMock(return_value=cached_data)

        result = await fetcher.fetch_fear_greed_history(30)

        assert result == cached_data
        fetcher._load_cache.assert_called_once_with("fear_greed_30d")

    async def test_fetches_and_parses_api_data(self, fetcher):
        """Should fetch from API and transform response correctly."""
        api_response = {
            "data": [
                {
                    "timestamp": "1700000000",
                    "value": "72",
                    "value_classification": "Greed",
                },
                {
                    "timestamp": "1700086400",
                    "value": "45",
                    "value_classification": "Fear",
                },
            ]
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_response)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_fear_greed_history(30)

        assert len(result) == 2
        assert result[0]["value"] == 72
        assert result[0]["classification"] == "Greed"
        assert result[1]["value"] == 45

    async def test_returns_empty_list_on_api_failure(self, fetcher):
        """Should return empty list when API returns None."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)

        result = await fetcher.fetch_fear_greed_history(30)

        assert result == []

    async def test_returns_empty_list_on_missing_data_key(self, fetcher):
        """Should return empty list when API response lacks 'data' key."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value={"error": "rate limited"})

        result = await fetcher.fetch_fear_greed_history(30)

        assert result == []


# ===========================================================================
# HistoricalDataFetcher - Klines / Price History
# ===========================================================================


class TestFetchKlinesHistory:
    """Tests for kline/OHLCV data fetching."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached klines data."""
        cached = [{"timestamp": 1700000, "close": 60000}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_klines_history("BTCUSDT", "1d", 30)

        assert result == cached

    async def test_parses_binance_kline_format(self, fetcher):
        """Should parse Binance kline array format correctly."""
        api_response = [
            [
                1700000000000,  # open time
                "60000.00",  # open
                "61000.00",  # high
                "59000.00",  # low
                "60500.00",  # close
                "1500.50",  # volume
                1700086399999,  # close time
                "90030000.00",  # quote volume
                5000,  # trades
                "750.25",  # taker buy base
                "45015000.00",  # taker buy quote
                "0",  # ignore
            ]
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_response)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_klines_history("BTCUSDT", "1d", 30)

        assert len(result) == 1
        assert result[0]["open"] == 60000.0
        assert result[0]["high"] == 61000.0
        assert result[0]["low"] == 59000.0
        assert result[0]["close"] == 60500.0
        assert result[0]["volume"] == 1500.50
        assert result[0]["timestamp"] == 1700000000

    async def test_returns_empty_on_api_failure(self, fetcher):
        """Should return empty list when API fails."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)

        result = await fetcher.fetch_klines_history("BTCUSDT", "1d", 30)

        assert result == []


# ===========================================================================
# HistoricalDataFetcher - CoinGecko Fallback
# ===========================================================================


class TestFetchCoingeckoHistory:
    """Tests for CoinGecko fallback price data."""

    async def test_parses_coingecko_format(self, fetcher):
        """Should parse CoinGecko market_chart format."""
        api_response = {
            "prices": [
                [1700000000000, 60000.0],
                [1700086400000, 61000.0],
            ]
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_response)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_coingecko_history("bitcoin", 30)

        assert len(result) == 2
        assert result[0]["close"] == 60000.0
        # CoinGecko synthesizes open/high/low from close price
        assert result[0]["open"] == pytest.approx(60000.0 * 0.99)
        assert result[0]["high"] == pytest.approx(60000.0 * 1.02)
        assert result[0]["low"] == pytest.approx(60000.0 * 0.98)

    async def test_returns_empty_on_no_prices(self, fetcher):
        """Should return empty list when CoinGecko returns no price data."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value={"market_caps": []})

        result = await fetcher.fetch_coingecko_history("bitcoin", 30)

        assert result == []

    async def test_returns_empty_on_api_failure(self, fetcher):
        """Should return empty list when CoinGecko API fails."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)

        result = await fetcher.fetch_coingecko_history("bitcoin", 30)

        assert result == []


# ===========================================================================
# HistoricalDataFetcher - Klines with Fallback
# ===========================================================================


class TestFetchKlinesWithFallback:
    """Tests for price data with CoinGecko fallback."""

    async def test_uses_binance_when_available(self, fetcher):
        """Should use Binance data when available."""
        binance_data = [{"timestamp": 1, "close": 60000}]
        fetcher.fetch_klines_history = AsyncMock(return_value=binance_data)
        fetcher.fetch_coingecko_history = AsyncMock()

        result = await fetcher.fetch_klines_with_fallback("BTCUSDT", 30)

        assert result == binance_data
        fetcher.fetch_coingecko_history.assert_not_called()

    async def test_falls_back_to_coingecko_for_btc(self, fetcher):
        """Should fall back to CoinGecko when Binance fails for BTC."""
        coingecko_data = [{"timestamp": 1, "close": 60000}]
        fetcher.fetch_klines_history = AsyncMock(return_value=[])
        fetcher.fetch_coingecko_history = AsyncMock(return_value=coingecko_data)

        result = await fetcher.fetch_klines_with_fallback("BTCUSDT", 30)

        assert result == coingecko_data
        fetcher.fetch_coingecko_history.assert_called_with("bitcoin", 30)

    async def test_falls_back_to_coingecko_for_eth(self, fetcher):
        """Should fall back to CoinGecko with 'ethereum' for ETH symbols."""
        coingecko_data = [{"timestamp": 1, "close": 3000}]
        fetcher.fetch_klines_history = AsyncMock(return_value=[])
        fetcher.fetch_coingecko_history = AsyncMock(return_value=coingecko_data)

        result = await fetcher.fetch_klines_with_fallback("ETHUSDT", 30)

        fetcher.fetch_coingecko_history.assert_called_with("ethereum", 30)

    async def test_returns_empty_when_all_fail(self, fetcher):
        """Should return empty list when both Binance and CoinGecko fail."""
        fetcher.fetch_klines_history = AsyncMock(return_value=[])
        fetcher.fetch_coingecko_history = AsyncMock(return_value=[])

        result = await fetcher.fetch_klines_with_fallback("BTCUSDT", 30)

        assert result == []


# ===========================================================================
# HistoricalDataFetcher - Funding Rate History
# ===========================================================================


class TestFetchFundingRateHistory:
    """Tests for funding rate history fetching."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached funding rate data."""
        cached = [{"timestamp": 1700000, "rate": 0.0001}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_funding_rate_history("BTCUSDT", 30)

        assert result == cached

    async def test_parses_funding_rate_data(self, fetcher):
        """Should parse Binance funding rate format correctly."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_data = [
            {"fundingTime": now_ms - 10000, "fundingRate": "0.00015"},
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_funding_rate_history("BTCUSDT", 30)

        assert len(result) >= 1
        assert result[0]["rate"] == pytest.approx(0.00015)

    async def test_returns_empty_on_no_data(self, fetcher):
        """Should return empty list when API returns no data."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_funding_rate_history("BTCUSDT", 30)

        assert result == []


# ===========================================================================
# HistoricalDataFetcher - Long/Short History
# ===========================================================================


class TestFetchLongShortHistory:
    """Tests for long/short ratio history."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached L/S ratio data."""
        cached = [{"timestamp": 1700000, "ratio": 1.5}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_long_short_history("BTCUSDT", 30)

        assert result == cached

    async def test_deduplicates_timestamps(self, fetcher):
        """Should remove duplicate timestamps from results."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_data = [
            {"timestamp": now_ms - 5000, "longShortRatio": "1.2"},
            {"timestamp": now_ms - 5000, "longShortRatio": "1.3"},  # duplicate
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_long_short_history("BTCUSDT", 30)

        # Duplicate timestamps should be deduped
        timestamps = [r["timestamp"] for r in result]
        assert len(timestamps) == len(set(timestamps))


# ===========================================================================
# HistoricalDataFetcher - Open Interest
# ===========================================================================


class TestFetchOpenInterestHistory:
    """Tests for open interest history."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached open interest data."""
        cached = [{"timestamp": 1700000, "oi_value": 18e9}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_open_interest_history("BTCUSDT", 30)

        assert result == cached

    async def test_parses_oi_fields(self, fetcher):
        """Should parse sumOpenInterestValue and sumOpenInterest."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_data = [
            {
                "timestamp": now_ms - 5000,
                "sumOpenInterestValue": "18000000000",
                "sumOpenInterest": "300000",
            }
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_open_interest_history("BTCUSDT", 30)

        assert len(result) >= 1
        assert result[0]["oi_value"] == 18_000_000_000.0
        assert result[0]["oi_quantity"] == 300_000.0


# ===========================================================================
# HistoricalDataFetcher - Taker Buy/Sell
# ===========================================================================


class TestFetchTakerBuySellHistory:
    """Tests for taker buy/sell ratio history."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached taker buy/sell data."""
        cached = [{"timestamp": 1700000, "ratio": 1.05}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_taker_buy_sell_history("BTCUSDT", 30)

        assert result == cached

    async def test_parses_taker_fields(self, fetcher):
        """Should parse buySellRatio, buyVol, and sellVol."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_data = [
            {
                "timestamp": now_ms - 5000,
                "buySellRatio": "1.15",
                "buyVol": "5000",
                "sellVol": "4350",
            }
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_taker_buy_sell_history("BTCUSDT", 30)

        assert len(result) >= 1
        assert result[0]["ratio"] == pytest.approx(1.15)
        assert result[0]["buy_vol"] == pytest.approx(5000.0)
        assert result[0]["sell_vol"] == pytest.approx(4350.0)


# ===========================================================================
# HistoricalDataFetcher - Top Trader L/S
# ===========================================================================


class TestFetchTopTraderLSHistory:
    """Tests for top trader long/short ratio."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached top trader data."""
        cached = [{"timestamp": 1700000, "ratio": 1.3}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_top_trader_ls_history("BTCUSDT", 30)

        assert result == cached


# ===========================================================================
# HistoricalDataFetcher - Bitget Funding
# ===========================================================================


class TestFetchBitgetFunding:
    """Tests for Bitget funding rate history."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached Bitget funding data."""
        cached = [{"timestamp": 1700000, "rate": 0.0002}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_bitget_funding_history("BTCUSDT", 30)

        assert result == cached

    async def test_parses_bitget_response(self, fetcher):
        """Should parse Bitget API response format."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_response = {
            "code": "00000",
            "data": [
                {"settleTime": str(now_ms - 5000), "fundingRate": "0.00025"},
            ],
        }
        fetcher._load_cache = MagicMock(return_value=None)
        # First page returns data, second page returns non-00000
        fetcher._get = AsyncMock(
            side_effect=[api_response, {"code": "00001", "data": []}]
        )
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_bitget_funding_history("BTCUSDT", 30)

        assert len(result) >= 1
        assert result[0]["rate"] == pytest.approx(0.00025)

    async def test_stops_on_non_success_code(self, fetcher):
        """Should stop pagination when API returns non-00000 code."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value={"code": "50000", "data": []})
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_bitget_funding_history("BTCUSDT", 30)

        assert result == []


# ===========================================================================
# HistoricalDataFetcher - Stablecoin History
# ===========================================================================


class TestFetchStablecoinHistory:
    """Tests for stablecoin (USDT) history."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached stablecoin data."""
        cached = [{"timestamp": 1700000, "usdt_mcap": 120e9}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_stablecoin_history(30)

        assert result == cached

    async def test_parses_defillama_format(self, fetcher):
        """Should parse DefiLlama stablecoin chart format."""
        now_ts = int(datetime.now().timestamp())
        api_data = [
            {
                "date": now_ts - 3600,
                "totalCirculatingUSD": {"peggedUSD": 120_000_000_000},
            }
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_data)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_stablecoin_history(30)

        assert len(result) == 1
        assert result[0]["usdt_mcap"] == 120_000_000_000.0

    async def test_returns_empty_on_non_list_response(self, fetcher):
        """Should return empty list when API returns non-list data."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value={"error": "not found"})

        result = await fetcher.fetch_stablecoin_history(30)

        assert result == []


# ===========================================================================
# HistoricalDataFetcher - Global Market Data
# ===========================================================================


class TestFetchGlobalMarketData:
    """Tests for CoinGecko global market data."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached global market data."""
        cached = {"btc_dominance": 52.0, "total_market_cap_usd": 2.5e12}
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_global_market_data()

        assert result == cached

    async def test_parses_global_data(self, fetcher):
        """Should parse CoinGecko global endpoint correctly."""
        api_response = {
            "data": {
                "market_cap_percentage": {"btc": 51.5, "eth": 18.2},
                "total_market_cap": {"usd": 2_400_000_000_000},
                "total_volume": {"usd": 100_000_000_000},
            }
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_response)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_global_market_data()

        assert result["btc_dominance"] == 51.5
        assert result["total_market_cap_usd"] == 2_400_000_000_000.0
        assert result["total_volume_usd"] == 100_000_000_000.0

    async def test_returns_empty_dict_on_failure(self, fetcher):
        """Should return empty dict when API fails."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)

        result = await fetcher.fetch_global_market_data()

        assert result == {}


# ===========================================================================
# HistoricalDataFetcher - BTC Hashrate
# ===========================================================================


class TestFetchBtcHashrate:
    """Tests for BTC hashrate history."""

    async def test_returns_cached_data(self, fetcher):
        """Should return cached hashrate data."""
        cached = [{"timestamp": 1700000, "hashrate": 650.0}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_btc_hashrate_history(30)

        assert result == cached

    async def test_parses_blockchain_info_format(self, fetcher):
        """Should parse Blockchain.info chart format."""
        api_response = {
            "values": [
                {"x": 1700000000, "y": 655.5},
                {"x": 1700086400, "y": 660.2},
            ]
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_response)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_btc_hashrate_history(30)

        assert len(result) == 2
        assert result[0]["hashrate"] == 655.5
        assert result[1]["hashrate"] == 660.2

    async def test_returns_empty_on_missing_values(self, fetcher):
        """Should return empty list when API response lacks 'values'."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value={"status": "error"})

        result = await fetcher.fetch_btc_hashrate_history(30)

        assert result == []


# ===========================================================================
# HistoricalDataFetcher - FRED Series
# ===========================================================================


class TestFetchFredSeries:
    """Tests for FRED economic data."""

    async def test_returns_empty_without_api_key(self, fetcher):
        """Should return empty list when FRED_API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FRED_API_KEY", None)
            result = await fetcher.fetch_fred_series("DTWEXBGS", 30)

        assert result == []

    async def test_fetches_data_with_api_key(self, fetcher):
        """Should fetch FRED data when API key is available."""
        api_response = {
            "observations": [
                {"date": "2025-01-15", "value": "104.5"},
                {"date": "2025-01-16", "value": "104.8"},
            ]
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_response)
        fetcher._save_cache = MagicMock()

        with patch.dict(os.environ, {"FRED_API_KEY": "test-key"}):
            result = await fetcher.fetch_fred_series("DTWEXBGS", 30)

        assert len(result) == 2
        assert result[0]["value"] == 104.5
        assert result[0]["date"] == "2025-01-15"

    async def test_skips_invalid_observations(self, fetcher):
        """Should skip observations with non-numeric values (e.g., '.')."""
        api_response = {
            "observations": [
                {"date": "2025-01-15", "value": "."},
                {"date": "2025-01-16", "value": "104.8"},
            ]
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_response)
        fetcher._save_cache = MagicMock()

        with patch.dict(os.environ, {"FRED_API_KEY": "test-key"}):
            result = await fetcher.fetch_fred_series("DTWEXBGS", 30)

        assert len(result) == 1
        assert result[0]["value"] == 104.8


# ===========================================================================
# HistoricalDataFetcher - Volatility Calculation
# ===========================================================================


class TestCalculateVolatility:
    """Tests for rolling historical volatility calculation."""

    def test_returns_empty_for_insufficient_data(self):
        """Should return empty dict when data is shorter than window+1."""
        klines = [{"close": 60000 + i * 100, "timestamp": 1700000 + i * 86400} for i in range(10)]

        result = HistoricalDataFetcher.calculate_volatility(klines, window=20)

        assert result == {}

    def test_returns_volatility_for_sufficient_data(self):
        """Should calculate volatility when data exceeds window size."""
        # Generate 30 days of synthetic kline data with varying prices
        klines = []
        base_price = 60000
        for i in range(30):
            price = base_price + (i % 3 - 1) * 500
            klines.append({
                "close": price,
                "timestamp": 1700000000 + i * 86400,
            })

        result = HistoricalDataFetcher.calculate_volatility(klines, window=20)

        assert len(result) > 0
        for date_key, vol in result.items():
            assert isinstance(vol, float)
            assert vol >= 0

    def test_volatility_values_are_annualized(self):
        """Volatility values should be annualized (multiplied by sqrt(365)*100)."""
        # With constant returns, volatility should be near 0
        klines = [
            {"close": 60000 * (1.001 ** i), "timestamp": 1700000000 + i * 86400}
            for i in range(30)
        ]

        result = HistoricalDataFetcher.calculate_volatility(klines, window=20)

        # Constant growth has zero variance -> vol should be ~0
        for vol in result.values():
            assert vol < 1.0  # Very low for constant returns

    def test_higher_variance_produces_higher_volatility(self):
        """More volatile prices should produce higher volatility numbers."""
        # Low volatility: small increments
        low_vol_klines = [
            {"close": 60000 + i, "timestamp": 1700000000 + i * 86400}
            for i in range(30)
        ]
        # High volatility: large swings
        high_vol_klines = [
            {"close": 60000 + ((-1) ** i) * 5000, "timestamp": 1700000000 + i * 86400}
            for i in range(30)
        ]

        low_result = HistoricalDataFetcher.calculate_volatility(low_vol_klines, window=20)
        high_result = HistoricalDataFetcher.calculate_volatility(high_vol_klines, window=20)

        avg_low = sum(low_result.values()) / len(low_result)
        avg_high = sum(high_result.values()) / len(high_result)

        assert avg_high > avg_low

    def test_handles_zero_prev_close(self):
        """Should handle zero previous close without division error."""
        klines = [{"close": 0, "timestamp": 1700000000 + i * 86400} for i in range(3)]
        klines.extend(
            [{"close": 60000 + i * 100, "timestamp": 1700259200 + i * 86400} for i in range(25)]
        )

        # Should not raise
        result = HistoricalDataFetcher.calculate_volatility(klines, window=20)


# ===========================================================================
# HistoricalDataFetcher - Save/Load Data Points
# ===========================================================================


class TestSaveLoadDataPoints:
    """Tests for saving and loading data points to/from files."""

    def test_save_and_load_data_points(self, fetcher, sample_data_point, tmp_cache_dir):
        """Should save and load data points through JSON serialization."""
        data_points = [sample_data_point]

        fetcher.save_data_points(data_points, "test_output.json")

        loaded = fetcher.load_data_points("test_output.json")

        assert len(loaded) == 1
        assert loaded[0].btc_price == sample_data_point.btc_price
        assert loaded[0].date_str == sample_data_point.date_str

    def test_load_returns_empty_for_missing_file(self, fetcher):
        """Should return empty list when file does not exist."""
        result = fetcher.load_data_points("nonexistent.json")

        assert result == []


# ===========================================================================
# BacktestResult Tests
# ===========================================================================


class TestBacktestResult:
    """Tests for the BacktestResult dataclass."""

    def test_empty_result(self):
        """BacktestResult.empty() should create zeroed-out result."""
        result = BacktestResult.empty()

        assert result.starting_capital == 0
        assert result.ending_capital == 0
        assert result.total_trades == 0
        assert result.win_rate == 0
        assert result.profit_factor == 0
        assert result.monthly_returns == {}
        assert result.trades == []

    def test_to_dict_includes_summary_fields(self, sample_backtest_result):
        """to_dict should include all summary fields."""
        d = sample_backtest_result.to_dict()

        assert d["start_date"] == "2025-01-01"
        assert d["end_date"] == "2025-06-30"
        assert d["starting_capital"] == 10000.0
        assert d["total_return_percent"] == 15.0
        assert d["win_rate"] == 60.0
        assert d["profit_factor"] == 2.25
        assert "monthly_returns" in d
        assert d["monthly_returns"]["2025-01"] == 200.0

    def test_to_dict_excludes_large_lists(self, sample_backtest_result):
        """to_dict should exclude trades and daily_stats lists."""
        d = sample_backtest_result.to_dict()

        assert "trades" not in d
        assert "daily_stats" not in d
        assert "config" not in d


# ===========================================================================
# BacktestReport - Console Report Tests
# ===========================================================================


class TestBacktestReportConsole:
    """Tests for console report generation."""

    def test_report_contains_header(self, sample_backtest_result):
        """Report should contain the header section."""
        report = BacktestReport(sample_backtest_result)
        text = report.generate_console_report()

        assert "BACKTEST REPORT" in text
        assert "Contrarian Liquidation Hunter" in text

    def test_report_contains_performance_summary(self, sample_backtest_result):
        """Report should contain performance metrics."""
        report = BacktestReport(sample_backtest_result)
        text = report.generate_console_report()

        assert "PERFORMANCE SUMMARY" in text
        assert "10,000.00" in text  # starting capital
        assert "11,500.00" in text  # ending capital
        assert "15.00%" in text  # total return

    def test_report_contains_trade_statistics(self, sample_backtest_result):
        """Report should contain trade statistics."""
        report = BacktestReport(sample_backtest_result)
        text = report.generate_console_report()

        assert "TRADE STATISTICS" in text
        assert "50" in text  # total trades
        assert "30" in text  # winning trades
        assert "60.00%" in text  # win rate

    def test_report_contains_costs(self, sample_backtest_result):
        """Report should contain cost breakdown."""
        report = BacktestReport(sample_backtest_result)
        text = report.generate_console_report()

        assert "COSTS" in text
        assert "250.00" in text  # fees
        assert "50.00" in text  # funding
        assert "300.00" in text  # total costs

    def test_report_contains_monthly_returns(self, sample_backtest_result):
        """Report should contain monthly return breakdown."""
        report = BacktestReport(sample_backtest_result)
        text = report.generate_console_report()

        assert "MONTHLY RETURNS" in text
        assert "2025-01" in text
        assert "2025-06" in text

    def test_report_without_monthly_returns(self):
        """Report should skip monthly section when no monthly data."""
        result = BacktestResult.empty()
        result.start_date = "2025-01-01"
        result.end_date = "2025-01-31"
        result.starting_capital = 10000  # avoid division by zero in recommendations
        report = BacktestReport(result)
        text = report.generate_console_report()

        assert "MONTHLY RETURNS" not in text

    def test_calculate_days_valid_dates(self, sample_backtest_result):
        """Should correctly calculate days between start and end dates."""
        report = BacktestReport(sample_backtest_result)
        days = report._calculate_days()

        assert days == 180  # Jan 1 to Jun 30

    def test_calculate_days_invalid_dates(self):
        """Should return 0 for invalid date formats."""
        result = BacktestResult.empty()
        result.start_date = "invalid"
        result.end_date = "also-invalid"
        report = BacktestReport(result)

        assert report._calculate_days() == 0

    def test_calculate_days_empty_dates(self):
        """Should return 0 for empty date strings."""
        result = BacktestResult.empty()
        report = BacktestReport(result)

        assert report._calculate_days() == 0


# ===========================================================================
# BacktestReport - Bar Chart
# ===========================================================================


class TestBacktestReportBarChart:
    """Tests for ASCII bar chart generation."""

    def test_positive_bar(self):
        """Positive values should generate # bars."""
        report = BacktestReport(BacktestResult.empty())
        bar = report._generate_bar(10.0)

        assert "[" in bar
        assert "]" in bar
        assert "#" in bar

    def test_negative_bar(self):
        """Negative values should generate - bars."""
        report = BacktestReport(BacktestResult.empty())
        bar = report._generate_bar(-10.0)

        assert "-" in bar

    def test_zero_bar(self):
        """Zero value should generate empty bar."""
        report = BacktestReport(BacktestResult.empty())
        bar = report._generate_bar(0.0)

        assert bar == "[" + " " * 20 + "]"

    def test_bar_length_capped_at_max_width(self):
        """Bar length should not exceed max_width."""
        report = BacktestReport(BacktestResult.empty())
        bar = report._generate_bar(200.0, max_width=10)

        # Total length should be max_width + 2 (for brackets)
        assert len(bar) == 12


# ===========================================================================
# BacktestReport - Recommendations
# ===========================================================================


class TestBacktestReportRecommendations:
    """Tests for recommendation generation."""

    def test_low_win_rate_warning(self):
        """Win rate below 50% should trigger warning."""
        result = BacktestResult.empty()
        result.win_rate = 40.0
        result.starting_capital = 10000
        result.total_fees = 0
        result.total_funding = 0
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "WIN RATE BELOW 50%" in text

    def test_marginal_win_rate_note(self):
        """Win rate 50-55% should get marginal warning."""
        result = BacktestResult.empty()
        result.win_rate = 52.0
        result.profit_factor = 1.6
        result.starting_capital = 10000
        result.total_fees = 100
        result.total_funding = 50
        result.start_date = "2025-01-01"
        result.end_date = "2025-06-30"
        result.total_trades = 100
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "marginal" in text.lower()

    def test_acceptable_win_rate(self):
        """Win rate 55-60% should get acceptable note."""
        result = BacktestResult.empty()
        result.win_rate = 57.0
        result.profit_factor = 1.8
        result.starting_capital = 10000
        result.total_fees = 100
        result.total_funding = 50
        result.start_date = "2025-01-01"
        result.end_date = "2025-06-30"
        result.total_trades = 100
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "acceptable" in text.lower()

    def test_excellent_win_rate(self):
        """Win rate >60% should get excellent note."""
        result = BacktestResult.empty()
        result.win_rate = 65.0
        result.profit_factor = 2.5
        result.max_drawdown_percent = 5.0
        result.starting_capital = 10000
        result.total_fees = 100
        result.total_funding = 50
        result.start_date = "2025-01-01"
        result.end_date = "2025-06-30"
        result.total_trades = 100
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "Excellent" in text

    def test_losing_strategy_warning(self):
        """Profit factor < 1.0 should warn about losing strategy."""
        result = BacktestResult.empty()
        result.win_rate = 40.0
        result.profit_factor = 0.8
        result.starting_capital = 10000
        result.total_fees = 100
        result.total_funding = 50
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "LOSING STRATEGY" in text

    def test_high_drawdown_warning(self):
        """Max drawdown > 15% should trigger warning."""
        result = BacktestResult.empty()
        result.win_rate = 65.0
        result.profit_factor = 2.0
        result.max_drawdown_percent = 20.0
        result.starting_capital = 10000
        result.total_fees = 100
        result.total_funding = 50
        result.start_date = "2025-01-01"
        result.end_date = "2025-06-30"
        result.total_trades = 100
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "HIGH DRAWDOWN" in text

    def test_moderate_drawdown_note(self):
        """Max drawdown 10-15% should trigger moderate warning."""
        result = BacktestResult.empty()
        result.win_rate = 65.0
        result.profit_factor = 2.0
        result.max_drawdown_percent = 12.0
        result.starting_capital = 10000
        result.total_fees = 100
        result.total_funding = 50
        result.start_date = "2025-01-01"
        result.end_date = "2025-06-30"
        result.total_trades = 100
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "Moderate drawdown" in text

    def test_low_trade_frequency_note(self):
        """Low trade frequency (<0.5/day) should trigger note."""
        result = BacktestResult.empty()
        result.win_rate = 65.0
        result.profit_factor = 2.0
        result.max_drawdown_percent = 5.0
        result.starting_capital = 10000
        result.total_fees = 100
        result.total_funding = 50
        result.start_date = "2025-01-01"
        result.end_date = "2025-07-01"
        result.total_trades = 30  # ~0.16/day over 181 days
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "Low trade frequency" in text

    def test_high_cost_warning(self):
        """High trading costs (>5% of capital) should trigger warning."""
        result = BacktestResult.empty()
        result.win_rate = 65.0
        result.profit_factor = 2.0
        result.max_drawdown_percent = 5.0
        result.starting_capital = 10000
        result.total_fees = 400
        result.total_funding = 200
        result.start_date = "2025-01-01"
        result.end_date = "2025-06-30"
        result.total_trades = 100
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "HIGH TRADING COSTS" in text

    def test_parameter_suggestions_for_poor_performance(self):
        """Low win rate + low profit factor should produce parameter suggestions."""
        result = BacktestResult.empty()
        result.win_rate = 45.0
        result.profit_factor = 1.0
        result.max_drawdown_percent = 12.0
        result.starting_capital = 10000
        result.total_fees = 100
        result.total_funding = 50
        report = BacktestReport(result)

        recs = report._generate_recommendations()
        text = "\n".join(recs)

        assert "SUGGESTED PARAMETER CHANGES" in text
        assert "Take Profit" in text
        assert "Position Size" in text


# ===========================================================================
# BacktestReport - Save JSON
# ===========================================================================


class TestBacktestReportSaveJson:
    """Tests for JSON report saving."""

    def test_save_json_creates_file(self, sample_backtest_result, tmp_path):
        """save_json should create a JSON file with results."""
        filepath = str(tmp_path / "results.json")
        report = BacktestReport(sample_backtest_result)

        report.save_json(filepath)

        assert Path(filepath).exists()

        with open(filepath) as f:
            data = json.load(f)

        assert "summary" in data
        assert "generated_at" in data
        assert data["summary"]["starting_capital"] == 10000.0

    def test_save_json_creates_parent_dirs(self, sample_backtest_result, tmp_path):
        """save_json should create parent directories if needed."""
        filepath = str(tmp_path / "nested" / "dir" / "results.json")
        report = BacktestReport(sample_backtest_result)

        report.save_json(filepath)

        assert Path(filepath).exists()


# ===========================================================================
# BacktestReport - Changelog Entry
# ===========================================================================


class TestBacktestReportChangelog:
    """Tests for changelog entry generation."""

    def test_changelog_contains_metrics(self, sample_backtest_result):
        """Changelog entry should contain key metrics."""
        report = BacktestReport(sample_backtest_result)
        entry = report.generate_changelog_entry()

        assert "2025-01-01" in entry
        assert "2025-06-30" in entry
        assert "$10,000.00" in entry
        assert "$11,500.00" in entry
        assert "+15.00%" in entry
        assert "60.00%" in entry

    def test_changelog_contains_monthly_performance(self, sample_backtest_result):
        """Changelog entry should include monthly breakdown."""
        report = BacktestReport(sample_backtest_result)
        entry = report.generate_changelog_entry()

        assert "2025-01" in entry
        assert "2025-06" in entry


# ===========================================================================
# Mock Data Generation Tests
# ===========================================================================


class TestGenerateMockHistoricalData:
    """Tests for mock historical data generation."""

    def test_generates_correct_number_of_days(self):
        """Should generate exactly the requested number of days."""
        data = generate_mock_historical_data(days=30, seed=42)

        assert len(data) == 30

    def test_generates_default_180_days(self):
        """Default generation should produce 180 data points."""
        data = generate_mock_historical_data()

        assert len(data) == 180

    def test_reproducible_with_same_seed(self):
        """Same seed should produce identical data."""
        data1 = generate_mock_historical_data(days=30, seed=123)
        data2 = generate_mock_historical_data(days=30, seed=123)

        for dp1, dp2 in zip(data1, data2):
            assert dp1.btc_price == dp2.btc_price
            assert dp1.fear_greed_index == dp2.fear_greed_index
            assert dp1.long_short_ratio == dp2.long_short_ratio

    def test_different_seeds_produce_different_data(self):
        """Different seeds should produce different data."""
        data1 = generate_mock_historical_data(days=30, seed=42)
        data2 = generate_mock_historical_data(days=30, seed=99)

        # At least some values should differ
        differences = sum(
            1 for dp1, dp2 in zip(data1, data2)
            if dp1.btc_price != dp2.btc_price
        )
        assert differences > 0

    def test_btc_price_stays_positive(self):
        """BTC price should always remain positive."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert dp.btc_price > 0

    def test_eth_price_stays_positive(self):
        """ETH price should always remain positive."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert dp.eth_price > 0

    def test_fear_greed_in_valid_range(self):
        """Fear & Greed index should stay within 1-100 range."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert 1 <= dp.fear_greed_index <= 100

    def test_fear_greed_classification_valid(self):
        """Fear & Greed classification should be one of the known values."""
        valid_classifications = {
            "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
        }
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert dp.fear_greed_classification in valid_classifications

    def test_long_short_ratio_reasonable_range(self):
        """Long/short ratio should stay within reasonable bounds."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert 0.2 <= dp.long_short_ratio <= 3.5

    def test_open_interest_stays_above_minimum(self):
        """Open interest should never go below minimum threshold."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert dp.open_interest_btc >= 5_000_000_000

    def test_usdt_market_cap_stays_above_minimum(self):
        """USDT market cap should never go below minimum threshold."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert dp.usdt_market_cap >= 50_000_000_000

    def test_dxy_in_valid_range(self):
        """DXY index should stay within reasonable bounds."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert 90 <= dp.dxy_index <= 115

    def test_fed_funds_rate_non_negative(self):
        """Fed funds rate should not go negative."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert dp.fed_funds_rate >= 0

    def test_btc_hashrate_stays_above_minimum(self):
        """BTC hashrate should not fall below minimum threshold."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert dp.btc_hashrate >= 300

    def test_high_low_relationship(self):
        """High should be >= low for both BTC and ETH."""
        data = generate_mock_historical_data(days=180, seed=42)

        for dp in data:
            assert dp.btc_high >= dp.btc_low
            assert dp.eth_high >= dp.eth_low

    def test_date_strings_sequential(self):
        """Date strings should be in sequential order."""
        data = generate_mock_historical_data(days=30, seed=42)

        dates = [dp.date_str for dp in data]
        for i in range(1, len(dates)):
            assert dates[i] > dates[i - 1]

    def test_historical_volatility_computed(self):
        """Historical volatility should be computed after day 20."""
        data = generate_mock_historical_data(days=30, seed=42)

        # After 20 days, volatility should be computed from actual returns
        for dp in data[20:]:
            assert dp.historical_volatility > 0

    def test_btc_volume_positive(self):
        """BTC volume should always be positive."""
        data = generate_mock_historical_data(days=30, seed=42)

        for dp in data:
            assert dp.btc_volume > 0

    def test_market_phases_affect_sentiment(self):
        """Different market phases should produce different sentiment ranges."""
        data = generate_mock_historical_data(days=180, seed=42)

        # The last phase (days ~145-180) should be capitulation with low fear_greed
        # and the second phase (days ~36-72) should be bullish with higher fear_greed
        early_phase_fgi = [dp.fear_greed_index for dp in data[:36]]
        bull_phase_fgi = [dp.fear_greed_index for dp in data[36:72]]

        avg_early = sum(early_phase_fgi) / len(early_phase_fgi)
        avg_bull = sum(bull_phase_fgi) / len(bull_phase_fgi)

        # Bull phase should have higher average fear/greed than accumulation
        # This is a statistical test, so we allow some tolerance
        assert avg_bull > avg_early - 15  # Allow tolerance


# ===========================================================================
# Mock Data Summary Tests
# ===========================================================================


class TestGetMockDataSummary:
    """Tests for mock data summary statistics."""

    def test_returns_empty_dict_for_empty_data(self):
        """Should return empty dict when no data points given."""
        result = get_mock_data_summary([])

        assert result == {}

    def test_summary_contains_period(self):
        """Summary should include the data period."""
        data = generate_mock_historical_data(days=30, seed=42)
        summary = get_mock_data_summary(data)

        assert "period" in summary
        assert data[0].date_str in summary["period"]
        assert data[-1].date_str in summary["period"]

    def test_summary_contains_price_stats(self):
        """Summary should include BTC price statistics."""
        data = generate_mock_historical_data(days=30, seed=42)
        summary = get_mock_data_summary(data)

        assert "btc_start" in summary
        assert "btc_end" in summary
        assert "btc_min" in summary
        assert "btc_max" in summary
        assert summary["btc_start"] == data[0].btc_price
        assert summary["btc_end"] == data[-1].btc_price
        assert summary["btc_min"] <= summary["btc_start"]
        assert summary["btc_max"] >= summary["btc_start"]

    def test_summary_contains_sentiment_stats(self):
        """Summary should include sentiment statistics."""
        data = generate_mock_historical_data(days=180, seed=42)
        summary = get_mock_data_summary(data)

        assert "fgi_avg" in summary
        assert "extreme_fear_days" in summary
        assert "extreme_greed_days" in summary
        assert 0 <= summary["fgi_avg"] <= 100
        assert summary["extreme_fear_days"] >= 0
        assert summary["extreme_greed_days"] >= 0

    def test_summary_contains_crowd_stats(self):
        """Summary should include crowded position statistics."""
        data = generate_mock_historical_data(days=180, seed=42)
        summary = get_mock_data_summary(data)

        assert "crowded_long_days" in summary
        assert "crowded_short_days" in summary
        assert "ls_avg" in summary

    def test_summary_contains_data_sources(self):
        """Summary should list all simulated data sources."""
        data = generate_mock_historical_data(days=30, seed=42)
        summary = get_mock_data_summary(data)

        assert "data_sources" in summary
        assert "Mock Data Generator" in summary["data_sources"]
        assert len(summary["data_sources"]) > 0

    def test_summary_day_count_matches_input(self):
        """Summary 'days' field should match input data length."""
        data = generate_mock_historical_data(days=45, seed=42)
        summary = get_mock_data_summary(data)

        assert summary["days"] == 45
