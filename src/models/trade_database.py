"""
Trade Database for persistent trade tracking.

Uses SQLite for lightweight, local storage of all trade history.
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
    """Trade record dataclass."""
    id: Optional[int]
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


class TradeDatabase:
    """
    SQLite database for trade persistence.

    Provides methods for:
    - Creating trades
    - Updating trade status
    - Querying trade history
    - Calculating statistics
    """

    def __init__(self, db_path: str = "data/trades.db"):
        """
        Initialize the trade database.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the database schema."""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

            # Create indexes for common queries
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)")

            await db.commit()

        self._initialized = True
        logger.info(f"Trade database initialized at {self.db_path}")

    async def create_trade(
        self,
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
        Create a new trade record.

        Args:
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
                    symbol, side, size, entry_price, take_profit, stop_loss,
                    leverage, confidence, reason, order_id, status,
                    entry_time, metrics_snapshot
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol, side, size, entry_price, take_profit, stop_loss,
                    leverage, confidence, reason, order_id, TradeStatus.OPEN.value,
                    datetime.now(), metrics_snapshot
                ),
            )
            await db.commit()
            trade_id = cursor.lastrowid

        logger.info(f"Created trade #{trade_id}: {side.upper()} {size} {symbol} @ ${entry_price}")
        return trade_id

    async def close_trade(
        self,
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
        Close an existing trade.

        Args:
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
            await db.execute(
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
                WHERE id = ?
                """,
                (
                    exit_price, pnl, pnl_percent, fees, funding_paid,
                    exit_reason, close_order_id, TradeStatus.CLOSED.value,
                    datetime.now(), datetime.now(), trade_id
                ),
            )
            await db.commit()

        logger.info(f"Closed trade #{trade_id}: PnL=${pnl:.2f} ({pnl_percent:+.2f}%)")
        return True

    async def update_entry_price(
        self,
        trade_id: int,
        actual_entry_price: float,
        slippage: Optional[float] = None,
    ) -> bool:
        """
        Update the entry price with the actual fill price from the exchange.

        This should be called after order execution to record the real fill price
        instead of the signal's estimated entry price.

        Args:
            trade_id: Trade ID to update
            actual_entry_price: Actual fill price from exchange
            slippage: Optional slippage amount (actual - expected)

        Returns:
            True if updated successfully
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # Get current trade to calculate slippage if not provided
            if slippage is not None:
                await db.execute(
                    """
                    UPDATE trades SET
                        entry_price = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (actual_entry_price, datetime.now(), trade_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE trades SET
                        entry_price = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (actual_entry_price, datetime.now(), trade_id),
                )
            await db.commit()

        logger.info(f"Updated trade #{trade_id} entry price to ${actual_entry_price:.2f}")
        return True

    async def get_trade(self, trade_id: int) -> Optional[Trade]:
        """
        Get a specific trade by ID.

        Args:
            trade_id: Trade ID

        Returns:
            Trade object or None
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trades WHERE id = ?",
                (trade_id,),
            )
            row = await cursor.fetchone()

            if row:
                return self._row_to_trade(row)

        return None

    async def get_trade_by_order_id(self, order_id: str) -> Optional[Trade]:
        """
        Get a trade by its exchange order ID.

        Args:
            order_id: Exchange order ID

        Returns:
            Trade object or None
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trades WHERE order_id = ?",
                (order_id,),
            )
            row = await cursor.fetchone()

            if row:
                return self._row_to_trade(row)

        return None

    async def get_open_trades(self, symbol: Optional[str] = None) -> List[Trade]:
        """
        Get all open trades.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open trades
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            if symbol:
                cursor = await db.execute(
                    "SELECT * FROM trades WHERE status = ? AND symbol = ? ORDER BY entry_time DESC",
                    (TradeStatus.OPEN.value, symbol),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM trades WHERE status = ? ORDER BY entry_time DESC",
                    (TradeStatus.OPEN.value,),
                )

            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    async def get_trades_for_date(self, date: str) -> List[Trade]:
        """
        Get all trades for a specific date.

        Args:
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
                WHERE DATE(entry_time) = ?
                ORDER BY entry_time ASC
                """,
                (date,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    async def get_recent_trades(self, limit: int = 50) -> List[Trade]:
        """
        Get recent trades.

        Args:
            limit: Number of trades to fetch

        Returns:
            List of recent trades
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_trade(row) for row in rows]

    async def get_statistics(self, days: int = 30) -> dict:
        """
        Calculate trading statistics over a period.

        Args:
            days: Number of days to analyze

        Returns:
            Statistics dictionary
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            # Total trades
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
                AND entry_time >= DATE('now', ?)
                """,
                (f"-{days} days",),
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

    async def count_trades_today(self) -> int:
        """
        Count the number of trades executed today.

        Returns:
            Number of trades today
        """
        await self.initialize()

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM trades WHERE DATE(entry_time) = DATE('now')"
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    def _row_to_trade(self, row) -> Trade:
        """Convert a database row to a Trade object."""
        return Trade(
            id=row["id"],
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
