"""Tests for src/auth/jwt_handler.py - JWT token creation and validation."""

import base64
import json
from datetime import timedelta

import jwt
import pytest

from src.auth.jwt_handler import (
    ALGORITHM_HS256,
    ALGORITHM_RS256,
    REFRESH_TOKEN_EXPIRE_DAYS,
    _get_hs_secret,
    create_access_token,
    create_refresh_token,
    decode_token,
)


@pytest.fixture(scope="module")
def rs_keypair():
    """Generate an RSA key-pair once per module for dual-validate tests."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


class TestCreateAccessTokenHS256:
    """HS256 is the test-environment default (JWT_SECRET_KEY set, no RS keys)."""

    def test_create_access_token(self):
        token = create_access_token({"sub": "42"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_access_token_has_expiry(self):
        token = create_access_token({"sub": "42"})
        payload = jwt.decode(token, _get_hs_secret(), algorithms=[ALGORITHM_HS256])
        assert "exp" in payload

    def test_token_contains_correct_type(self):
        token = create_access_token({"sub": "42"})
        payload = jwt.decode(token, _get_hs_secret(), algorithms=[ALGORITHM_HS256])
        assert payload["type"] == "access"


class TestCreateRefreshToken:
    def test_create_refresh_token(self):
        token = create_refresh_token({"sub": "42"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_refresh_token_contains_correct_type(self):
        token = create_refresh_token({"sub": "42"})
        payload = jwt.decode(token, _get_hs_secret(), algorithms=[ALGORITHM_HS256])
        assert payload["type"] == "refresh"

    def test_refresh_token_expiry_is_14_days(self):
        """SEC-003: 90-day expiry reduced to 14 days."""
        assert REFRESH_TOKEN_EXPIRE_DAYS == 14


class TestDecodeToken:
    def test_decode_valid_token(self):
        token = create_access_token({"sub": "99"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "99"

    def test_decode_expired_token(self):
        token = create_access_token({"sub": "99"}, expires_delta=timedelta(seconds=-1))
        assert decode_token(token) is None

    def test_decode_invalid_token(self):
        assert decode_token("not.a.valid.jwt.token") is None

    def test_expected_type_mismatch_rejected(self):
        refresh = create_refresh_token({"sub": "99"})
        assert decode_token(refresh, expected_type="access") is None
        assert decode_token(refresh, expected_type="refresh") is not None


class TestDualValidate:
    """SEC-001: RS256 is preferred, but HS256-signed tokens must remain valid
    during the 14-day rollover window when both env vars are configured."""

    def test_hs256_legacy_token_still_accepted(self, monkeypatch, rs_keypair):
        priv_pem, pub_pem = rs_keypair
        monkeypatch.setenv("JWT_PRIVATE_KEY", priv_pem)
        monkeypatch.setenv("JWT_PUBLIC_KEY", pub_pem)

        hs_secret = _get_hs_secret()
        if not hs_secret:
            pytest.skip("HS256 secret not configured in test env")

        legacy_token = jwt.encode(
            {"sub": "7", "type": "access", "exp": 9999999999},
            hs_secret,
            algorithm=ALGORITHM_HS256,
        )
        payload = decode_token(legacy_token, expected_type="access")
        assert payload is not None
        assert payload["sub"] == "7"

    def test_new_tokens_signed_with_rs256_when_configured(self, monkeypatch, rs_keypair):
        priv_pem, pub_pem = rs_keypair
        monkeypatch.setenv("JWT_PRIVATE_KEY", priv_pem)
        monkeypatch.setenv("JWT_PUBLIC_KEY", pub_pem)

        token = create_access_token({"sub": "7"})
        header_b64 = token.split(".")[0]
        padding = "=" * (-len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_b64 + padding))
        assert header["alg"] == ALGORITHM_RS256
