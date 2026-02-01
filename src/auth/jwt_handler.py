"""
JWT Token Handler for authentication.

Handles creation and validation of JWT access and refresh tokens.
Uses HS256 algorithm with configurable expiry times.
"""

import os
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional, Dict, Any

from jose import jwt, JWTError, ExpiredSignatureError

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default expiry times
DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 15
DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 7

# JWT algorithm
ALGORITHM = "HS256"


class TokenError(Exception):
    """Base exception for token errors."""
    pass


class TokenExpiredError(TokenError):
    """Raised when token has expired."""
    pass


class TokenInvalidError(TokenError):
    """Raised when token is invalid."""
    pass


@dataclass
class TokenPair:
    """Access and refresh token pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES * 60  # seconds

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_in": self.expires_in,
        }


@dataclass
class TokenPayload:
    """Decoded token payload."""
    user_id: int
    username: str
    is_admin: bool
    token_type: str  # 'access' or 'refresh'
    exp: datetime
    iat: datetime
    jti: str  # JWT ID for revocation


class JWTHandler:
    """
    JWT token handler for authentication.

    Features:
    - Access tokens (short-lived, 15 minutes default)
    - Refresh tokens (long-lived, 7 days default)
    - Token revocation support via JTI
    - Secure token hashing for storage

    Usage:
        handler = JWTHandler()
        tokens = handler.create_token_pair(user_id=1, username="john", is_admin=False)
        payload = handler.verify_access_token(tokens.access_token)
    """

    def __init__(
        self,
        secret_key: Optional[str] = None,
        access_token_expire_minutes: int = DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES,
        refresh_token_expire_days: int = DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS,
    ):
        """
        Initialize JWT handler.

        Args:
            secret_key: Secret for signing tokens. If None, uses JWT_SECRET env var.
            access_token_expire_minutes: Access token lifetime in minutes
            refresh_token_expire_days: Refresh token lifetime in days
        """
        if secret_key is None:
            secret_key = os.environ.get("JWT_SECRET")
            if not secret_key:
                raise ValueError(
                    "JWT_SECRET environment variable not set. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )

        if len(secret_key) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")

        self._secret_key = secret_key
        self._access_expire = timedelta(minutes=access_token_expire_minutes)
        self._refresh_expire = timedelta(days=refresh_token_expire_days)

    def create_token_pair(
        self,
        user_id: int,
        username: str,
        is_admin: bool = False,
    ) -> TokenPair:
        """
        Create access and refresh token pair.

        Args:
            user_id: User ID
            username: Username
            is_admin: Whether user has admin privileges

        Returns:
            TokenPair with access and refresh tokens
        """
        now = datetime.now(timezone.utc)

        # Create access token
        access_jti = secrets.token_urlsafe(16)
        access_payload = {
            "sub": str(user_id),
            "username": username,
            "is_admin": is_admin,
            "type": "access",
            "exp": now + self._access_expire,
            "iat": now,
            "jti": access_jti,
        }
        access_token = jwt.encode(access_payload, self._secret_key, algorithm=ALGORITHM)

        # Create refresh token
        refresh_jti = secrets.token_urlsafe(16)
        refresh_payload = {
            "sub": str(user_id),
            "username": username,
            "is_admin": is_admin,
            "type": "refresh",
            "exp": now + self._refresh_expire,
            "iat": now,
            "jti": refresh_jti,
        }
        refresh_token = jwt.encode(refresh_payload, self._secret_key, algorithm=ALGORITHM)

        logger.info(f"Created token pair for user_id={user_id}")

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(self._access_expire.total_seconds()),
        )

    def verify_access_token(self, token: str) -> TokenPayload:
        """
        Verify and decode an access token.

        Args:
            token: JWT access token

        Returns:
            TokenPayload with decoded data

        Raises:
            TokenExpiredError: If token has expired
            TokenInvalidError: If token is invalid
        """
        return self._verify_token(token, expected_type="access")

    def verify_refresh_token(self, token: str) -> TokenPayload:
        """
        Verify and decode a refresh token.

        Args:
            token: JWT refresh token

        Returns:
            TokenPayload with decoded data

        Raises:
            TokenExpiredError: If token has expired
            TokenInvalidError: If token is invalid
        """
        return self._verify_token(token, expected_type="refresh")

    def _verify_token(self, token: str, expected_type: str) -> TokenPayload:
        """Internal token verification."""
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[ALGORITHM])

            # Verify token type
            token_type = payload.get("type")
            if token_type != expected_type:
                raise TokenInvalidError(f"Expected {expected_type} token, got {token_type}")

            return TokenPayload(
                user_id=int(payload["sub"]),
                username=payload["username"],
                is_admin=payload.get("is_admin", False),
                token_type=token_type,
                exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
                iat=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
                jti=payload["jti"],
            )

        except ExpiredSignatureError:
            logger.debug(f"{expected_type.capitalize()} token expired")
            raise TokenExpiredError("Token has expired")
        except JWTError as e:
            logger.warning(f"Invalid {expected_type} token: {e}")
            raise TokenInvalidError(f"Invalid token: {e}")

    def refresh_access_token(
        self,
        refresh_token: str,
    ) -> TokenPair:
        """
        Create new token pair from refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New TokenPair

        Raises:
            TokenExpiredError: If refresh token has expired
            TokenInvalidError: If refresh token is invalid
        """
        payload = self.verify_refresh_token(refresh_token)

        return self.create_token_pair(
            user_id=payload.user_id,
            username=payload.username,
            is_admin=payload.is_admin,
        )

    @staticmethod
    def hash_token(token: str) -> str:
        """
        Create a hash of a token for storage.

        Use this to store tokens in the database for revocation checking.

        Args:
            token: Token to hash

        Returns:
            SHA-256 hash of token
        """
        return hashlib.sha256(token.encode()).hexdigest()

    def get_token_jti(self, token: str) -> Optional[str]:
        """
        Extract JTI from token without full verification.

        Useful for token blacklisting before expiry check.

        Args:
            token: JWT token

        Returns:
            JTI string or None if invalid
        """
        try:
            # Decode without verification to get JTI
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[ALGORITHM],
                options={"verify_exp": False}
            )
            return payload.get("jti")
        except JWTError:
            return None
