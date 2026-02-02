"""
Funding Rate Monitor for Arbitrage Opportunities.

Scans funding rates across trading pairs and identifies
profitable delta-neutral arbitrage opportunities.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


class OpportunityStatus(str, Enum):
    """Status of a funding rate opportunity."""
    ACTIVE = "active"
    EXPIRED = "expired"
    EXECUTED = "executed"
    BELOW_THRESHOLD = "below_threshold"


@dataclass
class FundingOpportunity:
    """Represents a funding rate arbitrage opportunity."""
    symbol: str
    funding_rate: float
    annualized_rate: float
    direction: str  # "long_spot_short_perp" or "short_spot_long_perp"
    expected_profit_per_cycle: float  # Per 8-hour cycle
    expected_daily_profit: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    status: OpportunityStatus = OpportunityStatus.ACTIVE
    consecutive_periods: int = 1  # How many periods rate has been favorable

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "funding_rate": self.funding_rate,
            "funding_rate_pct": f"{self.funding_rate * 100:.4f}%",
            "annualized_rate": f"{self.annualized_rate * 100:.2f}%",
            "direction": self.direction,
            "expected_profit_per_cycle": round(self.expected_profit_per_cycle, 4),
            "expected_daily_profit": round(self.expected_daily_profit, 4),
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "consecutive_periods": self.consecutive_periods,
        }


class FundingRateMonitor:
    """
    Monitors funding rates across trading pairs to identify
    delta-neutral arbitrage opportunities.

    When funding rate is positive:
      - Longs pay shorts -> Short perp + Long spot = collect funding
    When funding rate is negative:
      - Shorts pay longs -> Long perp + Short spot = collect funding
    """

    # 3 funding periods per day, 365 days per year
    PERIODS_PER_DAY = 3
    PERIODS_PER_YEAR = PERIODS_PER_DAY * 365

    def __init__(
        self,
        min_rate: float = 0.0005,
        exit_rate: float = 0.0001,
        lookback_periods: int = 6,
        min_consecutive: int = 2,
    ):
        """
        Initialize the funding rate monitor.

        Args:
            min_rate: Minimum absolute funding rate to trigger entry (0.05% default)
            exit_rate: Rate below which to exit positions (0.01% default)
            lookback_periods: Number of historical periods to analyze
            min_consecutive: Minimum consecutive periods above threshold
        """
        self.min_rate = min_rate
        self.exit_rate = exit_rate
        self.lookback_periods = lookback_periods
        self.min_consecutive = min_consecutive

        # Rate history: symbol -> list of (timestamp, rate)
        self._rate_history: Dict[str, List[Tuple[datetime, float]]] = {}
        # Current opportunities
        self._opportunities: Dict[str, FundingOpportunity] = {}

    def record_rate(self, symbol: str, rate: float, timestamp: Optional[datetime] = None):
        """
        Record a funding rate observation.

        Args:
            symbol: Trading pair
            rate: Funding rate (decimal, e.g., 0.001 = 0.1%)
            timestamp: Observation time (defaults to now)
        """
        ts = timestamp or datetime.utcnow()

        if symbol not in self._rate_history:
            self._rate_history[symbol] = []

        self._rate_history[symbol].append((ts, rate))

        # Keep only recent history
        cutoff = ts - timedelta(hours=8 * self.lookback_periods * 2)
        self._rate_history[symbol] = [
            (t, r) for t, r in self._rate_history[symbol] if t >= cutoff
        ]

    def scan_opportunities(
        self,
        current_rates: Dict[str, float],
        position_value: float = 10000.0,
    ) -> List[FundingOpportunity]:
        """
        Scan current funding rates for arbitrage opportunities.

        Args:
            current_rates: Dict of symbol -> current funding rate
            position_value: Notional value per side for profit calculation

        Returns:
            List of identified opportunities sorted by expected profit
        """
        opportunities = []

        for symbol, rate in current_rates.items():
            self.record_rate(symbol, rate)

            abs_rate = abs(rate)

            if abs_rate < self.min_rate:
                # Below threshold - check if we should close an existing opportunity
                if symbol in self._opportunities:
                    if abs_rate < self.exit_rate:
                        self._opportunities[symbol].status = OpportunityStatus.EXPIRED
                    else:
                        self._opportunities[symbol].status = OpportunityStatus.BELOW_THRESHOLD
                continue

            # Count consecutive periods above threshold
            consecutive = self._count_consecutive_above_threshold(symbol)

            if consecutive < self.min_consecutive:
                continue

            # Calculate expected profits
            profit_per_cycle = position_value * abs_rate
            daily_profit = profit_per_cycle * self.PERIODS_PER_DAY
            annualized = abs_rate * self.PERIODS_PER_YEAR

            # Determine direction
            if rate > 0:
                direction = "long_spot_short_perp"
            else:
                direction = "short_spot_long_perp"

            opp = FundingOpportunity(
                symbol=symbol,
                funding_rate=rate,
                annualized_rate=annualized,
                direction=direction,
                expected_profit_per_cycle=profit_per_cycle,
                expected_daily_profit=daily_profit,
                consecutive_periods=consecutive,
            )

            self._opportunities[symbol] = opp
            opportunities.append(opp)

        # Sort by expected daily profit descending
        opportunities.sort(key=lambda x: x.expected_daily_profit, reverse=True)
        return opportunities

    def should_enter(self, symbol: str) -> Tuple[bool, str]:
        """
        Check if conditions are met to enter an arbitrage position.

        Args:
            symbol: Trading pair to check

        Returns:
            Tuple of (should_enter, reason)
        """
        if symbol not in self._opportunities:
            return False, "No opportunity identified"

        opp = self._opportunities[symbol]

        if opp.status != OpportunityStatus.ACTIVE:
            return False, f"Opportunity status: {opp.status.value}"

        if opp.consecutive_periods < self.min_consecutive:
            return False, (
                f"Need {self.min_consecutive} consecutive periods, "
                f"have {opp.consecutive_periods}"
            )

        if abs(opp.funding_rate) < self.min_rate:
            return False, f"Rate {opp.funding_rate:.6f} below threshold {self.min_rate:.6f}"

        return True, f"Rate {opp.funding_rate*100:.4f}% for {opp.consecutive_periods} periods"

    def should_exit(self, symbol: str, current_rate: float) -> Tuple[bool, str]:
        """
        Check if an existing arbitrage position should be closed.

        Args:
            symbol: Trading pair
            current_rate: Current funding rate

        Returns:
            Tuple of (should_exit, reason)
        """
        abs_rate = abs(current_rate)

        if abs_rate < self.exit_rate:
            return True, f"Rate {current_rate*100:.4f}% below exit threshold {self.exit_rate*100:.4f}%"

        # Check if rate has flipped direction
        if symbol in self._opportunities:
            opp = self._opportunities[symbol]
            original_positive = opp.funding_rate > 0
            current_positive = current_rate > 0
            if original_positive != current_positive and abs_rate > self.exit_rate:
                return True, f"Rate direction flipped from {'positive' if original_positive else 'negative'}"

        return False, "Position still profitable"

    def get_opportunity(self, symbol: str) -> Optional[FundingOpportunity]:
        """Get the current opportunity for a symbol."""
        return self._opportunities.get(symbol)

    def get_all_opportunities(self) -> List[FundingOpportunity]:
        """Get all tracked opportunities."""
        return list(self._opportunities.values())

    def get_active_opportunities(self) -> List[FundingOpportunity]:
        """Get only active opportunities."""
        return [
            opp for opp in self._opportunities.values()
            if opp.status == OpportunityStatus.ACTIVE
        ]

    def get_rate_history(self, symbol: str) -> List[Tuple[datetime, float]]:
        """Get the rate history for a symbol."""
        return self._rate_history.get(symbol, [])

    def get_average_rate(self, symbol: str, periods: int = 6) -> Optional[float]:
        """
        Get the average funding rate over recent periods.

        Args:
            symbol: Trading pair
            periods: Number of recent periods to average

        Returns:
            Average rate or None if insufficient data
        """
        history = self._rate_history.get(symbol, [])
        if len(history) < 1:
            return None

        recent = history[-periods:]
        return sum(r for _, r in recent) / len(recent)

    def get_summary(self) -> dict:
        """Get a summary of the monitor state."""
        active = self.get_active_opportunities()
        return {
            "tracked_symbols": len(self._rate_history),
            "active_opportunities": len(active),
            "opportunities": [opp.to_dict() for opp in active],
            "min_rate_threshold": self.min_rate,
            "exit_rate_threshold": self.exit_rate,
        }

    def _count_consecutive_above_threshold(self, symbol: str) -> int:
        """Count consecutive recent periods where rate was above threshold."""
        history = self._rate_history.get(symbol, [])
        if not history:
            return 0

        count = 0
        for _, rate in reversed(history):
            if abs(rate) >= self.min_rate:
                count += 1
            else:
                break

        return count
