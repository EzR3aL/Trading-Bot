"""
Funding Rate Tracker Module.

Tracks and stores funding rate payments over time for accurate PnL calculation.
Funding rates are paid every 8 hours on most exchanges.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

import aiosqlite

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FundingPayment:
    """Single funding payment record."""
    id: Optional[int]
    symbol: str
    timestamp: datetime
    funding_rate: float
    position_size: float
    position_value: float
    payment_amount: float  # Positive = paid, Negative = received
    side: str  # "long" or "short"
    trade_id: Optional[int]  # Associated trade ID

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "funding_rate": self.funding_rate,
            "position_size": self.position_size,
            "position_value": self.position_value,
            "payment_amount": self.payment_amount,
            "side": self.side,
            "trade_id": self.trade_id,
        }


@dataclass
class FundingStats:
    """Aggregated funding statistics."""
    total_paid: float
    total_received: float
    net_funding: float
    payment_count: int
    avg_rate: float
    highest_rate: float
    lowest_rate: float


class FundingTracker:
    """
    Tracks funding rate payments for open positions.

    Features:
    - Records all funding payments to SQLite database
    - Calculates funding costs per trade
    - Provides historical funding analysis
    - Integrates with position monitoring
    """

    # Funding payment times (UTC hours)
    FUNDING_HOURS = [0, 8, 16]

    def __init__(self, db_path: str = "data/funding_tracker.db"):
        """
        Initialize the funding tracker.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Initialize the database connection and create tables."""
        self._db = await aiosqlite.connect(self.db_path)

        # Enable WAL mode for better concurrency
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")  # 5 second timeout for locks

        await self._create_tables()
        logger.info("Funding tracker initialized")

    async def _create_tables(self):
        """Create necessary database tables."""
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS funding_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                funding_rate REAL NOT NULL,
                position_size REAL NOT NULL,
                position_value REAL NOT NULL,
                payment_amount REAL NOT NULL,
                side TEXT NOT NULL,
                trade_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS funding_rates_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                funding_rate REAL NOT NULL,
                next_funding_time TEXT,
                UNIQUE(symbol, timestamp)
            )
        """)

        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_funding_payments_symbol
            ON funding_payments(symbol)
        """)

        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_funding_payments_trade_id
            ON funding_payments(trade_id)
        """)

        await self._db.commit()

    async def close(self):
        """Close the database connection."""
        if self._db:
            await self._db.close()

    async def record_funding_rate(
        self,
        symbol: str,
        funding_rate: float,
        next_funding_time: Optional[datetime] = None
    ):
        """
        Record a funding rate snapshot.

        Args:
            symbol: Trading pair
            funding_rate: Current funding rate
            next_funding_time: Next funding payment time
        """
        timestamp = datetime.utcnow().isoformat()
        next_time = next_funding_time.isoformat() if next_funding_time else None

        try:
            await self._db.execute("""
                INSERT OR REPLACE INTO funding_rates_history
                (symbol, timestamp, funding_rate, next_funding_time)
                VALUES (?, ?, ?, ?)
            """, (symbol, timestamp, funding_rate, next_time))
            await self._db.commit()
        except Exception as e:
            logger.error(f"Error recording funding rate: {e}")

    async def record_funding_payment(
        self,
        symbol: str,
        funding_rate: float,
        position_size: float,
        position_value: float,
        side: str,
        trade_id: Optional[int] = None
    ) -> Optional[FundingPayment]:
        """
        Record a funding payment for an open position.

        Args:
            symbol: Trading pair
            funding_rate: Current funding rate
            position_size: Position size in base currency
            position_value: Position value in USDT
            side: "long" or "short"
            trade_id: Associated trade ID

        Returns:
            FundingPayment record
        """
        timestamp = datetime.utcnow()

        # Calculate payment amount
        # Long positions pay when rate is positive, receive when negative
        # Short positions receive when rate is positive, pay when negative
        if side.lower() == "long":
            payment_amount = position_value * funding_rate
        else:
            payment_amount = -position_value * funding_rate

        try:
            cursor = await self._db.execute("""
                INSERT INTO funding_payments
                (symbol, timestamp, funding_rate, position_size, position_value,
                 payment_amount, side, trade_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol,
                timestamp.isoformat(),
                funding_rate,
                position_size,
                position_value,
                payment_amount,
                side.lower(),
                trade_id
            ))
            await self._db.commit()

            payment = FundingPayment(
                id=cursor.lastrowid,
                symbol=symbol,
                timestamp=timestamp,
                funding_rate=funding_rate,
                position_size=position_size,
                position_value=position_value,
                payment_amount=payment_amount,
                side=side.lower(),
                trade_id=trade_id
            )

            logger.info(
                f"Funding payment recorded: {symbol} {side} | "
                f"Rate: {funding_rate*100:.4f}% | Amount: ${payment_amount:.4f}"
            )

            return payment

        except Exception as e:
            logger.error(f"Error recording funding payment: {e}")
            return None

    async def get_trade_funding(self, trade_id: int) -> List[FundingPayment]:
        """
        Get all funding payments for a specific trade.

        Args:
            trade_id: Trade ID

        Returns:
            List of funding payments
        """
        cursor = await self._db.execute("""
            SELECT id, symbol, timestamp, funding_rate, position_size,
                   position_value, payment_amount, side, trade_id
            FROM funding_payments
            WHERE trade_id = ?
            ORDER BY timestamp ASC
        """, (trade_id,))

        rows = await cursor.fetchall()
        payments = []

        for row in rows:
            payments.append(FundingPayment(
                id=row[0],
                symbol=row[1],
                timestamp=datetime.fromisoformat(row[2]),
                funding_rate=row[3],
                position_size=row[4],
                position_value=row[5],
                payment_amount=row[6],
                side=row[7],
                trade_id=row[8]
            ))

        return payments

    async def get_total_funding_for_trade(self, trade_id: int) -> float:
        """
        Get total funding paid/received for a trade.

        Args:
            trade_id: Trade ID

        Returns:
            Total funding amount (positive = paid, negative = received)
        """
        cursor = await self._db.execute("""
            SELECT COALESCE(SUM(payment_amount), 0)
            FROM funding_payments
            WHERE trade_id = ?
        """, (trade_id,))

        row = await cursor.fetchone()
        return row[0] if row else 0.0

    async def get_funding_stats(
        self,
        symbol: Optional[str] = None,
        days: int = 30
    ) -> FundingStats:
        """
        Get aggregated funding statistics.

        Args:
            symbol: Filter by symbol (optional)
            days: Number of days to analyze

        Returns:
            FundingStats object
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        if symbol:
            cursor = await self._db.execute("""
                SELECT
                    SUM(CASE WHEN payment_amount > 0 THEN payment_amount ELSE 0 END),
                    SUM(CASE WHEN payment_amount < 0 THEN ABS(payment_amount) ELSE 0 END),
                    SUM(payment_amount),
                    COUNT(*),
                    AVG(funding_rate),
                    MAX(funding_rate),
                    MIN(funding_rate)
                FROM funding_payments
                WHERE symbol = ? AND timestamp > ?
            """, (symbol, cutoff))
        else:
            cursor = await self._db.execute("""
                SELECT
                    SUM(CASE WHEN payment_amount > 0 THEN payment_amount ELSE 0 END),
                    SUM(CASE WHEN payment_amount < 0 THEN ABS(payment_amount) ELSE 0 END),
                    SUM(payment_amount),
                    COUNT(*),
                    AVG(funding_rate),
                    MAX(funding_rate),
                    MIN(funding_rate)
                FROM funding_payments
                WHERE timestamp > ?
            """, (cutoff,))

        row = await cursor.fetchone()

        return FundingStats(
            total_paid=row[0] or 0.0,
            total_received=row[1] or 0.0,
            net_funding=row[2] or 0.0,
            payment_count=row[3] or 0,
            avg_rate=row[4] or 0.0,
            highest_rate=row[5] or 0.0,
            lowest_rate=row[6] or 0.0
        )

    async def get_recent_payments(self, limit: int = 50) -> List[FundingPayment]:
        """
        Get recent funding payments.

        Args:
            limit: Maximum number of payments to return

        Returns:
            List of recent funding payments
        """
        cursor = await self._db.execute("""
            SELECT id, symbol, timestamp, funding_rate, position_size,
                   position_value, payment_amount, side, trade_id
            FROM funding_payments
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))

        rows = await cursor.fetchall()
        payments = []

        for row in rows:
            payments.append(FundingPayment(
                id=row[0],
                symbol=row[1],
                timestamp=datetime.fromisoformat(row[2]),
                funding_rate=row[3],
                position_size=row[4],
                position_value=row[5],
                payment_amount=row[6],
                side=row[7],
                trade_id=row[8]
            ))

        return payments

    async def get_funding_rate_history(
        self,
        symbol: str,
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """
        Get funding rate history for a symbol.

        Args:
            symbol: Trading pair
            days: Number of days

        Returns:
            List of funding rate records
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        cursor = await self._db.execute("""
            SELECT timestamp, funding_rate
            FROM funding_rates_history
            WHERE symbol = ? AND timestamp > ?
            ORDER BY timestamp ASC
        """, (symbol, cutoff))

        rows = await cursor.fetchall()
        return [{"timestamp": row[0], "rate": row[1]} for row in rows]

    def is_funding_time(self) -> bool:
        """
        Check if current time is near a funding payment time.

        Returns:
            True if within 5 minutes of funding time
        """
        now = datetime.utcnow()
        current_hour = now.hour
        current_minute = now.minute

        for funding_hour in self.FUNDING_HOURS:
            if current_hour == funding_hour and current_minute < 5:
                return True

        return False

    async def get_daily_funding_summary(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily funding summary.

        Args:
            days: Number of days

        Returns:
            List of daily summaries
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        cursor = await self._db.execute("""
            SELECT
                DATE(timestamp) as date,
                SUM(payment_amount) as total,
                COUNT(*) as count,
                AVG(funding_rate) as avg_rate
            FROM funding_payments
            WHERE timestamp > ?
            GROUP BY DATE(timestamp)
            ORDER BY date DESC
        """, (cutoff,))

        rows = await cursor.fetchall()
        return [
            {
                "date": row[0],
                "total": row[1],
                "count": row[2],
                "avg_rate": row[3]
            }
            for row in rows
        ]
