"""
Extra tests for tax_report router — covering the CSV download endpoint
(lines 95-225) and the JSON tax report endpoint with trade data.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, TradeRecord, User
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
async def user(session_factory):
    async with session_factory() as session:
        u = User(
            username="taxtest",
            email="taxtest@test.com",
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
async def trades_data(session_factory, user):
    year = datetime.now(timezone.utc).year
    items = [
        TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="BTC long win",
            order_id="t_001",
            status="closed",
            pnl=10.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            builder_fee=0.2,
            entry_time=datetime(year, 3, 15, 10, 0),
            exit_time=datetime(year, 3, 16, 10, 0),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=user.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            exit_price=3600.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=4,
            confidence=65,
            reason="ETH short loss",
            order_id="t_002",
            status="closed",
            pnl=-10.0,
            pnl_percent=-2.86,
            fees=0.3,
            funding_paid=0.05,
            builder_fee=0.1,
            entry_time=datetime(year, 3, 20, 10, 0),
            exit_time=datetime(year, 3, 21, 10, 0),
            exit_reason="STOP_LOSS",
            exchange="hyperliquid",
            demo_mode=False,
        ),
    ]
    async with session_factory() as session:
        session.add_all(items)
        await session.commit()
        for t in items:
            await session.refresh(t)
    return items


@pytest_asyncio.fixture
async def app(session_factory):
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import tax_report
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
    test_app.include_router(tax_report.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# JSON endpoint — additional tests
# ---------------------------------------------------------------------------


async def test_tax_report_monthly_breakdown_values(client, auth_headers, trades_data):
    """Monthly breakdown sums PnL correctly per month."""
    year = datetime.now(timezone.utc).year
    resp = await client.get("/api/tax-report", headers=auth_headers, params={"year": year})
    data = resp.json()
    assert len(data["months"]) == 1  # Both trades in March
    march = data["months"][0]
    assert march["month"] == f"{year}-03"
    assert march["trades"] == 2
    assert march["pnl"] == pytest.approx(0.0, abs=0.01)


async def test_tax_report_net_pnl_calculation(client, auth_headers, trades_data):
    """Net PnL = total_pnl - total_fees - abs(total_funding)."""
    resp = await client.get("/api/tax-report", headers=auth_headers)
    data = resp.json()
    expected_net = data["total_pnl"] - data["total_fees"] - abs(data["total_funding"])
    assert data["net_pnl"] == pytest.approx(expected_net, abs=0.01)


# ---------------------------------------------------------------------------
# CSV endpoint — comprehensive tests
# ---------------------------------------------------------------------------


async def test_csv_has_utf8_bom(client, auth_headers, trades_data):
    """CSV starts with UTF-8 BOM."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.text.startswith("\ufeff")


async def test_csv_content_type(client, auth_headers, trades_data):
    """CSV has correct content type."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "text/csv" in resp.headers["content-type"]


async def test_csv_content_disposition(client, auth_headers, trades_data):
    """CSV has correct filename in Content-Disposition."""
    year = datetime.now(timezone.utc).year
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"year": year})
    disposition = resp.headers.get("content-disposition", "")
    assert f"steuerreport_{year}.csv" in disposition


async def test_csv_contains_steuerreport_header(client, auth_headers, trades_data):
    """CSV has STEUERREPORT header."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "STEUERREPORT" in resp.text


async def test_csv_contains_disclaimer(client, auth_headers, trades_data):
    """CSV contains disclaimer section."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "HINWEIS" in resp.text


async def test_csv_contains_summary(client, auth_headers, trades_data):
    """CSV contains ZUSAMMENFASSUNG section."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "ZUSAMMENFASSUNG" in resp.text


async def test_csv_contains_monthly_breakdown(client, auth_headers, trades_data):
    """CSV contains MONATLICHE section."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "MONATLICHE" in resp.text


async def test_csv_contains_detailed_trades(client, auth_headers, trades_data):
    """CSV contains EINZELTRANSAKTIONEN section."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "EINZELTRANSAKTIONEN" in resp.text


async def test_csv_contains_trade_symbols(client, auth_headers, trades_data):
    """CSV contains both trade symbols."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "BTCUSDT" in resp.text
    assert "ETHUSDT" in resp.text


async def test_csv_contains_win_rate(client, auth_headers, trades_data):
    """CSV contains Win Rate metric."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "Win Rate" in resp.text or "Gewinnrate" in resp.text


async def test_csv_mode_demo(client, auth_headers, trades_data):
    """CSV with demo_mode=true shows Demo label."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"demo_mode": True})
    assert "Demo" in resp.text


async def test_csv_mode_live(client, auth_headers, trades_data):
    """CSV with demo_mode=false shows Live label."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"demo_mode": False})
    assert "Live" in resp.text


async def test_csv_mode_all(client, auth_headers, trades_data):
    """CSV without demo_mode shows Alle/All label."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "Alle/All" in resp.text


async def test_csv_contains_duration(client, auth_headers, trades_data):
    """CSV trade rows include duration."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    # Duration of 24h = 24.0
    assert "24.0" in resp.text


async def test_csv_contains_builder_fee(client, auth_headers, trades_data):
    """CSV has Builder Fee in summary."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert "Builder Fee" in resp.text


async def test_csv_empty_year_still_has_headers(client, auth_headers, user):
    """CSV for year with no trades still has section headers."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"year": 2020})
    assert resp.status_code == 200
    assert "STEUERREPORT" in resp.text
    assert "ZUSAMMENFASSUNG" in resp.text


async def test_csv_requires_auth(client, user):
    """CSV endpoint requires authentication."""
    resp = await client.get("/api/tax-report/csv")
    assert resp.status_code == 401
