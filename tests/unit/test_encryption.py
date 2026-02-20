"""Tests for the encryption utility."""

import os
from unittest.mock import patch, MagicMock

import pytest
from cryptography.fernet import Fernet

import src.utils.encryption as enc_module
from src.utils.encryption import encrypt_value, decrypt_value, mask_value


@pytest.fixture(autouse=True)
def reset_fernet():
    """Reset the module-level fernet singleton between tests."""
    enc_module._fernet = None
    yield
    enc_module._fernet = None


@pytest.fixture
def fixed_key():
    """Provide a fixed Fernet key for tests."""
    return Fernet.generate_key()


class TestEncryptDecrypt:
    """Tests for encrypt_value and decrypt_value."""

    def test_roundtrip(self, fixed_key):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": fixed_key.decode()}):
            encrypted = encrypt_value("my-secret-key")
            assert encrypted != "my-secret-key"
            assert decrypt_value(encrypted) == "my-secret-key"

    def test_encrypt_empty_returns_empty(self, fixed_key):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": fixed_key.decode()}):
            assert encrypt_value("") == ""

    def test_decrypt_empty_returns_empty(self, fixed_key):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": fixed_key.decode()}):
            assert decrypt_value("") == ""

    def test_decrypt_invalid_ciphertext_raises(self, fixed_key):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": fixed_key.decode()}):
            with pytest.raises(ValueError, match="Failed to decrypt"):
                decrypt_value("not-valid-ciphertext")

    def test_decrypt_wrong_key_raises(self, fixed_key):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": fixed_key.decode()}):
            encrypted = encrypt_value("secret")

        # Reset fernet and use a different key
        enc_module._fernet = None
        other_key = Fernet.generate_key()
        with patch.dict(os.environ, {"ENCRYPTION_KEY": other_key.decode()}):
            with pytest.raises(ValueError, match="Failed to decrypt"):
                decrypt_value(encrypted)


class TestGetOrCreateKey:
    """Tests for _get_or_create_key."""

    def test_returns_env_key(self, fixed_key):
        with patch.dict(os.environ, {"ENCRYPTION_KEY": fixed_key.decode()}):
            result = enc_module._get_or_create_key()
            assert result == fixed_key

    def test_production_without_key_raises(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}, clear=False):
            env = os.environ.copy()
            env.pop("ENCRYPTION_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(RuntimeError, match="FATAL"):
                    enc_module._get_or_create_key()

    def test_dev_auto_generates_key_with_existing_env(self):
        """In dev mode without ENCRYPTION_KEY, an ephemeral key is auto-generated in memory."""
        env = os.environ.copy()
        env.pop("ENCRYPTION_KEY", None)
        env["ENVIRONMENT"] = "development"

        with patch.dict(os.environ, env, clear=True):
            result = enc_module._get_or_create_key()

        assert len(result) > 0
        assert os.environ.get("ENCRYPTION_KEY") is not None


class TestMaskValue:
    """Tests for mask_value."""

    def test_masks_long_value(self):
        assert mask_value("sk-1234567890", 4) == "*********7890"

    def test_masks_short_value(self):
        assert mask_value("abc", 4) == "****"

    def test_masks_empty_value(self):
        assert mask_value("", 4) == "****"

    def test_masks_exact_length(self):
        assert mask_value("abcd", 4) == "****"

    def test_masks_with_custom_visible(self):
        assert mask_value("mysecretvalue", 6) == "*******tvalue"

    def test_masks_none_returns_stars(self):
        assert mask_value(None, 4) == "****"
