"""
Unit tests for bot management API routes.

Tests bot CRUD operations and lifecycle management.
"""

import asyncio
import os
import pytest
import secrets
import tempfile
import base64
from pathlib import Path

# Set up test environment before imports
os.environ["JWT_SECRET"] = secrets.token_urlsafe(64)
test_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["ENCRYPTION_MASTER_KEY"] = test_key

from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.models.migrations.multi_tenant_schema import upgrade


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Run migration
    import asyncio
    asyncio.get_event_loop().run_until_complete(upgrade(db_path))

    yield db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def app(test_db, monkeypatch):
    """Create test FastAPI app with bot routes."""
    # Patch repositories to use test database
    from src.models.user import UserRepository
    from src.auth.dependencies import SessionManager
    from src.security.credential_manager import CredentialManager
    from src.models.credential import CredentialRepository
    from src.models.bot_instance import BotInstanceRepository
    from src.models.multi_tenant_trade_db import MultiTenantTradeDatabase
    from src.bot import orchestrator as orch_module

    def patched_user_init(self, db_path="data/trades.db"):
        self.db_path = Path(test_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def patched_session_init(self, db_path="data/trades.db"):
        self.db_path = test_db

    def patched_cred_manager_init(self, db_path="data/trades.db"):
        from src.security.encryption import CredentialEncryption
        self._encryption = CredentialEncryption()
        self._repository = CredentialRepository(test_db)

    def patched_cred_repo_init(self, db_path="data/trades.db"):
        self.db_path = Path(test_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def patched_bot_repo_init(self, db_path="data/trades.db"):
        self.db_path = Path(test_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def patched_trade_db_init(self, db_path="data/trades.db"):
        self.db_path = Path(test_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    monkeypatch.setattr(UserRepository, "__init__", patched_user_init)
    monkeypatch.setattr(SessionManager, "__init__", patched_session_init)
    monkeypatch.setattr(CredentialManager, "__init__", patched_cred_manager_init)
    monkeypatch.setattr(CredentialRepository, "__init__", patched_cred_repo_init)
    monkeypatch.setattr(BotInstanceRepository, "__init__", patched_bot_repo_init)
    monkeypatch.setattr(MultiTenantTradeDatabase, "__init__", patched_trade_db_init)

    # Reset global orchestrator for each test
    orch_module._orchestrator = None

    # Patch orchestrator to use test database
    original_init = orch_module.MultiTenantOrchestrator.__init__

    def patched_orchestrator_init(self, db_path="data/trades.db"):
        self.db_path = test_db
        self._instances = {}
        self._lock = asyncio.Lock()
        self._initialized = False
        self._bot_repo = BotInstanceRepository(test_db)
        self._trade_db = MultiTenantTradeDatabase(test_db)
        self._cred_manager = CredentialManager(test_db)
        self._heartbeat_task = None
        self._cleanup_task = None

    monkeypatch.setattr(orch_module.MultiTenantOrchestrator, "__init__", patched_orchestrator_init)

    # Import routes after patching
    from src.dashboard.auth_routes import router as auth_router, limiter as auth_limiter
    from src.dashboard.credential_routes import router as cred_router, limiter as cred_limiter
    from src.dashboard.bot_routes import router as bot_router, limiter as bot_limiter

    app = FastAPI()

    # Disable rate limiting for tests
    auth_limiter.enabled = False
    cred_limiter.enabled = False
    bot_limiter.enabled = False

    app.include_router(auth_router)
    app.include_router(cred_router)
    app.include_router(bot_router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Create a user and get auth headers."""
    response = client.post("/api/auth/register", json={
        "username": "bottest",
        "email": "bottest@example.com",
        "password": "SecurePass123"
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def credential_id(client, auth_headers):
    """Create a credential and return its ID."""
    response = client.post(
        "/api/credentials",
        headers=auth_headers,
        json={
            "name": "Test Credential",
            "api_key": "bg_test_key_1234567890",
            "api_secret": "test_secret_1234567890",
            "passphrase": "testpass123",
            "credential_type": "demo"
        }
    )
    return response.json()["id"]


class TestBotCRUD:
    """Tests for bot CRUD operations."""

    def test_create_bot(self, client, auth_headers, credential_id):
        """Test creating a new bot."""
        response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "My Trading Bot",
                "credential_id": credential_id,
                "config": {
                    "trading_pairs": ["BTCUSDT"],
                    "leverage": 5,
                    "max_trades_per_day": 3
                }
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My Trading Bot"
        assert data["credential_id"] == credential_id
        assert data["config"]["leverage"] == 5
        assert data["is_running"] is False
        assert data["runtime_status"] == "stopped"

    def test_create_bot_default_config(self, client, auth_headers, credential_id):
        """Test creating a bot with default configuration."""
        response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Default Config Bot",
                "credential_id": credential_id
            }
        )

        assert response.status_code == 201
        data = response.json()
        # Should use default config values
        assert data["config"]["leverage"] == 3
        assert data["config"]["max_trades_per_day"] == 2
        assert "BTCUSDT" in data["config"]["trading_pairs"]

    def test_list_bots(self, client, auth_headers, credential_id):
        """Test listing user's bots."""
        # Create two bots
        for i in range(2):
            client.post(
                "/api/bots",
                headers=auth_headers,
                json={
                    "name": f"Bot {i}",
                    "credential_id": credential_id
                }
            )

        response = client.get("/api/bots", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["bots"]) == 2

    def test_get_single_bot(self, client, auth_headers, credential_id):
        """Test getting a single bot."""
        # Create bot
        create_response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Single Bot",
                "credential_id": credential_id
            }
        )
        bot_id = create_response.json()["id"]

        # Get it
        response = client.get(f"/api/bots/{bot_id}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["name"] == "Single Bot"

    def test_update_bot_config(self, client, auth_headers, credential_id):
        """Test updating bot configuration."""
        # Create bot
        create_response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Update Bot",
                "credential_id": credential_id
            }
        )
        bot_id = create_response.json()["id"]

        # Update config
        response = client.put(
            f"/api/bots/{bot_id}",
            headers=auth_headers,
            json={
                "config": {
                    "trading_pairs": ["ETHUSDT"],
                    "leverage": 10,
                    "max_trades_per_day": 5,
                    "position_size_percent": 10.0,
                    "daily_loss_limit_percent": 3.0,
                    "take_profit_percent": 5.0,
                    "stop_loss_percent": 2.0,
                    "min_confidence": 70
                }
            }
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify update
        get_response = client.get(f"/api/bots/{bot_id}", headers=auth_headers)
        assert get_response.json()["config"]["leverage"] == 10

    def test_delete_bot(self, client, auth_headers, credential_id):
        """Test deleting a bot."""
        # Create bot
        create_response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Delete Me",
                "credential_id": credential_id
            }
        )
        bot_id = create_response.json()["id"]

        # Delete it
        response = client.delete(f"/api/bots/{bot_id}", headers=auth_headers)

        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()

        # Verify deletion
        get_response = client.get(f"/api/bots/{bot_id}", headers=auth_headers)
        assert get_response.status_code == 404


class TestBotValidation:
    """Tests for bot validation."""

    def test_create_bot_invalid_credential(self, client, auth_headers):
        """Test creating bot with non-existent credential."""
        response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Invalid Cred Bot",
                "credential_id": 99999
            }
        )

        assert response.status_code == 404

    def test_create_bot_invalid_leverage(self, client, auth_headers, credential_id):
        """Test creating bot with invalid leverage."""
        response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "High Leverage Bot",
                "credential_id": credential_id,
                "config": {
                    "leverage": 100  # Too high
                }
            }
        )

        assert response.status_code == 422

    def test_create_duplicate_name(self, client, auth_headers, credential_id):
        """Test creating bot with duplicate name."""
        # First bot
        client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Duplicate Name",
                "credential_id": credential_id
            }
        )

        # Second bot with same name
        response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Duplicate Name",
                "credential_id": credential_id
            }
        )

        assert response.status_code == 409


class TestBotIsolation:
    """Tests for tenant isolation of bots."""

    def test_user_cannot_see_other_users_bots(self, client, auth_headers, credential_id):
        """Test that users can only see their own bots."""
        # Create bot as first user
        client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "User 1 Bot",
                "credential_id": credential_id
            }
        )

        # Create second user
        client.post("/api/auth/register", json={
            "username": "user2bot",
            "email": "user2bot@example.com",
            "password": "SecurePass123"
        })
        user2_token = client.post("/api/auth/login", json={
            "username": "user2bot",
            "password": "SecurePass123"
        }).json()["access_token"]
        user2_headers = {"Authorization": f"Bearer {user2_token}"}

        # User 2 should see no bots
        response = client.get("/api/bots", headers=user2_headers)
        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_user_cannot_access_other_users_bot(self, client, auth_headers, credential_id):
        """Test that users cannot access bots by ID belonging to others."""
        # Create bot as first user
        create_response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Protected Bot",
                "credential_id": credential_id
            }
        )
        bot_id = create_response.json()["id"]

        # Create second user
        client.post("/api/auth/register", json={
            "username": "attacker3",
            "email": "attacker3@example.com",
            "password": "SecurePass123"
        })
        attacker_token = client.post("/api/auth/login", json={
            "username": "attacker3",
            "password": "SecurePass123"
        }).json()["access_token"]
        attacker_headers = {"Authorization": f"Bearer {attacker_token}"}

        # Attacker tries to access User 1's bot
        response = client.get(f"/api/bots/{bot_id}", headers=attacker_headers)
        assert response.status_code == 404

    def test_user_cannot_delete_other_users_bot(self, client, auth_headers, credential_id):
        """Test that users cannot delete bots belonging to others."""
        # Create bot as first user
        create_response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Cannot Delete Me",
                "credential_id": credential_id
            }
        )
        bot_id = create_response.json()["id"]

        # Create attacker
        client.post("/api/auth/register", json={
            "username": "attacker4",
            "email": "attacker4@example.com",
            "password": "SecurePass123"
        })
        attacker_token = client.post("/api/auth/login", json={
            "username": "attacker4",
            "password": "SecurePass123"
        }).json()["access_token"]
        attacker_headers = {"Authorization": f"Bearer {attacker_token}"}

        # Attacker tries to delete
        response = client.delete(f"/api/bots/{bot_id}", headers=attacker_headers)
        assert response.status_code == 404

        # Bot should still exist
        get_response = client.get(f"/api/bots/{bot_id}", headers=auth_headers)
        assert get_response.status_code == 200


class TestBotStatus:
    """Tests for bot status endpoints."""

    def test_get_bot_status(self, client, auth_headers, credential_id):
        """Test getting bot status."""
        # Create bot
        create_response = client.post(
            "/api/bots",
            headers=auth_headers,
            json={
                "name": "Status Bot",
                "credential_id": credential_id
            }
        )
        bot_id = create_response.json()["id"]

        # Get status
        response = client.get(f"/api/bots/{bot_id}/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"
        assert data["uptime_seconds"] == 0
        assert data["trades_today"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
