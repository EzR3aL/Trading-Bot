"""
Integration tests for the authentication flow.

Covers:
    - Login (success, wrong password, nonexistent user)
    - Protected endpoint access (with / without token)
    - Token refresh

Endpoints under test:
    POST /api/auth/login
    GET  /api/auth/me
    POST /api/auth/refresh
"""

import pytest

from src.errors import ERR_INVALID_CREDENTIALS
from tests.integration.conftest import auth_header


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_login_success(client, admin_token):
    """A valid admin user can log in and receive tokens."""
    # admin_token fixture already authenticates; verify directly.
    assert admin_token is not None

    # Also verify the full response shape.

    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123456"},
    )
    assert response.status_code == 200

    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.integration
async def test_login_wrong_password(client, admin_token):
    """Login with correct username but wrong password returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == ERR_INVALID_CREDENTIALS


@pytest.mark.integration
async def test_login_nonexistent_user(client, test_db):
    """Login with a username that does not exist returns 401."""
    response = await client.post(
        "/api/auth/login",
        json={"username": "ghost_user", "password": "doesntmatter"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == ERR_INVALID_CREDENTIALS


# ---------------------------------------------------------------------------
# Protected endpoint access
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_access_protected_endpoint_without_token(client, test_db):
    """GET /api/auth/me without Authorization header returns 401."""
    response = await client.get("/api/auth/me")
    assert response.status_code in (401, 403)


@pytest.mark.integration
async def test_access_protected_endpoint_with_valid_token(client, admin_token):
    """GET /api/auth/me with a valid token returns the user profile."""
    assert admin_token is not None

    response = await client.get("/api/auth/me", headers=auth_header(admin_token))
    assert response.status_code == 200

    body = response.json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    assert body["is_active"] is True


@pytest.mark.integration
async def test_access_protected_endpoint_with_invalid_token(client, test_db):
    """GET /api/auth/me with a garbage token returns 401."""
    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer this.is.not.a.valid.jwt"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_refresh_token(client, admin_token):
    """A valid refresh token (httpOnly cookie) can be exchanged for a new access token."""
    # First, obtain the refresh token cookie via login.
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123456"},
    )
    assert login_resp.status_code == 200

    # Extract refresh_token cookie from Set-Cookie header
    refresh_cookie = login_resp.cookies.get("refresh_token")
    assert refresh_cookie, "Login should set refresh_token httpOnly cookie"

    # Exchange the refresh token via cookie.
    refresh_resp = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert refresh_resp.status_code == 200

    # SEC-012: access_token is only in httpOnly cookie, not response body.
    new_access = refresh_resp.cookies.get("access_token")
    assert new_access, "Refresh should set a new access_token httpOnly cookie"
    assert refresh_resp.json()["token_type"] == "bearer"

    # The new access token should work on a protected endpoint.
    me_resp = await client.get(
        "/api/auth/me",
        headers=auth_header(new_access),
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "admin"


@pytest.mark.integration
async def test_refresh_token_with_invalid_token(client, test_db):
    """An invalid refresh token is rejected."""
    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": "not.a.real.token"},
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_logout_invalidates_session(client, admin_token):
    """After logout, the refresh token cookie should no longer work."""
    # Login to get a refresh cookie
    login_resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123456"},
    )
    assert login_resp.status_code == 200
    refresh_cookie = login_resp.cookies.get("refresh_token")
    assert refresh_cookie

    # Logout — invalidates session in DB and clears cookie
    logout_resp = await client.post(
        "/api/auth/logout",
        cookies={"refresh_token": refresh_cookie},
    )
    assert logout_resp.status_code == 200

    # Try to refresh with the old cookie — should be rejected
    refresh_resp = await client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": refresh_cookie},
    )
    assert refresh_resp.status_code == 401
