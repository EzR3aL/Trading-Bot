"""
Password hashing with bcrypt.

Provides secure password hashing and verification using bcrypt,
with configurable work factor for balancing security and performance.
"""

import bcrypt
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default bcrypt work factor (2^12 = 4096 iterations)
# Increase for more security at the cost of performance
DEFAULT_WORK_FACTOR = 12


class PasswordHandler:
    """
    Password hashing and verification using bcrypt.

    Features:
    - Secure bcrypt hashing with configurable work factor
    - Automatic salt generation
    - Timing-safe comparison

    Usage:
        handler = PasswordHandler()
        hashed = handler.hash("my_password")
        is_valid = handler.verify("my_password", hashed)
    """

    def __init__(self, work_factor: int = DEFAULT_WORK_FACTOR):
        """
        Initialize password handler.

        Args:
            work_factor: bcrypt work factor (cost). Higher = more secure but slower.
                        Recommended: 12 for production (takes ~250ms on modern hardware)
        """
        if work_factor < 4 or work_factor > 31:
            raise ValueError("Work factor must be between 4 and 31")

        self._work_factor = work_factor

    def hash(self, password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            bcrypt hash string (includes salt and work factor)

        Raises:
            ValueError: If password is empty
        """
        if not password:
            raise ValueError("Password cannot be empty")

        # bcrypt has a 72-byte limit, truncate if necessary
        # This is standard bcrypt behavior
        password_bytes = password.encode("utf-8")[:72]

        # Generate salt and hash
        salt = bcrypt.gensalt(rounds=self._work_factor)
        hashed = bcrypt.hashpw(password_bytes, salt)

        return hashed.decode("utf-8")

    def verify(self, password: str, hashed: str) -> bool:
        """
        Verify a password against a hash.

        This is timing-safe to prevent timing attacks.

        Args:
            password: Plain text password to verify
            hashed: bcrypt hash to verify against

        Returns:
            True if password matches, False otherwise
        """
        if not password or not hashed:
            return False

        try:
            # bcrypt has a 72-byte limit, truncate to match hash behavior
            password_bytes = password.encode("utf-8")[:72]
            return bcrypt.checkpw(
                password_bytes,
                hashed.encode("utf-8")
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Password verification error: {e}")
            return False

    def needs_rehash(self, hashed: str) -> bool:
        """
        Check if a hash needs to be rehashed.

        Call this when work factor has been increased to determine
        if existing hashes should be updated on next login.

        Args:
            hashed: Existing bcrypt hash

        Returns:
            True if hash should be upgraded
        """
        try:
            # Extract work factor from hash
            # bcrypt format: $2b$XX$... where XX is the work factor
            parts = hashed.split("$")
            if len(parts) >= 3:
                current_factor = int(parts[2])
                return current_factor < self._work_factor
        except (ValueError, IndexError):
            pass

        return False


def hash_password(password: str, work_factor: int = DEFAULT_WORK_FACTOR) -> str:
    """
    Convenience function to hash a password.

    Args:
        password: Plain text password
        work_factor: bcrypt work factor

    Returns:
        bcrypt hash string
    """
    return PasswordHandler(work_factor).hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """
    Convenience function to verify a password.

    Args:
        password: Plain text password
        hashed: bcrypt hash

    Returns:
        True if password matches
    """
    return PasswordHandler().verify(password, hashed)
