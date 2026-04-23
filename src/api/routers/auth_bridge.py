"""Auth bridge router — connects Supabase Auth to the bot's own JWT system.

Flow:
1. Main site calls POST /generate with a Supabase JWT
2. Bot returns a one-time code (60 s TTL, single use)
3. Main site opens new tab: bots.trading-department.com/auth/callback?code=X
4. Bot frontend calls POST /exchange with the code
5. Bot validates, provisions user if needed, returns bot JWT
"""

import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.auth_bridge import (
    BridgeUserProfile,
    ExchangeCodeRequest,
    ExchangeCodeResponse,
    GenerateCodeResponse,
)
from src.auth.auth_code import auth_code_store
from src.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    set_access_cookie,
    set_refresh_cookie,
)
from src.auth.password import hash_password
from src.auth.supabase_jwt import verify_supabase_token
from src.api.rate_limit import _get_real_client_ip, limiter
from src.models.database import User
from src.models.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/bridge", tags=["auth-bridge"])


# ── POST /generate — called by the Supabase Edge Function ─────────

@router.post("/generate", response_model=GenerateCodeResponse)
@limiter.limit("10/minute")
async def generate_code(request: Request):
    """Generate a one-time auth code from a valid Supabase JWT.

    The Supabase JWT must be passed in the Authorization header.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    supabase_jwt = auth_header.removeprefix("Bearer ").strip()
    claims = verify_supabase_token(supabase_jwt)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Supabase token",
        )

    code = await auth_code_store.generate(supabase_jwt)
    client_ip = _get_real_client_ip(request)
    logger.info(
        "AUTH_BRIDGE: Code generated for Supabase user %s from %s",
        claims.sub,
        client_ip,
    )
    return GenerateCodeResponse(code=code)


# ── POST /exchange — called by the bot frontend ───────────────────

@router.post("/exchange", response_model=ExchangeCodeResponse)
@limiter.limit("10/minute")
async def exchange_code(
    body: ExchangeCodeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a one-time code for bot JWT tokens.

    Looks up or creates a bot user based on the Supabase identity.
    """
    supabase_jwt = await auth_code_store.exchange(body.code)
    if supabase_jwt is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or already used code",
        )

    # Re-validate the Supabase JWT (defense in depth)
    claims = verify_supabase_token(supabase_jwt)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Supabase token expired during code exchange",
        )

    # Look up or provision the bot user
    user, is_new = await _get_or_create_user(db, claims.sub, claims.email, claims.app_role)

    # Issue bot JWT tokens
    tv = getattr(user, "token_version", 0) or 0
    token_data = {"sub": str(user.id), "role": user.role, "tv": tv}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    set_access_cookie(response, access_token)
    set_refresh_cookie(response, refresh_token)

    client_ip = _get_real_client_ip(request)
    logger.info(
        "AUTH_BRIDGE: User '%s' (id=%s, new=%s) authenticated via bridge from %s",
        user.username,
        user.id,
        is_new,
        client_ip,
    )

    return ExchangeCodeResponse(
        access_token=access_token,
        user=BridgeUserProfile(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
            language=user.language,
            is_new=is_new,
        ),
    )


# ── Role sync ─────────────────────────────────────────────────────

async def _sync_role(db: AsyncSession, user: User, app_role: str) -> None:
    """Sync admin role from Supabase app_metadata. Only upgrades, never downgrades."""
    changed = False
    if app_role == "admin" and user.role != "admin":
        user.role = "admin"
        changed = True
        logger.info("AUTH_BRIDGE: Upgraded user '%s' (id=%s) to admin via Supabase", user.username, user.id)
    # Update last login timestamp
    user.last_login_at = datetime.now(timezone.utc)
    if changed:
        await db.commit()
        await db.refresh(user)


# ── User provisioning ─────────────────────────────────────────────

async def _get_or_create_user(
    db: AsyncSession,
    supabase_uid: str,
    email: str,
    app_role: str = "user",
) -> tuple[User, bool]:
    """Find an existing bot user or create a new one.

    Lookup order:
    1. By supabase_user_id (already linked)
    2. By email (existing user, link accounts)
    3. Create new user

    Returns (user, is_new).
    """
    # 1. Direct lookup by Supabase UUID
    result = await db.execute(
        select(User).where(
            User.supabase_user_id == supabase_uid,
            User.is_deleted == False,  # noqa: E712
        )
    )
    user = result.scalar_one_or_none()
    if user:
        await _sync_role(db, user, app_role)
        return user, False

    # 2. Lookup by verified email — link existing account
    result = await db.execute(
        select(User).where(
            User.email == email,
            User.is_deleted == False,  # noqa: E712
        )
    )
    user = result.scalar_one_or_none()
    if user:
        user.supabase_user_id = supabase_uid
        user.auth_provider = "supabase"
        await _sync_role(db, user, app_role)
        await db.commit()
        await db.refresh(user)
        logger.info(
            "AUTH_BRIDGE: Linked existing user '%s' (id=%s) to Supabase %s",
            user.username,
            user.id,
            supabase_uid,
        )
        return user, False

    # 3. Create new user
    username = _generate_username(email)
    # Ensure username uniqueness
    for attempt in range(5):
        result = await db.execute(
            select(User).where(User.username == username)
        )
        if result.scalar_one_or_none() is None:
            break
        username = f"{_generate_username(email)}_{secrets.token_hex(3)}"

    random_password = secrets.token_urlsafe(48)
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(random_password),
        role="user",
        is_active=True,
        supabase_user_id=supabase_uid,
        auth_provider="supabase",
        language="de",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(
        "AUTH_BRIDGE: Created new user '%s' (id=%s) for Supabase %s",
        user.username,
        user.id,
        supabase_uid,
    )
    return user, True


def _generate_username(email: str) -> str:
    """Derive a username from an email address."""
    local_part = email.split("@")[0] if "@" in email else email
    # Keep only alphanumeric and underscores, max 40 chars
    clean = "".join(c if c.isalnum() or c == "_" else "_" for c in local_part)
    return clean[:40] or "user"
