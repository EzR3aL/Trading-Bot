"""
Fernet-based symmetric encryption for API keys and secrets.

Uses ENCRYPTION_KEY from environment. Auto-generates on first use if missing.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def _get_or_create_key() -> bytes:
    """Get encryption key from env or generate and persist one."""
    key = os.getenv("ENCRYPTION_KEY")
    if key:
        return key.encode()

    # Auto-generate and append to .env
    new_key = Fernet.generate_key()
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "a") as f:
            f.write(f"\n# Auto-generated encryption key for API key storage\n")
            f.write(f"ENCRYPTION_KEY={new_key.decode()}\n")
    else:
        with open(env_path, "w") as f:
            f.write(f"ENCRYPTION_KEY={new_key.decode()}\n")

    os.environ["ENCRYPTION_KEY"] = new_key.decode()
    return new_key


_fernet = None


def _get_fernet() -> Fernet:
    """Get or create Fernet instance (lazy singleton)."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_or_create_key())
    return _fernet


def encrypt_value(plaintext: str) -> str:
    """
    Encrypt a plaintext string.

    Args:
        plaintext: The string to encrypt (e.g., an API key)

    Returns:
        Base64-encoded ciphertext string
    """
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string.

    Args:
        ciphertext: Base64-encoded ciphertext from encrypt_value()

    Returns:
        Original plaintext string

    Raises:
        InvalidToken: If the ciphertext is invalid or key has changed
    """
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError("Failed to decrypt value. Encryption key may have changed.")


def mask_value(value: str, visible_chars: int = 4) -> str:
    """
    Mask a sensitive value for display, showing only last N characters.

    Args:
        value: The sensitive string to mask
        visible_chars: Number of characters to show at the end

    Returns:
        Masked string like '****1234'
    """
    if not value or len(value) <= visible_chars:
        return "****"
    return "*" * (len(value) - visible_chars) + value[-visible_chars:]
