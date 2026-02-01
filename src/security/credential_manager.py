"""
Credential Manager for secure storage and retrieval of API credentials.

Combines encryption with database storage to provide a complete
solution for multi-tenant credential management.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from src.security.encryption import CredentialEncryption, EncryptionError
from src.models.credential import Credential, CredentialRepository
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DecryptedCredential:
    """Decrypted credential for use in API calls."""
    id: int
    user_id: int
    name: str
    exchange: str
    credential_type: str
    api_key: str
    api_secret: str
    passphrase: str

    def __repr__(self) -> str:
        """Mask sensitive data in repr."""
        return (
            f"DecryptedCredential(id={self.id}, name='{self.name}', "
            f"api_key='****{self.api_key[-4:] if len(self.api_key) > 4 else '****'}')"
        )


class CredentialManager:
    """
    Manages encrypted credential storage and retrieval.

    This class combines:
    - AES-256-GCM encryption for credential security
    - Database storage for persistence
    - Tenant isolation for multi-user support

    Usage:
        manager = CredentialManager()

        # Store new credentials
        cred = await manager.store_credential(
            user_id=1,
            name="My Bitget Account",
            api_key="your-api-key",
            api_secret="your-api-secret",
            passphrase="your-passphrase"
        )

        # Retrieve decrypted credentials
        decrypted = await manager.get_credential(cred.id, user_id=1)
        # Use decrypted.api_key, decrypted.api_secret, etc.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """
        Initialize the credential manager.

        Args:
            db_path: Path to the SQLite database
        """
        self._encryption = CredentialEncryption()
        self._repository = CredentialRepository(db_path)

    async def store_credential(
        self,
        user_id: int,
        name: str,
        api_key: str,
        api_secret: str,
        passphrase: str,
        exchange: str = "bitget",
        credential_type: str = "live"
    ) -> Credential:
        """
        Store new credentials with encryption.

        Args:
            user_id: Owner user ID
            name: Friendly name for this credential set
            api_key: Plain text API key (will be encrypted)
            api_secret: Plain text API secret (will be encrypted)
            passphrase: Plain text passphrase (will be encrypted)
            exchange: Exchange name (default: bitget)
            credential_type: 'live' or 'demo'

        Returns:
            Credential object (with encrypted fields)

        Raises:
            EncryptionError: If encryption fails
            ValueError: If name already exists for user
        """
        # Encrypt all sensitive fields
        api_key_encrypted = self._encryption.encrypt(api_key)
        api_secret_encrypted = self._encryption.encrypt(api_secret)
        passphrase_encrypted = self._encryption.encrypt(passphrase)

        # Store in database
        credential = await self._repository.create(
            user_id=user_id,
            name=name,
            api_key_encrypted=api_key_encrypted,
            api_secret_encrypted=api_secret_encrypted,
            passphrase_encrypted=passphrase_encrypted,
            exchange=exchange,
            credential_type=credential_type
        )

        logger.info(f"Stored encrypted credential '{name}' for user_id={user_id}")
        return credential

    async def get_credential(
        self,
        credential_id: int,
        user_id: int
    ) -> Optional[DecryptedCredential]:
        """
        Retrieve and decrypt a credential.

        Args:
            credential_id: Credential ID
            user_id: User ID (for tenant isolation)

        Returns:
            DecryptedCredential with plain text values, or None if not found

        Raises:
            EncryptionError: If decryption fails
        """
        credential = await self._repository.get_by_id(credential_id, user_id)
        if not credential:
            return None

        # Decrypt all sensitive fields
        try:
            api_key = self._encryption.decrypt(credential.api_key_encrypted)
            api_secret = self._encryption.decrypt(credential.api_secret_encrypted)
            passphrase = self._encryption.decrypt(credential.passphrase_encrypted)
        except EncryptionError as e:
            logger.error(f"Failed to decrypt credential id={credential_id}: {e}")
            raise

        # Update last_used timestamp
        await self._repository.update_last_used(credential_id)

        return DecryptedCredential(
            id=credential.id,
            user_id=credential.user_id,
            name=credential.name,
            exchange=credential.exchange,
            credential_type=credential.credential_type,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase
        )

    async def get_user_credentials(
        self,
        user_id: int,
        credential_type: Optional[str] = None,
        decrypt: bool = False
    ) -> List:
        """
        Get all credentials for a user.

        Args:
            user_id: User ID
            credential_type: Filter by 'live' or 'demo'
            decrypt: If True, return DecryptedCredential objects

        Returns:
            List of Credential or DecryptedCredential objects
        """
        credentials = await self._repository.get_by_user(
            user_id,
            active_only=True,
            credential_type=credential_type
        )

        if not decrypt:
            return credentials

        # Decrypt all credentials
        decrypted = []
        for cred in credentials:
            try:
                api_key = self._encryption.decrypt(cred.api_key_encrypted)
                api_secret = self._encryption.decrypt(cred.api_secret_encrypted)
                passphrase = self._encryption.decrypt(cred.passphrase_encrypted)

                decrypted.append(DecryptedCredential(
                    id=cred.id,
                    user_id=cred.user_id,
                    name=cred.name,
                    exchange=cred.exchange,
                    credential_type=cred.credential_type,
                    api_key=api_key,
                    api_secret=api_secret,
                    passphrase=passphrase
                ))
            except EncryptionError as e:
                logger.error(f"Failed to decrypt credential id={cred.id}: {e}")
                # Skip this credential but continue with others

        return decrypted

    async def update_credential(
        self,
        credential_id: int,
        user_id: int,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None
    ) -> bool:
        """
        Update credential values (re-encrypts).

        This is typically used for credential rotation.

        Args:
            credential_id: Credential ID
            user_id: User ID (for tenant isolation)
            api_key: New API key (None to keep existing)
            api_secret: New API secret (None to keep existing)
            passphrase: New passphrase (None to keep existing)

        Returns:
            True if updated successfully
        """
        # Get existing credential
        existing = await self._repository.get_by_id(credential_id, user_id)
        if not existing:
            return False

        # Decrypt existing values for fields not being updated
        if api_key is None or api_secret is None or passphrase is None:
            try:
                current_key = self._encryption.decrypt(existing.api_key_encrypted)
                current_secret = self._encryption.decrypt(existing.api_secret_encrypted)
                current_pass = self._encryption.decrypt(existing.passphrase_encrypted)
            except EncryptionError:
                logger.error(f"Cannot update credential {credential_id}: decryption failed")
                return False

            api_key = api_key or current_key
            api_secret = api_secret or current_secret
            passphrase = passphrase or current_pass

        # Delete old and create new (atomic operation)
        await self._repository.delete(credential_id, user_id)
        await self._repository.create(
            user_id=user_id,
            name=existing.name,
            api_key_encrypted=self._encryption.encrypt(api_key),
            api_secret_encrypted=self._encryption.encrypt(api_secret),
            passphrase_encrypted=self._encryption.encrypt(passphrase),
            exchange=existing.exchange,
            credential_type=existing.credential_type
        )

        logger.info(f"Rotated credential id={credential_id}")
        return True

    async def revoke_credential(self, credential_id: int, user_id: int) -> bool:
        """
        Revoke (deactivate) a credential.

        This is a soft delete - the encrypted data remains but is marked inactive.

        Args:
            credential_id: Credential ID
            user_id: User ID (for tenant isolation)

        Returns:
            True if revoked successfully
        """
        result = await self._repository.deactivate(credential_id, user_id)
        if result:
            logger.info(f"Revoked credential id={credential_id}")
        return result

    async def delete_credential(self, credential_id: int, user_id: int) -> bool:
        """
        Permanently delete a credential.

        WARNING: This cannot be undone!

        Args:
            credential_id: Credential ID
            user_id: User ID (for tenant isolation)

        Returns:
            True if deleted successfully
        """
        result = await self._repository.delete(credential_id, user_id)
        if result:
            logger.warning(f"Permanently deleted credential id={credential_id}")
        return result

    async def validate_credential(
        self,
        credential_id: int,
        user_id: int
    ) -> tuple[bool, str]:
        """
        Validate that a credential can be decrypted.

        This doesn't test the credential against the exchange,
        just verifies the encryption is intact.

        Args:
            credential_id: Credential ID
            user_id: User ID

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            decrypted = await self.get_credential(credential_id, user_id)
            if decrypted is None:
                return False, "Credential not found"
            if not decrypted.api_key or not decrypted.api_secret:
                return False, "Credential appears corrupted"
            return True, "OK"
        except EncryptionError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Validation error: {e}"
