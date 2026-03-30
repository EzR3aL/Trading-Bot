"""Trading strategy modules."""

from .base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal

# Import each strategy with error handling so one broken strategy
# doesn't prevent others from loading.
from .contrarian_pulse import ContrarianPulseStrategy
from .edge_indicator import EdgeIndicatorStrategy
from .liquidation_hunter import LiquidationHunterStrategy

__all__ = [
    "BaseStrategy",
    "ContrarianPulseStrategy",
    "EdgeIndicatorStrategy",
    "SignalDirection",
    "StrategyRegistry",
    "TradeSignal",
    "LiquidationHunterStrategy",
]
