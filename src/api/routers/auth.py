"""Authentication endpoints with TOTP two-factor authentication."""

import base64
import hashlib
import io
import json
import secrets
import string
from datetime import datetime, timedelta, timezone

import pyotp
import qrcode
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import _get_real_client_ip, limiter  # noqa: F401 — re-export for backward compat
from src.api.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenResponse,
    TwoFactorDisableRequest,
    TwoFactorSetupResponse,
    TwoFactorVerifyLoginRequest,
    TwoFactorVerifyRequest,
    UserProfile,
)
from src.auth.dependencies import get_current_user
from src.auth.jwt_handler import (
    REFRESH_COOKIE_NAME,
    REFRESH_TOKEN_EXPIRE_DAYS,
    clear_refresh_cookie,
    create_access_token,
    create_refresh_token,
    decode_token,
    set_refresh_cookie,
)
from src.auth.password import hash_password, verify_password
from src.errors import (
    ERR_2FA_ALREADY_ENABLED,
    ERR_2FA_INVALID_CODE,
    ERR_2FA_NOT_ENABLED,
    ERR_2FA_SETUP_NOT_STARTED,
    ERR_2FA_TEMP_TOKEN_INVALID,
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
from src.utils.encryption import decrypt_value, encrypt_value
from src.utils.logger import get_logger

TOTP_TEMP_TOKEN_EXPIRE_MINUTES = 5
BACKUP_CODE_COUNT = 10
BACKUP_CODE_LENGTH = 8

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


# ── 2FA Helper Functions ────────────────────────────────────────────


def _generate_backup_codes() -> list[str]:
    """Generate a list of random alphanumeric backup codes."""
    alphabet = string.ascii_uppercase + string.digits
    return [
        "".join(secrets.choice(alphabet) for _ in range(BACKUP_CODE_LENGTH))
        for _ in range(BACKUP_CODE_COUNT)
    ]


def _hash_backup_codes(codes: list[str]) -> list[str]:
    """Hash backup codes with bcrypt for storage."""
    return [hash_password(code) for code in codes]


def _verify_backup_code(code: str, hashed_codes: list[str]) -> int | None:
    """Check a backup code against the hashed list, return index if found."""
    for i, hashed in enumerate(hashed_codes):
        if verify_password(code, hashed):
            return i
    return None


def _verify_totp_or_backup(
    code: str, totp_secret: str, backup_codes_json: str | None
) -> tuple[bool, str | None]:
    """Verify a TOTP code or backup code.

    Returns:
        (is_valid, updated_backup_codes_json_or_None)
        If a backup code was used, returns the updated JSON with the used
        code removed. Otherwise None (no change needed).
    """
    # Try TOTP first (6-digit codes)
    totp = pyotp.TOTP(totp_secret)
    if totp.verify(code, valid_window=1):
        return True, None

    # Try backup code (8-char alphanumeric)
    if backup_codes_json:
        hashed_codes = json.loads(backup_codes_json)
        idx = _verify_backup_code(code.upper(), hashed_codes)
        if idx is not None:
            hashed_codes.pop(idx)
            return True, json.dumps(hashed_codes)

    return False, None


def _create_temp_2fa_token(user_id: int) -> str:
    """Create a short-lived JWT for the 2FA verification step."""
    return create_access_token(
        {"sub": str(user_id), "purpose": "2fa_temp"},
        expires_delta=timedelta(minutes=TOTP_TEMP_TOKEN_EXPIRE_MINUTES),
    )


def _generate_qr_code_base64(secret: str, username: str, issuer: str = "TradingBot") -> str:
    """Generate a QR code PNG as a base64-encoded string."""
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=username, issuer_name=issuer)
    img = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


# ── Login ───────────────────────────────────────────────────────────


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, response: Response, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user and return JWT tokens, or request 2FA if enabled."""
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

    # 2FA check: if enabled, require TOTP code
    if user.totp_enabled:
        if not body.totp_code:
            # Password correct but 2FA required — return temp token
            await db.commit()
            temp_token = _create_temp_2fa_token(user.id)
            logger.info("AUTH: 2FA required for '%s' from %s", body.username, client_ip)
            return LoginResponse(requires_2fa=True, temp_token=temp_token)

        # Verify TOTP code or backup code
        totp_secret = decrypt_value(user.totp_secret)
        is_valid, updated_backup_codes = _verify_totp_or_backup(
            body.totp_code, totp_secret, user.totp_backup_codes
        )
        if not is_valid:
            await db.commit()
            logger.warning("AUTH: Invalid 2FA code for '%s' from %s", body.username, client_ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERR_2FA_INVALID_CODE,
            )

        # If a backup code was consumed, update the stored list
        if updated_backup_codes is not None:
            user.totp_backup_codes = updated_backup_codes
            logger.info("AUTH: Backup code used for '%s' from %s", body.username, client_ip)

    tv = getattr(user, "token_version", 0) or 0
    token_data = {"sub": str(user.id), "role": user.role, "tv": tv}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Track last login + session in DB
    user.last_login_at = datetime.now(timezone.utc)
    await _create_session(db, user.id, refresh_token, request)
    await db.commit()

    # Set refresh token as httpOnly cookie (XSS-safe)
    set_refresh_cookie(response, refresh_token)

    logger.info("AUTH: User '%s' (id=%s) logged in from %s", user.username, user.id, client_ip)
    return LoginResponse(
        access_token=access_token,
        # refresh_token intentionally NOT in response body — httpOnly cookie only
    )


@router.post("/2fa/verify-login")
@limiter.limit("5/minute")
async def verify_2fa_login(
    request: Request, response: Response, body: TwoFactorVerifyLoginRequest, db: AsyncSession = Depends(get_db)
):
    """Complete login by verifying TOTP code with temp token."""
    client_ip = _get_real_client_ip(request)

    # Decode the temp token — must have purpose "2fa_temp"
    payload = decode_token(body.temp_token, expected_type="access")
    if not payload or payload.get("purpose") != "2fa_temp":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_2FA_TEMP_TOKEN_INVALID,
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active or user.is_deleted or not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_2FA_TEMP_TOKEN_INVALID,
        )

    totp_secret = decrypt_value(user.totp_secret)
    is_valid, updated_backup_codes = _verify_totp_or_backup(
        body.code, totp_secret, user.totp_backup_codes
    )

    if not is_valid:
        logger.warning("AUTH: Invalid 2FA code in verify-login for user_id=%s from %s", user_id, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_2FA_INVALID_CODE,
        )

    if updated_backup_codes is not None:
        user.totp_backup_codes = updated_backup_codes
        logger.info("AUTH: Backup code used in verify-login for user_id=%s from %s", user_id, client_ip)

    tv = getattr(user, "token_version", 0) or 0
    token_data = {"sub": str(user.id), "role": user.role, "tv": tv}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    # Track session in DB for explicit revocation
    await _create_session(db, user.id, refresh_token, request)
    await db.commit()

    set_refresh_cookie(response, refresh_token)

    logger.info("AUTH: User '%s' (id=%s) completed 2FA login from %s", user.username, user.id, client_ip)
    return LoginResponse(
        access_token=access_token,
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

    # Validate session is still active in DB (catches explicit logout)
    if raw_token and refresh_token_cookie:
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
    new_refresh = create_refresh_token(token_data)

    # Rotate refresh token cookie and update session hash in DB
    set_refresh_cookie(response, new_refresh)
    if raw_token and refresh_token_cookie:
        old_hash = _hash_token(raw_token)
        new_hash = _hash_token(new_refresh)
        await db.execute(
            update(UserSession)
            .where(UserSession.session_token_hash == old_hash)
            .values(session_token_hash=new_hash, last_activity=datetime.now(timezone.utc))
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
    await db.commit()
    token_data = {"sub": str(user.id), "role": user.role, "tv": user.token_version}
    new_refresh = create_refresh_token(token_data)
    set_refresh_cookie(response, new_refresh)
    return {
        "access_token": create_access_token(token_data),
        "token_type": "bearer",
        "message": "Password changed successfully",
    }


# ── Profile ─────────────────────────────────────────────────────────


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
        totp_enabled=user.totp_enabled or False,
    )


# ── Two-Factor Authentication ──────────────────────────────────────


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
@limiter.limit("3/minute")
async def setup_2fa(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate TOTP secret and QR code to begin 2FA setup.

    The secret is stored encrypted but 2FA is NOT enabled yet.
    The user must confirm with POST /2fa/verify-setup first.
    """
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERR_2FA_ALREADY_ENABLED,
        )

    # Generate new TOTP secret
    secret = pyotp.random_base32()

    # Generate backup codes
    backup_codes = _generate_backup_codes()
    hashed_codes = _hash_backup_codes(backup_codes)

    # Store encrypted secret and hashed backup codes (2FA not yet enabled)
    user.totp_secret = encrypt_value(secret)
    user.totp_backup_codes = json.dumps(hashed_codes)
    await db.commit()

    # Generate QR code
    qr_code_base64 = _generate_qr_code_base64(secret, user.username)

    logger.info("AUTH: 2FA setup initiated for user_id=%s", user.id)
    return TwoFactorSetupResponse(
        secret=secret,
        qr_code_base64=qr_code_base64,
        backup_codes=backup_codes,
    )


@router.post("/2fa/verify-setup")
@limiter.limit("5/minute")
async def verify_2fa_setup(
    request: Request,
    body: TwoFactorVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify first TOTP code to confirm 2FA setup and enable it."""
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERR_2FA_ALREADY_ENABLED,
        )

    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERR_2FA_SETUP_NOT_STARTED,
        )

    # Verify the TOTP code against the stored (but not yet active) secret
    totp_secret = decrypt_value(user.totp_secret)
    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERR_2FA_INVALID_CODE,
        )

    # Enable 2FA
    user.totp_enabled = True
    await db.commit()

    logger.info("AUTH: 2FA enabled for user_id=%s", user.id)
    return {"message": "Zwei-Faktor-Authentifizierung erfolgreich aktiviert"}


@router.post("/2fa/disable")
@limiter.limit("3/minute")
async def disable_2fa(
    request: Request,
    body: TwoFactorDisableRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disable 2FA. Requires current password and a valid TOTP code."""
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERR_2FA_NOT_ENABLED,
        )

    # Verify password
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERR_CURRENT_PASSWORD_WRONG,
        )

    # Verify TOTP code or backup code
    totp_secret = decrypt_value(user.totp_secret)
    is_valid, _ = _verify_totp_or_backup(body.code, totp_secret, user.totp_backup_codes)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERR_2FA_INVALID_CODE,
        )

    # Disable 2FA and clear secrets
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_backup_codes = None
    await db.commit()

    logger.info("AUTH: 2FA disabled for user_id=%s", user.id)
    return {"message": "Zwei-Faktor-Authentifizierung deaktiviert"}


@router.post("/2fa/backup-codes")
@limiter.limit("3/minute")
async def regenerate_backup_codes(
    request: Request,
    body: TwoFactorVerifyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate new backup codes. Requires a valid TOTP code.

    Only accepts TOTP codes (not backup codes) to prevent using a backup
    code to generate new backup codes.
    """
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERR_2FA_NOT_ENABLED,
        )

    # Verify TOTP code only (not backup codes)
    totp_secret = decrypt_value(user.totp_secret)
    totp = pyotp.TOTP(totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERR_2FA_INVALID_CODE,
        )

    # Generate new backup codes
    backup_codes = _generate_backup_codes()
    hashed_codes = _hash_backup_codes(backup_codes)
    user.totp_backup_codes = json.dumps(hashed_codes)
    await db.commit()

    logger.info("AUTH: Backup codes regenerated for user_id=%s", user.id)
    return {"backup_codes": backup_codes}
