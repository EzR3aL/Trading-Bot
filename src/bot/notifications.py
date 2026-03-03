"""Notification helpers for BotWorker (mixin)."""

from typing import Callable, Optional

from src.notifications.discord_notifier import DiscordNotifier
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


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
        """Return all configured notifiers (Discord + Telegram + WhatsApp)."""
        notifiers = []
        discord = await self._get_discord_notifier()
        if discord:
            notifiers.append(discord)
        try:
            if self._config and self._config.telegram_bot_token and self._config.telegram_chat_id:
                from src.notifications.telegram_notifier import TelegramNotifier
                notifiers.append(TelegramNotifier(
                    bot_token=decrypt_value(self._config.telegram_bot_token),
                    chat_id=self._config.telegram_chat_id,
                ))
        except Exception as e:
            logger.warning(f"[Bot:{self.bot_config_id}] Could not load Telegram config: {e}")
        try:
            if (self._config
                    and self._config.whatsapp_phone_number_id
                    and self._config.whatsapp_access_token
                    and self._config.whatsapp_recipient):
                from src.notifications.whatsapp_notifier import WhatsAppNotifier
                notifiers.append(WhatsAppNotifier(
                    phone_number_id=decrypt_value(self._config.whatsapp_phone_number_id),
                    access_token=decrypt_value(self._config.whatsapp_access_token),
                    recipient_number=self._config.whatsapp_recipient,
                ))
        except Exception as e:
            logger.warning(f"[Bot:{self.bot_config_id}] Could not load WhatsApp config: {e}")
        return notifiers

    async def _send_notification(self, send_fn: Callable) -> None:
        """Dispatch a notification to all configured notifiers.

        Args:
            send_fn: async callable that takes a notifier and sends the message.
                     e.g. ``lambda n: n.send_trade_entry(...)``
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        try:
            for notifier in await self._get_notifiers():
                try:
                    async with notifier:
                        await send_fn(notifier)
                except Exception as ne:
                    logger.warning(f"{log_prefix} Notification failed: {ne}")
        except Exception as notify_err:
            logger.warning(f"{log_prefix} Notifier setup failed: {notify_err}")
