"""
Historical Data Storage with Parquet Format.

Efficient storage and retrieval of historical market data using Apache Parquet.
Supports multiple timeframes and symbols.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Literal

import pandas as pd
import numpy as np

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Supported timeframes
Timeframe = Literal["1m", "5m", "15m", "30m", "1H", "4H", "1D"]

TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "4H": 240,
    "1D": 1440,
}


class ParquetDataStorage:
    """
    Efficient storage for historical market data using Parquet format.

    Features:
    - Columnar storage for fast analytics
    - Compression (snappy by default)
    - Partitioned by symbol and timeframe
    - Supports multiple timeframes (1m, 5m, 15m, 30m, 1H, 4H, 1D)
    """

    def __init__(self, data_dir: str = "data/backtest/parquet"):
        """
        Initialize the data storage.

        Args:
            data_dir: Base directory for parquet files
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, symbol: str, timeframe: Timeframe) -> Path:
        """Get the parquet file path for a symbol and timeframe."""
        return self.data_dir / f"{symbol}_{timeframe}.parquet"

    def save_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        data: List[Dict],
        append: bool = True
    ) -> int:
        """
        Save OHLCV data to parquet file.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            timeframe: Candle timeframe
            data: List of OHLCV dicts with keys: timestamp, open, high, low, close, volume
            append: If True, append to existing data; if False, overwrite

        Returns:
            Number of rows saved
        """
        if not data:
            return 0

        # Convert to DataFrame
        df = pd.DataFrame(data)

        # Ensure proper column types
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)

        # Sort by timestamp
        df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp'])

        file_path = self._get_file_path(symbol, timeframe)

        if append and file_path.exists():
            # Load existing data and merge
            existing_df = pd.read_parquet(file_path)
            df = pd.concat([existing_df, df]).drop_duplicates(subset=['timestamp'])
            df = df.sort_values('timestamp')

        # Save with snappy compression
        df.to_parquet(file_path, compression='snappy', index=False)

        logger.info(f"Saved {len(df)} rows to {file_path}")
        return len(df)

    def load_ohlcv(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Load OHLCV data from parquet file.

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            start_date: Filter data after this date
            end_date: Filter data before this date
            limit: Maximum number of rows to return

        Returns:
            DataFrame with OHLCV data
        """
        file_path = self._get_file_path(symbol, timeframe)

        if not file_path.exists():
            logger.warning(f"No data file found: {file_path}")
            return pd.DataFrame()

        df = pd.read_parquet(file_path)

        # Apply date filters
        if start_date:
            df = df[df['timestamp'] >= start_date]
        if end_date:
            df = df[df['timestamp'] <= end_date]

        # Apply limit
        if limit:
            df = df.tail(limit)

        return df

    def get_date_range(self, symbol: str, timeframe: Timeframe) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Get the date range of stored data."""
        file_path = self._get_file_path(symbol, timeframe)

        if not file_path.exists():
            return None, None

        df = pd.read_parquet(file_path, columns=['timestamp'])

        if df.empty:
            return None, None

        return df['timestamp'].min(), df['timestamp'].max()

    def get_row_count(self, symbol: str, timeframe: Timeframe) -> int:
        """Get the number of rows in the data file."""
        file_path = self._get_file_path(symbol, timeframe)

        if not file_path.exists():
            return 0

        return len(pd.read_parquet(file_path))

    def list_available_data(self) -> List[Dict]:
        """List all available data files with metadata."""
        result = []

        for file_path in self.data_dir.glob("*.parquet"):
            parts = file_path.stem.split("_")
            if len(parts) >= 2:
                symbol = parts[0]
                timeframe = parts[1]

                start_date, end_date = self.get_date_range(symbol, timeframe)
                row_count = self.get_row_count(symbol, timeframe)
                file_size = file_path.stat().st_size / (1024 * 1024)  # MB

                result.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "rows": row_count,
                    "size_mb": round(file_size, 2)
                })

        return result

    def resample_timeframe(
        self,
        symbol: str,
        source_timeframe: Timeframe,
        target_timeframe: Timeframe
    ) -> pd.DataFrame:
        """
        Resample data from a lower timeframe to a higher timeframe.

        Args:
            symbol: Trading pair
            source_timeframe: Original timeframe (must be lower)
            target_timeframe: Target timeframe (must be higher)

        Returns:
            Resampled DataFrame
        """
        source_minutes = TIMEFRAME_MINUTES.get(source_timeframe, 1)
        target_minutes = TIMEFRAME_MINUTES.get(target_timeframe, 1)

        if target_minutes <= source_minutes:
            raise ValueError(f"Target timeframe {target_timeframe} must be higher than source {source_timeframe}")

        df = self.load_ohlcv(symbol, source_timeframe)

        if df.empty:
            return df

        # Set timestamp as index for resampling
        df = df.set_index('timestamp')

        # Map timeframe to pandas frequency
        freq_map = {
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1H": "1h",
            "4H": "4h",
            "1D": "1D",
        }

        freq = freq_map.get(target_timeframe, "1h")

        # Resample OHLCV
        resampled = df.resample(freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        return resampled.reset_index()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add common technical indicators to the DataFrame.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            DataFrame with added indicators
        """
        df = df.copy()

        # Simple Moving Averages
        df['sma_20'] = df['close'].rolling(window=20).mean()
        df['sma_50'] = df['close'].rolling(window=50).mean()
        df['sma_200'] = df['close'].rolling(window=200).mean()

        # Exponential Moving Averages
        df['ema_12'] = df['close'].ewm(span=12).mean()
        df['ema_26'] = df['close'].ewm(span=26).mean()

        # MACD
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)

        # ATR (Average True Range)
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()

        # Price change percentage
        df['pct_change'] = df['close'].pct_change() * 100

        # Volatility (20-period)
        df['volatility'] = df['pct_change'].rolling(window=20).std()

        return df

    def delete_data(self, symbol: str, timeframe: Timeframe) -> bool:
        """Delete a data file."""
        file_path = self._get_file_path(symbol, timeframe)

        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted {file_path}")
            return True

        return False


class BinanceDataDownloader:
    """
    Downloads historical data from Binance public data repository.

    Uses data.binance.vision for bulk historical downloads (free, no API key required).
    """

    BASE_URL = "https://data.binance.vision/data/futures/um"

    def __init__(self, storage: ParquetDataStorage):
        """
        Initialize the downloader.

        Args:
            storage: ParquetDataStorage instance for saving data
        """
        self.storage = storage

    async def download_klines(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        progress_callback: Optional[callable] = None
    ) -> int:
        """
        Download kline data from Binance data repository.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            timeframe: Candle timeframe
            start_date: Start date
            end_date: End date (defaults to now)
            progress_callback: Optional callback for progress updates

        Returns:
            Total number of rows downloaded
        """
        import aiohttp
        import zipfile
        import io

        if end_date is None:
            end_date = datetime.now()

        # Map timeframe to Binance interval
        interval_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1H": "1h",
            "4H": "4h",
            "1D": "1d",
        }
        interval = interval_map.get(timeframe, "1h")

        total_rows = 0
        current_date = start_date

        async with aiohttp.ClientSession() as session:
            while current_date <= end_date:
                # Try monthly first, then daily
                year = current_date.year
                month = current_date.month

                # Monthly URL
                url = f"{self.BASE_URL}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip"

                try:
                    async with session.get(url, timeout=60) as response:
                        if response.status == 200:
                            content = await response.read()

                            # Extract CSV from zip
                            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                                csv_name = zf.namelist()[0]
                                with zf.open(csv_name) as f:
                                    df = pd.read_csv(f, header=None)

                            # Parse columns (Binance format)
                            # 0: Open time, 1: Open, 2: High, 3: Low, 4: Close, 5: Volume, ...
                            data = []
                            for _, row in df.iterrows():
                                data.append({
                                    "timestamp": int(row[0]) // 1000,
                                    "open": float(row[1]),
                                    "high": float(row[2]),
                                    "low": float(row[3]),
                                    "close": float(row[4]),
                                    "volume": float(row[5]),
                                })

                            rows_saved = self.storage.save_ohlcv(symbol, timeframe, data)
                            total_rows += rows_saved

                            if progress_callback:
                                progress_callback(f"Downloaded {year}-{month:02d}: {rows_saved} rows")

                            logger.info(f"Downloaded {symbol} {timeframe} {year}-{month:02d}: {rows_saved} rows")
                        else:
                            logger.warning(f"No data for {symbol} {timeframe} {year}-{month:02d}")

                except Exception as e:
                    logger.error(f"Error downloading {symbol} {timeframe} {year}-{month:02d}: {e}")

                # Move to next month
                if month == 12:
                    current_date = datetime(year + 1, 1, 1)
                else:
                    current_date = datetime(year, month + 1, 1)

        return total_rows
