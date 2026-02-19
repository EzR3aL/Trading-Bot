"""
WebSocket endpoint with JWT authentication.

Clients connect via /api/ws?token=<jwt> and receive real-time events
such as bot_started, bot_stopped, trade_opened, trade_closed.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.websocket.manager import ws_manager
from src.auth.jwt_handler import decode_token
from src.monitoring.metrics import WEBSOCKET_CONNECTIONS
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Authenticated WebSocket endpoint for real-time events."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload.get("sub")
    if user_id is None:
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    # Ensure user_id is int
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        await websocket.close(code=4001, reason="Invalid user ID")
        return

    await ws_manager.connect(websocket, user_id)
    WEBSOCKET_CONNECTIONS.set(ws_manager.total_connections)

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
