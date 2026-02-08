"""JWT token creation and validation."""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from src.utils.logger import get_logger

_jwt_logger = get_logger(__name__)

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def validate_jwt_config() -> None:
    """Validate that JWT_SECRET_KEY is configured.

    Call this during application startup (lifespan) instead of at import
    time, so the error is logged properly rather than crashing via sys.exit().
    """
    if not SECRET_KEY:
        msg = (
            "FATAL: JWT_SECRET_KEY environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\" "
            "Then add it to your .env file."
        )
        _jwt_logger.critical(msg)
        raise RuntimeError(msg)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        data: Payload data (must include 'sub' with user_id)
        expires_delta: Custom expiration time

    Returns:
        Encoded JWT string
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """
    Create a JWT refresh token with longer expiration.

    Args:
        data: Payload data (must include 'sub' with user_id)

    Returns:
        Encoded JWT string
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and validate a JWT token.

    Args:
        token: Encoded JWT string

    Returns:
        Decoded payload dict or None if invalid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
