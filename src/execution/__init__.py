"""
Smart Execution Engine for optimized trade entry and exit.
"""

from src.execution.engine import (
    ExecutionEngine,
    ExecutionStrategy,
    ExecutionResult,
    SlippageRecord,
)
from src.execution.twap import TWAPExecutor, TWAPConfig
from src.execution.orderbook import OrderbookAnalyzer, OrderbookSnapshot

__all__ = [
    "ExecutionEngine",
    "ExecutionStrategy",
    "ExecutionResult",
    "SlippageRecord",
    "TWAPExecutor",
    "TWAPConfig",
    "OrderbookAnalyzer",
    "OrderbookSnapshot",
]
