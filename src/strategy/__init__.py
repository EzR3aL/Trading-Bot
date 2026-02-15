"""Trading strategy modules."""

from .base import BaseStrategy, SignalDirection, StrategyRegistry, TradeSignal

# Import each strategy with error handling so one broken strategy
# doesn't prevent others from loading.
from .degen import DegenStrategy

from .liquidation_hunter import LiquidationHunterStrategy
from .llm_signal import LLMSignalStrategy
from .sentiment_surfer import SentimentSurferStrategy

__all__ = [
    "BaseStrategy",
    "DegenStrategy",
    "SignalDirection",
    "StrategyRegistry",
    "TradeSignal",
    "LiquidationHunterStrategy",
    "LLMSignalStrategy",
    "SentimentSurferStrategy",
]
