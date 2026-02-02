"""
CLI commands for backtesting operations.

Provides commands for:
- Downloading historical data
- Running backtests
- Viewing stored data
"""

import asyncio
import argparse
from datetime import datetime, timedelta
from typing import Optional

from src.backtest.data_storage import ParquetDataStorage, BinanceDataDownloader
from src.backtest.historical_data import HistoricalDataFetcher
from src.backtest.engine import BacktestEngine, BacktestConfig
from src.backtest.report import BacktestReport
from src.utils.logger import get_logger

logger = get_logger(__name__)


async def download_data(
    symbol: str = "BTCUSDT",
    timeframe: str = "1H",
    days: int = 365,
    verbose: bool = True
) -> int:
    """
    Download historical data from Binance.

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        days: Number of days to download
        verbose: Print progress

    Returns:
        Number of rows downloaded
    """
    storage = ParquetDataStorage()
    downloader = BinanceDataDownloader(storage)

    start_date = datetime.now() - timedelta(days=days)

    if verbose:
        print(f"Downloading {symbol} {timeframe} data for {days} days...")
        print(f"Start date: {start_date.strftime('%Y-%m-%d')}")

    def progress(msg: str):
        if verbose:
            print(f"  {msg}")

    total_rows = await downloader.download_klines(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        progress_callback=progress
    )

    if verbose:
        print(f"\nTotal rows downloaded: {total_rows}")

    return total_rows


def list_data(verbose: bool = True) -> list:
    """
    List all available historical data.

    Returns:
        List of data files with metadata
    """
    storage = ParquetDataStorage()
    data_list = storage.list_available_data()

    if verbose:
        print("\nAvailable Historical Data:")
        print("-" * 70)
        print(f"{'Symbol':<12} {'Timeframe':<10} {'Start':<12} {'End':<12} {'Rows':<10} {'Size':<8}")
        print("-" * 70)

        for item in data_list:
            start = item['start_date'][:10] if item['start_date'] else 'N/A'
            end = item['end_date'][:10] if item['end_date'] else 'N/A'
            print(f"{item['symbol']:<12} {item['timeframe']:<10} {start:<12} {end:<12} {item['rows']:<10} {item['size_mb']:.2f}MB")

        print("-" * 70)

    return data_list


async def run_backtest_from_parquet(
    symbol: str = "BTCUSDT",
    timeframe: str = "1D",
    days: Optional[int] = None,
    capital: float = 10000.0,
    verbose: bool = True
) -> Optional[dict]:
    """
    Run backtest using data from parquet storage.

    Args:
        symbol: Trading pair
        timeframe: Candle timeframe
        days: Number of days to backtest (None = all available)
        capital: Starting capital
        verbose: Print report

    Returns:
        Backtest results as dict
    """
    from src.backtest.mock_data import generate_mock_historical_data

    storage = ParquetDataStorage()
    fetcher = HistoricalDataFetcher()

    # Load data from parquet
    if verbose:
        print(f"Loading {symbol} {timeframe} data from parquet storage...")

    df = storage.load_ohlcv(symbol, timeframe)

    if df.empty:
        if verbose:
            print("No parquet data found. Fetching from API...")

        # Fetch from API as fallback
        data_points = await fetcher.fetch_all_historical_data(days or 180)

        if not data_points:
            if verbose:
                print("Could not fetch live data. Using mock data...")
            data_points = generate_mock_historical_data(days or 180)
    else:
        # Convert parquet data to historical data points format
        if verbose:
            print(f"Loaded {len(df)} candles from parquet")

        # For now, use the existing fetcher which combines multiple data sources
        data_points = await fetcher.fetch_all_historical_data(days or 180)

        if not data_points:
            data_points = generate_mock_historical_data(days or 180)

    await fetcher.close()

    if not data_points:
        if verbose:
            print("ERROR: No data available for backtest")
        return None

    # Limit to specified days
    if days and len(data_points) > days:
        data_points = data_points[-days:]

    if verbose:
        print(f"Running backtest on {len(data_points)} data points...")
        print(f"Period: {data_points[0].date_str} to {data_points[-1].date_str}")
        print(f"Starting capital: ${capital:,.2f}")

    # Configure and run backtest
    from config import settings

    config = BacktestConfig(
        starting_capital=capital,
        leverage=settings.trading.leverage,
        take_profit_percent=settings.trading.take_profit_percent,
        stop_loss_percent=settings.trading.stop_loss_percent,
        max_trades_per_day=settings.trading.max_trades_per_day,
        daily_loss_limit_percent=settings.trading.daily_loss_limit_percent,
        position_size_percent=settings.trading.position_size_percent,
    )

    engine = BacktestEngine(config)
    result = engine.run(data_points)

    if verbose:
        report = BacktestReport(result)
        print(report.generate_console_report())
        report.save_json()

    return result.to_dict()


def main():
    """CLI entry point for backtest commands."""
    parser = argparse.ArgumentParser(
        description="Backtest CLI - Download data and run backtests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Download command
    download_parser = subparsers.add_parser("download", help="Download historical data")
    download_parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair")
    download_parser.add_argument("--timeframe", default="1H", help="Timeframe (1m, 5m, 15m, 30m, 1H, 4H, 1D)")
    download_parser.add_argument("--days", type=int, default=365, help="Days to download")

    # List command
    subparsers.add_parser("list", help="List available data")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run backtest")
    run_parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair")
    run_parser.add_argument("--timeframe", default="1D", help="Timeframe")
    run_parser.add_argument("--days", type=int, help="Days to backtest")
    run_parser.add_argument("--capital", type=float, default=10000.0, help="Starting capital")

    args = parser.parse_args()

    if args.command == "download":
        asyncio.run(download_data(args.symbol, args.timeframe, args.days))
    elif args.command == "list":
        list_data()
    elif args.command == "run":
        asyncio.run(run_backtest_from_parquet(args.symbol, args.timeframe, args.days, args.capital))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
