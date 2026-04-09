"""User management endpoints (admin only)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.user import AdminUserResponse, UserCreate, UserResponse, UserUpdate
from src.errors import ERR_CANNOT_DELETE_SELF, ERR_USERNAME_EXISTS, ERR_USER_NOT_FOUND
from src.auth.dependencies import get_current_admin
from src.auth.password import hash_password
from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User
from src.models.session import get_db
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[AdminUserResponse])
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all active users with support-relevant details (admin only)."""
    result = await db.execute(
        select(User).where(User.is_deleted == False).order_by(User.id)  # noqa: E712
    )
    users = result.scalars().all()
    user_ids = [u.id for u in users]

    # Batch: exchanges per user
    ex_result = await db.execute(
        select(ExchangeConnection.user_id, ExchangeConnection.exchange_type)
        .where(ExchangeConnection.user_id.in_(user_ids))
        .distinct()
    )
    exchanges_map: dict[int, list[str]] = {}
    for uid, ex_type in ex_result:
        exchanges_map.setdefault(uid, []).append(ex_type)

    # Batch: active bots per user
    bot_result = await db.execute(
        select(BotConfig.user_id, func.count(BotConfig.id))
        .where(BotConfig.user_id.in_(user_ids), BotConfig.is_enabled == True)  # noqa: E712
        .group_by(BotConfig.user_id)
    )
    bots_map = {uid: cnt for uid, cnt in bot_result.all()}

    # Batch: total trades per user
    trade_result = await db.execute(
        select(TradeRecord.user_id, func.count(TradeRecord.id))
        .where(TradeRecord.user_id.in_(user_ids))
        .group_by(TradeRecord.user_id)
    )
    trades_map = {uid: cnt for uid, cnt in trade_result.all()}

    return [
        AdminUserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            role=u.role,
            language=u.language,
            is_active=u.is_active,
            auth_provider=u.auth_provider or "local",
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
            created_at=u.created_at.isoformat() if u.created_at else None,
            exchanges=exchanges_map.get(u.id, []),
            active_bots=bots_map.get(u.id, 0),
            total_trades=trades_map.get(u.id, 0),
        )
        for u in users
    ]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def create_user(
    request: Request,
    data: UserCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin only)."""
    existing = await db.execute(
        select(User).where(User.username == data.username)
    )
    existing_user = existing.scalar_one_or_none()
    if existing_user:
        if existing_user.is_deleted:
            # Hard-delete the soft-deleted user so the username can be reused.
            # CASCADE on foreign keys removes bots, exchange connections, sessions.
            # Trade records are also cascaded — acceptable for deleted users.
            old_id = existing_user.id
            await db.delete(existing_user)
            await db.flush()
            logger.info("Hard-deleted soft-deleted user %s (id=%d) for username reuse", data.username, old_id)
        else:
            raise HTTPException(status_code=409, detail=ERR_USERNAME_EXISTS)

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
        language=data.language,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.put("/{user_id}", response_model=UserResponse)
@limiter.limit("10/minute")
async def update_user(
    request: Request,
    user_id: int,
    data: UserUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user (admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail=ERR_USER_NOT_FOUND)

    if data.email is not None:
        user.email = data.email
    if data.role is not None:
        user.role = data.role
    if data.language is not None:
        user.language = data.language
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password is not None:
        user.password_hash = hash_password(data.password)

    await db.flush()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def delete_user(
    request: Request,
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a user (admin only). Cannot delete yourself.

    Sets is_deleted=True and bumps token_version to revoke all sessions.
    Financial records (trades, funding) are preserved for audit purposes.
    """
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail=ERR_CANNOT_DELETE_SELF)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail=ERR_USER_NOT_FOUND)

    user.is_deleted = True
    user.is_active = False
    user.deleted_at = datetime.now(timezone.utc)
    user.token_version = (user.token_version or 0) + 1
    await db.flush()
    await db.commit()
