"""
Unit tests for authentication API routes.

Tests user registration, login, token refresh, and profile endpoints.
"""

import os
import pytest
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

# Set up test environment before imports
import base64
os.environ["JWT_SECRET"] = secrets.token_urlsafe(64)
# Generate a proper 32-byte key encoded as base64
test_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["ENCRYPTION_MASTER_KEY"] = test_key

from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.models.migrations.multi_tenant_schema import upgrade


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Run migration
    import asyncio
    asyncio.get_event_loop().run_until_complete(upgrade(db_path))

    yield db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def app(test_db, monkeypatch):
    """Create test FastAPI app with auth routes."""
    # Patch UserRepository to use test database
    from src.models.user import UserRepository
    from src.auth.dependencies import SessionManager

    original_user_init = UserRepository.__init__
    original_session_init = SessionManager.__init__

    def patched_user_init(self, db_path="data/trades.db"):
        self.db_path = Path(test_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def patched_session_init(self, db_path="data/trades.db"):
        self.db_path = test_db

    monkeypatch.setattr(UserRepository, "__init__", patched_user_init)
    monkeypatch.setattr(SessionManager, "__init__", patched_session_init)

    # Import router after patching
    from src.dashboard.auth_routes import router, limiter

    app = FastAPI()

    # Disable rate limiting for tests
    app.state.limiter = limiter
    limiter.enabled = False

    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


class TestRegistration:
    """Tests for user registration endpoint."""

    def test_register_success(self, client):
        """Test successful user registration."""
        response = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "SecurePass123"
        })

        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_register_invalid_username(self, client):
        """Test registration with invalid username."""
        response = client.post("/api/auth/register", json={
            "username": "test user!",  # Invalid characters
            "email": "test@example.com",
            "password": "SecurePass123"
        })

        assert response.status_code == 422

    def test_register_invalid_email(self, client):
        """Test registration with invalid email."""
        response = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "not-an-email",
            "password": "SecurePass123"
        })

        assert response.status_code == 422

    def test_register_weak_password(self, client):
        """Test registration with weak password."""
        response = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "weakpass"  # No uppercase or digits
        })

        assert response.status_code == 422

    def test_register_short_password(self, client):
        """Test registration with too short password."""
        response = client.post("/api/auth/register", json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "Ab1"  # Too short
        })

        assert response.status_code == 422

    def test_register_duplicate_username(self, client):
        """Test registration with duplicate username."""
        # First registration
        client.post("/api/auth/register", json={
            "username": "duplicate",
            "email": "first@example.com",
            "password": "SecurePass123"
        })

        # Second registration with same username
        response = client.post("/api/auth/register", json={
            "username": "duplicate",
            "email": "second@example.com",
            "password": "SecurePass123"
        })

        assert response.status_code == 409
        assert "Username already registered" in response.json()["detail"]

    def test_register_duplicate_email(self, client):
        """Test registration with duplicate email."""
        # First registration
        client.post("/api/auth/register", json={
            "username": "user1",
            "email": "same@example.com",
            "password": "SecurePass123"
        })

        # Second registration with same email
        response = client.post("/api/auth/register", json={
            "username": "user2",
            "email": "same@example.com",
            "password": "SecurePass123"
        })

        assert response.status_code == 409
        assert "Email already registered" in response.json()["detail"]


class TestLogin:
    """Tests for user login endpoint."""

    def test_login_success(self, client):
        """Test successful login."""
        # Register user first
        client.post("/api/auth/register", json={
            "username": "logintest",
            "email": "login@example.com",
            "password": "SecurePass123"
        })

        # Login
        response = client.post("/api/auth/login", json={
            "username": "logintest",
            "password": "SecurePass123"
        })

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_login_wrong_password(self, client):
        """Test login with wrong password."""
        # Register user first
        client.post("/api/auth/register", json={
            "username": "wrongpass",
            "email": "wrongpass@example.com",
            "password": "SecurePass123"
        })

        # Login with wrong password
        response = client.post("/api/auth/login", json={
            "username": "wrongpass",
            "password": "WrongPassword123"
        })

        assert response.status_code == 401
        assert "Invalid username or password" in response.json()["detail"]

    def test_login_nonexistent_user(self, client):
        """Test login with nonexistent user."""
        response = client.post("/api/auth/login", json={
            "username": "doesnotexist",
            "password": "SecurePass123"
        })

        assert response.status_code == 401
        assert "Invalid username or password" in response.json()["detail"]


class TestTokenRefresh:
    """Tests for token refresh endpoint."""

    def test_refresh_token_success(self, client):
        """Test successful token refresh."""
        # Register and get tokens
        reg_response = client.post("/api/auth/register", json={
            "username": "refreshtest",
            "email": "refresh@example.com",
            "password": "SecurePass123"
        })

        refresh_token = reg_response.json()["refresh_token"]

        # Refresh token
        response = client.post("/api/auth/refresh", json={
            "refresh_token": refresh_token
        })

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New tokens should be different
        assert data["refresh_token"] != refresh_token

    def test_refresh_invalid_token(self, client):
        """Test refresh with invalid token."""
        response = client.post("/api/auth/refresh", json={
            "refresh_token": "invalid.token.here"
        })

        assert response.status_code == 401


class TestProfile:
    """Tests for user profile endpoints."""

    def test_get_profile_success(self, client):
        """Test getting user profile."""
        # Register and get tokens
        reg_response = client.post("/api/auth/register", json={
            "username": "profiletest",
            "email": "profile@example.com",
            "password": "SecurePass123"
        })

        access_token = reg_response.json()["access_token"]

        # Get profile
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "profiletest"
        assert data["email"] == "profile@example.com"
        assert data["is_admin"] is False

    def test_get_profile_unauthorized(self, client):
        """Test getting profile without auth."""
        response = client.get("/api/auth/me")

        assert response.status_code == 401

    def test_update_email(self, client):
        """Test updating user email."""
        # Register and get tokens
        reg_response = client.post("/api/auth/register", json={
            "username": "emailupdate",
            "email": "old@example.com",
            "password": "SecurePass123"
        })

        access_token = reg_response.json()["access_token"]

        # Update email
        response = client.put(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"email": "new@example.com"}
        )

        assert response.status_code == 200
        assert response.json()["email"] == "new@example.com"

    def test_update_password(self, client):
        """Test updating user password."""
        # Register and get tokens
        reg_response = client.post("/api/auth/register", json={
            "username": "passupdate",
            "email": "passupdate@example.com",
            "password": "OldPassword123"
        })

        access_token = reg_response.json()["access_token"]

        # Update password
        response = client.put(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "current_password": "OldPassword123",
                "new_password": "NewPassword456"
            }
        )

        assert response.status_code == 200

        # Verify new password works
        login_response = client.post("/api/auth/login", json={
            "username": "passupdate",
            "password": "NewPassword456"
        })

        assert login_response.status_code == 200

    def test_update_password_wrong_current(self, client):
        """Test updating password with wrong current password."""
        # Register and get tokens
        reg_response = client.post("/api/auth/register", json={
            "username": "wrongcurrent",
            "email": "wrongcurrent@example.com",
            "password": "CorrectPass123"
        })

        access_token = reg_response.json()["access_token"]

        # Try update with wrong current password
        response = client.put(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "current_password": "WrongPassword123",
                "new_password": "NewPassword456"
            }
        )

        assert response.status_code == 401


class TestLogout:
    """Tests for logout endpoint."""

    def test_logout_success(self, client):
        """Test successful logout."""
        # Register and get tokens
        reg_response = client.post("/api/auth/register", json={
            "username": "logouttest",
            "email": "logout@example.com",
            "password": "SecurePass123"
        })

        access_token = reg_response.json()["access_token"]

        # Logout
        response = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 200
        assert response.json()["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
