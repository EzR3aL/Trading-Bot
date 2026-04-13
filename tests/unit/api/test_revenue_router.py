"""
Unit tests for the admin revenue router: GET/POST/PUT/DELETE /api/admin/revenue.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, RevenueEntry, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token


# ===========================================================================
# Shared fixtures
# ===========================================================================


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
            username="regular",
            email="regular@test.com",
            password_hash=hash_password("userpass123"),
            role="user",
            is_active=True,
            language="en",
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
    from src.api.routers import revenue
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
    test_app.include_router(revenue.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def sample_entries(session_factory):
    """Insert sample revenue entries for testing."""
    today = date.today()
    async with session_factory() as session:
        entries = [
            RevenueEntry(
                date=today,
                exchange="bitget",
                revenue_type="affiliate",
                amount_usd=150.00,
                source="manual",
                notes="Q1 payout",
            ),
            RevenueEntry(
                date=today - timedelta(days=5),
                exchange="weex",
                revenue_type="affiliate",
                amount_usd=80.50,
                source="manual",
            ),
            RevenueEntry(
                date=today - timedelta(days=10),
                exchange="hyperliquid",
                revenue_type="builder_fee",
                amount_usd=25.00,
                source="auto",
            ),
        ]
        session.add_all(entries)
        await session.commit()
        for e in entries:
            await session.refresh(e)
        return entries


# ===========================================================================
# GET /api/admin/revenue
# ===========================================================================


async def test_get_revenue_requires_admin(client, user_headers, regular_user):
    """Non-admin users get 403."""
    resp = await client.get("/api/admin/revenue", headers=user_headers)
    assert resp.status_code == 403


async def test_get_revenue_requires_auth(client):
    """Unauthenticated request gets 401."""
    resp = await client.get("/api/admin/revenue")
    assert resp.status_code == 401


async def test_get_revenue_empty(client, admin_headers, admin_user):
    """Returns zero summary when no data exists."""
    resp = await client.get("/api/admin/revenue", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total"] == 0
    assert data["summary"]["today"] == 0
    assert data["by_exchange"] == []
    assert data["entries"] == []


async def test_get_revenue_with_data(client, admin_headers, admin_user, sample_entries):
    """Returns aggregated data with manual entries."""
    resp = await client.get("/api/admin/revenue", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["summary"]["total"] > 0
    assert data["summary"]["today"] == 150.00
    assert len(data["entries"]) == 3
    assert len(data["by_exchange"]) >= 2


async def test_get_revenue_period_filter(client, admin_headers, admin_user, sample_entries):
    """Period filter limits results correctly."""
    resp = await client.get(
        "/api/admin/revenue", params={"period": "7d"}, headers=admin_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    # Entry from 10 days ago should be excluded
    assert data["summary"]["total"] == 230.50  # 150 + 80.50


async def test_get_revenue_response_structure(client, admin_headers, admin_user, sample_entries):
    """Response has expected top-level keys."""
    resp = await client.get("/api/admin/revenue", headers=admin_headers)
    data = resp.json()
    assert "summary" in data
    assert "by_exchange" in data
    assert "daily" in data
    assert "entries" in data
    assert set(data["summary"].keys()) == {"today", "last_7d", "last_30d", "total"}


async def test_get_revenue_entry_fields(client, admin_headers, admin_user, sample_entries):
    """Each entry in the response has expected fields."""
    resp = await client.get("/api/admin/revenue", headers=admin_headers)
    entry = resp.json()["entries"][0]
    assert "id" in entry
    assert "date" in entry
    assert "exchange" in entry
    assert "type" in entry
    assert "amount" in entry
    assert "source" in entry


# ===========================================================================
# POST /api/admin/revenue
# ===========================================================================


async def test_create_entry_success(client, admin_headers, admin_user):
    """Admin can create a manual revenue entry."""
    payload = {
        "date": str(date.today()),
        "exchange": "bingx",
        "revenue_type": "affiliate",
        "amount_usd": 42.50,
        "notes": "Test entry",
    }
    resp = await client.post("/api/admin/revenue", json=payload, headers=admin_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["exchange"] == "bingx"
    assert data["amount"] == 42.50
    assert data["source"] == "manual"
    assert data["notes"] == "Test entry"


async def test_create_entry_requires_admin(client, user_headers, regular_user):
    """Non-admin users cannot create entries."""
    payload = {
        "date": str(date.today()),
        "exchange": "bitget",
        "revenue_type": "affiliate",
        "amount_usd": 10.00,
    }
    resp = await client.post("/api/admin/revenue", json=payload, headers=user_headers)
    assert resp.status_code == 403


async def test_create_entry_validates_amount(client, admin_headers, admin_user):
    """Amount must be > 0."""
    payload = {
        "date": str(date.today()),
        "exchange": "bitget",
        "revenue_type": "affiliate",
        "amount_usd": -5.00,
    }
    resp = await client.post("/api/admin/revenue", json=payload, headers=admin_headers)
    assert resp.status_code == 422


async def test_create_entry_accepts_type_alias(client, admin_headers, admin_user):
    """Frontend sends 'type' instead of 'revenue_type' — both should work."""
    payload = {
        "date": str(date.today()),
        "exchange": "bitget",
        "type": "commission",
        "amount_usd": 25.00,
    }
    resp = await client.post("/api/admin/revenue", json=payload, headers=admin_headers)
    assert resp.status_code == 201
    assert resp.json()["type"] == "commission"


# ===========================================================================
# PUT /api/admin/revenue/{id}
# ===========================================================================


async def test_update_entry_success(client, admin_headers, admin_user, sample_entries):
    """Admin can update a manual entry."""
    entry_id = sample_entries[0].id  # manual entry
    payload = {"amount_usd": 200.00, "notes": "Updated amount"}
    resp = await client.put(
        f"/api/admin/revenue/{entry_id}", json=payload, headers=admin_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["amount"] == 200.00
    assert data["notes"] == "Updated amount"


async def test_update_entry_not_found(client, admin_headers, admin_user):
    """Updating a non-existent entry returns 404."""
    resp = await client.put(
        "/api/admin/revenue/99999", json={"amount_usd": 10.0}, headers=admin_headers
    )
    assert resp.status_code == 404


async def test_update_auto_entry_rejected(client, admin_headers, admin_user, sample_entries):
    """Auto entries cannot be edited."""
    auto_entry = sample_entries[2]  # source="auto"
    resp = await client.put(
        f"/api/admin/revenue/{auto_entry.id}",
        json={"amount_usd": 999.00},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "automatische" in resp.json()["detail"].lower()


async def test_update_entry_requires_admin(client, user_headers, regular_user, sample_entries):
    """Non-admin users cannot update entries."""
    resp = await client.put(
        f"/api/admin/revenue/{sample_entries[0].id}",
        json={"amount_usd": 10.0},
        headers=user_headers,
    )
    assert resp.status_code == 403


# ===========================================================================
# DELETE /api/admin/revenue/{id}
# ===========================================================================


async def test_delete_entry_success(client, admin_headers, admin_user, sample_entries):
    """Admin can delete a manual entry."""
    entry_id = sample_entries[0].id
    resp = await client.delete(
        f"/api/admin/revenue/{entry_id}", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["detail"] == "deleted"

    # Verify it's gone
    get_resp = await client.get("/api/admin/revenue", headers=admin_headers)
    ids = [e["id"] for e in get_resp.json()["entries"]]
    assert entry_id not in ids


async def test_delete_entry_not_found(client, admin_headers, admin_user):
    """Deleting a non-existent entry returns 404."""
    resp = await client.delete("/api/admin/revenue/99999", headers=admin_headers)
    assert resp.status_code == 404


async def test_delete_auto_entry_rejected(client, admin_headers, admin_user, sample_entries):
    """Auto entries cannot be deleted."""
    auto_entry = sample_entries[2]
    resp = await client.delete(
        f"/api/admin/revenue/{auto_entry.id}", headers=admin_headers
    )
    assert resp.status_code == 400
    assert "automatische" in resp.json()["detail"].lower()


async def test_delete_entry_requires_admin(client, user_headers, regular_user, sample_entries):
    """Non-admin users cannot delete entries."""
    resp = await client.delete(
        f"/api/admin/revenue/{sample_entries[0].id}", headers=user_headers
    )
    assert resp.status_code == 403
