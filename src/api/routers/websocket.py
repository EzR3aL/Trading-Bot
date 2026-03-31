"""
WebSocket endpoint with JWT authentication.

Clients connect via /api/ws and send the JWT token as the first message
(avoids exposing tokens in URL query strings / server logs).
Receives real-time events: bot_started, bot_stopped, trade_opened, trade_closed.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from src.api.websocket.manager import ws_manager
from src.auth.jwt_handler import decode_token
from src.models.database import User
from src.models.session import get_session
from src.monitoring.metrics import WEBSOCKET_CONNECTIONS
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

AUTH_TIMEOUT_SECONDS = 10


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Authenticated WebSocket endpoint for real-time events."""
    await websocket.accept()

    # Try httpOnly cookie first (browser sends cookies on WebSocket handshake)
    cookie_token = websocket.cookies.get("access_token")
    payload = None

    if cookie_token:
        payload = decode_token(cookie_token, expected_type="access")
        # If cookie token is invalid, fall through to message-based auth

    # Fallback: wait for auth message (first message = JWT token)
    if not payload:
        try:
            first_msg = await asyncio.wait_for(
                websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            await websocket.close(code=4001, reason="Auth timeout")
            return
        payload = decode_token(first_msg, expected_type="access")

    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")
    if user_id is None:
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        await websocket.close(code=4001, reason="Invalid user ID")
        return

    # Verify user status and token_version against database
    async with get_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            await websocket.close(code=4001, reason="User inactive")
            return
        if getattr(user, 'is_deleted', False):
            await websocket.close(code=4001, reason="User not found")
            return
        tv = payload.get("tv", 0)
        if tv < (user.token_version or 0):
            await websocket.close(code=4001, reason="Token revoked")
            return

    connected = await ws_manager.connect(websocket, user_id)
    if not connected:
        await websocket.close(code=4008, reason="Connection limit exceeded")
        return
    WEBSOCKET_CONNECTIONS.set(ws_manager.total_connections)
    await websocket.send_text("authenticated")

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(websocket, user_id)
        WEBSOCKET_CONNECTIONS.set(ws_manager.total_connections)
