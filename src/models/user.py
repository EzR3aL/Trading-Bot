"""
User model for multi-tenant authentication.

Handles user registration, authentication, and profile management.
"""

import aiosqlite
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class User:
    """User account dataclass."""
    id: Optional[int]
    username: str
    email: str
    password_hash: str
    is_active: bool = True
    is_admin: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """Convert to dictionary for API responses."""
        data = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_sensitive:
            data["password_hash"] = self.password_hash
        return data


class UserRepository:
    """
    Repository for user database operations.

    Provides CRUD operations for user accounts with proper
    multi-tenant isolation.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """Initialize the user repository."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def create(
        self,
        username: str,
        email: str,
        password_hash: str,
        is_admin: bool = False
    ) -> User:
        """
        Create a new user.

        Args:
            username: Unique username
            email: Unique email address
            password_hash: Bcrypt hashed password
            is_admin: Whether user has admin privileges

        Returns:
            Created User object

        Raises:
            ValueError: If username or email already exists
        """
        async with aiosqlite.connect(self.db_path) as db:
            try:
                cursor = await db.execute(
                    """
                    INSERT INTO users (username, email, password_hash, is_admin)
                    VALUES (?, ?, ?, ?)
                    """,
                    (username, email.lower(), password_hash, int(is_admin))
                )
                await db.commit()
                user_id = cursor.lastrowid

                logger.info(f"Created user: {username} (id={user_id})")

                return User(
                    id=user_id,
                    username=username,
                    email=email.lower(),
                    password_hash=password_hash,
                    is_active=True,
                    is_admin=is_admin,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
            except aiosqlite.IntegrityError as e:
                if "username" in str(e).lower():
                    raise ValueError(f"Username '{username}' already exists")
                elif "email" in str(e).lower():
                    raise ValueError(f"Email '{email}' already exists")
                raise

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            return self._row_to_user(row) if row else None

    async def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            )
            row = await cursor.fetchone()
            return self._row_to_user(row) if row else None

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM users WHERE email = ?",
                (email.lower(),)
            )
            row = await cursor.fetchone()
            return self._row_to_user(row) if row else None

    async def get_all(self, include_inactive: bool = False, limit: int = 100) -> List[User]:
        """
        Get all users.

        Args:
            include_inactive: Whether to include deactivated users
            limit: Maximum number of users to return

        Returns:
            List of users
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            if include_inactive:
                cursor = await db.execute(
                    "SELECT * FROM users ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM users WHERE is_active = 1 ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )

            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows]

    async def update(self, user: User) -> bool:
        """
        Update user profile.

        Args:
            user: User object with updated fields

        Returns:
            True if updated successfully
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE users SET
                    username = ?,
                    email = ?,
                    password_hash = ?,
                    is_active = ?,
                    is_admin = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    user.username,
                    user.email.lower(),
                    user.password_hash,
                    int(user.is_active),
                    int(user.is_admin),
                    datetime.now(),
                    user.id
                )
            )
            await db.commit()
            logger.info(f"Updated user: {user.username} (id={user.id})")
            return True

    async def update_password(self, user_id: int, new_password_hash: str) -> bool:
        """Update user password."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE users SET
                    password_hash = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (new_password_hash, datetime.now(), user_id)
            )
            await db.commit()
            logger.info(f"Updated password for user id={user_id}")
            return True

    async def deactivate(self, user_id: int) -> bool:
        """Deactivate a user account (soft delete)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE users SET
                    is_active = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (datetime.now(), user_id)
            )
            await db.commit()
            logger.info(f"Deactivated user id={user_id}")
            return True

    async def activate(self, user_id: int) -> bool:
        """Reactivate a user account."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE users SET
                    is_active = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (datetime.now(), user_id)
            )
            await db.commit()
            logger.info(f"Activated user id={user_id}")
            return True

    async def delete(self, user_id: int) -> bool:
        """
        Permanently delete a user account.

        WARNING: This will cascade delete all user data!
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            await db.commit()
            logger.warning(f"Permanently deleted user id={user_id}")
            return True

    async def count(self, active_only: bool = True) -> int:
        """Count total users."""
        async with aiosqlite.connect(self.db_path) as db:
            if active_only:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM users WHERE is_active = 1"
                )
            else:
                cursor = await db.execute("SELECT COUNT(*) FROM users")
            row = await cursor.fetchone()
            return row[0] if row else 0

    def _row_to_user(self, row) -> User:
        """Convert database row to User object."""
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            is_active=bool(row["is_active"]),
            is_admin=bool(row["is_admin"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )
