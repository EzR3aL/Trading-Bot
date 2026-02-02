"""
Prediction Market Execution Engine.

Handles order execution for prediction market trades with
slippage protection and parallel execution capabilities.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class OrderSide(str, Enum):
    """Order side for prediction market trades."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class PredictionOrder:
    """A single order in a prediction market."""
    order_id: str
    contract_id: str
    outcome: str
    side: OrderSide
    price: float
    size: float  # Number of contracts (each pays $1 on resolution)
    max_slippage_pct: float = 2.0

    @property
    def notional_value(self) -> float:
        """Total cost of the order."""
        return self.price * self.size

    @property
    def max_fill_price(self) -> float:
        """Maximum acceptable fill price (for buys)."""
        if self.side == OrderSide.BUY:
            return self.price * (1 + self.max_slippage_pct / 100)
        return self.price

    @property
    def min_fill_price(self) -> float:
        """Minimum acceptable fill price (for sells)."""
        if self.side == OrderSide.SELL:
            return self.price * (1 - self.max_slippage_pct / 100)
        return 0.0

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "contract_id": self.contract_id,
            "outcome": self.outcome,
            "side": self.side.value,
            "price": round(self.price, 4),
            "size": round(self.size, 4),
            "notional_value": round(self.notional_value, 4),
            "max_slippage_pct": self.max_slippage_pct,
        }


@dataclass
class FillResult:
    """Result of an order execution attempt."""
    order_id: str
    filled: bool
    fill_price: float = 0.0
    fill_size: float = 0.0
    slippage_pct: float = 0.0
    fees_paid: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_cost(self) -> float:
        return (self.fill_price * self.fill_size) + self.fees_paid

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "filled": self.filled,
            "fill_price": round(self.fill_price, 4),
            "fill_size": round(self.fill_size, 4),
            "slippage_pct": round(self.slippage_pct, 4),
            "fees_paid": round(self.fees_paid, 4),
            "total_cost": round(self.total_cost, 4),
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


class PredictionExecutor:
    """
    Execution engine for prediction market trades.

    Supports parallel execution of arbitrage legs with
    slippage protection and VWAP-style order splitting.
    """

    def __init__(
        self,
        max_slippage_pct: float = 2.0,
        max_position_usd: float = 500.0,
        min_edge_after_slippage: float = 0.1,
    ):
        """
        Initialize the prediction executor.

        Args:
            max_slippage_pct: Maximum allowed slippage per leg (%)
            max_position_usd: Maximum position size per trade ($)
            min_edge_after_slippage: Minimum edge to proceed after slippage check (%)
        """
        self.max_slippage_pct = max_slippage_pct
        self.max_position_usd = max_position_usd
        self.min_edge_after_slippage = min_edge_after_slippage

        self._order_history: List[PredictionOrder] = []
        self._fill_history: List[FillResult] = []
        self._next_order_id = 1

    def create_arb_orders(
        self,
        contract_id: str,
        outcomes: List[Dict],
        position_size: float,
    ) -> List[PredictionOrder]:
        """
        Create orders for an arbitrage execution.

        Args:
            contract_id: The contract to trade
            outcomes: List of {name, price, action} dicts
            position_size: Total position size in contracts

        Returns:
            List of PredictionOrder objects
        """
        capped_size = min(position_size, self.max_position_usd)
        orders = []

        for outcome in outcomes:
            side = OrderSide.BUY if outcome["action"] == "BUY" else OrderSide.SELL
            order = PredictionOrder(
                order_id=f"PORD-{self._next_order_id:04d}",
                contract_id=contract_id,
                outcome=outcome["name"],
                side=side,
                price=outcome["price"],
                size=capped_size,
                max_slippage_pct=self.max_slippage_pct,
            )
            self._next_order_id += 1
            orders.append(order)

        self._order_history.extend(orders)
        return orders

    def validate_execution(
        self,
        orders: List[PredictionOrder],
        edge_pct: float,
    ) -> Dict:
        """
        Validate whether an arb execution should proceed.

        Checks slippage tolerance and position sizing constraints.

        Args:
            orders: Orders to validate
            edge_pct: Expected edge percentage

        Returns:
            Validation result dict
        """
        issues = []

        # Check total position size
        total_cost = sum(o.notional_value for o in orders)
        if total_cost > self.max_position_usd:
            issues.append(f"Total cost ${total_cost:.2f} exceeds max ${self.max_position_usd:.2f}")

        # Check edge after worst-case slippage
        worst_case_slippage = self.max_slippage_pct * len(orders)
        edge_after_slippage = edge_pct - worst_case_slippage
        if edge_after_slippage < self.min_edge_after_slippage:
            issues.append(
                f"Edge after slippage ({edge_after_slippage:.2f}%) "
                f"below minimum ({self.min_edge_after_slippage}%)"
            )

        # Check individual order prices
        for order in orders:
            if order.price <= 0 or order.price >= 1.0:
                issues.append(f"Invalid price {order.price} for {order.outcome}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "total_cost": round(total_cost, 4),
            "edge_pct": round(edge_pct, 4),
            "edge_after_worst_slippage": round(edge_after_slippage, 4),
            "order_count": len(orders),
        }

    def simulate_fill(
        self,
        order: PredictionOrder,
        actual_price: Optional[float] = None,
        partial_fill_ratio: float = 1.0,
    ) -> FillResult:
        """
        Simulate an order fill (for backtesting/paper trading).

        Args:
            order: The order to simulate
            actual_price: Simulated fill price (defaults to order price)
            partial_fill_ratio: Fraction filled (0.0-1.0)

        Returns:
            FillResult with simulation data
        """
        fill_price = actual_price if actual_price is not None else order.price
        fill_size = order.size * partial_fill_ratio

        # Check slippage
        if order.side == OrderSide.BUY:
            slippage = ((fill_price - order.price) / order.price) * 100 if order.price > 0 else 0.0
        else:
            slippage = ((order.price - fill_price) / order.price) * 100 if order.price > 0 else 0.0

        # Reject if slippage exceeds limit
        if slippage > order.max_slippage_pct:
            result = FillResult(
                order_id=order.order_id,
                filled=False,
                error=f"Slippage {slippage:.2f}% exceeds max {order.max_slippage_pct}%",
            )
            self._fill_history.append(result)
            return result

        result = FillResult(
            order_id=order.order_id,
            filled=True,
            fill_price=fill_price,
            fill_size=fill_size,
            slippage_pct=slippage,
        )
        self._fill_history.append(result)
        return result

    def get_execution_stats(self) -> dict:
        """Get execution statistics."""
        total_orders = len(self._order_history)
        total_fills = len(self._fill_history)
        successful_fills = [f for f in self._fill_history if f.filled]
        failed_fills = [f for f in self._fill_history if not f.filled]

        avg_slippage = 0.0
        if successful_fills:
            avg_slippage = sum(f.slippage_pct for f in successful_fills) / len(successful_fills)

        return {
            "total_orders": total_orders,
            "total_fills": total_fills,
            "successful_fills": len(successful_fills),
            "failed_fills": len(failed_fills),
            "fill_rate": round(len(successful_fills) / total_fills, 4) if total_fills > 0 else 0.0,
            "avg_slippage_pct": round(avg_slippage, 4),
            "total_volume": round(sum(f.total_cost for f in successful_fills), 2),
        }

    def get_summary(self) -> dict:
        """Get executor summary."""
        return {
            "config": {
                "max_slippage_pct": self.max_slippage_pct,
                "max_position_usd": self.max_position_usd,
                "min_edge_after_slippage": self.min_edge_after_slippage,
            },
            "stats": self.get_execution_stats(),
        }
