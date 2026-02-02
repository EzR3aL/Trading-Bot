"""
Delta-Neutral Position Manager for Funding Rate Arbitrage.

Manages paired spot + perpetual positions to maintain
market-neutral exposure while collecting funding payments.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ArbitrageStatus(str, Enum):
    """Status of an arbitrage position."""
    PENDING = "pending"
    OPENING = "opening"
    OPEN = "open"
    REBALANCING = "rebalancing"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class PositionLeg:
    """One leg of a delta-neutral position (spot or perpetual)."""
    side: str  # "long" or "short"
    market_type: str  # "spot" or "perpetual"
    entry_price: float = 0.0
    current_price: float = 0.0
    size: float = 0.0  # In base currency
    value: float = 0.0  # In quote currency (USDT)
    unrealized_pnl: float = 0.0

    def update_price(self, price: float):
        """Update current price and recalculate PnL."""
        self.current_price = price
        if self.size > 0 and self.entry_price > 0:
            if self.side == "long":
                self.unrealized_pnl = (price - self.entry_price) * self.size
            else:
                self.unrealized_pnl = (self.entry_price - price) * self.size
            self.value = price * self.size

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "side": self.side,
            "market_type": self.market_type,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "size": self.size,
            "value": round(self.value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 4),
        }


@dataclass
class ArbitragePosition:
    """A complete delta-neutral arbitrage position with two legs."""
    id: str
    symbol: str
    spot_leg: PositionLeg
    perp_leg: PositionLeg
    status: ArbitrageStatus = ArbitrageStatus.PENDING
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    entry_funding_rate: float = 0.0
    funding_collected: float = 0.0
    funding_payments: int = 0
    rebalance_count: int = 0
    total_fees: float = 0.0

    @property
    def net_delta(self) -> float:
        """Calculate the net delta (should be near zero)."""
        spot_delta = self.spot_leg.size if self.spot_leg.side == "long" else -self.spot_leg.size
        perp_delta = self.perp_leg.size if self.perp_leg.side == "long" else -self.perp_leg.size
        return spot_delta + perp_delta

    @property
    def delta_ratio(self) -> float:
        """Delta as a ratio of position size (0.0 = perfectly hedged)."""
        total_size = self.spot_leg.size + self.perp_leg.size
        if total_size == 0:
            return 0.0
        return abs(self.net_delta) / (total_size / 2)

    @property
    def total_pnl(self) -> float:
        """Total P&L including funding, price PnL, and fees."""
        price_pnl = self.spot_leg.unrealized_pnl + self.perp_leg.unrealized_pnl
        return price_pnl + self.funding_collected - self.total_fees

    @property
    def total_value(self) -> float:
        """Total value of both legs."""
        return self.spot_leg.value + self.perp_leg.value

    @property
    def duration_hours(self) -> float:
        """How long the position has been open."""
        if not self.entry_time:
            return 0.0
        end = self.exit_time or datetime.utcnow()
        return (end - self.entry_time).total_seconds() / 3600

    def record_funding(self, amount: float):
        """Record a funding payment (positive = received)."""
        self.funding_collected += amount
        self.funding_payments += 1

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "status": self.status.value,
            "spot_leg": self.spot_leg.to_dict(),
            "perp_leg": self.perp_leg.to_dict(),
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "entry_funding_rate": self.entry_funding_rate,
            "net_delta": round(self.net_delta, 8),
            "delta_ratio": round(self.delta_ratio, 6),
            "funding_collected": round(self.funding_collected, 4),
            "funding_payments": self.funding_payments,
            "total_fees": round(self.total_fees, 4),
            "total_pnl": round(self.total_pnl, 4),
            "total_value": round(self.total_value, 2),
            "duration_hours": round(self.duration_hours, 2),
            "rebalance_count": self.rebalance_count,
        }


class DeltaNeutralManager:
    """
    Manages delta-neutral arbitrage positions.

    Handles:
    - Opening paired spot + perpetual positions
    - Monitoring delta drift and triggering rebalances
    - Recording funding payments
    - Position closure and P&L tracking
    """

    def __init__(
        self,
        max_positions: int = 3,
        max_position_value: float = 10000.0,
        delta_threshold: float = 0.05,
        max_total_exposure: float = 50000.0,
    ):
        """
        Initialize the delta-neutral manager.

        Args:
            max_positions: Maximum concurrent arbitrage positions
            max_position_value: Maximum value per side per position
            delta_threshold: Max delta drift before rebalancing (5% default)
            max_total_exposure: Maximum total exposure across all positions
        """
        self.max_positions = max_positions
        self.max_position_value = max_position_value
        self.delta_threshold = delta_threshold
        self.max_total_exposure = max_total_exposure

        self._positions: Dict[str, ArbitragePosition] = {}
        self._closed_positions: List[ArbitragePosition] = []
        self._next_id = 1

    def open_position(
        self,
        symbol: str,
        funding_rate: float,
        spot_price: float,
        perp_price: float,
        position_value: float,
    ) -> Tuple[Optional[ArbitragePosition], str]:
        """
        Open a new delta-neutral arbitrage position.

        Args:
            symbol: Trading pair
            funding_rate: Current funding rate
            spot_price: Current spot price
            perp_price: Current perpetual price
            position_value: Target value per side (USDT)

        Returns:
            Tuple of (ArbitragePosition or None, reason string)
        """
        # Validate capacity
        can_open, reason = self.can_open_position(symbol, position_value)
        if not can_open:
            return None, reason

        # Determine direction based on funding rate
        if funding_rate > 0:
            # Longs pay shorts -> Long spot + Short perp
            spot_side = "long"
            perp_side = "short"
        else:
            # Shorts pay longs -> Short spot + Long perp
            spot_side = "short"
            perp_side = "long"

        spot_size = position_value / spot_price
        perp_size = position_value / perp_price

        spot_leg = PositionLeg(
            side=spot_side,
            market_type="spot",
            entry_price=spot_price,
            current_price=spot_price,
            size=spot_size,
            value=position_value,
        )

        perp_leg = PositionLeg(
            side=perp_side,
            market_type="perpetual",
            entry_price=perp_price,
            current_price=perp_price,
            size=perp_size,
            value=position_value,
        )

        position_id = f"ARB-{self._next_id:04d}"
        self._next_id += 1

        position = ArbitragePosition(
            id=position_id,
            symbol=symbol,
            spot_leg=spot_leg,
            perp_leg=perp_leg,
            status=ArbitrageStatus.OPEN,
            entry_time=datetime.utcnow(),
            entry_funding_rate=funding_rate,
        )

        self._positions[position_id] = position

        logger.info(
            f"Opened arbitrage position {position_id}: {symbol} | "
            f"Rate: {funding_rate*100:.4f}% | Value: ${position_value:.2f}/side | "
            f"Direction: {spot_side} spot + {perp_side} perp"
        )

        return position, "Position opened"

    def close_position(
        self,
        position_id: str,
        spot_price: float,
        perp_price: float,
        fees: float = 0.0,
    ) -> Tuple[Optional[ArbitragePosition], str]:
        """
        Close an arbitrage position.

        Args:
            position_id: Position ID to close
            spot_price: Current spot price for PnL calculation
            perp_price: Current perp price for PnL calculation
            fees: Total fees for closing both legs

        Returns:
            Tuple of (closed position or None, reason)
        """
        if position_id not in self._positions:
            return None, f"Position {position_id} not found"

        position = self._positions[position_id]
        position.spot_leg.update_price(spot_price)
        position.perp_leg.update_price(perp_price)
        position.total_fees += fees
        position.status = ArbitrageStatus.CLOSED
        position.exit_time = datetime.utcnow()

        # Move to closed
        self._closed_positions.append(position)
        del self._positions[position_id]

        logger.info(
            f"Closed arbitrage position {position_id}: {position.symbol} | "
            f"PnL: ${position.total_pnl:.4f} | "
            f"Funding collected: ${position.funding_collected:.4f} | "
            f"Duration: {position.duration_hours:.1f}h"
        )

        return position, "Position closed"

    def update_prices(
        self,
        symbol: str,
        spot_price: float,
        perp_price: float,
    ) -> List[str]:
        """
        Update prices for all positions of a symbol.
        Returns list of position IDs that need rebalancing.

        Args:
            symbol: Trading pair
            spot_price: Current spot price
            perp_price: Current perp price

        Returns:
            List of position IDs needing rebalance
        """
        needs_rebalance = []

        for pos_id, pos in self._positions.items():
            if pos.symbol != symbol or pos.status != ArbitrageStatus.OPEN:
                continue

            pos.spot_leg.update_price(spot_price)
            pos.perp_leg.update_price(perp_price)

            if pos.delta_ratio > self.delta_threshold:
                needs_rebalance.append(pos_id)

        return needs_rebalance

    def record_funding_payment(
        self,
        position_id: str,
        amount: float,
    ) -> bool:
        """
        Record a funding payment for a position.

        Args:
            position_id: Position ID
            amount: Funding amount (positive = received)

        Returns:
            True if recorded successfully
        """
        if position_id not in self._positions:
            return False

        self._positions[position_id].record_funding(amount)
        return True

    def rebalance_position(
        self,
        position_id: str,
        spot_price: float,
        perp_price: float,
    ) -> Tuple[Optional[dict], str]:
        """
        Calculate rebalancing adjustments for a position.

        Returns the adjustments needed (not executed - caller handles execution).

        Args:
            position_id: Position ID
            spot_price: Current spot price
            perp_price: Current perp price

        Returns:
            Tuple of (adjustment dict or None, reason)
        """
        if position_id not in self._positions:
            return None, f"Position {position_id} not found"

        pos = self._positions[position_id]

        if pos.delta_ratio <= self.delta_threshold:
            return None, "Delta within threshold, no rebalance needed"

        # Calculate target sizes for equal value on each side
        target_value = (pos.spot_leg.value + pos.perp_leg.value) / 2
        target_spot_size = target_value / spot_price
        target_perp_size = target_value / perp_price

        spot_adjustment = target_spot_size - pos.spot_leg.size
        perp_adjustment = target_perp_size - pos.perp_leg.size

        adjustments = {
            "position_id": position_id,
            "symbol": pos.symbol,
            "spot_adjustment": {
                "size_delta": spot_adjustment,
                "action": "increase" if spot_adjustment > 0 else "decrease",
                "current_size": pos.spot_leg.size,
                "target_size": target_spot_size,
            },
            "perp_adjustment": {
                "size_delta": perp_adjustment,
                "action": "increase" if perp_adjustment > 0 else "decrease",
                "current_size": pos.perp_leg.size,
                "target_size": target_perp_size,
            },
            "current_delta_ratio": pos.delta_ratio,
        }

        pos.rebalance_count += 1
        pos.spot_leg.size = target_spot_size
        pos.spot_leg.value = target_value
        pos.perp_leg.size = target_perp_size
        pos.perp_leg.value = target_value

        logger.info(
            f"Rebalanced {position_id}: delta ratio "
            f"{adjustments['current_delta_ratio']:.4f} -> ~0.0"
        )

        return adjustments, "Rebalance calculated"

    def can_open_position(
        self,
        symbol: str,
        position_value: float,
    ) -> Tuple[bool, str]:
        """
        Check if a new position can be opened.

        Args:
            symbol: Trading pair
            position_value: Target value per side

        Returns:
            Tuple of (can_open, reason)
        """
        open_positions = self.get_open_positions()

        if len(open_positions) >= self.max_positions:
            return False, f"Max positions reached ({self.max_positions})"

        if position_value > self.max_position_value:
            return False, (
                f"Position value ${position_value:.2f} exceeds max "
                f"${self.max_position_value:.2f}"
            )

        # Check total exposure
        total_exposure = sum(p.total_value for p in open_positions)
        new_exposure = total_exposure + (position_value * 2)  # Both legs
        if new_exposure > self.max_total_exposure:
            return False, (
                f"Total exposure ${new_exposure:.2f} would exceed max "
                f"${self.max_total_exposure:.2f}"
            )

        # Check duplicate symbol
        for pos in open_positions:
            if pos.symbol == symbol:
                return False, f"Already have open position for {symbol}"

        return True, "OK"

    def get_position(self, position_id: str) -> Optional[ArbitragePosition]:
        """Get a specific open position."""
        return self._positions.get(position_id)

    def get_open_positions(self) -> List[ArbitragePosition]:
        """Get all open positions."""
        return [
            p for p in self._positions.values()
            if p.status in (ArbitrageStatus.OPEN, ArbitrageStatus.REBALANCING)
        ]

    def get_closed_positions(self, limit: int = 50) -> List[ArbitragePosition]:
        """Get recently closed positions."""
        return self._closed_positions[-limit:]

    def get_total_funding_collected(self) -> float:
        """Get total funding collected across all positions (open + closed)."""
        total = sum(p.funding_collected for p in self._positions.values())
        total += sum(p.funding_collected for p in self._closed_positions)
        return total

    def get_total_pnl(self) -> float:
        """Get total P&L across all positions (open + closed)."""
        total = sum(p.total_pnl for p in self._positions.values())
        total += sum(p.total_pnl for p in self._closed_positions)
        return total

    def get_summary(self) -> dict:
        """Get a summary of all arbitrage activity."""
        open_positions = self.get_open_positions()
        return {
            "open_positions": len(open_positions),
            "closed_positions": len(self._closed_positions),
            "total_funding_collected": round(self.get_total_funding_collected(), 4),
            "total_pnl": round(self.get_total_pnl(), 4),
            "total_exposure": round(sum(p.total_value for p in open_positions), 2),
            "max_positions": self.max_positions,
            "max_position_value": self.max_position_value,
            "delta_threshold": self.delta_threshold,
            "positions": [p.to_dict() for p in open_positions],
        }
