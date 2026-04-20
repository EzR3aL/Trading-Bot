"""Server-Sent Events stream for real-time trade updates (Issue #216, Section 2.2).

Replaces the 5-second frontend polling cycle for the trades list. Each
authenticated client holds a single long-lived HTTP connection and receives
JSON events as they are published on the process-local :class:`EventBus`.

Auth
----
``EventSource`` cannot set an ``Authorization`` header, so the endpoint
additionally accepts the access token via ``?token=<jwt>`` query parameter.
The same :mod:`src.auth.jwt_handler` validation path is reused: the header
is preferred when present, otherwise the query token or the httpOnly cookie
is used as a fallback.

Protocol
--------
* Normal event: ``data: <json>\\n\\n``
* Keepalive:    ``: keepalive\\n\\n`` emitted every 30 seconds of idle time
                (prevents intermediate proxies from dropping the connection).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from src.auth.jwt_handler import decode_token
from src.bot.event_bus import get_event_bus
from src.errors import (
    ERR_INVALID_TOKEN,
    ERR_INVALID_TOKEN_PAYLOAD,
    ERR_NOT_AUTHENTICATED,
    ERR_USER_NOT_FOUND_OR_INACTIVE,
)
from src.models.database import User
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Idle time between keepalive frames. A value above 30s triggers nginx's
# default ``proxy_read_timeout`` — pick 30 to be safely inside it.
KEEPALIVE_INTERVAL_SECONDS = 30

SSE_MEDIA_TYPE = "text/event-stream"

# Response headers that prevent proxy / browser buffering of the stream.
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disables nginx proxy_buffering for this response
}


router = APIRouter(prefix="/api/trades", tags=["trades"])


async def _resolve_sse_user(
    request: Request,
    token: Optional[str],
    db: AsyncSession,
) -> User:
    """Authenticate an SSE request. Mirrors :func:`get_current_user` but also
    accepts the token via the ``?token=`` query parameter.

    Precedence (same as the REST path):
    1. ``Authorization: Bearer <jwt>`` header.
    2. ``access_token`` httpOnly cookie.
    3. ``?token=`` query parameter (SSE fallback — ``EventSource`` cannot
       set custom headers, and cookies may not be sent cross-origin).
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    raw_token: Optional[str] = None
    if auth_header and auth_header.lower().startswith("bearer "):
        raw_token = auth_header.split(" ", 1)[1].strip()
    if not raw_token:
        raw_token = request.cookies.get("access_token")
    if not raw_token:
        raw_token = token

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(raw_token, expected_type="access")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_INVALID_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_INVALID_TOKEN_PAYLOAD,
        )

    result = await db.execute(select(User).where(User.id == int(user_id_raw)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active or user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_USER_NOT_FOUND_OR_INACTIVE,
        )

    return user


async def _event_stream(request: Request, user_id: int) -> AsyncIterator[bytes]:
    """Yield SSE frames for ``user_id`` until the client disconnects.

    Registers the subscriber **before** yielding the first byte so a publish
    that races the handshake is never dropped. Disconnection is detected by
    ``Request.is_disconnected`` which the ASGI server toggles when the
    socket closes.
    """
    bus = get_event_bus()
    queue = bus.register(user_id)

    # Initial frame tells the browser the stream is alive (resets the
    # ``EventSource`` retry counter immediately, avoiding a "connecting"
    # flash in the UI).
    yield b": connected\n\n"

    try:
        while True:
            if await request.is_disconnected():
                return

            try:
                event = await asyncio.wait_for(
                    queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue

            # SSE frames are terminated by a blank line. Keep the payload on
            # one line — JSON is already compact, no embedded newlines.
            yield f"data: {event}\n\n".encode("utf-8")
    finally:
        bus.unregister(user_id, queue)


@router.get("/stream")
async def stream_trades(
    request: Request,
    token: Optional[str] = Query(
        default=None,
        description=(
            "JWT access token. Provide here when the caller (EventSource) "
            "cannot set an Authorization header."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Open an SSE connection scoped to the authenticated user.

    Each delivered frame is one JSON object with keys ``event``,
    ``trade_id``, ``timestamp``, ``data``. The backend emits one of three
    event types (``trade_opened``, ``trade_updated``, ``trade_closed``)
    per trade lifecycle transition.
    """
    user = await _resolve_sse_user(request, token, db)

    logger.info(
        "trades_stream.subscribe user_id=%s",
        user.id,
        extra={"event_type": "trades_stream", "user_id": user.id},
    )

    return StreamingResponse(
        _event_stream(request, user.id),
        media_type=SSE_MEDIA_TYPE,
        headers=_SSE_HEADERS,
    )
