"""
Unit tests for multi-tenant trade database.

Verifies proper tenant isolation - users cannot access each other's trades.
"""

import os
import pytest
import tempfile
import asyncio

# Set up test environment
import base64
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-purposes-only-32chars"
# Generate a proper 32-byte key encoded as base64
test_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["ENCRYPTION_MASTER_KEY"] = test_key

from src.models.multi_tenant_trade_db import MultiTenantTradeDatabase, Trade, TradeStatus


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Create base trades table
    import aiosqlite

    async def setup_db():
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    size REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    take_profit REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    leverage INTEGER NOT NULL,
                    confidence INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    close_order_id TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    pnl REAL,
                    pnl_percent REAL,
                    fees REAL DEFAULT 0,
                    funding_paid REAL DEFAULT 0,
                    entry_time TIMESTAMP NOT NULL,
                    exit_time TIMESTAMP,
                    exit_reason TEXT,
                    metrics_snapshot TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    asyncio.get_event_loop().run_until_complete(setup_db())

    yield db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def trade_db(test_db):
    """Create multi-tenant trade database instance."""
    return MultiTenantTradeDatabase(db_path=test_db)


class TestTenantIsolation:
    """Tests for tenant isolation - the most critical security feature."""

    @pytest.mark.asyncio
    async def test_users_cannot_see_each_others_trades(self, trade_db):
        """Test that users can only see their own trades."""
        # User 1 creates a trade
        trade1_id = await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Test trade user 1",
            order_id="order-user1-001"
        )

        # User 2 creates a trade
        trade2_id = await trade_db.create_trade(
            user_id=2,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3000,
            take_profit=2800,
            stop_loss=3200,
            leverage=5,
            confidence=70,
            reason="Test trade user 2",
            order_id="order-user2-001"
        )

        # User 1 can only see their trade
        user1_trades = await trade_db.get_recent_trades(user_id=1, limit=10)
        assert len(user1_trades) == 1
        assert user1_trades[0].id == trade1_id
        assert user1_trades[0].symbol == "BTCUSDT"

        # User 2 can only see their trade
        user2_trades = await trade_db.get_recent_trades(user_id=2, limit=10)
        assert len(user2_trades) == 1
        assert user2_trades[0].id == trade2_id
        assert user2_trades[0].symbol == "ETHUSDT"

        # User 1 cannot access User 2's trade by ID
        trade = await trade_db.get_trade(user_id=1, trade_id=trade2_id)
        assert trade is None

        # User 2 cannot access User 1's trade by ID
        trade = await trade_db.get_trade(user_id=2, trade_id=trade1_id)
        assert trade is None

    @pytest.mark.asyncio
    async def test_user_cannot_close_another_users_trade(self, trade_db):
        """Test that users cannot close trades belonging to others."""
        # User 1 creates a trade
        trade_id = await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Test trade",
            order_id="order-001"
        )

        # User 2 tries to close User 1's trade
        result = await trade_db.close_trade(
            user_id=2,  # Wrong user!
            trade_id=trade_id,
            exit_price=51000,
            pnl=100,
            pnl_percent=2.0,
            fees=5,
            funding_paid=1,
            exit_reason="Test close",
            close_order_id="close-001"
        )

        # Should fail
        assert result is False

        # Trade should still be open
        trade = await trade_db.get_trade(user_id=1, trade_id=trade_id)
        assert trade.status == TradeStatus.OPEN

    @pytest.mark.asyncio
    async def test_user_cannot_cancel_another_users_trade(self, trade_db):
        """Test that users cannot cancel trades belonging to others."""
        # User 1 creates a trade
        trade_id = await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Test trade",
            order_id="order-001"
        )

        # User 2 tries to cancel User 1's trade
        result = await trade_db.cancel_trade(
            user_id=2,  # Wrong user!
            trade_id=trade_id,
            reason="Malicious cancel"
        )

        # Should fail
        assert result is False

        # Trade should still be open
        trade = await trade_db.get_trade(user_id=1, trade_id=trade_id)
        assert trade.status == TradeStatus.OPEN

    @pytest.mark.asyncio
    async def test_statistics_are_isolated(self, trade_db):
        """Test that statistics are calculated per-user only."""
        # User 1: 2 winning trades
        for i in range(2):
            trade_id = await trade_db.create_trade(
                user_id=1,
                symbol="BTCUSDT",
                side="long",
                size=0.01,
                entry_price=50000,
                take_profit=52000,
                stop_loss=48000,
                leverage=10,
                confidence=80,
                reason=f"User 1 trade {i}",
                order_id=f"order-u1-{i}"
            )
            await trade_db.close_trade(
                user_id=1,
                trade_id=trade_id,
                exit_price=51000,
                pnl=100,
                pnl_percent=2.0,
                fees=5,
                funding_paid=1,
                exit_reason="Take profit",
                close_order_id=f"close-u1-{i}"
            )

        # User 2: 1 losing trade
        trade_id = await trade_db.create_trade(
            user_id=2,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3000,
            take_profit=2800,
            stop_loss=3200,
            leverage=5,
            confidence=70,
            reason="User 2 trade",
            order_id="order-u2-0"
        )
        await trade_db.close_trade(
            user_id=2,
            trade_id=trade_id,
            exit_price=3100,
            pnl=-50,
            pnl_percent=-1.67,
            fees=3,
            funding_paid=0.5,
            exit_reason="Stop loss",
            close_order_id="close-u2-0"
        )

        # User 1 statistics
        user1_stats = await trade_db.get_statistics(user_id=1, days=30)
        assert user1_stats["total_trades"] == 2
        assert user1_stats["winning_trades"] == 2
        assert user1_stats["win_rate"] == 100.0
        assert user1_stats["total_pnl"] == 200  # 2 x 100

        # User 2 statistics
        user2_stats = await trade_db.get_statistics(user_id=2, days=30)
        assert user2_stats["total_trades"] == 1
        assert user2_stats["losing_trades"] == 1
        assert user2_stats["win_rate"] == 0.0
        assert user2_stats["total_pnl"] == -50

    @pytest.mark.asyncio
    async def test_count_trades_today_isolated(self, trade_db):
        """Test that daily trade count is per-user."""
        # User 1 creates 3 trades
        for i in range(3):
            await trade_db.create_trade(
                user_id=1,
                symbol="BTCUSDT",
                side="long",
                size=0.01,
                entry_price=50000,
                take_profit=52000,
                stop_loss=48000,
                leverage=10,
                confidence=80,
                reason=f"User 1 trade {i}",
                order_id=f"order-u1-{i}"
            )

        # User 2 creates 1 trade
        await trade_db.create_trade(
            user_id=2,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3000,
            take_profit=2800,
            stop_loss=3200,
            leverage=5,
            confidence=70,
            reason="User 2 trade",
            order_id="order-u2-0"
        )

        # Check counts
        user1_count = await trade_db.count_trades_today(user_id=1)
        user2_count = await trade_db.count_trades_today(user_id=2)

        assert user1_count == 3
        assert user2_count == 1


class TestTradeOperations:
    """Tests for basic trade operations."""

    @pytest.mark.asyncio
    async def test_create_and_get_trade(self, trade_db):
        """Test creating and retrieving a trade."""
        trade_id = await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Test trade",
            order_id="order-001"
        )

        trade = await trade_db.get_trade(user_id=1, trade_id=trade_id)

        assert trade is not None
        assert trade.id == trade_id
        assert trade.user_id == 1
        assert trade.symbol == "BTCUSDT"
        assert trade.side == "long"
        assert trade.status == TradeStatus.OPEN

    @pytest.mark.asyncio
    async def test_close_trade(self, trade_db):
        """Test closing a trade."""
        trade_id = await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Test trade",
            order_id="order-001"
        )

        result = await trade_db.close_trade(
            user_id=1,
            trade_id=trade_id,
            exit_price=51000,
            pnl=100,
            pnl_percent=2.0,
            fees=5,
            funding_paid=1,
            exit_reason="Take profit",
            close_order_id="close-001"
        )

        assert result is True

        trade = await trade_db.get_trade(user_id=1, trade_id=trade_id)
        assert trade.status == TradeStatus.CLOSED
        assert trade.exit_price == 51000
        assert trade.pnl == 100

    @pytest.mark.asyncio
    async def test_get_open_trades(self, trade_db):
        """Test getting open trades."""
        # Create open and closed trades
        open_trade_id = await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Open trade",
            order_id="order-001"
        )

        closed_trade_id = await trade_db.create_trade(
            user_id=1,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3000,
            take_profit=2800,
            stop_loss=3200,
            leverage=5,
            confidence=70,
            reason="Closed trade",
            order_id="order-002"
        )
        await trade_db.close_trade(
            user_id=1,
            trade_id=closed_trade_id,
            exit_price=2900,
            pnl=50,
            pnl_percent=3.33,
            fees=2,
            funding_paid=0,
            exit_reason="Take profit",
            close_order_id="close-002"
        )

        open_trades = await trade_db.get_open_trades(user_id=1)

        assert len(open_trades) == 1
        assert open_trades[0].id == open_trade_id
        assert open_trades[0].status == TradeStatus.OPEN

    @pytest.mark.asyncio
    async def test_get_trade_by_order_id(self, trade_db):
        """Test getting trade by exchange order ID."""
        await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Test trade",
            order_id="unique-order-123"
        )

        trade = await trade_db.get_trade_by_order_id(user_id=1, order_id="unique-order-123")

        assert trade is not None
        assert trade.order_id == "unique-order-123"

        # Different user can't access by order ID
        trade = await trade_db.get_trade_by_order_id(user_id=2, order_id="unique-order-123")
        assert trade is None

    @pytest.mark.asyncio
    async def test_update_entry_price(self, trade_db):
        """Test updating entry price after fill."""
        trade_id = await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,  # Estimated
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Test trade",
            order_id="order-001"
        )

        # Update with actual fill price
        result = await trade_db.update_entry_price(
            user_id=1,
            trade_id=trade_id,
            actual_entry_price=50050  # Slight slippage
        )

        assert result is True

        trade = await trade_db.get_trade(user_id=1, trade_id=trade_id)
        assert trade.entry_price == 50050

        # Wrong user can't update
        result = await trade_db.update_entry_price(
            user_id=2,
            trade_id=trade_id,
            actual_entry_price=99999
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_trade(self, trade_db):
        """Test cancelling a trade."""
        trade_id = await trade_db.create_trade(
            user_id=1,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=50000,
            take_profit=52000,
            stop_loss=48000,
            leverage=10,
            confidence=80,
            reason="Test trade",
            order_id="order-001"
        )

        result = await trade_db.cancel_trade(
            user_id=1,
            trade_id=trade_id,
            reason="Order not filled"
        )

        assert result is True

        trade = await trade_db.get_trade(user_id=1, trade_id=trade_id)
        assert trade.status == TradeStatus.CANCELLED
        assert trade.exit_reason == "Order not filled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
