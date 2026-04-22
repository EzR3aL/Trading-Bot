"""JWT token creation and validation.

Supports both HS256 (legacy) and RS256 (preferred). When both are configured,
signing uses RS256 and verification accepts either, enabling a 14-day rollover
window. See Anleitungen/auth-key-rotation.md.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Response
from jwt.exceptions import PyJWTError

from src.utils.logger import get_logger

_jwt_logger = get_logger(__name__)

ALGORITHM_HS256 = "HS256"
ALGORITHM_RS256 = "RS256"

ACCESS_TOKEN_EXPIRE_MINUTES = 240  # 4 hours
# 14 days is the industry default for refresh tokens. Combined with session
# rotation and `token_version`, this limits theft windows while still covering
# typical user dormancy (weekends, short trips).
REFRESH_TOKEN_EXPIRE_DAYS = 14

REFRESH_COOKIE_NAME = "refresh_token"
ACCESS_COOKIE_NAME = "access_token"


def _get_hs_secret() -> str:
    return os.getenv("JWT_SECRET_KEY", "")


def _get_rs_private_key() -> str:
    return os.getenv("JWT_PRIVATE_KEY", "")


def _get_rs_public_key() -> str:
    return os.getenv("JWT_PUBLIC_KEY", "")


def _rs256_configured() -> bool:
    return bool(_get_rs_private_key() and _get_rs_public_key())


def _signing_algorithm() -> str:
    return ALGORITHM_RS256 if _rs256_configured() else ALGORITHM_HS256


def _signing_key() -> str:
    return _get_rs_private_key() if _rs256_configured() else _get_hs_secret()


def validate_jwt_config() -> None:
    """Validate JWT config at startup. Accepts either RS256 key-pair or HS256 secret."""
    if _rs256_configured():
        priv = _get_rs_private_key()
        pub = _get_rs_public_key()
        if "BEGIN" not in priv or "BEGIN" not in pub:
            msg = "FATAL: JWT_PRIVATE_KEY / JWT_PUBLIC_KEY must be PEM-encoded."
            _jwt_logger.critical(msg)
            raise RuntimeError(msg)
        _jwt_logger.info("AUTH: JWT configured with RS256 (asymmetric). HS256 fallback: %s", bool(_get_hs_secret()))
        return

    key = _get_hs_secret()
    if not key:
        msg = (
            "FATAL: No JWT signing material configured. "
            "Set either JWT_PRIVATE_KEY + JWT_PUBLIC_KEY (RS256, preferred) "
            "or JWT_SECRET_KEY (HS256, legacy). "
            "See Anleitungen/auth-key-rotation.md."
        )
        _jwt_logger.critical(msg)
        raise RuntimeError(msg)

    if len(key) < 32:
        msg = (
            "FATAL: JWT_SECRET_KEY is too short (minimum 32 characters). "
            "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
        _jwt_logger.critical(msg)
        raise RuntimeError(msg)

    _jwt_logger.warning("AUTH: JWT configured with HS256 only. RS256 is preferred — see Anleitungen/auth-key-rotation.md.")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, _signing_key(), algorithm=_signing_algorithm())


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, _signing_key(), algorithm=_signing_algorithm())


def decode_token(token: str, expected_type: Optional[str] = None) -> Optional[dict]:
    """Decode and validate a JWT. Tries RS256 then HS256 (dual-validate window).

    Returns None on any failure: invalid signature, expired, wrong type, malformed.
    """
    payload = _try_decode(token, ALGORITHM_RS256, _get_rs_public_key())
    if payload is None:
        payload = _try_decode(token, ALGORITHM_HS256, _get_hs_secret())
    if payload is None:
        return None
    if expected_type and payload.get("type") != expected_type:
        return None
    return payload


def _try_decode(token: str, algorithm: str, key: str) -> Optional[dict]:
    if not key:
        return None
    try:
        return jwt.decode(token, key, algorithms=[algorithm])
    except PyJWTError:
        return None


def set_access_cookie(response: Response, access_token: str) -> None:
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
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        httponly=True,
        path="/api",
    )


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
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
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        path="/api/auth",
    )
