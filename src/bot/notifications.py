"""Notification helpers for BotWorker (mixin)."""

from typing import Callable, Optional

from src.notifications.discord_notifier import DiscordNotifier
from src.notifications.log_helper import log_notification
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _channel_name(notifier) -> str:
    """Derive channel name from notifier class."""
    name = type(notifier).__name__.lower()
    if "discord" in name:
        return "discord"
    if "telegram" in name:
        return "telegram"
    return "unknown"


class NotificationsMixin:
    """Mixin providing notification methods for BotWorker."""

    async def _get_discord_notifier(self) -> Optional[DiscordNotifier]:
        """Load Discord webhook from bot-specific config only."""
        try:
            if self._config and self._config.discord_webhook_url:
                webhook_url = decrypt_value(self._config.discord_webhook_url)
                return DiscordNotifier(webhook_url=webhook_url)
        except Exception as e:
            logger.warning(f"[Bot:{self.bot_config_id}] Could not load Discord config: {e}")
        return None

    async def _get_notifiers(self) -> list:
        """Return all configured notifiers (Discord + Telegram)."""
        notifiers = []
        discord = await self._get_discord_notifier()
        if discord:
            notifiers.append(discord)
        try:
            if self._config and self._config.telegram_bot_token and self._config.telegram_chat_id:
                from src.notifications.telegram_notifier import TelegramNotifier
                notifiers.append(TelegramNotifier(
                    bot_token=decrypt_value(self._config.telegram_bot_token),
                    chat_id=decrypt_value(self._config.telegram_chat_id),
                ))
        except Exception as e:
            logger.warning(f"[Bot:{self.bot_config_id}] Could not load Telegram config: {e}")
        return notifiers

    async def _send_notification(self, send_fn: Callable, event_type: str = "unknown", summary: str | None = None) -> None:
        """Dispatch a notification to all configured notifiers.

        Args:
            send_fn: async callable that takes a notifier and sends the message.
                     e.g. ``lambda n: n.send_trade_entry(...)``
            event_type: notification category for logging (e.g. "trade_entry").
            summary: optional short text for the log payload_summary field.
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        user_id = getattr(self._config, "user_id", None) if self._config else None
        try:
            for notifier in await self._get_notifiers():
                channel = _channel_name(notifier)
                try:
                    async with notifier:
                        await send_fn(notifier)
                    # Log successful delivery (fire-and-forget)
                    if user_id:
                        await log_notification(
                            user_id=user_id,
                            bot_config_id=self.bot_config_id,
                            channel=channel,
                            event_type=event_type,
                            status="sent",
                            summary=summary,
                        )
                except Exception as ne:
                    logger.warning(f"{log_prefix} Notification failed: {ne}")
                    # Log failed delivery (fire-and-forget)
                    if user_id:
                        await log_notification(
                            user_id=user_id,
                            bot_config_id=self.bot_config_id,
                            channel=channel,
                            event_type=event_type,
                            status="failed",
                            error=str(ne),
                            summary=summary,
                        )
        except Exception as notify_err:
            logger.warning(f"{log_prefix} Notifier setup failed: {notify_err}")
