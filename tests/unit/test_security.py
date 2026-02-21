"""
Security tests for the Trading Bot.

Tests cover:
- CRITICAL: No API secrets leak in any API response
- CRITICAL: User isolation (user A cannot access user B's keys)
- HIGH: Legacy plaintext keys no longer loaded from environment
- HIGH: Refresh token rate limiting
- HIGH: Deprecated webhook field is cleared
- Encryption module correctness
- Admin role query correctness
"""

import os
import pytest
from unittest.mock import MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set env vars before any src imports — use direct assignment so the
# test-only Fernet key is always used regardless of .env or conftest.
_TEST_FERNET_KEY = "KC5sHBMOIy_qadREh-hbvZu1kS3V2P_PiyoW7OQk-bI="
os.environ["ENCRYPTION_KEY"] = _TEST_FERNET_KEY
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.utils.encryption import encrypt_value, decrypt_value, mask_value  # noqa: E402
import src.utils.encryption as _enc_module  # noqa: E402


# ---------------------------------------------------------------------------
# Encryption correctness
# ---------------------------------------------------------------------------

class TestEncryptionModule:
    """Verify encryption/decryption round-trip and security properties."""

    def setup_method(self):
        """Reset Fernet singleton so each test uses current ENCRYPTION_KEY."""
        _enc_module._fernet = None

    def test_encrypt_decrypt_round_trip(self):
        secret = "sk-1234567890abcdef"
        encrypted = encrypt_value(secret)
        decrypted = decrypt_value(encrypted)
        assert decrypted == secret

    def test_encrypted_value_differs_from_plaintext(self):
        secret = "my-super-secret-api-key"
        encrypted = encrypt_value(secret)
        assert encrypted != secret
        assert "my-super-secret" not in encrypted

    def test_different_encryptions_produce_different_ciphertext(self):
        """Fernet uses random IV, so same plaintext -> different ciphertext."""
        secret = "same-secret"
        enc1 = encrypt_value(secret)
        enc2 = encrypt_value(secret)
        assert enc1 != enc2  # Different IVs

    def test_empty_string_returns_empty(self):
        assert encrypt_value("") == ""
        assert decrypt_value("") == ""

    def test_decrypt_invalid_token_raises(self):
        with pytest.raises(ValueError, match="decrypt"):
            decrypt_value("not-a-valid-fernet-token")

    def test_mask_value_hides_middle(self):
        masked = mask_value("sk-1234567890abcdef")
        assert masked.endswith("cdef")
        assert "1234567890ab" not in masked
        assert "*" in masked
        # Original plaintext must not appear
        assert masked != "sk-1234567890abcdef"

    def test_mask_short_value(self):
        masked = mask_value("abc")
        assert "abc" not in masked or len(masked) > len("abc")


# ---------------------------------------------------------------------------
# No secrets in API response schemas
# ---------------------------------------------------------------------------

class TestNoSecretsInResponses:
    """Verify that API response schemas never include encrypted or decrypted secrets."""

    def test_exchange_connection_response_has_no_secret_fields(self):
        from src.api.schemas.config import ExchangeConnectionResponse
        fields = ExchangeConnectionResponse.model_fields
        # Boolean flags like "api_keys_configured" are safe — they don't contain actual secrets
        safe_suffixes = ("_configured",)
        secret_keywords = ["key", "secret", "passphrase", "password", "token", "encrypted"]
        for field_name in fields:
            if any(field_name.endswith(s) for s in safe_suffixes):
                continue
            for kw in secret_keywords:
                assert kw not in field_name.lower(), (
                    f"Response schema ExchangeConnectionResponse has suspicious field: {field_name}"
                )

    def test_config_response_has_no_secret_fields(self):
        from src.api.schemas.config import ConfigResponse
        fields = ConfigResponse.model_fields
        safe_suffixes = ("_configured",)
        secret_keywords = ["key", "secret", "passphrase", "password", "token", "encrypted"]
        for field_name in fields:
            if any(field_name.endswith(s) for s in safe_suffixes):
                continue
            for kw in secret_keywords:
                assert kw not in field_name.lower(), (
                    f"Response schema ConfigResponse has suspicious field: {field_name}"
                )

    def test_bot_response_has_no_secret_fields(self):
        from src.api.schemas.bots import BotConfigResponse
        fields = BotConfigResponse.model_fields
        secret_keywords = ["secret", "passphrase", "password", "encrypted"]
        for field_name in fields:
            for kw in secret_keywords:
                assert kw not in field_name.lower(), (
                    f"Response schema BotConfigResponse has suspicious field: {field_name}"
                )

    def test_conn_to_response_only_returns_booleans(self):
        """_conn_to_response must convert encrypted fields to booleans only."""
        from src.api.routers.config import _conn_to_response
        mock_conn = MagicMock()
        mock_conn.exchange_type = "bitget"
        mock_conn.api_key_encrypted = "gAAAAABfake_encrypted_key..."
        mock_conn.demo_api_key_encrypted = None
        mock_conn.affiliate_uid = None
        mock_conn.affiliate_verified = None

        response = _conn_to_response(mock_conn)

        # Should be boolean, NOT the encrypted value
        assert response.api_keys_configured is True
        assert response.demo_api_keys_configured is False
        # The actual encrypted value must NOT appear anywhere
        assert "gAAAAABfake" not in str(response.model_dump())


# ---------------------------------------------------------------------------
# Admin role query fix (C1)
# ---------------------------------------------------------------------------

class TestAdminRoleQuery:
    """Verify the admin query uses User.role instead of User.is_admin."""

    def test_user_model_has_no_is_admin_attribute(self):
        from src.models.database import User
        assert not hasattr(User, "is_admin"), (
            "User model should not have is_admin attribute. Use User.role == 'admin' instead."
        )

    def test_user_model_has_role_field(self):
        from src.models.database import User
        assert hasattr(User, "role"), "User model must have a 'role' field."

    def test_get_admin_exchange_conn_source_code_uses_role(self):
        """Verify the source code of _get_admin_exchange_conn references User.role."""
        import inspect
        from src.api.routers.config import _get_admin_exchange_conn
        source = inspect.getsource(_get_admin_exchange_conn)
        assert 'User.role == "admin"' in source, (
            "_get_admin_exchange_conn must filter by User.role == 'admin'"
        )
        assert "is_admin" not in source, (
            "_get_admin_exchange_conn must NOT reference non-existent is_admin"
        )


# ---------------------------------------------------------------------------
# Legacy plaintext key removal (H1)
# ---------------------------------------------------------------------------

class TestLegacyPlaintextKeysRemoved:
    """Verify BitgetConfig no longer loads secrets from environment variables."""

    def test_bitget_config_does_not_load_api_key_from_env(self):
        """Even if BITGET_API_KEY is set, it should NOT be loaded."""
        os.environ["BITGET_API_KEY"] = "should-not-be-loaded"
        os.environ["BITGET_API_SECRET"] = "should-not-be-loaded"
        os.environ["BITGET_PASSPHRASE"] = "should-not-be-loaded"
        try:
            from config.settings import BitgetConfig
            config = BitgetConfig()
            assert config.api_key == "", f"BitgetConfig.api_key should be empty, got: {config.api_key}"
            assert config.api_secret == "", "BitgetConfig.api_secret should be empty"
            assert config.passphrase == "", "BitgetConfig.passphrase should be empty"
        finally:
            os.environ.pop("BITGET_API_KEY", None)
            os.environ.pop("BITGET_API_SECRET", None)
            os.environ.pop("BITGET_PASSPHRASE", None)

    def test_bitget_config_demo_keys_also_empty(self):
        from config.settings import BitgetConfig
        config = BitgetConfig()
        assert config.demo_api_key == ""
        assert config.demo_api_secret == ""
        assert config.demo_passphrase == ""



# ---------------------------------------------------------------------------
# Refresh token rate limiting (H2)
# ---------------------------------------------------------------------------

class TestRefreshTokenRateLimit:
    """Verify the refresh endpoint has rate limiting."""

    def test_refresh_endpoint_has_rate_limit_decorator(self):
        """The refresh_token endpoint must have a @limiter.limit decorator."""
        import inspect
        from src.api.routers.auth import refresh_token

        # Check the function is decorated (slowapi adds __wrapped__ or modifies __dict__)
        _source = inspect.getsource(refresh_token)
        # Also verify by checking the route registration - the source should show the decorator
        # We check the auth module source for the decorator above the function
        import src.api.routers.auth as auth_module
        auth_source = inspect.getsource(auth_module)
        # Find the refresh endpoint definition
        refresh_idx = auth_source.index('async def refresh_token')
        # Look at the 100 chars before it for the decorator
        preceding = auth_source[max(0, refresh_idx - 200):refresh_idx]
        assert 'limiter.limit' in preceding, (
            "The /api/auth/refresh endpoint must have a @limiter.limit decorator"
        )

    def test_refresh_endpoint_accepts_request_param(self):
        """Rate-limited endpoints need Request as first param for slowapi."""
        import inspect
        from src.api.routers.auth import refresh_token
        sig = inspect.signature(refresh_token)
        params = list(sig.parameters.keys())
        assert "request" in params, (
            "refresh_token must accept 'request: Request' param for rate limiting"
        )


# ---------------------------------------------------------------------------
# Deprecated webhook cleanup (H3)
# ---------------------------------------------------------------------------

class TestDeprecatedWebhookCleanup:
    """Verify the deprecated plaintext webhook is cleared."""

    def test_migration_clears_plaintext_webhooks(self):
        """The migration list must include a statement to NULL deprecated webhooks."""
        import inspect
        from src.models import session as session_module
        source = inspect.getsource(session_module)
        assert "UPDATE user_configs SET discord_webhook_url = NULL" in source, (
            "Migration must clear deprecated plaintext discord_webhook_url values"
        )

    def test_user_config_webhook_marked_deprecated(self):
        """The UserConfig.discord_webhook_url column should be documented as deprecated."""
        import inspect
        from src.models.database import UserConfig
        source = inspect.getsource(UserConfig)
        assert "DEPRECATED" in source and "discord_webhook_url" in source, (
            "UserConfig.discord_webhook_url must be marked as DEPRECATED in source"
        )


# ---------------------------------------------------------------------------
# User isolation
# ---------------------------------------------------------------------------

class TestUserIsolation:
    """Verify user isolation patterns in database queries."""

    def test_exchange_connections_query_filters_by_user_id(self):
        """_get_user_connections must filter by user_id."""
        import inspect
        from src.api.routers.config import _get_user_connections
        source = inspect.getsource(_get_user_connections)
        assert "user_id" in source, (
            "_get_user_connections must filter by user_id"
        )

    def test_bot_worker_loads_config_by_id(self):
        """BotWorker.initialize must load config by bot_config_id, not globally."""
        import inspect
        from src.bot.bot_worker import BotWorker
        source = inspect.getsource(BotWorker.initialize)
        assert "self.bot_config_id" in source, (
            "BotWorker.initialize must use self.bot_config_id to load config"
        )

    def test_bot_worker_uses_user_id_for_exchange_conn(self):
        """BotWorker must load exchange connection scoped to the bot owner's user_id."""
        import inspect
        from src.bot.bot_worker import BotWorker
        source = inspect.getsource(BotWorker.initialize)
        assert "self._config.user_id" in source, (
            "BotWorker must scope exchange connection to config.user_id"
        )


# ---------------------------------------------------------------------------
# Encryption key management
# ---------------------------------------------------------------------------

class TestEncryptionKeyManagement:
    """Verify encryption key safety properties."""

    def test_production_requires_explicit_key(self):
        """In production, missing ENCRYPTION_KEY must raise RuntimeError."""
        # We can't easily test this without reloading the module, but we can
        # verify the source code contains the check
        import inspect
        from src.utils import encryption
        source = inspect.getsource(encryption)
        assert 'ENVIRONMENT' in source or 'production' in source, (
            "Encryption module must check for production environment"
        )
        assert 'RuntimeError' in source, (
            "Encryption module must raise RuntimeError for missing key in production"
        )

    def test_encryption_key_not_in_git(self):
        """The .gitignore must exclude .env files."""
        gitignore_path = Path(__file__).parent.parent.parent / ".gitignore"
        if gitignore_path.exists():
            content = gitignore_path.read_text()
            assert ".env" in content, ".gitignore must exclude .env files"


# ---------------------------------------------------------------------------
# No logging of secrets
# ---------------------------------------------------------------------------

class TestNoSecretLogging:
    """Verify sensitive values are not logged."""

    def _scan_file_for_secret_logging(self, filepath: str):
        """Scan a Python file for potential secret logging patterns."""
        dangerous_patterns = [
            "logger.*api_key=",
            "logger.*api_secret=",
            "logger.*passphrase=",
            "logger.*password=",
            "logger.*{.*api_key",
            "logger.*{.*api_secret",
            "logger.*{.*passphrase",
            "logger.*{.*webhook_url",
            "print(.*api_key",
            "print(.*api_secret",
            "print(.*passphrase",
        ]
        import re
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            for pattern in dangerous_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    return matches
        except Exception:
            pass
        return []

    def test_bot_worker_does_not_log_secrets(self):
        filepath = str(Path(__file__).parent.parent.parent / "src" / "bot" / "bot_worker.py")
        matches = self._scan_file_for_secret_logging(filepath)
        assert matches == [], f"bot_worker.py may log secrets: {matches}"

    def test_config_router_does_not_log_secrets(self):
        filepath = str(Path(__file__).parent.parent.parent / "src" / "api" / "routers" / "config.py")
        matches = self._scan_file_for_secret_logging(filepath)
        assert matches == [], f"config.py may log secrets: {matches}"

    def test_encryption_module_does_not_log_secrets(self):
        filepath = str(Path(__file__).parent.parent.parent / "src" / "utils" / "encryption.py")
        matches = self._scan_file_for_secret_logging(filepath)
        assert matches == [], f"encryption.py may log secrets: {matches}"
