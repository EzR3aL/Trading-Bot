"""Tests for src/utils/encryption.py - Fernet encryption utilities."""

import os

import pytest
from cryptography.fernet import Fernet

import src.utils.encryption as encryption_module
from src.utils.encryption import decrypt_value, encrypt_value, mask_value

# Generate a stable Fernet key for the entire test module
_TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def reset_fernet_singleton():
    """Reset the module-level _fernet singleton and set a test encryption key
    before every test so we never trigger the auto-generate-to-.env logic."""
    encryption_module._fernet = None
    os.environ["ENCRYPTION_KEY"] = _TEST_KEY
    yield
    # Clean up after the test
    encryption_module._fernet = None


class TestEncryptDecrypt:
    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting then decrypting should return the original plaintext."""
        plaintext = "super-secret-api-key-12345"
        ciphertext = encrypt_value(plaintext)
        assert ciphertext != plaintext
        assert decrypt_value(ciphertext) == plaintext

    def test_encrypt_empty_string(self):
        """Encrypting an empty string should return an empty string."""
        assert encrypt_value("") == ""

    def test_decrypt_empty_string(self):
        """Decrypting an empty string should return an empty string."""
        assert decrypt_value("") == ""

    def test_encrypt_produces_different_ciphertexts(self):
        """Two encryptions of the same plaintext should differ (Fernet uses random IV)."""
        plaintext = "same-value"
        ct1 = encrypt_value(plaintext)
        ct2 = encrypt_value(plaintext)
        assert ct1 != ct2
        # Both should still decrypt to the same value
        assert decrypt_value(ct1) == plaintext
        assert decrypt_value(ct2) == plaintext


class TestMaskValue:
    def test_mask_value_long_string(self):
        """A long value should be masked with asterisks, showing last 4 chars."""
        result = mask_value("abcdefghijklmnop")
        assert result.endswith("mnop")
        assert result.startswith("*")
        assert result == "************mnop"

    def test_mask_value_short_string(self):
        """A string shorter than or equal to visible_chars returns '****'."""
        assert mask_value("ab") == "****"
        assert mask_value("abcd") == "****"
        assert mask_value("") == "****"
