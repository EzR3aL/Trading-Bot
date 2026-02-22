"""Normalized data types shared across all exchange adapters."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Balance:
    """Account balance information."""
    total: float
    available: float
    unrealized_pnl: float
    currency: str = "USDT"


@dataclass
class Order:
    """Normalized order representation."""
    order_id: str
    symbol: str
    side: str          # "long" | "short"
    size: float
    price: float
    status: str        # "filled" | "pending" | "cancelled" | "partial"
    exchange: str
    timestamp: Optional[datetime] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    leverage: Optional[int] = None
    fee: float = 0.0
    client_order_id: Optional[str] = None
    tpsl_failed: bool = False


@dataclass
class Position:
    """Normalized open position representation."""
    symbol: str
    side: str          # "long" | "short"
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    leverage: int
    exchange: str
    margin: float = 0.0
    liquidation_price: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None


@dataclass
class Ticker:
    """Market ticker data."""
    symbol: str
    last_price: float
    bid: float
    ask: float
    volume_24h: float
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    change_24h_percent: Optional[float] = None


@dataclass
class FundingRateInfo:
    """Funding rate information for perpetual futures."""
    symbol: str
    current_rate: float
    next_funding_time: Optional[datetime] = None
    predicted_rate: Optional[float] = None
