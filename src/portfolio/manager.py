"""
Portfolio Manager for Multi-Asset Trading.

Handles portfolio weight allocation, position sizing per asset,
and portfolio-level risk management.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AssetAllocation:
    """Configuration for a single asset in the portfolio."""
    symbol: str
    target_weight: float  # 0.0 to 1.0 (e.g., 0.40 = 40%)
    max_weight: float = 0.0  # Maximum allowed weight (0 = use target + drift)
    max_position_pct: float = 25.0  # Max position size as % of portfolio
    max_loss_pct: float = 5.0  # Max daily loss for this asset

    def __post_init__(self):
        if self.max_weight == 0:
            self.max_weight = min(self.target_weight * 1.5, 1.0)


@dataclass
class AssetState:
    """Current state of a single asset in the portfolio."""
    symbol: str
    current_weight: float = 0.0  # Current allocation weight
    open_position_value: float = 0.0  # Value of open positions
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    trade_count: int = 0
    last_price: float = 0.0

    @property
    def weight_drift(self) -> float:
        """How far the current weight is from target (set externally)."""
        return 0.0  # Calculated by PortfolioManager


@dataclass
class PortfolioState:
    """Complete portfolio state snapshot."""
    timestamp: datetime
    total_value: float
    cash_balance: float
    allocated_value: float
    assets: Dict[str, AssetState]
    daily_pnl: float = 0.0
    total_pnl: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "total_value": round(self.total_value, 2),
            "cash_balance": round(self.cash_balance, 2),
            "allocated_value": round(self.allocated_value, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "assets": {
                symbol: {
                    "symbol": state.symbol,
                    "current_weight": round(state.current_weight, 4),
                    "open_position_value": round(state.open_position_value, 2),
                    "daily_pnl": round(state.daily_pnl, 2),
                    "total_pnl": round(state.total_pnl, 2),
                    "trade_count": state.trade_count,
                    "last_price": round(state.last_price, 2),
                }
                for symbol, state in self.assets.items()
            },
        }


# Default portfolio configuration
DEFAULT_PORTFOLIO = {
    "BTCUSDT": AssetAllocation(symbol="BTCUSDT", target_weight=0.40),
    "ETHUSDT": AssetAllocation(symbol="ETHUSDT", target_weight=0.30),
    "SOLUSDT": AssetAllocation(symbol="SOLUSDT", target_weight=0.15),
    "DOGEUSDT": AssetAllocation(symbol="DOGEUSDT", target_weight=0.15),
}


class PortfolioManager:
    """
    Manages multi-asset portfolio allocation and risk.

    Features:
    - Per-asset weight allocation
    - Position sizing respecting portfolio weights
    - Portfolio-level and per-asset risk limits
    - Rebalancing recommendations
    """

    def __init__(
        self,
        allocations: Optional[Dict[str, AssetAllocation]] = None,
        starting_capital: float = 10000.0,
        rebalance_threshold: float = 0.10,  # 10% drift triggers rebalance
    ):
        """
        Initialize the portfolio manager.

        Args:
            allocations: Per-asset allocation configs. If None, uses defaults.
            starting_capital: Initial portfolio value
            rebalance_threshold: Weight drift threshold for rebalancing
        """
        self.allocations = allocations or DEFAULT_PORTFOLIO.copy()
        self.starting_capital = starting_capital
        self.rebalance_threshold = rebalance_threshold

        # Validate weights sum to ~1.0
        total_weight = sum(a.target_weight for a in self.allocations.values())
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(
                f"Portfolio weights sum to {total_weight:.2f}, not 1.0. "
                "Normalizing weights."
            )
            for alloc in self.allocations.values():
                alloc.target_weight /= total_weight

        # State tracking
        self._asset_states: Dict[str, AssetState] = {
            symbol: AssetState(symbol=symbol)
            for symbol in self.allocations
        }
        self._cash_balance = starting_capital
        self._daily_reset_date: Optional[str] = None

    @property
    def symbols(self) -> List[str]:
        """Get all portfolio symbols."""
        return list(self.allocations.keys())

    @property
    def total_value(self) -> float:
        """Get total portfolio value (cash + open positions)."""
        position_value = sum(s.open_position_value for s in self._asset_states.values())
        return self._cash_balance + position_value

    def get_state(self) -> PortfolioState:
        """Get current portfolio state snapshot."""
        # Update weights
        total = self.total_value
        if total > 0:
            for symbol, state in self._asset_states.items():
                state.current_weight = state.open_position_value / total

        return PortfolioState(
            timestamp=datetime.now(),
            total_value=total,
            cash_balance=self._cash_balance,
            allocated_value=total - self._cash_balance,
            assets=self._asset_states.copy(),
            daily_pnl=sum(s.daily_pnl for s in self._asset_states.values()),
            total_pnl=sum(s.total_pnl for s in self._asset_states.values()),
        )

    def calculate_position_size(
        self,
        symbol: str,
        confidence: int,
        entry_price: float,
        leverage: int = 1,
    ) -> Tuple[float, float]:
        """
        Calculate position size respecting portfolio weights.

        Args:
            symbol: Trading pair
            confidence: Signal confidence (0-100)
            entry_price: Current price
            leverage: Leverage multiplier

        Returns:
            Tuple of (position_size_base_currency, position_value_usdt)
        """
        if symbol not in self.allocations:
            logger.warning(f"Symbol {symbol} not in portfolio, using default sizing")
            # Fallback: equal weight
            target_weight = 1.0 / max(len(self.allocations), 1)
        else:
            target_weight = self.allocations[symbol].target_weight

        total = self.total_value

        # Base allocation for this asset
        target_value = total * target_weight

        # Already allocated to this asset
        current_value = self._asset_states.get(symbol, AssetState(symbol=symbol)).open_position_value

        # Available budget for this asset
        available = target_value - current_value

        if available <= 0:
            logger.info(f"{symbol}: Target weight reached, no additional position")
            return 0.0, 0.0

        # Confidence-based position scaling
        if confidence >= 85:
            scale = 1.0  # Full allocation
        elif confidence >= 75:
            scale = 0.75
        elif confidence >= 65:
            scale = 0.5
        elif confidence >= 55:
            scale = 0.35
        else:
            scale = 0.2

        # Position value in USDT
        position_value = min(available * scale, self._cash_balance * 0.9)  # Never use >90% of cash

        # Apply max position limit
        alloc = self.allocations.get(symbol)
        if alloc:
            max_position = total * (alloc.max_position_pct / 100)
            position_value = min(position_value, max_position)

        # Minimum position size
        if position_value < 10:
            return 0.0, 0.0

        # Calculate base currency size
        position_size = (position_value * leverage) / entry_price

        return position_size, position_value

    def record_entry(
        self,
        symbol: str,
        position_value: float,
        entry_price: float,
    ):
        """Record a new position entry."""
        self._check_daily_reset()

        if symbol not in self._asset_states:
            self._asset_states[symbol] = AssetState(symbol=symbol)

        state = self._asset_states[symbol]
        state.open_position_value += position_value
        state.last_price = entry_price
        state.trade_count += 1

        self._cash_balance -= position_value

        logger.info(
            f"Portfolio entry: {symbol} +${position_value:.2f} | "
            f"Weight: {state.current_weight:.2%} | "
            f"Cash: ${self._cash_balance:.2f}"
        )

    def record_exit(
        self,
        symbol: str,
        position_value: float,
        pnl: float,
    ):
        """Record a position exit."""
        self._check_daily_reset()

        if symbol not in self._asset_states:
            return

        state = self._asset_states[symbol]
        state.open_position_value = max(0, state.open_position_value - position_value)
        state.daily_pnl += pnl
        state.total_pnl += pnl

        self._cash_balance += position_value + pnl

        logger.info(
            f"Portfolio exit: {symbol} -${position_value:.2f} | "
            f"PnL: ${pnl:+.2f} | Cash: ${self._cash_balance:.2f}"
        )

    def can_trade_asset(self, symbol: str) -> Tuple[bool, str]:
        """
        Check if trading is allowed for a specific asset.

        Returns:
            Tuple of (can_trade, reason)
        """
        self._check_daily_reset()

        alloc = self.allocations.get(symbol)
        if not alloc:
            return False, f"Symbol {symbol} not in portfolio"

        state = self._asset_states.get(symbol, AssetState(symbol=symbol))

        # Check per-asset daily loss limit
        daily_loss_pct = abs(state.daily_pnl) / self.starting_capital * 100
        if state.daily_pnl < 0 and daily_loss_pct >= alloc.max_loss_pct:
            return False, f"{symbol}: Daily loss limit reached ({daily_loss_pct:.1f}%)"

        # Check if over max weight
        total = self.total_value
        if total > 0:
            current_weight = state.open_position_value / total
            if current_weight >= alloc.max_weight:
                return False, f"{symbol}: Max weight reached ({current_weight:.1%})"

        return True, "OK"

    def get_rebalance_recommendations(self) -> List[Dict]:
        """
        Get rebalancing recommendations when weights drift too far.

        Returns:
            List of rebalancing actions needed
        """
        recommendations = []
        total = self.total_value

        if total <= 0:
            return recommendations

        for symbol, alloc in self.allocations.items():
            state = self._asset_states.get(symbol, AssetState(symbol=symbol))
            current_weight = state.open_position_value / total
            drift = current_weight - alloc.target_weight

            if abs(drift) >= self.rebalance_threshold:
                if drift > 0:
                    # Overweight - reduce position
                    reduce_value = drift * total
                    recommendations.append({
                        "symbol": symbol,
                        "action": "reduce",
                        "current_weight": round(current_weight, 4),
                        "target_weight": round(alloc.target_weight, 4),
                        "drift": round(drift, 4),
                        "amount_usdt": round(reduce_value, 2),
                    })
                else:
                    # Underweight - increase position
                    increase_value = abs(drift) * total
                    recommendations.append({
                        "symbol": symbol,
                        "action": "increase",
                        "current_weight": round(current_weight, 4),
                        "target_weight": round(alloc.target_weight, 4),
                        "drift": round(drift, 4),
                        "amount_usdt": round(increase_value, 2),
                    })

        return recommendations

    def get_per_asset_stats(self) -> Dict[str, dict]:
        """Get per-asset performance statistics."""
        result = {}
        total = self.total_value

        for symbol, alloc in self.allocations.items():
            state = self._asset_states.get(symbol, AssetState(symbol=symbol))
            current_weight = state.open_position_value / total if total > 0 else 0

            result[symbol] = {
                "symbol": symbol,
                "target_weight": alloc.target_weight,
                "current_weight": round(current_weight, 4),
                "weight_drift": round(current_weight - alloc.target_weight, 4),
                "open_position_value": round(state.open_position_value, 2),
                "daily_pnl": round(state.daily_pnl, 2),
                "total_pnl": round(state.total_pnl, 2),
                "trade_count": state.trade_count,
            }

        return result

    def _check_daily_reset(self):
        """Reset daily stats if new day."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            for state in self._asset_states.values():
                state.daily_pnl = 0.0
                state.trade_count = 0
            self._daily_reset_date = today

    @classmethod
    def from_config(cls, trading_pairs: List[str], portfolio_weights: Optional[str] = None, **kwargs) -> "PortfolioManager":
        """
        Create a PortfolioManager from configuration.

        Args:
            trading_pairs: List of trading pairs
            portfolio_weights: Comma-separated weights (e.g., "40,30,15,15")
                              If None, uses equal weights.
            **kwargs: Additional kwargs for PortfolioManager

        Returns:
            Configured PortfolioManager
        """
        if portfolio_weights:
            weights = [float(w) / 100 for w in portfolio_weights.split(",")]
        else:
            # Equal weights
            weights = [1.0 / len(trading_pairs)] * len(trading_pairs)

        if len(weights) != len(trading_pairs):
            logger.warning("Weight count doesn't match pairs count, using equal weights")
            weights = [1.0 / len(trading_pairs)] * len(trading_pairs)

        allocations = {}
        for pair, weight in zip(trading_pairs, weights):
            allocations[pair] = AssetAllocation(
                symbol=pair,
                target_weight=weight,
            )

        return cls(allocations=allocations, **kwargs)
