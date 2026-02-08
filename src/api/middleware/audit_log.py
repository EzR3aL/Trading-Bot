"""
Request audit logging middleware.

Logs every request with timestamp, user_id (from JWT if present),
method, path, status_code, response_time_ms, and client_ip.
Also stores audit records in the database.
"""

import time
from typing import Optional

from fastapi import Request, Response
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every HTTP request for auditing purposes."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.monotonic()
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path

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

            # Store in database (non-blocking, best-effort)
            try:
                await _store_audit_record(
                    user_id=user_id,
                    method=method,
                    path=path,
                    status_code=status_code,
                    response_time_ms=response_time_ms,
                    client_ip=client_ip,
                )
            except Exception as e:
                logger.warning("Failed to store audit log record: %s", e)


def _extract_user_id(request: Request) -> Optional[int]:
    """Extract user_id from Authorization header JWT (best-effort)."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    try:
        import os
        secret = os.getenv("JWT_SECRET_KEY", "")
        if not secret:
            return None
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        sub = payload.get("sub")
        return int(sub) if sub else None
    except (JWTError, ValueError, TypeError):
        return None


async def _store_audit_record(
    user_id: Optional[int],
    method: str,
    path: str,
    status_code: int,
    response_time_ms: float,
    client_ip: str,
) -> None:
    """Store an audit log record in the database."""
    from sqlalchemy import text

    from src.models.session import async_session_factory

    async with async_session_factory() as session:
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
