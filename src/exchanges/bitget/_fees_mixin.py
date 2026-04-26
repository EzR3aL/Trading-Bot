"""Fee / fill / funding history queries for the Bitget client.

Routes order detail and orders-history queries to compute realised fees
and locate the close fill price for a trade. Methods here expect the
host class to expose ``_request`` (from :class:`HTTPExchangeClientMixin`).

No behavior change vs. the original ``client.py`` — pure mechanical move.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from src.exchanges.bitget.constants import ENDPOINTS, PRODUCT_TYPE_USDT
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BitgetFeesMixin:
    """Fee / fill / funding history queries used by :class:`BitgetExchangeClient`."""

    async def get_order_fees(self, symbol: str, order_id: str) -> float:
        """Get total fees paid for a single order via order-detail API.

        Returns absolute fee value (always positive). Returns 0.0 on error.
        """
        try:
            params = {
                "symbol": symbol,
                "productType": PRODUCT_TYPE_USDT,
                "orderId": order_id,
            }
            detail = await self._request("GET", ENDPOINTS["order_detail"], params=params)
            if not detail:
                return 0.0

            # Primary: 'fee' field (string, negative = cost)
            fee_str = detail.get("fee")
            if fee_str and fee_str != "0":
                return abs(float(fee_str))

            # Fallback: feeDetail[].totalFee
            fee_detail = detail.get("feeDetail")
            if fee_detail and isinstance(fee_detail, list):
                total = sum(abs(float(fd.get("totalFee", 0))) for fd in fee_detail)
                if total > 0:
                    return total

            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get order fees for {order_id}: {e}")
            return 0.0

    async def get_trade_total_fees(
        self, symbol: str, entry_order_id: str, close_order_id: Optional[str] = None
    ) -> float:
        """Get total fees (entry + exit) for a complete trade.

        Uses entry_order_id to get entry fees directly.
        If close_order_id is provided, uses it for exit fees.
        Otherwise, searches orders-history for the most recent close order
        on this symbol to find exit fees.

        Returns total absolute fees (always positive). Returns 0.0 on error.
        """
        total_fees = 0.0

        # 1. Entry fees (we always have this order ID)
        if entry_order_id:
            total_fees += await self.get_order_fees(symbol, entry_order_id)

        # 2. Exit fees
        if close_order_id:
            # Direct lookup — we know the close order ID
            total_fees += await self.get_order_fees(symbol, close_order_id)
        else:
            # Search orders-history for the most recent close order on this symbol.
            # Pass an explicit ~90-day window so Bitget does not silently apply
            # the 7-day default and drop older closes (Pattern F per #225).
            try:
                now_ms = int(time.time() * 1000)
                params = {
                    "symbol": symbol,
                    "productType": PRODUCT_TYPE_USDT,
                    "startTime": str(now_ms - 90 * 24 * 60 * 60 * 1000),
                    "endTime": str(now_ms),
                    "limit": "20",
                }
                data = await self._request("GET", ENDPOINTS["orders_history"], params=params)
                orders = (
                    data.get("entrustedList") or data.get("orderList") or data
                    if isinstance(data, dict) else data
                )
                if isinstance(orders, list):
                    for order in orders:
                        trade_side = order.get("tradeSide", "")
                        status = order.get("state", order.get("status", ""))
                        if "close" in trade_side and status == "filled":
                            fee_str = order.get("fee")
                            if fee_str:
                                total_fees += abs(float(fee_str))
                            break  # Most recent close order (list is sorted newest first)
            except Exception as e:
                logger.warning(f"Failed to get close order fees from history for {symbol}: {e}")

        return round(total_fees, 6)

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        """Get the fill price of the most recent close order from orders-history.

        Searches for the latest filled close order (TP/SL/trailing/manual) and
        returns its average fill price. Returns None if not found.

        Uses an explicit ~90-day window so Bitget's silent 7-day default
        does not drop older close orders (Pattern F per #225).
        """
        try:
            now_ms = int(time.time() * 1000)
            params = {
                "symbol": symbol,
                "productType": PRODUCT_TYPE_USDT,
                "startTime": str(now_ms - 90 * 24 * 60 * 60 * 1000),
                "endTime": str(now_ms),
                "limit": "20",
            }
            data = await self._request("GET", ENDPOINTS["orders_history"], params=params)
            orders = (
                data.get("entrustedList") or data.get("orderList") or data
                if isinstance(data, dict) else data
            )
            if isinstance(orders, list):
                for order in orders:
                    trade_side = order.get("tradeSide", "")
                    status = order.get("state", order.get("status", ""))
                    if "close" in trade_side and status == "filled":
                        price_avg = order.get("priceAvg") or order.get("fillPrice")
                        if price_avg and float(price_avg) > 0:
                            return float(price_avg)
        except Exception as e:
            logger.warning(f"Failed to get close fill price for {symbol}: {e}")
        return None

    async def get_funding_fees(
        self, symbol: str, start_time_ms: int, end_time_ms: int
    ) -> float:
        """Get total funding fees paid for a symbol between start and end time.

        Queries /api/v2/mix/account/bill filtered by businessType=contract_settle_fee.
        Funding fees are charged every 8h while holding a position.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            start_time_ms: Trade entry time in milliseconds
            end_time_ms: Trade exit time in milliseconds

        Returns total absolute funding paid (always positive). Returns 0.0 on error.
        """
        try:
            params = {
                "productType": PRODUCT_TYPE_USDT,
                "symbol": symbol,
                "businessType": "contract_settle_fee",
                "startTime": str(start_time_ms),
                "endTime": str(end_time_ms),
                "limit": "100",
            }
            data = await self._request("GET", ENDPOINTS["account_bill"], params=params)
            bills = data.get("bills", data) if isinstance(data, dict) else data
            if not isinstance(bills, list):
                return 0.0

            total_funding = 0.0
            for bill in bills:
                amount_str = bill.get("amount", "0")
                if amount_str:
                    total_funding += abs(float(amount_str))

            return round(total_funding, 6)
        except Exception as e:
            logger.warning(f"Failed to get funding fees for {symbol}: {e}")
            return 0.0

    async def get_fill_price(
        self, symbol: str, order_id: str, max_retries: int = 3, retry_delay: float = 0.5,
    ) -> Optional[float]:
        """Get actual fill price for a completed order with retry."""
        for attempt in range(max_retries):
            try:
                params = {
                    "symbol": symbol,
                    "productType": PRODUCT_TYPE_USDT,
                    "orderId": order_id,
                }
                detail = await self._request("GET", ENDPOINTS["order_detail"], params=params)
                if detail:
                    fill_price = detail.get("priceAvg") or detail.get("fillPrice")
                    if fill_price and float(fill_price) > 0:
                        return float(fill_price)
            except Exception as e:
                logger.warning(f"Error getting fill price (attempt {attempt + 1}): {e}")
            await asyncio.sleep(retry_delay * (2 ** attempt))
        return None
