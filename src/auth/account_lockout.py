"""
Account Lockout System.

Prevents brute force attacks by locking accounts after repeated failed login attempts.
Implements exponential backoff and automatic unlock after cooldown period.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple
from dataclasses import dataclass, field
import aiosqlite

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Configuration
MAX_FAILED_ATTEMPTS = 5
BASE_LOCKOUT_MINUTES = 5  # First lockout duration
MAX_LOCKOUT_MINUTES = 60  # Maximum lockout duration
LOCKOUT_MULTIPLIER = 2  # Exponential backoff multiplier
ATTEMPT_WINDOW_MINUTES = 15  # Time window to count failed attempts


@dataclass
class LockoutStatus:
    """Account lockout status."""
    is_locked: bool
    remaining_attempts: int
    lockout_until: Optional[datetime] = None
    lockout_duration_minutes: int = 0

    def to_dict(self) -> dict:
        return {
            "is_locked": self.is_locked,
            "remaining_attempts": self.remaining_attempts,
            "lockout_until": self.lockout_until.isoformat() if self.lockout_until else None,
            "lockout_duration_minutes": self.lockout_duration_minutes,
        }


class AccountLockoutManager:
    """
    Manages account lockout for brute force protection.

    Features:
    - Tracks failed login attempts per username/IP
    - Locks account after MAX_FAILED_ATTEMPTS failures
    - Implements exponential backoff for repeat offenders
    - Automatic unlock after cooldown period
    - Clears failed attempts on successful login

    Usage:
        lockout = AccountLockoutManager()
        await lockout.initialize()

        # Check before login
        status = await lockout.check_lockout("username", "192.168.1.1")
        if status.is_locked:
            raise AccountLockedException(status.lockout_until)

        # Record failed attempt
        await lockout.record_failed_attempt("username", "192.168.1.1")

        # Clear on successful login
        await lockout.clear_failed_attempts("username", "192.168.1.1")
    """

    def __init__(self, db_path: str = "data/users.db"):
        self.db_path = db_path
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the lockout tracking table."""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    ip_address TEXT,
                    attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    success BOOLEAN DEFAULT FALSE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS account_lockouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    locked_until TIMESTAMP NOT NULL,
                    lockout_count INTEGER DEFAULT 1,
                    last_lockout TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes if they don't exist
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_login_attempts_username
                ON login_attempts(username, attempt_time)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_login_attempts_ip
                ON login_attempts(ip_address, attempt_time)
            """)

            await db.commit()

        self._initialized = True
        logger.info("AccountLockoutManager initialized")

    async def check_lockout(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> LockoutStatus:
        """
        Check if an account is locked out.

        Args:
            username: The username to check
            ip_address: Optional IP address for additional tracking

        Returns:
            LockoutStatus with current lockout state
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Check for active lockout
            cursor = await db.execute(
                """
                SELECT locked_until, lockout_count
                FROM account_lockouts
                WHERE username = ? AND datetime(locked_until) > datetime('now')
                """,
                (username.lower(),)
            )
            lockout = await cursor.fetchone()

            if lockout:
                locked_until = datetime.fromisoformat(lockout["locked_until"])
                if locked_until.tzinfo is None:
                    locked_until = locked_until.replace(tzinfo=timezone.utc)

                lockout_duration = min(
                    BASE_LOCKOUT_MINUTES * (LOCKOUT_MULTIPLIER ** (lockout["lockout_count"] - 1)),
                    MAX_LOCKOUT_MINUTES
                )

                return LockoutStatus(
                    is_locked=True,
                    remaining_attempts=0,
                    lockout_until=locked_until,
                    lockout_duration_minutes=int(lockout_duration)
                )

            # Count recent failed attempts
            # Use datetime() function in SQLite for proper comparison
            cursor = await db.execute(
                """
                SELECT COUNT(*) as count
                FROM login_attempts
                WHERE username = ?
                  AND datetime(attempt_time) > datetime('now', ? || ' minutes')
                  AND success = FALSE
                """,
                (username.lower(), f"-{ATTEMPT_WINDOW_MINUTES}")
            )
            result = await cursor.fetchone()
            failed_count = result["count"] if result else 0

            remaining = max(0, MAX_FAILED_ATTEMPTS - failed_count)

            return LockoutStatus(
                is_locked=False,
                remaining_attempts=remaining,
                lockout_until=None,
                lockout_duration_minutes=0
            )

    async def record_failed_attempt(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> LockoutStatus:
        """
        Record a failed login attempt and potentially lock the account.

        Args:
            username: The username that failed to login
            ip_address: IP address of the attempt

        Returns:
            Updated LockoutStatus (may now be locked)
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Record the failed attempt
            await db.execute(
                """
                INSERT INTO login_attempts (username, ip_address, success)
                VALUES (?, ?, FALSE)
                """,
                (username.lower(), ip_address)
            )

            # Count recent failed attempts using SQLite datetime function
            cursor = await db.execute(
                """
                SELECT COUNT(*) as count
                FROM login_attempts
                WHERE username = ?
                  AND datetime(attempt_time) > datetime('now', ? || ' minutes')
                  AND success = FALSE
                """,
                (username.lower(), f"-{ATTEMPT_WINDOW_MINUTES}")
            )
            result = await cursor.fetchone()
            failed_count = result["count"] if result else 0

            # Check if we need to lock the account
            if failed_count >= MAX_FAILED_ATTEMPTS:
                # Get current lockout count for exponential backoff
                cursor = await db.execute(
                    """
                    SELECT lockout_count FROM account_lockouts WHERE username = ?
                    """,
                    (username.lower(),)
                )
                existing = await cursor.fetchone()
                lockout_count = (existing["lockout_count"] + 1) if existing else 1

                # Calculate lockout duration with exponential backoff
                lockout_minutes = min(
                    BASE_LOCKOUT_MINUTES * (LOCKOUT_MULTIPLIER ** (lockout_count - 1)),
                    MAX_LOCKOUT_MINUTES
                )

                locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)

                # Upsert lockout record
                await db.execute(
                    """
                    INSERT INTO account_lockouts (username, locked_until, lockout_count, last_lockout)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(username) DO UPDATE SET
                        locked_until = excluded.locked_until,
                        lockout_count = excluded.lockout_count,
                        last_lockout = CURRENT_TIMESTAMP
                    """,
                    (username.lower(), locked_until.isoformat(), lockout_count)
                )

                await db.commit()

                logger.warning(
                    f"Account locked: {username} for {lockout_minutes} minutes "
                    f"(lockout #{lockout_count})"
                )

                return LockoutStatus(
                    is_locked=True,
                    remaining_attempts=0,
                    lockout_until=locked_until,
                    lockout_duration_minutes=int(lockout_minutes)
                )

            await db.commit()

            remaining = max(0, MAX_FAILED_ATTEMPTS - failed_count)
            logger.info(f"Failed login for {username}: {remaining} attempts remaining")

            return LockoutStatus(
                is_locked=False,
                remaining_attempts=remaining,
                lockout_until=None,
                lockout_duration_minutes=0
            )

    async def clear_failed_attempts(
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Clear failed attempts after successful login.

        Also resets lockout count after a successful login.

        Args:
            username: The username that successfully logged in
            ip_address: IP address of the successful login
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # Record successful login
            await db.execute(
                """
                INSERT INTO login_attempts (username, ip_address, success)
                VALUES (?, ?, TRUE)
                """,
                (username.lower(), ip_address)
            )

            # Clear failed login attempts (reset the counter)
            await db.execute(
                """
                DELETE FROM login_attempts
                WHERE username = ? AND success = FALSE
                """,
                (username.lower(),)
            )

            # Clear lockout record (resets exponential backoff on success)
            await db.execute(
                """
                DELETE FROM account_lockouts WHERE username = ?
                """,
                (username.lower(),)
            )

            await db.commit()

            logger.debug(f"Cleared failed attempts for {username}")

    async def get_failed_attempt_count(
        self,
        username: str,
        window_minutes: int = ATTEMPT_WINDOW_MINUTES
    ) -> int:
        """
        Get the number of failed attempts in the time window.

        Args:
            username: The username to check
            window_minutes: Time window in minutes

        Returns:
            Number of failed attempts
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """
                SELECT COUNT(*) as count
                FROM login_attempts
                WHERE username = ?
                  AND datetime(attempt_time) > datetime('now', ? || ' minutes')
                  AND success = FALSE
                """,
                (username.lower(), f"-{window_minutes}")
            )
            result = await cursor.fetchone()

            return result["count"] if result else 0

    async def cleanup_old_records(self, days: int = 30) -> int:
        """
        Clean up old login attempt records.

        Args:
            days: Delete records older than this many days

        Returns:
            Number of records deleted
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            cursor = await db.execute(
                """
                DELETE FROM login_attempts WHERE attempt_time < ?
                """,
                (cutoff,)
            )
            deleted = cursor.rowcount

            await db.commit()

            logger.info(f"Cleaned up {deleted} old login attempt records")
            return deleted


class AccountLockedException(Exception):
    """Raised when an account is locked."""

    def __init__(self, lockout_until: datetime, message: str = None):
        self.lockout_until = lockout_until
        self.message = message or f"Account is locked until {lockout_until.isoformat()}"
        super().__init__(self.message)


# Singleton instance
_lockout_manager: Optional[AccountLockoutManager] = None


async def get_lockout_manager() -> AccountLockoutManager:
    """Get the singleton AccountLockoutManager instance."""
    global _lockout_manager
    if _lockout_manager is None:
        _lockout_manager = AccountLockoutManager()
        await _lockout_manager.initialize()
    return _lockout_manager
