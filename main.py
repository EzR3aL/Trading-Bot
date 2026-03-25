#!/usr/bin/env python3
"""
DEPRECATED CLI entry point. The web UI uses BotOrchestrator + BotWorker (v3.0.0+).
This file is kept for standalone CLI usage only (--test, --status).

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
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.logger import setup_logging, get_logger
from config import settings


logger = get_logger(__name__)


async def run_bot():
    """Run the trading bot via the web server (BotOrchestrator)."""
    logger.info("Starting web server with BotOrchestrator...")
    logger.info("Use the web UI at http://localhost:8000 to manage bots.")
    logger.info("The standalone TradingBot has been removed in v4.0.0.")
    logger.info("Use: python main.py --dashboard")
    return 1


async def show_status():
    """Show current bot status and statistics."""
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
        import re
        if not re.search(r'[A-Z]', args.password):
            parser.error("Password must contain at least one uppercase letter")
        if not re.search(r'[a-z]', args.password):
            parser.error("Password must contain at least one lowercase letter")
        if not re.search(r'[0-9]', args.password):
            parser.error("Password must contain at least one digit")
        if not re.search(r'[^A-Za-z0-9]', args.password):
            parser.error("Password must contain at least one special character")
        return asyncio.run(create_admin(args.username, args.password))

    # Setup logging
    setup_logging(log_level=args.log_level)

    # Run appropriate mode
    if args.status:
        return asyncio.run(show_status())
    elif args.test:
        print("The standalone --test mode has been removed.")
        print("Use the web UI (--dashboard) to manage and test bots.")
        return 1
    elif args.dashboard:
        import uvicorn
        from src.api.main_app import app
        uvicorn.run(app, host="0.0.0.0", port=args.dashboard_port)
        return 0
    else:
        return asyncio.run(run_bot())


if __name__ == "__main__":
    sys.exit(main())
