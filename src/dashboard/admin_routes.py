"""
Admin API routes for user management.

Provides REST endpoints for admin-only operations including
user management, role assignment, and system overview.
"""

from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.auth.dependencies import get_current_user_payload, TokenPayload
from src.auth.rbac import (
    Role,
    Permission,
    RoleChecker,
    PermissionChecker,
    require_admin,
    get_effective_user_id,
)
from src.models.user import UserRepository
from src.security.audit import get_audit_logger, AuditEventType
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Router with admin prefix
router = APIRouter(prefix="/api/admin", tags=["admin"])


# ==================== REQUEST/RESPONSE MODELS ====================


class UserResponse(BaseModel):
    """User data for admin views."""
    id: int
    username: str
    email: str
    is_active: bool
    is_admin: bool
    role: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    last_login: Optional[datetime]


class UserListResponse(BaseModel):
    """List of users."""
    users: List[UserResponse]
    count: int
    total: int


class RoleUpdateRequest(BaseModel):
    """Request to update user role."""
    role: str = Field(..., pattern="^(viewer|trader|admin)$")


class UserStatusUpdateRequest(BaseModel):
    """Request to update user status."""
    is_active: bool


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str
    success: bool = True


class SystemStatsResponse(BaseModel):
    """System statistics for admin dashboard."""
    total_users: int
    active_users: int
    total_bots: int
    active_bots: int
    total_trades_today: int


# ==================== ADMIN ENDPOINTS ====================


@router.get("/users", response_model=UserListResponse)
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    include_inactive: bool = False,
    limit: int = 100,
    payload: TokenPayload = Depends(require_admin),
):
    """
    List all users (admin only).

    Returns all users with their roles and status.
    """
    repo = UserRepository()
    users = await repo.get_all(include_inactive=include_inactive, limit=limit)
    total = await repo.count(active_only=not include_inactive)

    return UserListResponse(
        users=[
            UserResponse(
                id=u.id,
                username=u.username,
                email=u.email,
                is_active=u.is_active,
                is_admin=u.is_admin,
                role=u.role if not u.is_admin else "admin",
                created_at=u.created_at,
                updated_at=u.updated_at,
                last_login=u.last_login,
            )
            for u in users
        ],
        count=len(users),
        total=total,
    )


@router.get("/users/{user_id}", response_model=UserResponse)
@limiter.limit("30/minute")
async def get_user(
    request: Request,
    user_id: int,
    payload: TokenPayload = Depends(require_admin),
):
    """
    Get a specific user by ID (admin only).
    """
    repo = UserRepository()
    user = await repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        is_admin=user.is_admin,
        role=user.role if not user.is_admin else "admin",
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login=user.last_login,
    )


@router.put("/users/{user_id}/role", response_model=MessageResponse)
@limiter.limit("10/hour")
async def update_user_role(
    request: Request,
    user_id: int,
    data: RoleUpdateRequest,
    payload: TokenPayload = Depends(require_admin),
):
    """
    Update a user's role (admin only).

    Roles: viewer, trader, admin
    """
    repo = UserRepository()

    # Verify user exists
    user = await repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent self-demotion (admin can't remove their own admin role)
    if user_id == payload.user_id and data.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot demote yourself. Another admin must change your role."
        )

    # Update role
    await repo.update_role(user_id, data.role)

    logger.info(f"Admin {payload.user_id} changed user {user_id} role to {data.role}")

    # Audit log
    audit = await get_audit_logger()
    await audit.log(
        event_type=AuditEventType.USER_ROLE_CHANGE,
        user_id=payload.user_id,
        ip_address=request.client.host if request.client else None,
        severity="warning",
        details={
            "target_user_id": user_id,
            "old_role": user.role,
            "new_role": data.role,
        },
        success=True,
    )

    return MessageResponse(message=f"User role updated to {data.role}")


@router.put("/users/{user_id}/status", response_model=MessageResponse)
@limiter.limit("10/hour")
async def update_user_status(
    request: Request,
    user_id: int,
    data: UserStatusUpdateRequest,
    payload: TokenPayload = Depends(require_admin),
):
    """
    Activate or deactivate a user (admin only).
    """
    repo = UserRepository()

    # Verify user exists
    user = await repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent self-deactivation
    if user_id == payload.user_id and not data.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate yourself"
        )

    # Update status
    if data.is_active:
        await repo.activate(user_id)
        action = "activated"
    else:
        await repo.deactivate(user_id)
        action = "deactivated"

    logger.info(f"Admin {payload.user_id} {action} user {user_id}")

    # Audit log
    audit = await get_audit_logger()
    await audit.log(
        event_type=AuditEventType.USER_STATUS_CHANGE,
        user_id=payload.user_id,
        ip_address=request.client.host if request.client else None,
        severity="warning",
        details={
            "target_user_id": user_id,
            "action": action,
        },
        success=True,
    )

    return MessageResponse(message=f"User {action}")


@router.delete("/users/{user_id}", response_model=MessageResponse)
@limiter.limit("5/hour")
async def delete_user(
    request: Request,
    user_id: int,
    permanent: bool = False,
    payload: TokenPayload = Depends(require_admin),
):
    """
    Delete a user (admin only).

    By default this deactivates the user. Set permanent=true to
    permanently delete the user and all their data.
    """
    repo = UserRepository()

    # Verify user exists
    user = await repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent self-deletion
    if user_id == payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself"
        )

    if permanent:
        await repo.delete(user_id)
        action = "permanently deleted"
    else:
        await repo.deactivate(user_id)
        action = "deactivated"

    logger.warning(f"Admin {payload.user_id} {action} user {user_id}")

    # Audit log
    audit = await get_audit_logger()
    await audit.log(
        event_type=AuditEventType.USER_DELETE,
        user_id=payload.user_id,
        ip_address=request.client.host if request.client else None,
        severity="critical" if permanent else "warning",
        details={
            "target_user_id": user_id,
            "target_username": user.username,
            "permanent": permanent,
        },
        success=True,
    )

    return MessageResponse(message=f"User {action}")


@router.get("/stats", response_model=SystemStatsResponse)
@limiter.limit("30/minute")
async def get_system_stats(
    request: Request,
    payload: TokenPayload = Depends(require_admin),
):
    """
    Get system statistics (admin only).

    Returns counts of users, bots, and trades.
    """
    user_repo = UserRepository()

    total_users = await user_repo.count(active_only=False)
    active_users = await user_repo.count(active_only=True)

    # Bot stats would come from bot repository
    # For now, return placeholder values
    total_bots = 0
    active_bots = 0
    total_trades_today = 0

    try:
        from src.models.bot_instance import BotInstanceRepository
        bot_repo = BotInstanceRepository()
        all_bots = await bot_repo.get_all_instances()
        total_bots = len(all_bots)
        active_bots = sum(1 for b in all_bots if b.is_active)
    except Exception:
        pass

    try:
        from src.models.multi_tenant_trade_db import MultiTenantTradeDatabase
        from datetime import date
        trade_db = MultiTenantTradeDatabase()
        await trade_db.initialize()
        # Count today's trades across all users
        # This would need a method in the trade database
        total_trades_today = 0
    except Exception:
        pass

    return SystemStatsResponse(
        total_users=total_users,
        active_users=active_users,
        total_bots=total_bots,
        active_bots=active_bots,
        total_trades_today=total_trades_today,
    )


@router.get("/audit-logs")
@limiter.limit("30/minute")
async def get_audit_logs(
    request: Request,
    user_id: Optional[int] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    payload: TokenPayload = Depends(require_admin),
):
    """
    Get audit logs (admin only).

    Optionally filter by user_id or event_type.
    """
    audit = await get_audit_logger()

    if user_id:
        logs = await audit.get_user_logs(
            user_id=user_id,
            event_types=[event_type] if event_type else None,
            limit=limit,
        )
    else:
        # Get all logs (admin view)
        logs = await audit.get_all_logs(
            event_types=[event_type] if event_type else None,
            limit=limit,
        )

    return {
        "logs": [log.to_dict() for log in logs],
        "count": len(logs),
    }
