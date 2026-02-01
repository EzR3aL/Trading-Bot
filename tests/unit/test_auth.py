"""
Unit tests for authentication module.

Tests JWT token handling and password hashing.
"""

import os
import time
import pytest
import secrets

# Set up test environment
import base64
os.environ["JWT_SECRET"] = secrets.token_urlsafe(64)
# Generate a proper 32-byte key encoded as base64
test_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["ENCRYPTION_MASTER_KEY"] = test_key

from src.auth.jwt_handler import (
    JWTHandler,
    TokenPair,
    TokenPayload,
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
)
from src.auth.password import (
    PasswordHandler,
    hash_password,
    verify_password,
)


class TestJWTHandler:
    """Tests for JWT token handling."""

    @pytest.fixture
    def handler(self):
        """Create JWT handler with test secret."""
        return JWTHandler(secret_key=secrets.token_urlsafe(64))

    def test_create_token_pair(self, handler):
        """Test creating access and refresh token pair."""
        tokens = handler.create_token_pair(
            user_id=1,
            username="testuser",
            is_admin=False
        )

        assert isinstance(tokens, TokenPair)
        assert tokens.access_token
        assert tokens.refresh_token
        assert tokens.token_type == "bearer"
        assert tokens.expires_in > 0

    def test_verify_access_token(self, handler):
        """Test verifying a valid access token."""
        tokens = handler.create_token_pair(
            user_id=42,
            username="john",
            is_admin=True
        )

        payload = handler.verify_access_token(tokens.access_token)

        assert isinstance(payload, TokenPayload)
        assert payload.user_id == 42
        assert payload.username == "john"
        assert payload.is_admin is True
        assert payload.token_type == "access"

    def test_verify_refresh_token(self, handler):
        """Test verifying a valid refresh token."""
        tokens = handler.create_token_pair(
            user_id=1,
            username="test",
            is_admin=False
        )

        payload = handler.verify_refresh_token(tokens.refresh_token)

        assert payload.user_id == 1
        assert payload.token_type == "refresh"

    def test_access_token_as_refresh_fails(self, handler):
        """Test that access token cannot be used as refresh token."""
        tokens = handler.create_token_pair(user_id=1, username="test")

        with pytest.raises(TokenInvalidError):
            handler.verify_refresh_token(tokens.access_token)

    def test_refresh_token_as_access_fails(self, handler):
        """Test that refresh token cannot be used as access token."""
        tokens = handler.create_token_pair(user_id=1, username="test")

        with pytest.raises(TokenInvalidError):
            handler.verify_access_token(tokens.refresh_token)

    def test_expired_token(self):
        """Test that expired tokens are rejected."""
        handler = JWTHandler(
            secret_key=secrets.token_urlsafe(64),
            access_token_expire_minutes=0  # Immediate expiry
        )

        tokens = handler.create_token_pair(user_id=1, username="test")
        time.sleep(1)  # Wait for expiry

        with pytest.raises(TokenExpiredError):
            handler.verify_access_token(tokens.access_token)

    def test_invalid_token(self, handler):
        """Test that invalid tokens are rejected."""
        with pytest.raises(TokenInvalidError):
            handler.verify_access_token("invalid.token.here")

    def test_tampered_token(self, handler):
        """Test that tampered tokens are rejected."""
        tokens = handler.create_token_pair(user_id=1, username="test")

        # Tamper with the token
        parts = tokens.access_token.split(".")
        tampered = parts[0] + "." + parts[1] + ".tamperedsignature"

        with pytest.raises(TokenInvalidError):
            handler.verify_access_token(tampered)

    def test_wrong_secret_fails(self):
        """Test that tokens from different secrets fail."""
        handler1 = JWTHandler(secret_key=secrets.token_urlsafe(64))
        handler2 = JWTHandler(secret_key=secrets.token_urlsafe(64))

        tokens = handler1.create_token_pair(user_id=1, username="test")

        with pytest.raises(TokenInvalidError):
            handler2.verify_access_token(tokens.access_token)

    def test_refresh_access_token(self, handler):
        """Test refreshing access token."""
        original = handler.create_token_pair(user_id=1, username="test", is_admin=True)
        new_tokens = handler.refresh_access_token(original.refresh_token)

        assert new_tokens.access_token != original.access_token
        assert new_tokens.refresh_token != original.refresh_token

        payload = handler.verify_access_token(new_tokens.access_token)
        assert payload.user_id == 1
        assert payload.is_admin is True

    def test_unique_jti(self, handler):
        """Test that each token has a unique JTI."""
        tokens1 = handler.create_token_pair(user_id=1, username="test")
        tokens2 = handler.create_token_pair(user_id=1, username="test")

        payload1 = handler.verify_access_token(tokens1.access_token)
        payload2 = handler.verify_access_token(tokens2.access_token)

        assert payload1.jti != payload2.jti

    def test_hash_token(self, handler):
        """Test token hashing for storage."""
        tokens = handler.create_token_pair(user_id=1, username="test")

        hash1 = handler.hash_token(tokens.access_token)
        hash2 = handler.hash_token(tokens.access_token)

        # Same token = same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

        # Different token = different hash
        hash3 = handler.hash_token(tokens.refresh_token)
        assert hash1 != hash3

    def test_get_token_jti(self, handler):
        """Test extracting JTI from token."""
        tokens = handler.create_token_pair(user_id=1, username="test")

        jti = handler.get_token_jti(tokens.access_token)
        assert jti is not None

        # Invalid token returns None
        assert handler.get_token_jti("invalid") is None

    def test_short_secret_raises(self):
        """Test that short secret raises error."""
        with pytest.raises(ValueError):
            JWTHandler(secret_key="short")

    def test_missing_secret_raises(self, monkeypatch):
        """Test that missing secret raises error."""
        monkeypatch.delenv("JWT_SECRET", raising=False)
        with pytest.raises(ValueError):
            JWTHandler()


class TestPasswordHandler:
    """Tests for password hashing."""

    @pytest.fixture
    def handler(self):
        """Create password handler with low work factor for testing."""
        return PasswordHandler(work_factor=4)  # Fast for tests

    def test_hash_password(self, handler):
        """Test password hashing."""
        hashed = handler.hash("mypassword")

        assert hashed
        assert hashed != "mypassword"
        assert hashed.startswith("$2b$")

    def test_verify_correct_password(self, handler):
        """Test verifying correct password."""
        hashed = handler.hash("mypassword")
        assert handler.verify("mypassword", hashed) is True

    def test_verify_wrong_password(self, handler):
        """Test verifying wrong password."""
        hashed = handler.hash("mypassword")
        assert handler.verify("wrongpassword", hashed) is False

    def test_verify_empty_password(self, handler):
        """Test verifying empty password returns False."""
        hashed = handler.hash("mypassword")
        assert handler.verify("", hashed) is False

    def test_verify_empty_hash(self, handler):
        """Test verifying against empty hash returns False."""
        assert handler.verify("password", "") is False

    def test_hash_empty_password_raises(self, handler):
        """Test hashing empty password raises error."""
        with pytest.raises(ValueError):
            handler.hash("")

    def test_hash_unique_salts(self, handler):
        """Test that same password gets different hashes (different salts)."""
        hash1 = handler.hash("mypassword")
        hash2 = handler.hash("mypassword")
        assert hash1 != hash2

    def test_unicode_password(self, handler):
        """Test hashing unicode passwords."""
        hashed = handler.hash("密码🔐Пароль")
        assert handler.verify("密码🔐Пароль", hashed) is True

    def test_long_password(self, handler):
        """Test hashing long passwords."""
        # bcrypt has a 72-byte limit, but should still work
        long_pass = "x" * 100
        hashed = handler.hash(long_pass)
        assert handler.verify(long_pass, hashed) is True

    def test_needs_rehash_same_factor(self, handler):
        """Test needs_rehash with same work factor."""
        hashed = handler.hash("password")
        assert handler.needs_rehash(hashed) is False

    def test_needs_rehash_higher_factor(self):
        """Test needs_rehash with higher work factor."""
        low_handler = PasswordHandler(work_factor=4)
        high_handler = PasswordHandler(work_factor=6)

        hashed = low_handler.hash("password")
        assert high_handler.needs_rehash(hashed) is True

    def test_invalid_work_factor_low(self):
        """Test that work factor below 4 raises error."""
        with pytest.raises(ValueError):
            PasswordHandler(work_factor=3)

    def test_invalid_work_factor_high(self):
        """Test that work factor above 31 raises error."""
        with pytest.raises(ValueError):
            PasswordHandler(work_factor=32)


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_hash_password_function(self):
        """Test hash_password convenience function."""
        hashed = hash_password("test", work_factor=4)
        assert hashed.startswith("$2b$")

    def test_verify_password_function(self):
        """Test verify_password convenience function."""
        hashed = hash_password("test", work_factor=4)
        assert verify_password("test", hashed) is True
        assert verify_password("wrong", hashed) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
