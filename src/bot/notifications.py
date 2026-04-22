"""BotWorker notifications mixin (thin proxy to Notifier component).

Kept for backward compatibility with existing callsites
(``self._send_notification(...)``) and tests. The actual implementation
lives in ``src.bot.components.notifier.Notifier``. Phase 2 of the
composition refactor will migrate callsites to ``self._notifier.send_notification(...)``
and delete this mixin.
"""

from typing import Any, Callable, List, Optional


class NotificationsMixin:
    """Delegates notification calls to ``self._notifier`` (set in BotWorker.__init__)."""

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
