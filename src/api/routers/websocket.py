"""
WebSocket endpoint with JWT authentication.

Clients connect via /api/ws and send the JWT token as the first message
(avoids exposing tokens in URL query strings / server logs).
Receives real-time events: bot_started, bot_stopped, trade_opened, trade_closed.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.websocket.manager import ws_manager
from src.auth.jwt_handler import decode_token
from src.monitoring.metrics import WEBSOCKET_CONNECTIONS
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

AUTH_TIMEOUT_SECONDS = 10


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Authenticated WebSocket endpoint for real-time events."""
    await websocket.accept()

    # Wait for auth message (first message must be the JWT token)
    try:
        token = await asyncio.wait_for(
            websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        await websocket.close(code=4001, reason="Auth timeout")
        return

    payload = decode_token(token)
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

    await ws_manager.connect(websocket, user_id)
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
