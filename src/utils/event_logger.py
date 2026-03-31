"""
Fire-and-forget business event logging.

Stores events in the event_logs table using a dedicated engine
(same pattern as audit_log middleware) so it never blocks app queries.
"""

import asyncio
import json
from typing import Any, Dict, Optional, Set

from src.utils.logger import get_logger

logger = get_logger(__name__)

_pending_event_tasks: Set[asyncio.Task] = set()


async def log_event(
    event_type: str,
    message: str,
    severity: str = "info",
    user_id: Optional[int] = None,
    bot_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire-and-forget: schedule an event log write in the background."""
    task = asyncio.create_task(_store_event_safe(
        event_type=event_type,
        message=message,
        severity=severity,
        user_id=user_id,
        bot_id=bot_id,
        details=json.dumps(details) if details else None,
    ))
    _pending_event_tasks.add(task)
    task.add_done_callback(_pending_event_tasks.discard)


async def _store_event_safe(**kwargs) -> None:
    """Wrapper that logs failures but never blocks."""
    try:
        await _store_event(**kwargs)
    except Exception as e:
        logger.warning("Event log storage failed: %s", e)


_event_engine = None
_event_session_factory = None


def _get_event_session_factory():
    """Lazy-init a dedicated event engine with busy_timeout=0."""
    global _event_engine, _event_session_factory
    if _event_session_factory is None:
        import os
        from sqlalchemy.ext.asyncio import (
            AsyncSession as _AS,
            async_sessionmaker as _asm,
            create_async_engine as _cae,
        )
        from sqlalchemy import event as _ev

        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db")
        _event_engine = _cae(
            db_url,
            connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
        )
        if "sqlite" in db_url:
            @_ev.listens_for(_event_engine.sync_engine, "connect")
            def _set_pragma(dbapi_conn, _):
                c = dbapi_conn.cursor()
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA busy_timeout=0")
                c.close()
        _event_session_factory = _asm(
            _event_engine, class_=_AS, expire_on_commit=False,
        )
    return _event_session_factory


async def _store_event(
    event_type: str,
    message: str,
    severity: str,
    user_id: Optional[int],
    bot_id: Optional[int],
    details: Optional[str],
) -> None:
    """Store an event log record in the database."""
    from src.models.database import EventLog

    factory = _get_event_session_factory()
    async with factory() as session:
        record = EventLog(
            user_id=user_id,
            bot_id=bot_id,
            event_type=event_type,
            severity=severity,
            message=message,
            details=details,
        )
        session.add(record)
        await session.commit()


async def drain_pending_event_tasks(timeout: float = 5.0) -> int:
    """Wait for pending event writes to complete during shutdown."""
    pending = list(_pending_event_tasks)
    if not pending:
        return 0
    logger.info("Draining %d pending event writes...", len(pending))
    done, not_done = await asyncio.wait(pending, timeout=timeout)
    if not_done:
        logger.warning("%d event writes did not complete within %ss", len(not_done), timeout)
    return len(not_done)
