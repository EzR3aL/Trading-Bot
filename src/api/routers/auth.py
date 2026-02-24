"""Authentication endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import _get_real_client_ip, limiter  # noqa: F401 — re-export for backward compat
from src.api.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserProfile,
)
from src.auth.dependencies import get_current_user
from src.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from src.auth.password import hash_password, verify_password
from src.models.database import User
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT tokens."""
    result = await db.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()

    client_ip = _get_real_client_ip(request)

    if not user:
        logger.warning("AUTH: Failed login for '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungueltiger Benutzername oder Passwort",
        )

    # Check account lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        logger.warning("AUTH: Locked account login attempt for '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=423,
            detail="Konto voruebergehend gesperrt. Versuche es spaeter erneut.",
        )

    if not verify_password(body.password, user.password_hash):
        # Increment failed login attempts and lock with escalating duration
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= 5:
            # Exponential backoff: 15min, 30min, 60min, ... max 24h
            lockout_tier = user.failed_login_attempts // 5
            lockout_minutes = min(15 * (2 ** (lockout_tier - 1)), 1440)
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
            logger.warning(
                "AUTH: Account '%s' locked for %d min after %d failed attempts from %s",
                body.username, lockout_minutes, user.failed_login_attempts, client_ip,
            )
        await db.commit()
        logger.warning("AUTH: Failed login for '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungueltiger Benutzername oder Passwort",
        )

    if user.is_deleted:
        logger.warning("AUTH: Login attempt for deleted user '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungueltiger Benutzername oder Passwort",
        )

    if not user.is_active:
        logger.warning("AUTH: Login attempt for disabled user '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Konto ist deaktiviert",
        )

    # Successful login — reset lockout counters
    user.failed_login_attempts = 0
    user.locked_until = None

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
            detail="Ungueltiger Refresh-Token",
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active or user.is_deleted:
        logger.warning("AUTH: Refresh for inactive/deleted user_id=%s from %s", user_id, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Benutzer nicht gefunden oder inaktiv",
        )

    # Reject refresh tokens issued before a security event (password change,
    # forced logout). Do NOT bump token_version here — routine refreshes must
    # not invalidate tokens in other tabs / concurrent requests.
    token_tv = payload.get("tv")
    user_tv = getattr(user, "token_version", 0) or 0
    if token_tv is not None and token_tv < user_tv:
        logger.warning("AUTH: Revoked refresh token used for user_id=%s (tv=%s < %s) from %s", user_id, token_tv, user_tv, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token widerrufen — bitte erneut anmelden",
        )

    token_data = {"sub": str(user.id), "role": user.role, "tv": user_tv}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    logger.info("AUTH: Token refreshed for user_id=%s (tv=%s) from %s", user.id, user.token_version, client_ip)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.put("/change-password")
@limiter.limit("3/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password and revoke existing tokens."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Aktuelles Passwort ist falsch")
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    token_data = {"sub": str(user.id), "role": user.role, "tv": user.token_version}
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
        "message": "Password changed successfully",
    }


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
