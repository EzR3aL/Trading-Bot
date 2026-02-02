"""
Multi-tenant Trade Database for user-isolated trade tracking.

Extends TradeDatabase with user_id filtering for proper tenant isolation.
All queries are filtered by user_id to prevent cross-tenant data leaks.
"""

import aiosqlite
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List

from src.utils.logger import get_logger

logger = get_logger(__name__)


class TradeStatus(Enum):
    """Trade status enum."""
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass
class Trade:
    """Trade record dataclass with user isolation."""
    id: Optional[int]
    user_id: int  # Required for multi-tenancy
    symbol: str
    side: str  # long or short
    size: float
    entry_price: float
    exit_price: Optional[float]
    take_profit: float
    stop_loss: float
    leverage: int
    confidence: int
    reason: str
    order_id: str
    close_order_id: Optional[str]
    status: TradeStatus
    pnl: Optional[float]
    pnl_percent: Optional[float]
    fees: float
    funding_paid: float
    entry_time: datetime
    exit_time: Optional[datetime]
    exit_reason: Optional[str]
    metrics_snapshot: str  # JSON string

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "side": self.side,
            "size": self.size,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "leverage": self.leverage,
            "confidence": self.confidence,
            "reason": self.reason,
            "order_id": self.order_id,
            "close_order_id": self.close_order_id,
            "status": self.status.value,
            "pnl": self.pnl,
            "pnl_percent": self.pnl_percent,
            "fees": self.fees,
            "funding_paid": self.funding_paid,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_reason": self.exit_reason,
        }


class MultiTenantTradeDatabase:
    """
    Multi-tenant SQLite database for trade persistence.

    All methods require a user_id parameter to ensure proper
    tenant isolation. Queries will only return data belonging
    to the specified user.

    Security:
    - All SELECT queries filter by user_id
    - All INSERT queries include user_id
    - All UPDATE/DELETE queries verify user_id ownership
    - No cross-tenant data access possible
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """
        Initialize the multi-tenant trade database.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the database schema with user_id column."""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            # Check if trades table exists
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
            )
            table_exists = await cursor.fetchone() is not None

            if not table_exists:
                # Create trades table with user_id column
                await db.execute("""
                    CREATE TABLE trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        size REAL NOT NULL,
                        entry_price REAL NOT NULL,
                        exit_price REAL,
                        take_profit REAL NOT NULL,
                        stop_loss REAL NOT NULL,
                        leverage INTEGER NOT NULL,
                        confidence INTEGER NOT NULL,
                        reason TEXT,
                        order_id TEXT NOT NULL,
                        close_order_id TEXT,
                        status TEXT DEFAULT 'open',
                        pnl REAL,
                        pnl_percent REAL,
                        fees REAL DEFAULT 0,
                        funding_paid REAL DEFAULT 0,
                        entry_time TEXT NOT NULL,
                        exit_time TEXT,
                        exit_reason TEXT,
                        metrics_snapshot TEXT DEFAULT '{}'
                    )
                """)
                await db.commit()
                logger.info("Created trades table with user_id column")
            else:
                # Check if user_id column exists, add it if not
                cursor = await db.execute("PRAGMA table_info(trades)")
                columns = [row[1] for row in await cursor.fetchall()]

                if "user_id" not in columns:
                    # Add user_id column to existing trades table
                    await db.execute("ALTER TABLE trades ADD COLUMN user_id INTEGER")
                    await db.commit()
                    logger.info("Added user_id column to trades table")

            # Create indexes for user queries
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_user_id ON trades(user_id)")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_user_status ON trades(user_id, status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_user_entry_time ON trades(user_id, entry_time)"
            )
            await db.commit()

        self._initialized = True
        logger.info(f"Multi-tenant trade database initialized at {self.db_path}")

    async def create_trade(
        self,
        user_id: int,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        take_profit: float,
        stop_loss: float,
        leverage: int,
        confidence: int,
        reason: str,
        order_id: str,
        metrics_snapshot: str = "{}",
    ) -> int:
        """
        Create a new trade record for a user.

        Args:
            user_id: Owner user ID (required)
            symbol: Trading pair
            side: long or short
            size: Position size
            entry_price: Entry price
            take_profit: Take profit price
            stop_loss: Stop loss price
            leverage: Leverage used
            confidence: Strategy confidence
            reason: Trade reasoning
            order_id: Exchange order ID
            metrics_snapshot: JSON string of market metrics

        Returns:
            Trade ID
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO trades (
                    user_id, symbol, side, size, entry_price, take_profit, stop_loss,
                    leverage, confidence, reason, order_id, status,
                    entry_time, metrics_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, symbol, side, size, entry_price, take_profit, stop_loss,
                    leverage, confidence, reason, order_id, TradeStatus.OPEN.value,
                    datetime.now(), metrics_snapshot
                ),
            )
            await db.commit()
            trade_id = cursor.lastrowid

        logger.info(f"Created trade #{trade_id} for user {user_id}: {side.upper()} {size} {symbol}")
        return trade_id

    async def close_trade(
        self,
        user_id: int,
        trade_id: int,
        exit_price: float,
        pnl: float,
        pnl_percent: float,
        fees: float,
        funding_paid: float,
        exit_reason: str,
        close_order_id: str,
    ) -> bool:
        """
        Close an existing trade (with user verification).

        Args:
            user_id: Owner user ID (must match trade owner)
            trade_id: Trade ID to close
            exit_price: Exit price
            pnl: Absolute PnL
            pnl_percent: PnL percentage
            fees: Trading fees
            funding_paid: Funding payments
            exit_reason: Reason for exit
            close_order_id: Close order ID

        Returns:
            True if closed successfully
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # Only update if user owns this trade
            cursor = await db.execute(
                """
                UPDATE trades SET
                    exit_price = ?,
                    pnl = ?,
                    pnl_percent = ?,
                    fees = ?,
                    funding_paid = ?,
                    exit_reason = ?,
                    close_order_id = ?,
                    status = ?,
                    exit_time = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    exit_price, pnl, pnl_percent, fees, funding_paid,
                    exit_reason, close_order_id, TradeStatus.CLOSED.value,
                    datetime.now(), datetime.now(), trade_id, user_id
                ),
            )
            await db.commit()

            if cursor.rowcount == 0:
                logger.warning(f"Trade #{trade_id} not found or not owned by user {user_id}")
                return False

        logger.info(f"Closed trade #{trade_id} for user {user_id}: PnL=${pnl:.2f}")
        return True

    async def get_trade(self, user_id: int, trade_id: int) -> Optional[Trade]:
        """
        Get a specific trade by ID (user-filtered).

        Args:
            user_id: Owner user ID
            trade_id: Trade ID

        Returns:
            Trade object or None if not found/not owned
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trades WHERE id = ? AND user_id = ?",
                (trade_id, user_id),
            )
            row = await cursor.fetchone()

            if row:
                return self._row_to_trade(row)

        return None

    async def get_trade_by_order_id(self, user_id: int, order_id: str) -> Optional[Trade]:
        """
        Get a trade by its exchange order ID (user-filtered).

        Args:
            user_id: Owner user ID
            order_id: Exchange order ID

        Returns:
            Trade object or None
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trades WHERE order_id = ? AND user_id = ?",
                (order_id, user_id),
            )
            row = await cursor.fetchone()

            if row:
                return self._row_to_trade(row)

        return None

    async def get_open_trades(self, user_id: int, symbol: Optional[str] = None) -> List[Trade]:
        """
        Get all open trades for a user.

        Args:
            user_id: Owner user ID
            symbol: Optional symbol filter

        Returns:
            List of open trades
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            if symbol:
                cursor = await db.execute(
                    """
                    SELECT * FROM trades
                    WHERE status = ? AND user_id = ? AND symbol = ?
                    ORDER BY entry_time DESC
                    """,
                    (TradeStatus.OPEN.value, user_id, symbol),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT * FROM trades
                    WHERE status = ? AND user_id = ?
                    ORDER BY entry_time DESC
                    """,
                    (TradeStatus.OPEN.value, user_id),
                )

            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    async def get_trades_for_date(self, user_id: int, date: str) -> List[Trade]:
        """
        Get all trades for a specific date (user-filtered).

        Args:
            user_id: Owner user ID
            date: Date string (YYYY-MM-DD)

        Returns:
            List of trades
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM trades
                WHERE DATE(entry_time) = ? AND user_id = ?
                ORDER BY entry_time ASC
                """,
                (date, user_id),
            )
            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    async def get_recent_trades(self, user_id: int, limit: int = 50) -> List[Trade]:
        """
        Get recent trades for a user.

        Args:
            user_id: Owner user ID
            limit: Number of trades to fetch

        Returns:
            List of recent trades
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trades WHERE user_id = ? ORDER BY entry_time DESC LIMIT ?",
                (user_id, limit),
            )
            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    async def get_trades_by_year(self, user_id: int, year: int) -> List[Trade]:
        """
        Get all closed trades for a specific calendar year (user-filtered).

        Args:
            user_id: Owner user ID
            year: Calendar year (e.g., 2025)

        Returns:
            List of closed trades for the year
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM trades
                WHERE strftime('%Y', entry_time) = ?
                AND status = 'closed'
                AND user_id = ?
                ORDER BY entry_time ASC
                """,
                (str(year), user_id),
            )
            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    async def get_statistics(self, user_id: int, days: int = 30) -> dict:
        """
        Calculate trading statistics for a user over a period.

        Args:
            user_id: Owner user ID
            days: Number of days to analyze

        Returns:
            Statistics dictionary
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losing_trades,
                    SUM(pnl) as total_pnl,
                    SUM(fees) as total_fees,
                    SUM(funding_paid) as total_funding,
                    AVG(pnl_percent) as avg_pnl_percent,
                    MAX(pnl) as best_trade,
                    MIN(pnl) as worst_trade
                FROM trades
                WHERE status = 'closed'
                AND user_id = ?
                AND entry_time >= DATE('now', ?)
                """,
                (user_id, f"-{days} days"),
            )
            row = await cursor.fetchone()

            if row and row[0]:
                total_trades = row[0]
                winning_trades = row[1] or 0
                losing_trades = row[2] or 0
                total_pnl = row[3] or 0
                total_fees = row[4] or 0
                total_funding = row[5] or 0
                avg_pnl_percent = row[6] or 0
                best_trade = row[7] or 0
                worst_trade = row[8] or 0

                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

                return {
                    "user_id": user_id,
                    "period_days": days,
                    "total_trades": total_trades,
                    "winning_trades": winning_trades,
                    "losing_trades": losing_trades,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "total_fees": total_fees,
                    "total_funding": total_funding,
                    "net_pnl": total_pnl - total_fees - abs(total_funding),
                    "avg_pnl_percent": avg_pnl_percent,
                    "best_trade": best_trade,
                    "worst_trade": worst_trade,
                }

        return {
            "user_id": user_id,
            "period_days": days,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "total_funding": 0.0,
            "net_pnl": 0.0,
            "avg_pnl_percent": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
        }

    async def count_trades_today(self, user_id: int) -> int:
        """
        Count the number of trades executed today by a user.

        Args:
            user_id: Owner user ID

        Returns:
            Number of trades today
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM trades
                WHERE DATE(entry_time) = DATE('now') AND user_id = ?
                """,
                (user_id,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_daily_pnl(self, user_id: int, date: str) -> float:
        """
        Get total PnL for a specific date.

        Args:
            user_id: Owner user ID
            date: Date string (YYYY-MM-DD)

        Returns:
            Total PnL for the date
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT COALESCE(SUM(pnl), 0) FROM trades
                WHERE DATE(exit_time) = ? AND user_id = ? AND status = 'closed'
                """,
                (date, user_id),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0.0

    async def update_entry_price(
        self,
        user_id: int,
        trade_id: int,
        actual_entry_price: float,
    ) -> bool:
        """
        Update the entry price with actual fill price (user-verified).

        Args:
            user_id: Owner user ID
            trade_id: Trade ID to update
            actual_entry_price: Actual fill price from exchange

        Returns:
            True if updated successfully
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE trades SET
                    entry_price = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (actual_entry_price, datetime.now(), trade_id, user_id),
            )
            await db.commit()

            if cursor.rowcount == 0:
                return False

        logger.info(f"Updated trade #{trade_id} entry price to ${actual_entry_price:.2f}")
        return True

    async def cancel_trade(self, user_id: int, trade_id: int, reason: str = "cancelled") -> bool:
        """
        Cancel a trade (user-verified).

        Args:
            user_id: Owner user ID
            trade_id: Trade ID to cancel
            reason: Cancellation reason

        Returns:
            True if cancelled successfully
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE trades SET
                    status = ?,
                    exit_reason = ?,
                    exit_time = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ? AND status = ?
                """,
                (
                    TradeStatus.CANCELLED.value, reason, datetime.now(),
                    datetime.now(), trade_id, user_id, TradeStatus.OPEN.value
                ),
            )
            await db.commit()

            if cursor.rowcount == 0:
                return False

        logger.info(f"Cancelled trade #{trade_id} for user {user_id}: {reason}")
        return True

    def _row_to_trade(self, row) -> Trade:
        """Convert a database row to a Trade object."""
        return Trade(
            id=row["id"],
            user_id=row["user_id"] or 0,
            symbol=row["symbol"],
            side=row["side"],
            size=row["size"],
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            take_profit=row["take_profit"],
            stop_loss=row["stop_loss"],
            leverage=row["leverage"],
            confidence=row["confidence"],
            reason=row["reason"],
            order_id=row["order_id"],
            close_order_id=row["close_order_id"],
            status=TradeStatus(row["status"]),
            pnl=row["pnl"],
            pnl_percent=row["pnl_percent"],
            fees=row["fees"],
            funding_paid=row["funding_paid"],
            entry_time=datetime.fromisoformat(row["entry_time"]) if row["entry_time"] else None,
            exit_time=datetime.fromisoformat(row["exit_time"]) if row["exit_time"] else None,
            exit_reason=row["exit_reason"],
            metrics_snapshot=row["metrics_snapshot"] or "{}",
        )
