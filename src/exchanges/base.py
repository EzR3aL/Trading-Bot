"""
Exchange Adapter Base Classes.

Defines the interface that all exchange adapters must implement
for unified cross-exchange operations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ExchangeTicker:
    """Standardized ticker data from any exchange."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    last: float
    volume_24h: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid and self.ask else self.last

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return 0.0
        return ((self.ask - self.bid) / self.mid) * 100

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "mid": round(self.mid, 4),
            "spread_pct": round(self.spread_pct, 6),
            "volume_24h": self.volume_24h,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ExchangeBalance:
    """Standardized balance from any exchange."""
    exchange: str
    currency: str
    available: float
    locked: float
    total: float

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "currency": self.currency,
            "available": self.available,
            "locked": self.locked,
            "total": self.total,
        }


@dataclass
class ExchangeFundingRate:
    """Standardized funding rate from any exchange."""
    exchange: str
    symbol: str
    rate: float
    next_funding_time: Optional[datetime] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "symbol": self.symbol,
            "rate": self.rate,
            "rate_pct": f"{self.rate * 100:.4f}%",
            "next_funding_time": self.next_funding_time.isoformat() if self.next_funding_time else None,
            "timestamp": self.timestamp.isoformat(),
        }


class ExchangeAdapter(ABC):
    """
    Abstract base class for exchange adapters.

    All exchange integrations must implement this interface
    to enable unified cross-exchange operations.
    """

    def __init__(self, name: str):
        self.name = name
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self):
        """Establish connection to the exchange."""

    @abstractmethod
    async def disconnect(self):
        """Disconnect from the exchange."""

    @abstractmethod
    async def get_ticker(self, symbol: str) -> ExchangeTicker:
        """Get current ticker data for a symbol."""

    @abstractmethod
    async def get_tickers(self, symbols: List[str]) -> Dict[str, ExchangeTicker]:
        """Get tickers for multiple symbols."""

    @abstractmethod
    async def get_funding_rate(self, symbol: str) -> ExchangeFundingRate:
        """Get current funding rate."""

    @abstractmethod
    async def get_balance(self, currency: str = "USDT") -> ExchangeBalance:
        """Get account balance."""

    @abstractmethod
    async def get_supported_symbols(self) -> List[str]:
        """Get list of supported trading symbols."""
