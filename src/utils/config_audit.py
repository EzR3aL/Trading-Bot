"""Fire-and-forget config change audit logging.

Reuses the same dedicated engine pattern as event_logger.py
to avoid blocking application queries.
"""

import asyncio
import json
from typing import Any, Dict, Optional, Set

from src.utils.logger import get_logger

logger = get_logger(__name__)

_pending_audit_tasks: Set[asyncio.Task] = set()

# Sensitive fields that should not be logged in change diffs
_SENSITIVE_FIELDS = frozenset({
    "api_key", "api_secret", "passphrase",
    "demo_api_key", "demo_api_secret", "demo_passphrase",
    "api_key_encrypted", "api_secret_encrypted", "passphrase_encrypted",
    "demo_api_key_encrypted", "demo_api_secret_encrypted", "demo_passphrase_encrypted",
    "discord_webhook_url", "telegram_bot_token", "telegram_chat_id",
    "whatsapp_phone_number_id", "whatsapp_access_token", "whatsapp_recipient",
    "password_hash",
})


def compute_changes(
    old_data: Optional[Dict[str, Any]],
    new_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute a diff between old and new data dicts.

    Sensitive fields are recorded as changed but their values are redacted.
    """
    if not old_data or not new_data:
        return {}

    changes: Dict[str, Any] = {}
    all_keys = set(old_data) | set(new_data)

    for key in all_keys:
        old_val = old_data.get(key)
        new_val = new_data.get(key)
        if old_val != new_val:
            if key in _SENSITIVE_FIELDS:
                changes[key] = {"old": "***", "new": "***"}
            else:
                changes[key] = {"old": old_val, "new": new_val}

    return changes


async def log_config_change(
    user_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    old_data: Optional[Dict[str, Any]] = None,
    new_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire-and-forget: schedule a config change log write in the background."""
    changes = compute_changes(old_data, new_data)
    task = asyncio.create_task(_store_change_safe(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        changes=json.dumps(changes) if changes else None,
    ))
    _pending_audit_tasks.add(task)
    task.add_done_callback(_pending_audit_tasks.discard)


async def _store_change_safe(**kwargs) -> None:
    """Wrapper that logs failures but never raises."""
    try:
        await _store_change(**kwargs)
    except Exception as e:
        logger.warning("Config audit log storage failed: %s", e)


async def _store_change(
    user_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    changes: Optional[str],
) -> None:
    """Store a config change record using the event logger's dedicated engine."""
    from src.utils.event_logger import _get_event_session_factory
    from src.models.database import ConfigChangeLog

    factory = _get_event_session_factory()
    async with factory() as session:
        record = ConfigChangeLog(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            changes=changes,
        )
        session.add(record)
        await session.commit()


async def drain_pending_audit_tasks(timeout: float = 5.0) -> int:
    """Wait for pending audit writes to complete during shutdown."""
    pending = list(_pending_audit_tasks)
    if not pending:
        return 0
    logger.info("Draining %d pending audit writes...", len(pending))
    done, not_done = await asyncio.wait(pending, timeout=timeout)
    if not_done:
        logger.warning("%d audit writes did not complete within %ss", len(not_done), timeout)
    return len(not_done)
