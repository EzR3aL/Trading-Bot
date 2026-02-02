"""
Unit tests for WebSocket Connection Manager.

Tests connection tracking, authentication, and user-scoped messaging.
"""

import os
import pytest
import base64
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

# Set up test environment before imports
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-purposes-only-32chars"
test_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["ENCRYPTION_MASTER_KEY"] = test_key

from src.dashboard.websocket_manager import ConnectionManager, get_connection_manager
from src.auth.jwt_handler import TokenPayload


def create_test_payload(user_id: int, username: str = "testuser", is_admin: bool = False) -> TokenPayload:
    """Create a test token payload."""
    return TokenPayload(
        user_id=user_id,
        username=username,
        is_admin=is_admin,
        exp=datetime.now() + timedelta(hours=1),
        iat=datetime.now(),
        jti="test-jti-12345",
        token_type="access"
    )


def create_mock_websocket():
    """Create a mock WebSocket for testing."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


class TestConnectionManager:
    """Tests for ConnectionManager class."""

    @pytest.fixture
    def manager(self):
        """Create a fresh connection manager for each test."""
        return ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_registers_connection(self, manager):
        """Test that connecting adds the WebSocket to tracking."""
        ws = create_mock_websocket()
        payload = create_test_payload(user_id=1)

        await manager.connect(ws, payload)

        assert manager.get_user_connection_count(1) == 1
        assert manager.get_total_connection_count() == 1
        assert manager.is_user_connected(1)

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self, manager):
        """Test that disconnecting removes the WebSocket from tracking."""
        ws = create_mock_websocket()
        payload = create_test_payload(user_id=1)

        await manager.connect(ws, payload)
        await manager.disconnect(ws)

        assert manager.get_user_connection_count(1) == 0
        assert manager.get_total_connection_count() == 0
        assert not manager.is_user_connected(1)

    @pytest.mark.asyncio
    async def test_multiple_connections_per_user(self, manager):
        """Test that a user can have multiple connections."""
        ws1 = create_mock_websocket()
        ws2 = create_mock_websocket()
        payload = create_test_payload(user_id=1)

        await manager.connect(ws1, payload)
        await manager.connect(ws2, payload)

        assert manager.get_user_connection_count(1) == 2

        await manager.disconnect(ws1)
        assert manager.get_user_connection_count(1) == 1

    @pytest.mark.asyncio
    async def test_broadcast_to_user(self, manager):
        """Test broadcasting to specific user."""
        # Connect user 1
        ws1 = create_mock_websocket()
        payload1 = create_test_payload(user_id=1)
        await manager.connect(ws1, payload1)

        # Connect user 2
        ws2 = create_mock_websocket()
        payload2 = create_test_payload(user_id=2)
        await manager.connect(ws2, payload2)

        # Broadcast to user 1 only
        message = {"type": "test", "data": "hello"}
        sent = await manager.broadcast_to_user(1, message)

        assert sent == 1
        ws1.send_json.assert_called_once_with(message)
        ws2.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self, manager):
        """Test broadcasting to all users."""
        # Connect multiple users
        ws1 = create_mock_websocket()
        ws2 = create_mock_websocket()
        await manager.connect(ws1, create_test_payload(user_id=1))
        await manager.connect(ws2, create_test_payload(user_id=2))

        message = {"type": "announcement", "data": "global message"}
        sent = await manager.broadcast_to_all(message)

        assert sent == 2
        ws1.send_json.assert_called_once_with(message)
        ws2.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_admin_only(self, manager):
        """Test broadcasting to admin users only."""
        # Connect regular user
        ws_user = create_mock_websocket()
        await manager.connect(ws_user, create_test_payload(user_id=1, is_admin=False))

        # Connect admin user
        ws_admin = create_mock_websocket()
        await manager.connect(ws_admin, create_test_payload(user_id=2, is_admin=True))

        message = {"type": "admin_alert", "data": "admin only"}
        sent = await manager.broadcast_to_all(message, admin_only=True)

        assert sent == 1
        ws_user.send_json.assert_not_called()
        ws_admin.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_trade_notification(self, manager):
        """Test sending trade notifications."""
        ws = create_mock_websocket()
        await manager.connect(ws, create_test_payload(user_id=1))

        trade_data = {
            "trade_id": 123,
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 50000.0,
        }
        await manager.send_trade_notification(1, trade_data)

        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "trade"
        assert call_args["data"] == trade_data

    @pytest.mark.asyncio
    async def test_send_bot_status(self, manager):
        """Test sending bot status updates."""
        ws = create_mock_websocket()
        await manager.connect(ws, create_test_payload(user_id=1))

        await manager.send_bot_status(
            user_id=1,
            bot_id=5,
            status="running",
            details={"symbol": "ETHUSDT"}
        )

        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "bot_status"
        assert call_args["data"]["bot_id"] == 5
        assert call_args["data"]["status"] == "running"
        assert call_args["data"]["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_send_risk_alert(self, manager):
        """Test sending risk alerts."""
        ws = create_mock_websocket()
        await manager.connect(ws, create_test_payload(user_id=1))

        await manager.send_risk_alert(
            user_id=1,
            alert_type="daily_limit",
            message_text="Daily loss limit reached",
            severity="critical"
        )

        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "risk_alert"
        assert call_args["data"]["alert_type"] == "daily_limit"
        assert call_args["data"]["severity"] == "critical"

    @pytest.mark.asyncio
    async def test_get_connected_users(self, manager):
        """Test getting list of connected users."""
        await manager.connect(create_mock_websocket(), create_test_payload(user_id=1))
        await manager.connect(create_mock_websocket(), create_test_payload(user_id=2))
        await manager.connect(create_mock_websocket(), create_test_payload(user_id=3))

        users = manager.get_connected_users()
        assert sorted(users) == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_failed_send_cleans_up_connection(self, manager):
        """Test that failed sends clean up the connection."""
        ws = create_mock_websocket()
        ws.send_json.side_effect = Exception("Connection closed")

        await manager.connect(ws, create_test_payload(user_id=1))
        assert manager.get_user_connection_count(1) == 1

        # This should fail and clean up the connection
        await manager.broadcast_to_user(1, {"test": "message"})
        assert manager.get_user_connection_count(1) == 0


class TestGlobalConnectionManager:
    """Tests for global connection manager singleton."""

    def test_get_connection_manager_singleton(self):
        """Test that get_connection_manager returns a singleton."""
        manager1 = get_connection_manager()
        manager2 = get_connection_manager()
        assert manager1 is manager2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
