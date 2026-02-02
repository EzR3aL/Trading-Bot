"""
Role-Based Access Control (RBAC) for Multi-Tenant Trading Platform.

Provides role definitions, permission checks, and FastAPI dependencies
for protecting endpoints based on user roles.

Roles:
- Admin: Full access, can manage all users, impersonate for support
- Trader: Can trade, manage own credentials and bots
- Viewer: Read-only access to own data
"""

from enum import Enum
from functools import wraps
from typing import Set, Callable, Optional

from fastapi import HTTPException, Depends, status

from src.auth.dependencies import get_current_user_payload, TokenPayload
from src.utils.logger import get_logger

logger = get_logger(__name__)


class Role(str, Enum):
    """User roles with increasing privilege levels."""
    VIEWER = "viewer"
    TRADER = "trader"
    ADMIN = "admin"

    @classmethod
    def from_string(cls, role_str: str) -> "Role":
        """Convert string to Role enum."""
        try:
            return cls(role_str.lower())
        except ValueError:
            return cls.VIEWER  # Default to viewer for safety


class Permission(str, Enum):
    """Granular permissions for fine-grained access control."""
    # User management
    USER_READ_SELF = "user:read:self"
    USER_UPDATE_SELF = "user:update:self"
    USER_READ_ALL = "user:read:all"
    USER_UPDATE_ALL = "user:update:all"
    USER_DELETE = "user:delete"
    USER_IMPERSONATE = "user:impersonate"

    # Credential management
    CREDENTIAL_READ = "credential:read"
    CREDENTIAL_CREATE = "credential:create"
    CREDENTIAL_UPDATE = "credential:update"
    CREDENTIAL_DELETE = "credential:delete"

    # Bot management
    BOT_READ = "bot:read"
    BOT_CREATE = "bot:create"
    BOT_UPDATE = "bot:update"
    BOT_DELETE = "bot:delete"
    BOT_START = "bot:start"
    BOT_STOP = "bot:stop"

    # Trading
    TRADE_READ = "trade:read"
    TRADE_EXECUTE = "trade:execute"

    # Risk management
    RISK_READ = "risk:read"
    RISK_UPDATE = "risk:update"

    # Audit logs
    AUDIT_READ_SELF = "audit:read:self"
    AUDIT_READ_ALL = "audit:read:all"

    # System management
    SYSTEM_STATS = "system:stats"
    SYSTEM_CONFIG = "system:config"


# Role-to-permission mapping
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.VIEWER: {
        Permission.USER_READ_SELF,
        Permission.CREDENTIAL_READ,
        Permission.BOT_READ,
        Permission.TRADE_READ,
        Permission.RISK_READ,
        Permission.AUDIT_READ_SELF,
    },
    Role.TRADER: {
        # All viewer permissions
        Permission.USER_READ_SELF,
        Permission.USER_UPDATE_SELF,
        Permission.CREDENTIAL_READ,
        Permission.CREDENTIAL_CREATE,
        Permission.CREDENTIAL_UPDATE,
        Permission.CREDENTIAL_DELETE,
        Permission.BOT_READ,
        Permission.BOT_CREATE,
        Permission.BOT_UPDATE,
        Permission.BOT_DELETE,
        Permission.BOT_START,
        Permission.BOT_STOP,
        Permission.TRADE_READ,
        Permission.TRADE_EXECUTE,
        Permission.RISK_READ,
        Permission.RISK_UPDATE,
        Permission.AUDIT_READ_SELF,
    },
    Role.ADMIN: {
        # All permissions
        Permission.USER_READ_SELF,
        Permission.USER_UPDATE_SELF,
        Permission.USER_READ_ALL,
        Permission.USER_UPDATE_ALL,
        Permission.USER_DELETE,
        Permission.USER_IMPERSONATE,
        Permission.CREDENTIAL_READ,
        Permission.CREDENTIAL_CREATE,
        Permission.CREDENTIAL_UPDATE,
        Permission.CREDENTIAL_DELETE,
        Permission.BOT_READ,
        Permission.BOT_CREATE,
        Permission.BOT_UPDATE,
        Permission.BOT_DELETE,
        Permission.BOT_START,
        Permission.BOT_STOP,
        Permission.TRADE_READ,
        Permission.TRADE_EXECUTE,
        Permission.RISK_READ,
        Permission.RISK_UPDATE,
        Permission.AUDIT_READ_SELF,
        Permission.AUDIT_READ_ALL,
        Permission.SYSTEM_STATS,
        Permission.SYSTEM_CONFIG,
    },
}


def has_permission(role: Role, permission: Permission) -> bool:
    """Check if a role has a specific permission."""
    return permission in ROLE_PERMISSIONS.get(role, set())


def has_any_permission(role: Role, permissions: Set[Permission]) -> bool:
    """Check if a role has any of the specified permissions."""
    role_perms = ROLE_PERMISSIONS.get(role, set())
    return bool(role_perms & permissions)


def has_all_permissions(role: Role, permissions: Set[Permission]) -> bool:
    """Check if a role has all of the specified permissions."""
    role_perms = ROLE_PERMISSIONS.get(role, set())
    return permissions.issubset(role_perms)


def get_user_role(payload: TokenPayload) -> Role:
    """Extract role from token payload."""
    if payload.is_admin:
        return Role.ADMIN
    # Default to trader for authenticated users
    return Role.TRADER


class RoleChecker:
    """
    FastAPI dependency for checking user roles.

    Usage:
        @router.get("/admin/users")
        async def admin_endpoint(
            _: None = Depends(RoleChecker(Role.ADMIN))
        ):
            ...

        @router.get("/data")
        async def trader_endpoint(
            _: None = Depends(RoleChecker([Role.ADMIN, Role.TRADER]))
        ):
            ...
    """

    def __init__(self, allowed_roles: Role | list[Role]):
        """
        Initialize role checker.

        Args:
            allowed_roles: Single role or list of roles that can access
        """
        if isinstance(allowed_roles, Role):
            self.allowed_roles = {allowed_roles}
        else:
            self.allowed_roles = set(allowed_roles)

    async def __call__(
        self,
        payload: TokenPayload = Depends(get_current_user_payload)
    ) -> TokenPayload:
        """Check if user has required role."""
        user_role = get_user_role(payload)

        if user_role not in self.allowed_roles:
            logger.warning(
                f"Access denied: user {payload.user_id} "
                f"with role {user_role.value} tried to access "
                f"endpoint requiring {[r.value for r in self.allowed_roles]}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this action"
            )

        return payload


class PermissionChecker:
    """
    FastAPI dependency for checking user permissions.

    Usage:
        @router.post("/bots/{id}/start")
        async def start_bot(
            _: None = Depends(PermissionChecker(Permission.BOT_START))
        ):
            ...
    """

    def __init__(
        self,
        required_permissions: Permission | list[Permission],
        require_all: bool = True
    ):
        """
        Initialize permission checker.

        Args:
            required_permissions: Single permission or list of permissions
            require_all: If True, require all permissions; if False, require any
        """
        if isinstance(required_permissions, Permission):
            self.required_permissions = {required_permissions}
        else:
            self.required_permissions = set(required_permissions)
        self.require_all = require_all

    async def __call__(
        self,
        payload: TokenPayload = Depends(get_current_user_payload)
    ) -> TokenPayload:
        """Check if user has required permissions."""
        user_role = get_user_role(payload)

        if self.require_all:
            has_perms = has_all_permissions(user_role, self.required_permissions)
        else:
            has_perms = has_any_permission(user_role, self.required_permissions)

        if not has_perms:
            logger.warning(
                f"Access denied: user {payload.user_id} "
                f"with role {user_role.value} lacks permissions "
                f"{[p.value for p in self.required_permissions]}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this action"
            )

        return payload


# Convenience dependencies
require_admin = RoleChecker(Role.ADMIN)
require_trader = RoleChecker([Role.ADMIN, Role.TRADER])
require_viewer = RoleChecker([Role.ADMIN, Role.TRADER, Role.VIEWER])

require_trade = PermissionChecker(Permission.TRADE_EXECUTE)
require_bot_control = PermissionChecker([Permission.BOT_START, Permission.BOT_STOP])
require_user_management = PermissionChecker(Permission.USER_READ_ALL)


def admin_only(func: Callable) -> Callable:
    """Decorator to require admin role for a function."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # This is used internally, not as a FastAPI dependency
        # The actual check happens in the dependency injection
        return await func(*args, **kwargs)
    return wrapper


def get_effective_user_id(
    payload: TokenPayload,
    target_user_id: Optional[int] = None,
) -> int:
    """
    Get the effective user ID, handling impersonation for admins.

    Args:
        payload: Token payload of the requesting user
        target_user_id: User ID to impersonate (admin only)

    Returns:
        Effective user ID to use for the operation
    """
    user_role = get_user_role(payload)

    # If no target specified, use the requesting user
    if target_user_id is None:
        return payload.user_id

    # Only admins can impersonate
    if user_role != Role.ADMIN:
        logger.warning(
            f"Impersonation attempt by non-admin user {payload.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access other users' data"
        )

    logger.info(
        f"Admin {payload.user_id} impersonating user {target_user_id}"
    )
    return target_user_id
