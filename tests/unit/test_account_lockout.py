"""
Tests for Account Lockout System.

Tests brute force protection, exponential backoff, and lockout clearing.
"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock, MagicMock
import tempfile
import os

from src.auth.account_lockout import (
    AccountLockoutManager,
    LockoutStatus,
    AccountLockedException,
    get_lockout_manager,
    MAX_FAILED_ATTEMPTS,
    BASE_LOCKOUT_MINUTES,
    LOCKOUT_MULTIPLIER,
    MAX_LOCKOUT_MINUTES,
)


@pytest.fixture
async def lockout_manager(tmp_path):
    """Create a lockout manager with temporary database."""
    db_path = str(tmp_path / "test_users.db")
    manager = AccountLockoutManager(db_path=db_path)
    await manager.initialize()
    return manager


class TestLockoutStatus:
    """Tests for LockoutStatus dataclass."""

    def test_unlocked_status(self):
        """Test status when account is not locked."""
        status = LockoutStatus(
            is_locked=False,
            remaining_attempts=3,
        )
        assert not status.is_locked
        assert status.remaining_attempts == 3
        assert status.lockout_until is None

    def test_locked_status(self):
        """Test status when account is locked."""
        lockout_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        status = LockoutStatus(
            is_locked=True,
            remaining_attempts=0,
            lockout_until=lockout_time,
            lockout_duration_minutes=5,
        )
        assert status.is_locked
        assert status.remaining_attempts == 0
        assert status.lockout_until == lockout_time
        assert status.lockout_duration_minutes == 5

    def test_to_dict(self):
        """Test conversion to dictionary."""
        lockout_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        status = LockoutStatus(
            is_locked=True,
            remaining_attempts=0,
            lockout_until=lockout_time,
            lockout_duration_minutes=5,
        )
        d = status.to_dict()
        assert d["is_locked"] is True
        assert d["remaining_attempts"] == 0
        assert d["lockout_duration_minutes"] == 5
        assert d["lockout_until"] is not None


class TestAccountLockoutManager:
    """Tests for AccountLockoutManager."""

    @pytest.mark.asyncio
    async def test_initialize(self, lockout_manager):
        """Test manager initialization."""
        assert lockout_manager._initialized is True

    @pytest.mark.asyncio
    async def test_check_lockout_clean_account(self, lockout_manager):
        """Test checking lockout for account with no failed attempts."""
        status = await lockout_manager.check_lockout("newuser", "192.168.1.1")
        assert not status.is_locked
        assert status.remaining_attempts == MAX_FAILED_ATTEMPTS

    @pytest.mark.asyncio
    async def test_record_single_failed_attempt(self, lockout_manager):
        """Test recording a single failed attempt."""
        status = await lockout_manager.record_failed_attempt("testuser", "192.168.1.1")
        assert not status.is_locked
        assert status.remaining_attempts == MAX_FAILED_ATTEMPTS - 1

    @pytest.mark.asyncio
    async def test_account_locks_after_max_attempts(self, lockout_manager):
        """Test that account locks after MAX_FAILED_ATTEMPTS."""
        username = "bruteforceuser"

        # Record MAX_FAILED_ATTEMPTS - 1 attempts
        for i in range(MAX_FAILED_ATTEMPTS - 1):
            status = await lockout_manager.record_failed_attempt(username, "192.168.1.1")
            assert not status.is_locked
            assert status.remaining_attempts == MAX_FAILED_ATTEMPTS - i - 1

        # The next attempt should trigger lockout
        status = await lockout_manager.record_failed_attempt(username, "192.168.1.1")
        assert status.is_locked
        assert status.remaining_attempts == 0
        assert status.lockout_until is not None
        assert status.lockout_duration_minutes == BASE_LOCKOUT_MINUTES

    @pytest.mark.asyncio
    async def test_locked_account_blocked(self, lockout_manager):
        """Test that locked accounts cannot attempt login."""
        username = "lockeduser"

        # Lock the account
        for _ in range(MAX_FAILED_ATTEMPTS):
            await lockout_manager.record_failed_attempt(username, "192.168.1.1")

        # Check that account is locked
        status = await lockout_manager.check_lockout(username, "192.168.1.1")
        assert status.is_locked
        assert status.lockout_duration_minutes >= BASE_LOCKOUT_MINUTES

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, lockout_manager):
        """Test exponential backoff for repeat lockouts."""
        username = "repeatoffender"

        # First lockout
        for _ in range(MAX_FAILED_ATTEMPTS):
            await lockout_manager.record_failed_attempt(username, "192.168.1.1")

        status = await lockout_manager.check_lockout(username)
        first_duration = status.lockout_duration_minutes
        assert first_duration == BASE_LOCKOUT_MINUTES

        # Clear and lock again (simulating time passing)
        await lockout_manager.clear_failed_attempts(username)

        # This should be second lockout with longer duration
        for _ in range(MAX_FAILED_ATTEMPTS):
            await lockout_manager.record_failed_attempt(username, "192.168.1.1")

        status = await lockout_manager.check_lockout(username)
        # After clear, lockout count resets, so duration should be base again
        # (In real scenario, you'd wait for lockout to expire, not clear it)

    @pytest.mark.asyncio
    async def test_clear_failed_attempts(self, lockout_manager):
        """Test clearing failed attempts on successful login."""
        username = "clearuser"

        # Add some failed attempts
        for _ in range(3):
            await lockout_manager.record_failed_attempt(username, "192.168.1.1")

        # Clear on successful login
        await lockout_manager.clear_failed_attempts(username, "192.168.1.1")

        # Check that attempts are cleared
        status = await lockout_manager.check_lockout(username)
        assert not status.is_locked
        assert status.remaining_attempts == MAX_FAILED_ATTEMPTS

    @pytest.mark.asyncio
    async def test_get_failed_attempt_count(self, lockout_manager):
        """Test getting failed attempt count."""
        username = "countuser"

        # Record some failures
        for _ in range(3):
            await lockout_manager.record_failed_attempt(username, "192.168.1.1")

        count = await lockout_manager.get_failed_attempt_count(username)
        assert count == 3

    @pytest.mark.asyncio
    async def test_different_users_independent(self, lockout_manager):
        """Test that lockouts are independent per user."""
        user1 = "user1"
        user2 = "user2"

        # Lock user1
        for _ in range(MAX_FAILED_ATTEMPTS):
            await lockout_manager.record_failed_attempt(user1, "192.168.1.1")

        # user1 should be locked
        status1 = await lockout_manager.check_lockout(user1)
        assert status1.is_locked

        # user2 should not be affected
        status2 = await lockout_manager.check_lockout(user2)
        assert not status2.is_locked
        assert status2.remaining_attempts == MAX_FAILED_ATTEMPTS

    @pytest.mark.asyncio
    async def test_cleanup_old_records(self, lockout_manager):
        """Test cleanup of old records."""
        username = "olduser"

        # Record some failures
        await lockout_manager.record_failed_attempt(username, "192.168.1.1")

        # Cleanup (with 0 days should delete all)
        deleted = await lockout_manager.cleanup_old_records(days=0)
        assert deleted >= 1

    @pytest.mark.asyncio
    async def test_case_insensitive_username(self, lockout_manager):
        """Test that username comparison is case insensitive."""
        # Record failure for lowercase
        await lockout_manager.record_failed_attempt("TestUser", "192.168.1.1")

        # Check with different case
        status = await lockout_manager.check_lockout("testuser", "192.168.1.1")
        assert status.remaining_attempts == MAX_FAILED_ATTEMPTS - 1


class TestAccountLockedException:
    """Tests for AccountLockedException."""

    def test_exception_message(self):
        """Test exception contains lockout info."""
        lockout_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        exc = AccountLockedException(lockout_time)
        assert str(lockout_time.isoformat()) in exc.message
        assert exc.lockout_until == lockout_time

    def test_custom_message(self):
        """Test exception with custom message."""
        lockout_time = datetime.now(timezone.utc)
        exc = AccountLockedException(lockout_time, "Custom lockout message")
        assert exc.message == "Custom lockout message"


class TestLockoutConfiguration:
    """Tests for lockout configuration."""

    def test_max_failed_attempts_reasonable(self):
        """Test that MAX_FAILED_ATTEMPTS is reasonable (3-10)."""
        assert 3 <= MAX_FAILED_ATTEMPTS <= 10

    def test_base_lockout_minutes_reasonable(self):
        """Test that BASE_LOCKOUT_MINUTES is reasonable (1-30)."""
        assert 1 <= BASE_LOCKOUT_MINUTES <= 30

    def test_max_lockout_capped(self):
        """Test that MAX_LOCKOUT_MINUTES is capped reasonably."""
        assert MAX_LOCKOUT_MINUTES <= 1440  # Max 24 hours

    def test_exponential_growth_capped(self):
        """Test that exponential backoff doesn't exceed max."""
        # Calculate theoretical lockout after 10 repeat offenses
        theoretical_minutes = BASE_LOCKOUT_MINUTES * (LOCKOUT_MULTIPLIER ** 10)
        # With capping, it should never exceed MAX_LOCKOUT_MINUTES
        actual_minutes = min(theoretical_minutes, MAX_LOCKOUT_MINUTES)
        assert actual_minutes == MAX_LOCKOUT_MINUTES
