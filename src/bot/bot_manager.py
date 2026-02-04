"""
BotManager: Per-user, per-exchange bot instance management.

Handles starting, stopping, and switching presets for individual user bots.
Supports running multiple bots in parallel on different exchanges.
"""

import json
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.exchanges.factory import create_exchange_client, create_exchange_websocket
from src.models.database import BotInstance, ConfigPreset, ExchangeConnection
from src.models.session import get_session
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BotManager:
    """Manages per-user, per-exchange bot instances."""

    def __init__(self):
        # user_id -> {exchange_type -> bot_info}
        self._bots: Dict[int, Dict[str, dict]] = {}

    async def start_bot(
        self,
        user_id: int,
        exchange_type: str = "bitget",
        preset_id: Optional[int] = None,
        demo_mode: bool = True,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """Start a bot for a user on a specific exchange."""
        user_bots = self._bots.get(user_id, {})
        if exchange_type in user_bots and user_bots[exchange_type].get("running"):
            raise ValueError(f"Bot already running on {exchange_type}")

        try:
            async with get_session() as session:
                # Get exchange connection credentials
                result = await session.execute(
                    select(ExchangeConnection).where(
                        ExchangeConnection.user_id == user_id,
                        ExchangeConnection.exchange_type == exchange_type,
                    )
                )
                conn = result.scalar_one_or_none()

                if not conn:
                    raise ValueError(
                        f"No API keys configured for {exchange_type}. "
                        "Add keys in Settings first."
                    )

                # Get credentials based on mode
                if demo_mode:
                    if not conn.demo_api_key_encrypted:
                        raise ValueError(
                            f"No demo API keys configured for {exchange_type}. "
                            "Add demo keys in Settings first."
                        )
                    api_key = decrypt_value(conn.demo_api_key_encrypted)
                    api_secret = decrypt_value(conn.demo_api_secret_encrypted)
                    passphrase = decrypt_value(conn.demo_passphrase_encrypted) if conn.demo_passphrase_encrypted else ""
                else:
                    if not conn.api_key_encrypted:
                        raise ValueError(
                            f"No live API keys configured for {exchange_type}. "
                            "Add live keys in Settings first."
                        )
                    api_key = decrypt_value(conn.api_key_encrypted)
                    api_secret = decrypt_value(conn.api_secret_encrypted)
                    passphrase = decrypt_value(conn.passphrase_encrypted) if conn.passphrase_encrypted else ""

                # Get preset config if specified
                preset_name = None
                if preset_id:
                    preset_result = await session.execute(
                        select(ConfigPreset).where(
                            ConfigPreset.id == preset_id,
                            ConfigPreset.user_id == user_id,
                        )
                    )
                    preset = preset_result.scalar_one_or_none()
                    if preset:
                        preset_name = preset.name

                # Create exchange client
                exchange_client = create_exchange_client(
                    exchange_type=exchange_type,
                    api_key=api_key,
                    api_secret=api_secret,
                    passphrase=passphrase,
                    demo_mode=demo_mode,
                )

                # Store bot info
                if user_id not in self._bots:
                    self._bots[user_id] = {}
                self._bots[user_id][exchange_type] = {
                    "running": True,
                    "exchange_type": exchange_type,
                    "demo_mode": demo_mode,
                    "preset_id": preset_id,
                    "preset_name": preset_name,
                    "exchange_client": exchange_client,
                    "started_at": datetime.utcnow().isoformat(),
                }

                # Record in DB
                bot_instance = BotInstance(
                    user_id=user_id,
                    exchange_type=exchange_type,
                    is_running=True,
                    demo_mode=demo_mode,
                    active_preset_id=preset_id,
                    started_at=datetime.utcnow(),
                )
                session.add(bot_instance)

            logger.info(
                f"Bot started for user {user_id}: "
                f"{exchange_type} ({'demo' if demo_mode else 'live'})"
            )
            return True

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to start bot for user {user_id} on {exchange_type}: {e}")
            return False

    async def stop_bot(self, user_id: int, exchange_type: str) -> bool:
        """Stop a user's bot on a specific exchange."""
        user_bots = self._bots.get(user_id, {})
        if exchange_type not in user_bots or not user_bots[exchange_type].get("running"):
            return False

        bot_info = user_bots[exchange_type]

        # Close exchange client
        client = bot_info.get("exchange_client")
        if client:
            try:
                await client.close()
            except Exception as e:
                logger.error(f"Error closing exchange client: {e}")

        bot_info["running"] = False
        bot_info["stopped_at"] = datetime.utcnow().isoformat()

        # Update DB
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(BotInstance).where(
                        BotInstance.user_id == user_id,
                        BotInstance.exchange_type == exchange_type,
                        BotInstance.is_running == True,
                    )
                )
                instance = result.scalar_one_or_none()
                if instance:
                    instance.is_running = False
                    instance.stopped_at = datetime.utcnow()
        except Exception as e:
            logger.error(f"Error updating bot instance in DB: {e}")

        logger.info(f"Bot stopped for user {user_id} on {exchange_type}")
        return True

    def get_status(self, user_id: int) -> List[dict]:
        """Get bot status for all exchanges of a user."""
        user_bots = self._bots.get(user_id, {})
        if not user_bots:
            return []

        statuses = []
        for exchange_type, info in user_bots.items():
            statuses.append({
                "is_running": info.get("running", False),
                "exchange_type": info.get("exchange_type"),
                "demo_mode": info.get("demo_mode", True),
                "active_preset_id": info.get("preset_id"),
                "active_preset_name": info.get("preset_name"),
                "started_at": info.get("started_at"),
            })
        return statuses

    def get_exchange_status(self, user_id: int, exchange_type: str) -> dict:
        """Get bot status for a specific exchange."""
        user_bots = self._bots.get(user_id, {})
        info = user_bots.get(exchange_type)
        if not info:
            return {
                "is_running": False,
                "exchange_type": exchange_type,
                "demo_mode": True,
                "active_preset_id": None,
                "active_preset_name": None,
                "started_at": None,
            }
        return {
            "is_running": info.get("running", False),
            "exchange_type": info.get("exchange_type"),
            "demo_mode": info.get("demo_mode", True),
            "active_preset_id": info.get("preset_id"),
            "active_preset_name": info.get("preset_name"),
            "started_at": info.get("started_at"),
        }

    def is_running(self, user_id: int, exchange_type: Optional[str] = None) -> bool:
        """Check if a bot is running. If exchange_type is None, checks any exchange."""
        user_bots = self._bots.get(user_id, {})
        if exchange_type:
            return exchange_type in user_bots and user_bots[exchange_type].get("running", False)
        return any(info.get("running", False) for info in user_bots.values())

    async def stop_all_for_user(self, user_id: int) -> int:
        """Stop all running bots for a user. Returns count of stopped bots."""
        user_bots = self._bots.get(user_id, {})
        stopped = 0
        for exchange_type in list(user_bots.keys()):
            if user_bots[exchange_type].get("running"):
                await self.stop_bot(user_id, exchange_type)
                stopped += 1
        return stopped

    async def switch_preset(self, user_id: int, preset_id: int, exchange_type: str) -> bool:
        """Switch preset: stop current bot on exchange, load new preset, restart."""
        was_running = self.is_running(user_id, exchange_type)
        demo_mode = True

        if was_running:
            demo_mode = self._bots[user_id][exchange_type].get("demo_mode", True)
            await self.stop_bot(user_id, exchange_type)

        return await self.start_bot(
            user_id=user_id,
            exchange_type=exchange_type,
            preset_id=preset_id,
            demo_mode=demo_mode,
        )

    async def shutdown_all(self):
        """Stop all running bots (called on app shutdown)."""
        for user_id in list(self._bots.keys()):
            for exchange_type in list(self._bots[user_id].keys()):
                if self._bots[user_id][exchange_type].get("running"):
                    await self.stop_bot(user_id, exchange_type)
        logger.info("All bots shut down")
