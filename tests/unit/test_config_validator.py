"""Tests for startup configuration validator."""

import os
import pytest
from unittest.mock import patch

from src.utils.config_validator import validate_startup_config, ConfigValidationError


def test_valid_config_passes_in_development():
    """Development mode should pass with default settings."""
    with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=False):
        # Should not raise
        validate_startup_config()


def test_production_without_jwt_secret_raises():
    """Production without a proper JWT_SECRET_KEY should raise."""
    env = {
        "ENVIRONMENT": "production",
        "JWT_SECRET_KEY": "short",  # Too short
        "POSTGRES_PASSWORD": "StrongTestPass123!",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ConfigValidationError, match="JWT_SECRET_KEY"):
            validate_startup_config()


def test_production_with_valid_jwt_secret_passes():
    """Production with a valid JWT secret should pass."""
    env = {
        "ENVIRONMENT": "production",
        "JWT_SECRET_KEY": "a" * 64,
        "ENCRYPTION_KEY": "some-key",
        "CORS_ORIGINS": "https://example.com",
        "DATABASE_URL": "postgresql+asyncpg://localhost/db",
        "POSTGRES_PASSWORD": "StrongTestPass123!",
    }
    with patch.dict(os.environ, env, clear=False):
        validate_startup_config()


def test_production_sqlite_warning(caplog):
    """Production with SQLite should warn but not raise."""
    env = {
        "ENVIRONMENT": "production",
        "JWT_SECRET_KEY": "a" * 64,
        "ENCRYPTION_KEY": "some-key",
        "DATABASE_URL": "sqlite+aiosqlite:///test.db",
        "CORS_ORIGINS": "https://example.com",
        "POSTGRES_PASSWORD": "StrongTestPass123!",
    }
    with patch.dict(os.environ, env, clear=False):
        validate_startup_config()
    assert "SQLite in production" in caplog.text


def test_production_missing_cors_warning(caplog):
    """Production without CORS_ORIGINS should warn but not raise."""
    env = {
        "ENVIRONMENT": "production",
        "JWT_SECRET_KEY": "a" * 64,
        "ENCRYPTION_KEY": "some-key",
        "DATABASE_URL": "postgresql+asyncpg://localhost/db",
        "POSTGRES_PASSWORD": "StrongTestPass123!",
    }
    # Remove CORS_ORIGINS if present
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("CORS_ORIGINS", None)
        validate_startup_config()
    assert "CORS_ORIGINS" in caplog.text


def test_production_missing_encryption_key_warning(caplog):
    """Production without ENCRYPTION_KEY should warn but not raise."""
    env = {
        "ENVIRONMENT": "production",
        "JWT_SECRET_KEY": "a" * 64,
        "DATABASE_URL": "postgresql+asyncpg://localhost/db",
        "CORS_ORIGINS": "https://example.com",
        "POSTGRES_PASSWORD": "StrongTestPass123!",
    }
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("ENCRYPTION_KEY", None)
        validate_startup_config()
    assert "ENCRYPTION_KEY" in caplog.text
