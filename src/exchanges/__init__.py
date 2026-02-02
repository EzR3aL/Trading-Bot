"""
Multi-exchange support and cross-exchange arbitrage.
"""

from src.exchanges.base import ExchangeAdapter, ExchangeTicker, ExchangeBalance
from src.exchanges.registry import ExchangeRegistry
from src.exchanges.arb_scanner import (
    ArbScanner,
    ArbOpportunity,
    ArbType,
)

__all__ = [
    "ExchangeAdapter",
    "ExchangeTicker",
    "ExchangeBalance",
    "ExchangeRegistry",
    "ArbScanner",
    "ArbOpportunity",
    "ArbType",
]
