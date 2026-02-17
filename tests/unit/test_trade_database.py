"""
Unit tests for src.models.trade_database module.

Tests cover:
- TradeStatus enum values
- Trade dataclass and to_dict conversion
- TradeDatabase initialization
- CRUD operations (create_trade, close_trade, update_entry_price, get_trade)
- Query methods (get_open_trades, get_recent_trades, get_trades_for_date, etc.)
- Statistics calculation (get_statistics, count_trades_today)
- _row_to_trade helper
- Error and edge-case paths

All aiosqlite interactions are mocked so no real database is used.
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.models.trade_database import Trade, TradeDatabase, TradeStatus


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
    """Build a mock aiosqlite connection (async context manager)."""
    if cursor is None:
        cursor = make_mock_cursor()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=cursor)
    db.commit = AsyncMock()
    db.row_factory = None
    return db


def make_connect_cm(db):
    """Wrap a mock db in an async context manager compatible with `async with`."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def make_mock_row(data: dict):
    """Create a dict-like mock row that supports bracket access."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: data[key]
    row.keys = lambda: data.keys()
    return row


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

SAMPLE_ROW_DATA = {
    "id": 1,
    "symbol": "BTCUSDT",
    "side": "long",
    "size": 0.01,
    "entry_price": 95000.0,
    "exit_price": 96000.0,
    "take_profit": 97000.0,
    "stop_loss": 94000.0,
    "leverage": 4,
    "confidence": 75,
    "reason": "Strong buy signal",
    "order_id": "order_001",
    "close_order_id": "close_001",
    "status": "closed",
    "pnl": 10.0,
    "pnl_percent": 1.05,
    "fees": 0.5,
    "funding_paid": 0.1,
    "entry_time": "2025-06-01T12:00:00",
    "exit_time": "2025-06-01T14:00:00",
    "exit_reason": "TAKE_PROFIT",
    "metrics_snapshot": '{"fear_greed": 50}',
}

SAMPLE_OPEN_ROW_DATA = {
    **SAMPLE_ROW_DATA,
    "id": 2,
    "status": "open",
    "exit_price": None,
    "close_order_id": None,
    "pnl": None,
    "pnl_percent": None,
    "exit_time": None,
    "exit_reason": None,
    "order_id": "order_002",
    "metrics_snapshot": None,
}


def make_sample_trade() -> Trade:
    """Create a Trade object matching SAMPLE_ROW_DATA."""
    return Trade(
        id=1,
        symbol="BTCUSDT",
        side="long",
        size=0.01,
        entry_price=95000.0,
        exit_price=96000.0,
        take_profit=97000.0,
        stop_loss=94000.0,
        leverage=4,
        confidence=75,
        reason="Strong buy signal",
        order_id="order_001",
        close_order_id="close_001",
        status=TradeStatus.CLOSED,
        pnl=10.0,
        pnl_percent=1.05,
        fees=0.5,
        funding_paid=0.1,
        entry_time=datetime.fromisoformat("2025-06-01T12:00:00"),
        exit_time=datetime.fromisoformat("2025-06-01T14:00:00"),
        exit_reason="TAKE_PROFIT",
        metrics_snapshot='{"fear_greed": 50}',
    )


# ============================================================================
# TradeStatus enum tests
# ============================================================================

class TestTradeStatus:
    """Tests for the TradeStatus enum."""

    def test_open_value(self):
        assert TradeStatus.OPEN.value == "open"

    def test_closed_value(self):
        assert TradeStatus.CLOSED.value == "closed"

    def test_cancelled_value(self):
        assert TradeStatus.CANCELLED.value == "cancelled"

    def test_from_string(self):
        assert TradeStatus("open") == TradeStatus.OPEN
        assert TradeStatus("closed") == TradeStatus.CLOSED
        assert TradeStatus("cancelled") == TradeStatus.CANCELLED

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            TradeStatus("invalid")


# ============================================================================
# Trade dataclass tests
# ============================================================================

class TestTrade:
    """Tests for the Trade dataclass."""

    def test_creation(self):
        trade = make_sample_trade()
        assert trade.id == 1
        assert trade.symbol == "BTCUSDT"
        assert trade.side == "long"
        assert trade.status == TradeStatus.CLOSED

    def test_to_dict_returns_all_fields(self):
        trade = make_sample_trade()
        d = trade.to_dict()

        assert d["id"] == 1
        assert d["symbol"] == "BTCUSDT"
        assert d["side"] == "long"
        assert d["size"] == 0.01
        assert d["entry_price"] == 95000.0
        assert d["exit_price"] == 96000.0
        assert d["take_profit"] == 97000.0
        assert d["stop_loss"] == 94000.0
        assert d["leverage"] == 4
        assert d["confidence"] == 75
        assert d["reason"] == "Strong buy signal"
        assert d["order_id"] == "order_001"
        assert d["close_order_id"] == "close_001"
        assert d["status"] == "closed"
        assert d["pnl"] == 10.0
        assert d["pnl_percent"] == 1.05
        assert d["fees"] == 0.5
        assert d["funding_paid"] == 0.1
        assert d["exit_reason"] == "TAKE_PROFIT"

    def test_to_dict_status_is_string_not_enum(self):
        trade = make_sample_trade()
        d = trade.to_dict()
        assert isinstance(d["status"], str)
        assert d["status"] == "closed"

    def test_to_dict_entry_time_is_isoformat(self):
        trade = make_sample_trade()
        d = trade.to_dict()
        assert d["entry_time"] == "2025-06-01T12:00:00"

    def test_to_dict_exit_time_is_isoformat(self):
        trade = make_sample_trade()
        d = trade.to_dict()
        assert d["exit_time"] == "2025-06-01T14:00:00"

    def test_to_dict_none_entry_time(self):
        trade = make_sample_trade()
        trade.entry_time = None
        d = trade.to_dict()
        assert d["entry_time"] is None

    def test_to_dict_none_exit_time(self):
        trade = make_sample_trade()
        trade.exit_time = None
        d = trade.to_dict()
        assert d["exit_time"] is None

    def test_optional_fields_can_be_none(self):
        trade = Trade(
            id=None,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            exit_price=None,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=2,
            confidence=60,
            reason="Test",
            order_id="order_x",
            close_order_id=None,
            status=TradeStatus.OPEN,
            pnl=None,
            pnl_percent=None,
            fees=0.0,
            funding_paid=0.0,
            entry_time=datetime.now(),
            exit_time=None,
            exit_reason=None,
            metrics_snapshot="{}",
        )
        d = trade.to_dict()
        assert d["id"] is None
        assert d["exit_price"] is None
        assert d["pnl"] is None
        assert d["close_order_id"] is None


# ============================================================================
# TradeDatabase.__init__ tests
# ============================================================================

class TestTradeDatabaseInit:
    """Tests for TradeDatabase constructor."""

    @patch("src.models.trade_database.Path.mkdir")
    def test_default_db_path(self, mock_mkdir):
        db = TradeDatabase()
        assert db.db_path == Path("data/trades.db")
        assert db._initialized is False

    @patch("src.models.trade_database.Path.mkdir")
    def test_custom_db_path(self, mock_mkdir):
        db = TradeDatabase(db_path="custom/path/my.db")
        assert db.db_path == Path("custom/path/my.db")

    @patch("src.models.trade_database.Path.mkdir")
    def test_creates_parent_directory(self, mock_mkdir):
        TradeDatabase(db_path="some/nested/dir/trades.db")
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)


# ============================================================================
# TradeDatabase.initialize tests
# ============================================================================

class TestTradeDatabaseInitialize:
    """Tests for the initialize method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_initialize_creates_schema(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()

        # Act
        await db.initialize()

        # Assert
        assert db._initialized is True
        # Should execute PRAGMA + CREATE TABLE + 3 indexes = at least 5 calls
        assert mock_db.execute.call_count >= 5
        mock_db.commit.assert_awaited_once()

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_initialize_skips_if_already_initialized(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        await db.initialize()

        # Assert - aiosqlite.connect should NOT have been called
        mock_aiosqlite.connect.assert_not_called()

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_initialize_sets_wal_mode(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()

        # Act
        await db.initialize()

        # Assert - first two execute calls should be PRAGMA
        calls = mock_db.execute.call_args_list
        first_call_sql = calls[0][0][0]
        assert "PRAGMA journal_mode=WAL" in first_call_sql


# ============================================================================
# TradeDatabase.create_trade tests
# ============================================================================

class TestCreateTrade:
    """Tests for create_trade method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_create_trade_returns_trade_id(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(lastrowid=42)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        trade_id = await db.create_trade(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Test signal",
            order_id="order_123",
        )

        # Assert
        assert trade_id == 42
        mock_db.commit.assert_awaited_once()

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_create_trade_inserts_with_open_status(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(lastrowid=1)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        await db.create_trade(
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=2,
            confidence=80,
            reason="Short signal",
            order_id="order_456",
        )

        # Assert - verify the INSERT call contains "open" status
        insert_call = mock_db.execute.call_args
        params = insert_call[0][1]  # second positional arg = tuple of params
        assert "open" in params  # TradeStatus.OPEN.value

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_create_trade_default_metrics_snapshot(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(lastrowid=1)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        await db.create_trade(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Test",
            order_id="order_789",
        )

        # Assert - default metrics_snapshot is "{}"
        insert_call = mock_db.execute.call_args
        params = insert_call[0][1]
        assert "{}" in params

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_create_trade_custom_metrics_snapshot(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(lastrowid=1)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        custom_metrics = '{"fear_greed": 80}'

        # Act
        await db.create_trade(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Test",
            order_id="order_999",
            metrics_snapshot=custom_metrics,
        )

        # Assert
        insert_call = mock_db.execute.call_args
        params = insert_call[0][1]
        assert custom_metrics in params

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_create_trade_calls_initialize(self, mock_aiosqlite, mock_mkdir):
        """create_trade should call initialize() if not already initialized."""
        # Arrange - need two connect calls: one for init, one for the insert
        mock_init_db = make_mock_db()
        mock_insert_cursor = make_mock_cursor(lastrowid=1)
        mock_insert_db = make_mock_db(cursor=mock_insert_cursor)

        call_count = 0

        def connect_side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_connect_cm(mock_init_db)
            return make_connect_cm(mock_insert_db)

        mock_aiosqlite.connect.side_effect = connect_side_effect

        db = TradeDatabase()
        assert db._initialized is False

        # Act
        trade_id = await db.create_trade(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Test",
            order_id="order_init",
        )

        # Assert
        assert db._initialized is True
        assert trade_id == 1


# ============================================================================
# TradeDatabase.close_trade tests
# ============================================================================

class TestCloseTrade:
    """Tests for close_trade method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_close_trade_returns_true(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        result = await db.close_trade(
            trade_id=1,
            exit_price=96000.0,
            pnl=10.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            exit_reason="TAKE_PROFIT",
            close_order_id="close_001",
        )

        # Assert
        assert result is True
        mock_db.commit.assert_awaited_once()

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_close_trade_updates_with_closed_status(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        await db.close_trade(
            trade_id=5,
            exit_price=93000.0,
            pnl=-20.0,
            pnl_percent=-2.1,
            fees=0.4,
            funding_paid=0.08,
            exit_reason="STOP_LOSS",
            close_order_id="close_005",
        )

        # Assert - verify the UPDATE call contains "closed" status and trade_id
        update_call = mock_db.execute.call_args
        params = update_call[0][1]
        assert "closed" in params
        assert 5 in params  # trade_id is last param

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_close_trade_passes_all_parameters(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        await db.close_trade(
            trade_id=3,
            exit_price=96500.0,
            pnl=15.0,
            pnl_percent=1.5,
            fees=0.6,
            funding_paid=0.2,
            exit_reason="MANUAL",
            close_order_id="close_003",
        )

        # Assert
        update_call = mock_db.execute.call_args
        params = update_call[0][1]
        assert 96500.0 in params
        assert 15.0 in params
        assert 1.5 in params
        assert 0.6 in params
        assert 0.2 in params
        assert "MANUAL" in params
        assert "close_003" in params


# ============================================================================
# TradeDatabase.update_entry_price tests
# ============================================================================

class TestUpdateEntryPrice:
    """Tests for update_entry_price method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_update_entry_price_returns_true(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        result = await db.update_entry_price(trade_id=1, actual_entry_price=95100.0)

        # Assert
        assert result is True
        mock_db.commit.assert_awaited_once()

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_update_entry_price_with_slippage(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        result = await db.update_entry_price(
            trade_id=1, actual_entry_price=95100.0, slippage=100.0
        )

        # Assert
        assert result is True
        # Verify the price is in the params
        update_call = mock_db.execute.call_args
        params = update_call[0][1]
        assert 95100.0 in params

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_update_entry_price_without_slippage(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_db = make_mock_db()
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        result = await db.update_entry_price(
            trade_id=2, actual_entry_price=3510.0, slippage=None
        )

        # Assert
        assert result is True
        update_call = mock_db.execute.call_args
        params = update_call[0][1]
        assert 3510.0 in params
        assert 2 in params


# ============================================================================
# TradeDatabase.get_trade tests
# ============================================================================

class TestGetTrade:
    """Tests for get_trade method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_trade_found(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_row = make_mock_row(SAMPLE_ROW_DATA)
        mock_cursor = make_mock_cursor(fetchone_result=mock_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trade = await db.get_trade(1)

        # Assert
        assert trade is not None
        assert isinstance(trade, Trade)
        assert trade.id == 1
        assert trade.symbol == "BTCUSDT"
        assert trade.status == TradeStatus.CLOSED

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_trade_not_found(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchone_result=None)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trade = await db.get_trade(999)

        # Assert
        assert trade is None


# ============================================================================
# TradeDatabase.get_trade_by_order_id tests
# ============================================================================

class TestGetTradeByOrderId:
    """Tests for get_trade_by_order_id method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_trade_by_order_id_found(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_row = make_mock_row(SAMPLE_ROW_DATA)
        mock_cursor = make_mock_cursor(fetchone_result=mock_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trade = await db.get_trade_by_order_id("order_001")

        # Assert
        assert trade is not None
        assert trade.order_id == "order_001"

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_trade_by_order_id_not_found(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchone_result=None)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trade = await db.get_trade_by_order_id("nonexistent_order")

        # Assert
        assert trade is None


# ============================================================================
# TradeDatabase.get_open_trades tests
# ============================================================================

class TestGetOpenTrades:
    """Tests for get_open_trades method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_open_trades_no_symbol_filter(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_row = make_mock_row(SAMPLE_OPEN_ROW_DATA)
        mock_cursor = make_mock_cursor(fetchall_result=[mock_row])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_open_trades()

        # Assert
        assert len(trades) == 1
        assert trades[0].status == TradeStatus.OPEN

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_open_trades_with_symbol_filter(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_row = make_mock_row(SAMPLE_OPEN_ROW_DATA)
        mock_cursor = make_mock_cursor(fetchall_result=[mock_row])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_open_trades(symbol="BTCUSDT")

        # Assert
        assert len(trades) == 1
        # Verify the query included both status and symbol params
        execute_call = mock_db.execute.call_args
        params = execute_call[0][1]
        assert "open" in params
        assert "BTCUSDT" in params

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_open_trades_empty_result(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_open_trades()

        # Assert
        assert trades == []

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_open_trades_multiple_results(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        row1 = make_mock_row(SAMPLE_OPEN_ROW_DATA)
        row2_data = {**SAMPLE_OPEN_ROW_DATA, "id": 3, "symbol": "ETHUSDT", "order_id": "order_003"}
        row2 = make_mock_row(row2_data)
        mock_cursor = make_mock_cursor(fetchall_result=[row1, row2])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_open_trades()

        # Assert
        assert len(trades) == 2


# ============================================================================
# TradeDatabase.get_trades_for_date tests
# ============================================================================

class TestGetTradesForDate:
    """Tests for get_trades_for_date method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_trades_for_date_with_results(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_row = make_mock_row(SAMPLE_ROW_DATA)
        mock_cursor = make_mock_cursor(fetchall_result=[mock_row])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_trades_for_date("2025-06-01")

        # Assert
        assert len(trades) == 1
        execute_call = mock_db.execute.call_args
        params = execute_call[0][1]
        assert "2025-06-01" in params

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_trades_for_date_no_results(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_trades_for_date("2020-01-01")

        # Assert
        assert trades == []


# ============================================================================
# TradeDatabase.get_recent_trades tests
# ============================================================================

class TestGetRecentTrades:
    """Tests for get_recent_trades method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_recent_trades_default_limit(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_row = make_mock_row(SAMPLE_ROW_DATA)
        mock_cursor = make_mock_cursor(fetchall_result=[mock_row])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_recent_trades()

        # Assert
        assert len(trades) == 1
        execute_call = mock_db.execute.call_args
        params = execute_call[0][1]
        assert 50 in params  # default limit

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_recent_trades_custom_limit(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_recent_trades(limit=10)

        # Assert
        execute_call = mock_db.execute.call_args
        params = execute_call[0][1]
        assert 10 in params

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_recent_trades_empty(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_recent_trades()

        # Assert
        assert trades == []


# ============================================================================
# TradeDatabase.get_trades_by_year tests
# ============================================================================

class TestGetTradesByYear:
    """Tests for get_trades_by_year method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_trades_by_year_with_results(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_row = make_mock_row(SAMPLE_ROW_DATA)
        mock_cursor = make_mock_cursor(fetchall_result=[mock_row])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_trades_by_year(2025)

        # Assert
        assert len(trades) == 1
        execute_call = mock_db.execute.call_args
        params = execute_call[0][1]
        assert "2025" in params  # year is passed as string

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_trades_by_year_empty(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchall_result=[])
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trades = await db.get_trades_by_year(2020)

        # Assert
        assert trades == []


# ============================================================================
# TradeDatabase.get_statistics tests
# ============================================================================

class TestGetStatistics:
    """Tests for get_statistics method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_with_trades(self, mock_aiosqlite, mock_mkdir):
        # Arrange - row represents aggregated stats
        # (total, winning, losing, total_pnl, total_fees, total_funding,
        #  avg_pnl_percent, best_trade, worst_trade)
        stats_row = (10, 7, 3, 50.0, 5.0, 2.0, 1.5, 20.0, -10.0)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics(days=30)

        # Assert
        assert stats["period_days"] == 30
        assert stats["total_trades"] == 10
        assert stats["winning_trades"] == 7
        assert stats["losing_trades"] == 3
        assert stats["win_rate"] == 70.0
        assert stats["total_pnl"] == 50.0
        assert stats["total_fees"] == 5.0
        assert stats["total_funding"] == 2.0
        assert stats["net_pnl"] == 50.0 - 5.0 - abs(2.0)
        assert stats["avg_pnl_percent"] == 1.5
        assert stats["best_trade"] == 20.0
        assert stats["worst_trade"] == -10.0

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_no_trades(self, mock_aiosqlite, mock_mkdir):
        # Arrange - row[0] is 0 (no trades)
        stats_row = (0, None, None, None, None, None, None, None, None)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics(days=7)

        # Assert - should return empty stats
        assert stats["period_days"] == 7
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0
        assert stats["total_pnl"] == 0.0
        assert stats["net_pnl"] == 0.0

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_null_row(self, mock_aiosqlite, mock_mkdir):
        # Arrange - fetchone returns None
        mock_cursor = make_mock_cursor(fetchone_result=None)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics()

        # Assert - should return default empty stats
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0
        assert stats["net_pnl"] == 0.0

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_default_days(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        stats_row = (0, None, None, None, None, None, None, None, None)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics()

        # Assert - default is 30 days
        assert stats["period_days"] == 30
        execute_call = mock_db.execute.call_args
        params = execute_call[0][1]
        assert "-30 days" in params

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_handles_none_aggregates(self, mock_aiosqlite, mock_mkdir):
        """When some aggregate values are None, they should default to 0."""
        # Arrange - total_trades > 0 but some fields None
        stats_row = (5, None, None, None, None, None, None, None, None)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics()

        # Assert - None values should become 0
        assert stats["total_trades"] == 5
        assert stats["winning_trades"] == 0
        assert stats["losing_trades"] == 0
        assert stats["total_pnl"] == 0
        assert stats["total_fees"] == 0
        assert stats["total_funding"] == 0
        assert stats["avg_pnl_percent"] == 0
        assert stats["best_trade"] == 0
        assert stats["worst_trade"] == 0

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_net_pnl_calculation(self, mock_aiosqlite, mock_mkdir):
        """net_pnl = total_pnl - total_fees - abs(total_funding)."""
        # Arrange - negative funding_paid
        stats_row = (3, 2, 1, 100.0, 10.0, -5.0, 2.5, 80.0, -30.0)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics()

        # Assert: net_pnl = 100.0 - 10.0 - abs(-5.0) = 85.0
        assert stats["net_pnl"] == 85.0

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_win_rate_calculation(self, mock_aiosqlite, mock_mkdir):
        """Win rate should be (winning / total) * 100."""
        # Arrange
        stats_row = (4, 3, 1, 30.0, 2.0, 1.0, 3.0, 20.0, -5.0)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics()

        # Assert
        assert stats["win_rate"] == 75.0


# ============================================================================
# TradeDatabase.count_trades_today tests
# ============================================================================

class TestCountTradesToday:
    """Tests for count_trades_today method."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_count_trades_today_with_trades(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchone_result=(5,))
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        count = await db.count_trades_today()

        # Assert
        assert count == 5

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_count_trades_today_zero(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchone_result=(0,))
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        count = await db.count_trades_today()

        # Assert
        assert count == 0

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_count_trades_today_null_row(self, mock_aiosqlite, mock_mkdir):
        # Arrange
        mock_cursor = make_mock_cursor(fetchone_result=None)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        count = await db.count_trades_today()

        # Assert
        assert count == 0


# ============================================================================
# TradeDatabase._row_to_trade tests
# ============================================================================

class TestRowToTrade:
    """Tests for _row_to_trade private method."""

    @patch("src.models.trade_database.Path.mkdir")
    def test_row_to_trade_closed_trade(self, mock_mkdir):
        # Arrange
        db = TradeDatabase()
        row = make_mock_row(SAMPLE_ROW_DATA)

        # Act
        trade = db._row_to_trade(row)

        # Assert
        assert isinstance(trade, Trade)
        assert trade.id == 1
        assert trade.symbol == "BTCUSDT"
        assert trade.side == "long"
        assert trade.size == 0.01
        assert trade.entry_price == 95000.0
        assert trade.exit_price == 96000.0
        assert trade.take_profit == 97000.0
        assert trade.stop_loss == 94000.0
        assert trade.leverage == 4
        assert trade.confidence == 75
        assert trade.reason == "Strong buy signal"
        assert trade.order_id == "order_001"
        assert trade.close_order_id == "close_001"
        assert trade.status == TradeStatus.CLOSED
        assert trade.pnl == 10.0
        assert trade.pnl_percent == 1.05
        assert trade.fees == 0.5
        assert trade.funding_paid == 0.1
        assert trade.entry_time == datetime.fromisoformat("2025-06-01T12:00:00")
        assert trade.exit_time == datetime.fromisoformat("2025-06-01T14:00:00")
        assert trade.exit_reason == "TAKE_PROFIT"
        assert trade.metrics_snapshot == '{"fear_greed": 50}'

    @patch("src.models.trade_database.Path.mkdir")
    def test_row_to_trade_open_trade_with_nulls(self, mock_mkdir):
        # Arrange
        db = TradeDatabase()
        row = make_mock_row(SAMPLE_OPEN_ROW_DATA)

        # Act
        trade = db._row_to_trade(row)

        # Assert
        assert trade.status == TradeStatus.OPEN
        assert trade.exit_price is None
        assert trade.close_order_id is None
        assert trade.pnl is None
        assert trade.pnl_percent is None
        assert trade.exit_time is None
        assert trade.exit_reason is None
        # None metrics_snapshot should default to "{}"
        assert trade.metrics_snapshot == "{}"

    @patch("src.models.trade_database.Path.mkdir")
    def test_row_to_trade_entry_time_parsed(self, mock_mkdir):
        # Arrange
        db = TradeDatabase()
        row = make_mock_row(SAMPLE_ROW_DATA)

        # Act
        trade = db._row_to_trade(row)

        # Assert
        assert isinstance(trade.entry_time, datetime)
        assert trade.entry_time.year == 2025
        assert trade.entry_time.month == 6
        assert trade.entry_time.day == 1

    @patch("src.models.trade_database.Path.mkdir")
    def test_row_to_trade_null_entry_time(self, mock_mkdir):
        """If entry_time is None in the row, trade.entry_time should be None."""
        # Arrange
        db = TradeDatabase()
        row_data = {**SAMPLE_ROW_DATA, "entry_time": None}
        row = make_mock_row(row_data)

        # Act
        trade = db._row_to_trade(row)

        # Assert
        assert trade.entry_time is None

    @patch("src.models.trade_database.Path.mkdir")
    def test_row_to_trade_cancelled_status(self, mock_mkdir):
        # Arrange
        db = TradeDatabase()
        row_data = {**SAMPLE_ROW_DATA, "status": "cancelled"}
        row = make_mock_row(row_data)

        # Act
        trade = db._row_to_trade(row)

        # Assert
        assert trade.status == TradeStatus.CANCELLED


# ============================================================================
# Integration-style tests (mocked but testing workflow)
# ============================================================================

class TestTradeDatabaseWorkflow:
    """Tests for typical usage workflows with all dependencies mocked."""

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_create_then_get_trade_workflow(self, mock_aiosqlite, mock_mkdir):
        """Simulate creating a trade then retrieving it."""
        # Arrange - create phase
        create_cursor = make_mock_cursor(lastrowid=7)
        create_db = make_mock_db(cursor=create_cursor)

        # Arrange - get phase
        mock_row = make_mock_row({**SAMPLE_ROW_DATA, "id": 7})
        get_cursor = make_mock_cursor(fetchone_result=mock_row)
        get_db = make_mock_db(cursor=get_cursor)

        call_count = 0

        def connect_side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_connect_cm(create_db)
            return make_connect_cm(get_db)

        mock_aiosqlite.connect.side_effect = connect_side_effect
        mock_aiosqlite.Row = MagicMock()

        db = TradeDatabase()
        db._initialized = True

        # Act
        trade_id = await db.create_trade(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Test",
            order_id="order_wf",
        )
        trade = await db.get_trade(trade_id)

        # Assert
        assert trade_id == 7
        assert trade is not None
        assert trade.id == 7

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_create_then_close_trade_workflow(self, mock_aiosqlite, mock_mkdir):
        """Simulate creating and closing a trade."""
        # Arrange
        create_cursor = make_mock_cursor(lastrowid=10)
        create_db = make_mock_db(cursor=create_cursor)

        close_db = make_mock_db()

        call_count = 0

        def connect_side_effect(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_connect_cm(create_db)
            return make_connect_cm(close_db)

        mock_aiosqlite.connect.side_effect = connect_side_effect

        db = TradeDatabase()
        db._initialized = True

        # Act
        trade_id = await db.create_trade(
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=2,
            confidence=80,
            reason="Short signal",
            order_id="order_close_wf",
        )
        closed = await db.close_trade(
            trade_id=trade_id,
            exit_price=3400.0,
            pnl=10.0,
            pnl_percent=2.86,
            fees=0.3,
            funding_paid=0.05,
            exit_reason="TAKE_PROFIT",
            close_order_id="close_wf",
        )

        # Assert
        assert trade_id == 10
        assert closed is True


# ============================================================================
# Edge case tests
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_trade_status_all_values(self):
        """All enum values should be accessible."""
        statuses = list(TradeStatus)
        assert len(statuses) == 3
        values = {s.value for s in statuses}
        assert values == {"open", "closed", "cancelled"}

    def test_trade_to_dict_does_not_include_metrics_snapshot(self):
        """to_dict() intentionally does not include metrics_snapshot."""
        trade = make_sample_trade()
        d = trade.to_dict()
        assert "metrics_snapshot" not in d

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_custom_days(self, mock_aiosqlite, mock_mkdir):
        """Custom days parameter is properly passed to query."""
        # Arrange
        stats_row = (0, None, None, None, None, None, None, None, None)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics(days=7)

        # Assert
        assert stats["period_days"] == 7
        execute_call = mock_db.execute.call_args
        params = execute_call[0][1]
        assert "-7 days" in params

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_all_winning(self, mock_aiosqlite, mock_mkdir):
        """100% win rate scenario."""
        # Arrange
        stats_row = (5, 5, 0, 100.0, 5.0, 1.0, 4.0, 50.0, 5.0)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics()

        # Assert
        assert stats["win_rate"] == 100.0
        assert stats["losing_trades"] == 0

    @patch("src.models.trade_database.Path.mkdir")
    @patch("src.models.trade_database.aiosqlite")
    async def test_get_statistics_all_losing(self, mock_aiosqlite, mock_mkdir):
        """0% win rate scenario."""
        # Arrange
        stats_row = (3, 0, 3, -30.0, 3.0, 0.5, -3.3, -5.0, -15.0)
        mock_cursor = make_mock_cursor(fetchone_result=stats_row)
        mock_db = make_mock_db(cursor=mock_cursor)
        mock_aiosqlite.connect.return_value = make_connect_cm(mock_db)

        db = TradeDatabase()
        db._initialized = True

        # Act
        stats = await db.get_statistics()

        # Assert
        assert stats["win_rate"] == 0.0
        assert stats["winning_trades"] == 0
        assert stats["total_pnl"] == -30.0

    @patch("src.models.trade_database.Path.mkdir")
    def test_row_to_trade_metrics_snapshot_none_defaults_to_empty_json(self, mock_mkdir):
        """When metrics_snapshot is None in DB, should become '{}'."""
        db = TradeDatabase()
        row_data = {**SAMPLE_ROW_DATA, "metrics_snapshot": None}
        row = make_mock_row(row_data)

        trade = db._row_to_trade(row)
        assert trade.metrics_snapshot == "{}"

    @patch("src.models.trade_database.Path.mkdir")
    def test_row_to_trade_metrics_snapshot_with_data(self, mock_mkdir):
        """When metrics_snapshot has data, it should be preserved."""
        db = TradeDatabase()
        row_data = {**SAMPLE_ROW_DATA, "metrics_snapshot": '{"key": "value"}'}
        row = make_mock_row(row_data)

        trade = db._row_to_trade(row)
        assert trade.metrics_snapshot == '{"key": "value"}'
