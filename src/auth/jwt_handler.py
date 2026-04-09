"""JWT token creation and validation."""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Response
from jwt.exceptions import PyJWTError

from src.utils.logger import get_logger

_jwt_logger = get_logger(__name__)

ALGORITHM = "HS256"
# 4 hours — shorter TTL for financial security; refresh token handles session continuity
ACCESS_TOKEN_EXPIRE_MINUTES = 240
# Refresh token: 90 days. Bumped from 30 because users complained about
# being logged out — the previous TTL hit users who only opened the app
# every couple of weeks.
REFRESH_TOKEN_EXPIRE_DAYS = 90

REFRESH_COOKIE_NAME = "refresh_token"


def _get_secret_key() -> str:
    """Lazy-load JWT secret key from environment.

    Reads at call time (not import time) so that load_dotenv() in
    main_app.py has already populated the environment.
    """
    return os.getenv("JWT_SECRET_KEY", "")


def validate_jwt_config() -> None:
    """Validate that JWT_SECRET_KEY is configured and strong enough.

    Call this during application startup (lifespan) instead of at import
    time, so the error is logged properly rather than crashing via sys.exit().
    """
    key = _get_secret_key()
    if not key:
        msg = (
            "FATAL: JWT_SECRET_KEY environment variable is not set. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\" "
            "Then add it to your .env file."
        )
        _jwt_logger.critical(msg)
        raise RuntimeError(msg)

    if len(key) < 32:
        msg = (
            "FATAL: JWT_SECRET_KEY is too short (minimum 32 characters). "
            "Generate a strong key with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
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
    return jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)


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
    return jwt.encode(to_encode, _get_secret_key(), algorithm=ALGORITHM)


def decode_token(token: str, expected_type: Optional[str] = None) -> Optional[dict]:
    """
    Decode and validate a JWT token.

    Args:
        token: Encoded JWT string
        expected_type: If set, reject tokens whose "type" field doesn't match
                       (e.g. "access" or "refresh")

    Returns:
        Decoded payload dict or None if invalid / wrong type
    """
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        if expected_type and payload.get("type") != expected_type:
            return None
        return payload
    except PyJWTError:
        return None


ACCESS_COOKIE_NAME = "access_token"


def set_access_cookie(response: Response, access_token: str) -> None:
    """Set the access token as an httpOnly secure cookie.

    Security properties:
    - httponly: JS cannot read the cookie (XSS protection)
    - secure: Only sent over HTTPS (except in development)
    - samesite=lax: Prevents CSRF on cross-origin POST
    - path=/api: Cookie sent to all API endpoints
    """
    environment = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = environment == "production"

    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        path="/api",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def clear_access_cookie(response: Response) -> None:
    """Clear the access token cookie (on logout or token revocation)."""
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        httponly=True,
        path="/api",
    )


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set the refresh token as an httpOnly secure cookie.

    Security properties:
    - httponly: JS cannot read the cookie (XSS protection)
    - secure: Only sent over HTTPS (except in development)
    - samesite=lax: Prevents CSRF on cross-origin POST
    - path=/api/auth: Cookie only sent to auth endpoints (minimizes exposure)
    """
    environment = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = environment == "production"

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        path="/api/auth",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie (on logout or token revocation)."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        path="/api/auth",
    )
