"""Migrate risk stats from JSON files to database.

Reads all data/risk/bot_*/daily_stats_*.json files and inserts them
into the risk_stats table. Idempotent (upserts by bot_config_id + date).

Usage:
    python -m scripts.migrate_risk_json
"""

import asyncio
import json
import re
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.database import RiskStats  # noqa: E402
from src.models.session import get_session, init_db  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402
from sqlalchemy import select  # noqa: E402

logger = get_logger(__name__)

RISK_DATA_DIR = Path("data/risk")
BOT_DIR_PATTERN = re.compile(r"bot_(\d+)")
STATS_FILE_PATTERN = re.compile(r"daily_stats_(\d{4}-\d{2}-\d{2})\.json")


async def migrate() -> None:
    """Migrate all JSON risk stats files to the database."""
    await init_db()

    if not RISK_DATA_DIR.exists():
        logger.info("No risk data directory found — nothing to migrate")
        return

    migrated = 0
    skipped = 0

    for bot_dir in sorted(RISK_DATA_DIR.iterdir()):
        if not bot_dir.is_dir():
            continue
        match = BOT_DIR_PATTERN.match(bot_dir.name)
        if not match:
            continue
        bot_config_id = int(match.group(1))

        for stats_file in sorted(bot_dir.glob("daily_stats_*.json")):
            file_match = STATS_FILE_PATTERN.match(stats_file.name)
            if not file_match:
                continue
            date_str = file_match.group(1)

            try:
                with open(stats_file) as f:
                    stats_dict = json.load(f)

                async with get_session() as session:
                    existing = await session.execute(
                        select(RiskStats).where(
                            RiskStats.bot_config_id == bot_config_id,
                            RiskStats.date == date_str,
                        )
                    )
                    if existing.scalar_one_or_none():
                        skipped += 1
                        continue

                    row = RiskStats(
                        bot_config_id=bot_config_id,
                        date=date_str,
                        stats_json=json.dumps(stats_dict),
                        daily_pnl=stats_dict.get("net_pnl", 0.0),
                        trades_count=stats_dict.get("trades_executed", 0),
                        is_halted=stats_dict.get("is_trading_halted", False),
                    )
                    session.add(row)
                    migrated += 1

            except Exception as e:
                logger.warning("Failed to migrate %s: %s", stats_file, e)

    logger.info("Migration complete: %d migrated, %d skipped (already exists)", migrated, skipped)


if __name__ == "__main__":
    asyncio.run(migrate())
