"""
WebSocket endpoint with JWT authentication (SEC-013).

Authentication happens **before** the WebSocket handshake is accepted:
the JWT is required as a ``token`` query parameter and is validated
with ``decode_token(expected_type="access")``. Failed auth is signalled
with close code ``1008`` (policy violation) per RFC 6455.

Token sources (in priority order):
1. ``?token=...`` query param (required — returns 1008 if missing).
2. The ``access_token`` httpOnly cookie — used as a fallback for
   browsers that cannot put the JWT in the URL (the cookie is sent on
   the WebSocket handshake automatically).

Once authenticated the client receives real-time events:
``bot_started``, ``bot_stopped``, ``trade_opened``, ``trade_closed``.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from starlette.status import WS_1008_POLICY_VIOLATION

from src.api.websocket.manager import ws_manager
from src.auth.jwt_handler import decode_token
from src.models.database import User
from src.models.session import get_session
from src.monitoring.metrics import WEBSOCKET_CONNECTIONS
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

WS_INACTIVITY_TIMEOUT = 300  # seconds


@router.websocket("/api/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),
):
    """Authenticated WebSocket endpoint for real-time events.

    The JWT access token MUST be supplied either as the ``token`` query
    parameter or the ``access_token`` httpOnly cookie. Requests that
    fail authentication are rejected with close code ``1008`` (policy
    violation) before the handshake is accepted.
    """
    # Resolve token: query param first, fall back to httpOnly cookie.
    raw_token = token or websocket.cookies.get("access_token")
    if not raw_token:
        await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="Missing token")
        return

    payload = decode_token(raw_token, expected_type="access")
    if not payload:
        await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    user_id_claim = payload.get("sub")
    if user_id_claim is None:
        await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="Invalid token payload")
        return
    try:
        user_id = int(user_id_claim)
    except (TypeError, ValueError):
        await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="Invalid user ID")
        return

    # Verify user status and token_version against the database before accepting.
    async with get_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="User inactive")
            return
        if getattr(user, "is_deleted", False):
            await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="User not found")
            return
        tv = payload.get("tv", 0)
        if tv < (user.token_version or 0):
            await websocket.close(code=WS_1008_POLICY_VIOLATION, reason="Token revoked")
            return

    # Auth successful — accept the connection and register it.
    await websocket.accept()

    connected = await ws_manager.connect(websocket, user_id)
    if not connected:
        await websocket.close(code=4008, reason="Connection limit exceeded")
        return
    WEBSOCKET_CONNECTIONS.set(ws_manager.total_connections)
    await websocket.send_text("authenticated")

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=WS_INACTIVITY_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.info(
                    "WebSocket: Client %d timed out after 5min inactivity", user_id
                )
                break
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket, user_id)
        WEBSOCKET_CONNECTIONS.set(ws_manager.total_connections)
