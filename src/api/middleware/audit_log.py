"""
Request audit logging middleware.

Logs every request with timestamp, user_id (from JWT if present),
method, path, status_code, response_time_ms, and client_ip.
Also stores audit records in the database.
"""

import asyncio
import time
from typing import Optional, Set

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth.jwt_handler import decode_token
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Track pending audit tasks for clean shutdown
_pending_audit_tasks: Set[asyncio.Task] = set()


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every HTTP request for auditing purposes."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.monotonic()
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        # Only log the path, never query parameters (may contain tokens/keys)
        path = request.url.path[:500]

        # Try to extract user_id from JWT token (best-effort, no validation)
        user_id = _extract_user_id(request)

        # Process the request
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            response_time_ms = round((time.monotonic() - start_time) * 1000, 1)

            # Log to app logger
            logger.info(
                "AUDIT | %s %s | status=%d | time=%sms | ip=%s | user=%s",
                method,
                path,
                status_code,
                response_time_ms,
                client_ip,
                user_id or "anonymous",
            )

            # Store in database (fire-and-forget, skip if contention)
            if path not in ("/api/status", "/openapi.json"):
                task = asyncio.create_task(_store_audit_record_safe(
                    user_id=user_id,
                    method=method,
                    path=path,
                    status_code=status_code,
                    response_time_ms=response_time_ms,
                    client_ip=client_ip,
                ))
                _pending_audit_tasks.add(task)
                task.add_done_callback(_pending_audit_tasks.discard)


def _extract_user_id(request: Request) -> Optional[int]:
    """Extract user_id from Authorization header JWT (best-effort)."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    try:
        payload = decode_token(token)
        if not payload:
            return None
        sub = payload.get("sub")
        return int(sub) if sub else None
    except (ValueError, TypeError):
        return None


async def _store_audit_record_safe(**kwargs) -> None:
    """Fire-and-forget wrapper — logs failures but never blocks."""
    try:
        await _store_audit_record(**kwargs)
    except Exception as e:
        logger.warning("Audit record storage failed: %s", e)


# Dedicated engine for audit writes — zero busy_timeout to never block app queries
_audit_engine = None
_audit_session_factory = None


def _get_audit_session_factory():
    """Lazy-init a dedicated audit engine (SQLite: busy_timeout=0, PostgreSQL: small pool)."""
    global _audit_engine, _audit_session_factory
    if _audit_session_factory is None:
        import os
        from sqlalchemy.ext.asyncio import AsyncSession as _AS, async_sessionmaker as _asm, create_async_engine as _cae
        from sqlalchemy import event as _ev
        db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db")
        _is_sqlite = db_url.startswith("sqlite")
        if _is_sqlite:
            _audit_engine = _cae(db_url, connect_args={"check_same_thread": False})
            @_ev.listens_for(_audit_engine.sync_engine, "connect")
            def _set_pragma(dbapi_conn, _):  # pragma: no cover — SQLite-only event
                c = dbapi_conn.cursor()
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA busy_timeout=500")
                c.close()
        else:
            _audit_engine = _cae(
                db_url,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
        _audit_session_factory = _asm(_audit_engine, class_=_AS, expire_on_commit=False)
    return _audit_session_factory


async def _store_audit_record(
    user_id: Optional[int],
    method: str,
    path: str,
    status_code: int,
    response_time_ms: float,
    client_ip: str,
) -> None:
    """Store an audit log record in the database (dedicated engine, never blocks main)."""
    from sqlalchemy import text

    factory = _get_audit_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO audit_logs "
                "(user_id, method, path, status_code, response_time_ms, client_ip) "
                "VALUES (:user_id, :method, :path, :status_code, :response_time_ms, :client_ip)"
            ),
            {
                "user_id": user_id,
                "method": method,
                "path": path,
                "status_code": status_code,
                "response_time_ms": response_time_ms,
                "client_ip": client_ip,
            },
        )
        await session.commit()


async def drain_pending_audit_tasks(timeout: float = 5.0) -> int:
    """Wait for pending audit writes to complete during shutdown.

    Args:
        timeout: Max seconds to wait for pending writes.

    Returns:
        Number of tasks that were still pending.
    """
    pending = list(_pending_audit_tasks)
    if not pending:
        return 0
    logger.info("Draining %d pending audit writes...", len(pending))
    done, not_done = await asyncio.wait(pending, timeout=timeout)
    if not_done:
        logger.warning("%d audit writes did not complete within %ss", len(not_done), timeout)
    return len(not_done)
