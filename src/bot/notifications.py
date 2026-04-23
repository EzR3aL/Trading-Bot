"""BotWorker notifications mixin + manual-close API helpers.

The ``NotificationsMixin`` is a thin proxy delegating to
``src.bot.components.notifier.Notifier`` (composition refactor — ARCH-H1
Phase 1 PR-1, #276). Module-level helpers (``_load_notifiers_from_config``,
``build_standalone_dispatcher``) support the manual-close API path where
no BotWorker is available to supply ``self._send_notification``.
"""

from typing import Any, Callable, List, Optional

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


def _load_notifiers_from_config(config) -> list:
    """Build a list of configured notifiers from a BotConfig.

    Standalone variant (no ``self``) so the manual-close API path can send
    notifications without instantiating a full BotWorker. Mirrors the
    semantics of :meth:`Notifier.get_notifiers`.
    """
    notifiers: list = []
    if config is None:
        return notifiers
    try:
        if getattr(config, "discord_webhook_url", None):
            webhook_url = decrypt_value(config.discord_webhook_url)
            notifiers.append(DiscordNotifier(webhook_url=webhook_url))
    except Exception as e:
        logger.warning("Could not load Discord config for bot %s: %s",
                       getattr(config, "id", "?"), e)
    try:
        if getattr(config, "telegram_bot_token", None) and getattr(config, "telegram_chat_id", None):
            from src.notifications.telegram_notifier import TelegramNotifier
            notifiers.append(TelegramNotifier(
                bot_token=decrypt_value(config.telegram_bot_token),
                chat_id=decrypt_value(config.telegram_chat_id),
            ))
    except Exception as e:
        logger.warning("Could not load Telegram config for bot %s: %s",
                       getattr(config, "id", "?"), e)
    return notifiers


def build_standalone_dispatcher(config, bot_config_id: int) -> Callable:
    """Return an async dispatcher callable compatible with :func:`close_and_record_trade`.

    Used by the manual-close API endpoint when no BotWorker is available to
    supply ``_send_notification``. Semantics match the mixin: fire each
    configured notifier, log success/failure via ``log_notification``,
    swallow exceptions so notification errors never break the close flow.
    """
    async def dispatcher(send_fn: Callable, event_type: str = "unknown", summary: Optional[str] = None) -> None:
        log_prefix = f"[Bot:{bot_config_id}]"
        user_id = getattr(config, "user_id", None) if config else None
        try:
            for notifier in _load_notifiers_from_config(config):
                channel = _channel_name(notifier)
                try:
                    async with notifier:
                        await send_fn(notifier)
                    if user_id:
                        await log_notification(
                            user_id=user_id,
                            bot_config_id=bot_config_id,
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
                            bot_config_id=bot_config_id,
                            channel=channel,
                            event_type=event_type,
                            status="failed",
                            error=str(ne),
                            summary=summary,
                        )
        except Exception as notify_err:
            logger.warning(f"{log_prefix} Notifier setup failed: {notify_err}")

    return dispatcher


class NotificationsMixin:
    """Thin proxy delegating to ``self._notifier`` (Notifier component, set in BotWorker.__init__)."""

    async def _get_discord_notifier(self) -> Optional[Any]:
        return await self._notifier.get_discord_notifier()

    async def _get_notifiers(self) -> List[Any]:
        return await self._notifier.get_notifiers()

    async def _send_notification(
        self,
        send_fn: Callable,
        event_type: str = "unknown",
        summary: Optional[str] = None,
    ) -> None:
        # Load notifiers through the proxy (not the component directly) so
        # tests that stub ``worker._get_notifiers`` keep working.
        try:
            notifiers = await self._get_notifiers()
        except Exception:
            notifiers = []
        await self._notifier.send_notification(
            send_fn, event_type, summary, notifiers=notifiers
        )
