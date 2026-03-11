"""Fire-and-forget notification logging helper."""

import logging

from src.models.database import NotificationLog
from src.models.session import get_session

logger = logging.getLogger(__name__)


async def log_notification(
    user_id: int,
    bot_config_id: int | None,
    channel: str,
    event_type: str,
    status: str,
    error: str | None = None,
    summary: str | None = None,
) -> None:
    """Persist a notification delivery attempt.

    Designed for fire-and-forget usage: failures are logged as warnings
    but never propagate to the caller.
    """
    try:
        async with get_session() as session:
            entry = NotificationLog(
                user_id=user_id,
                bot_config_id=bot_config_id,
                channel=channel,
                event_type=event_type,
                status=status,
                error_message=error[:500] if error else None,
                payload_summary=summary[:500] if summary else None,
            )
            session.add(entry)
    except Exception:
        logger.warning("Failed to log notification", exc_info=True)
