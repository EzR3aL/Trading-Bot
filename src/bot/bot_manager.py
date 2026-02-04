"""
BotManager: Per-user bot instance management.

Handles starting, stopping, and switching presets for individual user bots.
"""

import json
from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.exchanges.factory import create_exchange_client, create_exchange_websocket
from src.models.database import BotInstance, ConfigPreset, UserConfig
from src.models.session import get_session
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BotManager:
    """Manages per-user bot instances."""

    def __init__(self):
        self._bots: Dict[int, dict] = {}  # user_id -> bot info

    async def start_bot(
        self,
        user_id: int,
        exchange_type: str = "bitget",
        preset_id: Optional[int] = None,
        demo_mode: bool = True,
        db: Optional[AsyncSession] = None,
    ) -> bool:
        """Start a bot for a user."""
        if user_id in self._bots and self._bots[user_id].get("running"):
            logger.warning(f"Bot already running for user {user_id}")
            raise ValueError("Bot is already running")

        try:
            async with get_session() as session:
                # Get user config
                result = await session.execute(
                    select(UserConfig).where(UserConfig.user_id == user_id)
                )
                config = result.scalar_one_or_none()

                if not config:
                    logger.error(f"No config found for user {user_id}")
                    raise ValueError("No configuration found. Set up your settings first.")

                # Get credentials based on mode
                if demo_mode:
                    if not config.demo_api_key_encrypted:
                        logger.error(f"Demo mode requested but no demo API keys configured for user {user_id}")
                        raise ValueError("No demo API keys configured. Add demo keys in Settings first.")
                    api_key = decrypt_value(config.demo_api_key_encrypted)
                    api_secret = decrypt_value(config.demo_api_secret_encrypted)
                    passphrase = decrypt_value(config.demo_passphrase_encrypted) if config.demo_passphrase_encrypted else ""
                else:
                    if not config.api_key_encrypted:
                        logger.error(f"Live mode requested but no live API keys configured for user {user_id}")
                        raise ValueError("No live API keys configured. Add live keys in Settings first.")
                    api_key = decrypt_value(config.api_key_encrypted)
                    api_secret = decrypt_value(config.api_secret_encrypted)
                    passphrase = decrypt_value(config.passphrase_encrypted) if config.passphrase_encrypted else ""

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
                        exchange_type = preset.exchange_type

                # Create exchange client
                exchange_client = create_exchange_client(
                    exchange_type=exchange_type,
                    api_key=api_key,
                    api_secret=api_secret,
                    passphrase=passphrase,
                    demo_mode=demo_mode,
                )

                # Store bot info
                self._bots[user_id] = {
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

        except Exception as e:
            logger.error(f"Failed to start bot for user {user_id}: {e}")
            return False

    async def stop_bot(self, user_id: int) -> bool:
        """Stop a user's bot."""
        if user_id not in self._bots or not self._bots[user_id].get("running"):
            return False

        bot_info = self._bots[user_id]

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
                    select(BotInstance)
                    .where(BotInstance.user_id == user_id, BotInstance.is_running == True)
                )
                instance = result.scalar_one_or_none()
                if instance:
                    instance.is_running = False
                    instance.stopped_at = datetime.utcnow()
        except Exception as e:
            logger.error(f"Error updating bot instance in DB: {e}")

        logger.info(f"Bot stopped for user {user_id}")
        return True

    def get_status(self, user_id: int) -> dict:
        """Get bot status for a user."""
        if user_id not in self._bots:
            return {
                "is_running": False,
                "exchange_type": None,
                "demo_mode": True,
                "active_preset_id": None,
                "active_preset_name": None,
                "started_at": None,
            }

        info = self._bots[user_id]
        return {
            "is_running": info.get("running", False),
            "exchange_type": info.get("exchange_type"),
            "demo_mode": info.get("demo_mode", True),
            "active_preset_id": info.get("preset_id"),
            "active_preset_name": info.get("preset_name"),
            "started_at": info.get("started_at"),
        }

    def is_running(self, user_id: int) -> bool:
        """Check if a bot is running for a user."""
        return user_id in self._bots and self._bots[user_id].get("running", False)

    async def switch_preset(self, user_id: int, preset_id: int) -> bool:
        """Switch preset: stop current bot, load new preset, restart."""
        was_running = self.is_running(user_id)
        demo_mode = True

        if was_running:
            demo_mode = self._bots[user_id].get("demo_mode", True)
            await self.stop_bot(user_id)

        return await self.start_bot(
            user_id=user_id,
            preset_id=preset_id,
            demo_mode=demo_mode,
        )

    async def shutdown_all(self):
        """Stop all running bots (called on app shutdown)."""
        for user_id in list(self._bots.keys()):
            if self._bots[user_id].get("running"):
                await self.stop_bot(user_id)
        logger.info("All bots shut down")
