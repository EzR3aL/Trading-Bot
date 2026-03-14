"""
Bitget Exchange Client implementing the ExchangeClient ABC.

Refactored from src/api/bitget_client.py to use normalized types.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import math
import time
from typing import Any, Dict, List, Literal, Optional

import aiohttp

from src.exceptions import ExchangeError
from src.exchanges.base import ExchangeClient
from src.exchanges.bitget.constants import (
    BASE_URL,
    ENDPOINTS,
    PRODUCT_TYPE_USDT,
    SUCCESS_CODE,
    TESTNET_URL,
)
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.utils.circuit_breaker import CircuitBreakerError, circuit_registry, with_retry
from src.utils.logger import get_logger

logger = get_logger(__name__)

_bitget_breaker = circuit_registry.get("bitget_api", fail_threshold=5, reset_timeout=60)


class BitgetClientError(ExchangeError):
    """Custom exception for Bitget API errors."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__("bitget", message, original_error)


class BitgetExchangeClient(ExchangeClient):
    """
    Async client for Bitget Futures API implementing ExchangeClient ABC.

    Supports demo trading via paptrading header.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        demo_mode: bool = True,
        testnet: bool = False,
        **kwargs,
    ):
        super().__init__(api_key, api_secret, passphrase, demo_mode)
        self.testnet = testnet
        self.base_url = TESTNET_URL if testnet else BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None
        mode_str = "DEMO" if demo_mode else "LIVE"
        logger.info(f"BitgetExchangeClient initialized in {mode_str} mode")

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def exchange_name(self) -> str:
        return "bitget"

    @property
    def supports_demo(self) -> bool:
        return True

    # ==================== Auth ====================

    def _generate_signature(self, timestamp: str, method: str,
                            request_path: str, body: str = "") -> str:
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method: str, request_path: str,
                     body: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, request_path, body)
        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }
        if self.demo_mode:
            headers["paptrading"] = "1"
        return headers

    # ==================== HTTP ====================

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth: bool = True,
        use_circuit_breaker: bool = True,
    ) -> Dict[str, Any]:
        if use_circuit_breaker:
            async def _do():
                return await self._raw_request(method, endpoint, params, data, auth)
            try:
                return await _bitget_breaker.call(_do)
            except CircuitBreakerError as e:
                raise BitgetClientError(f"API temporarily unavailable: {e}")
        return await self._raw_request(method, endpoint, params, data, auth)

    @with_retry(max_attempts=3, min_wait=1.0, max_wait=10.0,
                retry_on=(aiohttp.ClientError, asyncio.TimeoutError))
    async def _raw_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth: bool = True,
    ) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(data) if data else ""

        if params:
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            request_path = f"{endpoint}?{query_string}"
            url = f"{url}?{query_string}"
        else:
            request_path = endpoint

        headers = (
            self._get_headers(method, request_path, body)
            if auth
            else {"Content-Type": "application/json"}
        )

        try:
            async with self._session.request(
                method=method,
                url=url,
                headers=headers,
                data=body if body else None,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                result = await response.json()

                if response.status == 429:
                    raise aiohttp.ClientResponseError(
                        response.request_info, response.history,
                        status=429, message="Rate limited",
                    )

                if response.status != 200:
                    raise BitgetClientError(
                        f"API Error: {result.get('msg', 'Unknown error')}"
                    )

                if result.get("code") != SUCCESS_CODE:
                    raise BitgetClientError(
                        f"Bitget Error: {result.get('msg', 'Unknown error')}"
                    )

                return result.get("data", result)

        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise

    # ==================== ABC Implementation ====================

    async def get_account_balance(self) -> Balance:
        endpoint = ENDPOINTS["account_balance"]
        params = {
            "symbol": "BTCUSDT",
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
        }
        data = await self._request("GET", endpoint, params=params)

        if isinstance(data, list):
            data = data[0] if data else {}

        logger.debug(
            "Bitget balance: equity=%s available=%s crossedMax=%s unrealizedPL=%s",
            data.get("accountEquity"), data.get("available"),
            data.get("crossedMaxAvailable"), data.get("unrealizedPL"),
        )

        return Balance(
            total=float(data.get("accountEquity", 0) or data.get("usdtEquity", 0)),
            available=float(data.get("crossedMaxAvailable", 0) or data.get("available", 0)),
            unrealized_pnl=float(data.get("unrealizedPL", 0)),
            currency="USDT",
        )

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: int,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        margin_mode: str = "cross",
    ) -> Order:
        # Set leverage first
        await self.set_leverage(symbol, leverage, margin_mode=margin_mode)

        api_margin = "crossed" if margin_mode == "cross" else "isolated"
        order_side = "buy" if side == "long" else "sell"
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": api_margin,
            "marginCoin": "USDT",
            "side": order_side,
            "tradeSide": "open",
            "orderType": "market",
            "size": str(size),
        }

        result = await self._request("POST", ENDPOINTS["place_order"], data=data)

        order_id = result.get("orderId", result.get("data", {}).get("orderId", ""))

        # Set Entire TP/SL via dedicated endpoint (covers full position)
        # Brief delay to ensure order fill is registered before setting TP/SL
        tpsl_failed = False
        if take_profit is not None or stop_loss is not None:
            await asyncio.sleep(0.2)
            for attempt in range(2):
                try:
                    await self._set_position_tpsl(
                        symbol=symbol,
                        hold_side=side,
                        take_profit=take_profit,
                        stop_loss=stop_loss,
                    )
                    tpsl_failed = False
                    break
                except Exception as e:
                    tpsl_failed = True
                    if attempt == 0:
                        logger.warning(f"TP/SL attempt 1 failed for {symbol}, retrying: {e}")
                        await asyncio.sleep(0.5)
                    else:
                        logger.error(
                            f"CRITICAL: TP/SL failed for {symbol} after 2 attempts: {e}. "
                            "Position is UNPROTECTED — manual intervention required."
                        )

        return Order(
            order_id=str(order_id),
            symbol=symbol,
            side=side,
            size=size,
            price=0.0,  # Market order; fill price obtained separately
            status="filled",
            exchange="bitget",
            leverage=leverage,
            take_profit=take_profit,
            stop_loss=stop_loss,
            tpsl_failed=tpsl_failed,
        )

    async def _set_position_tpsl(
        self,
        symbol: str,
        hold_side: str,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
    ) -> None:
        """Set Entire TP/SL for a position (covers full position size)."""
        contract = await self._get_contract_info(symbol)
        pp = contract["pricePlace"]
        ps = contract["priceEndStep"]

        tpsl_data: Dict[str, str] = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
            "holdSide": hold_side,
        }
        if take_profit is not None:
            tpsl_data["stopSurplusTriggerPrice"] = str(self._round_price(take_profit, pp, ps))
            tpsl_data["stopSurplusTriggerType"] = "fill_price"
        if stop_loss is not None:
            tpsl_data["stopLossTriggerPrice"] = str(self._round_price(stop_loss, pp, ps))
            tpsl_data["stopLossTriggerType"] = "fill_price"

        await self._request(
            "POST",
            "/api/v2/mix/order/place-pos-tpsl",
            data=tpsl_data,
        )
        logger.info(f"Entire TP/SL set for {symbol} {hold_side}: TP={take_profit}, SL={stop_loss}")

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "orderId": order_id,
        }
        try:
            await self._request("POST", ENDPOINTS["cancel_order"], data=data)
            return True
        except BitgetClientError:
            return False

    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        # Get position size and actual hold side from exchange
        pos = await self.get_position(symbol)
        if not pos:
            return None

        actual_side = pos.side  # "long" or "short" from exchange

        # Use flash-close endpoint (works reliably in both hedge and one-way mode)
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "holdSide": actual_side,
        }
        result = await self._request("POST", ENDPOINTS["close_positions"], data=data)

        success_list = result.get("successList", [])
        order_id = success_list[0].get("orderId", "") if success_list else ""

        return Order(
            order_id=str(order_id),
            symbol=symbol,
            side=side,
            size=pos.size,
            price=0.0,
            status="filled",
            exchange="bitget",
        )

    async def get_position(self, symbol: str) -> Optional[Position]:
        params = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
        }
        data = await self._request("GET", ENDPOINTS["single_position"], params=params)

        positions = data if isinstance(data, list) else [data] if data else []
        for pos in positions:
            total = float(pos.get("total", 0))
            if total > 0:
                return Position(
                    symbol=symbol,
                    side=pos.get("holdSide", "long"),
                    size=total,
                    entry_price=float(pos.get("openPriceAvg", 0)),
                    current_price=float(pos.get("markPrice", 0)),
                    unrealized_pnl=float(pos.get("unrealizedPL", 0)),
                    leverage=int(pos.get("leverage", 1)),
                    exchange="bitget",
                    margin=float(pos.get("margin", 0)),
                    liquidation_price=float(pos.get("liquidationPrice", 0) or 0),
                )
        return None

    async def get_open_positions(self) -> List[Position]:
        params = {
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
        }
        data = await self._request("GET", ENDPOINTS["all_positions"], params=params)
        positions = []
        items = data if isinstance(data, list) else []
        for pos in items:
            total = float(pos.get("total", 0))
            if total > 0:
                positions.append(
                    Position(
                        symbol=pos.get("symbol", ""),
                        side=pos.get("holdSide", "long"),
                        size=total,
                        entry_price=float(pos.get("openPriceAvg", 0)),
                        current_price=float(pos.get("markPrice", 0)),
                        unrealized_pnl=float(pos.get("unrealizedPL", 0)),
                        leverage=int(pos.get("leverage", 1)),
                        exchange="bitget",
                        margin=float(pos.get("margin", 0)),
                        liquidation_price=float(pos.get("liquidationPrice", 0) or 0),
                    )
                )
        return positions

    async def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        for hold_side in ("long", "short"):
            data = {
                "symbol": symbol,
                "productType": PRODUCT_TYPE_USDT,
                "marginCoin": "USDT",
                "leverage": str(leverage),
                "holdSide": hold_side,
            }
            try:
                # Skip circuit breaker — leverage errors are expected when
                # a position already exists and should not poison the breaker
                await self._request("POST", ENDPOINTS["set_leverage"], data=data,
                                    use_circuit_breaker=False)
            except BitgetClientError as e:
                err_msg = str(e).lower()
                # "already set" is fine — leverage matches what we want
                if "same" in err_msg or "not changed" in err_msg or "equal" in err_msg:
                    continue
                # Position open with different leverage — cannot change
                logger.warning("set_leverage failed for %s %s: %s", symbol, hold_side, e)
                return False
        return True

    async def get_ticker(self, symbol: str) -> Ticker:
        params = {"symbol": symbol, "productType": PRODUCT_TYPE_USDT}
        data = await self._request("GET", ENDPOINTS["ticker"], params=params, auth=False)

        if isinstance(data, list):
            data = data[0] if data else {}

        return Ticker(
            symbol=symbol,
            last_price=float(data.get("lastPr", 0) or data.get("last", 0)),
            bid=float(data.get("bidPr", 0) or data.get("bestBid", 0)),
            ask=float(data.get("askPr", 0) or data.get("bestAsk", 0)),
            volume_24h=float(data.get("baseVolume", 0) or data.get("volume24h", 0)),
            high_24h=float(data.get("high24h", 0)) if data.get("high24h") else None,
            low_24h=float(data.get("low24h", 0)) if data.get("low24h") else None,
            change_24h_percent=float(data.get("change24h", 0)) if data.get("change24h") else None,
        )

    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        params = {"symbol": symbol, "productType": PRODUCT_TYPE_USDT}
        data = await self._request(
            "GET", ENDPOINTS["funding_rate"], params=params, auth=False
        )

        if isinstance(data, list):
            data = data[0] if data else {}

        return FundingRateInfo(
            symbol=symbol,
            current_rate=float(data.get("fundingRate", 0)),
        )

    # ==================== Trailing Stop ====================

    async def _get_contract_info(self, symbol: str) -> dict:
        """Fetch contract specification for a symbol from Bitget contracts API.

        Returns dict with 'volumePlace' and 'pricePlace' (decimal precision).
        """
        try:
            result = await self._request(
                "GET", ENDPOINTS["contracts"],
                params={"productType": PRODUCT_TYPE_USDT, "symbol": symbol},
                use_circuit_breaker=False,
            )
            contracts = result if isinstance(result, list) else [result] if result else []
            for c in contracts:
                if c.get("symbol") == symbol:
                    return {
                        "volumePlace": int(c.get("volumePlace", 2)),
                        "pricePlace": int(c.get("pricePlace", 2)),
                        "priceEndStep": int(c.get("priceEndStep", 1)),
                    }
        except Exception:
            pass
        return {"volumePlace": 2, "pricePlace": 2, "priceEndStep": 1}

    async def _get_volume_place(self, symbol: str) -> int:
        """Fetch volumePlace (size decimal precision) for a symbol."""
        info = await self._get_contract_info(symbol)
        return info["volumePlace"]

    def _round_price(self, price: float, price_place: int, price_end_step: int) -> float:
        """Round price to exchange precision using pricePlace and priceEndStep.

        pricePlace = number of decimal places (e.g. 1 for BTC → $70000.1)
        priceEndStep = minimum tick increment at the last decimal
                       (e.g. 5 means price must end in 0 or 5)
        """
        factor = 10 ** price_place
        stepped = math.floor(price * factor / price_end_step) * price_end_step
        return stepped / factor

    async def place_trailing_stop(
        self,
        symbol: str,
        hold_side: str,
        size: float,
        callback_ratio: float,
        trigger_price: float,
        margin_mode: str = "cross",
    ) -> Optional[dict]:
        """Place a position-level trailing stop (moving_plan) on Bitget.

        Uses place-tpsl-order with planType=moving_plan, which shows up in
        the Bitget UI under "Trailing TP/SL" on the position card.

        Args:
            symbol: Trading pair (e.g. "BTCUSDT")
            hold_side: "long" or "short"
            size: Position size
            callback_ratio: Trail distance in % (e.g. 2.5 = 2.5%)
            trigger_price: Price at which trailing begins
            margin_mode: "cross" or "isolated"

        Returns:
            API response dict or None on failure.
        """
        api_margin = "crossed" if margin_mode == "cross" else "isolated"

        # Fetch contract precision for size and price
        contract = await self._get_contract_info(symbol)
        volume_place = contract["volumePlace"]
        rounded_size = math.floor(size * 10**volume_place) / 10**volume_place

        # Round trigger price to exchange precision
        rounded_trigger = self._round_price(
            trigger_price, contract["pricePlace"], contract["priceEndStep"],
        )

        # rangeRate must have exactly 2 decimal places
        range_rate = f"{callback_ratio:.2f}"

        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": api_margin,
            "marginCoin": "USDT",
            "planType": "moving_plan",
            "triggerPrice": str(rounded_trigger),
            "triggerType": "mark_price",
            "rangeRate": range_rate,
            "holdSide": hold_side,
            "size": str(rounded_size),
        }

        result = await self._request(
            "POST", ENDPOINTS["place_tpsl_order"], data=data,
            use_circuit_breaker=False,
        )
        logger.info(
            "Trailing stop placed on Bitget: %s %s size=%s rangeRate=%s%% trigger=$%.2f",
            symbol, hold_side, rounded_size, range_rate, trigger_price,
        )
        return result

    # ==================== Additional Bitget-specific methods ====================

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
            # Search orders-history for the most recent close order on this symbol
            try:
                params = {
                    "symbol": symbol,
                    "productType": PRODUCT_TYPE_USDT,
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
        """
        try:
            params = {
                "symbol": symbol,
                "productType": PRODUCT_TYPE_USDT,
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

    async def get_raw_account_balance(self, margin_coin: str = "USDT") -> Dict[str, Any]:
        """Get raw account balance data (Bitget-specific format)."""
        params = {
            "symbol": "BTCUSDT",
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": margin_coin,
        }
        return await self._request("GET", ENDPOINTS["account_balance"], params=params)

    async def get_raw_position(self, symbol: str) -> Dict[str, Any]:
        """Get raw position data (Bitget-specific format)."""
        params = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginCoin": "USDT",
        }
        return await self._request("GET", ENDPOINTS["single_position"], params=params)

    async def place_raw_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        trade_side: Literal["open", "close"],
        size: str,
        order_type: Literal["market", "limit"] = "market",
        price: Optional[str] = None,
        take_profit: Optional[str] = None,
        stop_loss: Optional[str] = None,
        margin_mode: str = "cross",
    ) -> Dict[str, Any]:
        """Place an order using raw Bitget API format."""
        api_margin = "crossed" if margin_mode == "cross" else "isolated"
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": api_margin,
            "marginCoin": "USDT",
            "side": side,
            "tradeSide": trade_side,
            "orderType": order_type,
            "size": size,
        }
        if price and order_type == "limit":
            data["price"] = price
        if take_profit:
            data["presetStopSurplusPrice"] = take_profit
        if stop_loss:
            data["presetStopLossPrice"] = stop_loss

        return await self._request("POST", ENDPOINTS["place_order"], data=data)

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a UID is in our affiliate referral list via Bitget Affiliate API."""
        try:
            page = 1
            while True:
                result = await self._request(
                    "GET",
                    "/api/v2/affiliate/entity/customerInfo/GetDirectCommissions",
                    params={"page": str(page), "pageSize": "200"},
                )
                items = result if isinstance(result, list) else result.get("list", [])
                for item in items:
                    if str(item.get("uid", "")) == str(uid):
                        return True
                if not items or len(items) < 200:
                    break
                page += 1
            return False
        except Exception as e:
            logger.warning(f"Affiliate UID check failed for {uid}: {e}")
            return False

    def calculate_position_size(
        self, balance: float, price: float, risk_percent: float, leverage: int,
    ) -> float:
        """Calculate position size based on risk parameters."""
        risk_amount = balance * (risk_percent / 100)
        position_value = risk_amount * leverage
        return round(position_value / price, 6)
