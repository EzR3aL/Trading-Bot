"""
Tests for authentication endpoints.

Covers login, token refresh, profile access, invalid credentials,
expired tokens, and access without tokens.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

# Ensure env vars are set before imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.auth.jwt_handler import create_access_token, create_refresh_token


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_valid_credentials(client, test_user):
    """Successful login returns access_token and refresh_token."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 1800


@pytest.mark.asyncio
async def test_login_with_wrong_password(client, test_user):
    """Login with incorrect password returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert "Invalid username or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_with_nonexistent_user(client, test_user):
    """Login with unknown username returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "nonexistent", "password": "anypassword"},
    )
    assert response.status_code == 401
    assert "Invalid username or password" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_with_empty_username(client, test_user):
    """Login with empty username returns 422 validation error."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "", "password": "testpassword123"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_with_empty_password(client, test_user):
    """Login with empty password returns 422 validation error."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": ""},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Token refresh tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_flow(client, test_user, refresh_token_str):
    """Valid refresh token returns new access and refresh tokens."""
    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token_str},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_refresh_with_invalid_token(client, test_user):
    """Invalid refresh token returns 401."""
    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": "invalid.token.string"},
    )
    assert response.status_code == 401
    assert "Invalid refresh token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_with_access_token_instead(client, test_user):
    """Using an access token as refresh token returns 401."""
    token_data = {"sub": str(test_user.id), "role": test_user.role}
    access_token = create_access_token(token_data)
    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert response.status_code == 401
    assert "Invalid refresh token" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Protected endpoint access tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_protected_endpoint_with_valid_token(client, test_user, auth_headers):
    """Accessing /me with a valid token returns user profile."""
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"
    assert data["role"] == "admin"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_access_protected_endpoint_without_token(client, test_user):
    """Accessing /me without a token returns 401."""
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_protected_endpoint_with_invalid_token(client, test_user):
    """Accessing /me with garbage token returns 401."""
    headers = {"Authorization": "Bearer invalid.token.garbage"}
    response = await client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_protected_endpoint_with_expired_token(client, test_user):
    """Accessing /me with an expired token returns 401."""
    token_data = {"sub": str(test_user.id), "role": test_user.role}
    # Create a token that expired 1 hour ago
    expired_token = create_access_token(
        token_data, expires_delta=timedelta(hours=-1)
    )
    headers = {"Authorization": f"Bearer {expired_token}"}
    response = await client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_access_with_refresh_token_instead_of_access(client, test_user, refresh_token_str):
    """Using a refresh token as access token returns 401 (wrong token type)."""
    headers = {"Authorization": f"Bearer {refresh_token_str}"}
    response = await client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
