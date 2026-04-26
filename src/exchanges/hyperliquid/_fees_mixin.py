"""Fee/fill-history queries for the Hyperliquid client.

Wraps the HL info-API's ``user_fills`` and ``user_funding_history``
endpoints to surface per-order fees, weighted fill prices and funding
deltas — the same numbers the dashboard's PnL widget consumes.

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidFeesMixin:
    """Fees and fill-history queries used by :class:`HyperliquidClient`."""

    async def get_order_fees(self, symbol: str, order_id: str) -> float:
        """Get fees for a single order from fills history."""
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        total = 0.0
        try:
            fills = self._info_exec.user_fills(address)
            for fill in fills:
                if str(fill.get("oid", "")) == str(order_id) and fill.get("coin") == coin:
                    total += abs(float(fill.get("fee", 0)))
        except Exception as e:
            logger.warning(f"Failed to get order fees for {order_id}: {e}")
        return round(total, 6)

    async def get_trade_total_fees(
        self, symbol: str, entry_order_id: str, close_order_id: Optional[str] = None
    ) -> float:
        """Get total trading fees (entry + exit) from fills history."""
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        total_fees = 0.0
        try:
            fills = self._info_exec.user_fills(address)
            target_oids = {str(entry_order_id)}
            if close_order_id:
                target_oids.add(str(close_order_id))
            for fill in fills:
                if str(fill.get("oid", "")) in target_oids and fill.get("coin") == coin:
                    total_fees += abs(float(fill.get("fee", 0)))
        except Exception as e:
            logger.warning(f"Failed to get trade total fees for {symbol}: {e}")
        return round(total_fees, 6)

    async def get_fill_price(
        self, symbol: str, order_id: str, **kwargs
    ) -> Optional[float]:
        """Get actual fill price for an order from fills history.

        In demo mode the real fill lives on testnet at illiquid prices; returning
        the mainnet mid instead keeps entry_price consistent with the ticker the
        user sees on the live Hyperliquid UI.
        """
        if self.demo_mode:
            try:
                ticker = await self.get_ticker(symbol)
                px = float(getattr(ticker, "last_price", 0) or 0)
                return px if px > 0 else None
            except Exception as e:
                logger.debug(f"Demo fill price fallback failed for {symbol}: {e}")
                return None

        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        try:
            fills = self._info_exec.user_fills(address)
            total_value = 0.0
            total_size = 0.0
            for fill in fills:
                if str(fill.get("oid", "")) == str(order_id) and fill.get("coin") == coin:
                    px = float(fill.get("px", 0))
                    sz = float(fill.get("sz", 0))
                    if px > 0 and sz > 0:
                        total_value += px * sz
                        total_size += sz
            if total_size > 0:
                return round(total_value / total_size, 8)
        except Exception as e:
            logger.warning(f"Failed to get fill price for {order_id}: {e}")
        return None

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        """Get fill price of the most recent close fill from Hyperliquid.

        In demo mode returns None so the caller falls back to the mainnet ticker;
        testnet close fills would pollute PnL with detached testnet prices.
        """
        if self.demo_mode:
            return None

        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        try:
            fills = self._info_exec.user_fills(address)
            for fill in reversed(fills):
                if fill.get("coin") == coin and fill.get("dir", "").startswith("Close"):
                    price = fill.get("px")
                    if price and float(price) > 0:
                        return float(price)
        except Exception as e:
            logger.warning(f"Failed to get close fill price for {symbol}: {e}")
        return None

    async def get_funding_fees(
        self, symbol: str, start_time_ms: int, end_time_ms: int
    ) -> float:
        """Get total funding fees for a symbol between two timestamps."""
        coin = self._normalize_symbol(symbol)
        address = (self.wallet_address or self._wallet.address).lower()
        total_funding = 0.0
        try:
            history = self._info_exec.user_funding_history(
                user=address,
                startTime=start_time_ms,
                endTime=end_time_ms,
            )
            if isinstance(history, list):
                for entry in history:
                    if entry.get("coin") == coin or entry.get("asset") == coin:
                        # delta is negative when funding is paid, positive when received
                        # We track net funding cost (positive = paid, negative = received)
                        total_funding += float(entry.get("delta", 0))
        except Exception as e:
            logger.warning(f"Failed to get funding fees for {symbol}: {e}")
        return round(total_funding, 6)
