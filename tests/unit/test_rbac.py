"""
Unit tests for Role-Based Access Control (RBAC) system.

Tests role permissions, role checking, and permission validation.
"""

import os
import pytest
import base64
from datetime import datetime, timedelta

# Set up test environment before imports
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-purposes-only-32chars"
test_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["ENCRYPTION_MASTER_KEY"] = test_key

from src.auth.rbac import (
    Role,
    Permission,
    ROLE_PERMISSIONS,
    has_permission,
    has_any_permission,
    has_all_permissions,
    get_user_role,
    RoleChecker,
    PermissionChecker,
    get_effective_user_id,
)
from src.auth.jwt_handler import TokenPayload


def create_test_payload(user_id: int, username: str, is_admin: bool = False) -> TokenPayload:
    """Helper to create a test TokenPayload with all required fields."""
    return TokenPayload(
        user_id=user_id,
        username=username,
        is_admin=is_admin,
        exp=datetime.now() + timedelta(hours=1),
        iat=datetime.now(),
        jti="test-jti-12345",
        token_type="access"
    )


class TestRoleEnum:
    """Tests for Role enum."""

    def test_role_values(self):
        """Test that all roles have expected values."""
        assert Role.VIEWER.value == "viewer"
        assert Role.TRADER.value == "trader"
        assert Role.ADMIN.value == "admin"

    def test_role_from_string(self):
        """Test converting string to Role."""
        assert Role.from_string("viewer") == Role.VIEWER
        assert Role.from_string("trader") == Role.TRADER
        assert Role.from_string("admin") == Role.ADMIN
        assert Role.from_string("ADMIN") == Role.ADMIN  # Case insensitive

    def test_role_from_string_invalid(self):
        """Test invalid role string defaults to viewer."""
        assert Role.from_string("invalid") == Role.VIEWER
        assert Role.from_string("") == Role.VIEWER


class TestPermissions:
    """Tests for permission system."""

    def test_viewer_permissions(self):
        """Test viewer has read-only permissions."""
        viewer_perms = ROLE_PERMISSIONS[Role.VIEWER]

        # Viewer can read
        assert Permission.USER_READ_SELF in viewer_perms
        assert Permission.BOT_READ in viewer_perms
        assert Permission.TRADE_READ in viewer_perms

        # Viewer cannot write
        assert Permission.USER_UPDATE_SELF not in viewer_perms
        assert Permission.BOT_CREATE not in viewer_perms
        assert Permission.TRADE_EXECUTE not in viewer_perms

    def test_trader_permissions(self):
        """Test trader has trading permissions."""
        trader_perms = ROLE_PERMISSIONS[Role.TRADER]

        # Trader can read and trade
        assert Permission.USER_READ_SELF in trader_perms
        assert Permission.BOT_CREATE in trader_perms
        assert Permission.BOT_START in trader_perms
        assert Permission.TRADE_EXECUTE in trader_perms

        # Trader cannot manage all users
        assert Permission.USER_READ_ALL not in trader_perms
        assert Permission.USER_DELETE not in trader_perms

    def test_admin_permissions(self):
        """Test admin has all permissions."""
        admin_perms = ROLE_PERMISSIONS[Role.ADMIN]

        # Admin has all management permissions
        assert Permission.USER_READ_ALL in admin_perms
        assert Permission.USER_UPDATE_ALL in admin_perms
        assert Permission.USER_DELETE in admin_perms
        assert Permission.USER_IMPERSONATE in admin_perms
        assert Permission.SYSTEM_CONFIG in admin_perms
        assert Permission.AUDIT_READ_ALL in admin_perms


class TestPermissionChecks:
    """Tests for permission check functions."""

    def test_has_permission(self):
        """Test single permission check."""
        assert has_permission(Role.ADMIN, Permission.USER_DELETE) is True
        assert has_permission(Role.TRADER, Permission.USER_DELETE) is False
        assert has_permission(Role.VIEWER, Permission.USER_DELETE) is False

    def test_has_any_permission(self):
        """Test any permission check."""
        perms = {Permission.BOT_CREATE, Permission.BOT_DELETE}

        assert has_any_permission(Role.ADMIN, perms) is True
        assert has_any_permission(Role.TRADER, perms) is True
        assert has_any_permission(Role.VIEWER, perms) is False

    def test_has_all_permissions(self):
        """Test all permissions check."""
        perms = {Permission.BOT_CREATE, Permission.BOT_START}

        assert has_all_permissions(Role.ADMIN, perms) is True
        assert has_all_permissions(Role.TRADER, perms) is True
        assert has_all_permissions(Role.VIEWER, perms) is False


class TestGetUserRole:
    """Tests for get_user_role function."""

    def test_admin_role(self):
        """Test admin detection from payload."""
        payload = create_test_payload(user_id=1, username="admin", is_admin=True)
        assert get_user_role(payload) == Role.ADMIN

    def test_trader_role(self):
        """Test trader role for non-admin."""
        payload = create_test_payload(user_id=2, username="trader", is_admin=False)
        assert get_user_role(payload) == Role.TRADER


class TestRoleChecker:
    """Tests for RoleChecker dependency."""

    def test_role_checker_init_single(self):
        """Test RoleChecker with single role."""
        checker = RoleChecker(Role.ADMIN)
        assert checker.allowed_roles == {Role.ADMIN}

    def test_role_checker_init_multiple(self):
        """Test RoleChecker with multiple roles."""
        checker = RoleChecker([Role.ADMIN, Role.TRADER])
        assert checker.allowed_roles == {Role.ADMIN, Role.TRADER}


class TestPermissionChecker:
    """Tests for PermissionChecker dependency."""

    def test_permission_checker_init_single(self):
        """Test PermissionChecker with single permission."""
        checker = PermissionChecker(Permission.BOT_START)
        assert checker.required_permissions == {Permission.BOT_START}
        assert checker.require_all is True

    def test_permission_checker_init_multiple(self):
        """Test PermissionChecker with multiple permissions."""
        checker = PermissionChecker(
            [Permission.BOT_START, Permission.BOT_STOP],
            require_all=False
        )
        assert checker.required_permissions == {Permission.BOT_START, Permission.BOT_STOP}
        assert checker.require_all is False


class TestEffectiveUserId:
    """Tests for get_effective_user_id function."""

    def test_no_target_returns_own_id(self):
        """Test that no target returns own user ID."""
        payload = create_test_payload(user_id=1, username="user", is_admin=False)
        assert get_effective_user_id(payload) == 1

    def test_admin_can_impersonate(self):
        """Test that admin can impersonate another user."""
        payload = create_test_payload(user_id=1, username="admin", is_admin=True)
        assert get_effective_user_id(payload, target_user_id=2) == 2

    def test_non_admin_cannot_impersonate(self):
        """Test that non-admin cannot impersonate."""
        from fastapi import HTTPException

        payload = create_test_payload(user_id=2, username="user", is_admin=False)
        with pytest.raises(HTTPException) as exc_info:
            get_effective_user_id(payload, target_user_id=1)
        assert exc_info.value.status_code == 403


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
