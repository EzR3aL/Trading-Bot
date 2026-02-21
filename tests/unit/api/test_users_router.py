"""
Unit tests for the users API router.

Covers list_users, create_user, update_user, delete_user,
admin-only access, validation, and error paths.
"""

import os
import sys
from pathlib import Path

import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def admin_user(session_factory):
    async with session_factory() as session:
        u = User(
            username="admin",
            email="admin@test.com",
            password_hash=hash_password("adminpass123"),
            role="admin",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def regular_user(session_factory):
    async with session_factory() as session:
        u = User(
            username="regularuser",
            email="regular@test.com",
            password_hash=hash_password("userpass123"),
            role="user",
            is_active=True,
            language="de",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def admin_headers(admin_user):
    token_data = {"sub": str(admin_user.id), "role": admin_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def user_headers(regular_user):
    token_data = {"sub": str(regular_user.id), "role": regular_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def app(session_factory):
    from fastapi import FastAPI
    from src.api.routers import users
    from src.models.session import get_db

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app = FastAPI()
    test_app.include_router(users.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /api/users: list users (admin only)
# ---------------------------------------------------------------------------


async def test_list_users_admin(client, admin_headers, admin_user):
    """Admin can list all users."""
    resp = await client.get("/api/users", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["username"] == "admin"


async def test_list_users_includes_all(client, admin_headers, admin_user, regular_user):
    """Admin can see all users in the system."""
    resp = await client.get("/api/users", headers=admin_headers)
    data = resp.json()
    usernames = [u["username"] for u in data]
    assert "admin" in usernames
    assert "regularuser" in usernames


async def test_list_users_forbidden_for_regular_user(client, user_headers, regular_user):
    """Regular user cannot list users (403)."""
    resp = await client.get("/api/users", headers=user_headers)
    assert resp.status_code == 403


async def test_list_users_requires_auth(client):
    """List users without auth returns 401."""
    resp = await client.get("/api/users")
    assert resp.status_code == 401


async def test_list_users_response_fields(client, admin_headers, admin_user):
    """User response includes expected fields."""
    resp = await client.get("/api/users", headers=admin_headers)
    data = resp.json()
    user_data = data[0]
    expected_fields = {"id", "username", "email", "role", "language", "is_active"}
    assert expected_fields.issubset(set(user_data.keys()))
    # Ensure password_hash is NOT exposed
    assert "password_hash" not in user_data


# ---------------------------------------------------------------------------
# POST /api/users: create user (admin only)
# ---------------------------------------------------------------------------


async def test_create_user_success(client, admin_headers, admin_user):
    """Admin can create a new user."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "newuser",
            "password": "New@pass123",
            "email": "new@test.com",
            "role": "user",
            "language": "de",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newuser"
    assert data["email"] == "new@test.com"
    assert data["role"] == "user"
    assert data["language"] == "de"
    assert data["is_active"] is True


async def test_create_user_default_role(client, admin_headers, admin_user):
    """Creating user without role defaults to 'user'."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "defaultrole", "password": "Test@1234"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "user"


async def test_create_user_default_language(client, admin_headers, admin_user):
    """Creating user without language defaults to 'de'."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "defaultlang", "password": "Test@1234"},
    )
    assert resp.status_code == 201
    assert resp.json()["language"] == "de"


async def test_create_user_duplicate_username(client, admin_headers, admin_user):
    """Creating a user with an existing username returns 409."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "admin", "password": "Test@1234"},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


async def test_create_user_forbidden_for_regular_user(client, user_headers, regular_user):
    """Regular user cannot create users (403)."""
    resp = await client.post(
        "/api/users",
        headers=user_headers,
        json={"username": "blocked", "password": "Test@1234"},
    )
    assert resp.status_code == 403


async def test_create_user_requires_auth(client):
    """Create user without auth returns 401."""
    resp = await client.post(
        "/api/users",
        json={"username": "noauth", "password": "Test@1234"},
    )
    assert resp.status_code == 401


async def test_create_user_short_username_rejected(client, admin_headers, admin_user):
    """Username shorter than 3 characters is rejected (422)."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "ab", "password": "Test@1234"},
    )
    assert resp.status_code == 422


async def test_create_user_short_password_rejected(client, admin_headers, admin_user):
    """Password shorter than 8 characters is rejected (422)."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "validname", "password": "short"},
    )
    assert resp.status_code == 422


async def test_create_user_invalid_role_rejected(client, admin_headers, admin_user):
    """Invalid role value is rejected (422)."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "badrole", "password": "Test@1234", "role": "superadmin"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/users/{user_id}: update user (admin only)
# ---------------------------------------------------------------------------


async def test_update_user_email(client, admin_headers, admin_user, regular_user):
    """Admin can update a user's email."""
    resp = await client.put(
        f"/api/users/{regular_user.id}",
        headers=admin_headers,
        json={"email": "updated@test.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "updated@test.com"


async def test_update_user_role(client, admin_headers, admin_user, regular_user):
    """Admin can change a user's role."""
    resp = await client.put(
        f"/api/users/{regular_user.id}",
        headers=admin_headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_update_user_language(client, admin_headers, admin_user, regular_user):
    """Admin can change a user's language."""
    resp = await client.put(
        f"/api/users/{regular_user.id}",
        headers=admin_headers,
        json={"language": "en"},
    )
    assert resp.status_code == 200
    assert resp.json()["language"] == "en"


async def test_update_user_is_active(client, admin_headers, admin_user, regular_user):
    """Admin can deactivate a user."""
    resp = await client.put(
        f"/api/users/{regular_user.id}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


async def test_update_user_password(client, admin_headers, admin_user, regular_user):
    """Admin can change a user's password."""
    resp = await client.put(
        f"/api/users/{regular_user.id}",
        headers=admin_headers,
        json={"password": "New@pass789"},
    )
    assert resp.status_code == 200
    # Password change should not be visible in response
    assert "password" not in resp.json()
    assert "password_hash" not in resp.json()


async def test_update_user_not_found(client, admin_headers, admin_user):
    """Updating a non-existent user returns 404."""
    resp = await client.put(
        "/api/users/99999",
        headers=admin_headers,
        json={"email": "gone@test.com"},
    )
    assert resp.status_code == 404


async def test_update_user_forbidden_for_regular(client, user_headers, regular_user):
    """Regular user cannot update users (403)."""
    resp = await client.put(
        f"/api/users/{regular_user.id}",
        headers=user_headers,
        json={"email": "nope@test.com"},
    )
    assert resp.status_code == 403


async def test_update_user_no_changes(client, admin_headers, admin_user, regular_user):
    """Sending empty update body still returns 200 with current data."""
    resp = await client.put(
        f"/api/users/{regular_user.id}",
        headers=admin_headers,
        json={},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "regularuser"


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_id} (admin only)
# ---------------------------------------------------------------------------


async def test_delete_user_success(client, admin_headers, admin_user, regular_user):
    """Admin can delete another user."""
    resp = await client.delete(f"/api/users/{regular_user.id}", headers=admin_headers)
    assert resp.status_code == 204


async def test_delete_user_cannot_delete_self(client, admin_headers, admin_user):
    """Admin cannot delete themselves."""
    resp = await client.delete(f"/api/users/{admin_user.id}", headers=admin_headers)
    assert resp.status_code == 400
    assert "Cannot delete yourself" in resp.json()["detail"]


async def test_delete_user_not_found(client, admin_headers, admin_user):
    """Deleting a non-existent user returns 404."""
    resp = await client.delete("/api/users/99999", headers=admin_headers)
    assert resp.status_code == 404


async def test_delete_user_forbidden_for_regular(client, user_headers, regular_user, admin_user):
    """Regular user cannot delete users (403)."""
    resp = await client.delete(f"/api/users/{admin_user.id}", headers=user_headers)
    assert resp.status_code == 403


async def test_delete_user_requires_auth(client, regular_user):
    """Delete without auth returns 401."""
    resp = await client.delete(f"/api/users/{regular_user.id}")
    assert resp.status_code == 401


async def test_delete_user_then_list_excludes_deleted(client, admin_headers, admin_user, regular_user):
    """After deleting a user, they no longer appear in the list."""
    await client.delete(f"/api/users/{regular_user.id}", headers=admin_headers)
    resp = await client.get("/api/users", headers=admin_headers)
    data = resp.json()
    usernames = [u["username"] for u in data]
    assert "regularuser" not in usernames
