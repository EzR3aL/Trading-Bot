"""Authentication endpoints."""

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import _get_real_client_ip, limiter
from src.api.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenResponse,
    UserProfile,
)
from src.auth.dependencies import get_current_user
from src.auth.jwt_handler import (
    REFRESH_COOKIE_NAME,
    REFRESH_TOKEN_EXPIRE_DAYS,
    clear_access_cookie,
    clear_refresh_cookie,
    create_access_token,
    create_refresh_token,
    decode_token,
    set_access_cookie,
    set_refresh_cookie,
)
from src.auth.password import hash_password, verify_password
from src.errors import (
    ERR_ACCOUNT_DISABLED,
    ERR_ACCOUNT_LOCKED,
    ERR_CURRENT_PASSWORD_WRONG,
    ERR_INVALID_CREDENTIALS,
    ERR_INVALID_REFRESH_TOKEN,
    ERR_TOKEN_REVOKED,
    ERR_USER_NOT_FOUND_OR_INACTIVE,
)
from src.models.database import User, UserSession
from src.models.session import get_db
from src.services import users_service
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Session Helpers ─────────────────────────────────────────────────


def _hash_token(token: str) -> str:
    """Create a SHA-256 hash of a token for storage (fast, non-reversible)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_device_name(user_agent: str | None) -> str | None:
    """Extract a human-readable device name from the User-Agent header."""
    if not user_agent:
        return None
    ua_lower = user_agent.lower()
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        return "Mobile Browser"
    if "tablet" in ua_lower or "ipad" in ua_lower:
        return "Tablet"
    if "postman" in ua_lower:
        return "Postman"
    if "curl" in ua_lower:
        return "curl"
    if "python" in ua_lower:
        return "Python Client"
    return "Desktop Browser"


async def _create_session(
    db: AsyncSession,
    user_id: int,
    refresh_token: str,
    request: Request,
) -> UserSession:
    """Create a new UserSession record for a login or token refresh."""
    client_ip = _get_real_client_ip(request)
    user_agent = request.headers.get("user-agent")
    session = UserSession(
        user_id=user_id,
        session_token_hash=_hash_token(refresh_token),
        device_name=_parse_device_name(user_agent),
        ip_address=client_ip,
        user_agent=user_agent[:500] if user_agent else None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    await db.flush()
    return session


# ── Login ───────────────────────────────────────────────────────────


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, response: Response, body: LoginRequest, db: AsyncSession = Depends(get_db)):
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
            detail=ERR_INVALID_CREDENTIALS,
        )

    # Check account lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        logger.warning("AUTH: Locked account login attempt for '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=423,
            detail=ERR_ACCOUNT_LOCKED,
        )

    if not verify_password(body.password, user.password_hash):
        # Increment failed login attempts and lock with escalating duration
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= 5:
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
            detail=ERR_INVALID_CREDENTIALS,
        )

    if user.is_deleted:
        logger.warning("AUTH: Login attempt for deleted user '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_INVALID_CREDENTIALS,
        )

    if not user.is_active:
        logger.warning("AUTH: Login attempt for disabled user '%s' from %s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERR_ACCOUNT_DISABLED,
        )

    # Successful password check — reset lockout counters
    user.failed_login_attempts = 0
    user.locked_until = None

    tv = getattr(user, "token_version", 0) or 0
    token_data = {"sub": str(user.id), "role": user.role, "tv": tv}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Track last login + session in DB
    user.last_login_at = datetime.now(timezone.utc)
    await _create_session(db, user.id, refresh_token, request)
    await db.commit()

    # Set tokens as httpOnly cookies (XSS-safe)
    set_access_cookie(response, access_token)
    set_refresh_cookie(response, refresh_token)

    logger.info("AUTH: User '%s' (id=%s) logged in from %s", user.username, user.id, client_ip)
    return LoginResponse(
        access_token=access_token,
        # refresh_token intentionally NOT in response body — httpOnly cookie only
    )


# ── Token Refresh ───────────────────────────────────────────────────


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("5/minute")
async def refresh_token(
    request: Request,
    response: Response,
    body: RefreshRequest | None = None,
    refresh_token_cookie: str | None = Cookie(None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token from httpOnly cookie or request body.

    Accepts the refresh token from:
    1. httpOnly cookie (preferred, XSS-safe)
    2. Request body (backward compatibility for existing clients)
    """
    client_ip = _get_real_client_ip(request)

    # Prefer cookie, fall back to body for backward compatibility
    raw_token = refresh_token_cookie or (body.refresh_token if body else None)
    if not raw_token:
        logger.warning("AUTH: Missing refresh token from %s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_INVALID_REFRESH_TOKEN,
        )

    payload = decode_token(raw_token, expected_type="refresh")
    if not payload:
        # Clear stale cookie if present
        clear_refresh_cookie(response)
        logger.warning("AUTH: Invalid refresh token from %s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_INVALID_REFRESH_TOKEN,
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active or user.is_deleted:
        clear_refresh_cookie(response)
        logger.warning("AUTH: Refresh for inactive/deleted user_id=%s from %s", user_id, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_USER_NOT_FOUND_OR_INACTIVE,
        )

    token_tv = payload.get("tv")
    user_tv = getattr(user, "token_version", 0) or 0
    if token_tv is not None and token_tv < user_tv:
        clear_refresh_cookie(response)
        logger.warning("AUTH: Revoked refresh token used for user_id=%s (tv=%s < %s) from %s", user_id, token_tv, user_tv, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_TOKEN_REVOKED,
        )

    # Validate session is still active in DB (catches explicit logout).
    # Check for both cookie-based and body-based tokens — a revoked session
    # must block refresh regardless of how the token was transmitted.
    token_hash = _hash_token(raw_token)
    session_result = await db.execute(
        select(UserSession).where(
            UserSession.session_token_hash == token_hash,
            UserSession.user_id == int(user_id),
            UserSession.is_active.is_(True),
        ).limit(1)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        clear_refresh_cookie(response)
        logger.warning("AUTH: Refresh with invalidated session for user_id=%s from %s", user_id, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_INVALID_REFRESH_TOKEN,
        )

    token_data = {"sub": str(user.id), "role": user.role, "tv": user_tv}
    access_token = create_access_token(token_data)

    # Issue a fresh access token but DO NOT rotate the refresh token. Rotating
    # caused logouts under normal use because two parallel refresh requests
    # (PWA wake-up + interceptor 401, multi-tab visibility events) raced on
    # the same session row, leaving the browser with a token whose hash no
    # longer existed in the DB. The next refresh would then fail and force a
    # login. With httpOnly + secure cookies the theft window is small enough
    # that we accept the trade-off.
    set_access_cookie(response, access_token)
    await db.execute(
        update(UserSession)
        .where(UserSession.session_token_hash == _hash_token(raw_token))
        .values(last_activity=datetime.now(timezone.utc))
    )
    await db.commit()

    logger.info("AUTH: Token refreshed for user_id=%s (tv=%s) from %s", user.id, user.token_version, client_ip)
    return TokenResponse(
        access_token=access_token,
        # refresh_token NOT in body — httpOnly cookie only
    )


# ── Logout ─────────────────────────────────────────────────────────


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token_cookie: str | None = Cookie(None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate the current session in DB and clear the httpOnly cookie."""
    if refresh_token_cookie:
        token_hash = _hash_token(refresh_token_cookie)
        await db.execute(
            update(UserSession)
            .where(UserSession.session_token_hash == token_hash, UserSession.is_active.is_(True))
            .values(is_active=False)
        )
        await db.commit()
        logger.info("AUTH: Session invalidated via logout")

    clear_access_cookie(response)
    clear_refresh_cookie(response)
    return {"message": "Logged out"}


# ── Password Management ────────────────────────────────────────────


@router.put("/change-password")
@limiter.limit("3/minute")
async def change_password(
    request: Request,
    response: Response,
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password and revoke existing tokens."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail=ERR_CURRENT_PASSWORD_WRONG)
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1

    # Invalidate all existing sessions so old refresh tokens cannot be used,
    # even if token_version alone would catch them.
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.is_active.is_(True))
        .values(is_active=False)
    )
    await db.commit()

    # Issue fresh tokens and create a new session for the current device
    token_data = {"sub": str(user.id), "role": user.role, "tv": user.token_version}
    new_access = create_access_token(token_data)
    new_refresh = create_refresh_token(token_data)
    set_access_cookie(response, new_access)
    set_refresh_cookie(response, new_refresh)
    await _create_session(db, user.id, new_refresh, request)
    await db.commit()

    logger.info("AUTH: Password changed for user_id=%s, all sessions revoked", user.id)
    return {
        "access_token": new_access,
        "token_type": "bearer",
        "message": "Password changed successfully",
    }


# ── Profile ─────────────────────────────────────────────────────────


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user)):
    """Get current user profile."""
    profile = users_service.get_profile(user)
    return UserProfile(
        id=profile.id,
        username=profile.username,
        email=profile.email,
        role=profile.role,
        language=profile.language,
        is_active=profile.is_active,
    )


