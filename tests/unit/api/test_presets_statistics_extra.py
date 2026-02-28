"""
Integration tests for presets, statistics, and funding routers.

Covers uncovered lines in:
- src/api/routers/presets.py (lines 17-195)
- src/api/routers/statistics.py (lines 51-60, 160-168)
- src/api/routers/funding.py (lines 14-93)
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, ConfigPreset, FundingPayment, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token
from src.errors import ERR_PRESET_ACTIVE_CANNOT_DELETE


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
async def user(session_factory):
    async with session_factory() as session:
        u = User(
            username="presetuser",
            email="preset@test.com",
            password_hash=hash_password("password123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def auth_headers(user):
    token_data = {"sub": str(user.id), "role": user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def app(session_factory):
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import presets, statistics, funding
    from src.models.session import get_db

    limiter.enabled = False

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app = FastAPI()
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    test_app.include_router(presets.router)
    test_app.include_router(statistics.router)
    test_app.include_router(funding.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def preset(session_factory, user):
    async with session_factory() as session:
        p = ConfigPreset(
            user_id=user.id,
            name="Test Preset",
            description="A test preset",
            exchange_type="bitget",
            trading_config=json.dumps({"leverage": 5, "position_size_percent": 10}),
            strategy_config=json.dumps({"llm_provider": "groq"}),
            trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT"]),
            is_active=False,
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return p


@pytest_asyncio.fixture
async def trade_data(session_factory, user):
    async with session_factory() as session:
        trades = [
            TradeRecord(
                user_id=user.id,
                symbol="BTCUSDT",
                side="long",
                size=0.01,
                entry_price=95000,
                exit_price=96000,
                take_profit=97000,
                stop_loss=94000,
                leverage=4,
                confidence=75,
                reason="BTC long",
                order_id="ord_001",
                status="closed",
                pnl=10.0,
                pnl_percent=1.05,
                fees=0.5,
                funding_paid=0.1,
                builder_fee=0.2,
                entry_time=datetime.now(timezone.utc) - timedelta(days=5),
                exit_time=datetime.now(timezone.utc) - timedelta(days=4),
                exchange="hyperliquid",
                demo_mode=False,
            ),
            TradeRecord(
                user_id=user.id,
                symbol="ETHUSDT",
                side="short",
                size=0.1,
                entry_price=3500,
                exit_price=3600,
                take_profit=3300,
                stop_loss=3600,
                leverage=4,
                confidence=60,
                reason="ETH short",
                order_id="ord_002",
                status="closed",
                pnl=-10.0,
                pnl_percent=-2.86,
                fees=0.3,
                funding_paid=0.05,
                builder_fee=0.0,
                entry_time=datetime.now(timezone.utc) - timedelta(days=3),
                exit_time=datetime.now(timezone.utc) - timedelta(days=2),
                exchange="bitget",
                demo_mode=True,
            ),
        ]
        session.add_all(trades)
        await session.commit()
    return trades


@pytest_asyncio.fixture
async def funding_data(session_factory, user):
    async with session_factory() as session:
        payments = [
            FundingPayment(
                user_id=user.id,
                symbol="BTCUSDT",
                funding_rate=0.0001,
                position_size=0.01,
                position_value=950.0,
                payment_amount=0.95,
                side="long",
                timestamp=datetime.now(timezone.utc) - timedelta(days=2),
            ),
            FundingPayment(
                user_id=user.id,
                symbol="ETHUSDT",
                funding_rate=-0.0002,
                position_size=0.1,
                position_value=350.0,
                payment_amount=-0.7,
                side="short",
                timestamp=datetime.now(timezone.utc) - timedelta(days=1),
            ),
        ]
        session.add_all(payments)
        await session.commit()
    return payments


# ---------------------------------------------------------------------------
# Presets Router Tests
# ---------------------------------------------------------------------------


async def test_list_presets_empty(client, auth_headers):
    resp = await client.get("/api/presets", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_preset(client, auth_headers):
    resp = await client.post(
        "/api/presets",
        headers=auth_headers,
        json={
            "name": "My Preset",
            "description": "Test desc",
            "exchange_type": "bitget",
            "trading_config": {"leverage": 10},
            "strategy_config": {"llm_provider": "openai"},
            "trading_pairs": ["BTCUSDT"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Preset"
    assert data["exchange_type"] == "bitget"
    assert data["trading_config"]["leverage"] == 10
    assert data["trading_pairs"] == ["BTCUSDT"]


async def test_create_preset_minimal(client, auth_headers):
    resp = await client.post(
        "/api/presets",
        headers=auth_headers,
        json={
            "name": "Minimal",
            "exchange_type": "hyperliquid",
            "trading_pairs": ["BTC"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["trading_config"] is None
    assert data["strategy_config"] is None


async def test_list_presets_with_data(client, auth_headers, preset):
    resp = await client.get("/api/presets", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["name"] == "Test Preset"


async def test_get_preset(client, auth_headers, preset):
    resp = await client.get(f"/api/presets/{preset.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == preset.id
    assert data["name"] == "Test Preset"
    assert data["trading_config"]["leverage"] == 5


async def test_get_preset_not_found(client, auth_headers):
    resp = await client.get("/api/presets/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_update_preset_all_fields(client, auth_headers, preset):
    resp = await client.put(
        f"/api/presets/{preset.id}",
        headers=auth_headers,
        json={
            "name": "Updated Preset",
            "description": "Updated desc",
            "trading_config": {"leverage": 20},
            "strategy_config": {"llm_provider": "gemini"},
            "trading_pairs": ["SOLUSDT"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Preset"
    assert data["trading_config"]["leverage"] == 20
    assert data["trading_pairs"] == ["SOLUSDT"]


async def test_update_preset_partial(client, auth_headers, preset):
    resp = await client.put(
        f"/api/presets/{preset.id}",
        headers=auth_headers,
        json={"description": "New description"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "New description"


async def test_update_preset_not_found(client, auth_headers):
    resp = await client.put(
        "/api/presets/99999",
        headers=auth_headers,
        json={"name": "Nope"},
    )
    assert resp.status_code == 404


async def test_delete_preset(client, auth_headers, preset):
    resp = await client.delete(f"/api/presets/{preset.id}", headers=auth_headers)
    assert resp.status_code == 204


async def test_delete_preset_not_found(client, auth_headers):
    resp = await client.delete("/api/presets/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_delete_active_preset_fails(client, auth_headers, preset, session_factory):
    async with session_factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(ConfigPreset).where(ConfigPreset.id == preset.id)
        )
        p = result.scalar_one()
        p.is_active = True
        await session.commit()

    resp = await client.delete(f"/api/presets/{preset.id}", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == ERR_PRESET_ACTIVE_CANNOT_DELETE


async def test_activate_preset(client, auth_headers, preset):
    resp = await client.post(
        f"/api/presets/{preset.id}/activate", headers=auth_headers
    )
    assert resp.status_code == 200
    assert "activated" in resp.json()["message"]


async def test_activate_deactivates_others(client, auth_headers, preset, session_factory):
    # Create a second preset and activate it
    async with session_factory() as session:
        p2 = ConfigPreset(
            user_id=preset.user_id,
            name="Second",
            exchange_type="bitget",
            trading_pairs=json.dumps(["BTCUSDT"]),
            is_active=True,
        )
        session.add(p2)
        await session.commit()
        await session.refresh(p2)
        _p2_id = p2.id

    # Activate the first preset
    resp = await client.post(
        f"/api/presets/{preset.id}/activate", headers=auth_headers
    )
    assert resp.status_code == 200

    # Verify via list that only one is active
    resp = await client.get("/api/presets", headers=auth_headers)
    data = resp.json()
    active_presets = [p for p in data if p["is_active"]]
    assert len(active_presets) == 1
    assert active_presets[0]["id"] == preset.id


async def test_activate_preset_not_found(client, auth_headers):
    resp = await client.post("/api/presets/99999/activate", headers=auth_headers)
    assert resp.status_code == 404


async def test_duplicate_preset(client, auth_headers, preset):
    resp = await client.post(
        f"/api/presets/{preset.id}/duplicate", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Preset (Copy)"
    assert data["is_active"] is False
    assert data["exchange_type"] == "bitget"


async def test_duplicate_preset_not_found(client, auth_headers):
    resp = await client.post("/api/presets/99999/duplicate", headers=auth_headers)
    assert resp.status_code == 404


async def test_presets_require_auth(client):
    resp = await client.get("/api/presets")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Statistics Router Tests
# ---------------------------------------------------------------------------


async def test_get_statistics_empty(client, auth_headers):
    resp = await client.get("/api/statistics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_trades"] == 0
    assert data["win_rate"] == 0


async def test_get_statistics_with_trades(client, auth_headers, trade_data):
    resp = await client.get("/api/statistics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_trades"] == 2
    assert data["winning_trades"] == 1
    assert data["losing_trades"] == 1
    assert data["win_rate"] == 50.0
    assert data["total_builder_fees"] > 0


async def test_get_statistics_demo_filter(client, auth_headers, trade_data):
    resp = await client.get(
        "/api/statistics", headers=auth_headers, params={"demo_mode": True}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_trades"] == 1


async def test_get_statistics_live_filter(client, auth_headers, trade_data):
    resp = await client.get(
        "/api/statistics", headers=auth_headers, params={"demo_mode": False}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_trades"] == 1


async def test_get_statistics_custom_days(client, auth_headers, trade_data):
    resp = await client.get(
        "/api/statistics", headers=auth_headers, params={"days": 1}
    )
    assert resp.status_code == 200


async def test_get_daily_stats(client, auth_headers, trade_data):
    resp = await client.get("/api/statistics/daily", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "days" in data
    assert len(data["days"]) >= 1
    day = data["days"][0]
    assert "date" in day
    assert "trades" in day
    assert "pnl" in day
    assert "builder_fees" in day


async def test_get_daily_stats_demo_filter(client, auth_headers, trade_data):
    resp = await client.get(
        "/api/statistics/daily",
        headers=auth_headers,
        params={"demo_mode": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["days"]) >= 1


async def test_get_revenue_analytics(client, auth_headers, trade_data):
    resp = await client.get("/api/statistics/revenue", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_trades" in data
    assert "total_builder_fees" in data
    assert "monthly_estimate" in data
    assert "daily" in data


async def test_get_revenue_with_hl_trades(client, auth_headers, trade_data):
    resp = await client.get(
        "/api/statistics/revenue",
        headers=auth_headers,
        params={"demo_mode": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only HL trades with demo_mode=False
    assert data["total_trades"] >= 1
    assert data["total_builder_fees"] >= 0


async def test_statistics_requires_auth(client):
    resp = await client.get("/api/statistics")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Funding Router Tests
# ---------------------------------------------------------------------------


async def test_list_funding_empty(client, auth_headers):
    resp = await client.get("/api/funding", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["payments"] == []
    assert data["total_count"] == 0


async def test_list_funding_with_data(client, auth_headers, funding_data):
    resp = await client.get("/api/funding", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 2
    assert len(data["payments"]) == 2


async def test_list_funding_filter_by_symbol(client, auth_headers, funding_data):
    resp = await client.get(
        "/api/funding", headers=auth_headers, params={"symbol": "BTCUSDT"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 1
    assert data["payments"][0]["symbol"] == "BTCUSDT"


async def test_list_funding_custom_days(client, auth_headers, funding_data):
    resp = await client.get(
        "/api/funding", headers=auth_headers, params={"days": 1}
    )
    assert resp.status_code == 200


async def test_funding_summary(client, auth_headers, funding_data):
    resp = await client.get("/api/funding/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_payments"] == 2
    assert data["total_received"] > 0
    assert data["total_paid"] < 0
    assert "net" in data


async def test_funding_summary_empty(client, auth_headers):
    resp = await client.get("/api/funding/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_payments"] == 0


async def test_funding_requires_auth(client):
    resp = await client.get("/api/funding")
    assert resp.status_code == 401
