"""
Credential model for storing encrypted API keys.

Handles storage and retrieval of exchange API credentials
with encryption at rest.
"""

import aiosqlite
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Credential:
    """API Credential dataclass (encrypted fields)."""
    id: Optional[int]
    user_id: int
    name: str
    exchange: str
    credential_type: str  # 'live' or 'demo'
    api_key_encrypted: str
    api_secret_encrypted: str
    passphrase_encrypted: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    last_used: Optional[datetime] = None

    def to_dict(self, mask_keys: bool = True) -> dict:
        """
        Convert to dictionary for API responses.

        Args:
            mask_keys: If True, only show last 4 characters of keys
        """
        if mask_keys:
            # Mask the encrypted keys for display
            api_key_display = "****" + self.api_key_encrypted[-4:] if len(self.api_key_encrypted) > 4 else "****"
        else:
            api_key_display = self.api_key_encrypted

        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "exchange": self.exchange,
            "credential_type": self.credential_type,
            "api_key": api_key_display,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
        }


class CredentialRepository:
    """
    Repository for API credential database operations.

    All credentials are stored encrypted. The encryption/decryption
    is handled by the CredentialManager in src/security/.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """Initialize the credential repository."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def create(
        self,
        user_id: int,
        name: str,
        api_key_encrypted: str,
        api_secret_encrypted: str,
        passphrase_encrypted: str,
        exchange: str = "bitget",
        credential_type: str = "live"
    ) -> Credential:
        """
        Store new encrypted credentials.

        Args:
            user_id: Owner user ID
            name: Friendly name for this credential set
            api_key_encrypted: Encrypted API key
            api_secret_encrypted: Encrypted API secret
            passphrase_encrypted: Encrypted passphrase
            exchange: Exchange name (default: bitget)
            credential_type: 'live' or 'demo'

        Returns:
            Created Credential object

        Raises:
            ValueError: If name already exists for user
        """
        if credential_type not in ('live', 'demo'):
            raise ValueError("credential_type must be 'live' or 'demo'")

        async with aiosqlite.connect(self.db_path) as db:
            try:
                cursor = await db.execute(
                    """
                    INSERT INTO user_credentials (
                        user_id, name, exchange, credential_type,
                        api_key_encrypted, api_secret_encrypted, passphrase_encrypted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id, name, exchange, credential_type,
                        api_key_encrypted, api_secret_encrypted, passphrase_encrypted
                    )
                )
                await db.commit()
                credential_id = cursor.lastrowid

                logger.info(f"Created credential '{name}' for user_id={user_id}")

                return Credential(
                    id=credential_id,
                    user_id=user_id,
                    name=name,
                    exchange=exchange,
                    credential_type=credential_type,
                    api_key_encrypted=api_key_encrypted,
                    api_secret_encrypted=api_secret_encrypted,
                    passphrase_encrypted=passphrase_encrypted,
                    is_active=True,
                    created_at=datetime.now(),
                    last_used=None
                )
            except aiosqlite.IntegrityError:
                raise ValueError(f"Credential name '{name}' already exists for this user")

    async def get_by_id(self, credential_id: int, user_id: int) -> Optional[Credential]:
        """
        Get credential by ID with user verification.

        Args:
            credential_id: Credential ID
            user_id: User ID (for tenant isolation)

        Returns:
            Credential if found and belongs to user, None otherwise
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM user_credentials WHERE id = ? AND user_id = ?",
                (credential_id, user_id)
            )
            row = await cursor.fetchone()
            return self._row_to_credential(row) if row else None

    async def get_by_user(
        self,
        user_id: int,
        active_only: bool = True,
        credential_type: Optional[str] = None
    ) -> List[Credential]:
        """
        Get all credentials for a user.

        Args:
            user_id: User ID
            active_only: Only return active credentials
            credential_type: Filter by 'live' or 'demo'

        Returns:
            List of credentials
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            query = "SELECT * FROM user_credentials WHERE user_id = ?"
            params = [user_id]

            if active_only:
                query += " AND is_active = 1"

            if credential_type:
                query += " AND credential_type = ?"
                params.append(credential_type)

            query += " ORDER BY created_at DESC"

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [self._row_to_credential(row) for row in rows]

    async def update_last_used(self, credential_id: int) -> bool:
        """Update the last_used timestamp."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE user_credentials SET last_used = ? WHERE id = ?",
                (datetime.now(), credential_id)
            )
            await db.commit()
            return True

    async def deactivate(self, credential_id: int, user_id: int) -> bool:
        """
        Deactivate a credential (soft delete).

        Args:
            credential_id: Credential ID
            user_id: User ID (for tenant isolation)
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE user_credentials SET is_active = 0
                WHERE id = ? AND user_id = ?
                """,
                (credential_id, user_id)
            )
            await db.commit()
            if cursor.rowcount > 0:
                logger.info(f"Deactivated credential id={credential_id}")
                return True
            return False

    async def delete(self, credential_id: int, user_id: int) -> bool:
        """
        Permanently delete a credential.

        Args:
            credential_id: Credential ID
            user_id: User ID (for tenant isolation)
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM user_credentials WHERE id = ? AND user_id = ?",
                (credential_id, user_id)
            )
            await db.commit()
            if cursor.rowcount > 0:
                logger.warning(f"Deleted credential id={credential_id}")
                return True
            return False

    async def count_by_user(self, user_id: int) -> int:
        """Count credentials for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM user_credentials WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    def _row_to_credential(self, row) -> Credential:
        """Convert database row to Credential object."""
        return Credential(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            exchange=row["exchange"],
            credential_type=row["credential_type"],
            api_key_encrypted=row["api_key_encrypted"],
            api_secret_encrypted=row["api_secret_encrypted"],
            passphrase_encrypted=row["passphrase_encrypted"],
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            last_used=datetime.fromisoformat(row["last_used"]) if row["last_used"] else None,
        )
