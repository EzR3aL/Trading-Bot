"""Unit tests for the admin revenue router (read-only after auto-import refactor)."""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import AffiliateState, Base, RevenueEntry, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token


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
    token = create_access_token({"sub": str(admin_user.id), "role": admin_user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def user_headers(regular_user):
    token = create_access_token({"sub": str(regular_user.id), "role": regular_user.role})
    return {"Authorization": f"Bearer {token}"}


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
    today = date.today()
    async with session_factory() as session:
        entries = [
            RevenueEntry(date=today, exchange="bitget", revenue_type="affiliate",
                         amount_usd=150.00, source="auto_import"),
            RevenueEntry(date=today - timedelta(days=5), exchange="weex",
                         revenue_type="affiliate", amount_usd=80.50, source="auto_import"),
        ]
        session.add_all(entries)
        session.add(AffiliateState(
            exchange="bitunix",
            cumulative_amount_usd=0.0,
            last_status="unsupported",
            last_error="No public API",
        ))
        await session.commit()
        return entries


async def test_get_requires_admin(client, user_headers, regular_user):
    resp = await client.get("/api/admin/revenue", headers=user_headers)
    assert resp.status_code == 403


async def test_get_requires_auth(client):
    resp = await client.get("/api/admin/revenue")
    assert resp.status_code == 401


async def test_get_empty(client, admin_headers, admin_user):
    resp = await client.get("/api/admin/revenue", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total"] == 0
    assert data["by_exchange"] == []
    assert data["sync_status"] == {}
    assert "entries" not in data  # manual entry list removed


async def test_get_with_data(client, admin_headers, admin_user, sample_entries):
    resp = await client.get("/api/admin/revenue", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["today"] == 150.00
    assert data["summary"]["total"] == 230.50
    by_ex = {row["exchange"]: row["total"] for row in data["by_exchange"]}
    assert by_ex == {"bitget": 150.00, "weex": 80.50}
    assert data["sync_status"]["bitunix"]["status"] == "unsupported"


async def test_post_manual_entry_route_removed(client, admin_headers, admin_user):
    resp = await client.post("/api/admin/revenue", headers=admin_headers, json={
        "date": str(date.today()), "exchange": "bitget",
        "revenue_type": "affiliate", "amount_usd": 10,
    })
    assert resp.status_code == 405  # Method Not Allowed


async def test_sync_endpoint_requires_admin(client, user_headers):
    resp = await client.post("/api/admin/revenue/sync", headers=user_headers)
    assert resp.status_code == 403
