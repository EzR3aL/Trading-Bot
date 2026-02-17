"""
Fernet-based symmetric encryption for API keys and secrets.

Uses ENCRYPTION_KEY from environment. Auto-generates on first use if missing
in development mode only.

Key Rotation (v1.11.0):
- Encrypted values are prefixed with the key version: "v1:ciphertext"
- During rotation, set ENCRYPTION_KEY to the new key and
  ENCRYPTION_KEY_PREVIOUS to the old key.
- decrypt_value() tries the current key first, then falls back to previous.
- Legacy values without a version prefix are treated as v1.

SECURITY NOTE: In production (ENVIRONMENT=production), the ENCRYPTION_KEY
environment variable MUST be explicitly set. Auto-generation is disabled
in production to prevent accidental key rotation, which would render all
previously encrypted API keys unreadable.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from src.utils.logger import get_logger

_encryption_logger = get_logger(__name__)

# Current key version — bump when rotating
_KEY_VERSION = "v1"


def _get_or_create_key() -> bytes:
    """Get encryption key from env or generate and persist one.

    In production (ENVIRONMENT=production), the ENCRYPTION_KEY must be
    explicitly provided. Auto-generation is only allowed in development.
    """
    key = os.getenv("ENCRYPTION_KEY")
    if key:
        key_bytes = key.encode()
        # Validate key is a proper Fernet key (44 bytes base64-encoded = 32 bytes raw)
        if len(key_bytes) < 32:
            raise ValueError(
                "ENCRYPTION_KEY is too short. Generate a proper key with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        # Validate it's a valid Fernet key format
        try:
            Fernet(key_bytes)
        except (ValueError, Exception) as e:
            raise ValueError(
                f"ENCRYPTION_KEY is not a valid Fernet key: {e}. "
                'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from e
        return key_bytes

    environment = os.getenv("ENVIRONMENT", "development").lower()

    if environment == "production":
        raise RuntimeError(
            "FATAL: ENCRYPTION_KEY environment variable is not set and "
            "auto-generation is disabled in production mode. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "Then add ENCRYPTION_KEY=<key> to your environment."
        )

    # Auto-generate and append to .env (development only)
    _encryption_logger.warning(
        "ENCRYPTION_KEY not set — auto-generating for development. "
        "Set ENCRYPTION_KEY explicitly for production use."
    )
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
_fernet_previous = None


def _get_fernet() -> Fernet:
    """Get or create Fernet instance for the current key (lazy singleton)."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_or_create_key())
    return _fernet


def _get_fernet_previous():
    """Get Fernet instance for the previous key (for rotation), or None."""
    global _fernet_previous
    if _fernet_previous is None:
        prev_key = os.getenv("ENCRYPTION_KEY_PREVIOUS")
        if prev_key and len(prev_key.encode()) >= 32:
            _fernet_previous = Fernet(prev_key.encode())
        else:
            return None
    return _fernet_previous


def encrypt_value(plaintext: str) -> str:
    """
    Encrypt a plaintext string with key version prefix.

    Args:
        plaintext: The string to encrypt (e.g., an API key)

    Returns:
        Versioned ciphertext string: "v1:base64ciphertext"
    """
    if not plaintext:
        return ""
    ciphertext = _get_fernet().encrypt(plaintext.encode()).decode()
    return f"{_KEY_VERSION}:{ciphertext}"


def decrypt_value(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string, supporting key rotation.

    Tries the current key first. If that fails and ENCRYPTION_KEY_PREVIOUS
    is set, tries the previous key (for rotation window).

    Args:
        ciphertext: Versioned or legacy ciphertext from encrypt_value()

    Returns:
        Original plaintext string

    Raises:
        ValueError: If decryption fails with all available keys
    """
    if not ciphertext:
        return ""

    # Strip version prefix if present (v1:ciphertext)
    raw_ciphertext = ciphertext
    if ":" in ciphertext and ciphertext.split(":")[0].startswith("v"):
        raw_ciphertext = ciphertext.split(":", 1)[1]

    # Try current key first
    try:
        return _get_fernet().decrypt(raw_ciphertext.encode()).decode()
    except InvalidToken:
        pass

    # Try previous key (rotation window)
    prev = _get_fernet_previous()
    if prev:
        try:
            _encryption_logger.info("Decrypting with previous key (rotation in progress)")
            return prev.decrypt(raw_ciphertext.encode()).decode()
        except InvalidToken:
            pass

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
