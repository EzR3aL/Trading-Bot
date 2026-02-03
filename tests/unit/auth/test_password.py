"""Tests for src/auth/password.py - bcrypt password hashing and verification."""

from src.auth.password import hash_password, verify_password


class TestHashPassword:
    def test_hash_password_returns_bcrypt_hash(self):
        """hash_password should return a string starting with the bcrypt prefix."""
        hashed = hash_password("my_secret_password")
        assert isinstance(hashed, str)
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_hash_password_different_each_time(self):
        """Two hashes of the same password must differ due to random salting."""
        password = "same_password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        assert hash1 != hash2


class TestVerifyPassword:
    def test_verify_password_correct(self):
        """verify_password returns True for the correct plaintext."""
        password = "correct_horse_battery_staple"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password returns False for a wrong plaintext."""
        hashed = hash_password("real_password")
        assert verify_password("wrong_password", hashed) is False
