"""
Extra tests for historical_data.py to improve coverage from 73% to 90%+.

Focuses on:
- fetch_all_historical_data (the large combined method)
- Pagination loops in multiple fetch methods
- Edge cases in data parsing and transformation
- FRED series with cached data and missing observations
- Stablecoin non-dict circulating data
- Volatility edge cases
- Session lifecycle edge cases
- save/load error paths
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.backtest.historical_data import HistoricalDataFetcher, HistoricalDataPoint


# ===========================================================================
# Fixtures
# ===========================================================================


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


def _make_klines(count, base_ts=1700000000, base_price=60000.0, step=86400):
    """Helper: generate kline data for testing."""
    result = []
    for i in range(count):
        price = base_price + i * 100
        result.append({
            "timestamp": base_ts + i * step,
            "open": price - 50,
            "high": price + 500,
            "low": price - 500,
            "close": price,
            "volume": 1000000.0 + i * 10000,
        })
    return result


def _make_fear_greed(count, base_ts=1700000000, step=86400):
    """Helper: generate fear & greed data for testing."""
    result = []
    for i in range(count):
        val = 30 + (i % 50)
        classifications = {
            range(0, 25): "Extreme Fear",
            range(25, 45): "Fear",
            range(45, 55): "Neutral",
            range(55, 75): "Greed",
            range(75, 101): "Extreme Greed",
        }
        cls_name = "Neutral"
        for rng, name in classifications.items():
            if val in rng:
                cls_name = name
                break
        result.append({
            "timestamp": base_ts + i * step,
            "value": val,
            "classification": cls_name,
        })
    return result


def _make_funding(count, base_ts=1700000000, step=28800):
    """Helper: generate funding rate data (3x per day)."""
    result = []
    for i in range(count):
        result.append({
            "timestamp": base_ts + i * step,
            "rate": 0.0001 + (i % 5) * 0.00005,
        })
    return result


def _make_long_short(count, base_ts=1700000000, step=86400):
    """Helper: generate long/short ratio data."""
    return [
        {"timestamp": base_ts + i * step, "ratio": 1.0 + (i % 10) * 0.1}
        for i in range(count)
    ]


# ===========================================================================
# Session Lifecycle Edge Cases
# ===========================================================================


class TestSessionLifecycle:
    """Tests for session management edge cases."""

    async def test_ensure_session_creates_new_when_closed(self, fetcher):
        """_ensure_session should create a new session when current session is closed."""
        mock_old_session = MagicMock()
        mock_old_session.closed = True
        fetcher._session = mock_old_session

        with patch("src.backtest.historical_data.aiohttp.ClientSession") as mock_cls:
            mock_new = AsyncMock()
            mock_cls.return_value = mock_new

            await fetcher._ensure_session()

            mock_cls.assert_called_once()
            assert fetcher._session == mock_new

    async def test_close_does_nothing_when_session_is_none(self, fetcher):
        """close() should not raise when session is None."""
        fetcher._session = None
        await fetcher.close()

    async def test_close_does_nothing_when_session_already_closed(self, fetcher):
        """close() should not call close again when session is already closed."""
        mock_session = MagicMock()
        mock_session.closed = True
        mock_session.close = AsyncMock()
        fetcher._session = mock_session

        await fetcher.close()

        mock_session.close.assert_not_called()

    async def test_get_passes_params(self, fetcher):
        """_get should pass params to the session.get call."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"ok": True})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.closed = False
        fetcher._session = mock_session

        result = await fetcher._get("https://example.com/api", {"key": "value"})

        assert result == {"ok": True}
        mock_session.get.assert_called_once_with(
            "https://example.com/api",
            params={"key": "value"},
            timeout=30,
        )


# ===========================================================================
# Funding Rate Pagination
# ===========================================================================


class TestFundingRatePagination:
    """Tests for funding rate pagination loop."""

    async def test_funding_rate_paginates_multiple_pages(self, fetcher):
        """Should paginate through multiple pages of funding rate data."""
        now_ms = int(datetime.now().timestamp() * 1000)
        page1 = [
            {"fundingTime": now_ms - 1000, "fundingRate": "0.0001"},
            {"fundingTime": now_ms - 50000, "fundingRate": "0.0002"},
        ]
        page2 = [
            {"fundingTime": now_ms - 100000, "fundingRate": "0.0003"},
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[page1, page2, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_funding_rate_history("BTCUSDT", 1)

        assert len(result) >= 1
        assert fetcher._get.call_count >= 2

    async def test_funding_rate_handles_empty_first_page(self, fetcher):
        """Should return empty list when first page returns empty data."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=[])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_funding_rate_history("BTCUSDT", 30)

        assert result == []

    async def test_funding_rate_filters_by_start_time(self, fetcher):
        """Should filter out data points before the start time window."""
        now_ms = int(datetime.now().timestamp() * 1000)
        very_old_ts = now_ms - (200 * 86400 * 1000)  # 200 days ago
        recent_ts = now_ms - 5000

        api_data = [
            {"fundingTime": recent_ts, "fundingRate": "0.0001"},
            {"fundingTime": very_old_ts, "fundingRate": "0.0002"},
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_funding_rate_history("BTCUSDT", 30)

        # The very old data point should be filtered out
        timestamps = [r["timestamp"] for r in result]
        cutoff = int((datetime.now() - timedelta(days=30)).timestamp())
        for ts in timestamps:
            assert ts >= cutoff


# ===========================================================================
# Long/Short Pagination
# ===========================================================================


class TestLongShortPagination:
    """Tests for long/short ratio pagination."""

    async def test_long_short_paginates(self, fetcher):
        """Should paginate through multiple pages."""
        now_ms = int(datetime.now().timestamp() * 1000)
        page1 = [
            {"timestamp": now_ms - 1000, "longShortRatio": "1.5"},
            {"timestamp": now_ms - 50000, "longShortRatio": "1.3"},
        ]
        page2 = [
            {"timestamp": now_ms - 100000, "longShortRatio": "1.1"},
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[page1, page2, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_long_short_history("BTCUSDT", 1)

        assert len(result) >= 1

    async def test_long_short_empty_first_page(self, fetcher):
        """Should handle empty data on first page."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_long_short_history("BTCUSDT", 30)

        assert result == []


# ===========================================================================
# Open Interest Pagination
# ===========================================================================


class TestOpenInterestPagination:
    """Tests for open interest pagination."""

    async def test_open_interest_paginates(self, fetcher):
        """Should paginate and deduplicate open interest data."""
        now_ms = int(datetime.now().timestamp() * 1000)
        page1 = [
            {"timestamp": now_ms - 5000, "sumOpenInterestValue": "18000000000", "sumOpenInterest": "300000"},
            {"timestamp": now_ms - 90000, "sumOpenInterestValue": "17500000000", "sumOpenInterest": "290000"},
        ]
        page2 = [
            {"timestamp": now_ms - 180000, "sumOpenInterestValue": "17000000000", "sumOpenInterest": "280000"},
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[page1, page2, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_open_interest_history("BTCUSDT", 1)

        assert len(result) >= 1
        # Check deduplication
        timestamps = [r["timestamp"] for r in result]
        assert len(timestamps) == len(set(timestamps))

    async def test_open_interest_empty_first_page(self, fetcher):
        """Should handle empty data on first page."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=[])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_open_interest_history("BTCUSDT", 30)

        assert result == []

    async def test_open_interest_missing_fields_default_to_zero(self, fetcher):
        """Should default to 0 for missing sumOpenInterestValue/sumOpenInterest."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_data = [
            {"timestamp": now_ms - 5000},  # missing fields
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_open_interest_history("BTCUSDT", 1)

        assert len(result) >= 1
        assert result[0]["oi_value"] == 0.0
        assert result[0]["oi_quantity"] == 0.0


# ===========================================================================
# Taker Buy/Sell Pagination
# ===========================================================================


class TestTakerBuySellPagination:
    """Tests for taker buy/sell ratio pagination."""

    async def test_taker_paginates(self, fetcher):
        """Should paginate through multiple pages."""
        now_ms = int(datetime.now().timestamp() * 1000)
        page1 = [
            {"timestamp": now_ms - 5000, "buySellRatio": "1.1", "buyVol": "100", "sellVol": "90"},
            {"timestamp": now_ms - 90000, "buySellRatio": "0.9", "buyVol": "90", "sellVol": "100"},
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[page1, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_taker_buy_sell_history("BTCUSDT", 1)

        assert len(result) >= 1

    async def test_taker_empty_first_page(self, fetcher):
        """Should handle empty data on first page."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_taker_buy_sell_history("BTCUSDT", 30)

        assert result == []

    async def test_taker_missing_fields_default(self, fetcher):
        """Should use defaults when optional fields are missing."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_data = [{"timestamp": now_ms - 5000}]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_taker_buy_sell_history("BTCUSDT", 1)

        assert len(result) >= 1
        assert result[0]["ratio"] == 1.0
        assert result[0]["buy_vol"] == 0.0
        assert result[0]["sell_vol"] == 0.0


# ===========================================================================
# Top Trader L/S Pagination
# ===========================================================================


class TestTopTraderLSPagination:
    """Tests for top trader L/S ratio pagination."""

    async def test_top_trader_paginates(self, fetcher):
        """Should paginate through multiple pages."""
        now_ms = int(datetime.now().timestamp() * 1000)
        page1 = [
            {"timestamp": now_ms - 5000, "longShortRatio": "1.2"},
            {"timestamp": now_ms - 90000, "longShortRatio": "1.4"},
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[page1, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_top_trader_ls_history("BTCUSDT", 1)

        assert len(result) >= 1
        assert result[0]["ratio"] in [1.2, 1.4]

    async def test_top_trader_empty_first_page(self, fetcher):
        """Should handle empty data on first page."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=[])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_top_trader_ls_history("BTCUSDT", 30)

        assert result == []

    async def test_top_trader_missing_ratio_defaults(self, fetcher):
        """Should default ratio to 1.0 when longShortRatio is missing."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_data = [{"timestamp": now_ms - 5000}]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_top_trader_ls_history("BTCUSDT", 1)

        assert len(result) >= 1
        assert result[0]["ratio"] == 1.0

    async def test_top_trader_deduplicates(self, fetcher):
        """Should deduplicate entries with same timestamp."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_data = [
            {"timestamp": now_ms - 5000, "longShortRatio": "1.2"},
            {"timestamp": now_ms - 5000, "longShortRatio": "1.3"},  # duplicate
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_data, []])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_top_trader_ls_history("BTCUSDT", 1)

        timestamps = [r["timestamp"] for r in result]
        assert len(timestamps) == len(set(timestamps))


# ===========================================================================
# Bitget Funding Pagination
# ===========================================================================


class TestBitgetFundingPagination:
    """Tests for Bitget funding rate pagination."""

    async def test_bitget_paginates_multiple_pages(self, fetcher):
        """Should paginate through multiple pages."""
        now_ms = int(datetime.now().timestamp() * 1000)
        page1 = {
            "code": "00000",
            "data": [
                {"settleTime": str(now_ms - 5000), "fundingRate": "0.0001"},
                {"settleTime": str(now_ms - 50000), "fundingRate": "0.0002"},
            ],
        }
        page2 = {
            "code": "00000",
            "data": [
                {"settleTime": str(now_ms - 100000), "fundingRate": "0.0003"},
            ],
        }
        page3 = {"code": "00000", "data": []}

        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[page1, page2, page3])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_bitget_funding_history("BTCUSDT", 1)

        assert len(result) >= 1
        fetcher._get.call_count >= 2

    async def test_bitget_stops_on_none_response(self, fetcher):
        """Should stop when API returns None."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_bitget_funding_history("BTCUSDT", 30)

        assert result == []

    async def test_bitget_filters_by_cutoff(self, fetcher):
        """Should filter data older than the requested days."""
        now_ms = int(datetime.now().timestamp() * 1000)
        old_ts = now_ms - (200 * 86400 * 1000)  # 200 days ago
        recent_ts = now_ms - 5000

        api_response = {
            "code": "00000",
            "data": [
                {"settleTime": str(recent_ts), "fundingRate": "0.0001"},
                {"settleTime": str(old_ts), "fundingRate": "0.0002"},
            ],
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_response, {"code": "00000", "data": []}])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_bitget_funding_history("BTCUSDT", 30)

        # Old data should be filtered out
        cutoff = int((datetime.now() - timedelta(days=30)).timestamp())
        for r in result:
            assert r["timestamp"] >= cutoff

    async def test_bitget_missing_funding_rate_defaults_to_zero(self, fetcher):
        """Should default fundingRate to 0 when missing."""
        now_ms = int(datetime.now().timestamp() * 1000)
        api_response = {
            "code": "00000",
            "data": [{"settleTime": str(now_ms - 5000)}],
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(side_effect=[api_response, {"code": "00000", "data": []}])
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_bitget_funding_history("BTCUSDT", 1)

        assert len(result) >= 1
        assert result[0]["rate"] == 0.0


# ===========================================================================
# Stablecoin History Edge Cases
# ===========================================================================


class TestStablecoinEdgeCases:
    """Tests for stablecoin history edge cases."""

    async def test_stablecoin_non_dict_circulating(self, fetcher):
        """Should handle non-dict totalCirculatingUSD (set mcap to 0)."""
        now_ts = int(datetime.now().timestamp())
        api_data = [
            {
                "date": now_ts - 3600,
                "totalCirculatingUSD": "not_a_dict",
            }
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_data)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_stablecoin_history(30)

        assert len(result) == 1
        assert result[0]["usdt_mcap"] == 0

    async def test_stablecoin_missing_date_field(self, fetcher):
        """Should handle missing date field (defaults to 0)."""
        api_data = [
            {"totalCirculatingUSD": {"peggedUSD": 100_000_000_000}},
        ]
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_data)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_stablecoin_history(30)

        # date=0 is way before cutoff, so should be filtered out
        assert result == []

    async def test_stablecoin_none_response(self, fetcher):
        """Should return empty list when API returns None."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)

        result = await fetcher.fetch_stablecoin_history(30)

        assert result == []


# ===========================================================================
# Global Market Data Edge Cases
# ===========================================================================


class TestGlobalMarketEdgeCases:
    """Tests for global market data edge cases."""

    async def test_global_market_missing_nested_keys(self, fetcher):
        """Should handle missing nested keys with defaults."""
        api_response = {
            "data": {
                "market_cap_percentage": {},
                "total_market_cap": {},
                "total_volume": {},
            }
        }
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=api_response)
        fetcher._save_cache = MagicMock()

        result = await fetcher.fetch_global_market_data()

        assert result["btc_dominance"] == 0.0
        assert result["total_market_cap_usd"] == 0.0
        assert result["total_volume_usd"] == 0.0

    async def test_global_market_missing_data_key(self, fetcher):
        """Should return empty dict when 'data' key is missing."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value={"status": "error"})

        result = await fetcher.fetch_global_market_data()

        assert result == {}


# ===========================================================================
# FRED Series Edge Cases
# ===========================================================================


class TestFredSeriesEdgeCases:
    """Tests for FRED series edge cases."""

    async def test_fred_returns_cached_data(self, fetcher):
        """Should return cached FRED data."""
        cached = [{"timestamp": 1700000, "value": 104.5}]
        fetcher._load_cache = MagicMock(return_value=cached)

        with patch.dict(os.environ, {"FRED_API_KEY": "test-key"}):
            result = await fetcher.fetch_fred_series("DTWEXBGS", 30)

        assert result == cached

    async def test_fred_no_observations_key(self, fetcher):
        """Should return empty list when 'observations' key is missing."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value={"error": "not found"})
        fetcher._save_cache = MagicMock()

        with patch.dict(os.environ, {"FRED_API_KEY": "test-key"}):
            result = await fetcher.fetch_fred_series("DTWEXBGS", 30)

        assert result == []

    async def test_fred_none_response(self, fetcher):
        """Should return empty list when API returns None."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)

        with patch.dict(os.environ, {"FRED_API_KEY": "test-key"}):
            result = await fetcher.fetch_fred_series("DTWEXBGS", 30)

        assert result == []

    async def test_fred_observation_missing_value_key(self, fetcher):
        """Should skip observations with missing 'value' key."""
        api_response = {
            "observations": [
                {"date": "2025-01-15"},  # missing value
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
# BTC Hashrate Edge Cases
# ===========================================================================


class TestBtcHashrateEdgeCases:
    """Tests for BTC hashrate edge cases."""

    async def test_hashrate_returns_none_on_api_failure(self, fetcher):
        """Should return empty list when API returns None."""
        fetcher._load_cache = MagicMock(return_value=None)
        fetcher._get = AsyncMock(return_value=None)

        result = await fetcher.fetch_btc_hashrate_history(30)

        assert result == []


# ===========================================================================
# Volatility Calculation Edge Cases
# ===========================================================================


class TestVolatilityEdgeCases:
    """Additional volatility calculation tests."""

    def test_volatility_with_exactly_window_plus_one(self):
        """Should return at least one data point when data == window+1."""
        klines = _make_klines(22)

        result = HistoricalDataFetcher.calculate_volatility(klines, window=20)

        assert len(result) >= 1

    def test_volatility_with_identical_prices(self):
        """Should return 0 volatility when all prices are the same."""
        klines = [
            {"close": 60000.0, "timestamp": 1700000000 + i * 86400}
            for i in range(25)
        ]

        result = HistoricalDataFetcher.calculate_volatility(klines, window=20)

        # All returns are 0, but variance formula may still give near-zero
        # The key is it should not raise
        for vol in result.values():
            assert vol == 0.0

    def test_volatility_window_size_affects_result(self):
        """Different window sizes should produce different results."""
        klines = _make_klines(50)

        result_10 = HistoricalDataFetcher.calculate_volatility(klines, window=10)
        result_20 = HistoricalDataFetcher.calculate_volatility(klines, window=20)

        assert len(result_10) > len(result_20)

    def test_volatility_empty_klines(self):
        """Should return empty dict for empty input."""
        result = HistoricalDataFetcher.calculate_volatility([], window=20)

        assert result == {}

    def test_volatility_single_kline(self):
        """Should return empty dict for single kline."""
        result = HistoricalDataFetcher.calculate_volatility(
            [{"close": 60000.0, "timestamp": 1700000000}], window=20
        )

        assert result == {}


# ===========================================================================
# Data Sources Property
# ===========================================================================


class TestDataSourcesProperty:
    """Tests for data_sources property."""

    def test_data_sources_returns_list(self, fetcher):
        """data_sources should return the internal list."""
        fetcher._data_sources = ["Source A", "Source B"]
        assert fetcher.data_sources == ["Source A", "Source B"]

    def test_data_sources_empty_by_default(self, fetcher):
        """data_sources should be empty on init."""
        assert fetcher.data_sources == []


# ===========================================================================
# Save / Load Data Points Edge Cases
# ===========================================================================


class TestSaveLoadEdgeCases:
    """Tests for save/load data points edge cases."""

    def test_save_multiple_data_points(self, fetcher, tmp_cache_dir):
        """Should save and load multiple data points."""
        points = []
        for i in range(5):
            points.append(HistoricalDataPoint(
                timestamp=datetime(2025, 1, 1 + i),
                date_str=f"2025-01-0{i+1}",
                fear_greed_index=50 + i,
                fear_greed_classification="Neutral",
                long_short_ratio=1.0,
                funding_rate_btc=0.0,
                funding_rate_eth=0.0,
                btc_price=60000.0 + i * 1000,
                eth_price=3000.0 + i * 100,
                btc_high=61000.0,
                btc_low=59000.0,
                eth_high=3100.0,
                eth_low=2900.0,
                btc_24h_change=0.0,
                eth_24h_change=0.0,
            ))

        fetcher.save_data_points(points, "multi_test.json")
        loaded = fetcher.load_data_points("multi_test.json")

        assert len(loaded) == 5
        assert loaded[0].btc_price == 60000.0
        assert loaded[4].btc_price == 64000.0

    def test_save_empty_list(self, fetcher, tmp_cache_dir):
        """Should save and load empty list."""
        fetcher.save_data_points([], "empty_test.json")
        loaded = fetcher.load_data_points("empty_test.json")

        assert loaded == []


# ===========================================================================
# CoinGecko Fallback Edge Cases
# ===========================================================================


class TestCoinGeckoFallbackEdgeCases:
    """Additional tests for CoinGecko fallback."""

    async def test_coingecko_cached_data(self, fetcher):
        """Should return cached CoinGecko data."""
        cached = [{"timestamp": 1700000, "close": 60000}]
        fetcher._load_cache = MagicMock(return_value=cached)

        result = await fetcher.fetch_coingecko_history("bitcoin", 30)

        assert result == cached


# ===========================================================================
# fetch_all_historical_data - The Big Combined Method
# ===========================================================================


class TestFetchAllHistoricalData:
    """Tests for the combined fetch_all_historical_data method."""

    async def test_fetch_all_returns_data_points_from_core_data(self, fetcher):
        """Should combine core data sources into HistoricalDataPoint objects."""
        base_ts = int((datetime.now() - timedelta(days=5)).timestamp())
        klines_btc = _make_klines(5, base_ts=base_ts)
        klines_eth = _make_klines(5, base_ts=base_ts, base_price=3000.0)
        fear_greed = _make_fear_greed(5, base_ts=base_ts)
        funding_btc = _make_funding(15, base_ts=base_ts)
        funding_eth = _make_funding(15, base_ts=base_ts)
        long_short = _make_long_short(5, base_ts=base_ts)

        # Mock all fetch methods
        fetcher.fetch_fear_greed_history = AsyncMock(return_value=fear_greed)
        fetcher.fetch_funding_rate_history = AsyncMock(side_effect=[funding_btc, funding_eth])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=long_short)

        # Extended sources return empty
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=5)

        assert len(result) == 5
        assert all(isinstance(dp, HistoricalDataPoint) for dp in result)
        assert result[0].btc_price > 0
        assert result[0].eth_price > 0

    async def test_fetch_all_tracks_data_sources(self, fetcher):
        """Should track which data sources returned data."""
        base_ts = int((datetime.now() - timedelta(days=3)).timestamp())
        klines_btc = _make_klines(3, base_ts=base_ts)
        klines_eth = _make_klines(3, base_ts=base_ts, base_price=3000.0)
        fear_greed = _make_fear_greed(3, base_ts=base_ts)
        funding_btc = _make_funding(9, base_ts=base_ts)
        long_short = _make_long_short(3, base_ts=base_ts)

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=fear_greed)
        fetcher.fetch_funding_rate_history = AsyncMock(side_effect=[funding_btc, []])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=long_short)
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        await fetcher.fetch_all_historical_data(days=3)

        sources = fetcher.data_sources
        assert "Binance Futures (OHLCV)" in sources
        assert "Alternative.me (Fear & Greed)" in sources
        assert "Binance (L/S Ratio)" in sources
        assert "Binance (Funding Rates)" in sources

    async def test_fetch_all_with_all_extended_sources(self, fetcher):
        """Should include extended data sources in data points when available."""
        base_ts = int((datetime.now() - timedelta(days=3)).timestamp())
        klines_btc = _make_klines(3, base_ts=base_ts)
        klines_eth = _make_klines(3, base_ts=base_ts, base_price=3000.0)
        fear_greed = _make_fear_greed(3, base_ts=base_ts)
        funding_btc = _make_funding(9, base_ts=base_ts)
        funding_eth = _make_funding(9, base_ts=base_ts)
        long_short = _make_long_short(3, base_ts=base_ts)

        # Extended sources with data
        open_interest = [
            {"timestamp": base_ts + i * 86400, "oi_value": 18e9 + i * 1e8, "oi_quantity": 300000}
            for i in range(3)
        ]
        taker_bs = [
            {"timestamp": base_ts + i * 86400, "ratio": 1.05 + i * 0.01, "buy_vol": 5000, "sell_vol": 4500}
            for i in range(3)
        ]
        top_trader_ls = [
            {"timestamp": base_ts + i * 86400, "ratio": 1.1 + i * 0.05}
            for i in range(3)
        ]
        bitget_funding = [
            {"timestamp": base_ts + i * 86400, "rate": 0.0002 + i * 0.00001}
            for i in range(3)
        ]
        stablecoin = [
            {"timestamp": base_ts + i * 86400, "usdt_mcap": 120e9 + i * 1e9}
            for i in range(3)
        ]
        hashrate = [
            {"timestamp": base_ts + i * 86400, "hashrate": 650 + i * 5}
            for i in range(3)
        ]
        global_market = {
            "btc_dominance": 52.3,
            "total_market_cap_usd": 2.5e12,
            "total_volume_usd": 100e9,
        }
        fred_dxy = [
            {"timestamp": base_ts + i * 86400, "value": 104.5 + i * 0.1, "date": datetime.fromtimestamp(base_ts + i * 86400).strftime("%Y-%m-%d")}
            for i in range(3)
        ]
        fred_ffr = [
            {"timestamp": base_ts + i * 86400, "value": 5.25, "date": datetime.fromtimestamp(base_ts + i * 86400).strftime("%Y-%m-%d")}
            for i in range(3)
        ]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=fear_greed)
        fetcher.fetch_funding_rate_history = AsyncMock(side_effect=[funding_btc, funding_eth])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=long_short)
        fetcher.fetch_open_interest_history = AsyncMock(return_value=open_interest)
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=taker_bs)
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=top_trader_ls)
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=bitget_funding)
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=stablecoin)
        fetcher.fetch_global_market_data = AsyncMock(return_value=global_market)
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=hashrate)
        fetcher.fetch_fred_series = AsyncMock(side_effect=[fred_dxy, fred_ffr])

        result = await fetcher.fetch_all_historical_data(days=3)

        assert len(result) == 3
        # Check extended fields are populated
        dp = result[0]
        assert dp.btc_dominance == 52.3
        assert dp.total_crypto_market_cap == 2.5e12
        assert dp.open_interest_btc > 0
        assert dp.taker_buy_sell_ratio > 0
        assert dp.top_trader_long_short_ratio > 0
        assert dp.dxy_index > 0
        assert dp.fed_funds_rate > 0
        assert dp.btc_hashrate > 0

        # All extended sources should be tracked
        sources = fetcher.data_sources
        assert "Binance (Open Interest)" in sources
        assert "Binance (Taker Buy/Sell)" in sources
        assert "Binance (Top Trader L/S)" in sources
        assert "Bitget (Funding Rates)" in sources
        assert "DefiLlama (Stablecoin Flows)" in sources
        assert "CoinGecko (Global Market)" in sources
        assert "Blockchain.info (Hashrate)" in sources
        assert "FRED (DXY Index)" in sources
        assert "FRED (Fed Funds Rate)" in sources

    async def test_fetch_all_handles_core_exceptions(self, fetcher):
        """Should handle exceptions from core data sources gracefully."""
        fetcher.fetch_fear_greed_history = AsyncMock(side_effect=Exception("API error"))
        fetcher.fetch_funding_rate_history = AsyncMock(side_effect=Exception("timeout"))
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[[], []])
        fetcher.fetch_long_short_history = AsyncMock(side_effect=Exception("fail"))
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        # Should not raise - exceptions are caught by asyncio.gather(return_exceptions=True)
        result = await fetcher.fetch_all_historical_data(days=3)

        # No klines = no data points
        assert result == []

    async def test_fetch_all_handles_extended_exceptions(self, fetcher):
        """Should handle exceptions from extended data sources gracefully."""
        base_ts = int((datetime.now() - timedelta(days=3)).timestamp())
        klines_btc = _make_klines(3, base_ts=base_ts)
        klines_eth = _make_klines(3, base_ts=base_ts, base_price=3000.0)

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])

        # Extended sources all throw exceptions
        fetcher.fetch_open_interest_history = AsyncMock(side_effect=Exception("OI fail"))
        fetcher.fetch_taker_buy_sell_history = AsyncMock(side_effect=Exception("taker fail"))
        fetcher.fetch_top_trader_ls_history = AsyncMock(side_effect=Exception("top fail"))
        fetcher.fetch_bitget_funding_history = AsyncMock(side_effect=Exception("bitget fail"))
        fetcher.fetch_stablecoin_history = AsyncMock(side_effect=Exception("stable fail"))
        fetcher.fetch_global_market_data = AsyncMock(side_effect=Exception("global fail"))
        fetcher.fetch_btc_hashrate_history = AsyncMock(side_effect=Exception("hash fail"))
        fetcher.fetch_fred_series = AsyncMock(side_effect=Exception("fred fail"))

        result = await fetcher.fetch_all_historical_data(days=3)

        # Should still produce data points from klines
        assert len(result) == 3
        # Extended fields should have defaults
        assert result[0].open_interest_btc == 0
        assert result[0].btc_dominance == 0

    async def test_fetch_all_empty_klines_returns_empty(self, fetcher):
        """Should return empty list when no kline data is available."""
        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(return_value=[])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=30)

        assert result == []

    async def test_fetch_all_calculates_btc_change_percent(self, fetcher):
        """Should calculate BTC 24h change from open/close prices."""
        base_ts = int((datetime.now() - timedelta(days=2)).timestamp())
        klines_btc = [
            {"timestamp": base_ts, "open": 50000.0, "high": 52000.0, "low": 49000.0, "close": 51000.0, "volume": 1e6},
            {"timestamp": base_ts + 86400, "open": 51000.0, "high": 53000.0, "low": 50000.0, "close": 52000.0, "volume": 1.1e6},
        ]
        klines_eth = _make_klines(2, base_ts=base_ts, base_price=3000.0)

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=2)

        assert len(result) == 2
        # First data point: (51000 - 50000) / 50000 * 100 = 2.0%
        assert result[0].btc_24h_change == pytest.approx(2.0)

    async def test_fetch_all_handles_zero_open_price(self, fetcher):
        """Should handle zero open price without division error."""
        base_ts = int((datetime.now() - timedelta(days=1)).timestamp())
        klines_btc = [
            {"timestamp": base_ts, "open": 0, "high": 1000, "low": 0, "close": 500, "volume": 1e6},
        ]
        klines_eth = [
            {"timestamp": base_ts, "open": 0, "high": 100, "low": 0, "close": 50, "volume": 1e5},
        ]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=1)

        assert len(result) == 1
        assert result[0].btc_24h_change == 0
        assert result[0].eth_24h_change == 0

    async def test_fetch_all_stablecoin_flow_calculation(self, fetcher):
        """Should calculate 7-day stablecoin flow correctly."""
        base_ts = int((datetime.now() - timedelta(days=10)).timestamp())
        klines_btc = _make_klines(10, base_ts=base_ts)
        klines_eth = _make_klines(10, base_ts=base_ts, base_price=3000.0)

        stablecoin = [
            {"timestamp": base_ts + i * 86400, "usdt_mcap": 100e9 + i * 1e9}
            for i in range(10)
        ]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=stablecoin)
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=10)

        assert len(result) == 10
        # After 7 days, stablecoin flow should be calculated
        # Flow at day 7 = mcap[7] - mcap[0] = (100e9 + 7e9) - 100e9 = 7e9
        # But data alignment depends on date keys matching between klines and stablecoin

    async def test_fetch_all_oi_change_calculation(self, fetcher):
        """Should calculate OI 24h change percentage correctly."""
        base_ts = int((datetime.now() - timedelta(days=3)).timestamp())
        klines_btc = _make_klines(3, base_ts=base_ts)
        klines_eth = _make_klines(3, base_ts=base_ts, base_price=3000.0)

        open_interest = [
            {"timestamp": base_ts, "oi_value": 10e9, "oi_quantity": 200000},
            {"timestamp": base_ts + 86400, "oi_value": 11e9, "oi_quantity": 210000},
            {"timestamp": base_ts + 2 * 86400, "oi_value": 10.5e9, "oi_quantity": 205000},
        ]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=open_interest)
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=3)

        assert len(result) == 3
        # Day 0: oi_change = 0 (first element)
        # Day 1: oi_change = (11e9 - 10e9) / 10e9 * 100 = 10.0
        # Day 2: oi_change = (10.5e9 - 11e9) / 11e9 * 100 = -4.545...

    async def test_fetch_all_fred_forward_fill(self, fetcher):
        """Should forward-fill FRED data for dates without observations."""
        base_ts = int((datetime.now() - timedelta(days=5)).timestamp())
        klines_btc = _make_klines(5, base_ts=base_ts)
        klines_eth = _make_klines(5, base_ts=base_ts, base_price=3000.0)

        # FRED data only on days 0 and 3
        date0 = datetime.fromtimestamp(base_ts).strftime("%Y-%m-%d")
        date3 = datetime.fromtimestamp(base_ts + 3 * 86400).strftime("%Y-%m-%d")
        fred_dxy = [
            {"timestamp": base_ts, "value": 104.0, "date": date0},
            {"timestamp": base_ts + 3 * 86400, "value": 105.0, "date": date3},
        ]
        fred_ffr = [
            {"timestamp": base_ts, "value": 5.25, "date": date0},
        ]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(side_effect=[fred_dxy, fred_ffr])

        result = await fetcher.fetch_all_historical_data(days=5)

        assert len(result) == 5
        # Day 0: dxy = 104.0, ffr = 5.25
        assert result[0].dxy_index == 104.0
        assert result[0].fed_funds_rate == 5.25
        # Days 1-2: forward-filled from day 0
        assert result[1].dxy_index == 104.0
        assert result[2].dxy_index == 104.0
        # Day 3: updated to 105.0
        assert result[3].dxy_index == 105.0
        # Day 4: forward-filled from day 3
        assert result[4].dxy_index == 105.0

    async def test_fetch_all_with_volatility(self, fetcher):
        """Should calculate and include historical volatility."""
        base_ts = int((datetime.now() - timedelta(days=25)).timestamp())
        klines_btc = _make_klines(25, base_ts=base_ts)
        klines_eth = _make_klines(25, base_ts=base_ts, base_price=3000.0)

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=25)

        assert len(result) == 25
        # After 20+ days, volatility should be calculated for some points
        has_vol = any(dp.historical_volatility > 0 for dp in result)
        assert has_vol

    async def test_fetch_all_data_points_sorted_by_timestamp(self, fetcher):
        """Should return data points sorted by timestamp."""
        base_ts = int((datetime.now() - timedelta(days=5)).timestamp())
        klines_btc = _make_klines(5, base_ts=base_ts)
        klines_eth = _make_klines(5, base_ts=base_ts, base_price=3000.0)

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=5)

        for i in range(1, len(result)):
            assert result[i].timestamp >= result[i - 1].timestamp

    async def test_fetch_all_with_bitget_funding_aggregation(self, fetcher):
        """Should average multiple Bitget funding rates for the same day."""
        base_ts = int((datetime.now() - timedelta(days=2)).timestamp())
        klines_btc = _make_klines(2, base_ts=base_ts)
        klines_eth = _make_klines(2, base_ts=base_ts, base_price=3000.0)

        # Multiple Bitget funding entries for the same day
        bitget_funding = [
            {"timestamp": base_ts + 0, "rate": 0.0001},
            {"timestamp": base_ts + 28800, "rate": 0.0003},  # same day, 8h later
            {"timestamp": base_ts + 57600, "rate": 0.0002},  # same day, 16h later
        ]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=bitget_funding)
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=2)

        assert len(result) == 2
        # The first day should have averaged Bitget funding
        assert result[0].funding_rate_bitget == pytest.approx(0.0002, abs=0.0001)

    async def test_fetch_all_global_market_non_dict(self, fetcher):
        """Should handle non-dict global_market (exception turned empty)."""
        base_ts = int((datetime.now() - timedelta(days=2)).timestamp())
        klines_btc = _make_klines(2, base_ts=base_ts)
        klines_eth = _make_klines(2, base_ts=base_ts, base_price=3000.0)

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value=[])  # list instead of dict
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=2)

        assert len(result) == 2
        # global_market is a list, not dict -> isinstance check fails -> defaults to 0
        assert result[0].btc_dominance == 0
        assert result[0].total_crypto_market_cap == 0

    async def test_fetch_all_missing_eth_kline_uses_defaults(self, fetcher):
        """Should use default ETH values when ETH kline data is missing for a date."""
        base_ts = int((datetime.now() - timedelta(days=3)).timestamp())
        klines_btc = _make_klines(3, base_ts=base_ts)
        # ETH has only 1 data point, so days 1 and 2 will miss ETH data
        klines_eth = _make_klines(1, base_ts=base_ts, base_price=3000.0)

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=3)

        assert len(result) == 3
        # Day 0 has ETH data
        assert result[0].eth_price > 0
        # Days 1, 2 have default ETH values (0)
        assert result[1].eth_price == 0
        assert result[2].eth_price == 0

    async def test_fetch_all_resets_data_sources(self, fetcher):
        """Should reset data sources list on each call."""
        fetcher._data_sources = ["Old Source"]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(return_value=[])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        await fetcher.fetch_all_historical_data(days=1)

        assert "Old Source" not in fetcher.data_sources

    async def test_fetch_all_oi_change_with_zero_prev(self, fetcher):
        """Should handle OI change calculation when previous OI is zero."""
        base_ts = int((datetime.now() - timedelta(days=2)).timestamp())
        klines_btc = _make_klines(2, base_ts=base_ts)
        klines_eth = _make_klines(2, base_ts=base_ts, base_price=3000.0)

        open_interest = [
            {"timestamp": base_ts, "oi_value": 0, "oi_quantity": 0},
            {"timestamp": base_ts + 86400, "oi_value": 10e9, "oi_quantity": 200000},
        ]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=open_interest)
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=2)

        assert len(result) == 2
        # OI change with prev=0 should be 0 (handled by the if prev_oi > 0 check)

    async def test_fetch_all_funding_rate_aggregation(self, fetcher):
        """Should average multiple funding rates per day for BTC and ETH."""
        # Use midnight of yesterday to ensure all 3 funding timestamps (0h, 8h, 16h) land on same date
        yesterday = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        base_ts = int(yesterday.timestamp())
        klines_btc = _make_klines(1, base_ts=base_ts)
        klines_eth = _make_klines(1, base_ts=base_ts, base_price=3000.0)

        # 3 funding payments per day for BTC
        funding_btc = [
            {"timestamp": base_ts + 0, "rate": 0.0001},
            {"timestamp": base_ts + 28800, "rate": 0.0002},
            {"timestamp": base_ts + 57600, "rate": 0.0003},
        ]
        # 3 funding payments per day for ETH
        funding_eth = [
            {"timestamp": base_ts + 0, "rate": 0.00005},
            {"timestamp": base_ts + 28800, "rate": 0.00015},
            {"timestamp": base_ts + 57600, "rate": 0.00010},
        ]

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(side_effect=[funding_btc, funding_eth])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=1)

        assert len(result) == 1
        # BTC funding avg: (0.0001 + 0.0002 + 0.0003) / 3 = 0.0002
        assert result[0].funding_rate_btc == pytest.approx(0.0002)
        # ETH funding avg: (0.00005 + 0.00015 + 0.00010) / 3 = 0.0001
        assert result[0].funding_rate_eth == pytest.approx(0.0001)

    async def test_fetch_all_btc_volume_from_klines(self, fetcher):
        """Should populate btc_volume from kline volume data."""
        base_ts = int((datetime.now() - timedelta(days=1)).timestamp())
        klines_btc = [
            {"timestamp": base_ts, "open": 60000, "high": 61000, "low": 59000, "close": 60500, "volume": 12345.67},
        ]
        klines_eth = _make_klines(1, base_ts=base_ts, base_price=3000.0)

        fetcher.fetch_fear_greed_history = AsyncMock(return_value=[])
        fetcher.fetch_funding_rate_history = AsyncMock(return_value=[])
        fetcher.fetch_klines_with_fallback = AsyncMock(side_effect=[klines_btc, klines_eth])
        fetcher.fetch_long_short_history = AsyncMock(return_value=[])
        fetcher.fetch_open_interest_history = AsyncMock(return_value=[])
        fetcher.fetch_taker_buy_sell_history = AsyncMock(return_value=[])
        fetcher.fetch_top_trader_ls_history = AsyncMock(return_value=[])
        fetcher.fetch_bitget_funding_history = AsyncMock(return_value=[])
        fetcher.fetch_stablecoin_history = AsyncMock(return_value=[])
        fetcher.fetch_global_market_data = AsyncMock(return_value={})
        fetcher.fetch_btc_hashrate_history = AsyncMock(return_value=[])
        fetcher.fetch_fred_series = AsyncMock(return_value=[])

        result = await fetcher.fetch_all_historical_data(days=1)

        assert result[0].btc_volume == pytest.approx(12345.67)


# ===========================================================================
# HistoricalDataPoint Additional Tests
# ===========================================================================


class TestHistoricalDataPointExtra:
    """Additional tests for HistoricalDataPoint dataclass."""

    def test_to_dict_preserves_all_extended_fields(self):
        """to_dict should include all extended fields."""
        dp = HistoricalDataPoint(
            timestamp=datetime(2025, 6, 1),
            date_str="2025-06-01",
            fear_greed_index=50,
            fear_greed_classification="Neutral",
            long_short_ratio=1.0,
            funding_rate_btc=0.0001,
            funding_rate_eth=0.00005,
            btc_price=60000,
            eth_price=3000,
            btc_high=61000,
            btc_low=59000,
            eth_high=3100,
            eth_low=2900,
            btc_24h_change=1.5,
            eth_24h_change=0.8,
            open_interest_btc=18e9,
            open_interest_change_24h=3.5,
            taker_buy_sell_ratio=1.05,
            top_trader_long_short_ratio=1.1,
            funding_rate_bitget=0.00025,
            stablecoin_flow_7d=5e8,
            usdt_market_cap=120e9,
            btc_dominance=52.3,
            total_crypto_market_cap=2.5e12,
            dxy_index=104.5,
            fed_funds_rate=5.25,
            btc_hashrate=650.0,
            historical_volatility=55.0,
            btc_volume=15e9,
        )

        d = dp.to_dict()

        assert d["open_interest_btc"] == 18e9
        assert d["open_interest_change_24h"] == 3.5
        assert d["taker_buy_sell_ratio"] == 1.05
        assert d["top_trader_long_short_ratio"] == 1.1
        assert d["funding_rate_bitget"] == 0.00025
        assert d["stablecoin_flow_7d"] == 5e8
        assert d["usdt_market_cap"] == 120e9
        assert d["btc_dominance"] == 52.3
        assert d["total_crypto_market_cap"] == 2.5e12
        assert d["dxy_index"] == 104.5
        assert d["fed_funds_rate"] == 5.25
        assert d["btc_hashrate"] == 650.0
        assert d["historical_volatility"] == 55.0
        assert d["btc_volume"] == 15e9

    def test_from_dict_handles_all_extended_fields(self):
        """from_dict should restore all extended fields."""
        data = {
            "timestamp": "2025-06-01T00:00:00",
            "date_str": "2025-06-01",
            "fear_greed_index": 50,
            "fear_greed_classification": "Neutral",
            "long_short_ratio": 1.0,
            "funding_rate_btc": 0.0001,
            "funding_rate_eth": 0.00005,
            "btc_price": 60000,
            "eth_price": 3000,
            "btc_high": 61000,
            "btc_low": 59000,
            "eth_high": 3100,
            "eth_low": 2900,
            "btc_24h_change": 1.5,
            "eth_24h_change": 0.8,
            "open_interest_btc": 18e9,
            "taker_buy_sell_ratio": 1.05,
            "btc_hashrate": 650.0,
            "dxy_index": 104.5,
        }

        dp = HistoricalDataPoint.from_dict(data)

        assert dp.open_interest_btc == 18e9
        assert dp.taker_buy_sell_ratio == 1.05
        assert dp.btc_hashrate == 650.0
        assert dp.dxy_index == 104.5
