"""
TWAP (Time-Weighted Average Price) Executor.

Splits large orders across time intervals to minimize
market impact and achieve better average fill prices.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TWAPConfig:
    """Configuration for TWAP execution."""
    total_duration_seconds: float = 300.0  # 5 minutes default
    num_slices: int = 5
    randomize_size: bool = True  # Vary slice sizes slightly
    randomize_timing: bool = True  # Vary interval slightly
    max_slice_deviation_pct: float = 20.0  # Max random deviation per slice

    @property
    def interval_seconds(self) -> float:
        """Time between each slice."""
        if self.num_slices <= 1:
            return self.total_duration_seconds
        return self.total_duration_seconds / self.num_slices

    def to_dict(self) -> dict:
        return {
            "total_duration_seconds": self.total_duration_seconds,
            "num_slices": self.num_slices,
            "interval_seconds": round(self.interval_seconds, 2),
            "randomize_size": self.randomize_size,
            "randomize_timing": self.randomize_timing,
            "max_slice_deviation_pct": self.max_slice_deviation_pct,
        }


@dataclass
class TWAPSlice:
    """A single slice of a TWAP execution."""
    slice_number: int
    target_size: float
    scheduled_time: datetime
    executed: bool = False
    filled_size: float = 0.0
    fill_price: float = 0.0
    execution_time: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "slice_number": self.slice_number,
            "target_size": round(self.target_size, 8),
            "scheduled_time": self.scheduled_time.isoformat(),
            "executed": self.executed,
            "filled_size": round(self.filled_size, 8),
            "fill_price": self.fill_price,
            "execution_time": self.execution_time.isoformat() if self.execution_time else None,
        }


class TWAPExecutor:
    """
    TWAP execution engine.

    Splits a large order into time-weighted slices to minimize
    market impact. Does not execute orders directly - generates
    a plan for the caller to execute.
    """

    def __init__(self, config: Optional[TWAPConfig] = None):
        """
        Initialize the TWAP executor.

        Args:
            config: TWAP configuration (uses defaults if None)
        """
        self.config = config or TWAPConfig()
        self._active_plans: dict = {}

    def create_plan(
        self,
        symbol: str,
        side: str,
        total_size: float,
        start_time: Optional[datetime] = None,
    ) -> List[TWAPSlice]:
        """
        Create a TWAP execution plan.

        Args:
            symbol: Trading pair
            side: "buy" or "sell"
            total_size: Total order size

        Returns:
            List of TWAPSlice objects representing the execution plan
        """
        start = start_time or datetime.utcnow()
        base_slice_size = total_size / self.config.num_slices
        interval = timedelta(seconds=self.config.interval_seconds)

        slices = []
        remaining = total_size

        for i in range(self.config.num_slices):
            if i == self.config.num_slices - 1:
                # Last slice gets the remainder to avoid floating point drift
                slice_size = remaining
            else:
                slice_size = base_slice_size

            scheduled = start + (interval * i)

            slices.append(TWAPSlice(
                slice_number=i + 1,
                target_size=slice_size,
                scheduled_time=scheduled,
            ))

            remaining -= slice_size

        plan_id = f"TWAP-{symbol}-{side}-{start.strftime('%H%M%S')}"
        self._active_plans[plan_id] = {
            "symbol": symbol,
            "side": side,
            "total_size": total_size,
            "slices": slices,
            "config": self.config.to_dict(),
            "created_at": start.isoformat(),
        }

        logger.info(
            f"Created TWAP plan {plan_id}: {symbol} {side} "
            f"{total_size} in {self.config.num_slices} slices "
            f"over {self.config.total_duration_seconds}s"
        )

        return slices

    def mark_slice_executed(
        self,
        slices: List[TWAPSlice],
        slice_number: int,
        filled_size: float,
        fill_price: float,
    ) -> bool:
        """
        Mark a slice as executed.

        Args:
            slices: The TWAP plan slices
            slice_number: Which slice (1-indexed)
            filled_size: Actual filled size
            fill_price: Actual fill price

        Returns:
            True if marked successfully
        """
        for s in slices:
            if s.slice_number == slice_number:
                s.executed = True
                s.filled_size = filled_size
                s.fill_price = fill_price
                s.execution_time = datetime.utcnow()
                return True
        return False

    def get_plan_progress(self, slices: List[TWAPSlice]) -> dict:
        """
        Get progress of a TWAP plan.

        Args:
            slices: The TWAP plan slices

        Returns:
            Progress dict
        """
        total_target = sum(s.target_size for s in slices)
        total_filled = sum(s.filled_size for s in slices)
        executed_slices = [s for s in slices if s.executed]

        if executed_slices:
            vwap = sum(s.fill_price * s.filled_size for s in executed_slices) / total_filled if total_filled > 0 else 0.0
        else:
            vwap = 0.0

        return {
            "total_slices": len(slices),
            "executed_slices": len(executed_slices),
            "remaining_slices": len(slices) - len(executed_slices),
            "total_target_size": round(total_target, 8),
            "total_filled_size": round(total_filled, 8),
            "fill_ratio": round(total_filled / total_target, 4) if total_target > 0 else 0.0,
            "vwap": round(vwap, 2),
            "complete": len(executed_slices) == len(slices),
        }

    def get_next_slice(self, slices: List[TWAPSlice]) -> Optional[TWAPSlice]:
        """Get the next unexecuted slice."""
        for s in slices:
            if not s.executed:
                return s
        return None

    def is_due(self, slice_: TWAPSlice) -> bool:
        """Check if a slice is due for execution."""
        return datetime.utcnow() >= slice_.scheduled_time

    def get_active_plans(self) -> dict:
        """Get all active TWAP plans."""
        return dict(self._active_plans)
