"""
Unit tests for src.data.funding_tracker module.

Tests cover:
- FundingPayment dataclass creation and to_dict conversion
- FundingStats dataclass creation
- FundingTracker.__init__ (default and custom db_path)
- FundingTracker.initialize (DB connect, PRAGMA, table creation)
- FundingTracker.close (connection cleanup)
- FundingTracker.record_funding_rate (happy path and error)
- FundingTracker.record_funding_payment (long, short, error path)
- FundingTracker.get_trade_funding (with results and empty)
- FundingTracker.get_total_funding_for_trade (with data, empty, None row)
- FundingTracker.get_funding_stats (with symbol, without symbol, empty data)
- FundingTracker.get_recent_payments (default limit, custom limit, empty)
- FundingTracker.get_funding_rate_history (with data, empty)
- FundingTracker.is_funding_time (at funding time, outside funding time)
- FundingTracker.get_daily_funding_summary (with data, empty)

All aiosqlite interactions are mocked so no real database is used.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data.funding_tracker import FundingPayment, FundingStats, FundingTracker


# ---------------------------------------------------------------------------
# Helpers: mock aiosqlite connection and cursor
# ---------------------------------------------------------------------------

def make_mock_cursor(lastrowid=None, fetchone_result=None, fetchall_result=None):
    """Build a mock cursor returned by db.execute(...)."""
    cursor = AsyncMock()
    cursor.lastrowid = lastrowid
    cursor.fetchone = AsyncMock(return_value=fetchone_result)
    cursor.fetchall = AsyncMock(return_value=fetchall_result or [])
    return cursor


def make_mock_db(cursor=None):
    """Build a mock aiosqlite connection."""
    if cursor is None:
        cursor = make_mock_cursor()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=cursor)
    db.commit = AsyncMock()
    db.close = AsyncMock()
    return db


# ============================================================================
# FundingPayment dataclass tests
# ============================================================================

class TestFundingPayment:
    """Tests for the FundingPayment dataclass."""

    def test_creation_with_all_fields(self):
        # Arrange / Act
        payment = FundingPayment(
            id=1,
            symbol="BTCUSDT",
            timestamp=datetime(2025, 6, 1, 8, 0, 0),
            funding_rate=0.0001,
            position_size=0.5,
            position_value=47500.0,
            payment_amount=4.75,
            side="long",
            trade_id=10,
        )

        # Assert
        assert payment.id == 1
        assert payment.symbol == "BTCUSDT"
        assert payment.timestamp == datetime(2025, 6, 1, 8, 0, 0)
        assert payment.funding_rate == 0.0001
        assert payment.position_size == 0.5
        assert payment.position_value == 47500.0
        assert payment.payment_amount == 4.75
        assert payment.side == "long"
        assert payment.trade_id == 10

    def test_creation_with_optional_none_fields(self):
        # Arrange / Act
        payment = FundingPayment(
            id=None,
            symbol="ETHUSDT",
            timestamp=datetime(2025, 6, 1, 0, 0, 0),
            funding_rate=-0.0002,
            position_size=1.0,
            position_value=3500.0,
            payment_amount=-0.70,
            side="short",
            trade_id=None,
        )

        # Assert
        assert payment.id is None
        assert payment.trade_id is None

    def test_to_dict_returns_all_fields(self):
        # Arrange
        ts = datetime(2025, 6, 1, 8, 0, 0)
        payment = FundingPayment(
            id=1,
            symbol="BTCUSDT",
            timestamp=ts,
            funding_rate=0.0001,
            position_size=0.5,
            position_value=47500.0,
            payment_amount=4.75,
            side="long",
            trade_id=10,
        )

        # Act
        d = payment.to_dict()

        # Assert
        assert d["id"] == 1
        assert d["symbol"] == "BTCUSDT"
        assert d["timestamp"] == ts.isoformat()
        assert d["funding_rate"] == 0.0001
        assert d["position_size"] == 0.5
        assert d["position_value"] == 47500.0
        assert d["payment_amount"] == 4.75
        assert d["side"] == "long"
        assert d["trade_id"] == 10

    def test_to_dict_timestamp_is_isoformat(self):
        # Arrange
        ts = datetime(2025, 12, 31, 23, 59, 59)
        payment = FundingPayment(
            id=2,
            symbol="ETHUSDT",
            timestamp=ts,
            funding_rate=0.0005,
            position_size=1.0,
            position_value=3500.0,
            payment_amount=1.75,
            side="short",
            trade_id=None,
        )

        # Act
        d = payment.to_dict()

        # Assert
        assert d["timestamp"] == "2025-12-31T23:59:59"
        assert isinstance(d["timestamp"], str)

    def test_to_dict_none_values_preserved(self):
        # Arrange
        payment = FundingPayment(
            id=None,
            symbol="BTCUSDT",
            timestamp=datetime(2025, 1, 1),
            funding_rate=0.0,
            position_size=0.0,
            position_value=0.0,
            payment_amount=0.0,
            side="long",
            trade_id=None,
        )

        # Act
        d = payment.to_dict()

        # Assert
        assert d["id"] is None
        assert d["trade_id"] is None


# ============================================================================
# FundingStats dataclass tests
# ============================================================================

class TestFundingStats:
    """Tests for the FundingStats dataclass."""

    def test_creation(self):
        # Arrange / Act
        stats = FundingStats(
            total_paid=50.0,
            total_received=20.0,
            net_funding=30.0,
            payment_count=10,
            avg_rate=0.0001,
            highest_rate=0.001,
            lowest_rate=-0.0005,
        )

        # Assert
        assert stats.total_paid == 50.0
        assert stats.total_received == 20.0
        assert stats.net_funding == 30.0
        assert stats.payment_count == 10
        assert stats.avg_rate == 0.0001
        assert stats.highest_rate == 0.001
        assert stats.lowest_rate == -0.0005

    def test_creation_with_zeros(self):
        # Arrange / Act
        stats = FundingStats(
            total_paid=0.0,
            total_received=0.0,
            net_funding=0.0,
            payment_count=0,
            avg_rate=0.0,
            highest_rate=0.0,
            lowest_rate=0.0,
        )

        # Assert
        assert stats.payment_count == 0
        assert stats.net_funding == 0.0


# ============================================================================
# FundingTracker.__init__ tests
# ============================================================================

class TestFundingTrackerInit:
    """Tests for FundingTracker constructor."""

    @patch("src.data.funding_tracker.Path.mkdir")
    def test_default_db_path(self, mock_mkdir):
        # Act
        tracker = FundingTracker()

        # Assert
        assert tracker.db_path == Path("data/funding_tracker.db")
        assert tracker._db is None

    @patch("src.data.funding_tracker.Path.mkdir")
    def test_custom_db_path(self, mock_mkdir):
        # Act
        tracker = FundingTracker(db_path="custom/path/funding.db")

        # Assert
        assert tracker.db_path == Path("custom/path/funding.db")

    @patch("src.data.funding_tracker.Path.mkdir")
    def test_creates_parent_directory(self, mock_mkdir):
        # Act
        FundingTracker(db_path="some/nested/dir/funding.db")

        # Assert
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)


# ============================================================================
# FundingTracker.initialize tests
# ============================================================================

class TestFundingTrackerInitialize:
    """Tests for the initialize method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.aiosqlite")
    async def test_initialize_connects_to_database(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect = AsyncMock(return_value=mock_db)

        tracker = FundingTracker()

        # Act
        await tracker.initialize()

        # Assert
        mock_aiosqlite.connect.assert_awaited_once_with(tracker.db_path)
        assert tracker._db is mock_db

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.aiosqlite")
    async def test_initialize_sets_wal_mode(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect = AsyncMock(return_value=mock_db)

        tracker = FundingTracker()

        # Act
        await tracker.initialize()

        # Assert
        calls = mock_db.execute.call_args_list
        sql_calls = [call[0][0] for call in calls]
        assert any("PRAGMA journal_mode=WAL" in sql for sql in sql_calls)

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.aiosqlite")
    async def test_initialize_sets_busy_timeout(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect = AsyncMock(return_value=mock_db)

        tracker = FundingTracker()

        # Act
        await tracker.initialize()

        # Assert
        calls = mock_db.execute.call_args_list
        sql_calls = [call[0][0] for call in calls]
        assert any("PRAGMA busy_timeout=5000" in sql for sql in sql_calls)

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.aiosqlite")
    async def test_initialize_creates_tables_and_indexes(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect = AsyncMock(return_value=mock_db)

        tracker = FundingTracker()

        # Act
        await tracker.initialize()

        # Assert - 2 PRAGMAs + 2 CREATE TABLEs + 2 CREATE INDEXes = 6 execute calls
        assert mock_db.execute.call_count == 6
        mock_db.commit.assert_awaited_once()

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.aiosqlite")
    async def test_initialize_creates_funding_payments_table(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect = AsyncMock(return_value=mock_db)

        tracker = FundingTracker()

        # Act
        await tracker.initialize()

        # Assert
        calls = mock_db.execute.call_args_list
        sql_calls = [call[0][0] for call in calls]
        assert any("funding_payments" in sql and "CREATE TABLE" in sql for sql in sql_calls)

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.aiosqlite")
    async def test_initialize_creates_funding_rates_history_table(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect = AsyncMock(return_value=mock_db)

        tracker = FundingTracker()

        # Act
        await tracker.initialize()

        # Assert
        calls = mock_db.execute.call_args_list
        sql_calls = [call[0][0] for call in calls]
        assert any("funding_rates_history" in sql and "CREATE TABLE" in sql for sql in sql_calls)


# ============================================================================
# FundingTracker.close tests
# ============================================================================

class TestFundingTrackerClose:
    """Tests for the close method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_close_with_active_connection(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        mock_db = make_mock_db()
        tracker._db = mock_db

        # Act
        await tracker.close()

        # Assert
        mock_db.close.assert_awaited_once()

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_close_without_connection(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        tracker._db = None

        # Act - should not raise
        await tracker.close()

        # Assert - no exception raised


# ============================================================================
# FundingTracker.record_funding_rate tests
# ============================================================================

class TestRecordFundingRate:
    """Tests for record_funding_rate method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_rate_happy_path(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        mock_db = make_mock_db()
        tracker._db = mock_db

        # Act
        await tracker.record_funding_rate(
            symbol="BTCUSDT",
            funding_rate=0.0001,
        )

        # Assert
        mock_db.execute.assert_awaited_once()
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "INSERT OR REPLACE INTO funding_rates_history" in sql
        assert params[0] == "BTCUSDT"
        assert params[2] == 0.0001
        assert params[3] is None  # no next_funding_time
        mock_db.commit.assert_awaited_once()

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_rate_with_next_funding_time(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        mock_db = make_mock_db()
        tracker._db = mock_db
        next_time = datetime(2025, 6, 1, 16, 0, 0)

        # Act
        await tracker.record_funding_rate(
            symbol="ETHUSDT",
            funding_rate=-0.0002,
            next_funding_time=next_time,
        )

        # Assert
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params[0] == "ETHUSDT"
        assert params[2] == -0.0002
        assert params[3] == next_time.isoformat()

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_rate_handles_db_error(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        mock_db = make_mock_db()
        mock_db.execute = AsyncMock(side_effect=Exception("DB write error"))
        tracker._db = mock_db

        # Act - should not raise, error is caught internally
        await tracker.record_funding_rate(
            symbol="BTCUSDT",
            funding_rate=0.0001,
        )

        # Assert - no exception raised, commit not called
        mock_db.commit.assert_not_awaited()


# ============================================================================
# FundingTracker.record_funding_payment tests
# ============================================================================

class TestRecordFundingPayment:
    """Tests for record_funding_payment method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_long_positive_rate(self, mock_mkdir):
        # Arrange - long + positive rate = positive payment (paid)
        tracker = FundingTracker()
        mock_cursor = make_mock_cursor(lastrowid=1)
        mock_db = make_mock_db(cursor=mock_cursor)
        tracker._db = mock_db

        # Act
        payment = await tracker.record_funding_payment(
            symbol="BTCUSDT",
            funding_rate=0.0001,
            position_size=0.5,
            position_value=47500.0,
            side="long",
            trade_id=10,
        )

        # Assert
        assert payment is not None
        assert payment.id == 1
        assert payment.symbol == "BTCUSDT"
        assert payment.funding_rate == 0.0001
        assert payment.position_size == 0.5
        assert payment.position_value == 47500.0
        assert payment.payment_amount == pytest.approx(47500.0 * 0.0001)
        assert payment.side == "long"
        assert payment.trade_id == 10
        mock_db.commit.assert_awaited_once()

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_long_negative_rate(self, mock_mkdir):
        # Arrange - long + negative rate = negative payment (received)
        tracker = FundingTracker()
        mock_cursor = make_mock_cursor(lastrowid=2)
        mock_db = make_mock_db(cursor=mock_cursor)
        tracker._db = mock_db

        # Act
        payment = await tracker.record_funding_payment(
            symbol="BTCUSDT",
            funding_rate=-0.0002,
            position_size=0.5,
            position_value=47500.0,
            side="long",
        )

        # Assert
        assert payment is not None
        assert payment.payment_amount == pytest.approx(47500.0 * -0.0002)
        assert payment.payment_amount < 0  # received money

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_short_positive_rate(self, mock_mkdir):
        # Arrange - short + positive rate = negative payment (received)
        tracker = FundingTracker()
        mock_cursor = make_mock_cursor(lastrowid=3)
        mock_db = make_mock_db(cursor=mock_cursor)
        tracker._db = mock_db

        # Act
        payment = await tracker.record_funding_payment(
            symbol="ETHUSDT",
            funding_rate=0.0001,
            position_size=1.0,
            position_value=3500.0,
            side="short",
        )

        # Assert
        assert payment is not None
        assert payment.payment_amount == pytest.approx(-3500.0 * 0.0001)
        assert payment.payment_amount < 0  # shorts receive when rate positive

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_short_negative_rate(self, mock_mkdir):
        # Arrange - short + negative rate = positive payment (paid)
        tracker = FundingTracker()
        mock_cursor = make_mock_cursor(lastrowid=4)
        mock_db = make_mock_db(cursor=mock_cursor)
        tracker._db = mock_db

        # Act
        payment = await tracker.record_funding_payment(
            symbol="ETHUSDT",
            funding_rate=-0.0003,
            position_size=1.0,
            position_value=3500.0,
            side="SHORT",  # Test uppercase normalization
        )

        # Assert
        assert payment is not None
        assert payment.payment_amount == pytest.approx(-3500.0 * -0.0003)
        assert payment.payment_amount > 0  # shorts pay when rate negative
        assert payment.side == "short"  # normalized to lowercase

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_side_normalized_to_lowercase(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        mock_cursor = make_mock_cursor(lastrowid=5)
        mock_db = make_mock_db(cursor=mock_cursor)
        tracker._db = mock_db

        # Act
        payment = await tracker.record_funding_payment(
            symbol="BTCUSDT",
            funding_rate=0.0001,
            position_size=0.5,
            position_value=47500.0,
            side="LONG",
        )

        # Assert
        assert payment.side == "long"

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_without_trade_id(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        mock_cursor = make_mock_cursor(lastrowid=6)
        mock_db = make_mock_db(cursor=mock_cursor)
        tracker._db = mock_db

        # Act
        payment = await tracker.record_funding_payment(
            symbol="BTCUSDT",
            funding_rate=0.0001,
            position_size=0.5,
            position_value=47500.0,
            side="long",
        )

        # Assert
        assert payment is not None
        assert payment.trade_id is None

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_inserts_correct_params(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        mock_cursor = make_mock_cursor(lastrowid=7)
        mock_db = make_mock_db(cursor=mock_cursor)
        tracker._db = mock_db

        # Act
        await tracker.record_funding_payment(
            symbol="BTCUSDT",
            funding_rate=0.0001,
            position_size=0.5,
            position_value=47500.0,
            side="long",
            trade_id=42,
        )

        # Assert
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "INSERT INTO funding_payments" in sql
        assert params[0] == "BTCUSDT"
        # params[1] is timestamp ISO string
        assert params[2] == 0.0001
        assert params[3] == 0.5
        assert params[4] == 47500.0
        assert params[5] == pytest.approx(47500.0 * 0.0001)
        assert params[6] == "long"
        assert params[7] == 42

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_handles_db_error(self, mock_mkdir):
        # Arrange
        tracker = FundingTracker()
        mock_db = make_mock_db()
        mock_db.execute = AsyncMock(side_effect=Exception("DB insert error"))
        tracker._db = mock_db

        # Act
        result = await tracker.record_funding_payment(
            symbol="BTCUSDT",
            funding_rate=0.0001,
            position_size=0.5,
            position_value=47500.0,
            side="long",
        )

        # Assert
        assert result is None

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_record_funding_payment_zero_rate(self, mock_mkdir):
        # Arrange - zero funding rate should produce zero payment
        tracker = FundingTracker()
        mock_cursor = make_mock_cursor(lastrowid=8)
        mock_db = make_mock_db(cursor=mock_cursor)
        tracker._db = mock_db

        # Act
        payment = await tracker.record_funding_payment(
            symbol="BTCUSDT",
            funding_rate=0.0,
            position_size=0.5,
            position_value=47500.0,
            side="long",
        )

        # Assert
        assert payment is not None
        assert payment.payment_amount == 0.0


# ============================================================================
# FundingTracker.get_trade_funding tests
# ============================================================================

class TestGetTradeFunding:
    """Tests for get_trade_funding method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_trade_funding_with_results(self, mock_mkdir):
        # Arrange
        rows = [
            (1, "BTCUSDT", "2025-06-01T08:00:00", 0.0001, 0.5, 47500.0, 4.75, "long", 10),
            (2, "BTCUSDT", "2025-06-01T16:00:00", 0.00015, 0.5, 47600.0, 7.14, "long", 10),
        ]
        mock_cursor = make_mock_cursor(fetchall_result=rows)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        payments = await tracker.get_trade_funding(trade_id=10)

        # Assert
        assert len(payments) == 2
        assert payments[0].id == 1
        assert payments[0].symbol == "BTCUSDT"
        assert payments[0].timestamp == datetime.fromisoformat("2025-06-01T08:00:00")
        assert payments[0].funding_rate == 0.0001
        assert payments[0].position_size == 0.5
        assert payments[0].position_value == 47500.0
        assert payments[0].payment_amount == 4.75
        assert payments[0].side == "long"
        assert payments[0].trade_id == 10

        assert payments[1].id == 2
        assert payments[1].payment_amount == 7.14

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_trade_funding_empty_results(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        payments = await tracker.get_trade_funding(trade_id=999)

        # Assert
        assert payments == []

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_trade_funding_queries_correct_trade_id(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_trade_funding(trade_id=42)

        # Assert
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "WHERE trade_id = ?" in sql
        assert params == (42,)


# ============================================================================
# FundingTracker.get_total_funding_for_trade tests
# ============================================================================

class TestGetTotalFundingForTrade:
    """Tests for get_total_funding_for_trade method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_total_funding_with_data(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchone_result=(15.50,))
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        total = await tracker.get_total_funding_for_trade(trade_id=10)

        # Assert
        assert total == 15.50

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_total_funding_zero_when_no_payments(self, mock_mkdir):
        # Arrange - COALESCE returns 0 when no matching rows
        mock_cursor = make_mock_cursor(fetchone_result=(0,))
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        total = await tracker.get_total_funding_for_trade(trade_id=999)

        # Assert
        assert total == 0.0

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_total_funding_none_row_returns_zero(self, mock_mkdir):
        # Arrange - fetchone returns None
        mock_cursor = make_mock_cursor(fetchone_result=None)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        total = await tracker.get_total_funding_for_trade(trade_id=999)

        # Assert
        assert total == 0.0

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_total_funding_negative_value(self, mock_mkdir):
        # Arrange - net negative means received more than paid
        mock_cursor = make_mock_cursor(fetchone_result=(-8.25,))
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        total = await tracker.get_total_funding_for_trade(trade_id=5)

        # Assert
        assert total == -8.25

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_total_funding_queries_correct_trade_id(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchone_result=(0,))
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_total_funding_for_trade(trade_id=77)

        # Assert
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params == (77,)


# ============================================================================
# FundingTracker.get_funding_stats tests
# ============================================================================

class TestGetFundingStats:
    """Tests for get_funding_stats method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_stats_without_symbol(self, mock_mkdir):
        # Arrange
        stats_row = (50.0, 20.0, 30.0, 10, 0.0001, 0.001, -0.0005)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        stats = await tracker.get_funding_stats(days=30)

        # Assert
        assert isinstance(stats, FundingStats)
        assert stats.total_paid == 50.0
        assert stats.total_received == 20.0
        assert stats.net_funding == 30.0
        assert stats.payment_count == 10
        assert stats.avg_rate == 0.0001
        assert stats.highest_rate == 0.001
        assert stats.lowest_rate == -0.0005

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_stats_with_symbol(self, mock_mkdir):
        # Arrange
        stats_row = (25.0, 10.0, 15.0, 5, 0.00015, 0.0008, -0.0003)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        stats = await tracker.get_funding_stats(symbol="BTCUSDT", days=7)

        # Assert
        assert stats.total_paid == 25.0
        assert stats.payment_count == 5

        # Verify symbol was passed to query
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert "BTCUSDT" in params

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_stats_with_symbol_uses_different_query(self, mock_mkdir):
        # Arrange
        stats_row = (0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_funding_stats(symbol="BTCUSDT", days=30)

        # Assert - query should contain WHERE symbol = ?
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        assert "WHERE symbol = ?" in sql

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_stats_without_symbol_no_symbol_filter(self, mock_mkdir):
        # Arrange
        stats_row = (0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_funding_stats(days=30)

        # Assert - query should not contain WHERE symbol
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        assert "WHERE symbol" not in sql
        assert "WHERE timestamp" in sql

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_stats_none_values_default_to_zero(self, mock_mkdir):
        # Arrange - all NULLs from DB
        stats_row = (None, None, None, None, None, None, None)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        stats = await tracker.get_funding_stats()

        # Assert
        assert stats.total_paid == 0.0
        assert stats.total_received == 0.0
        assert stats.net_funding == 0.0
        assert stats.payment_count == 0
        assert stats.avg_rate == 0.0
        assert stats.highest_rate == 0.0
        assert stats.lowest_rate == 0.0

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_stats_default_days_is_30(self, mock_mkdir):
        # Arrange
        stats_row = (0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_funding_stats()

        # Assert - default days=30 cutoff
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        # The cutoff is computed as (utcnow - 30 days).isoformat()
        # We verify it's a single-element tuple (no symbol filter)
        assert len(params) == 1


# ============================================================================
# FundingTracker.get_recent_payments tests
# ============================================================================

class TestGetRecentPayments:
    """Tests for get_recent_payments method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_recent_payments_with_results(self, mock_mkdir):
        # Arrange
        rows = [
            (1, "BTCUSDT", "2025-06-01T16:00:00", 0.0001, 0.5, 47500.0, 4.75, "long", 10),
            (2, "ETHUSDT", "2025-06-01T08:00:00", -0.0002, 1.0, 3500.0, -0.70, "short", 11),
        ]
        mock_cursor = make_mock_cursor(fetchall_result=rows)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        payments = await tracker.get_recent_payments()

        # Assert
        assert len(payments) == 2
        assert payments[0].id == 1
        assert payments[0].symbol == "BTCUSDT"
        assert payments[1].id == 2
        assert payments[1].symbol == "ETHUSDT"

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_recent_payments_default_limit(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_recent_payments()

        # Assert
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params == (50,)

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_recent_payments_custom_limit(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_recent_payments(limit=10)

        # Assert
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params == (10,)

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_recent_payments_empty(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        payments = await tracker.get_recent_payments()

        # Assert
        assert payments == []

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_recent_payments_parses_timestamps(self, mock_mkdir):
        # Arrange
        rows = [
            (1, "BTCUSDT", "2025-06-01T16:00:00", 0.0001, 0.5, 47500.0, 4.75, "long", 10),
        ]
        mock_cursor = make_mock_cursor(fetchall_result=rows)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        payments = await tracker.get_recent_payments()

        # Assert
        assert isinstance(payments[0].timestamp, datetime)
        assert payments[0].timestamp == datetime(2025, 6, 1, 16, 0, 0)


# ============================================================================
# FundingTracker.get_funding_rate_history tests
# ============================================================================

class TestGetFundingRateHistory:
    """Tests for get_funding_rate_history method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_rate_history_with_data(self, mock_mkdir):
        # Arrange
        rows = [
            ("2025-06-01T00:00:00", 0.0001),
            ("2025-06-01T08:00:00", 0.00015),
            ("2025-06-01T16:00:00", -0.0001),
        ]
        mock_cursor = make_mock_cursor(fetchall_result=rows)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        history = await tracker.get_funding_rate_history(symbol="BTCUSDT", days=7)

        # Assert
        assert len(history) == 3
        assert history[0] == {"timestamp": "2025-06-01T00:00:00", "rate": 0.0001}
        assert history[1] == {"timestamp": "2025-06-01T08:00:00", "rate": 0.00015}
        assert history[2] == {"timestamp": "2025-06-01T16:00:00", "rate": -0.0001}

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_rate_history_empty(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        history = await tracker.get_funding_rate_history(symbol="BTCUSDT")

        # Assert
        assert history == []

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_rate_history_queries_correct_symbol(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_funding_rate_history(symbol="ETHUSDT", days=3)

        # Assert
        call_args = mock_db.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "WHERE symbol = ?" in sql
        assert params[0] == "ETHUSDT"

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_funding_rate_history_default_days_is_7(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_funding_rate_history(symbol="BTCUSDT")

        # Assert - default is 7 days; the cutoff param should be ~7 days ago
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        # params = (symbol, cutoff_isoformat)
        assert params[0] == "BTCUSDT"
        # cutoff should be about 7 days before now
        cutoff = datetime.fromisoformat(params[1])
        now = datetime.utcnow()
        diff = now - cutoff
        assert 6.9 < diff.total_seconds() / 86400 < 7.1


# ============================================================================
# FundingTracker.is_funding_time tests
# ============================================================================

class TestIsFundingTime:
    """Tests for is_funding_time method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.datetime")
    def test_is_funding_time_at_midnight(self, mock_datetime, mock_mkdir):
        # Arrange - 00:02 UTC
        mock_datetime.utcnow.return_value = datetime(2025, 6, 1, 0, 2, 0)
        tracker = FundingTracker()

        # Act
        result = tracker.is_funding_time()

        # Assert
        assert result is True

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.datetime")
    def test_is_funding_time_at_8am(self, mock_datetime, mock_mkdir):
        # Arrange - 08:03 UTC
        mock_datetime.utcnow.return_value = datetime(2025, 6, 1, 8, 3, 0)
        tracker = FundingTracker()

        # Act
        result = tracker.is_funding_time()

        # Assert
        assert result is True

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.datetime")
    def test_is_funding_time_at_4pm(self, mock_datetime, mock_mkdir):
        # Arrange - 16:04 UTC
        mock_datetime.utcnow.return_value = datetime(2025, 6, 1, 16, 4, 0)
        tracker = FundingTracker()

        # Act
        result = tracker.is_funding_time()

        # Assert
        assert result is True

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.datetime")
    def test_is_funding_time_at_exact_funding_hour(self, mock_datetime, mock_mkdir):
        # Arrange - 00:00 UTC (exactly)
        mock_datetime.utcnow.return_value = datetime(2025, 6, 1, 0, 0, 0)
        tracker = FundingTracker()

        # Act
        result = tracker.is_funding_time()

        # Assert
        assert result is True

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.datetime")
    def test_is_not_funding_time_after_5_minutes(self, mock_datetime, mock_mkdir):
        # Arrange - 00:05 UTC (5 minutes past, should be False)
        mock_datetime.utcnow.return_value = datetime(2025, 6, 1, 0, 5, 0)
        tracker = FundingTracker()

        # Act
        result = tracker.is_funding_time()

        # Assert
        assert result is False

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.datetime")
    def test_is_not_funding_time_random_hour(self, mock_datetime, mock_mkdir):
        # Arrange - 10:30 UTC (not near any funding time)
        mock_datetime.utcnow.return_value = datetime(2025, 6, 1, 10, 30, 0)
        tracker = FundingTracker()

        # Act
        result = tracker.is_funding_time()

        # Assert
        assert result is False

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.datetime")
    def test_is_not_funding_time_just_before_funding_hour(self, mock_datetime, mock_mkdir):
        # Arrange - 07:59 UTC (1 minute before 8am funding)
        mock_datetime.utcnow.return_value = datetime(2025, 6, 1, 7, 59, 0)
        tracker = FundingTracker()

        # Act
        result = tracker.is_funding_time()

        # Assert
        assert result is False

    @patch("src.data.funding_tracker.Path.mkdir")
    @patch("src.data.funding_tracker.datetime")
    def test_is_not_funding_time_6_minutes_past(self, mock_datetime, mock_mkdir):
        # Arrange - 16:06 UTC (6 minutes past, outside 5-minute window)
        mock_datetime.utcnow.return_value = datetime(2025, 6, 1, 16, 6, 0)
        tracker = FundingTracker()

        # Act
        result = tracker.is_funding_time()

        # Assert
        assert result is False

    @patch("src.data.funding_tracker.Path.mkdir")
    def test_funding_hours_constant(self, mock_mkdir):
        # Arrange / Act
        tracker = FundingTracker()

        # Assert
        assert tracker.FUNDING_HOURS == [0, 8, 16]


# ============================================================================
# FundingTracker.get_daily_funding_summary tests
# ============================================================================

class TestGetDailyFundingSummary:
    """Tests for get_daily_funding_summary method."""

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_daily_funding_summary_with_data(self, mock_mkdir):
        # Arrange
        rows = [
            ("2025-06-01", 15.50, 3, 0.0001),
            ("2025-05-31", -5.20, 2, -0.0002),
        ]
        mock_cursor = make_mock_cursor(fetchall_result=rows)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        summary = await tracker.get_daily_funding_summary(days=30)

        # Assert
        assert len(summary) == 2
        assert summary[0] == {
            "date": "2025-06-01",
            "total": 15.50,
            "count": 3,
            "avg_rate": 0.0001,
        }
        assert summary[1] == {
            "date": "2025-05-31",
            "total": -5.20,
            "count": 2,
            "avg_rate": -0.0002,
        }

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_daily_funding_summary_empty(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        summary = await tracker.get_daily_funding_summary()

        # Assert
        assert summary == []

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_daily_funding_summary_default_days_is_30(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_daily_funding_summary()

        # Assert
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        cutoff = datetime.fromisoformat(params[0])
        now = datetime.utcnow()
        diff = now - cutoff
        assert 29.9 < diff.total_seconds() / 86400 < 30.1

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_daily_funding_summary_custom_days(self, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        await tracker.get_daily_funding_summary(days=7)

        # Assert
        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        cutoff = datetime.fromisoformat(params[0])
        now = datetime.utcnow()
        diff = now - cutoff
        assert 6.9 < diff.total_seconds() / 86400 < 7.1

    @patch("src.data.funding_tracker.Path.mkdir")
    async def test_get_daily_funding_summary_single_day(self, mock_mkdir):
        # Arrange
        rows = [
            ("2025-06-01", 3.25, 1, 0.00005),
        ]
        mock_cursor = make_mock_cursor(fetchall_result=rows)
        mock_db = make_mock_db(cursor=mock_cursor)

        tracker = FundingTracker()
        tracker._db = mock_db

        # Act
        summary = await tracker.get_daily_funding_summary(days=1)

        # Assert
        assert len(summary) == 1
        assert summary[0]["date"] == "2025-06-01"
        assert summary[0]["total"] == 3.25
        assert summary[0]["count"] == 1
        assert summary[0]["avg_rate"] == 0.00005
