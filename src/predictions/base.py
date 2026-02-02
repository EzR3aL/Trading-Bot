"""
Prediction Markets Base Classes.

Defines standardized data structures and the platform adapter
interface for prediction market integrations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarketStatus(str, Enum):
    """Status of a prediction market."""
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"
    DISPUTED = "disputed"


@dataclass
class MarketOutcome:
    """A single outcome in a prediction market (e.g., YES or NO)."""
    name: str
    price: float  # 0.0 to 1.0 (probability as price)
    volume_24h: float = 0.0
    liquidity: float = 0.0  # Available liquidity at this price
    last_traded: Optional[datetime] = None

    @property
    def implied_probability(self) -> float:
        """Price directly represents implied probability."""
        return max(0.0, min(1.0, self.price))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": round(self.price, 4),
            "implied_probability": round(self.implied_probability, 4),
            "volume_24h": round(self.volume_24h, 2),
            "liquidity": round(self.liquidity, 2),
            "last_traded": self.last_traded.isoformat() if self.last_traded else None,
        }


@dataclass
class PredictionContract:
    """
    A single prediction contract within a market.

    Binary markets have two outcomes (YES/NO).
    Multi-outcome markets have N outcomes.
    """
    contract_id: str
    market_id: str
    question: str
    outcomes: List[MarketOutcome]
    status: MarketStatus = MarketStatus.OPEN
    resolution_date: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_implied_probability(self) -> float:
        """Sum of all outcome probabilities. Should be ~1.0 for efficient market."""
        return sum(o.implied_probability for o in self.outcomes)

    @property
    def overround(self) -> float:
        """
        Market overround (vig/juice).

        Values > 1.0 mean the market-maker has an edge.
        Values < 1.0 mean there's a guaranteed arb.
        """
        return self.total_implied_probability

    @property
    def is_binary(self) -> bool:
        return len(self.outcomes) == 2

    @property
    def total_volume(self) -> float:
        return sum(o.volume_24h for o in self.outcomes)

    @property
    def total_liquidity(self) -> float:
        return sum(o.liquidity for o in self.outcomes)

    def to_dict(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "market_id": self.market_id,
            "question": self.question,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "total_implied_probability": round(self.total_implied_probability, 4),
            "overround": round(self.overround, 4),
            "is_binary": self.is_binary,
            "status": self.status.value,
            "total_volume": round(self.total_volume, 2),
            "total_liquidity": round(self.total_liquidity, 2),
            "resolution_date": self.resolution_date.isoformat() if self.resolution_date else None,
        }


@dataclass
class PredictionMarket:
    """A prediction market containing one or more contracts."""
    market_id: str
    platform: str
    title: str
    category: str
    contracts: List[PredictionContract] = field(default_factory=list)
    url: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_volume(self) -> float:
        return sum(c.total_volume for c in self.contracts)

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "platform": self.platform,
            "title": self.title,
            "category": self.category,
            "contracts": [c.to_dict() for c in self.contracts],
            "total_volume": round(self.total_volume, 2),
            "url": self.url,
        }


class PredictionPlatform(ABC):
    """
    Abstract base class for prediction market platform adapters.

    All prediction market integrations must implement this interface
    for unified scanning and execution.
    """

    def __init__(self, name: str):
        self.name = name
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self):
        """Establish connection to the platform."""

    @abstractmethod
    async def disconnect(self):
        """Disconnect from the platform."""

    @abstractmethod
    async def get_markets(self, category: Optional[str] = None,
                          limit: int = 50) -> List[PredictionMarket]:
        """Get active markets, optionally filtered by category."""

    @abstractmethod
    async def get_market(self, market_id: str) -> PredictionMarket:
        """Get a specific market by ID."""

    @abstractmethod
    async def get_contract(self, contract_id: str) -> PredictionContract:
        """Get a specific contract by ID."""

    @abstractmethod
    async def get_orderbook(self, contract_id: str, outcome: str) -> Dict:
        """Get orderbook for a specific outcome."""
