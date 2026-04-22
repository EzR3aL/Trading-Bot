"""Notifier component: Discord / Telegram dispatch for a single bot.

Extracted from ``src.bot.notifications.NotificationsMixin`` as the first
step of the BotWorker composition refactor (ARCH-H1 Phase 1 PR-1,
issue #274). The old mixin now delegates to this component so existing
callsites and tests stay unchanged; Phase 2 will migrate callsites to
``self._notifier.send_notification(...)`` directly.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from src.notifications.discord_notifier import DiscordNotifier
from src.notifications.log_helper import log_notification
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _channel_name(notifier: Any) -> str:
    """Derive channel name from notifier class."""
    name = type(notifier).__name__.lower()
    if "discord" in name:
        return "discord"
    if "telegram" in name:
        return "telegram"
    return "unknown"


class Notifier:
    """Composition-owned notification dispatcher for one BotWorker.

    The ``config_getter`` indirection exists because BotWorker loads its
    ``BotConfig`` only during ``start()``, while the Notifier is
    constructed in ``__init__``.
    """

    def __init__(
        self,
        bot_config_id: int,
        config_getter: Callable[[], Optional[Any]],
    ) -> None:
        self._bot_config_id = bot_config_id
        self._get_config = config_getter

    async def get_discord_notifier(self) -> Optional[DiscordNotifier]:
        """Load Discord webhook from bot-specific config only."""
        config = self._get_config()
        try:
            if config and config.discord_webhook_url:
                webhook_url = decrypt_value(config.discord_webhook_url)
                return DiscordNotifier(webhook_url=webhook_url)
        except Exception as e:
            logger.warning(
                f"[Bot:{self._bot_config_id}] Could not load Discord config: {e}"
            )
        return None

    async def get_notifiers(self) -> List[Any]:
        """Return all configured notifiers (Discord + Telegram)."""
        notifiers: List[Any] = []
        discord = await self.get_discord_notifier()
        if discord:
            notifiers.append(discord)
        config = self._get_config()
        try:
            if (
                config
                and config.telegram_bot_token
                and config.telegram_chat_id
            ):
                from src.notifications.telegram_notifier import TelegramNotifier

                notifiers.append(
                    TelegramNotifier(
                        bot_token=decrypt_value(config.telegram_bot_token),
                        chat_id=decrypt_value(config.telegram_chat_id),
                    )
                )
        except Exception as e:
            logger.warning(
                f"[Bot:{self._bot_config_id}] Could not load Telegram config: {e}"
            )
        return notifiers

    async def send_notification(
        self,
        send_fn: Callable,
        event_type: str = "unknown",
        summary: Optional[str] = None,
        notifiers: Optional[List[Any]] = None,
    ) -> None:
        """Dispatch a notification to all configured notifiers.

        Args:
            send_fn: async callable that takes a notifier and sends the message.
                     e.g. ``lambda n: n.send_trade_entry(...)``
            event_type: notification category for logging (e.g. "trade_entry").
            summary: optional short text for the log payload_summary field.
            notifiers: explicit notifier list (used by the Mixin proxy so
                worker-level ``_get_notifiers`` stubs remain honoured in
                tests). When ``None``, the component loads its own list.
        """
        log_prefix = f"[Bot:{self._bot_config_id}]"
        config = self._get_config()
        user_id = getattr(config, "user_id", None) if config else None
        if notifiers is None:
            notifiers = await self.get_notifiers()
        try:
            for notifier in notifiers:
                channel = _channel_name(notifier)
                try:
                    async with notifier:
                        await send_fn(notifier)
                    if user_id:
                        await log_notification(
                            user_id=user_id,
                            bot_config_id=self._bot_config_id,
                            channel=channel,
                            event_type=event_type,
                            status="sent",
                            summary=summary,
                        )
                except Exception as ne:
                    logger.warning(f"{log_prefix} Notification failed: {ne}")
                    if user_id:
                        await log_notification(
                            user_id=user_id,
                            bot_config_id=self._bot_config_id,
                            channel=channel,
                            event_type=event_type,
                            status="failed",
                            error=str(ne),
                            summary=summary,
                        )
        except Exception as notify_err:
            logger.warning(f"{log_prefix} Notifier setup failed: {notify_err}")
