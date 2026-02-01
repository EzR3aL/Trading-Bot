"""
Bot Instance model for multi-tenant bot management.

Each user can have multiple bot instances, each with
their own configuration and credentials.
"""

import aiosqlite
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BotConfig:
    """Trading configuration for a bot instance."""
    trading_pairs: List[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    leverage: int = 3
    position_size_percent: float = 7.5
    max_trades_per_day: int = 2
    daily_loss_limit_percent: float = 5.0
    take_profit_percent: float = 4.0
    stop_loss_percent: float = 1.5
    min_confidence: int = 60

    def to_dict(self) -> dict:
        return {
            "trading_pairs": self.trading_pairs,
            "leverage": self.leverage,
            "position_size_percent": self.position_size_percent,
            "max_trades_per_day": self.max_trades_per_day,
            "daily_loss_limit_percent": self.daily_loss_limit_percent,
            "take_profit_percent": self.take_profit_percent,
            "stop_loss_percent": self.stop_loss_percent,
            "min_confidence": self.min_confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BotConfig":
        return cls(
            trading_pairs=data.get("trading_pairs", ["BTCUSDT", "ETHUSDT"]),
            leverage=data.get("leverage", 3),
            position_size_percent=data.get("position_size_percent", 7.5),
            max_trades_per_day=data.get("max_trades_per_day", 2),
            daily_loss_limit_percent=data.get("daily_loss_limit_percent", 5.0),
            take_profit_percent=data.get("take_profit_percent", 4.0),
            stop_loss_percent=data.get("stop_loss_percent", 1.5),
            min_confidence=data.get("min_confidence", 60),
        )


@dataclass
class BotInstance:
    """Bot instance dataclass."""
    id: Optional[int]
    user_id: int
    credential_id: int
    name: str
    config: BotConfig
    is_running: bool = False
    last_heartbeat: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "credential_id": self.credential_id,
            "name": self.name,
            "config": self.config.to_dict(),
            "is_running": self.is_running,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class BotInstanceRepository:
    """
    Repository for bot instance database operations.

    Manages CRUD operations for bot instances with proper
    multi-tenant isolation.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """Initialize the bot instance repository."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def create(
        self,
        user_id: int,
        credential_id: int,
        name: str,
        config: Optional[BotConfig] = None
    ) -> BotInstance:
        """
        Create a new bot instance.

        Args:
            user_id: Owner user ID
            credential_id: API credential ID to use
            name: Friendly name for this bot instance
            config: Trading configuration (uses defaults if None)

        Returns:
            Created BotInstance object

        Raises:
            ValueError: If name already exists for user
        """
        if config is None:
            config = BotConfig()

        config_json = json.dumps(config.to_dict())

        async with aiosqlite.connect(self.db_path) as db:
            try:
                cursor = await db.execute(
                    """
                    INSERT INTO bot_instances (user_id, credential_id, name, config)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, credential_id, name, config_json)
                )
                await db.commit()
                instance_id = cursor.lastrowid

                logger.info(f"Created bot instance '{name}' for user_id={user_id}")

                return BotInstance(
                    id=instance_id,
                    user_id=user_id,
                    credential_id=credential_id,
                    name=name,
                    config=config,
                    is_running=False,
                    last_heartbeat=None,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
            except aiosqlite.IntegrityError:
                raise ValueError(f"Bot instance name '{name}' already exists for this user")

    async def get_by_id(self, instance_id: int, user_id: int) -> Optional[BotInstance]:
        """
        Get bot instance by ID with user verification.

        Args:
            instance_id: Bot instance ID
            user_id: User ID (for tenant isolation)

        Returns:
            BotInstance if found and belongs to user, None otherwise
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM bot_instances WHERE id = ? AND user_id = ?",
                (instance_id, user_id)
            )
            row = await cursor.fetchone()
            return self._row_to_instance(row) if row else None

    async def get_by_user(self, user_id: int) -> List[BotInstance]:
        """
        Get all bot instances for a user.

        Args:
            user_id: User ID

        Returns:
            List of bot instances
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM bot_instances WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return [self._row_to_instance(row) for row in rows]

    async def get_running(self) -> List[BotInstance]:
        """Get all currently running bot instances."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM bot_instances WHERE is_running = 1"
            )
            rows = await cursor.fetchall()
            return [self._row_to_instance(row) for row in rows]

    async def update_config(
        self,
        instance_id: int,
        user_id: int,
        config: BotConfig
    ) -> bool:
        """
        Update bot instance configuration.

        Args:
            instance_id: Bot instance ID
            user_id: User ID (for tenant isolation)
            config: New configuration

        Returns:
            True if updated successfully
        """
        config_json = json.dumps(config.to_dict())

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE bot_instances SET
                    config = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (config_json, datetime.now(), instance_id, user_id)
            )
            await db.commit()
            if cursor.rowcount > 0:
                logger.info(f"Updated config for bot instance id={instance_id}")
                return True
            return False

    async def set_running(self, instance_id: int, is_running: bool) -> bool:
        """Update the running status of a bot instance."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE bot_instances SET
                    is_running = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (int(is_running), datetime.now(), instance_id)
            )
            await db.commit()
            return True

    async def update_heartbeat(self, instance_id: int) -> bool:
        """Update the last heartbeat timestamp."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE bot_instances SET last_heartbeat = ? WHERE id = ?",
                (datetime.now(), instance_id)
            )
            await db.commit()
            return True

    async def delete(self, instance_id: int, user_id: int) -> bool:
        """
        Delete a bot instance.

        Args:
            instance_id: Bot instance ID
            user_id: User ID (for tenant isolation)

        Returns:
            True if deleted successfully
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM bot_instances WHERE id = ? AND user_id = ?",
                (instance_id, user_id)
            )
            await db.commit()
            if cursor.rowcount > 0:
                logger.warning(f"Deleted bot instance id={instance_id}")
                return True
            return False

    async def count_by_user(self, user_id: int) -> int:
        """Count bot instances for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM bot_instances WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    def _row_to_instance(self, row) -> BotInstance:
        """Convert database row to BotInstance object."""
        config_data = json.loads(row["config"]) if row["config"] else {}
        config = BotConfig.from_dict(config_data)

        return BotInstance(
            id=row["id"],
            user_id=row["user_id"],
            credential_id=row["credential_id"],
            name=row["name"],
            config=config,
            is_running=bool(row["is_running"]),
            last_heartbeat=datetime.fromisoformat(row["last_heartbeat"]) if row["last_heartbeat"] else None,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )
