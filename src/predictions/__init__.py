"""
Prediction Markets Integration.

Scans prediction markets (Polymarket, Azuro, etc.) for
mispricing and arbitrage opportunities.
"""

from src.predictions.base import (
    PredictionMarket,
    PredictionContract,
    MarketOutcome,
    MarketStatus,
    PredictionPlatform,
)
from src.predictions.scanner import (
    PredictionArbScanner,
    PredictionOpportunity,
    OpportunityType,
)
from src.predictions.execution import (
    PredictionExecutor,
    PredictionOrder,
    OrderSide,
    FillResult,
)

__all__ = [
    "PredictionMarket",
    "PredictionContract",
    "MarketOutcome",
    "MarketStatus",
    "PredictionPlatform",
    "PredictionArbScanner",
    "PredictionOpportunity",
    "OpportunityType",
    "PredictionExecutor",
    "PredictionOrder",
    "OrderSide",
    "FillResult",
]
