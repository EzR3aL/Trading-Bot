"""
Integration tests for statistics endpoints.

Covers aggregate statistics, daily stats, demo_mode filtering,
and empty results.

Migrated from tests/test_statistics.py to tests/integration/.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_statistics_default_30_days(client, auth_headers, sample_trades):
    """Get statistics returns aggregate data for the default 30-day period."""
    response = await client.get("/api/statistics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["period_days"] == 30
    # 3 closed trades in sample data
    assert data["total_trades"] == 3
    assert data["winning_trades"] == 2
    assert data["losing_trades"] == 1
    assert data["total_pnl"] == pytest.approx(0.0, abs=0.01)  # 10 + 10 - 20 = 0
    assert "win_rate" in data
    assert "net_pnl" in data
    assert "avg_pnl_percent" in data
    assert "best_trade" in data
    assert "worst_trade" in data


@pytest.mark.asyncio
async def test_get_statistics_custom_days(client, auth_headers, sample_trades):
    """Get statistics respects the custom days parameter."""
    response = await client.get(
        "/api/statistics", headers=auth_headers, params={"days": 7}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["period_days"] == 7


@pytest.mark.asyncio
async def test_get_statistics_win_rate_calculation(client, auth_headers, sample_trades):
    """Win rate is calculated correctly."""
    response = await client.get("/api/statistics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    # 2 winners out of 3 total
    expected_win_rate = (2 / 3) * 100
    assert data["win_rate"] == pytest.approx(expected_win_rate, abs=0.1)


# ---------------------------------------------------------------------------
# Filter by demo_mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_statistics_demo_mode_true(client, auth_headers, sample_trades):
    """Statistics filtered to demo_mode=true show only demo trades."""
    response = await client.get(
        "/api/statistics", headers=auth_headers, params={"demo_mode": True}
    )
    assert response.status_code == 200
    data = response.json()

    # 2 closed demo trades in sample data (trade 1 and 2)
    assert data["total_trades"] == 2
    assert data["winning_trades"] == 2
    assert data["losing_trades"] == 0


@pytest.mark.asyncio
async def test_get_statistics_demo_mode_false(client, auth_headers, sample_trades):
    """Statistics filtered to demo_mode=false show only live trades."""
    response = await client.get(
        "/api/statistics", headers=auth_headers, params={"demo_mode": False}
    )
    assert response.status_code == 200
    data = response.json()

    # 1 closed live trade (trade 3, losing)
    assert data["total_trades"] == 1
    assert data["winning_trades"] == 0
    assert data["losing_trades"] == 1


# ---------------------------------------------------------------------------
# Empty results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_statistics_empty_results(client, auth_headers, test_user):
    """Statistics with no trades returns zeroed values."""
    response = await client.get("/api/statistics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert data["total_trades"] == 0
    assert data["winning_trades"] == 0
    assert data["losing_trades"] == 0
    assert data["total_pnl"] == 0
    assert data["win_rate"] == 0
    assert data["net_pnl"] == 0


# ---------------------------------------------------------------------------
# Daily stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_daily_stats(client, auth_headers, sample_trades):
    """Daily stats returns per-day breakdown."""
    response = await client.get("/api/statistics/daily", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert "days" in data
    assert isinstance(data["days"], list)
    # Each day entry should have the expected fields
    for day in data["days"]:
        assert "date" in day
        assert "trades" in day
        assert "pnl" in day
        assert "fees" in day
        assert "funding" in day
        assert "wins" in day
        assert "losses" in day


@pytest.mark.asyncio
async def test_get_daily_stats_with_demo_mode_filter(client, auth_headers, sample_trades):
    """Daily stats filtered by demo_mode returns only matching days."""
    response = await client.get(
        "/api/statistics/daily",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert response.status_code == 200
    data = response.json()

    assert "days" in data
    # Total trades across all days should equal demo closed trades
    total_trades = sum(d["trades"] for d in data["days"])
    assert total_trades == 2  # 2 closed demo trades


@pytest.mark.asyncio
async def test_get_daily_stats_empty(client, auth_headers, test_user):
    """Daily stats with no trades returns empty list."""
    response = await client.get("/api/statistics/daily", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["days"] == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_statistics_requires_auth(client, sample_trades):
    """Statistics endpoint requires authentication."""
    response = await client.get("/api/statistics")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_daily_stats_requires_auth(client, sample_trades):
    """Daily stats endpoint requires authentication."""
    response = await client.get("/api/statistics/daily")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_statistics_best_and_worst_trade(client, auth_headers, sample_trades):
    """Best and worst trade values are correct."""
    response = await client.get("/api/statistics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    # Best trade: +10.0 (trade 1 or 2), Worst trade: -20.0 (trade 3)
    assert data["best_trade"] == pytest.approx(10.0)
    assert data["worst_trade"] == pytest.approx(-20.0)
