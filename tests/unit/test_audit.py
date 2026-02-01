"""
Unit tests for audit logging system.

Tests event logging, retrieval, and retention policies.
"""

import os
import pytest
import tempfile
import asyncio
from datetime import datetime, timedelta

# Set up test environment
import base64
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-purposes-only-32chars"
test_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["ENCRYPTION_MASTER_KEY"] = test_key

from src.security.audit import (
    AuditLogger,
    AuditEventType,
    AuditSeverity,
    AuditEntry,
)


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def audit_logger(temp_db):
    """Create an audit logger instance."""
    return AuditLogger(db_path=temp_db, retention_days=30)


class TestAuditLogging:
    """Tests for basic audit logging."""

    @pytest.mark.asyncio
    async def test_initialize_creates_table(self, audit_logger):
        """Test that initialize creates the audit_logs table."""
        await audit_logger.initialize()
        assert audit_logger._initialized is True

    @pytest.mark.asyncio
    async def test_log_event(self, audit_logger):
        """Test logging a basic event."""
        entry_id = await audit_logger.log(
            event_type=AuditEventType.USER_LOGIN,
            user_id=1,
            ip_address="192.168.1.1",
            severity=AuditSeverity.INFO,
            details={"username": "testuser"},
            success=True,
        )
        assert entry_id > 0

    @pytest.mark.asyncio
    async def test_log_auth_event(self, audit_logger):
        """Test logging an authentication event."""
        entry_id = await audit_logger.log_auth_event(
            event_type=AuditEventType.USER_LOGIN,
            user_id=1,
            ip_address="10.0.0.1",
            username="testuser",
            success=True,
        )
        assert entry_id > 0

    @pytest.mark.asyncio
    async def test_log_failed_login(self, audit_logger):
        """Test logging a failed login attempt."""
        entry_id = await audit_logger.log_auth_event(
            event_type=AuditEventType.USER_LOGIN_FAILED,
            user_id=None,
            ip_address="192.168.1.100",
            username="attacker",
            success=False,
            error_message="Invalid password",
        )
        assert entry_id > 0

    @pytest.mark.asyncio
    async def test_log_credential_event(self, audit_logger):
        """Test logging a credential event."""
        entry_id = await audit_logger.log_credential_event(
            event_type=AuditEventType.CREDENTIAL_CREATE,
            user_id=1,
            credential_id=10,
            ip_address="10.0.0.1",
            credential_name="My Trading Keys",
            success=True,
        )
        assert entry_id > 0

    @pytest.mark.asyncio
    async def test_log_bot_event(self, audit_logger):
        """Test logging a bot management event."""
        entry_id = await audit_logger.log_bot_event(
            event_type=AuditEventType.BOT_START,
            user_id=1,
            bot_id=5,
            ip_address="10.0.0.1",
            bot_name="My Trading Bot",
            success=True,
        )
        assert entry_id > 0

    @pytest.mark.asyncio
    async def test_log_trade_event(self, audit_logger):
        """Test logging a trade event."""
        entry_id = await audit_logger.log_trade_event(
            event_type=AuditEventType.TRADE_ENTRY,
            user_id=1,
            bot_id=5,
            trade_id=100,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            price=50000.0,
            success=True,
        )
        assert entry_id > 0


class TestAuditRetrieval:
    """Tests for retrieving audit logs."""

    @pytest.mark.asyncio
    async def test_get_user_logs(self, audit_logger):
        """Test retrieving logs for a specific user."""
        # Create some logs
        for i in range(5):
            await audit_logger.log_auth_event(
                event_type=AuditEventType.USER_LOGIN,
                user_id=1,
                ip_address="10.0.0.1",
                success=True,
            )

        # Also create logs for another user
        await audit_logger.log_auth_event(
            event_type=AuditEventType.USER_LOGIN,
            user_id=2,
            ip_address="10.0.0.2",
            success=True,
        )

        # Get logs for user 1
        logs = await audit_logger.get_user_logs(user_id=1)
        assert len(logs) == 5
        assert all(log.user_id == 1 for log in logs)

    @pytest.mark.asyncio
    async def test_get_user_logs_with_filter(self, audit_logger):
        """Test filtering logs by event type."""
        # Create mixed events
        await audit_logger.log_auth_event(
            event_type=AuditEventType.USER_LOGIN,
            user_id=1,
            ip_address="10.0.0.1",
            success=True,
        )
        await audit_logger.log_auth_event(
            event_type=AuditEventType.USER_LOGOUT,
            user_id=1,
            ip_address="10.0.0.1",
            success=True,
        )
        await audit_logger.log_bot_event(
            event_type=AuditEventType.BOT_START,
            user_id=1,
            bot_id=1,
            success=True,
        )

        # Filter by login events only
        logs = await audit_logger.get_user_logs(
            user_id=1,
            event_types=[AuditEventType.USER_LOGIN.value],
        )
        assert len(logs) == 1
        assert logs[0].event_type == AuditEventType.USER_LOGIN.value

    @pytest.mark.asyncio
    async def test_get_resource_logs(self, audit_logger):
        """Test retrieving logs for a specific resource."""
        # Create bot events
        await audit_logger.log_bot_event(
            event_type=AuditEventType.BOT_START,
            user_id=1,
            bot_id=5,
            success=True,
        )
        await audit_logger.log_bot_event(
            event_type=AuditEventType.BOT_STOP,
            user_id=1,
            bot_id=5,
            success=True,
        )
        await audit_logger.log_bot_event(
            event_type=AuditEventType.BOT_START,
            user_id=1,
            bot_id=6,  # Different bot
            success=True,
        )

        # Get logs for bot 5
        logs = await audit_logger.get_resource_logs(
            resource_type="bot",
            resource_id=5,
        )
        assert len(logs) == 2
        assert all(log.resource_id == 5 for log in logs)

    @pytest.mark.asyncio
    async def test_get_login_history(self, audit_logger):
        """Test getting login history."""
        # Create login events
        await audit_logger.log_auth_event(
            event_type=AuditEventType.USER_LOGIN,
            user_id=1,
            ip_address="10.0.0.1",
            success=True,
        )
        await audit_logger.log_auth_event(
            event_type=AuditEventType.USER_LOGIN_FAILED,
            user_id=1,
            ip_address="10.0.0.2",
            success=False,
        )
        await audit_logger.log_auth_event(
            event_type=AuditEventType.USER_LOGOUT,
            user_id=1,
            ip_address="10.0.0.1",
            success=True,
        )

        # Get login history
        history = await audit_logger.get_login_history(user_id=1)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_count_failed_logins(self, audit_logger):
        """Test counting failed login attempts."""
        # Create failed logins
        for _ in range(3):
            await audit_logger.log_auth_event(
                event_type=AuditEventType.USER_LOGIN_FAILED,
                user_id=1,
                ip_address="192.168.1.100",
                success=False,
            )

        # Count failed logins
        count = await audit_logger.count_failed_logins(user_id=1)
        assert count == 3

        # Count for specific IP
        count_ip = await audit_logger.count_failed_logins(ip_address="192.168.1.100")
        assert count_ip == 3


class TestAuditRetention:
    """Tests for log retention policies."""

    @pytest.mark.asyncio
    async def test_cleanup_old_logs(self, temp_db):
        """Test cleaning up old logs."""
        # Create logger with short retention
        audit_logger = AuditLogger(db_path=temp_db, retention_days=1)
        await audit_logger.initialize()

        # Create a log
        await audit_logger.log(
            event_type=AuditEventType.USER_LOGIN,
            user_id=1,
            success=True,
        )

        # Manually insert an old log directly
        import aiosqlite
        old_date = (datetime.now() - timedelta(days=5)).isoformat()
        async with aiosqlite.connect(temp_db) as db:
            await db.execute(
                """
                INSERT INTO audit_logs (event_type, user_id, severity, details, success, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (AuditEventType.USER_LOGIN.value, 1, "info", "{}", 1, old_date)
            )
            await db.commit()

        # Verify both logs exist
        logs = await audit_logger.get_user_logs(user_id=1)
        assert len(logs) == 2

        # Run cleanup
        deleted = await audit_logger.cleanup_old_logs()
        assert deleted == 1

        # Verify old log was deleted
        logs = await audit_logger.get_user_logs(user_id=1)
        assert len(logs) == 1


class TestAuditEntry:
    """Tests for AuditEntry data class."""

    def test_to_dict(self):
        """Test converting entry to dictionary."""
        entry = AuditEntry(
            id=1,
            event_type="user.login",
            user_id=1,
            ip_address="10.0.0.1",
            severity="info",
            details={"username": "test"},
            timestamp=datetime.now(),
            success=True,
            error_message=None,
        )

        d = entry.to_dict()
        assert d["id"] == 1
        assert d["event_type"] == "user.login"
        assert d["user_id"] == 1
        assert d["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
