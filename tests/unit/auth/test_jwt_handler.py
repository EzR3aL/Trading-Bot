"""Tests for src/auth/jwt_handler.py - JWT token creation and validation."""

from datetime import timedelta

import jwt

from src.auth.jwt_handler import (
    ALGORITHM,
    _get_secret_key,
    create_access_token,
    create_refresh_token,
    decode_token,
)


class TestCreateAccessToken:
    def test_create_access_token(self):
        """create_access_token should return a non-empty JWT string."""
        token = create_access_token({"sub": "42"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_access_token_has_expiry(self):
        """The decoded access token payload must contain an 'exp' claim."""
        token = create_access_token({"sub": "42"})
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_token_contains_correct_type(self):
        """Access tokens must have type='access' in the payload."""
        token = create_access_token({"sub": "42"})
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        assert payload["type"] == "access"


class TestCreateRefreshToken:
    def test_create_refresh_token(self):
        """create_refresh_token should return a non-empty JWT string."""
        token = create_refresh_token({"sub": "42"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_refresh_token_contains_correct_type(self):
        """Refresh tokens must have type='refresh' in the payload."""
        token = create_refresh_token({"sub": "42"})
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
        assert payload["type"] == "refresh"


class TestDecodeToken:
    def test_decode_valid_token(self):
        """decode_token returns the payload dict for a valid token."""
        token = create_access_token({"sub": "99"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "99"

    def test_decode_expired_token(self):
        """decode_token returns None for an expired token."""
        token = create_access_token(
            {"sub": "99"}, expires_delta=timedelta(seconds=-1)
        )
        result = decode_token(token)
        assert result is None

    def test_decode_invalid_token(self):
        """decode_token returns None for a garbage string."""
        result = decode_token("not.a.valid.jwt.token")
        assert result is None
