"""FastAPI authentication dependencies."""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.jwt_handler import decode_token
from src.errors import (
    ERR_ADMIN_REQUIRED,
    ERR_INVALID_TOKEN,
    ERR_INVALID_TOKEN_PAYLOAD,
    ERR_NOT_AUTHENTICATED,
    ERR_TOKEN_REVOKED,
    ERR_USER_NOT_FOUND_OR_INACTIVE,
)
from src.models.database import User
from src.models.session import get_db

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate JWT access token and return the authenticated user.

    Token sources (checked in order):
    1. Bearer header (backward compatible)
    2. httpOnly cookie ``access_token`` (XSS-safe)

    Raises 401 if token is missing, invalid, or user not found.
    """
    # Try Bearer header first
    token = credentials.credentials if credentials else None

    # Fallback to httpOnly cookie
    if not token:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_NOT_AUTHENTICATED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token, expected_type="access")
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_INVALID_TOKEN,
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_INVALID_TOKEN_PAYLOAD,
        )

    # Check token_version to support token revocation
    token_version = payload.get("tv")

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active or user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_USER_NOT_FOUND_OR_INACTIVE,
        )

    # Reject tokens issued before a password change / forced logout.
    # Treat missing 'tv' as version 0 so legacy tokens are revocable.
    effective_tv = token_version if token_version is not None else 0
    if hasattr(user, "token_version") and user.token_version is not None:
        if effective_tv < user.token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERR_TOKEN_REVOKED,
                headers={"WWW-Authenticate": "Bearer"},
            )

    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Require admin role. Returns user if admin, raises 403 otherwise."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERR_ADMIN_REQUIRED,
        )
    return user
