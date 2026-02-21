"""Authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import _get_real_client_ip, limiter  # noqa: F401 — re-export for backward compat
from src.api.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserProfile,
)
from src.auth.dependencies import get_current_user
from src.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from src.auth.password import verify_password
from src.models.database import User
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("30/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT tokens."""
    result = await db.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()

    client_ip = _get_real_client_ip(request)

    if not user or not verify_password(body.password, user.password_hash):
        logger.warning("AUTH: Failed login for '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if user.is_deleted:
        logger.warning("AUTH: Login attempt for deleted user '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.is_active:
        logger.warning("AUTH: Login attempt for disabled user '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    tv = getattr(user, "token_version", 0) or 0
    token_data = {"sub": str(user.id), "role": user.role, "tv": tv}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("AUTH: User '%s' (id=%s) logged in from %s", user.username, user.id, client_ip)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh_token(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Refresh access token using a valid refresh token."""
    client_ip = _get_real_client_ip(request)

    payload = decode_token(body.refresh_token, expected_type="refresh")
    if not payload:
        logger.warning("AUTH: Invalid refresh token from %s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active or user.is_deleted:
        logger.warning("AUTH: Refresh for inactive/deleted user_id=%s from %s", user_id, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Reject refresh tokens issued before a token revocation
    token_tv = payload.get("tv")
    user_tv = getattr(user, "token_version", 0) or 0
    if token_tv is not None and token_tv < user_tv:
        logger.warning("AUTH: Revoked refresh token used for user_id=%s (tv=%s < %s) from %s", user_id, token_tv, user_tv, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revoked — please log in again",
        )

    # Refresh token rotation: increment token_version so the old refresh
    # token is invalidated. Only the newly issued tokens will work.
    user.token_version = user_tv + 1
    await db.commit()

    token_data = {"sub": str(user.id), "role": user.role, "tv": user.token_version}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("AUTH: Token refreshed for user_id=%s (tv=%s) from %s", user.id, user.token_version, client_ip)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user)):
    """Get current user profile."""
    return UserProfile(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        language=user.language,
        is_active=user.is_active,
    )
