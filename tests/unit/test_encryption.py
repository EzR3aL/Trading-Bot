"""
Unit tests for credential encryption module.

Tests AES-256-GCM encryption/decryption functionality.
"""

import os
import pytest
import base64
import secrets

# Set up test environment before importing modules
TEST_KEY = base64.b64encode(secrets.token_bytes(32)).decode()
os.environ["ENCRYPTION_MASTER_KEY"] = TEST_KEY

from src.security.encryption import (
    CredentialEncryption,
    EncryptionError,
    generate_master_key,
    KEY_LENGTH,
    NONCE_LENGTH,
)


class TestCredentialEncryption:
    """Tests for CredentialEncryption class."""

    @pytest.fixture
    def encryption(self):
        """Create encryption instance with test key."""
        key = secrets.token_bytes(32)
        return CredentialEncryption(master_key=key)

    def test_encrypt_decrypt_roundtrip(self, encryption):
        """Test that encrypt/decrypt returns original value."""
        original = "my_secret_api_key_12345"
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_produces_different_output(self, encryption):
        """Test that encrypting same value twice produces different ciphertext."""
        original = "same_value"
        encrypted1 = encryption.encrypt(original)
        encrypted2 = encryption.encrypt(original)
        # Due to random nonce, ciphertexts should differ
        assert encrypted1 != encrypted2

    def test_decrypt_both_ciphertexts(self, encryption):
        """Test that both different ciphertexts decrypt to same value."""
        original = "same_value"
        encrypted1 = encryption.encrypt(original)
        encrypted2 = encryption.encrypt(original)
        assert encryption.decrypt(encrypted1) == original
        assert encryption.decrypt(encrypted2) == original

    def test_encrypt_empty_string_raises(self, encryption):
        """Test that encrypting empty string raises error."""
        with pytest.raises(EncryptionError):
            encryption.encrypt("")

    def test_decrypt_empty_string_raises(self, encryption):
        """Test that decrypting empty string raises error."""
        with pytest.raises(EncryptionError):
            encryption.decrypt("")

    def test_decrypt_invalid_base64_raises(self, encryption):
        """Test that decrypting invalid base64 raises error."""
        with pytest.raises(EncryptionError):
            encryption.decrypt("not_valid_base64!!!")

    def test_decrypt_too_short_raises(self, encryption):
        """Test that decrypting too-short ciphertext raises error."""
        # Create base64 that's too short (less than nonce + tag)
        short_data = base64.b64encode(b"short").decode()
        with pytest.raises(EncryptionError):
            encryption.decrypt(short_data)

    def test_decrypt_tampered_data_raises(self, encryption):
        """Test that decrypting tampered ciphertext raises error."""
        original = "sensitive_data"
        encrypted = encryption.encrypt(original)

        # Tamper with the ciphertext
        data = base64.b64decode(encrypted)
        # Flip a bit in the middle
        tampered = data[:20] + bytes([data[20] ^ 0xFF]) + data[21:]
        tampered_b64 = base64.b64encode(tampered).decode()

        with pytest.raises(EncryptionError):
            encryption.decrypt(tampered_b64)

    def test_wrong_key_fails_decryption(self):
        """Test that decrypting with wrong key fails."""
        key1 = secrets.token_bytes(32)
        key2 = secrets.token_bytes(32)

        enc1 = CredentialEncryption(master_key=key1)
        enc2 = CredentialEncryption(master_key=key2)

        encrypted = enc1.encrypt("secret")

        with pytest.raises(EncryptionError):
            enc2.decrypt(encrypted)

    def test_encrypt_unicode(self, encryption):
        """Test encryption of unicode strings."""
        original = "密码🔐Пароль"
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_long_string(self, encryption):
        """Test encryption of long strings."""
        original = "x" * 10000  # 10KB string
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_special_characters(self, encryption):
        """Test encryption of strings with special characters."""
        original = "key=abc123&secret=xyz!@#$%^&*()"
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == original


class TestKeyGeneration:
    """Tests for key generation utilities."""

    def test_generate_master_key_length(self):
        """Test that generated key has correct length."""
        key_b64 = generate_master_key()
        key = base64.b64decode(key_b64)
        assert len(key) == KEY_LENGTH

    def test_generate_master_key_unique(self):
        """Test that generated keys are unique."""
        keys = [generate_master_key() for _ in range(10)]
        assert len(set(keys)) == 10  # All unique

    def test_is_valid_key_correct(self):
        """Test validation of correct key."""
        key = generate_master_key()
        assert CredentialEncryption.is_valid_key(key) is True

    def test_is_valid_key_too_short(self):
        """Test validation of too-short key."""
        key = base64.b64encode(b"short").decode()
        assert CredentialEncryption.is_valid_key(key) is False

    def test_is_valid_key_invalid_base64(self):
        """Test validation of invalid base64."""
        assert CredentialEncryption.is_valid_key("not_base64!!!") is False


class TestEnvironmentKey:
    """Tests for loading key from environment."""

    def test_missing_env_key_raises(self, monkeypatch):
        """Test that missing env var raises clear error."""
        monkeypatch.delenv("ENCRYPTION_MASTER_KEY", raising=False)
        with pytest.raises(ValueError) as exc_info:
            CredentialEncryption()
        assert "ENCRYPTION_MASTER_KEY" in str(exc_info.value)

    def test_invalid_env_key_raises(self, monkeypatch):
        """Test that invalid env var format raises error."""
        monkeypatch.setenv("ENCRYPTION_MASTER_KEY", "invalid!!!")
        with pytest.raises(ValueError):
            CredentialEncryption()

    def test_wrong_length_env_key_raises(self, monkeypatch):
        """Test that wrong-length key raises error."""
        short_key = base64.b64encode(b"short").decode()
        monkeypatch.setenv("ENCRYPTION_MASTER_KEY", short_key)
        with pytest.raises(ValueError) as exc_info:
            CredentialEncryption()
        assert "256 bits" in str(exc_info.value)

    def test_valid_env_key_works(self, monkeypatch):
        """Test that valid env key works."""
        valid_key = generate_master_key()
        monkeypatch.setenv("ENCRYPTION_MASTER_KEY", valid_key)
        enc = CredentialEncryption()
        assert enc.encrypt("test") is not None


class TestSecurityProperties:
    """Tests for security properties of the encryption."""

    @pytest.fixture
    def encryption(self):
        key = secrets.token_bytes(32)
        return CredentialEncryption(master_key=key)

    def test_ciphertext_length_reasonable(self, encryption):
        """Test that ciphertext length is reasonable (not leaking info)."""
        # Different length plaintexts should have different length ciphertexts
        # but the overhead should be constant (nonce + tag)
        short = encryption.encrypt("a")
        medium = encryption.encrypt("a" * 100)
        long = encryption.encrypt("a" * 1000)

        short_len = len(base64.b64decode(short))
        medium_len = len(base64.b64decode(medium))
        long_len = len(base64.b64decode(long))

        # Overhead should be nonce (12) + tag (16) = 28 bytes
        expected_overhead = NONCE_LENGTH + 16

        assert short_len == 1 + expected_overhead
        assert medium_len == 100 + expected_overhead
        assert long_len == 1000 + expected_overhead

    def test_nonce_is_random(self, encryption):
        """Test that nonces are random (not sequential)."""
        ciphertexts = [encryption.encrypt("same") for _ in range(100)]
        nonces = [base64.b64decode(ct)[:NONCE_LENGTH] for ct in ciphertexts]

        # All nonces should be unique
        assert len(set(nonces)) == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
