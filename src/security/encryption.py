"""
AES-256-GCM encryption for API credentials.

Uses the cryptography library for authenticated encryption,
ensuring both confidentiality and integrity of stored credentials.
"""

import os
import base64
import secrets
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Key length for AES-256
KEY_LENGTH = 32  # 256 bits
# Nonce length for GCM (96 bits recommended)
NONCE_LENGTH = 12


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


class CredentialEncryption:
    """
    AES-256-GCM encryption for sensitive credentials.

    Features:
    - Authenticated encryption (prevents tampering)
    - Unique nonce per encryption (prevents replay attacks)
    - Base64 encoding for storage compatibility

    Usage:
        encryption = CredentialEncryption()  # Uses ENCRYPTION_MASTER_KEY env var
        encrypted = encryption.encrypt("my_secret_api_key")
        decrypted = encryption.decrypt(encrypted)
    """

    def __init__(self, master_key: Optional[bytes] = None):
        """
        Initialize encryption with master key.

        Args:
            master_key: 32-byte key for AES-256. If None, loads from
                       ENCRYPTION_MASTER_KEY environment variable.

        Raises:
            ValueError: If key is missing or wrong length
        """
        if master_key is None:
            key_b64 = os.environ.get("ENCRYPTION_MASTER_KEY")
            if not key_b64:
                raise ValueError(
                    "ENCRYPTION_MASTER_KEY environment variable not set. "
                    "Generate one with: python -c \"import secrets; import base64; "
                    "print(base64.b64encode(secrets.token_bytes(32)).decode())\""
                )
            try:
                master_key = base64.b64decode(key_b64)
            except Exception as e:
                raise ValueError(f"Invalid ENCRYPTION_MASTER_KEY format: {e}")

        if len(master_key) != KEY_LENGTH:
            raise ValueError(
                f"Master key must be exactly {KEY_LENGTH} bytes (256 bits), "
                f"got {len(master_key)} bytes"
            )

        self._aesgcm = AESGCM(master_key)
        logger.debug("CredentialEncryption initialized")

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string using AES-256-GCM.

        Args:
            plaintext: The string to encrypt

        Returns:
            Base64-encoded ciphertext (nonce + encrypted data + auth tag)

        Raises:
            EncryptionError: If encryption fails
        """
        if not plaintext:
            raise EncryptionError("Cannot encrypt empty string")

        try:
            # Generate unique nonce for this encryption
            nonce = secrets.token_bytes(NONCE_LENGTH)

            # Encrypt the plaintext
            ciphertext = self._aesgcm.encrypt(
                nonce,
                plaintext.encode("utf-8"),
                None  # No associated data
            )

            # Combine nonce + ciphertext and encode as base64
            combined = nonce + ciphertext
            return base64.b64encode(combined).decode("utf-8")

        except Exception as e:
            logger.error(f"Encryption failed: {type(e).__name__}")
            raise EncryptionError(f"Encryption failed: {e}")

    def decrypt(self, encrypted: str) -> str:
        """
        Decrypt a base64-encoded ciphertext.

        Args:
            encrypted: Base64-encoded string from encrypt()

        Returns:
            Original plaintext string

        Raises:
            EncryptionError: If decryption fails (wrong key, tampered data, etc.)
        """
        if not encrypted:
            raise EncryptionError("Cannot decrypt empty string")

        try:
            # Decode from base64
            combined = base64.b64decode(encrypted)

            if len(combined) < NONCE_LENGTH + 16:  # minimum: nonce + auth tag
                raise EncryptionError("Ciphertext too short")

            # Split nonce and ciphertext
            nonce = combined[:NONCE_LENGTH]
            ciphertext = combined[NONCE_LENGTH:]

            # Decrypt and verify
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")

        except InvalidTag:
            logger.error("Decryption failed: authentication tag invalid (tampered or wrong key)")
            raise EncryptionError("Decryption failed: data may be tampered or wrong key")
        except Exception as e:
            logger.error(f"Decryption failed: {type(e).__name__}")
            raise EncryptionError(f"Decryption failed: {e}")

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new random master key.

        Returns:
            Base64-encoded 32-byte key suitable for ENCRYPTION_MASTER_KEY
        """
        key = secrets.token_bytes(KEY_LENGTH)
        return base64.b64encode(key).decode("utf-8")

    @staticmethod
    def is_valid_key(key_b64: str) -> bool:
        """
        Check if a base64-encoded key is valid.

        Args:
            key_b64: Base64-encoded key to validate

        Returns:
            True if key is valid (correct length)
        """
        try:
            key = base64.b64decode(key_b64)
            return len(key) == KEY_LENGTH
        except Exception:
            return False


def generate_master_key() -> str:
    """
    Generate a new master key for credential encryption.

    Returns:
        Base64-encoded 32-byte key

    Example:
        key = generate_master_key()
        print(f"ENCRYPTION_MASTER_KEY={key}")
    """
    return CredentialEncryption.generate_key()


if __name__ == "__main__":
    # Generate a new master key when run directly
    print("Generated ENCRYPTION_MASTER_KEY:")
    print(generate_master_key())
