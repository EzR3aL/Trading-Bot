"""
Integration tests for trade history endpoints.

Covers listing trades with pagination, filtering by status, symbol,
demo_mode, and the trade sync endpoint.

Migrated from tests/test_trades.py to tests/integration/.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


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
async def test_sync_trades_no_open_trades(client, auth_headers, test_user):
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
