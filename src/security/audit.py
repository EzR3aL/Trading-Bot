"""
Audit Logging Module for Multi-Tenant Trading Platform.

Provides comprehensive logging of sensitive operations including:
- User authentication (login, logout, registration)
- Credential management (add, remove, access)
- Bot lifecycle (start, stop, configuration changes)
- Trade execution
- Configuration changes

All logs include user_id, timestamp, and IP address for compliance.
"""

import aiosqlite
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AuditEventType(Enum):
    """Types of auditable events."""
    # Authentication
    USER_REGISTER = "user.register"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_PASSWORD_CHANGE = "user.password_change"
    USER_PROFILE_UPDATE = "user.profile_update"
    USER_ROLE_CHANGE = "user.role_change"
    USER_STATUS_CHANGE = "user.status_change"
    USER_DELETE = "user.delete"

    # Credentials
    CREDENTIAL_CREATE = "credential.create"
    CREDENTIAL_UPDATE = "credential.update"
    CREDENTIAL_DELETE = "credential.delete"
    CREDENTIAL_ACCESS = "credential.access"
    CREDENTIAL_TEST = "credential.test"

    # Bot Management
    BOT_CREATE = "bot.create"
    BOT_DELETE = "bot.delete"
    BOT_START = "bot.start"
    BOT_STOP = "bot.stop"
    BOT_RESTART = "bot.restart"
    BOT_CONFIG_UPDATE = "bot.config_update"

    # Trading
    TRADE_ENTRY = "trade.entry"
    TRADE_EXIT = "trade.exit"
    TRADE_CANCELLED = "trade.cancelled"

    # Risk Management
    RISK_LIMIT_HIT = "risk.limit_hit"
    RISK_CONFIG_UPDATE = "risk.config_update"

    # System
    SYSTEM_ERROR = "system.error"
    ADMIN_ACTION = "admin.action"


class AuditSeverity(Enum):
    """Severity levels for audit events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEntry:
    """An audit log entry."""
    id: Optional[int]
    event_type: str
    user_id: Optional[int]
    ip_address: Optional[str]
    severity: str
    details: dict
    timestamp: datetime
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "id": self.id,
            "event_type": self.event_type,
            "user_id": self.user_id,
            "ip_address": self.ip_address,
            "severity": self.severity,
            "details": self.details,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "success": self.success,
            "error_message": self.error_message,
        }


class AuditLogger:
    """
    Centralized audit logging for the trading platform.

    Features:
    - Async database storage
    - Automatic log retention (default 90 days)
    - Query by user, event type, time range
    - JSON-serialized event details
    """

    def __init__(self, db_path: str = "data/trades.db", retention_days: int = 90):
        """
        Initialize the audit logger.

        Args:
            db_path: Path to the database
            retention_days: Number of days to retain logs
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the audit log table."""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    user_id INTEGER,
                    ip_address TEXT,
                    severity TEXT DEFAULT 'info',
                    details TEXT,
                    resource_type TEXT,
                    resource_id INTEGER,
                    success INTEGER DEFAULT 1,
                    error_message TEXT,
                    timestamp TEXT NOT NULL
                )
            """)

            # Create indexes for common queries
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_logs(user_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_logs(event_type)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_logs(resource_type, resource_id)"
            )

            await db.commit()

        self._initialized = True
        logger.info("Audit logger initialized")

    async def log(
        self,
        event_type: AuditEventType,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        severity: AuditSeverity = AuditSeverity.INFO,
        details: Optional[Dict[str, Any]] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> int:
        """
        Log an audit event.

        Args:
            event_type: Type of event
            user_id: User who triggered the event
            ip_address: Client IP address
            severity: Event severity level
            details: Additional event details (JSON-serializable)
            resource_type: Type of resource affected (bot, credential, etc.)
            resource_id: ID of the resource affected
            success: Whether the operation succeeded
            error_message: Error message if failed

        Returns:
            ID of the created audit entry
        """
        if not self._initialized:
            await self.initialize()

        timestamp = datetime.now().isoformat()
        details_json = json.dumps(details or {})

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO audit_logs (
                    event_type, user_id, ip_address, severity,
                    details, resource_type, resource_id,
                    success, error_message, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_type.value,
                    user_id,
                    ip_address,
                    severity.value,
                    details_json,
                    resource_type,
                    resource_id,
                    1 if success else 0,
                    error_message,
                    timestamp,
                )
            )
            await db.commit()
            entry_id = cursor.lastrowid

        # Also log to file logger for immediate visibility
        log_msg = (
            f"AUDIT: {event_type.value} | user={user_id} | "
            f"ip={ip_address} | success={success}"
        )
        if error_message:
            log_msg += f" | error={error_message}"

        if severity == AuditSeverity.CRITICAL:
            logger.critical(log_msg)
        elif severity == AuditSeverity.ERROR:
            logger.error(log_msg)
        elif severity == AuditSeverity.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        return entry_id

    async def log_auth_event(
        self,
        event_type: AuditEventType,
        user_id: Optional[int],
        ip_address: Optional[str],
        username: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> int:
        """Log an authentication event."""
        details = {"username": username} if username else {}
        severity = AuditSeverity.INFO if success else AuditSeverity.WARNING

        return await self.log(
            event_type=event_type,
            user_id=user_id,
            ip_address=ip_address,
            severity=severity,
            details=details,
            success=success,
            error_message=error_message,
        )

    async def log_credential_event(
        self,
        event_type: AuditEventType,
        user_id: int,
        credential_id: int,
        ip_address: Optional[str],
        credential_name: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> int:
        """Log a credential management event."""
        details = {"credential_name": credential_name} if credential_name else {}

        return await self.log(
            event_type=event_type,
            user_id=user_id,
            ip_address=ip_address,
            severity=AuditSeverity.WARNING if event_type == AuditEventType.CREDENTIAL_ACCESS else AuditSeverity.INFO,
            details=details,
            resource_type="credential",
            resource_id=credential_id,
            success=success,
            error_message=error_message,
        )

    async def log_bot_event(
        self,
        event_type: AuditEventType,
        user_id: int,
        bot_id: int,
        ip_address: Optional[str] = None,
        bot_name: Optional[str] = None,
        config_changes: Optional[dict] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> int:
        """Log a bot management event."""
        details = {}
        if bot_name:
            details["bot_name"] = bot_name
        if config_changes:
            details["config_changes"] = config_changes

        return await self.log(
            event_type=event_type,
            user_id=user_id,
            ip_address=ip_address,
            severity=AuditSeverity.INFO,
            details=details,
            resource_type="bot",
            resource_id=bot_id,
            success=success,
            error_message=error_message,
        )

    async def log_trade_event(
        self,
        event_type: AuditEventType,
        user_id: int,
        bot_id: int,
        trade_id: Optional[int] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        size: Optional[float] = None,
        price: Optional[float] = None,
        pnl: Optional[float] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> int:
        """Log a trade execution event."""
        details = {
            "bot_id": bot_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
        }
        if pnl is not None:
            details["pnl"] = pnl

        return await self.log(
            event_type=event_type,
            user_id=user_id,
            severity=AuditSeverity.INFO,
            details=details,
            resource_type="trade",
            resource_id=trade_id,
            success=success,
            error_message=error_message,
        )

    async def get_user_logs(
        self,
        user_id: int,
        limit: int = 100,
        offset: int = 0,
        event_types: Optional[List[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[AuditEntry]:
        """
        Get audit logs for a specific user.

        Args:
            user_id: User to query logs for
            limit: Maximum number of entries to return
            offset: Offset for pagination
            event_types: Filter by event types
            start_date: Filter logs after this date
            end_date: Filter logs before this date

        Returns:
            List of audit entries
        """
        if not self._initialized:
            await self.initialize()

        query = "SELECT * FROM audit_logs WHERE user_id = ?"
        params = [user_id]

        if event_types:
            placeholders = ",".join("?" * len(event_types))
            query += f" AND event_type IN ({placeholders})"
            params.extend(event_types)

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def get_resource_logs(
        self,
        resource_type: str,
        resource_id: int,
        user_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """
        Get audit logs for a specific resource.

        Args:
            resource_type: Type of resource (bot, credential, trade)
            resource_id: ID of the resource
            user_id: Optional user filter (for tenant isolation)
            limit: Maximum number of entries

        Returns:
            List of audit entries
        """
        if not self._initialized:
            await self.initialize()

        query = "SELECT * FROM audit_logs WHERE resource_type = ? AND resource_id = ?"
        params = [resource_type, resource_id]

        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def cleanup_old_logs(self) -> int:
        """
        Delete logs older than the retention period.

        Returns:
            Number of logs deleted
        """
        if not self._initialized:
            await self.initialize()

        cutoff_date = datetime.now() - timedelta(days=self.retention_days)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM audit_logs WHERE timestamp < ?",
                (cutoff_date.isoformat(),)
            )
            await db.commit()
            deleted = cursor.rowcount

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} audit logs older than {self.retention_days} days")

        return deleted

    async def get_login_history(
        self,
        user_id: int,
        limit: int = 20,
    ) -> List[AuditEntry]:
        """Get recent login history for a user."""
        return await self.get_user_logs(
            user_id=user_id,
            limit=limit,
            event_types=[
                AuditEventType.USER_LOGIN.value,
                AuditEventType.USER_LOGIN_FAILED.value,
                AuditEventType.USER_LOGOUT.value,
            ],
        )

    async def get_all_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        event_types: Optional[List[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[AuditEntry]:
        """
        Get all audit logs (admin view).

        Args:
            limit: Maximum number of entries to return
            offset: Offset for pagination
            event_types: Filter by event types
            start_date: Filter logs after this date
            end_date: Filter logs before this date

        Returns:
            List of audit entries
        """
        if not self._initialized:
            await self.initialize()

        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []

        if event_types:
            placeholders = ",".join("?" * len(event_types))
            query += f" AND event_type IN ({placeholders})"
            params.extend(event_types)

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date.isoformat())

        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def count_failed_logins(
        self,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> int:
        """
        Count failed login attempts.

        Useful for detecting brute force attacks.
        """
        if not self._initialized:
            await self.initialize()

        query = "SELECT COUNT(*) FROM audit_logs WHERE event_type = ?"
        params = [AuditEventType.USER_LOGIN_FAILED.value]

        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)

        if ip_address is not None:
            query += " AND ip_address = ?"
            params.append(ip_address)

        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since.isoformat())

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()

        return row[0] if row else 0

    def _row_to_entry(self, row) -> AuditEntry:
        """Convert database row to AuditEntry."""
        return AuditEntry(
            id=row["id"],
            event_type=row["event_type"],
            user_id=row["user_id"],
            ip_address=row["ip_address"],
            severity=row["severity"],
            details=json.loads(row["details"]) if row["details"] else {},
            timestamp=datetime.fromisoformat(row["timestamp"]),
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            success=bool(row["success"]),
            error_message=row["error_message"],
        )


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


async def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
        await _audit_logger.initialize()
    return _audit_logger
