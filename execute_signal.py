#!/usr/bin/env python3
"""
DEPRECATED: Uses legacy TradingBot. For multibot system, use the web UI.

Execute a single trade signal manually.
This script runs the bot's analysis and executes the trade if a signal is generated.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.bot.trading_bot import TradingBot
from src.utils.logger import setup_logging, get_logger
from config import settings

logger = get_logger(__name__)


async def execute_single_trade():
    """Execute a single trade based on current market conditions."""
    setup_logging(log_level="INFO")

    print("=" * 60)
    print("EXECUTING TRADE SIGNAL")
    print("=" * 60)
    print(f"Mode: {'DEMO' if settings.is_demo_mode else 'LIVE'}")
    print("=" * 60)

    bot = TradingBot()

    # Initialize
    success = await bot.initialize()
    if not success:
        logger.error("Failed to initialize bot")
        return 1

    # In demo mode, manually initialize risk manager with simulated balance
    if settings.is_demo_mode:
        simulated_balance = 10000.0  # $10,000 demo balance
        bot.risk_manager.initialize_day(simulated_balance)
        print(f"Demo Mode: Using simulated balance of ${simulated_balance:,.2f}\n")

    # Run one analysis and trade cycle
    print("\nAnalyzing market and executing trades...\n")
    await bot.analyze_and_trade()

    print("\n" + "=" * 60)
    print("Trade execution complete!")
    print("=" * 60)

    # Cleanup
    await bot.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(execute_single_trade()))
