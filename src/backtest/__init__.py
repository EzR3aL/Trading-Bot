"""
Backtesting module for the Contrarian Liquidation Hunter Strategy.

This module provides:
- Historical data fetching and caching
- Backtest engine for strategy simulation
- Performance reporting and analysis
- Parquet-based data storage for efficiency
- Multi-timeframe support (1m, 5m, 15m, 30m, 1H, 4H, 1D)
"""

from src.backtest.historical_data import HistoricalDataFetcher, HistoricalDataPoint
from src.backtest.engine import BacktestEngine, BacktestTrade
from src.backtest.report import BacktestReport, BacktestResult
from src.backtest.data_storage import ParquetDataStorage, BinanceDataDownloader

__all__ = [
    "HistoricalDataFetcher",
    "HistoricalDataPoint",
    "BacktestEngine",
    "BacktestTrade",
    "BacktestReport",
    "BacktestResult",
    "ParquetDataStorage",
    "BinanceDataDownloader",
]
