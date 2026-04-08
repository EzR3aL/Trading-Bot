"""Trading strategy modules."""

from .base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal, check_atr_trailing_stop

# Import each strategy with error handling so one broken strategy
# doesn't prevent others from loading.
from .edge_indicator import EdgeIndicatorStrategy
from .liquidation_hunter import LiquidationHunterStrategy
from .copy_trading import CopyTradingStrategy  # noqa: F401 — registers on import

__all__ = [
    "BaseStrategy",
    "EdgeIndicatorStrategy",
    "SignalDirection",
    "StrategyRegistry",
    "TradeSignal",
    "LiquidationHunterStrategy",
    "check_atr_trailing_stop",
]
