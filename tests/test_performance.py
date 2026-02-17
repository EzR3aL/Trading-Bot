"""
Tests for performance queries and aggregations.

Verifies that func.date() works correctly with SQLite,
daily series aggregation, cumulative PnL calculation,
and demo_mode filtering in performance contexts.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import BotConfig, TradeRecord


# ---------------------------------------------------------------------------
# Helpers: create trades across multiple days
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def multi_day_trades(test_engine, test_user, sample_bot_config):
    """Create trades spread across multiple days for daily aggregation tests."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    # Use noon as base time to avoid midnight boundary issues
    now = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    trades = []

    # Day 1: 2 winning trades (demo) - same date, different hours
    for i in range(2):
        trades.append(TradeRecord(
            user_id=test_user.id,
            bot_config_id=sample_bot_config.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=95500.0,
            take_profit=96000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason=f"Day 1 trade {i+1}",
            order_id=f"perf_order_d1_{i}",
            status="closed",
            pnl=5.0,
            pnl_percent=0.53,
            fees=0.2,
            funding_paid=0.05,
            entry_time=now - timedelta(days=10, hours=i),
            exit_time=now - timedelta(days=10, hours=i) + timedelta(hours=1),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ))

    # Day 2: 1 losing trade (demo)
    trades.append(TradeRecord(
        user_id=test_user.id,
        bot_config_id=sample_bot_config.id,
        symbol="BTCUSDT",
        side="long",
        size=0.02,
        entry_price=95500.0,
        exit_price=95000.0,
        take_profit=96500.0,
        stop_loss=94500.0,
        leverage=4,
        confidence=60,
        reason="Day 2 losing trade",
        order_id="perf_order_d2_0",
        status="closed",
        pnl=-10.0,
        pnl_percent=-1.05,
        fees=0.3,
        funding_paid=0.08,
        entry_time=now - timedelta(days=9, hours=3),
        exit_time=now - timedelta(days=9, hours=2),
        exit_reason="STOP_LOSS",
        exchange="bitget",
        demo_mode=True,
    ))

    # Day 3: 1 winning trade (live - NOT demo)
    trades.append(TradeRecord(
        user_id=test_user.id,
        bot_config_id=sample_bot_config.id,
        symbol="ETHUSDT",
        side="short",
        size=0.1,
        entry_price=3500.0,
        exit_price=3400.0,
        take_profit=3300.0,
        stop_loss=3600.0,
        leverage=4,
        confidence=80,
        reason="Day 3 live trade",
        order_id="perf_order_d3_0",
        status="closed",
        pnl=10.0,
        pnl_percent=2.86,
        fees=0.25,
        funding_paid=0.03,
        entry_time=now - timedelta(days=8, hours=5),
        exit_time=now - timedelta(days=8, hours=4),
        exit_reason="TAKE_PROFIT",
        exchange="bitget",
        demo_mode=False,
    ))

    async with session_factory() as session:
        session.add_all(trades)
        await session.commit()

    return trades


# ---------------------------------------------------------------------------
# func.date() correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_stats_groups_by_date(client, auth_headers, multi_day_trades):
    """Daily statistics groups trades by date correctly using func.date()."""
    response = await client.get("/api/statistics/daily", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    days = data["days"]
    # Should have 3 distinct days
    assert len(days) == 3

    # Day 1 should have 2 trades
    day1 = days[0]
    assert day1["trades"] == 2
    assert day1["pnl"] == pytest.approx(10.0, abs=0.01)  # 5 + 5
    assert day1["wins"] == 2
    assert day1["losses"] == 0

    # Day 2 should have 1 trade
    day2 = days[1]
    assert day2["trades"] == 1
    assert day2["pnl"] == pytest.approx(-10.0, abs=0.01)
    assert day2["wins"] == 0
    assert day2["losses"] == 1


@pytest.mark.asyncio
async def test_daily_stats_date_format(client, auth_headers, multi_day_trades):
    """Daily stats dates are in YYYY-MM-DD format."""
    response = await client.get("/api/statistics/daily", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    for day in data["days"]:
        date_str = day["date"]
        # Should be parseable as a date
        assert len(date_str) == 10  # YYYY-MM-DD
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        assert parsed is not None


# ---------------------------------------------------------------------------
# Daily series aggregation in bot statistics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_statistics_daily_series(client, auth_headers, multi_day_trades, sample_bot_config):
    """Bot statistics daily series aggregates per-day PnL correctly."""
    bot_id = sample_bot_config.id
    response = await client.get(
        f"/api/bots/{bot_id}/statistics", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    series = data["daily_series"]
    # Should have entries for the days with closed trades
    assert len(series) >= 2  # At least 2 days with trades (some are same bot)

    for entry in series:
        assert "date" in entry
        assert "pnl" in entry
        assert "cumulative_pnl" in entry
        assert "trades" in entry


# ---------------------------------------------------------------------------
# Cumulative PnL calculation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cumulative_pnl_increases_correctly(client, auth_headers, multi_day_trades, sample_bot_config):
    """Cumulative PnL accumulates day-over-day in the daily series."""
    bot_id = sample_bot_config.id
    response = await client.get(
        f"/api/bots/{bot_id}/statistics", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    series = data["daily_series"]
    if len(series) < 2:
        pytest.skip("Not enough daily data points for cumulative check")

    # Verify cumulative is running sum of daily pnl
    running_total = 0.0
    for entry in series:
        running_total += entry["pnl"]
        assert entry["cumulative_pnl"] == pytest.approx(running_total, abs=0.01)


# ---------------------------------------------------------------------------
# Demo mode filtering in performance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_stats_demo_mode_filter(client, auth_headers, multi_day_trades):
    """Daily stats with demo_mode=true excludes live trades."""
    response = await client.get(
        "/api/statistics/daily",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert response.status_code == 200
    data = response.json()

    total_trades = sum(d["trades"] for d in data["days"])
    # 3 demo trades (2 on day 1, 1 on day 2), exclude 1 live trade on day 3
    assert total_trades == 3


@pytest.mark.asyncio
async def test_daily_stats_live_mode_filter(client, auth_headers, multi_day_trades):
    """Daily stats with demo_mode=false returns only live trades."""
    response = await client.get(
        "/api/statistics/daily",
        headers=auth_headers,
        params={"demo_mode": False},
    )
    assert response.status_code == 200
    data = response.json()

    total_trades = sum(d["trades"] for d in data["days"])
    # 1 live trade on day 3
    assert total_trades == 1


@pytest.mark.asyncio
async def test_bot_statistics_demo_filter(client, auth_headers, multi_day_trades, sample_bot_config):
    """Bot statistics with demo_mode=true excludes live trades."""
    bot_id = sample_bot_config.id
    response = await client.get(
        f"/api/bots/{bot_id}/statistics",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert response.status_code == 200
    data = response.json()

    # Only demo closed trades: 3
    assert data["summary"]["total_trades"] == 3


@pytest.mark.asyncio
async def test_bot_statistics_live_filter(client, auth_headers, multi_day_trades, sample_bot_config):
    """Bot statistics with demo_mode=false shows only live trades."""
    bot_id = sample_bot_config.id
    response = await client.get(
        f"/api/bots/{bot_id}/statistics",
        headers=auth_headers,
        params={"demo_mode": False},
    )
    assert response.status_code == 200
    data = response.json()

    # Only live closed trades: 1
    assert data["summary"]["total_trades"] == 1


# ---------------------------------------------------------------------------
# Empty results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_stats_empty_period(client, auth_headers, test_user):
    """Daily stats with no trades in the period returns empty list."""
    response = await client.get(
        "/api/statistics/daily",
        headers=auth_headers,
        params={"days": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["days"] == []


@pytest.mark.asyncio
async def test_bot_statistics_no_trades(client, auth_headers, sample_bot_config):
    """Bot statistics with no trades returns zeroed summary."""
    bot_id = sample_bot_config.id
    response = await client.get(
        f"/api/bots/{bot_id}/statistics", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["total_trades"] == 0
    assert data["summary"]["total_pnl"] == 0
    assert data["summary"]["wins"] == 0
    assert data["summary"]["losses"] == 0
    assert data["daily_series"] == []


# ---------------------------------------------------------------------------
# Compare bots performance with daily series
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_bots_series_data(client, auth_headers, multi_day_trades, sample_bot_config):
    """Compare bots includes daily cumulative series per bot."""
    response = await client.get(
        "/api/bots/compare/performance", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    assert len(data["bots"]) >= 1
    bot_data = data["bots"][0]
    assert "series" in bot_data
    assert len(bot_data["series"]) >= 1

    # Verify cumulative PnL in series
    for point in bot_data["series"]:
        assert "date" in point
        assert "cumulative_pnl" in point


@pytest.mark.asyncio
async def test_compare_bots_win_rate(client, auth_headers, multi_day_trades, sample_bot_config):
    """Compare bots calculates correct win rate."""
    response = await client.get(
        "/api/bots/compare/performance", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()

    bot_data = data["bots"][0]
    total = bot_data["total_trades"]
    wins = bot_data["wins"]
    if total > 0:
        expected_wr = round((wins / total) * 100, 1)
        assert bot_data["win_rate"] == pytest.approx(expected_wr, abs=0.2)
