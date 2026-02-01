"""
FastAPI authentication dependencies.

Provides dependency injection for route authentication,
extracting and validating user identity from JWT tokens.
"""

import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.auth.jwt_handler import (
    JWTHandler,
    TokenPayload,
    TokenExpiredError,
    TokenInvalidError,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# HTTP Bearer security scheme
security = HTTPBearer(auto_error=False)

# Global JWT handler (initialized on first use)
_jwt_handler: Optional[JWTHandler] = None


def get_jwt_handler() -> JWTHandler:
    """Get or create the JWT handler singleton."""
    global _jwt_handler
    if _jwt_handler is None:
        _jwt_handler = JWTHandler()
    return _jwt_handler


async def get_token_payload(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
) -> TokenPayload:
    """
    Extract and validate JWT token from Authorization header.

    Args:
        credentials: HTTP Authorization credentials
        jwt_handler: JWT handler instance

    Returns:
        TokenPayload with user information

    Raises:
        HTTPException: 401 if token is missing, invalid, or expired
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt_handler.verify_access_token(credentials.credentials)
        return payload

    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except TokenInvalidError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    payload: TokenPayload = Depends(get_token_payload),
) -> int:
    """
    Get the current authenticated user's ID.

    Use this dependency in routes that require authentication.

    Args:
        payload: Validated token payload

    Returns:
        User ID from token

    Example:
        @app.get("/api/me")
        async def get_profile(user_id: int = Depends(get_current_user)):
            return {"user_id": user_id}
    """
    return payload.user_id


async def get_current_user_payload(
    payload: TokenPayload = Depends(get_token_payload),
) -> TokenPayload:
    """
    Get the full token payload for the current user.

    Use this when you need more than just the user ID.

    Returns:
        Full TokenPayload with user_id, username, is_admin, etc.
    """
    return payload


async def get_current_admin_user(
    payload: TokenPayload = Depends(get_token_payload),
) -> int:
    """
    Get the current user if they are an admin.

    Use this for admin-only routes.

    Args:
        payload: Validated token payload

    Returns:
        Admin user ID

    Raises:
        HTTPException: 403 if user is not an admin
    """
    if not payload.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return payload.user_id


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    jwt_handler: JWTHandler = Depends(get_jwt_handler),
) -> Optional[int]:
    """
    Get the current user ID if authenticated, None otherwise.

    Use this for routes that work for both authenticated and anonymous users.

    Returns:
        User ID if authenticated, None otherwise
    """
    if credentials is None:
        return None

    try:
        payload = jwt_handler.verify_access_token(credentials.credentials)
        return payload.user_id
    except (TokenExpiredError, TokenInvalidError):
        return None


class SessionManager:
    """
    Manages user sessions in the database.

    Handles session creation, validation, and revocation
    for token blacklisting.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        self.db_path = db_path

    async def create_session(
        self,
        user_id: int,
        access_token_hash: str,
        refresh_token_hash: str,
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> int:
        """
        Create a new session record.

        Args:
            user_id: User ID
            access_token_hash: SHA-256 hash of access token
            refresh_token_hash: SHA-256 hash of refresh token
            expires_at: Session expiry time
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            Session ID
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO user_sessions (
                    user_id, token_hash, refresh_token_hash,
                    expires_at, ip_address, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, access_token_hash, refresh_token_hash,
                    expires_at, ip_address, user_agent
                )
            )
            await db.commit()
            return cursor.lastrowid

    async def is_session_valid(self, token_hash: str) -> bool:
        """
        Check if a session is valid (not revoked and not expired).

        Args:
            token_hash: SHA-256 hash of the token

        Returns:
            True if session is valid
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT id FROM user_sessions
                WHERE token_hash = ?
                AND revoked_at IS NULL
                AND expires_at > ?
                """,
                (token_hash, datetime.now(timezone.utc))
            )
            row = await cursor.fetchone()
            return row is not None

    async def revoke_session(self, token_hash: str) -> bool:
        """
        Revoke a session (logout).

        Args:
            token_hash: SHA-256 hash of the token

        Returns:
            True if session was revoked
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE user_sessions
                SET revoked_at = ?
                WHERE token_hash = ?
                """,
                (datetime.now(timezone.utc), token_hash)
            )
            await db.commit()
            return cursor.rowcount > 0

    async def revoke_all_user_sessions(self, user_id: int) -> int:
        """
        Revoke all sessions for a user (logout everywhere).

        Args:
            user_id: User ID

        Returns:
            Number of sessions revoked
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE user_sessions
                SET revoked_at = ?
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (datetime.now(timezone.utc), user_id)
            )
            await db.commit()
            return cursor.rowcount

    async def cleanup_expired_sessions(self) -> int:
        """
        Remove expired sessions from the database.

        Call this periodically to clean up old sessions.

        Returns:
            Number of sessions deleted
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM user_sessions WHERE expires_at < ?",
                (datetime.now(timezone.utc),)
            )
            await db.commit()
            return cursor.rowcount
