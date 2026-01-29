#!/usr/bin/env python3
"""
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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Bitget Trading Bot - Contrarian Liquidation Hunter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py            Run the trading bot
  python main.py --test     Run analysis without trading
  python main.py --status   Show current status and statistics

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

    args = parser.parse_args()

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
    else:
        return asyncio.run(run_bot())


if __name__ == "__main__":
    sys.exit(main())
