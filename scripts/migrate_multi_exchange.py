#!/usr/bin/env python3
"""
Multi-Exchange Migration Script.

Migrates API keys from UserConfig to the new ExchangeConnection table.
Existing encrypted values are copied directly (no re-encryption needed).

Usage:
    python scripts/migrate_multi_exchange.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select

from src.models.database import ExchangeConnection, UserConfig
from src.models.session import get_session, init_db


async def migrate():
    """Migrate API keys from UserConfig to ExchangeConnection."""
    print("Initializing database (creates new tables if needed)...")
    await init_db()

    async with get_session() as session:
        # Get all UserConfig rows that have API keys
        result = await session.execute(select(UserConfig))
        configs = result.scalars().all()

        migrated = 0
        skipped = 0

        for config in configs:
            has_keys = config.api_key_encrypted or config.demo_api_key_encrypted
            if not has_keys:
                continue

            exchange_type = config.exchange_type or "bitget"

            # Check if already migrated
            existing = await session.execute(
                select(ExchangeConnection).where(
                    ExchangeConnection.user_id == config.user_id,
                    ExchangeConnection.exchange_type == exchange_type,
                )
            )
            if existing.scalar_one_or_none():
                print(f"  Skipped user {config.user_id} ({exchange_type}): already exists")
                skipped += 1
                continue

            # Create ExchangeConnection with existing encrypted values
            conn = ExchangeConnection(
                user_id=config.user_id,
                exchange_type=exchange_type,
                api_key_encrypted=config.api_key_encrypted,
                api_secret_encrypted=config.api_secret_encrypted,
                passphrase_encrypted=config.passphrase_encrypted,
                demo_api_key_encrypted=config.demo_api_key_encrypted,
                demo_api_secret_encrypted=config.demo_api_secret_encrypted,
                demo_passphrase_encrypted=config.demo_passphrase_encrypted,
            )
            session.add(conn)
            migrated += 1
            print(f"  Migrated user {config.user_id} ({exchange_type})")

    print(f"\nDone: {migrated} migrated, {skipped} skipped")


if __name__ == "__main__":
    asyncio.run(migrate())
