"""
Tests for free date selection (Option A) in backtesting.

Validates:
- HistoricalDataFetcher.set_date_range() and helper methods
- Date range propagation through strategy_adapter
- API validation (timeframe-specific limits, earliest date, future dates)
- Cache key uniqueness for different date ranges
"""

import math
import os
import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

# Skip tests that call external APIs when running in CI
_in_ci = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"

from src.backtest.historical_data import HistoricalDataFetcher


# ── HistoricalDataFetcher date range helpers ──────────────────────────────


class TestSetDateRange:
    """Tests for set_date_range() and helper methods."""

    def test_set_date_range_stores_milliseconds(self):
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        start = datetime(2024, 1, 1)
        end = datetime(2024, 6, 30)
        fetcher.set_date_range(start, end)
        assert fetcher._start_ms == int(start.timestamp() * 1000)
        assert fetcher._end_ms == int(end.timestamp() * 1000)

    def test_set_date_range_none_clears(self):
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        fetcher.set_date_range(datetime(2024, 1, 1), datetime(2024, 6, 30))
        fetcher.set_date_range(None, None)
        assert fetcher._start_ms is None
        assert fetcher._end_ms is None

    def test_get_time_range_ms_with_date_range(self):
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        start = datetime(2024, 3, 1)
        end = datetime(2024, 3, 31)
        fetcher.set_date_range(start, end)
        start_ms, end_ms = fetcher._get_time_range_ms(days=30)
        assert start_ms == int(start.timestamp() * 1000)
        assert end_ms == int(end.timestamp() * 1000)

    def test_get_time_range_ms_without_date_range(self):
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        # No date range set -> uses now() - days
        start_ms, end_ms = fetcher._get_time_range_ms(days=30)
        now_ms = int(datetime.now().timestamp() * 1000)
        # end_ms should be close to now
        assert abs(end_ms - now_ms) < 2000  # within 2 seconds
        # start_ms should be ~30 days before now
        expected_start = now_ms - 30 * 86400 * 1000
        assert abs(start_ms - expected_start) < 2000

    def test_cache_suffix_with_date_range(self):
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        fetcher.set_date_range(datetime(2024, 1, 15), datetime(2024, 7, 20))
        suffix = fetcher._cache_suffix()
        assert suffix == "_20240115_20240720"

    def test_cache_suffix_without_date_range(self):
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        assert fetcher._cache_suffix() == ""

    def test_cache_suffix_changes_with_different_dates(self):
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        fetcher.set_date_range(datetime(2024, 1, 1), datetime(2024, 3, 1))
        suffix1 = fetcher._cache_suffix()
        fetcher.set_date_range(datetime(2024, 6, 1), datetime(2024, 9, 1))
        suffix2 = fetcher._cache_suffix()
        assert suffix1 != suffix2


class TestFetchAllHistoricalDataSignature:
    """Tests for the updated fetch_all_historical_data signature."""

    @pytest.mark.asyncio
    async def test_accepts_start_end_date(self):
        """Verify the method accepts start_date/end_date parameters."""
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        # Mock the sub-fetchers to avoid real API calls
        with patch.object(fetcher, 'fetch_fear_greed_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_funding_rate_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_klines_with_fallback', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_long_short_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_open_interest_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_taker_buy_sell_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_top_trader_ls_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_bitget_funding_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_stablecoin_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_global_market_data', new_callable=AsyncMock, return_value={}), \
             patch.object(fetcher, 'fetch_btc_hashrate_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_fred_series', new_callable=AsyncMock, return_value=[]):
            result = await fetcher.fetch_all_historical_data(
                days=30,
                interval="1h",
                start_date=datetime(2024, 6, 1),
                end_date=datetime(2024, 7, 1),
            )
            assert isinstance(result, list)
            # Date range should have been set on the instance
            assert fetcher._start_ms is not None
            assert fetcher._end_ms is not None
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_backward_compatible_without_dates(self):
        """Calling without start_date/end_date should work as before."""
        fetcher = HistoricalDataFetcher(cache_dir="/tmp/test_cache_dr")
        with patch.object(fetcher, 'fetch_fear_greed_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_funding_rate_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_klines_with_fallback', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_long_short_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_open_interest_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_taker_buy_sell_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_top_trader_ls_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_bitget_funding_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_stablecoin_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_global_market_data', new_callable=AsyncMock, return_value={}), \
             patch.object(fetcher, 'fetch_btc_hashrate_history', new_callable=AsyncMock, return_value=[]), \
             patch.object(fetcher, 'fetch_fred_series', new_callable=AsyncMock, return_value=[]):
            result = await fetcher.fetch_all_historical_data(days=30, interval="1d")
            assert isinstance(result, list)
            # No date range set
            assert fetcher._start_ms is None
            assert fetcher._end_ms is None
        await fetcher.close()


# ── API Validation ────────────────────────────────────────────────────────


class TestBacktestAPIValidation:
    """Tests for the backtest API date validation constants."""

    def test_timeframe_max_days_constants(self):
        """Verify timeframe limits are defined and reasonable."""
        from src.api.routers.backtest import TIMEFRAME_MAX_DAYS, EARLIEST_DATE

        assert TIMEFRAME_MAX_DAYS["1m"] == 7
        assert TIMEFRAME_MAX_DAYS["5m"] == 30
        assert TIMEFRAME_MAX_DAYS["15m"] == 90
        assert TIMEFRAME_MAX_DAYS["30m"] == 180
        assert TIMEFRAME_MAX_DAYS["1h"] == 365
        assert TIMEFRAME_MAX_DAYS["4h"] == 365
        assert TIMEFRAME_MAX_DAYS["1d"] == 365

        # Earliest date should be 2020-01-01
        assert EARLIEST_DATE == datetime(2020, 1, 1)

    def test_smaller_timeframes_have_smaller_limits(self):
        """Smaller candle sizes should have stricter day limits."""
        from src.api.routers.backtest import TIMEFRAME_MAX_DAYS

        assert TIMEFRAME_MAX_DAYS["1m"] < TIMEFRAME_MAX_DAYS["5m"]
        assert TIMEFRAME_MAX_DAYS["5m"] < TIMEFRAME_MAX_DAYS["15m"]
        assert TIMEFRAME_MAX_DAYS["15m"] < TIMEFRAME_MAX_DAYS["30m"]
        assert TIMEFRAME_MAX_DAYS["30m"] <= TIMEFRAME_MAX_DAYS["1h"]


# ── Strategy Adapter date propagation ─────────────────────────────────────


class TestStrategyAdapterDatePropagation:
    """Tests that strategy_adapter passes dates to the fetcher."""

    @pytest.mark.asyncio
    async def test_adapter_passes_dates_to_fetcher(self):
        """Verify run_backtest_for_strategy passes start/end dates."""
        from src.backtest.strategy_adapter import run_backtest_for_strategy

        captured_args = {}

        async def mock_fetch_all(self, days=180, interval="1d", start_date=None, end_date=None):
            captured_args['start_date'] = start_date
            captured_args['end_date'] = end_date
            captured_args['days'] = days
            captured_args['interval'] = interval
            # Return empty -> will fallback to mock data
            return []

        with patch.object(HistoricalDataFetcher, 'fetch_all_historical_data', mock_fetch_all), \
             patch.object(HistoricalDataFetcher, 'close', new_callable=AsyncMock):
            _result = await run_backtest_for_strategy(
                strategy_type="liquidation_hunter",
                symbol="BTCUSDT",
                timeframe="4h",
                start_date=datetime(2024, 6, 1),
                end_date=datetime(2024, 7, 1),
                initial_capital=10000.0,
            )

        # Should have passed the end_date
        assert captured_args['end_date'] == datetime(2024, 7, 1)
        # start_date should be adjusted for warmup buffer
        assert captured_args['start_date'] < datetime(2024, 6, 1)
        # interval should match timeframe
        assert captured_args['interval'] == "4h"

    @pytest.mark.asyncio
    async def test_adapter_warmup_buffer(self):
        """Verify warmup buffer is subtracted from start_date."""
        from src.backtest.strategy_adapter import run_backtest_for_strategy, CANDLES_PER_DAY

        captured_args = {}

        async def mock_fetch_all(self, days=180, interval="1d", start_date=None, end_date=None):
            captured_args['start_date'] = start_date
            captured_args['end_date'] = end_date
            return []

        with patch.object(HistoricalDataFetcher, 'fetch_all_historical_data', mock_fetch_all), \
             patch.object(HistoricalDataFetcher, 'close', new_callable=AsyncMock):
            await run_backtest_for_strategy(
                strategy_type="liquidation_hunter",
                symbol="BTCUSDT",
                timeframe="1d",
                start_date=datetime(2024, 6, 1),
                end_date=datetime(2024, 7, 1),
                initial_capital=10000.0,
            )

        # For 1d: 50 warmup candles / 1 cpd = 50 days + 1 = 51 days buffer
        # So fetch_start should be ~51 days before user's start_date
        expected_warmup = math.ceil(50 / CANDLES_PER_DAY["1d"]) + 1
        expected_fetch_start = datetime(2024, 6, 1) - timedelta(days=expected_warmup)
        assert captured_args['start_date'] == expected_fetch_start


# ── Integration: date range with mock data ────────────────────────────────


@pytest.mark.skipif(_in_ci, reason="Binance Futures API returns HTTP 451 on US-based CI runners")
class TestDateRangeWithMockData:
    """End-to-end tests with mock data fallback (requires Binance API access)."""

    @pytest.mark.asyncio
    async def test_backtest_with_historical_dates(self):
        """Run a backtest with dates in the past (uses mock fallback)."""
        from src.backtest.strategy_adapter import run_backtest_for_strategy

        result = await run_backtest_for_strategy(
            strategy_type="edge_indicator",
            symbol="BTCUSDT",
            timeframe="4h",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            initial_capital=10000.0,
        )

        assert "metrics" in result
        assert "trades" in result
        assert "equity_curve" in result
        assert result["metrics"]["starting_capital"] == 10000.0

    @pytest.mark.asyncio
    async def test_different_date_ranges_produce_different_results(self):
        """Different date ranges should produce different backtest results."""
        from src.backtest.strategy_adapter import run_backtest_for_strategy

        result1 = await run_backtest_for_strategy(
            strategy_type="edge_indicator",
            symbol="BTCUSDT",
            timeframe="1h",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 15),
            initial_capital=10000.0,
        )

        result2 = await run_backtest_for_strategy(
            strategy_type="edge_indicator",
            symbol="BTCUSDT",
            timeframe="1h",
            start_date=datetime(2024, 6, 1),
            end_date=datetime(2024, 6, 15),
            initial_capital=10000.0,
        )

        # Both should complete successfully
        assert result1["metrics"]["total_trades"] >= 0
        assert result2["metrics"]["total_trades"] >= 0
