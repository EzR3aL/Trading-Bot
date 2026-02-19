"""
WebSocket connection manager with per-user pub/sub.

Maintains a mapping of user_id -> active WebSocket connections
and provides methods to broadcast events to specific users or all users.
"""

import asyncio
import json
from typing import Any, Dict, Set

from fastapi import WebSocket

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Manages WebSocket connections grouped by user."""

    def __init__(self):
        self._connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
        logger.debug("WS connected: user=%s (total=%d)", user_id, self.total_connections)

    async def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
        logger.debug("WS disconnected: user=%s (total=%d)", user_id, self.total_connections)

    async def broadcast_to_user(self, user_id: int, event_type: str, data: Any) -> None:
        """Send an event to all connections of a specific user."""
        message = json.dumps({"type": event_type, "data": data})
        async with self._lock:
            connections = list(self._connections.get(user_id, set()))
        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws, user_id)

    async def broadcast_all(self, event_type: str, data: Any) -> None:
        """Broadcast an event to every connected user."""
        message = json.dumps({"type": event_type, "data": data})
        async with self._lock:
            all_pairs = [
                (uid, list(conns)) for uid, conns in self._connections.items()
            ]
        for uid, connections in all_pairs:
            for ws in connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    await self.disconnect(ws, uid)

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


# Singleton — imported by other modules to publish events
ws_manager = ConnectionManager()
