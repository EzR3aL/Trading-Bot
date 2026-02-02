"""
Unit tests for credential management API routes.

Tests CRUD operations on credentials with proper tenant isolation.
"""

import os
import pytest
import secrets
import tempfile
from pathlib import Path

# Set up test environment before imports
os.environ["JWT_SECRET"] = secrets.token_urlsafe(64)
# Generate a proper 32-byte key encoded as base64
import base64
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
    """Create test FastAPI app with credential routes."""
    # Patch repositories to use test database
    from src.models.user import UserRepository
    from src.auth.dependencies import SessionManager
    from src.security.credential_manager import CredentialManager
    from src.models.credential import CredentialRepository

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

    monkeypatch.setattr(UserRepository, "__init__", patched_user_init)
    monkeypatch.setattr(SessionManager, "__init__", patched_session_init)
    monkeypatch.setattr(CredentialManager, "__init__", patched_cred_manager_init)
    monkeypatch.setattr(CredentialRepository, "__init__", patched_cred_repo_init)

    # Import routes after patching
    from src.dashboard.auth_routes import router as auth_router, limiter as auth_limiter
    from src.dashboard.credential_routes import router as cred_router, limiter as cred_limiter

    app = FastAPI()

    # Disable rate limiting for tests
    auth_limiter.enabled = False
    cred_limiter.enabled = False

    app.include_router(auth_router)
    app.include_router(cred_router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def auth_token(client):
    """Create a user and get auth token."""
    response = client.post("/api/auth/register", json={
        "username": "credtest",
        "email": "credtest@example.com",
        "password": "SecurePass123"
    })
    return response.json()["access_token"]


@pytest.fixture
def auth_headers(auth_token):
    """Get authorization headers."""
    return {"Authorization": f"Bearer {auth_token}"}


class TestCredentialCRUD:
    """Tests for basic credential CRUD operations."""

    def test_create_credential(self, client, auth_headers):
        """Test creating a new credential."""
        response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "My Bitget Account",
                "api_key": "bg_1234567890abcdef",
                "api_secret": "secretkey1234567890",
                "passphrase": "mypassphrase",
                "exchange": "bitget",
                "credential_type": "demo"
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My Bitget Account"
        assert data["exchange"] == "bitget"
        assert data["credential_type"] == "demo"
        assert "****" in data["api_key_masked"]  # Key should be masked
        assert data["is_active"] is True

    def test_list_credentials(self, client, auth_headers):
        """Test listing user credentials."""
        # Create two credentials
        for i in range(2):
            client.post(
                "/api/credentials",
                headers=auth_headers,
                json={
                    "name": f"Account {i}",
                    "api_key": f"bg_key_{i}_1234567890",
                    "api_secret": f"secret_{i}_1234567890",
                    "passphrase": f"pass{i}word",
                    "credential_type": "demo"
                }
            )

        response = client.get("/api/credentials", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["credentials"]) == 2

    def test_get_single_credential(self, client, auth_headers):
        """Test getting a single credential."""
        # Create credential
        create_response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Single Test",
                "api_key": "bg_single_1234567890",
                "api_secret": "secret_single_1234567890",
                "passphrase": "singlepass"
            }
        )
        cred_id = create_response.json()["id"]

        # Get it
        response = client.get(f"/api/credentials/{cred_id}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["name"] == "Single Test"

    def test_update_credential(self, client, auth_headers):
        """Test updating a credential."""
        # Create credential
        create_response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Update Test",
                "api_key": "bg_update_1234567890",
                "api_secret": "secret_update_1234567890",
                "passphrase": "updatepass"
            }
        )
        cred_id = create_response.json()["id"]

        # Update it
        response = client.put(
            f"/api/credentials/{cred_id}",
            headers=auth_headers,
            json={
                "api_key": "bg_new_key_1234567890",
                "api_secret": "new_secret_1234567890"
            }
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_revoke_credential(self, client, auth_headers):
        """Test revoking (soft delete) a credential."""
        # Create credential
        create_response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Revoke Test",
                "api_key": "bg_revoke_1234567890",
                "api_secret": "secret_revoke_1234567890",
                "passphrase": "revokepass"
            }
        )
        cred_id = create_response.json()["id"]

        # Revoke it
        response = client.delete(f"/api/credentials/{cred_id}", headers=auth_headers)

        assert response.status_code == 200
        assert "revoked" in response.json()["message"]

        # Should not appear in list
        list_response = client.get("/api/credentials", headers=auth_headers)
        cred_ids = [c["id"] for c in list_response.json()["credentials"]]
        assert cred_id not in cred_ids

    def test_delete_credential_permanently(self, client, auth_headers):
        """Test permanently deleting a credential."""
        # Create credential
        create_response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Delete Test",
                "api_key": "bg_delete_1234567890",
                "api_secret": "secret_delete_1234567890",
                "passphrase": "deletepass"
            }
        )
        cred_id = create_response.json()["id"]

        # Delete permanently
        response = client.delete(
            f"/api/credentials/{cred_id}?permanent=true",
            headers=auth_headers
        )

        assert response.status_code == 200
        assert "deleted" in response.json()["message"]


class TestCredentialValidation:
    """Tests for credential validation."""

    def test_create_with_invalid_name(self, client, auth_headers):
        """Test that invalid credential names are rejected."""
        response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Invalid<>Name!",  # Invalid characters
                "api_key": "bg_1234567890abcdef",
                "api_secret": "secretkey1234567890",
                "passphrase": "mypassphrase"
            }
        )

        assert response.status_code == 422

    def test_create_with_short_api_key(self, client, auth_headers):
        """Test that short API keys are rejected."""
        response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Short Key",
                "api_key": "short",  # Too short
                "api_secret": "secretkey1234567890",
                "passphrase": "mypassphrase"
            }
        )

        assert response.status_code == 422

    def test_create_with_invalid_type(self, client, auth_headers):
        """Test that invalid credential types are rejected."""
        response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Invalid Type",
                "api_key": "bg_1234567890abcdef",
                "api_secret": "secretkey1234567890",
                "passphrase": "mypassphrase",
                "credential_type": "invalid"  # Not live or demo
            }
        )

        assert response.status_code == 422

    def test_update_with_no_fields(self, client, auth_headers):
        """Test that updating with no fields is rejected."""
        # Create credential first
        create_response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "No Update",
                "api_key": "bg_noupdate_1234567890",
                "api_secret": "secret_noupdate_1234567890",
                "passphrase": "noupdatepass"
            }
        )
        cred_id = create_response.json()["id"]

        # Try to update with empty body
        response = client.put(
            f"/api/credentials/{cred_id}",
            headers=auth_headers,
            json={}
        )

        assert response.status_code == 400


class TestCredentialIsolation:
    """Tests for tenant isolation of credentials."""

    def test_user_cannot_see_other_users_credentials(self, client, auth_headers):
        """Test that users can only see their own credentials."""
        # Create credential as first user
        client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "User 1 Credential",
                "api_key": "bg_user1_1234567890",
                "api_secret": "secret_user1_1234567890",
                "passphrase": "user1pass"
            }
        )

        # Create second user
        client.post("/api/auth/register", json={
            "username": "user2",
            "email": "user2@example.com",
            "password": "SecurePass123"
        })
        user2_token = client.post("/api/auth/login", json={
            "username": "user2",
            "password": "SecurePass123"
        }).json()["access_token"]
        user2_headers = {"Authorization": f"Bearer {user2_token}"}

        # User 2 should see no credentials
        response = client.get("/api/credentials", headers=user2_headers)
        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_user_cannot_access_other_users_credential(self, client, auth_headers):
        """Test that users cannot access credentials by ID belonging to others."""
        # Create credential as first user
        create_response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "User 1 Only",
                "api_key": "bg_user1only_1234567890",
                "api_secret": "secret_user1only_1234567890",
                "passphrase": "user1onlypass"
            }
        )
        cred_id = create_response.json()["id"]

        # Create second user
        client.post("/api/auth/register", json={
            "username": "attacker",
            "email": "attacker@example.com",
            "password": "SecurePass123"
        })
        attacker_token = client.post("/api/auth/login", json={
            "username": "attacker",
            "password": "SecurePass123"
        }).json()["access_token"]
        attacker_headers = {"Authorization": f"Bearer {attacker_token}"}

        # Attacker tries to access User 1's credential
        response = client.get(f"/api/credentials/{cred_id}", headers=attacker_headers)
        assert response.status_code == 404

    def test_user_cannot_delete_other_users_credential(self, client, auth_headers):
        """Test that users cannot delete credentials belonging to others."""
        # Create credential as first user
        create_response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Protected Cred",
                "api_key": "bg_protected_1234567890",
                "api_secret": "secret_protected_1234567890",
                "passphrase": "protectedpass"
            }
        )
        cred_id = create_response.json()["id"]

        # Create second user (attacker)
        client.post("/api/auth/register", json={
            "username": "attacker2",
            "email": "attacker2@example.com",
            "password": "SecurePass123"
        })
        attacker_token = client.post("/api/auth/login", json={
            "username": "attacker2",
            "password": "SecurePass123"
        }).json()["access_token"]
        attacker_headers = {"Authorization": f"Bearer {attacker_token}"}

        # Attacker tries to delete User 1's credential
        response = client.delete(f"/api/credentials/{cred_id}", headers=attacker_headers)
        assert response.status_code == 404

        # Credential should still exist for original user
        list_response = client.get("/api/credentials", headers=auth_headers)
        assert list_response.json()["count"] >= 1


class TestCredentialTest:
    """Tests for credential testing endpoint."""

    def test_test_credential_validation(self, client, auth_headers):
        """Test that credential test validates encryption."""
        # Create credential
        create_response = client.post(
            "/api/credentials",
            headers=auth_headers,
            json={
                "name": "Test Me",
                "api_key": "bg_testme_1234567890",
                "api_secret": "secret_testme_1234567890",
                "passphrase": "testmepass"
            }
        )
        cred_id = create_response.json()["id"]

        # Test the credential
        response = client.post(
            f"/api/credentials/{cred_id}/test",
            headers=auth_headers
        )

        # Should succeed (encryption valid) even if API test unavailable
        assert response.status_code == 200
        # The response should indicate validation status
        data = response.json()
        assert "success" in data
        assert "message" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
