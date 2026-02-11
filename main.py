#!/usr/bin/env python3
"""
DEPRECATED CLI entry point. The web UI uses BotOrchestrator + BotWorker (v3.0.0+).
This file is kept for standalone CLI usage only (--test, --status, --backtest).

Bitget Trading Bot - Main Entry Point

Contrarian Liquidation Hunter Strategy
=====================================

This bot implements a sophisticated trading strategy that acts as an
"Institutional Market Maker" by betting against the crowd when leverage
and sentiment reach extreme levels.

Key Features:
- Monitors Fear & Greed Index, Long/Short Ratio, and Funding Rates
- Executes contrarian trades during extreme market conditions
- Risk management with daily loss limits and position sizing
- Discord notifications for all trade activities
- Persistent trade tracking with SQLite database

Usage:
    python main.py              # Run the bot
    python main.py --test       # Run a single analysis cycle (no trading)
    python main.py --status     # Show current bot status
    python main.py --backtest   # Run backtest on historical data

Requirements:
    - Python 3.10+
    - Bitget API credentials in .env file
    - Discord webhook URL for notifications

Author: Trading Bot Team
Version: 1.0.0
"""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.bot.trading_bot import TradingBot
from src.utils.logger import setup_logging, get_logger
from config import settings


# Global bot instance for signal handling
bot: TradingBot = None
logger = get_logger(__name__)


def handle_shutdown(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    if bot:
        asyncio.create_task(bot.stop())


async def run_bot():
    """Run the trading bot."""
    global bot

    bot = TradingBot()

    # Initialize
    success = await bot.initialize()
    if not success:
        logger.error("Failed to initialize bot")
        return 1

    # Start the bot
    await bot.start()
    return 0


async def run_test():
    """Run a single analysis cycle for testing."""
    logger.info("Running test analysis...")

    bot = TradingBot()
    await bot.initialize()

    signals = await bot.run_once()

    print("\n" + "=" * 60)
    print("TEST ANALYSIS RESULTS")
    print("=" * 60)

    for signal in signals:
        print(f"\nSymbol: {signal.symbol}")
        print(f"Direction: {signal.direction.value.upper()}")
        print(f"Confidence: {signal.confidence}%")
        print(f"Entry Price: ${signal.entry_price:,.2f}")
        print(f"Take Profit: ${signal.target_price:,.2f}")
        print(f"Stop Loss: ${signal.stop_loss:,.2f}")
        print(f"Reason: {signal.reason}")
        print("-" * 40)

    await bot.stop()
    return 0


async def show_status():
    """Show current bot status and statistics."""
    from src.models.trade_database import TradeDatabase
    from src.risk.risk_manager import RiskManager

    print("\n" + "=" * 60)
    print("TRADING BOT STATUS")
    print("=" * 60)

    # Configuration
    print("\nConfiguration:")
    print(f"  Trading Pairs: {', '.join(settings.trading.trading_pairs)}")
    print(f"  Max Trades/Day: {settings.trading.max_trades_per_day}")
    print(f"  Daily Loss Limit: {settings.trading.daily_loss_limit_percent}%")
    print(f"  Position Size: {settings.trading.position_size_percent}%")
    print(f"  Leverage: {settings.trading.leverage}x")
    print(f"  Take Profit: {settings.trading.take_profit_percent}%")
    print(f"  Stop Loss: {settings.trading.stop_loss_percent}%")

    # Strategy thresholds
    print("\nStrategy Thresholds:")
    print(f"  Fear & Greed Extreme Fear: <{settings.strategy.fear_greed_extreme_fear}")
    print(f"  Fear & Greed Extreme Greed: >{settings.strategy.fear_greed_extreme_greed}")
    print(f"  L/S Crowded Longs: >{settings.strategy.long_short_crowded_longs}")
    print(f"  L/S Crowded Shorts: <{settings.strategy.long_short_crowded_shorts}")
    print(f"  High Confidence: >={settings.strategy.high_confidence_min}%")
    print(f"  Low Confidence: >={settings.strategy.low_confidence_min}%")

    # Trade statistics
    trade_db = TradeDatabase()
    await trade_db.initialize()
    stats = await trade_db.get_statistics(30)

    print("\n30-Day Statistics:")
    print(f"  Total Trades: {stats['total_trades']}")
    print(f"  Win Rate: {stats['win_rate']:.1f}%")
    print(f"  Total PnL: ${stats['total_pnl']:,.2f}")
    print(f"  Total Fees: ${stats['total_fees']:.2f}")
    print(f"  Net PnL: ${stats['net_pnl']:,.2f}")
    print(f"  Best Trade: ${stats['best_trade']:,.2f}")
    print(f"  Worst Trade: ${stats['worst_trade']:,.2f}")

    # Daily stats
    risk_manager = RiskManager()
    daily = risk_manager.get_daily_stats()
    if daily:
        print(f"\nToday's Stats:")
        print(f"  Trades: {daily.trades_executed}/{settings.trading.max_trades_per_day}")
        print(f"  Win/Loss: {daily.winning_trades}/{daily.losing_trades}")
        print(f"  PnL: ${daily.net_pnl:,.2f} ({daily.return_percent:+.2f}%)")
        print(f"  Trading Halted: {'Yes' if daily.is_trading_halted else 'No'}")

    print("\n" + "=" * 60)
    return 0


async def run_backtest(days: int = 180, capital: float = 10000.0):
    """Run backtest on historical data."""
    from src.backtest.historical_data import HistoricalDataFetcher
    from src.backtest.engine import BacktestEngine, BacktestConfig
    from src.backtest.report import BacktestReport
    from src.backtest.mock_data import generate_mock_historical_data, get_mock_data_summary

    print("\n" + "=" * 70)
    print("BACKTESTING - Contrarian Liquidation Hunter Strategy")
    print("=" * 70)
    print(f"\nPeriod: Last {days} days")
    print(f"Starting Capital: ${capital:,.2f}")
    print(f"Leverage: {settings.trading.leverage}x")
    print("\nFetching historical data...")

    # Fetch historical data
    fetcher = HistoricalDataFetcher()
    try:
        data_points = await fetcher.fetch_all_historical_data(days)

        if not data_points:
            print("Could not fetch live data. Using simulated historical data...")
            data_points = generate_mock_historical_data(days)
            summary = get_mock_data_summary(data_points)
            print(f"\nSimulated Data Summary:")
            print(f"  Period: {summary['period']}")
            print(f"  BTC Range: ${summary['btc_min']:,.0f} - ${summary['btc_max']:,.0f}")
            print(f"  Extreme Fear Days: {summary['extreme_fear_days']}")
            print(f"  Extreme Greed Days: {summary['extreme_greed_days']}")
            print(f"  Crowded Long Days: {summary['crowded_long_days']}")
            print(f"  Crowded Short Days: {summary['crowded_short_days']}")

        if not data_points:
            print("ERROR: Could not fetch historical data")
            return 1

        print(f"Loaded {len(data_points)} data points")
        print("\nRunning backtest simulation...")

        # Configure backtest
        config = BacktestConfig(
            starting_capital=capital,
            leverage=settings.trading.leverage,
            take_profit_percent=settings.trading.take_profit_percent,
            stop_loss_percent=settings.trading.stop_loss_percent,
            max_trades_per_day=settings.trading.max_trades_per_day,
            daily_loss_limit_percent=settings.trading.daily_loss_limit_percent,
            position_size_percent=settings.trading.position_size_percent,
            fear_greed_extreme_fear=settings.strategy.fear_greed_extreme_fear,
            fear_greed_extreme_greed=settings.strategy.fear_greed_extreme_greed,
            long_short_crowded_longs=settings.strategy.long_short_crowded_longs,
            long_short_crowded_shorts=settings.strategy.long_short_crowded_shorts,
            funding_rate_high=settings.strategy.funding_rate_high,
            funding_rate_low=settings.strategy.funding_rate_low,
            high_confidence_min=settings.strategy.high_confidence_min,
            low_confidence_min=settings.strategy.low_confidence_min,
            enable_profit_lock=True,
            profit_lock_percent=75.0,
            min_profit_floor=0.5,
        )

        # Run backtest
        engine = BacktestEngine(config)
        result = engine.run(data_points)

        # Generate report
        report = BacktestReport(result)
        print(report.generate_console_report())

        # Save results
        report.save_json()
        print(f"\nDetailed results saved to: data/backtest/results.json")

        # Save data points for reference
        fetcher.save_data_points(data_points)

        return 0

    finally:
        await fetcher.close()


async def create_admin(username: str, password: str):
    """Create an admin user."""
    from src.models.session import init_db, close_db, get_session
    from src.models.database import User
    from src.auth.password import hash_password
    from sqlalchemy import select

    await init_db()

    try:
        async with get_session() as session:
            # Check if user exists
            result = await session.execute(
                select(User).where(User.username == username)
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"User '{username}' already exists!")
                return 1

            user = User(
                username=username,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
                language="de",
            )
            session.add(user)

        print(f"Admin user '{username}' created successfully!")
        return 0
    finally:
        await close_db()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Bitget Trading Bot - Contrarian Liquidation Hunter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                         Run the trading bot
  python main.py --test                  Run analysis without trading
  python main.py --status                Show current status and statistics
  python main.py --backtest              Run 6-month backtest with $10,000
  python main.py --dashboard             Start web dashboard at http://localhost:8080
  python main.py --dashboard --dashboard-port 3000

For more information, see the README.md file.
        """,
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Run a single analysis cycle without executing trades",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current bot status and statistics",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Set logging level (default: INFO)",
    )

    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run backtest on historical data",
    )

    parser.add_argument(
        "--backtest-days",
        type=int,
        default=180,
        help="Number of days for backtest (default: 180)",
    )

    parser.add_argument(
        "--backtest-capital",
        type=float,
        default=10000.0,
        help="Starting capital for backtest (default: 10000)",
    )

    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Start the web dashboard for live monitoring",
    )

    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=8080,
        help="Port for the web dashboard (default: 8080)",
    )

    parser.add_argument(
        "--create-admin",
        action="store_true",
        help="Create an admin user (requires --username and --password)",
    )

    parser.add_argument(
        "--username",
        type=str,
        help="Username for --create-admin",
    )

    parser.add_argument(
        "--password",
        type=str,
        help="Password for --create-admin (min 8 characters)",
    )

    args = parser.parse_args()

    # Handle create-admin (before logging setup)
    if args.create_admin:
        if not args.username or not args.password:
            parser.error("--create-admin requires --username and --password")
        if len(args.password) < 8:
            parser.error("Password must be at least 8 characters")
        return asyncio.run(create_admin(args.username, args.password))

    # Setup logging
    setup_logging(log_level=args.log_level)

    # Setup signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Run appropriate mode
    if args.status:
        return asyncio.run(show_status())
    elif args.test:
        return asyncio.run(run_test())
    elif args.backtest:
        return asyncio.run(run_backtest(args.backtest_days, args.backtest_capital))
    elif args.dashboard:
        from src.dashboard import run_dashboard
        run_dashboard(port=args.dashboard_port)
        return 0
    else:
        return asyncio.run(run_bot())


if __name__ == "__main__":
    sys.exit(main())
