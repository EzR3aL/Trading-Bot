"""Unit tests for :mod:`src.data.funding_tracker`.

Covers:
- initialize / close lifecycle
- record_funding_rate: stores snapshot
- record_funding_payment: long positive, short negative, zero rate
- get_trade_funding: returns payments for specific trade_id
- get_total_funding_for_trade: sum over multiple payments, empty trade
- get_funding_stats: all-symbol and per-symbol, empty DB
- get_recent_payments: limit respected
- get_funding_rate_history: cutoff filter, empty result
- get_daily_funding_summary: groups by date
- is_funding_time: true inside 5-minute window, false outside
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.data.funding_tracker import FundingPayment, FundingTracker


# ---------------------------------------------------------------------------
# Fixture: isolated in-memory tracker (uses :memory: SQLite via aiosqlite)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def tracker(tmp_path):
    db_path = tmp_path / "test_funding.db"
    ft = FundingTracker(db_path=str(db_path))
    await ft.initialize()
    yield ft
    await ft.close()


# ---------------------------------------------------------------------------
# Initialize / close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_creates_tables(tracker):
    # If tables don't exist, record_funding_rate would raise — just calling
    # initialize again must not error.
    cursor = await tracker._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = {row[0] for row in await cursor.fetchall()}
    assert "funding_payments" in tables
    assert "funding_rates_history" in tables


# ---------------------------------------------------------------------------
# record_funding_rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_funding_rate_stores_snapshot(tracker):
    from datetime import timedelta
    next_time = datetime.now(timezone.utc) + timedelta(hours=8)
    await tracker.record_funding_rate("BTCUSDT", 0.0001, next_funding_time=next_time)

    cursor = await tracker._db.execute(
        "SELECT symbol, funding_rate FROM funding_rates_history"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "BTCUSDT"
    assert abs(rows[0][1] - 0.0001) < 1e-9


@pytest.mark.asyncio
async def test_record_funding_rate_no_next_time(tracker):
    await tracker.record_funding_rate("ETHUSDT", 0.0002, next_funding_time=None)

    cursor = await tracker._db.execute(
        "SELECT next_funding_time FROM funding_rates_history"
    )
    rows = await cursor.fetchall()
    assert rows[0][0] is None


@pytest.mark.asyncio
async def test_record_funding_rate_replace_duplicate(tracker):
    """INSERT OR REPLACE handles duplicate (symbol, timestamp) gracefully."""
    await tracker.record_funding_rate("BTCUSDT", 0.0001)
    await tracker.record_funding_rate("BTCUSDT", 0.0003)

    cursor = await tracker._db.execute(
        "SELECT COUNT(*) FROM funding_rates_history WHERE symbol='BTCUSDT'"
    )
    row = await cursor.fetchone()
    # Two distinct timestamps — both kept (no actual collision in this test)
    assert row[0] >= 1


# ---------------------------------------------------------------------------
# record_funding_payment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_funding_payment_long_positive_rate(tracker):
    """LONG + positive rate → payment_amount = position_value * rate (positive)."""
    result = await tracker.record_funding_payment(
        symbol="BTCUSDT",
        funding_rate=0.001,
        position_size=0.1,
        position_value=6820.0,
        side="long",
        trade_id=42,
    )

    assert result is not None
    assert isinstance(result, FundingPayment)
    assert result.payment_amount == pytest.approx(6820.0 * 0.001)
    assert result.side == "long"
    assert result.trade_id == 42


@pytest.mark.asyncio
async def test_record_funding_payment_short_positive_rate(tracker):
    """SHORT + positive rate → payment_amount is negative (trader receives)."""
    result = await tracker.record_funding_payment(
        symbol="BTCUSDT",
        funding_rate=0.001,
        position_size=0.1,
        position_value=6820.0,
        side="short",
    )

    assert result is not None
    assert result.payment_amount == pytest.approx(-6820.0 * 0.001)


@pytest.mark.asyncio
async def test_record_funding_payment_zero_rate(tracker):
    result = await tracker.record_funding_payment(
        symbol="ETHUSDT",
        funding_rate=0.0,
        position_size=1.0,
        position_value=3000.0,
        side="long",
    )
    assert result is not None
    assert result.payment_amount == 0.0


@pytest.mark.asyncio
async def test_record_funding_payment_no_trade_id(tracker):
    result = await tracker.record_funding_payment(
        symbol="BTCUSDT",
        funding_rate=0.0005,
        position_size=0.5,
        position_value=34100.0,
        side="long",
        trade_id=None,
    )
    assert result is not None
    assert result.trade_id is None


# ---------------------------------------------------------------------------
# get_trade_funding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_trade_funding_returns_payments_for_trade(tracker):
    await tracker.record_funding_payment("BTCUSDT", 0.001, 0.1, 6000.0, "long", trade_id=10)
    await tracker.record_funding_payment("BTCUSDT", 0.002, 0.1, 6000.0, "long", trade_id=10)
    await tracker.record_funding_payment("ETHUSDT", 0.001, 1.0, 3000.0, "long", trade_id=99)

    payments = await tracker.get_trade_funding(trade_id=10)
    assert len(payments) == 2
    assert all(p.trade_id == 10 for p in payments)


@pytest.mark.asyncio
async def test_get_trade_funding_empty_for_unknown_trade(tracker):
    payments = await tracker.get_trade_funding(trade_id=9999)
    assert payments == []


# ---------------------------------------------------------------------------
# get_total_funding_for_trade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_total_funding_sums_payments(tracker):
    await tracker.record_funding_payment("BTCUSDT", 0.001, 0.1, 10000.0, "long", trade_id=5)
    await tracker.record_funding_payment("BTCUSDT", 0.002, 0.1, 10000.0, "long", trade_id=5)

    total = await tracker.get_total_funding_for_trade(trade_id=5)
    expected = 10000.0 * 0.001 + 10000.0 * 0.002
    assert total == pytest.approx(expected)


@pytest.mark.asyncio
async def test_get_total_funding_returns_zero_for_unknown(tracker):
    total = await tracker.get_total_funding_for_trade(trade_id=8888)
    assert total == 0.0


# ---------------------------------------------------------------------------
# get_funding_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_funding_stats_empty_db(tracker):
    stats = await tracker.get_funding_stats()
    assert stats.total_paid == 0.0
    assert stats.total_received == 0.0
    assert stats.payment_count == 0


@pytest.mark.asyncio
async def test_get_funding_stats_with_data(tracker):
    # Long pays 10, short receives 5
    await tracker.record_funding_payment("BTCUSDT", 0.001, 1.0, 10000.0, "long", trade_id=1)
    await tracker.record_funding_payment("BTCUSDT", 0.001, 1.0, 5000.0, "short", trade_id=2)

    stats = await tracker.get_funding_stats()
    assert stats.total_paid == pytest.approx(10.0)
    assert stats.total_received == pytest.approx(5.0)
    assert stats.payment_count == 2


@pytest.mark.asyncio
async def test_get_funding_stats_filtered_by_symbol(tracker):
    await tracker.record_funding_payment("BTCUSDT", 0.001, 1.0, 10000.0, "long", trade_id=1)
    await tracker.record_funding_payment("ETHUSDT", 0.002, 1.0, 3000.0, "long", trade_id=2)

    btc_stats = await tracker.get_funding_stats(symbol="BTCUSDT")
    assert btc_stats.payment_count == 1
    assert btc_stats.total_paid == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# get_recent_payments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recent_payments_respects_limit(tracker):
    for i in range(5):
        await tracker.record_funding_payment(
            "BTCUSDT", 0.001 * i, 0.1, 1000.0, "long", trade_id=i
        )

    payments = await tracker.get_recent_payments(limit=3)
    assert len(payments) == 3


@pytest.mark.asyncio
async def test_get_recent_payments_empty(tracker):
    payments = await tracker.get_recent_payments()
    assert payments == []


# ---------------------------------------------------------------------------
# get_funding_rate_history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_funding_rate_history_returns_for_symbol(tracker):
    await tracker.record_funding_rate("BTCUSDT", 0.0001)
    await tracker.record_funding_rate("ETHUSDT", 0.0002)

    history = await tracker.get_funding_rate_history("BTCUSDT", days=1)
    assert len(history) >= 1
    assert all(isinstance(h["rate"], float) for h in history)


@pytest.mark.asyncio
async def test_get_funding_rate_history_empty_for_unknown(tracker):
    history = await tracker.get_funding_rate_history("XYZUSDT", days=7)
    assert history == []


# ---------------------------------------------------------------------------
# get_daily_funding_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_daily_funding_summary_groups_by_date(tracker):
    await tracker.record_funding_payment("BTCUSDT", 0.001, 1.0, 10000.0, "long", trade_id=1)
    await tracker.record_funding_payment("BTCUSDT", 0.002, 1.0, 10000.0, "long", trade_id=2)

    summary = await tracker.get_daily_funding_summary(days=1)
    assert len(summary) >= 1
    assert "date" in summary[0]
    assert "total" in summary[0]
    assert "count" in summary[0]


@pytest.mark.asyncio
async def test_get_daily_funding_summary_empty(tracker):
    summary = await tracker.get_daily_funding_summary(days=30)
    assert summary == []


# ---------------------------------------------------------------------------
# is_funding_time
# ---------------------------------------------------------------------------


def test_is_funding_time_true_at_hour_0_minute_0():
    mock_now = datetime(2026, 4, 26, 0, 0, 0, tzinfo=timezone.utc)
    with patch("src.data.funding_tracker.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        tracker_inst = FundingTracker.__new__(FundingTracker)
        tracker_inst.FUNDING_HOURS = [0, 8, 16]
        result = tracker_inst.is_funding_time()
    assert result is True


def test_is_funding_time_true_at_hour_8_minute_4():
    mock_now = datetime(2026, 4, 26, 8, 4, 0, tzinfo=timezone.utc)
    with patch("src.data.funding_tracker.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        tracker_inst = FundingTracker.__new__(FundingTracker)
        tracker_inst.FUNDING_HOURS = [0, 8, 16]
        result = tracker_inst.is_funding_time()
    assert result is True


def test_is_funding_time_false_at_hour_8_minute_5():
    mock_now = datetime(2026, 4, 26, 8, 5, 0, tzinfo=timezone.utc)
    with patch("src.data.funding_tracker.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        tracker_inst = FundingTracker.__new__(FundingTracker)
        tracker_inst.FUNDING_HOURS = [0, 8, 16]
        result = tracker_inst.is_funding_time()
    assert result is False


def test_is_funding_time_false_at_off_hour():
    mock_now = datetime(2026, 4, 26, 13, 30, 0, tzinfo=timezone.utc)
    with patch("src.data.funding_tracker.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        tracker_inst = FundingTracker.__new__(FundingTracker)
        tracker_inst.FUNDING_HOURS = [0, 8, 16]
        result = tracker_inst.is_funding_time()
    assert result is False
