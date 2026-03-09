"""Startup configuration validation.

Validates critical environment variables and settings on application startup.
Warns on issues, raises on critical misconfigurations.
"""

import os

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ConfigValidationError(Exception):
    """Raised when configuration is invalid."""
    pass


def validate_startup_config():
    """Validate critical configuration at startup. Warns on issues, raises on critical."""
    warnings = []
    errors = []

    # JWT secret must be set in production
    environment = os.getenv("ENVIRONMENT", "development").lower()
    jwt_secret = os.getenv("JWT_SECRET_KEY", "")
    if environment == "production" and (not jwt_secret or len(jwt_secret) < 32):
        errors.append("JWT_SECRET_KEY must be set and at least 32 characters in production")

    # Encryption key should be set in production
    if environment == "production" and not os.getenv("ENCRYPTION_KEY"):
        warnings.append("ENCRYPTION_KEY not set in production; auto-generated key will not persist across restarts")

    # Database URL must be configured
    db_url = os.getenv("DATABASE_URL", "")
    if environment == "production" and "sqlite" in db_url.lower():
        warnings.append("Using SQLite in production is not recommended; consider PostgreSQL")

    # Reject default/weak database password in production
    _WEAK_PASSWORDS = {"tradingbot_dev", "changeme", "password", "postgres", "admin", ""}
    pg_password = os.getenv("POSTGRES_PASSWORD", "")
    if environment == "production" and pg_password in _WEAK_PASSWORDS:
        errors.append(
            "POSTGRES_PASSWORD is a default/weak value. "
            "Set a strong random password in .env for production"
        )

    # Grafana admin password
    gf_password = os.getenv("GF_ADMIN_PASSWORD", "")
    if gf_password and gf_password in _WEAK_PASSWORDS:
        warnings.append(
            "GF_ADMIN_PASSWORD is a default/weak value. "
            "Set a strong random password for the Grafana dashboard"
        )

    # CORS origins in production
    if environment == "production" and not os.getenv("CORS_ORIGINS"):
        warnings.append("CORS_ORIGINS not set in production; API will reject cross-origin requests")

    for w in warnings:
        logger.warning("Config warning: %s", w)

    if errors:
        for e in errors:
            logger.error("Config error: %s", e)
        raise ConfigValidationError(f"{len(errors)} config error(s): {'; '.join(errors)}")

    logger.info("Configuration validation passed")
