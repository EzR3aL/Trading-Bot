"""
Portfolio Management Module.

Provides multi-asset portfolio trading with:
- Per-asset weight allocation
- Correlation tracking
- Portfolio-level risk management
- Rebalancing logic
"""

from src.portfolio.manager import PortfolioManager, AssetAllocation, PortfolioState
from src.portfolio.correlation import CorrelationTracker

__all__ = [
    "PortfolioManager",
    "AssetAllocation",
    "PortfolioState",
    "CorrelationTracker",
]
