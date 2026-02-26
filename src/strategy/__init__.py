"""Trading strategy modules."""

from .base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal

# Import each strategy with error handling so one broken strategy
# doesn't prevent others from loading.
from .degen import DegenStrategy
from .edge_indicator import EdgeIndicatorStrategy

from .liquidation_hunter import LiquidationHunterStrategy
from .llm_signal import LLMSignalStrategy
from .sentiment_surfer import SentimentSurferStrategy

__all__ = [
    "BaseStrategy",
    "DegenStrategy",
    "EdgeIndicatorStrategy",
    "SignalDirection",
    "StrategyRegistry",
    "TradeSignal",
    "LiquidationHunterStrategy",
    "LLMSignalStrategy",
    "SentimentSurferStrategy",
]
