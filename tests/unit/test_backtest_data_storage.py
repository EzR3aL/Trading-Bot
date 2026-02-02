"""
Tests for the Parquet data storage module.
"""

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pandas as pd

from src.backtest.data_storage import ParquetDataStorage, TIMEFRAME_MINUTES


class TestParquetDataStorage:
    """Tests for ParquetDataStorage class."""

    @pytest.fixture
    def temp_storage(self, tmp_path):
        """Create a temporary storage instance."""
        return ParquetDataStorage(data_dir=str(tmp_path / "parquet"))

    @pytest.fixture
    def sample_data(self):
        """Generate sample OHLCV data."""
        base_time = int(datetime.now().timestamp()) - (86400 * 10)  # 10 days ago
        return [
            {
                "timestamp": base_time + (i * 3600),  # Hourly
                "open": 50000 + (i * 10),
                "high": 50100 + (i * 10),
                "low": 49900 + (i * 10),
                "close": 50050 + (i * 10),
                "volume": 1000 + i
            }
            for i in range(100)
        ]

    def test_save_ohlcv(self, temp_storage, sample_data):
        """Test saving OHLCV data to parquet."""
        rows = temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        assert rows == len(sample_data)
        assert temp_storage._get_file_path("BTCUSDT", "1H").exists()

    def test_load_ohlcv(self, temp_storage, sample_data):
        """Test loading OHLCV data from parquet."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        df = temp_storage.load_ohlcv("BTCUSDT", "1H")

        assert len(df) == len(sample_data)
        assert "timestamp" in df.columns
        assert "open" in df.columns
        assert "high" in df.columns
        assert "low" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns

    def test_load_ohlcv_with_date_filter(self, temp_storage, sample_data):
        """Test loading data with date filters."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        # Get middle date
        df_all = temp_storage.load_ohlcv("BTCUSDT", "1H")
        mid_date = df_all.iloc[50]["timestamp"]

        # Filter by start date
        df_filtered = temp_storage.load_ohlcv("BTCUSDT", "1H", start_date=mid_date)
        assert len(df_filtered) < len(df_all)
        assert df_filtered["timestamp"].min() >= mid_date

    def test_load_ohlcv_with_limit(self, temp_storage, sample_data):
        """Test loading data with row limit."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        df = temp_storage.load_ohlcv("BTCUSDT", "1H", limit=10)

        assert len(df) == 10

    def test_load_nonexistent_file(self, temp_storage):
        """Test loading from a file that doesn't exist."""
        df = temp_storage.load_ohlcv("NONEXISTENT", "1H")

        assert df.empty

    def test_append_data(self, temp_storage, sample_data):
        """Test appending data to existing file."""
        # Save first half
        first_half = sample_data[:50]
        temp_storage.save_ohlcv("BTCUSDT", "1H", first_half)

        # Append second half
        second_half = sample_data[50:]
        temp_storage.save_ohlcv("BTCUSDT", "1H", second_half, append=True)

        df = temp_storage.load_ohlcv("BTCUSDT", "1H")
        assert len(df) == len(sample_data)

    def test_overwrite_data(self, temp_storage, sample_data):
        """Test overwriting existing data."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        # Overwrite with new data
        new_data = sample_data[:10]
        temp_storage.save_ohlcv("BTCUSDT", "1H", new_data, append=False)

        df = temp_storage.load_ohlcv("BTCUSDT", "1H")
        assert len(df) == 10

    def test_deduplicate_on_append(self, temp_storage, sample_data):
        """Test that duplicates are removed on append."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        # Append same data again
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data, append=True)

        df = temp_storage.load_ohlcv("BTCUSDT", "1H")
        assert len(df) == len(sample_data)  # No duplicates

    def test_get_date_range(self, temp_storage, sample_data):
        """Test getting date range of stored data."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        start, end = temp_storage.get_date_range("BTCUSDT", "1H")

        assert start is not None
        assert end is not None
        assert start < end

    def test_get_date_range_no_file(self, temp_storage):
        """Test getting date range when file doesn't exist."""
        start, end = temp_storage.get_date_range("NONEXISTENT", "1H")

        assert start is None
        assert end is None

    def test_get_row_count(self, temp_storage, sample_data):
        """Test getting row count."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        count = temp_storage.get_row_count("BTCUSDT", "1H")

        assert count == len(sample_data)

    def test_list_available_data(self, temp_storage, sample_data):
        """Test listing available data files."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)
        temp_storage.save_ohlcv("ETHUSDT", "1D", sample_data)

        data_list = temp_storage.list_available_data()

        assert len(data_list) == 2
        symbols = {item["symbol"] for item in data_list}
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols

    def test_delete_data(self, temp_storage, sample_data):
        """Test deleting a data file."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)
        assert temp_storage._get_file_path("BTCUSDT", "1H").exists()

        result = temp_storage.delete_data("BTCUSDT", "1H")

        assert result is True
        assert not temp_storage._get_file_path("BTCUSDT", "1H").exists()

    def test_delete_nonexistent_data(self, temp_storage):
        """Test deleting a file that doesn't exist."""
        result = temp_storage.delete_data("NONEXISTENT", "1H")

        assert result is False

    def test_calculate_indicators(self, temp_storage, sample_data):
        """Test calculating technical indicators."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)
        df = temp_storage.load_ohlcv("BTCUSDT", "1H")

        df_with_indicators = temp_storage.calculate_indicators(df)

        # Check indicator columns exist
        assert "sma_20" in df_with_indicators.columns
        assert "sma_50" in df_with_indicators.columns
        assert "ema_12" in df_with_indicators.columns
        assert "macd" in df_with_indicators.columns
        assert "rsi" in df_with_indicators.columns
        assert "bb_upper" in df_with_indicators.columns
        assert "bb_lower" in df_with_indicators.columns
        assert "atr" in df_with_indicators.columns

    def test_resample_timeframe(self, temp_storage, sample_data):
        """Test resampling from lower to higher timeframe."""
        temp_storage.save_ohlcv("BTCUSDT", "1H", sample_data)

        df_4h = temp_storage.resample_timeframe("BTCUSDT", "1H", "4H")

        # 100 hourly candles should result in ~25 4-hour candles
        assert len(df_4h) < len(sample_data)
        assert len(df_4h) > 0

    def test_resample_invalid_direction(self, temp_storage, sample_data):
        """Test resampling with invalid direction raises error."""
        temp_storage.save_ohlcv("BTCUSDT", "1D", sample_data)

        with pytest.raises(ValueError):
            # Can't resample from 1D to 1H
            temp_storage.resample_timeframe("BTCUSDT", "1D", "1H")


class TestTimeframeMinutes:
    """Tests for timeframe configuration."""

    def test_all_timeframes_defined(self):
        """Test that all supported timeframes have minute values."""
        expected_timeframes = ["1m", "5m", "15m", "30m", "1H", "4H", "1D"]

        for tf in expected_timeframes:
            assert tf in TIMEFRAME_MINUTES
            assert TIMEFRAME_MINUTES[tf] > 0

    def test_timeframe_ordering(self):
        """Test that timeframes are ordered correctly."""
        assert TIMEFRAME_MINUTES["1m"] < TIMEFRAME_MINUTES["5m"]
        assert TIMEFRAME_MINUTES["5m"] < TIMEFRAME_MINUTES["15m"]
        assert TIMEFRAME_MINUTES["15m"] < TIMEFRAME_MINUTES["30m"]
        assert TIMEFRAME_MINUTES["30m"] < TIMEFRAME_MINUTES["1H"]
        assert TIMEFRAME_MINUTES["1H"] < TIMEFRAME_MINUTES["4H"]
        assert TIMEFRAME_MINUTES["4H"] < TIMEFRAME_MINUTES["1D"]
