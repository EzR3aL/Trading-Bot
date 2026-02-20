"""
Integration tests for multibot management endpoints.

Covers CRUD operations (create, list, get, update, delete),
bot statistics, bot comparison performance, and demo_mode filtering.

Migrated from tests/test_bots.py to tests/integration/.
"""

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Create bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_bot(client, auth_headers, test_user):
    """Creating a bot returns the bot configuration."""
    body = {
        "name": "My Test Bot",
        "description": "A bot for testing",
        "strategy_type": "test_strategy",
        "exchange_type": "bitget",
        "mode": "demo",
        "trading_pairs": ["BTCUSDT"],
        "leverage": 4,
        "position_size_percent": 7.5,
        "max_trades_per_day": 2,
        "take_profit_percent": 4.0,
        "stop_loss_percent": 1.5,
        "daily_loss_limit_percent": 5.0,
    }
    response = await client.post("/api/bots", json=body, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "My Test Bot"
    assert data["strategy_type"] == "test_strategy"
    assert data["exchange_type"] == "bitget"
    assert data["mode"] == "demo"
    assert data["trading_pairs"] == ["BTCUSDT"]
    assert data["leverage"] == 4
    assert data["is_enabled"] is False
    assert data["id"] > 0


@pytest.mark.asyncio
async def test_create_bot_with_invalid_strategy(client, auth_headers, test_user):
    """Creating a bot with an unregistered strategy returns 400."""
    body = {
        "name": "Bad Strategy Bot",
        "strategy_type": "nonexistent_strategy",
        "exchange_type": "bitget",
        "mode": "demo",
    }
    response = await client.post("/api/bots", json=body, headers=auth_headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_bot_with_invalid_exchange(client, auth_headers, test_user):
    """Creating a bot with an invalid exchange returns 422."""
    body = {
        "name": "Bad Exchange Bot",
        "strategy_type": "test_strategy",
        "exchange_type": "invalid_exchange",
        "mode": "demo",
    }
    response = await client.post("/api/bots", json=body, headers=auth_headers)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# List bots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bots(client, auth_headers, sample_bot_config):
    """List bots returns all bots for the user."""
    response = await client.get("/api/bots", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "bots" in data
    assert len(data["bots"]) >= 1

    bot = data["bots"][0]
    assert bot["name"] == "Test Bot Alpha"
    assert bot["strategy_type"] == "test_strategy"
    assert bot["exchange_type"] == "bitget"
    assert bot["mode"] == "demo"


@pytest.mark.asyncio
async def test_list_bots_empty(client, auth_headers, test_user):
    """List bots with no bots returns empty list."""
    response = await client.get("/api/bots", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["bots"] == []


@pytest.mark.asyncio
async def test_list_bots_demo_mode_filter(client, auth_headers, sample_bot_config):
    """List bots with demo_mode=true returns bots in demo or both mode."""
    response = await client.get(
        "/api/bots", headers=auth_headers, params={"demo_mode": True}
    )
    assert response.status_code == 200
    data = response.json()
    # Our sample bot is mode="demo", so it should appear
    assert len(data["bots"]) >= 1
    for bot in data["bots"]:
        assert bot["mode"] in ["demo", "both"]


@pytest.mark.asyncio
async def test_list_bots_live_mode_filter(client, auth_headers, sample_bot_config):
    """List bots with demo_mode=false returns bots in live or both mode."""
    response = await client.get(
        "/api/bots", headers=auth_headers, params={"demo_mode": False}
    )
    assert response.status_code == 200
    data = response.json()
    # Our sample bot is mode="demo", so it should NOT appear
    for bot in data["bots"]:
        assert bot["mode"] in ["live", "both"]


# ---------------------------------------------------------------------------
# Get bot by ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_bot_by_id(client, auth_headers, sample_bot_config):
    """Get a specific bot by its ID."""
    bot_id = sample_bot_config.id
    response = await client.get(f"/api/bots/{bot_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == bot_id
    assert data["name"] == "Test Bot Alpha"
    assert data["trading_pairs"] == ["BTCUSDT", "ETHUSDT"]


@pytest.mark.asyncio
async def test_get_bot_not_found(client, auth_headers, test_user):
    """Getting a nonexistent bot returns 404."""
    response = await client.get("/api/bots/99999", headers=auth_headers)
    assert response.status_code == 404
    assert "Bot not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Update bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_bot(client, auth_headers, sample_bot_config):
    """Updating a bot changes its configuration."""
    bot_id = sample_bot_config.id
    response = await client.put(
        f"/api/bots/{bot_id}",
        json={"name": "Updated Bot Name", "leverage": 8},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Bot Name"
    assert data["leverage"] == 8


@pytest.mark.asyncio
async def test_update_bot_not_found(client, auth_headers, test_user):
    """Updating a nonexistent bot returns 404."""
    response = await client.put(
        "/api/bots/99999",
        json={"name": "Ghost Bot"},
        headers=auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_bot_while_running(client, auth_headers, sample_bot_config, mock_orchestrator):
    """Updating a running bot returns 400."""
    mock_orchestrator.is_running.return_value = True
    bot_id = sample_bot_config.id
    response = await client.put(
        f"/api/bots/{bot_id}",
        json={"name": "Should Fail"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Stop the bot" in response.json()["detail"]
    # Reset mock
    mock_orchestrator.is_running.return_value = False


# ---------------------------------------------------------------------------
# Delete bot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_bot(client, auth_headers, sample_bot_config):
    """Deleting a bot removes it."""
    bot_id = sample_bot_config.id
    response = await client.delete(f"/api/bots/{bot_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # Verify it is gone
    response2 = await client.get(f"/api/bots/{bot_id}", headers=auth_headers)
    assert response2.status_code == 404


@pytest.mark.asyncio
async def test_delete_bot_not_found(client, auth_headers, test_user):
    """Deleting a nonexistent bot returns 404."""
    response = await client.delete("/api/bots/99999", headers=auth_headers)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Bot statistics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_bot_statistics(client, auth_headers, sample_bot_with_trades):
    """Get statistics for a specific bot."""
    bot_id = sample_bot_with_trades.id
    response = await client.get(
        f"/api/bots/{bot_id}/statistics", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    assert data["bot_id"] == bot_id
    assert data["bot_name"] == "Test Bot Alpha"
    assert "summary" in data
    assert "daily_series" in data
    assert "recent_trades" in data

    summary = data["summary"]
    assert summary["total_trades"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1


@pytest.mark.asyncio
async def test_get_bot_statistics_not_found(client, auth_headers, test_user):
    """Bot statistics for nonexistent bot returns 404."""
    response = await client.get("/api/bots/99999/statistics", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_bot_statistics_with_demo_mode_filter(
    client, auth_headers, sample_bot_with_trades
):
    """Bot statistics with demo_mode filter."""
    bot_id = sample_bot_with_trades.id
    response = await client.get(
        f"/api/bots/{bot_id}/statistics",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert response.status_code == 200
    data = response.json()
    # Both bot trades are demo_mode=True
    assert data["summary"]["total_trades"] == 2


@pytest.mark.asyncio
async def test_get_bot_statistics_cumulative_pnl(client, auth_headers, sample_bot_with_trades):
    """Bot statistics daily series has cumulative PnL calculation."""
    bot_id = sample_bot_with_trades.id
    response = await client.get(
        f"/api/bots/{bot_id}/statistics", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    series = data["daily_series"]
    if len(series) > 0:
        # Verify cumulative_pnl field exists
        for entry in series:
            assert "cumulative_pnl" in entry
            assert "pnl" in entry
            assert "date" in entry


# ---------------------------------------------------------------------------
# Compare bots performance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_bots_performance(client, auth_headers, sample_bot_with_trades):
    """Compare bots endpoint returns data for all user bots."""
    response = await client.get(
        "/api/bots/compare/performance", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    assert "days" in data
    assert "bots" in data
    assert len(data["bots"]) >= 1

    bot_data = data["bots"][0]
    assert "bot_id" in bot_data
    assert "name" in bot_data
    assert "total_trades" in bot_data
    assert "total_pnl" in bot_data
    assert "win_rate" in bot_data
    assert "series" in bot_data


@pytest.mark.asyncio
async def test_compare_bots_performance_with_demo_filter(
    client, auth_headers, sample_bot_with_trades
):
    """Compare bots with demo_mode filter returns filtered results."""
    response = await client.get(
        "/api/bots/compare/performance",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert response.status_code == 200
    data = response.json()

    assert "bots" in data
    # Our bot is mode="demo" so it should appear with demo_mode=True
    assert len(data["bots"]) >= 1


@pytest.mark.asyncio
async def test_compare_bots_empty(client, auth_headers, test_user):
    """Compare bots with no bots returns empty list."""
    response = await client.get(
        "/api/bots/compare/performance", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert data["bots"] == []


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bots_requires_auth(client, test_user):
    """Bots endpoints require authentication."""
    response = await client.get("/api/bots")
    assert response.status_code == 401
