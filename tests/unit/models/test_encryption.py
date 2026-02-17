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


class TestKeyRotation:
    """Tests for encryption key rotation support."""

    def test_decrypt_with_previous_key_fallback(self):
        """Values encrypted with old key can be decrypted via ENCRYPTION_KEY_PREVIOUS."""
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        # Encrypt with old key
        os.environ["ENCRYPTION_KEY"] = old_key
        encryption_module._fernet = None
        encryption_module._fernet_previous = None
        ciphertext = encrypt_value("my-secret")

        # Switch to new key, set old as previous
        os.environ["ENCRYPTION_KEY"] = new_key
        os.environ["ENCRYPTION_KEY_PREVIOUS"] = old_key
        encryption_module._fernet = None
        encryption_module._fernet_previous = None

        # Should decrypt via fallback to previous key
        assert decrypt_value(ciphertext) == "my-secret"

        # Cleanup
        os.environ.pop("ENCRYPTION_KEY_PREVIOUS", None)
        encryption_module._fernet_previous = None

    def test_decrypt_fails_with_wrong_keys(self):
        """Decryption fails when neither current nor previous key matches."""
        old_key = Fernet.generate_key().decode()
        wrong_key = Fernet.generate_key().decode()

        # Encrypt with old key
        os.environ["ENCRYPTION_KEY"] = old_key
        encryption_module._fernet = None
        encryption_module._fernet_previous = None
        ciphertext = encrypt_value("my-secret")

        # Switch to completely different key, no previous set
        os.environ["ENCRYPTION_KEY"] = wrong_key
        os.environ.pop("ENCRYPTION_KEY_PREVIOUS", None)
        encryption_module._fernet = None
        encryption_module._fernet_previous = None

        with pytest.raises(ValueError, match="Failed to decrypt"):
            decrypt_value(ciphertext)

    def test_decrypt_fails_with_both_current_and_previous_keys(self):
        """Decryption fails when both current AND previous key are wrong."""
        original_key = Fernet.generate_key().decode()
        wrong_current = Fernet.generate_key().decode()
        wrong_previous = Fernet.generate_key().decode()

        # Encrypt with original key
        os.environ["ENCRYPTION_KEY"] = original_key
        encryption_module._fernet = None
        encryption_module._fernet_previous = None
        ciphertext = encrypt_value("my-secret")

        # Set both keys to wrong values
        os.environ["ENCRYPTION_KEY"] = wrong_current
        os.environ["ENCRYPTION_KEY_PREVIOUS"] = wrong_previous
        encryption_module._fernet = None
        encryption_module._fernet_previous = None

        with pytest.raises(ValueError, match="Failed to decrypt"):
            decrypt_value(ciphertext)

        # Cleanup
        os.environ.pop("ENCRYPTION_KEY_PREVIOUS", None)
        encryption_module._fernet_previous = None

    def test_encrypt_value_has_version_prefix(self):
        """Encrypted values start with version prefix v1:."""
        ciphertext = encrypt_value("hello")
        assert ciphertext.startswith("v1:")

    def test_decrypt_legacy_value_without_prefix(self):
        """Legacy ciphertext without version prefix still decrypts."""
        # Encrypt directly with Fernet (no prefix)
        raw_ct = Fernet(_TEST_KEY.encode()).encrypt(b"legacy-secret").decode()
        assert decrypt_value(raw_ct) == "legacy-secret"


class TestKeyValidation:
    """Tests for encryption key validation."""

    def test_invalid_fernet_key_format_rejected(self):
        """A key that is long enough but not valid Fernet base64 is rejected."""
        os.environ["ENCRYPTION_KEY"] = "x" * 44  # 44 chars but not valid base64
        encryption_module._fernet = None
        with pytest.raises(ValueError, match="not a valid Fernet key"):
            from src.utils.encryption import _get_or_create_key
            _get_or_create_key()


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
