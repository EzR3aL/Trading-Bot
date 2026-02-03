#!/usr/bin/env python3
"""
Legacy Data Migration Script.

Migrates data from old SQLite databases (trades.db, funding_tracker.db)
to the new SQLAlchemy-based schema. Creates an admin user from .env values.

Usage:
    python scripts/migrate_legacy_data.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import aiosqlite
from sqlalchemy import select

from src.auth.password import hash_password
from src.models.database import (
    Base,
    ConfigPreset,
    FundingPayment,
    TradeRecord,
    User,
    UserConfig,
)
from src.models.session import engine, get_session, init_db
from src.utils.encryption import encrypt_value
from src.utils.logger import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


async def create_admin_user() -> int:
    """Create admin user from .env credentials. Returns user_id."""
    async with get_session() as session:
        # Check if admin already exists
        result = await session.execute(
            select(User).where(User.username == "admin")
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.info(f"Admin user already exists (id={existing.id})")
            return existing.id

        admin_password = os.getenv("ADMIN_PASSWORD", "changeme123")
        admin = User(
            username="admin",
            email=os.getenv("ADMIN_EMAIL", "admin@trading-bot.local"),
            password_hash=hash_password(admin_password),
            role="admin",
            language="de",
        )
        session.add(admin)
        await session.flush()
        await session.refresh(admin)
        logger.info(f"Created admin user (id={admin.id})")
        return admin.id


async def create_user_config(user_id: int) -> None:
    """Create user config from .env values."""
    async with get_session() as session:
        result = await session.execute(
            select(UserConfig).where(UserConfig.user_id == user_id)
        )
        if result.scalar_one_or_none():
            logger.info("User config already exists")
            return

        config = UserConfig(
            user_id=user_id,
            exchange_type="bitget",
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", ""),
        )

        # Encrypt API keys from .env
        api_key = os.getenv("BITGET_API_KEY", "")
        if api_key and api_key != "your_live_api_key_here":
            config.api_key_encrypted = encrypt_value(api_key)
            config.api_secret_encrypted = encrypt_value(os.getenv("BITGET_API_SECRET", ""))
            config.passphrase_encrypted = encrypt_value(os.getenv("BITGET_PASSPHRASE", ""))

        demo_key = os.getenv("BITGET_DEMO_API_KEY", "")
        if demo_key and demo_key != "your_demo_api_key_here":
            config.demo_api_key_encrypted = encrypt_value(demo_key)
            config.demo_api_secret_encrypted = encrypt_value(os.getenv("BITGET_DEMO_API_SECRET", ""))
            config.demo_passphrase_encrypted = encrypt_value(os.getenv("BITGET_DEMO_PASSPHRASE", ""))

        # Trading config from .env
        trading_config = {
            "max_trades_per_day": int(os.getenv("MAX_TRADES_PER_DAY", "3")),
            "daily_loss_limit_percent": float(os.getenv("DAILY_LOSS_LIMIT_PERCENT", "5.0")),
            "position_size_percent": float(os.getenv("POSITION_SIZE_PERCENT", "7.5")),
            "leverage": int(os.getenv("LEVERAGE", "4")),
            "take_profit_percent": float(os.getenv("TAKE_PROFIT_PERCENT", "4.0")),
            "stop_loss_percent": float(os.getenv("STOP_LOSS_PERCENT", "1.5")),
            "trading_pairs": os.getenv("TRADING_PAIRS", "BTCUSDT,ETHUSDT").split(","),
            "demo_mode": os.getenv("DEMO_MODE", "true").lower() == "true",
        }
        config.trading_config = json.dumps(trading_config)

        # Strategy config from .env
        strategy_config = {
            "fear_greed_extreme_fear": int(os.getenv("FEAR_GREED_EXTREME_FEAR", "20")),
            "fear_greed_extreme_greed": int(os.getenv("FEAR_GREED_EXTREME_GREED", "80")),
            "long_short_crowded_longs": float(os.getenv("LONG_SHORT_CROWDED_LONGS", "2.5")),
            "long_short_crowded_shorts": float(os.getenv("LONG_SHORT_CROWDED_SHORTS", "0.4")),
            "funding_rate_high": float(os.getenv("FUNDING_RATE_HIGH", "0.0005")),
            "funding_rate_low": float(os.getenv("FUNDING_RATE_LOW", "-0.0002")),
            "high_confidence_min": int(os.getenv("HIGH_CONFIDENCE_MIN", "85")),
            "low_confidence_min": int(os.getenv("LOW_CONFIDENCE_MIN", "60")),
        }
        config.strategy_config = json.dumps(strategy_config)

        session.add(config)
        logger.info("Created user config from .env values")


async def create_default_preset(user_id: int) -> None:
    """Create a default preset from .env config."""
    async with get_session() as session:
        result = await session.execute(
            select(ConfigPreset).where(ConfigPreset.user_id == user_id)
        )
        if result.scalars().first():
            logger.info("Presets already exist")
            return

        trading_config = {
            "max_trades_per_day": int(os.getenv("MAX_TRADES_PER_DAY", "3")),
            "daily_loss_limit_percent": float(os.getenv("DAILY_LOSS_LIMIT_PERCENT", "5.0")),
            "position_size_percent": float(os.getenv("POSITION_SIZE_PERCENT", "7.5")),
            "leverage": int(os.getenv("LEVERAGE", "4")),
            "take_profit_percent": float(os.getenv("TAKE_PROFIT_PERCENT", "4.0")),
            "stop_loss_percent": float(os.getenv("STOP_LOSS_PERCENT", "1.5")),
            "trading_pairs": os.getenv("TRADING_PAIRS", "BTCUSDT,ETHUSDT").split(","),
            "demo_mode": True,
        }

        strategy_config = {
            "fear_greed_extreme_fear": int(os.getenv("FEAR_GREED_EXTREME_FEAR", "20")),
            "fear_greed_extreme_greed": int(os.getenv("FEAR_GREED_EXTREME_GREED", "80")),
            "long_short_crowded_longs": float(os.getenv("LONG_SHORT_CROWDED_LONGS", "2.5")),
            "long_short_crowded_shorts": float(os.getenv("LONG_SHORT_CROWDED_SHORTS", "0.4")),
            "funding_rate_high": float(os.getenv("FUNDING_RATE_HIGH", "0.0005")),
            "funding_rate_low": float(os.getenv("FUNDING_RATE_LOW", "-0.0002")),
            "high_confidence_min": int(os.getenv("HIGH_CONFIDENCE_MIN", "85")),
            "low_confidence_min": int(os.getenv("LOW_CONFIDENCE_MIN", "60")),
        }

        preset = ConfigPreset(
            user_id=user_id,
            name="Default (from .env)",
            description="Auto-generated from existing .env configuration",
            exchange_type="bitget",
            is_active=True,
            trading_config=json.dumps(trading_config),
            strategy_config=json.dumps(strategy_config),
            trading_pairs=json.dumps(os.getenv("TRADING_PAIRS", "BTCUSDT,ETHUSDT").split(",")),
        )
        session.add(preset)
        logger.info("Created default preset from .env")


async def migrate_trades(user_id: int) -> int:
    """Migrate trades from old trades.db. Returns count."""
    old_db_path = Path("data/trades.db")
    if not old_db_path.exists():
        logger.info("No legacy trades.db found - skipping trade migration")
        return 0

    count = 0
    async with aiosqlite.connect(old_db_path) as old_db:
        old_db.row_factory = aiosqlite.Row
        cursor = await old_db.execute("SELECT * FROM trades ORDER BY entry_time ASC")
        rows = await cursor.fetchall()

        async with get_session() as session:
            for row in rows:
                trade = TradeRecord(
                    user_id=user_id,
                    exchange="bitget",
                    symbol=row["symbol"],
                    side=row["side"],
                    size=row["size"],
                    entry_price=row["entry_price"],
                    exit_price=row["exit_price"],
                    take_profit=row["take_profit"],
                    stop_loss=row["stop_loss"],
                    leverage=row["leverage"],
                    confidence=row["confidence"],
                    reason=row["reason"],
                    order_id=row["order_id"],
                    close_order_id=row["close_order_id"],
                    status=row["status"],
                    pnl=row["pnl"],
                    pnl_percent=row["pnl_percent"],
                    fees=row["fees"] or 0,
                    funding_paid=row["funding_paid"] or 0,
                    entry_time=datetime.fromisoformat(row["entry_time"]) if row["entry_time"] else datetime.utcnow(),
                    exit_time=datetime.fromisoformat(row["exit_time"]) if row["exit_time"] else None,
                    exit_reason=row["exit_reason"],
                    metrics_snapshot=row["metrics_snapshot"],
                )
                session.add(trade)
                count += 1

    logger.info(f"Migrated {count} trades from legacy database")
    return count


async def migrate_funding(user_id: int) -> int:
    """Migrate funding payments from old funding database. Returns count."""
    old_db_path = Path("data/funding_tracker.db")
    if not old_db_path.exists():
        logger.info("No legacy funding_tracker.db found - skipping")
        return 0

    count = 0
    async with aiosqlite.connect(old_db_path) as old_db:
        old_db.row_factory = aiosqlite.Row
        try:
            cursor = await old_db.execute(
                "SELECT * FROM funding_payments ORDER BY timestamp ASC"
            )
            rows = await cursor.fetchall()
        except Exception:
            logger.info("No funding_payments table in legacy DB")
            return 0

        async with get_session() as session:
            for row in rows:
                payment = FundingPayment(
                    user_id=user_id,
                    symbol=row["symbol"],
                    funding_rate=row["funding_rate"],
                    position_size=row["position_size"],
                    position_value=row.get("position_value", 0) or 0,
                    payment_amount=row["payment_amount"],
                    side=row.get("side"),
                    timestamp=datetime.fromisoformat(row["timestamp"]) if row["timestamp"] else datetime.utcnow(),
                )
                session.add(payment)
                count += 1

    logger.info(f"Migrated {count} funding payments from legacy database")
    return count


async def main():
    """Run the full migration."""
    print("=" * 60)
    print("TRADING BOT - DATA MIGRATION")
    print("=" * 60)

    # Initialize new database
    print("\n1. Initializing new database schema...")
    await init_db()
    print("   Done.")

    # Create admin user
    print("\n2. Creating admin user...")
    user_id = await create_admin_user()
    print(f"   Admin user ID: {user_id}")

    # Create user config
    print("\n3. Creating user config from .env...")
    await create_user_config(user_id)
    print("   Done.")

    # Create default preset
    print("\n4. Creating default preset...")
    await create_default_preset(user_id)
    print("   Done.")

    # Migrate trades
    print("\n5. Migrating legacy trades...")
    trade_count = await migrate_trades(user_id)
    print(f"   Migrated {trade_count} trades.")

    # Migrate funding
    print("\n6. Migrating legacy funding payments...")
    funding_count = await migrate_funding(user_id)
    print(f"   Migrated {funding_count} funding payments.")

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print(f"  Admin user: admin (ID: {user_id})")
    print(f"  Trades migrated: {trade_count}")
    print(f"  Funding payments migrated: {funding_count}")
    print(f"  Default preset created: Yes")
    print(f"  Old database files preserved as backup")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
