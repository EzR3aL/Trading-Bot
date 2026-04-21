"""
WebSocket connection manager with per-user pub/sub.

ARCH-H5: every accepted connection owns an ``asyncio.Queue(maxsize=100)``
and a dedicated writer task. Broadcast helpers only enqueue the payload
(``put_nowait``) so one slow peer can never stall the others; if a queue
is full the slowest connection is disconnected rather than throttling
the whole fan-out. Previously ``broadcast_all`` awaited every
``ws.send_text`` sequentially inside the lock, which turned a single
stuck peer into a head-of-line blocker for all connected users.
"""

import asyncio
import json
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

from src.utils.logger import get_logger

logger = get_logger(__name__)


MAX_CONNECTIONS_PER_USER = 5
MAX_TOTAL_CONNECTIONS = 100

# Per-connection queue depth. Picked to absorb short stalls without
# letting a misbehaving client accumulate unbounded backlog.
CONNECTION_QUEUE_MAXSIZE = 100

# Hard deadline for a single send — defensive against half-closed sockets.
CONNECTION_SEND_TIMEOUT = 5.0


class _ConnectionState:
    """Per-connection queue + writer task."""

    __slots__ = ("ws", "user_id", "queue", "writer_task")

    def __init__(self, ws: WebSocket, user_id: int):
        self.ws = ws
        self.user_id = user_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=CONNECTION_QUEUE_MAXSIZE)
        self.writer_task: Optional[asyncio.Task] = None


class ConnectionManager:
    """Manages WebSocket connections grouped by user."""

    def __init__(self):
        self._connections: Dict[int, Set[WebSocket]] = {}
        # ws -> state; keyed by WebSocket so broadcast callers only need the user map
        self._state: Dict[WebSocket, _ConnectionState] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int) -> bool:
        """Connect a WebSocket. Returns False if limit exceeded."""
        async with self._lock:
            if self.total_connections >= MAX_TOTAL_CONNECTIONS:
                logger.warning("WS rejected: total limit reached (%d)", MAX_TOTAL_CONNECTIONS)
                return False
            if user_id not in self._connections:
                self._connections[user_id] = set()
            if len(self._connections[user_id]) >= MAX_CONNECTIONS_PER_USER:
                logger.warning("WS rejected: per-user limit for user=%s (%d)", user_id, MAX_CONNECTIONS_PER_USER)
                return False
            self._connections[user_id].add(websocket)
            state = _ConnectionState(websocket, user_id)
            state.writer_task = asyncio.create_task(self._writer_loop(state))
            self._state[websocket] = state
        logger.debug("WS connected: user=%s (total=%d)", user_id, self.total_connections)
        return True

    async def disconnect(self, websocket: WebSocket, user_id: int) -> None:
        state: Optional[_ConnectionState] = None
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
            state = self._state.pop(websocket, None)

        # Cancel writer outside the lock to avoid self-deadlock if it
        # happens to be re-entering disconnect via an exception path.
        if state is not None and state.writer_task is not None:
            state.writer_task.cancel()
            try:
                await state.writer_task
            except (asyncio.CancelledError, Exception):
                pass
        logger.debug("WS disconnected: user=%s (total=%d)", user_id, self.total_connections)

    async def broadcast_to_user(self, user_id: int, event_type: str, data: Any) -> None:
        """Enqueue an event for every connection of a specific user."""
        message = json.dumps({"type": event_type, "data": data})
        async with self._lock:
            connections = list(self._connections.get(user_id, set()))
            states = [self._state[ws] for ws in connections if ws in self._state]
        self._enqueue_many(states, message)

    async def broadcast_all(self, event_type: str, data: Any) -> None:
        """Enqueue an event for every connected user."""
        message = json.dumps({"type": event_type, "data": data})
        async with self._lock:
            states = list(self._state.values())
        self._enqueue_many(states, message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enqueue_many(self, states: list[_ConnectionState], message: str) -> None:
        """put_nowait on each connection queue; disconnect slow ones."""
        slow: list[_ConnectionState] = []
        for state in states:
            try:
                state.queue.put_nowait(message)
            except asyncio.QueueFull:
                slow.append(state)
        for state in slow:
            logger.warning(
                "WS queue full for user=%s — dropping slow connection",
                state.user_id,
            )
            # Fire-and-forget disconnect; the writer loop will also exit
            # once the ws.send_text starts failing.
            asyncio.create_task(self.disconnect(state.ws, state.user_id))

    async def _writer_loop(self, state: _ConnectionState) -> None:
        """Consume the queue and forward messages to the underlying socket."""
        try:
            while True:
                message = await state.queue.get()
                try:
                    await asyncio.wait_for(
                        state.ws.send_text(message),
                        timeout=CONNECTION_SEND_TIMEOUT,
                    )
                except asyncio.CancelledError:
                    raise
                except (asyncio.TimeoutError, Exception) as exc:
                    logger.debug(
                        "WS send failed (user=%s): %s — disconnecting",
                        state.user_id, exc,
                    )
                    # Schedule disconnect; return to let the task finish cleanly.
                    asyncio.create_task(self.disconnect(state.ws, state.user_id))
                    return
        except asyncio.CancelledError:
            # Expected on disconnect. Drain remaining items so GC is clean.
            while not state.queue.empty():
                try:
                    state.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            raise

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


# Singleton — imported by other modules to publish events
ws_manager = ConnectionManager()
