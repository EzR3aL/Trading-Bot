"""
Exchange Registry for managing multiple exchange connections.
"""

from typing import Dict, List, Optional

from src.exchanges.base import (
    ExchangeAdapter,
    ExchangeTicker,
    ExchangeBalance,
    ExchangeFundingRate,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ExchangeRegistry:
    """
    Central registry for managing multiple exchange adapters.

    Provides unified access to all connected exchanges for
    cross-exchange price comparison and arbitrage operations.
    """

    def __init__(self):
        self._exchanges: Dict[str, ExchangeAdapter] = {}

    def register(self, adapter: ExchangeAdapter):
        """
        Register an exchange adapter.

        Args:
            adapter: Exchange adapter instance
        """
        self._exchanges[adapter.name] = adapter
        logger.info(f"Registered exchange: {adapter.name}")

    def unregister(self, name: str):
        """Remove an exchange from the registry."""
        if name in self._exchanges:
            del self._exchanges[name]

    def get(self, name: str) -> Optional[ExchangeAdapter]:
        """Get a specific exchange adapter."""
        return self._exchanges.get(name)

    def list_exchanges(self) -> List[str]:
        """Get list of registered exchange names."""
        return list(self._exchanges.keys())

    def get_connected(self) -> List[str]:
        """Get list of connected exchange names."""
        return [name for name, ex in self._exchanges.items() if ex.is_connected]

    async def get_all_tickers(self, symbol: str) -> Dict[str, ExchangeTicker]:
        """
        Get ticker for a symbol from all connected exchanges.

        Args:
            symbol: Trading pair

        Returns:
            Dict of exchange_name -> ExchangeTicker
        """
        tickers = {}
        for name, exchange in self._exchanges.items():
            if not exchange.is_connected:
                continue
            try:
                ticker = await exchange.get_ticker(symbol)
                tickers[name] = ticker
            except Exception as e:
                logger.warning(f"Failed to get ticker from {name}: {e}")
        return tickers

    async def get_all_funding_rates(self, symbol: str) -> Dict[str, ExchangeFundingRate]:
        """
        Get funding rate for a symbol from all connected exchanges.

        Args:
            symbol: Trading pair

        Returns:
            Dict of exchange_name -> ExchangeFundingRate
        """
        rates = {}
        for name, exchange in self._exchanges.items():
            if not exchange.is_connected:
                continue
            try:
                rate = await exchange.get_funding_rate(symbol)
                rates[name] = rate
            except Exception as e:
                logger.warning(f"Failed to get funding rate from {name}: {e}")
        return rates

    def get_summary(self) -> dict:
        """Get registry summary."""
        return {
            "registered": len(self._exchanges),
            "connected": len(self.get_connected()),
            "exchanges": {
                name: {
                    "connected": ex.is_connected,
                }
                for name, ex in self._exchanges.items()
            },
        }
