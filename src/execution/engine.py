"""
Smart Execution Engine.

Provides intelligent order execution with limit-order-first strategy,
slippage tracking, and configurable execution modes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ExecutionStrategy(str, Enum):
    """Available execution strategies."""
    MARKET = "market"          # Immediate market order
    LIMIT_WITH_FALLBACK = "limit_with_fallback"  # Limit order, fallback to market
    TWAP = "twap"             # Time-weighted average price
    ICEBERG = "iceberg"       # Split into smaller chunks


@dataclass
class SlippageRecord:
    """Records slippage for a single execution."""
    symbol: str
    side: str  # "buy" or "sell"
    expected_price: float
    actual_price: float
    size: float
    slippage_pct: float  # Positive = worse than expected
    slippage_usd: float
    strategy: ExecutionStrategy
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "expected_price": self.expected_price,
            "actual_price": self.actual_price,
            "size": self.size,
            "slippage_pct": round(self.slippage_pct, 6),
            "slippage_usd": round(self.slippage_usd, 4),
            "strategy": self.strategy.value,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ExecutionResult:
    """Result of an execution attempt."""
    success: bool
    symbol: str
    side: str
    strategy: ExecutionStrategy
    requested_size: float
    filled_size: float
    average_price: float
    slippage: Optional[SlippageRecord] = None
    chunks: int = 1  # Number of order chunks used
    retries: int = 0
    total_fees: float = 0.0
    execution_time_ms: float = 0.0
    reason: str = ""

    @property
    def fill_ratio(self) -> float:
        """Fraction of requested size that was filled."""
        if self.requested_size <= 0:
            return 0.0
        return self.filled_size / self.requested_size

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "symbol": self.symbol,
            "side": self.side,
            "strategy": self.strategy.value,
            "requested_size": self.requested_size,
            "filled_size": self.filled_size,
            "fill_ratio": round(self.fill_ratio, 4),
            "average_price": self.average_price,
            "slippage": self.slippage.to_dict() if self.slippage else None,
            "chunks": self.chunks,
            "retries": self.retries,
            "total_fees": round(self.total_fees, 4),
            "execution_time_ms": round(self.execution_time_ms, 2),
            "reason": self.reason,
        }


class ExecutionEngine:
    """
    Smart execution engine for optimized trade entry and exit.

    Features:
    - Limit-order-first with market order fallback
    - Slippage tracking and reporting
    - Large order splitting (iceberg)
    - Execution quality metrics
    """

    def __init__(
        self,
        default_strategy: ExecutionStrategy = ExecutionStrategy.LIMIT_WITH_FALLBACK,
        limit_timeout_seconds: float = 5.0,
        max_slippage_pct: float = 0.5,
        iceberg_chunk_pct: float = 25.0,
        price_improvement_ticks: int = 1,
    ):
        """
        Initialize the execution engine.

        Args:
            default_strategy: Default execution strategy
            limit_timeout_seconds: How long to wait for limit fill
            max_slippage_pct: Maximum acceptable slippage percentage
            iceberg_chunk_pct: Percentage of total size per iceberg chunk
            price_improvement_ticks: Ticks of price improvement for limit orders
        """
        self.default_strategy = default_strategy
        self.limit_timeout_seconds = limit_timeout_seconds
        self.max_slippage_pct = max_slippage_pct
        self.iceberg_chunk_pct = iceberg_chunk_pct
        self.price_improvement_ticks = price_improvement_ticks

        self._slippage_history: List[SlippageRecord] = []
        self._execution_history: List[ExecutionResult] = []

    def calculate_limit_price(
        self,
        side: str,
        reference_price: float,
        tick_size: float = 0.01,
    ) -> float:
        """
        Calculate optimal limit order price with price improvement.

        For buys: bid slightly above best bid (but below ask)
        For sells: ask slightly below best ask (but above bid)

        Args:
            side: "buy" or "sell"
            reference_price: Best bid (for buy) or best ask (for sell)
            tick_size: Minimum price increment

        Returns:
            Optimized limit price
        """
        improvement = tick_size * self.price_improvement_ticks

        if side == "buy":
            return reference_price + improvement
        else:
            return reference_price - improvement

    def calculate_slippage(
        self,
        side: str,
        expected_price: float,
        actual_price: float,
        size: float,
        strategy: ExecutionStrategy,
    ) -> SlippageRecord:
        """
        Calculate and record slippage for an execution.

        Args:
            side: "buy" or "sell"
            expected_price: Expected fill price
            actual_price: Actual fill price
            size: Executed size
            strategy: Strategy used

        Returns:
            SlippageRecord
        """
        if expected_price <= 0:
            slippage_pct = 0.0
        elif side == "buy":
            # For buys, slippage is positive when actual > expected
            slippage_pct = ((actual_price - expected_price) / expected_price) * 100
        else:
            # For sells, slippage is positive when actual < expected
            slippage_pct = ((expected_price - actual_price) / expected_price) * 100

        slippage_usd = abs(actual_price - expected_price) * size

        record = SlippageRecord(
            symbol="",  # Caller should set
            side=side,
            expected_price=expected_price,
            actual_price=actual_price,
            size=size,
            slippage_pct=slippage_pct,
            slippage_usd=slippage_usd,
            strategy=strategy,
        )

        self._slippage_history.append(record)
        return record

    def calculate_iceberg_chunks(
        self,
        total_size: float,
        chunk_pct: Optional[float] = None,
    ) -> List[float]:
        """
        Split a large order into smaller iceberg chunks.

        Args:
            total_size: Total order size
            chunk_pct: Percentage per chunk (overrides default)

        Returns:
            List of chunk sizes
        """
        pct = chunk_pct or self.iceberg_chunk_pct
        if pct <= 0 or pct >= 100:
            return [total_size]

        chunk_size = total_size * (pct / 100.0)
        if chunk_size <= 0:
            return [total_size]

        chunks = []
        remaining = total_size

        while remaining > 0:
            this_chunk = min(chunk_size, remaining)
            chunks.append(this_chunk)
            remaining -= this_chunk

        return chunks

    def should_use_limit(
        self,
        spread_pct: float,
        volatility_pct: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Decide whether to use limit or market order based on conditions.

        Args:
            spread_pct: Current bid-ask spread percentage
            volatility_pct: Recent volatility percentage

        Returns:
            Tuple of (use_limit, reason)
        """
        # Wide spread -> use limit to save on spread
        if spread_pct > 0.1:
            return True, f"Wide spread ({spread_pct:.3f}%) favors limit order"

        # High volatility -> use market to ensure fill
        if volatility_pct is not None and volatility_pct > 2.0:
            return False, f"High volatility ({volatility_pct:.1f}%) favors market order"

        # Narrow spread -> market is fine
        if spread_pct < 0.03:
            return False, f"Tight spread ({spread_pct:.3f}%) - market order is fine"

        # Default: use limit
        return True, "Default: limit with fallback"

    def is_slippage_acceptable(
        self,
        slippage_pct: float,
        max_override: Optional[float] = None,
    ) -> Tuple[bool, str]:
        """
        Check if slippage is within acceptable range.

        Args:
            slippage_pct: Slippage percentage
            max_override: Override max slippage threshold

        Returns:
            Tuple of (acceptable, reason)
        """
        threshold = max_override or self.max_slippage_pct

        if slippage_pct <= threshold:
            return True, f"Slippage {slippage_pct:.4f}% within threshold {threshold:.2f}%"

        return False, f"Slippage {slippage_pct:.4f}% exceeds threshold {threshold:.2f}%"

    def record_execution(self, result: ExecutionResult):
        """Record an execution result for metrics."""
        self._execution_history.append(result)

    def get_slippage_stats(self, symbol: Optional[str] = None) -> dict:
        """
        Get slippage statistics.

        Args:
            symbol: Filter by symbol (optional)

        Returns:
            Slippage statistics dict
        """
        records = self._slippage_history
        if symbol:
            records = [r for r in records if r.symbol == symbol]

        if not records:
            return {
                "count": 0,
                "avg_slippage_pct": 0.0,
                "max_slippage_pct": 0.0,
                "total_slippage_usd": 0.0,
                "positive_slippage_count": 0,
            }

        slippages = [r.slippage_pct for r in records]
        return {
            "count": len(records),
            "avg_slippage_pct": round(sum(slippages) / len(slippages), 6),
            "max_slippage_pct": round(max(slippages), 6),
            "min_slippage_pct": round(min(slippages), 6),
            "total_slippage_usd": round(sum(r.slippage_usd for r in records), 4),
            "positive_slippage_count": sum(1 for s in slippages if s > 0),
        }

    def get_execution_stats(self) -> dict:
        """Get execution quality metrics."""
        if not self._execution_history:
            return {
                "total_executions": 0,
                "success_rate": 0.0,
                "avg_fill_ratio": 0.0,
                "strategy_breakdown": {},
            }

        successes = sum(1 for e in self._execution_history if e.success)
        fill_ratios = [e.fill_ratio for e in self._execution_history]

        # Strategy breakdown
        strategy_counts: Dict[str, int] = {}
        for e in self._execution_history:
            key = e.strategy.value
            strategy_counts[key] = strategy_counts.get(key, 0) + 1

        return {
            "total_executions": len(self._execution_history),
            "success_rate": round(successes / len(self._execution_history) * 100, 2),
            "avg_fill_ratio": round(sum(fill_ratios) / len(fill_ratios), 4),
            "avg_execution_time_ms": round(
                sum(e.execution_time_ms for e in self._execution_history) /
                len(self._execution_history), 2
            ),
            "strategy_breakdown": strategy_counts,
        }

    def get_summary(self) -> dict:
        """Get combined execution engine summary."""
        return {
            "config": {
                "default_strategy": self.default_strategy.value,
                "limit_timeout_seconds": self.limit_timeout_seconds,
                "max_slippage_pct": self.max_slippage_pct,
                "iceberg_chunk_pct": self.iceberg_chunk_pct,
            },
            "slippage": self.get_slippage_stats(),
            "execution": self.get_execution_stats(),
        }
