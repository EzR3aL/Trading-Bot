"""
WebSocket Connection Manager for Multi-Tenant Trading Platform.

Manages per-user WebSocket connections with JWT authentication.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Set
from fastapi import WebSocket

from src.auth.jwt_handler import JWTHandler, TokenPayload, TokenExpiredError, TokenInvalidError
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections with per-user isolation.

    Features:
    - JWT-based authentication
    - Per-user connection tracking
    - Broadcast to specific users
    - Connection health monitoring
    """

    def __init__(self):
        """Initialize the connection manager."""
        # Map of user_id -> set of WebSocket connections
        self._connections: Dict[int, Set[WebSocket]] = {}
        # Map of WebSocket -> user_id for reverse lookup
        self._websocket_to_user: Dict[WebSocket, int] = {}
        # Map of WebSocket -> TokenPayload for auth info
        self._websocket_auth: Dict[WebSocket, TokenPayload] = {}
        # JWT handler for token verification
        self._jwt_handler = JWTHandler()
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def authenticate(self, websocket: WebSocket, token: str) -> Optional[TokenPayload]:
        """
        Authenticate a WebSocket connection using JWT token.

        Args:
            websocket: The WebSocket connection
            token: JWT access token

        Returns:
            TokenPayload if authentication succeeds, None otherwise
        """
        try:
            payload = self._jwt_handler.verify_access_token(token)
            return payload
        except TokenExpiredError:
            logger.warning("WebSocket auth failed: Token expired")
            return None
        except TokenInvalidError as e:
            logger.warning(f"WebSocket auth failed: {e}")
            return None

    async def connect(self, websocket: WebSocket, payload: TokenPayload) -> bool:
        """
        Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
            payload: Authenticated token payload

        Returns:
            True if connection was registered
        """
        await websocket.accept()

        async with self._lock:
            user_id = payload.user_id

            # Initialize user's connection set if needed
            if user_id not in self._connections:
                self._connections[user_id] = set()

            # Register the connection
            self._connections[user_id].add(websocket)
            self._websocket_to_user[websocket] = user_id
            self._websocket_auth[websocket] = payload

        logger.info(
            f"WebSocket connected: user={payload.user_id} username={payload.username} "
            f"(total connections for user: {len(self._connections.get(user_id, []))})"
        )

        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection.

        Args:
            websocket: The WebSocket to disconnect
        """
        async with self._lock:
            user_id = self._websocket_to_user.pop(websocket, None)
            self._websocket_auth.pop(websocket, None)

            if user_id and user_id in self._connections:
                self._connections[user_id].discard(websocket)

                # Clean up empty connection sets
                if not self._connections[user_id]:
                    del self._connections[user_id]

                logger.info(
                    f"WebSocket disconnected: user={user_id} "
                    f"(remaining connections: {len(self._connections.get(user_id, []))})"
                )

    async def broadcast_to_user(
        self,
        user_id: int,
        message: dict,
        exclude: Optional[WebSocket] = None
    ) -> int:
        """
        Send a message to all connections for a specific user.

        Args:
            user_id: Target user ID
            message: Message to send (will be JSON-encoded)
            exclude: Optional WebSocket to exclude from broadcast

        Returns:
            Number of connections the message was sent to
        """
        async with self._lock:
            connections = self._connections.get(user_id, set()).copy()

        sent_count = 0
        failed = []

        for websocket in connections:
            if websocket == exclude:
                continue

            try:
                await websocket.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send to WebSocket: {e}")
                failed.append(websocket)

        # Clean up failed connections
        for websocket in failed:
            await self.disconnect(websocket)

        return sent_count

    async def broadcast_to_all(
        self,
        message: dict,
        admin_only: bool = False
    ) -> int:
        """
        Broadcast a message to all connected users.

        Args:
            message: Message to send
            admin_only: If True, only send to admin users

        Returns:
            Number of connections the message was sent to
        """
        async with self._lock:
            all_websockets = list(self._websocket_to_user.keys())

        sent_count = 0
        failed = []

        for websocket in all_websockets:
            # Check admin filter
            if admin_only:
                payload = self._websocket_auth.get(websocket)
                if not payload or not payload.is_admin:
                    continue

            try:
                await websocket.send_json(message)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to broadcast to WebSocket: {e}")
                failed.append(websocket)

        # Clean up failed connections
        for websocket in failed:
            await self.disconnect(websocket)

        return sent_count

    async def send_trade_notification(
        self,
        user_id: int,
        trade_data: dict
    ) -> int:
        """
        Send a trade notification to a user.

        Args:
            user_id: User ID to notify
            trade_data: Trade information

        Returns:
            Number of connections notified
        """
        message = {
            "type": "trade",
            "timestamp": datetime.now().isoformat(),
            "data": trade_data,
        }
        return await self.broadcast_to_user(user_id, message)

    async def send_bot_status(
        self,
        user_id: int,
        bot_id: int,
        status: str,
        details: Optional[dict] = None
    ) -> int:
        """
        Send a bot status update to a user.

        Args:
            user_id: User ID to notify
            bot_id: Bot ID
            status: Status string (running, stopped, error)
            details: Optional additional details

        Returns:
            Number of connections notified
        """
        message = {
            "type": "bot_status",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "bot_id": bot_id,
                "status": status,
                **(details or {}),
            },
        }
        return await self.broadcast_to_user(user_id, message)

    async def send_risk_alert(
        self,
        user_id: int,
        alert_type: str,
        message_text: str,
        severity: str = "warning"
    ) -> int:
        """
        Send a risk alert to a user.

        Args:
            user_id: User ID to notify
            alert_type: Type of alert (daily_limit, position_limit, etc.)
            message_text: Alert message
            severity: Alert severity (info, warning, critical)

        Returns:
            Number of connections notified
        """
        message = {
            "type": "risk_alert",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "alert_type": alert_type,
                "message": message_text,
                "severity": severity,
            },
        }
        return await self.broadcast_to_user(user_id, message)

    def get_user_connection_count(self, user_id: int) -> int:
        """Get the number of active connections for a user."""
        return len(self._connections.get(user_id, []))

    def get_total_connection_count(self) -> int:
        """Get the total number of active connections."""
        return len(self._websocket_to_user)

    def get_connected_users(self) -> List[int]:
        """Get list of user IDs with active connections."""
        return list(self._connections.keys())

    def is_user_connected(self, user_id: int) -> bool:
        """Check if a user has any active connections."""
        return user_id in self._connections and len(self._connections[user_id]) > 0


# Global connection manager instance
_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get or create the global connection manager."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager
