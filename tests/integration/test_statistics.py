"""
Integration tests for statistics endpoints.

Covers aggregate statistics, daily stats, demo_mode filtering,
and empty results.

Migrated from tests/test_statistics.py to tests/integration/.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
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
    now = datetime.now(timezone.utc)
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
async def test_get_statistics_empty_results(client, auth_headers, test_user_obj):
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
async def test_get_daily_stats_empty(client, auth_headers, test_user_obj):
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


@pytest.mark.asyncio
async def test_closed_trade_with_null_exit_time_still_counted(client, auth_headers, test_user_obj):
    """A closed trade with exit_time=NULL falls back to entry_time via COALESCE."""
    now = datetime.now(timezone.utc)
    trade = TradeRecord(
        user_id=test_user_obj.id,
        symbol="SOLUSDT",
        side="long",
        size=1.0,
        entry_price=150.0,
        exit_price=155.0,
        leverage=3,
        confidence=65,
        reason="Test NULL exit_time fallback",
        order_id="order_null_exit",
        status="closed",
        pnl=5.0,
        pnl_percent=3.33,
        fees=0.2,
        entry_time=now - timedelta(days=1),
        exit_time=None,
        exchange="bitget",
        demo_mode=False,
    )
    async with get_session() as session:
        session.add(trade)

    # Aggregate stats must include this trade
    response = await client.get("/api/statistics", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_trades"] == 1
    assert data["total_pnl"] == pytest.approx(5.0)

    # Daily stats must show one day entry (falling back to entry_time date)
    response = await client.get("/api/statistics/daily", headers=auth_headers)
    assert response.status_code == 200
    days = response.json()["days"]
    assert len(days) == 1
    assert days[0]["pnl"] == pytest.approx(5.0)
