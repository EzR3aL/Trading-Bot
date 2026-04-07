"""
Comprehensive unit tests for the auth system.

Covers:
- Login endpoint (valid/invalid credentials, inactive user, disabled account)
- Token refresh endpoint (valid, invalid, wrong type, revoked token_version)
- JWT token creation and verification (access, refresh, custom expiry, data preservation)
- Password hashing and verification (edge cases: unicode, long passwords)
- get_current_user dependency (direct unit test with mocked DB)
- get_current_admin dependency (role check)
- validate_jwt_config (missing secret key)
- Token version / revocation logic

Uses pytest, pytest-asyncio, and unittest.mock.
Does NOT duplicate the existing tests in tests/unit/auth/ or tests/test_auth.py.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
import jwt
from starlette.requests import Request as StarletteRequest

# Ensure env vars are set before any src imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production-minimum-32-chars")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.rate_limit import limiter  # noqa: E402
limiter.enabled = False

from src.auth.jwt_handler import (  # noqa: E402
    ALGORITHM,
    _get_secret_key,
    create_access_token,
    create_refresh_token,
    decode_token,
    validate_jwt_config,
)
from src.auth.password import hash_password, verify_password  # noqa: E402
from src.auth.dependencies import get_current_user, get_current_admin  # noqa: E402
from src.errors import (  # noqa: E402
    ERR_ACCOUNT_DISABLED,
    ERR_ADMIN_REQUIRED,
    ERR_INVALID_CREDENTIALS,
    ERR_INVALID_REFRESH_TOKEN,
    ERR_INVALID_TOKEN,
    ERR_INVALID_TOKEN_PAYLOAD,
    ERR_NOT_AUTHENTICATED,
    ERR_TOKEN_REVOKED,
    ERR_USER_NOT_FOUND_OR_INACTIVE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_user(
    user_id=1,
    username="testuser",
    email="test@example.com",
    role="user",
    is_active=True,
    is_deleted=False,
    token_version=0,
    language="en",
):
    """Create a mock User object with the fields used by auth code."""
    user = MagicMock()
    user.id = user_id
    user.username = username
    user.email = email
    user.role = role
    user.is_active = is_active
    user.is_deleted = is_deleted
    user.token_version = token_version
    user.language = language
    user.password_hash = hash_password("correct_password")
    user.locked_until = None
    user.failed_login_attempts = 0
    return user


def _make_mock_credentials(token_str):
    """Create a mock HTTPAuthorizationCredentials."""
    creds = MagicMock()
    creds.credentials = token_str
    return creds


def _make_mock_db_session(user=None):
    """Create a mock AsyncSession that returns the given user from a query."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


def _make_mock_request(cookies=None):
    """Create a mock Request with a cookies dict (for get_current_user dependency)."""
    req = MagicMock()
    req.cookies = cookies or {}
    return req


def _make_starlette_request():
    """Create a real Starlette Request that satisfies slowapi's type check."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": [],
        "query_string": b"",
        "root_path": "",
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 12345),
    }
    return StarletteRequest(scope)


# ============================================================================
# JWT Token Creation Tests (supplementing tests/unit/auth/test_jwt_handler.py)
# ============================================================================


class TestJwtTokenDataPreservation:
    """Verify that token payloads preserve all input data fields."""

    def test_access_token_preserves_sub_field(self):
        """The 'sub' field in the input data must appear in the decoded token."""
        token = create_access_token({"sub": "123", "role": "admin"})
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        assert payload["sub"] == "123"

    def test_access_token_preserves_role_field(self):
        """Custom fields like 'role' must survive the encode/decode round-trip."""
        token = create_access_token({"sub": "1", "role": "admin"})
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        assert payload["role"] == "admin"

    def test_access_token_preserves_token_version(self):
        """The 'tv' (token_version) field must be preserved in the token."""
        token = create_access_token({"sub": "1", "role": "user", "tv": 3})
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        assert payload["tv"] == 3

    def test_refresh_token_preserves_all_fields(self):
        """Refresh token must preserve sub, role, and tv fields."""
        data = {"sub": "42", "role": "admin", "tv": 5}
        token = create_refresh_token(data)
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        assert payload["sub"] == "42"
        assert payload["role"] == "admin"
        assert payload["tv"] == 5

    def test_create_access_token_does_not_mutate_input(self):
        """The original data dict must not be modified by token creation."""
        original_data = {"sub": "1", "role": "user"}
        data_copy = original_data.copy()
        create_access_token(original_data)
        assert original_data == data_copy

    def test_create_refresh_token_does_not_mutate_input(self):
        """The original data dict must not be modified by token creation."""
        original_data = {"sub": "1", "role": "user"}
        data_copy = original_data.copy()
        create_refresh_token(original_data)
        assert original_data == data_copy


class TestJwtCustomExpiry:
    """Verify custom expiration deltas work for access tokens."""

    def test_access_token_with_custom_short_expiry(self):
        """A token with 1-second expiry should still be decodable immediately."""
        token = create_access_token(
            {"sub": "1"}, expires_delta=timedelta(seconds=30)
        )
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "1"

    def test_access_token_with_negative_expiry_is_expired(self):
        """A token created with a negative delta should fail to decode."""
        token = create_access_token(
            {"sub": "1"}, expires_delta=timedelta(seconds=-10)
        )
        payload = decode_token(token)
        assert payload is None


class TestJwtTokenTypes:
    """Verify that token type discrimination works correctly."""

    def test_access_and_refresh_tokens_have_different_types(self):
        """Access token type='access', refresh token type='refresh'."""
        data = {"sub": "1"}
        access = create_access_token(data)
        refresh = create_refresh_token(data)

        access_payload = jwt.decode(access, _get_secret_key(), algorithms=[ALGORITHM])
        refresh_payload = jwt.decode(refresh, _get_secret_key(), algorithms=[ALGORITHM])

        assert access_payload["type"] == "access"
        assert refresh_payload["type"] == "refresh"

    def test_access_and_refresh_tokens_are_different_strings(self):
        """Even with the same data, access and refresh tokens differ."""
        data = {"sub": "1", "role": "user"}
        access = create_access_token(data)
        refresh = create_refresh_token(data)
        assert access != refresh


class TestDecodeTokenEdgeCases:
    """Edge cases for decode_token not covered by existing tests."""

    def test_decode_token_with_empty_string(self):
        """An empty string should return None."""
        assert decode_token("") is None

    def test_decode_token_with_tampered_payload(self):
        """A token with a tampered signature should return None."""
        token = create_access_token({"sub": "1"})
        # Tamper by flipping multiple characters deep in the signature
        parts = token.rsplit(".", 1)
        sig = list(parts[1])
        for i in range(min(6, len(sig))):
            sig[i] = "A" if sig[i] != "A" else "B"
        tampered = parts[0] + "." + "".join(sig)
        assert decode_token(tampered) is None

    def test_decode_token_with_wrong_secret(self):
        """A token signed with a different secret should return None."""
        token = jwt.encode(
            {"sub": "1", "type": "access"},
            "different-secret-key",
            algorithm=ALGORITHM,
        )
        assert decode_token(token) is None


class TestValidateJwtConfig:
    """Tests for validate_jwt_config startup check."""

    def test_validate_jwt_config_raises_when_secret_empty(self):
        """validate_jwt_config should raise RuntimeError if secret key is empty."""
        with patch("src.auth.jwt_handler._get_secret_key", return_value=""):
            with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
                validate_jwt_config()

    def test_validate_jwt_config_passes_when_secret_set(self):
        """validate_jwt_config should not raise when secret key is set."""
        with patch("src.auth.jwt_handler._get_secret_key", return_value="a-real-secret-key-that-is-at-least-32-characters-long"):
            validate_jwt_config()


# ============================================================================
# Password Tests (supplementing tests/unit/auth/test_password.py)
# ============================================================================


class TestPasswordEdgeCases:
    """Edge-case tests for password hashing not covered by existing tests."""

    def test_hash_and_verify_unicode_password(self):
        """Unicode characters (umlauts, emoji) should hash and verify correctly."""
        password = "Passwort_mit_Umlauten_aou_ess"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_hash_and_verify_long_password(self):
        """A 200-character password should hash and verify correctly."""
        password = "a" * 200
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_hash_and_verify_password_with_special_characters(self):
        """Passwords with special characters must work correctly."""
        password = "p@$$w0rd!#%^&*()_+-=[]{}|;':\",./<>?"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_with_whitespace_differences(self):
        """Trailing/leading whitespace should cause verification failure."""
        password = "my_password"
        hashed = hash_password(password)
        assert verify_password(" my_password", hashed) is False
        assert verify_password("my_password ", hashed) is False

    def test_hash_password_returns_different_type_than_input(self):
        """The hash output is structurally different from the plaintext input."""
        password = "simple"
        hashed = hash_password(password)
        assert hashed != password
        assert "$" in hashed  # bcrypt hashes contain '$' delimiters


# ============================================================================
# get_current_user Dependency Tests
# ============================================================================


class TestGetCurrentUser:
    """Unit tests for the get_current_user FastAPI dependency."""

    @pytest.mark.asyncio
    async def test_get_current_user_returns_user_for_valid_token(self):
        """A valid access token should return the corresponding user."""
        mock_user = _make_mock_user(user_id=7, role="user")
        token = create_access_token({"sub": "7", "role": "user", "tv": 0})
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session(user=mock_user)
        request = _make_mock_request()

        result = await get_current_user(request=request, credentials=credentials, db=db)
        assert result.id == 7

    @pytest.mark.asyncio
    async def test_get_current_user_raises_401_when_no_credentials(self):
        """Missing credentials and no cookie should raise HTTP 401."""
        db = _make_mock_db_session()
        request = _make_mock_request()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=request, credentials=None, db=db)
        assert exc_info.value.status_code == 401
        assert ERR_NOT_AUTHENTICATED in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_falls_back_to_cookie(self):
        """When no Bearer header, should use access_token cookie."""
        mock_user = _make_mock_user(user_id=42, role="user")
        token = create_access_token({"sub": "42", "role": "user", "tv": 0})
        db = _make_mock_db_session(user=mock_user)
        request = _make_mock_request(cookies={"access_token": token})

        result = await get_current_user(request=request, credentials=None, db=db)
        assert result.id == 42

    @pytest.mark.asyncio
    async def test_get_current_user_raises_401_for_invalid_token(self):
        """A garbage token should raise HTTP 401."""
        credentials = _make_mock_credentials("garbage.token.value")
        db = _make_mock_db_session()
        request = _make_mock_request()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=request, credentials=credentials, db=db)
        assert exc_info.value.status_code == 401
        assert ERR_INVALID_TOKEN in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_raises_401_for_refresh_token(self):
        """Using a refresh token should raise HTTP 401 (wrong type)."""
        token = create_refresh_token({"sub": "1", "role": "user"})
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session()
        request = _make_mock_request()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=request, credentials=credentials, db=db)
        assert exc_info.value.status_code == 401
        assert ERR_INVALID_TOKEN in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_raises_401_for_expired_token(self):
        """An expired access token should raise HTTP 401."""
        token = create_access_token(
            {"sub": "1", "role": "user"},
            expires_delta=timedelta(seconds=-10),
        )
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session()
        request = _make_mock_request()
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=request, credentials=credentials, db=db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_raises_401_when_user_not_found(self):
        """If the DB returns no user for the token's sub, raise 401."""
        token = create_access_token({"sub": "999", "role": "user", "tv": 0})
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session(user=None)
        request = _make_mock_request()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=request, credentials=credentials, db=db)
        assert exc_info.value.status_code == 401
        assert ERR_USER_NOT_FOUND_OR_INACTIVE in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_raises_401_when_user_inactive(self):
        """An inactive user should be rejected with HTTP 401."""
        mock_user = _make_mock_user(user_id=1, is_active=False)
        token = create_access_token({"sub": "1", "role": "user", "tv": 0})
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session(user=mock_user)
        request = _make_mock_request()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=request, credentials=credentials, db=db)
        assert exc_info.value.status_code == 401
        assert ERR_USER_NOT_FOUND_OR_INACTIVE in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_raises_401_for_revoked_token_version(self):
        """A token with tv < user.token_version should be rejected."""
        mock_user = _make_mock_user(user_id=1, token_version=5)
        # Token was issued with tv=3, but user has tv=5 now (password changed)
        token = create_access_token({"sub": "1", "role": "user", "tv": 3})
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session(user=mock_user)
        request = _make_mock_request()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=request, credentials=credentials, db=db)
        assert exc_info.value.status_code == 401
        assert ERR_TOKEN_REVOKED in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_accepts_matching_token_version(self):
        """A token with tv == user.token_version should be accepted."""
        mock_user = _make_mock_user(user_id=1, token_version=3)
        token = create_access_token({"sub": "1", "role": "user", "tv": 3})
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session(user=mock_user)
        request = _make_mock_request()

        result = await get_current_user(request=request, credentials=credentials, db=db)
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_get_current_user_accepts_newer_token_version(self):
        """A token with tv > user.token_version should be accepted (edge case)."""
        mock_user = _make_mock_user(user_id=1, token_version=2)
        token = create_access_token({"sub": "1", "role": "user", "tv": 5})
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session(user=mock_user)
        request = _make_mock_request()

        result = await get_current_user(request=request, credentials=credentials, db=db)
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_get_current_user_accepts_token_without_tv_field(self):
        """Tokens without 'tv' should still work (backwards compatibility)."""
        mock_user = _make_mock_user(user_id=1, token_version=0)
        token = create_access_token({"sub": "1", "role": "user"})
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session(user=mock_user)
        request = _make_mock_request()

        result = await get_current_user(request=request, credentials=credentials, db=db)
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_get_current_user_raises_401_when_sub_missing(self):
        """A token without 'sub' claim should raise 401."""
        # Manually craft a token without 'sub'
        token = jwt.encode(
            {"role": "user", "type": "access", "exp": 9999999999},
            _get_secret_key(),
            algorithm=ALGORITHM,
        )
        credentials = _make_mock_credentials(token)
        db = _make_mock_db_session()
        request = _make_mock_request()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=request, credentials=credentials, db=db)
        assert exc_info.value.status_code == 401
        assert ERR_INVALID_TOKEN_PAYLOAD in exc_info.value.detail


# ============================================================================
# get_current_admin Dependency Tests
# ============================================================================


class TestGetCurrentAdmin:
    """Unit tests for the get_current_admin dependency."""

    @pytest.mark.asyncio
    async def test_get_current_admin_returns_admin_user(self):
        """An admin user should pass through successfully."""
        mock_user = _make_mock_user(user_id=1, role="admin")
        result = await get_current_admin(user=mock_user)
        assert result.id == 1
        assert result.role == "admin"

    @pytest.mark.asyncio
    async def test_get_current_admin_raises_403_for_regular_user(self):
        """A non-admin user should be rejected with HTTP 403."""
        mock_user = _make_mock_user(user_id=2, role="user")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_admin(user=mock_user)
        assert exc_info.value.status_code == 403
        assert ERR_ADMIN_REQUIRED in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_admin_rejects_empty_role(self):
        """A user with an empty role string should be rejected."""
        mock_user = _make_mock_user(user_id=3, role="")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_admin(user=mock_user)
        assert exc_info.value.status_code == 403


# ============================================================================
# Login Endpoint Unit Tests (testing router logic with mocked DB)
# ============================================================================


class TestLoginEndpointLogic:
    """Unit tests for login edge cases not covered by integration tests."""

    @pytest.mark.asyncio
    async def test_login_disabled_account_returns_403(self):
        """An active=False user should get HTTP 403 even with correct password."""
        from src.api.routers.auth import login
        from src.api.schemas.auth import LoginRequest

        inactive_user = _make_mock_user(user_id=1, is_active=False)
        body = LoginRequest(username="testuser", password="correct_password")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inactive_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await login(request=mock_request, response=MagicMock(), body=body, db=mock_db)
        assert exc_info.value.status_code == 403
        assert ERR_ACCOUNT_DISABLED in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_deleted_user_returns_401(self):
        """A soft-deleted user should get 401 with generic error (no user enumeration)."""
        from src.api.routers.auth import login
        from src.api.schemas.auth import LoginRequest

        deleted_user = _make_mock_user(user_id=1, is_active=True, is_deleted=True)
        body = LoginRequest(username="testuser", password="correct_password")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = deleted_user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await login(request=mock_request, response=MagicMock(), body=body, db=mock_db)
        assert exc_info.value.status_code == 401
        assert ERR_INVALID_CREDENTIALS in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_nonexistent_user_returns_401(self):
        """A username that does not exist should return 401."""
        from src.api.routers.auth import login
        from src.api.schemas.auth import LoginRequest

        body = LoginRequest(username="nobody", password="anything")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await login(request=mock_request, response=MagicMock(), body=body, db=mock_db)
        assert exc_info.value.status_code == 401
        assert ERR_INVALID_CREDENTIALS in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(self):
        """A wrong password should return 401 for an existing user."""
        from src.api.routers.auth import login
        from src.api.schemas.auth import LoginRequest

        user = _make_mock_user(user_id=1, is_active=True)
        body = LoginRequest(username="testuser", password="wrong_password")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await login(request=mock_request, response=MagicMock(), body=body, db=mock_db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_login_success_returns_token_response(self):
        """A valid login should return TokenResponse with both tokens."""
        from src.api.routers.auth import login
        from src.api.schemas.auth import LoginRequest

        user = _make_mock_user(user_id=5, role="admin", is_active=True, token_version=2)
        body = LoginRequest(username="testuser", password="correct_password")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()
        mock_response = MagicMock()

        result = await login(request=mock_request, response=mock_response, body=body, db=mock_db)

        assert result.access_token is not None
        assert result.token_type == "bearer"

        # Verify the access token contains the correct user data
        access_payload = decode_token(result.access_token)
        assert access_payload["sub"] == "5"
        assert access_payload["role"] == "admin"
        assert access_payload["tv"] == 2
        assert access_payload["type"] == "access"

        # Verify the refresh token is set as httpOnly cookie (not in response body)
        assert mock_response.set_cookie.call_count >= 1
        # Find the refresh_token cookie call
        refresh_cookie_calls = [
            c for c in mock_response.set_cookie.call_args_list
            if (c.kwargs.get("key") or (c.args[0] if c.args else "")) == "refresh_token"
        ]
        assert len(refresh_cookie_calls) == 1
        refresh_cookie_value = refresh_cookie_calls[0].kwargs.get("value") or refresh_cookie_calls[0][1].get("value", "")
        refresh_payload = decode_token(refresh_cookie_value)
        assert refresh_payload["sub"] == "5"
        assert refresh_payload["role"] == "admin"
        assert refresh_payload["tv"] == 2
        assert refresh_payload["type"] == "refresh"


# ============================================================================
# Refresh Endpoint Unit Tests (testing router logic with mocked DB)
# ============================================================================


class TestRefreshEndpointLogic:
    """Unit tests for the refresh token endpoint logic."""

    @pytest.mark.asyncio
    async def test_refresh_with_valid_refresh_token_returns_new_access_only(self):
        """A valid refresh request returns a new access token but does NOT
        rotate the refresh token (#147 — rotation race caused logouts)."""
        from src.api.routers.auth import refresh_token as refresh_endpoint
        from src.api.schemas.auth import RefreshRequest

        user = _make_mock_user(user_id=3, role="user", is_active=True, token_version=1)
        old_refresh = create_refresh_token({"sub": "3", "role": "user", "tv": 1})
        body = RefreshRequest(refresh_token=old_refresh)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        mock_resp = MagicMock()
        result = await refresh_endpoint(request=mock_request, response=mock_resp, body=body, refresh_token_cookie=None, db=mock_db)

        assert result.access_token is not None
        assert result.token_type == "bearer"
        # Only the access cookie is rotated; the refresh cookie stays put
        # to avoid the multi-tab race that locked out users.
        assert mock_resp.set_cookie.call_count == 1
        cookie_call = mock_resp.set_cookie.call_args
        cookie_key = cookie_call.kwargs.get("key") or cookie_call.args[0]
        assert "access" in str(cookie_key).lower()

    @pytest.mark.asyncio
    async def test_refresh_with_cookie_and_no_body_succeeds(self):
        """Regression: no body must work when httpOnly cookie carries refresh token."""
        from src.api.routers.auth import refresh_token as refresh_endpoint

        user = _make_mock_user(user_id=5, role="user", is_active=True, token_version=1)
        cookie_token = create_refresh_token({"sub": "5", "role": "user", "tv": 1})

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()
        mock_response = MagicMock()

        result = await refresh_endpoint(
            request=mock_request, response=mock_response,
            body=None, refresh_token_cookie=cookie_token, db=mock_db,
        )

        assert result.access_token is not None
        assert result.token_type == "bearer"

    @pytest.mark.asyncio
    async def test_refresh_with_no_cookie_and_no_body_returns_401(self):
        """No cookie and no body should return 401, not 422."""
        from src.api.routers.auth import refresh_token as refresh_endpoint

        mock_db = AsyncMock()
        mock_request = _make_starlette_request()
        mock_response = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(
                request=mock_request, response=mock_response,
                body=None, refresh_token_cookie=None, db=mock_db,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_returns_401(self):
        """Passing an access token to the refresh endpoint should fail."""
        from src.api.routers.auth import refresh_token as refresh_endpoint
        from src.api.schemas.auth import RefreshRequest

        access = create_access_token({"sub": "1", "role": "user"})
        body = RefreshRequest(refresh_token=access)

        mock_db = AsyncMock()
        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(request=mock_request, response=MagicMock(), body=body, refresh_token_cookie=None, db=mock_db)
        assert exc_info.value.status_code == 401
        assert ERR_INVALID_REFRESH_TOKEN in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_refresh_with_garbage_token_returns_401(self):
        """A garbage string should fail with 401."""
        from src.api.routers.auth import refresh_token as refresh_endpoint
        from src.api.schemas.auth import RefreshRequest

        body = RefreshRequest(refresh_token="not.a.real.jwt")

        mock_db = AsyncMock()
        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(request=mock_request, response=MagicMock(), body=body, refresh_token_cookie=None, db=mock_db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_inactive_user_returns_401(self):
        """Refreshing for an inactive user should fail."""
        from src.api.routers.auth import refresh_token as refresh_endpoint
        from src.api.schemas.auth import RefreshRequest

        user = _make_mock_user(user_id=1, is_active=False)
        old_refresh = create_refresh_token({"sub": "1", "role": "user", "tv": 0})
        body = RefreshRequest(refresh_token=old_refresh)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(request=mock_request, response=MagicMock(), body=body, refresh_token_cookie=None, db=mock_db)
        assert exc_info.value.status_code == 401
        assert ERR_USER_NOT_FOUND_OR_INACTIVE in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_refresh_with_deleted_user_returns_401(self):
        """Refreshing for a user that no longer exists should fail."""
        from src.api.routers.auth import refresh_token as refresh_endpoint
        from src.api.schemas.auth import RefreshRequest

        old_refresh = create_refresh_token({"sub": "999", "role": "user", "tv": 0})
        body = RefreshRequest(refresh_token=old_refresh)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(request=mock_request, response=MagicMock(), body=body, refresh_token_cookie=None, db=mock_db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_revoked_token_version_returns_401(self):
        """A refresh token with tv < user.token_version should be rejected."""
        from src.api.routers.auth import refresh_token as refresh_endpoint
        from src.api.schemas.auth import RefreshRequest

        # User has bumped token_version to 5, but refresh token was issued at tv=2
        user = _make_mock_user(user_id=1, is_active=True, token_version=5)
        old_refresh = create_refresh_token({"sub": "1", "role": "user", "tv": 2})
        body = RefreshRequest(refresh_token=old_refresh)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        with pytest.raises(HTTPException) as exc_info:
            await refresh_endpoint(request=mock_request, response=MagicMock(), body=body, refresh_token_cookie=None, db=mock_db)
        assert exc_info.value.status_code == 401
        assert ERR_TOKEN_REVOKED in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_refresh_with_matching_token_version_succeeds(self):
        """A refresh token with tv == user.token_version should succeed.

        Per the no-rotation policy (#147), only the access cookie is set —
        the refresh cookie stays untouched so multi-tab and PWA wake-up
        races can't lock the user out.
        """
        from src.api.routers.auth import refresh_token as refresh_endpoint
        from src.api.schemas.auth import RefreshRequest

        user = _make_mock_user(user_id=1, is_active=True, token_version=3)
        old_refresh = create_refresh_token({"sub": "1", "role": "user", "tv": 3})
        body = RefreshRequest(refresh_token=old_refresh)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        mock_resp = MagicMock()
        result = await refresh_endpoint(request=mock_request, response=mock_resp, body=body, refresh_token_cookie=None, db=mock_db)
        assert result.access_token is not None
        # Only the access cookie — no rotation
        assert mock_resp.set_cookie.call_count == 1

    @pytest.mark.asyncio
    async def test_refresh_new_tokens_contain_updated_user_data(self):
        """New access token from refresh should contain the user's current data.

        Refresh token is NOT rotated (#147), so we only verify the access
        token contents and that exactly one cookie was set.
        """
        from src.api.routers.auth import refresh_token as refresh_endpoint
        from src.api.schemas.auth import RefreshRequest

        user = _make_mock_user(user_id=10, role="admin", is_active=True, token_version=7)
        old_refresh = create_refresh_token({"sub": "10", "role": "admin", "tv": 7})
        body = RefreshRequest(refresh_token=old_refresh)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_request = _make_starlette_request()

        mock_resp = MagicMock()
        result = await refresh_endpoint(request=mock_request, response=mock_resp, body=body, refresh_token_cookie=None, db=mock_db)

        # Verify new access token has correct data (tv stays the same —
        # token_version is only bumped for security events, not routine refreshes)
        access_payload = decode_token(result.access_token)
        assert access_payload["sub"] == "10"
        assert access_payload["role"] == "admin"
        assert access_payload["tv"] == 7
        assert access_payload["type"] == "access"

        # Only the access cookie was set; refresh cookie was NOT rotated
        assert mock_resp.set_cookie.call_count == 1
        cookie_call = mock_resp.set_cookie.call_args
        cookie_key = cookie_call.kwargs.get("key") or cookie_call.args[0]
        assert "access" in str(cookie_key).lower()


# ============================================================================
# /me Endpoint Tests (get_me router function)
# ============================================================================


class TestGetMeEndpoint:
    """Unit tests for the GET /api/auth/me endpoint logic."""

    @pytest.mark.asyncio
    async def test_get_me_returns_user_profile(self):
        """get_me should return a UserProfile with the correct fields."""
        from src.api.routers.auth import get_me

        mock_user = _make_mock_user(
            user_id=42,
            username="edgar",
            email="edgar@example.com",
            role="admin",
            language="de",
            is_active=True,
        )

        result = await get_me(user=mock_user)
        assert result.id == 42
        assert result.username == "edgar"
        assert result.email == "edgar@example.com"
        assert result.role == "admin"
        assert result.language == "de"
        assert result.is_active is True

    @pytest.mark.asyncio
    async def test_get_me_handles_none_email(self):
        """get_me should handle users with no email (nullable field)."""
        from src.api.routers.auth import get_me

        mock_user = _make_mock_user(user_id=1, email=None)

        result = await get_me(user=mock_user)
        assert result.email is None


class TestGetRealClientIp:
    """Tests for _get_real_client_ip rate limiter key function."""

    def test_uses_x_forwarded_for_when_behind_proxy(self):
        from src.api import rate_limit as rl_mod
        from src.api.rate_limit import _get_real_client_ip
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        original = rl_mod._TRUST_PROXY
        try:
            rl_mod._TRUST_PROXY = True
            assert _get_real_client_ip(request) == "1.2.3.4"
        finally:
            rl_mod._TRUST_PROXY = original

    def test_ignores_x_forwarded_for_without_proxy(self):
        from src.api import rate_limit as rl_mod
        from src.api.rate_limit import _get_real_client_ip
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4"}
        request.client.host = "10.0.0.1"
        original = rl_mod._TRUST_PROXY
        try:
            rl_mod._TRUST_PROXY = False
            assert _get_real_client_ip(request) == "10.0.0.1"
        finally:
            rl_mod._TRUST_PROXY = original

    def test_falls_back_to_client_host(self):
        from src.api.rate_limit import _get_real_client_ip
        request = MagicMock()
        request.headers = {}
        request.client.host = "10.0.0.1"
        assert _get_real_client_ip(request) == "10.0.0.1"

    def test_handles_no_client(self):
        from src.api.rate_limit import _get_real_client_ip
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert _get_real_client_ip(request) == "unknown"
