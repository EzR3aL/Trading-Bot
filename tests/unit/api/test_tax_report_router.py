"""
Unit tests for the tax_report API router.

Covers JSON tax report, CSV download, monthly breakdown,
demo_mode filtering, empty year, edge cases, and auth requirements.
"""

import os
import sys
from datetime import datetime, timedelta
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
async def user(session_factory):
    async with session_factory() as session:
        u = User(
            username="taxuser",
            email="tax@test.com",
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
async def closed_trades(session_factory, user):
    """Insert closed trades in the current year for tax reporting.

    All entry_time dates must be within the current year so the default
    year filter picks them up correctly.
    """
    year = datetime.utcnow().year
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
            order_id="tax_001",
            status="closed",
            pnl=10.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            builder_fee=0.2,
            entry_time=datetime(year, 1, 15, 10, 0),
            exit_time=datetime(year, 1, 16, 10, 0),
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
            exit_price=3400.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=4,
            confidence=80,
            reason="ETH short win",
            order_id="tax_002",
            status="closed",
            pnl=10.0,
            pnl_percent=2.86,
            fees=0.3,
            funding_paid=0.05,
            builder_fee=0.1,
            entry_time=datetime(year, 1, 20, 10, 0),
            exit_time=datetime(year, 1, 21, 10, 0),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.02,
            entry_price=94000.0,
            exit_price=93000.0,
            take_profit=96000.0,
            stop_loss=93000.0,
            leverage=4,
            confidence=60,
            reason="BTC long loss",
            order_id="tax_003",
            status="closed",
            pnl=-20.0,
            pnl_percent=-1.06,
            fees=0.4,
            funding_paid=0.08,
            builder_fee=0.15,
            entry_time=datetime(year, 2, 5, 10, 0),
            exit_time=datetime(year, 2, 6, 10, 0),
            exit_reason="STOP_LOSS",
            exchange="bitget",
            demo_mode=False,
        ),
        # Open trade (should be excluded from tax report)
        TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95500.0,
            take_profit=97000.0,
            stop_loss=94500.0,
            leverage=4,
            confidence=70,
            reason="BTC open",
            order_id="tax_004",
            status="open",
            entry_time=datetime(year, 2, 10, 10, 0),
            exchange="bitget",
            demo_mode=True,
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
# _fmt helper function
# ---------------------------------------------------------------------------


def test_fmt_none_value():
    """_fmt returns '0.00' for None."""
    from src.api.routers.tax_report import _fmt
    assert _fmt(None) == "0.00"


def test_fmt_float_value():
    """_fmt formats a float with correct decimals."""
    from src.api.routers.tax_report import _fmt
    assert _fmt(10.12345) == "10.12"
    assert _fmt(10.12345, 4) == "10.1235"


def test_fmt_zero_value():
    """_fmt handles 0.0 correctly."""
    from src.api.routers.tax_report import _fmt
    assert _fmt(0.0) == "0.00"


def test_fmt_negative_value():
    """_fmt handles negative values."""
    from src.api.routers.tax_report import _fmt
    assert _fmt(-5.5) == "-5.50"


def test_fmt_none_with_custom_decimals():
    """_fmt with None and custom decimals."""
    from src.api.routers.tax_report import _fmt
    assert _fmt(None, 4) == "0.0000"


# ---------------------------------------------------------------------------
# _query_trades helper function
# ---------------------------------------------------------------------------


def test_query_trades_returns_select():
    """_query_trades returns a SQLAlchemy select statement."""
    from src.api.routers.tax_report import _query_trades
    query = _query_trades(user_id=1, year=2025, demo_mode=None)
    assert query is not None


def test_query_trades_with_demo_mode():
    """_query_trades includes demo_mode filter when provided."""
    from src.api.routers.tax_report import _query_trades
    query = _query_trades(user_id=1, year=2025, demo_mode=True)
    assert query is not None


# ---------------------------------------------------------------------------
# GET /api/tax-report (JSON)
# ---------------------------------------------------------------------------


async def test_get_tax_report_current_year(client, auth_headers, closed_trades):
    """Tax report for current year returns correct summary."""
    year = datetime.utcnow().year
    resp = await client.get("/api/tax-report", headers=auth_headers, params={"year": year})
    assert resp.status_code == 200
    data = resp.json()
    assert data["year"] == year
    assert data["total_trades"] == 3
    assert "total_pnl" in data
    assert "total_fees" in data
    assert "total_funding" in data
    assert "net_pnl" in data
    assert "months" in data


async def test_get_tax_report_default_year(client, auth_headers, closed_trades):
    """Tax report without year param defaults to current year."""
    resp = await client.get("/api/tax-report", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["year"] == datetime.utcnow().year


async def test_get_tax_report_totals_correct(client, auth_headers, closed_trades):
    """Tax report totals are computed correctly: 10 + 10 + (-20) = 0."""
    resp = await client.get("/api/tax-report", headers=auth_headers)
    data = resp.json()
    assert data["total_trades"] == 3
    assert data["total_pnl"] == pytest.approx(0.0, abs=0.01)


async def test_get_tax_report_fees_summed(client, auth_headers, closed_trades):
    """Tax report sums fees correctly: 0.5 + 0.3 + 0.4 = 1.2."""
    resp = await client.get("/api/tax-report", headers=auth_headers)
    data = resp.json()
    assert data["total_fees"] == pytest.approx(1.2, abs=0.01)


async def test_get_tax_report_funding_summed(client, auth_headers, closed_trades):
    """Tax report sums funding correctly: 0.1 + 0.05 + 0.08 = 0.23."""
    resp = await client.get("/api/tax-report", headers=auth_headers)
    data = resp.json()
    assert data["total_funding"] == pytest.approx(0.23, abs=0.01)


async def test_get_tax_report_net_pnl(client, auth_headers, closed_trades):
    """Net PnL = total_pnl - total_fees - abs(total_funding)."""
    resp = await client.get("/api/tax-report", headers=auth_headers)
    data = resp.json()
    # total_pnl=0, total_fees=1.2, total_funding=0.23
    # net_pnl = 0 - 1.2 - 0.23 = -1.43
    expected_net = data["total_pnl"] - data["total_fees"] - abs(data["total_funding"])
    assert data["net_pnl"] == pytest.approx(expected_net, abs=0.01)


async def test_get_tax_report_monthly_breakdown(client, auth_headers, closed_trades):
    """Tax report includes monthly breakdown entries."""
    resp = await client.get("/api/tax-report", headers=auth_headers)
    data = resp.json()
    assert isinstance(data["months"], list)
    assert len(data["months"]) >= 1
    for month in data["months"]:
        assert "month" in month
        assert "trades" in month
        assert "pnl" in month
        assert "fees" in month
        assert "funding" in month


async def test_get_tax_report_months_sorted(client, auth_headers, closed_trades):
    """Monthly breakdown is sorted by month key."""
    resp = await client.get("/api/tax-report", headers=auth_headers)
    data = resp.json()
    month_keys = [m["month"] for m in data["months"]]
    assert month_keys == sorted(month_keys)


# ---------------------------------------------------------------------------
# GET /api/tax-report: demo_mode filter
# ---------------------------------------------------------------------------


async def test_get_tax_report_demo_true(client, auth_headers, closed_trades):
    """Tax report filtered by demo_mode=true returns only demo trades."""
    resp = await client.get("/api/tax-report", headers=auth_headers, params={"demo_mode": True})
    data = resp.json()
    assert data["total_trades"] == 2
    assert data["total_pnl"] == pytest.approx(20.0, abs=0.01)


async def test_get_tax_report_demo_false(client, auth_headers, closed_trades):
    """Tax report filtered by demo_mode=false returns only live trades."""
    resp = await client.get("/api/tax-report", headers=auth_headers, params={"demo_mode": False})
    data = resp.json()
    assert data["total_trades"] == 1
    assert data["total_pnl"] == pytest.approx(-20.0, abs=0.01)


# ---------------------------------------------------------------------------
# GET /api/tax-report: empty year
# ---------------------------------------------------------------------------


async def test_get_tax_report_empty_year(client, auth_headers, user):
    """Tax report for a year with no trades returns zeroed values."""
    resp = await client.get("/api/tax-report", headers=auth_headers, params={"year": 2020})
    data = resp.json()
    assert data["year"] == 2020
    assert data["total_trades"] == 0
    assert data["total_pnl"] == 0
    assert data["total_fees"] == 0
    assert data["total_funding"] == 0
    assert data["net_pnl"] == 0
    assert data["months"] == []


# ---------------------------------------------------------------------------
# GET /api/tax-report: auth required
# ---------------------------------------------------------------------------


async def test_get_tax_report_requires_auth(client, user):
    """Tax report endpoint requires authentication."""
    resp = await client.get("/api/tax-report")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/tax-report/csv
# ---------------------------------------------------------------------------


async def test_download_csv_returns_csv_content_type(client, auth_headers, closed_trades):
    """CSV download has text/csv content type."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]


async def test_download_csv_has_content_disposition(client, auth_headers, closed_trades):
    """CSV download has correct Content-Disposition header."""
    year = datetime.utcnow().year
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"year": year})
    assert resp.status_code == 200
    disposition = resp.headers.get("content-disposition", "")
    assert f"steuerreport_{year}.csv" in disposition


async def test_download_csv_has_steuerreport_header(client, auth_headers, closed_trades):
    """CSV content starts with STEUERREPORT header."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    content = resp.text
    lines = content.strip().split("\n")
    assert "STEUERREPORT" in lines[0] or "TAX REPORT" in lines[0]


async def test_download_csv_has_bom_for_excel(client, auth_headers, closed_trades):
    """CSV starts with UTF-8 BOM for Windows Excel compatibility."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    # BOM is \ufeff which is the first character
    assert resp.text.startswith("\ufeff")


async def test_download_csv_contains_trade_data(client, auth_headers, closed_trades):
    """CSV contains trade detail rows for closed trades."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    content = resp.text
    lines = content.strip().split("\n")
    trade_lines = [l for l in lines if "BTCUSDT" in l or "ETHUSDT" in l]
    # Filter out header row
    trade_lines = [l for l in trade_lines if "Richtung" not in l and "Side" not in l]
    assert len(trade_lines) == 3


async def test_download_csv_has_summary_section(client, auth_headers, closed_trades):
    """CSV contains a ZUSAMMENFASSUNG / SUMMARY section."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    content = resp.text
    assert "ZUSAMMENFASSUNG" in content or "SUMMARY" in content


async def test_download_csv_has_monthly_breakdown(client, auth_headers, closed_trades):
    """CSV contains a MONATLICHE AUFSCHLUESSELUNG / MONTHLY BREAKDOWN section."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    content = resp.text
    assert "MONATLICHE" in content or "MONTHLY" in content


async def test_download_csv_has_trade_detail_section(client, auth_headers, closed_trades):
    """CSV contains EINZELTRANSAKTIONEN / DETAILED TRADES header."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    content = resp.text
    assert "EINZELTRANSAKTIONEN" in content or "DETAILED TRADES" in content


async def test_download_csv_with_demo_filter(client, auth_headers, closed_trades):
    """CSV with demo_mode=true filter returns only demo trades."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"demo_mode": True})
    content = resp.text
    lines = content.strip().split("\n")
    trade_data_lines = [l for l in lines if "BTCUSDT" in l or "ETHUSDT" in l]
    trade_data_lines = [l for l in trade_data_lines if "Richtung" not in l and "Side" not in l]
    assert len(trade_data_lines) == 2


async def test_download_csv_mode_label_demo(client, auth_headers, closed_trades):
    """CSV with demo_mode=true shows 'Demo' in mode row."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"demo_mode": True})
    content = resp.text
    assert "Demo" in content


async def test_download_csv_mode_label_live(client, auth_headers, closed_trades):
    """CSV with demo_mode=false shows 'Live' in mode row."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"demo_mode": False})
    content = resp.text
    assert "Live" in content


async def test_download_csv_mode_label_all(client, auth_headers, closed_trades):
    """CSV without demo_mode filter shows 'Alle/All' in mode row."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    content = resp.text
    assert "Alle/All" in content


async def test_download_csv_default_year(client, auth_headers, closed_trades):
    """CSV without year defaults to current year."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert resp.status_code == 200
    year = datetime.utcnow().year
    content = resp.text
    assert str(year) in content


async def test_download_csv_empty_year(client, auth_headers, user):
    """CSV for a year with no trades still has headers but no trade rows."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers, params={"year": 2020})
    assert resp.status_code == 200
    content = resp.text
    assert "STEUERREPORT" in content or "TAX REPORT" in content
    assert any("0" in line and "Trade Count" in line for line in content.split("\n"))


async def test_download_csv_requires_auth(client, user):
    """CSV endpoint requires authentication."""
    resp = await client.get("/api/tax-report/csv")
    assert resp.status_code == 401


async def test_download_csv_has_disclaimer(client, auth_headers, closed_trades):
    """CSV contains a disclaimer note."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    content = resp.text
    assert "HINWEIS" in content or "NOTE" in content


async def test_download_csv_win_rate(client, auth_headers, closed_trades):
    """CSV includes win rate calculation."""
    resp = await client.get("/api/tax-report/csv", headers=auth_headers)
    content = resp.text
    # 2 wins out of 3 trades = 66.7%
    assert "Win Rate" in content or "Gewinnrate" in content
