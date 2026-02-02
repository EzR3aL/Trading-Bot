"""
Orderbook Analyzer for Smart Execution.

Analyzes orderbook depth to determine optimal entry points
and detect potential slippage before execution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OrderbookLevel:
    """A single price level in the orderbook."""
    price: float
    size: float
    cumulative_size: float = 0.0
    cumulative_value: float = 0.0


@dataclass
class OrderbookSnapshot:
    """Snapshot of the orderbook at a point in time."""
    symbol: str
    bids: List[OrderbookLevel] = field(default_factory=list)
    asks: List[OrderbookLevel] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def best_bid(self) -> float:
        """Best (highest) bid price."""
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        """Best (lowest) ask price."""
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        """Mid-market price."""
        if not self.bids or not self.asks:
            return 0.0
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> float:
        """Absolute bid-ask spread."""
        if not self.bids or not self.asks:
            return 0.0
        return self.best_ask - self.best_bid

    @property
    def spread_pct(self) -> float:
        """Spread as percentage of mid price."""
        mid = self.mid_price
        if mid <= 0:
            return 0.0
        return (self.spread / mid) * 100

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": round(self.mid_price, 2),
            "spread": round(self.spread, 4),
            "spread_pct": round(self.spread_pct, 6),
            "bid_depth": len(self.bids),
            "ask_depth": len(self.asks),
            "timestamp": self.timestamp.isoformat(),
        }


class OrderbookAnalyzer:
    """
    Analyzes orderbook data for execution optimization.

    Provides:
    - Spread analysis
    - Depth analysis (can the order be filled at desired price?)
    - Slippage estimation
    - Bid/ask imbalance detection
    """

    def __init__(self, max_depth: int = 20):
        """
        Initialize the orderbook analyzer.

        Args:
            max_depth: Maximum orderbook levels to analyze
        """
        self.max_depth = max_depth
        self._snapshots: Dict[str, OrderbookSnapshot] = {}

    def create_snapshot(
        self,
        symbol: str,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ) -> OrderbookSnapshot:
        """
        Create an orderbook snapshot from raw bid/ask data.

        Args:
            symbol: Trading pair
            bids: List of (price, size) tuples, sorted high to low
            asks: List of (price, size) tuples, sorted low to high

        Returns:
            OrderbookSnapshot
        """
        bid_levels = []
        cumulative = 0.0
        cum_value = 0.0
        for price, size in bids[:self.max_depth]:
            cumulative += size
            cum_value += price * size
            bid_levels.append(OrderbookLevel(
                price=price, size=size,
                cumulative_size=cumulative, cumulative_value=cum_value,
            ))

        ask_levels = []
        cumulative = 0.0
        cum_value = 0.0
        for price, size in asks[:self.max_depth]:
            cumulative += size
            cum_value += price * size
            ask_levels.append(OrderbookLevel(
                price=price, size=size,
                cumulative_size=cumulative, cumulative_value=cum_value,
            ))

        snapshot = OrderbookSnapshot(
            symbol=symbol, bids=bid_levels, asks=ask_levels,
        )
        self._snapshots[symbol] = snapshot
        return snapshot

    def estimate_slippage(
        self,
        snapshot: OrderbookSnapshot,
        side: str,
        size: float,
    ) -> dict:
        """
        Estimate slippage for an order of a given size.

        Args:
            snapshot: Orderbook snapshot
            side: "buy" or "sell"
            size: Order size in base currency

        Returns:
            Slippage estimation dict
        """
        if side == "buy":
            levels = snapshot.asks
            reference_price = snapshot.best_ask
        else:
            levels = snapshot.bids
            reference_price = snapshot.best_bid

        if not levels or reference_price <= 0:
            return {
                "estimatable": False,
                "reason": "Insufficient orderbook data",
            }

        filled = 0.0
        total_cost = 0.0

        for level in levels:
            available = level.size
            to_fill = min(available, size - filled)
            total_cost += to_fill * level.price
            filled += to_fill

            if filled >= size:
                break

        if filled < size:
            return {
                "estimatable": False,
                "reason": f"Insufficient depth: can fill {filled:.4f} of {size:.4f}",
                "available_depth": round(filled, 8),
            }

        avg_price = total_cost / filled
        slippage_pct = abs(avg_price - reference_price) / reference_price * 100

        return {
            "estimatable": True,
            "reference_price": reference_price,
            "estimated_avg_price": round(avg_price, 4),
            "estimated_slippage_pct": round(slippage_pct, 6),
            "estimated_slippage_usd": round(abs(avg_price - reference_price) * size, 4),
            "levels_consumed": min(len(levels), sum(1 for l in levels if l.cumulative_size <= size) + 1),
        }

    def get_depth_at_price(
        self,
        snapshot: OrderbookSnapshot,
        side: str,
        price_distance_pct: float = 1.0,
    ) -> dict:
        """
        Get total depth within a price distance from best price.

        Args:
            snapshot: Orderbook snapshot
            side: "buy" (asks) or "sell" (bids)
            price_distance_pct: Price distance percentage from best price

        Returns:
            Depth information
        """
        if side == "buy":
            levels = snapshot.asks
            reference = snapshot.best_ask
            limit_price = reference * (1 + price_distance_pct / 100)
        else:
            levels = snapshot.bids
            reference = snapshot.best_bid
            limit_price = reference * (1 - price_distance_pct / 100)

        total_size = 0.0
        total_value = 0.0
        level_count = 0

        for level in levels:
            if side == "buy" and level.price > limit_price:
                break
            if side == "sell" and level.price < limit_price:
                break
            total_size += level.size
            total_value += level.price * level.size
            level_count += 1

        return {
            "side": side,
            "price_distance_pct": price_distance_pct,
            "reference_price": reference,
            "limit_price": round(limit_price, 4),
            "total_size": round(total_size, 8),
            "total_value": round(total_value, 2),
            "levels": level_count,
        }

    def get_imbalance(self, snapshot: OrderbookSnapshot, levels: int = 5) -> dict:
        """
        Calculate bid/ask imbalance from top N levels.

        Imbalance > 0: more buy pressure (bullish)
        Imbalance < 0: more sell pressure (bearish)

        Args:
            snapshot: Orderbook snapshot
            levels: Number of levels to analyze

        Returns:
            Imbalance analysis
        """
        bid_volume = sum(b.size for b in snapshot.bids[:levels])
        ask_volume = sum(a.size for a in snapshot.asks[:levels])
        total = bid_volume + ask_volume

        if total == 0:
            return {
                "imbalance": 0.0,
                "bid_volume": 0.0,
                "ask_volume": 0.0,
                "interpretation": "No data",
            }

        imbalance = (bid_volume - ask_volume) / total  # -1 to +1

        if imbalance > 0.3:
            interpretation = "Strong buy pressure"
        elif imbalance > 0.1:
            interpretation = "Moderate buy pressure"
        elif imbalance < -0.3:
            interpretation = "Strong sell pressure"
        elif imbalance < -0.1:
            interpretation = "Moderate sell pressure"
        else:
            interpretation = "Balanced"

        return {
            "imbalance": round(imbalance, 4),
            "bid_volume": round(bid_volume, 4),
            "ask_volume": round(ask_volume, 4),
            "bid_pct": round(bid_volume / total * 100, 2),
            "ask_pct": round(ask_volume / total * 100, 2),
            "levels_analyzed": levels,
            "interpretation": interpretation,
        }

    def get_snapshot(self, symbol: str) -> Optional[OrderbookSnapshot]:
        """Get the latest snapshot for a symbol."""
        return self._snapshots.get(symbol)
