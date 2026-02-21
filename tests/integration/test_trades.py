"""
Integration tests for trade history endpoints.

Covers listing trades with pagination, filtering by status, symbol,
demo_mode, and the trade sync endpoint.

Migrated from tests/test_trades.py to tests/integration/.
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.integration.conftest import auth_header

from src.models.database import TradeRecord
from src.models.session import get_session


@pytest_asyncio.fixture
async def test_user_obj(admin_token):
    """Return the admin user object created by admin_token fixture."""
    from sqlalchemy import select
    from src.models.database import User

    async with get_session() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        return result.scalar_one()


@pytest_asyncio.fixture
async def auth_headers(admin_token):
    """Build auth headers from the admin token."""
    return auth_header(admin_token)


@pytest_asyncio.fixture
async def sample_trades(test_user_obj):
    """Insert sample trade records via the monkeypatched session."""
    now = datetime.utcnow()
    trades_data = [
        TradeRecord(
            user_id=test_user_obj.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Test trade 1",
            order_id="order_001",
            status="closed",
            pnl=10.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            entry_time=now - timedelta(days=5),
            exit_time=now - timedelta(days=4),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=test_user_obj.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            exit_price=3400.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=4,
            confidence=80,
            reason="Test trade 2",
            order_id="order_002",
            status="closed",
            pnl=10.0,
            pnl_percent=2.86,
            fees=0.3,
            funding_paid=0.05,
            entry_time=now - timedelta(days=3),
            exit_time=now - timedelta(days=2),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=test_user_obj.id,
            symbol="BTCUSDT",
            side="long",
            size=0.02,
            entry_price=94000.0,
            exit_price=93000.0,
            take_profit=96000.0,
            stop_loss=93000.0,
            leverage=4,
            confidence=60,
            reason="Test trade 3 - losing",
            order_id="order_003",
            status="closed",
            pnl=-20.0,
            pnl_percent=-1.06,
            fees=0.4,
            funding_paid=0.08,
            entry_time=now - timedelta(days=2),
            exit_time=now - timedelta(days=1),
            exit_reason="STOP_LOSS",
            exchange="bitget",
            demo_mode=False,
        ),
        TradeRecord(
            user_id=test_user_obj.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95500.0,
            take_profit=97000.0,
            stop_loss=94500.0,
            leverage=4,
            confidence=70,
            reason="Test trade 4 - open",
            order_id="order_004",
            status="open",
            entry_time=now - timedelta(hours=2),
            exchange="bitget",
            demo_mode=True,
        ),
    ]

    async with get_session() as session:
        session.add_all(trades_data)

    return trades_data


# ---------------------------------------------------------------------------
# List trades
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trades_returns_all(client, auth_headers, sample_trades):
    """List trades returns all trades for the user."""
    response = await client.get("/api/trades", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4
    assert len(data["trades"]) == 4
    assert data["page"] == 1
    assert data["per_page"] == 50


@pytest.mark.asyncio
async def test_list_trades_pagination(client, auth_headers, sample_trades):
    """List trades respects pagination parameters."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"per_page": 2, "page": 1}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["trades"]) == 2
    assert data["total"] == 4
    assert data["page"] == 1
    assert data["per_page"] == 2


@pytest.mark.asyncio
async def test_list_trades_pagination_page_2(client, auth_headers, sample_trades):
    """List trades returns correct results for page 2."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"per_page": 2, "page": 2}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["trades"]) == 2
    assert data["total"] == 4
    assert data["page"] == 2


# ---------------------------------------------------------------------------
# Filter by status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trades_filter_by_status_closed(client, auth_headers, sample_trades):
    """Filter by status=closed returns only closed trades."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"status": "closed"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    for trade in data["trades"]:
        assert trade["status"] == "closed"


@pytest.mark.asyncio
async def test_list_trades_filter_by_status_open(client, auth_headers, sample_trades):
    """Filter by status=open returns only open trades."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"status": "open"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["trades"][0]["status"] == "open"


# ---------------------------------------------------------------------------
# Filter by symbol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trades_filter_by_symbol(client, auth_headers, sample_trades):
    """Filter by symbol returns only matching trades."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"symbol": "ETHUSDT"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["trades"][0]["symbol"] == "ETHUSDT"


@pytest.mark.asyncio
async def test_list_trades_filter_by_symbol_btcusdt(client, auth_headers, sample_trades):
    """Filter by symbol=BTCUSDT returns only BTC trades."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"symbol": "BTCUSDT"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    for trade in data["trades"]:
        assert trade["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# Filter by demo_mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trades_filter_demo_mode_true(client, auth_headers, sample_trades):
    """Filter by demo_mode=true returns only demo trades."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"demo_mode": True}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    for trade in data["trades"]:
        assert trade["demo_mode"] is True


@pytest.mark.asyncio
async def test_list_trades_filter_demo_mode_false(client, auth_headers, sample_trades):
    """Filter by demo_mode=false returns only live trades."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"demo_mode": False}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    for trade in data["trades"]:
        assert trade["demo_mode"] is False


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trades_combined_filters(client, auth_headers, sample_trades):
    """Combined filters (status + symbol) work correctly."""
    response = await client.get(
        "/api/trades",
        headers=auth_headers,
        params={"status": "closed", "symbol": "BTCUSDT"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    for trade in data["trades"]:
        assert trade["status"] == "closed"
        assert trade["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# Get single trade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trade_by_id(client, auth_headers, sample_trades):
    """Get a specific trade by its ID."""
    trade_id = sample_trades[0].id
    response = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == trade_id
    assert data["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_get_trade_not_found(client, auth_headers, sample_trades):
    """Getting a nonexistent trade returns 404."""
    response = await client.get("/api/trades/99999", headers=auth_headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Trade sync endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_trades_no_open_trades(client, auth_headers, test_user_obj):
    """Sync with no open trades returns synced=0."""
    response = await client.post("/api/trades/sync", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["synced"] == 0
    assert data["closed_trades"] == []


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trades_requires_auth(client, sample_trades):
    """Accessing trades without auth returns 401."""
    response = await client.get("/api/trades")
    assert response.status_code == 401
