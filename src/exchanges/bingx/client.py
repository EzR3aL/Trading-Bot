"""
BingX Exchange Client implementing the ExchangeClient ABC.

BingX Perpetual Swap V2 API with HMAC-SHA256 authentication.
Supports both live and VST (Virtual Simulated Trading) demo mode.

API Reference: https://bingx-api.github.io/docs/#/swapV2/introduce
"""

import asyncio
import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from src.exceptions import ExchangeError
from src.exchanges.base import ExchangeClient
from src.exchanges.bingx.constants import (
    BASE_URL,
    CONDITIONAL_ORDER_TYPES,
    DEFAULT_RECV_WINDOW,
    ENDPOINTS,
    ERROR_CODES,
    MARGIN_CROSSED,
    MARGIN_ISOLATED,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_TRAILING_STOP_MARKET,
    POSITION_LONG,
    POSITION_SHORT,
    SIDE_BUY,
    SIDE_SELL,
    SUCCESS_CODE,
    TESTNET_URL,
)
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.utils.circuit_breaker import CircuitBreakerError, circuit_registry, with_retry
from src.utils.logger import get_logger

logger = get_logger(__name__)

_bingx_breaker = circuit_registry.get("bingx_api", fail_threshold=5, reset_timeout=60)


class BingXClientError(ExchangeError):
    """Custom exception for BingX API errors."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__("bingx", message, original_error)


class BingXClient(ExchangeClient):
    """
    Async client for BingX Perpetual Swap API implementing ExchangeClient ABC.

    BingX authentication uses HMAC-SHA256 signature on query parameters.
    The API key is sent via the X-BX-APIKEY header, while the signature
    is appended as a query parameter.

    Demo trading is supported via the VST (Virtual Simulated Trading)
    mode, which uses a separate base URL.

    Symbol format: BTC-USDT (hyphenated)
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
        super().__init__(api_key, api_secret, passphrase, demo_mode, **kwargs)
        self.testnet = testnet
        # BingX demo mode uses a separate VST domain
        if demo_mode:
            self.base_url = TESTNET_URL
        elif testnet:
            self.base_url = TESTNET_URL
        else:
            self.base_url = BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None
        mode_str = "DEMO (VST)" if demo_mode else "LIVE"
        logger.info(f"BingXClient initialized in {mode_str} mode")

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
        return "bingx"

    @staticmethod
    def _is_close_fill(fill: dict) -> bool:
        """Detect if a fill represents a position close.

        Handles both dual-side mode (positionSide=LONG/SHORT) and
        one-way mode (VST demo) where positionSide may be empty or BOTH.
        In one-way mode, BingX uses reduceOnly or the fill's profit field
        to indicate a close.
        """
        pos_side = fill.get("positionSide", "").upper()
        fill_side = fill.get("side", "").upper()

        # Dual-side mode: explicit positionSide
        if pos_side in ("LONG", "SHORT"):
            return (
                (fill_side == "SELL" and pos_side == "LONG") or
                (fill_side == "BUY" and pos_side == "SHORT")
            )

        # One-way / VST mode: check reduceOnly flag or profit field
        if str(fill.get("reduceOnly", "")).lower() == "true":
            return True
        # A non-zero profit/realizedPnl means the fill closed a position
        profit = fill.get("profit") or fill.get("realizedPnl") or fill.get("realisedPnl")
        if profit and float(profit) != 0:
            return True

        return False

    @property
    def supports_demo(self) -> bool:
        return True

    # ==================== Auth ====================

    def _generate_signature(self, params_str: str) -> str:
        """
        Generate HMAC-SHA256 signature for BingX API.

        BingX signs the full query string (all parameters joined by &)
        using the API secret and returns the hex digest.
        """
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            params_str.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        return signature

    def _get_headers(self) -> Dict[str, str]:
        """
        Build request headers.

        BingX uses the X-BX-APIKEY header for authentication.
        The signature is sent as a query parameter, not a header.
        Note: Do NOT set Content-Type for authenticated requests — all params
        are sent as query string, not JSON body. VST API rejects requests
        with Content-Type: application/json when the body is empty.
        """
        return {
            "X-BX-APIKEY": self.api_key,
        }

    def _build_signed_params(self, params: Optional[Dict] = None) -> str:
        """
        Build signed query string with timestamp and signature.

        BingX signature flow:
        1. Add timestamp to parameters
        2. Sort and URL-encode all parameters into a query string
        3. HMAC-SHA256 sign the query string with the API secret
        4. Append signature= to the query string

        Returns the full query string with signature appended.
        """
        if params is None:
            params = {}

        # Add timestamp (milliseconds)
        params["timestamp"] = str(int(time.time() * 1000))
        params["recvWindow"] = str(DEFAULT_RECV_WINDOW)

        # Build query string (sorted for consistency)
        sorted_params = sorted(params.items())
        query_string = urlencode(sorted_params)

        # Generate signature
        signature = self._generate_signature(query_string)

        # Append signature to query string
        return f"{query_string}&signature={signature}"

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
                return await _bingx_breaker.call(_do)
            except CircuitBreakerError as e:
                raise BingXClientError(f"API temporarily unavailable: {e}")
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
        """
        Execute an HTTP request to BingX API.

        BingX sends authentication via:
        - Header: X-BX-APIKEY = api_key
        - Query param: signature = HMAC-SHA256(query_string, api_secret)
        - Query param: timestamp = current time in ms

        For GET/DELETE: all params go in query string (signed)
        For POST: params go in query string (signed), body is empty or
                  params are sent as query string on the URL
        """
        await self._ensure_session()

        url = f"{self.base_url}{endpoint}"

        if auth:
            headers = self._get_headers()
            # BingX sends all parameters (including POST body params) as
            # query string parameters for signature purposes
            all_params = {}
            if params:
                all_params.update(params)
            if data:
                all_params.update(data)

            signed_query = self._build_signed_params(all_params)
            url = f"{url}?{signed_query}"
            body = None
        else:
            headers = {"Content-Type": "application/json"}
            if params:
                query_string = urlencode(sorted(params.items()))
                url = f"{url}?{query_string}"
            body = None

        try:
            async with self._session.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                result = await response.json()

                if response.status == 429:
                    raise aiohttp.ClientResponseError(
                        response.request_info, response.history,
                        status=429, message="Rate limited",
                    )

                if response.status != 200:
                    error_msg = result.get("msg", "Unknown error")
                    raise BingXClientError(
                        f"HTTP {response.status}: {error_msg}"
                    )

                # BingX returns {"code": 0, "msg": "", "data": {...}}
                # Code 0 means success
                code = result.get("code", -1)
                if code != SUCCESS_CODE:
                    error_msg = result.get("msg", "Unknown error")
                    error_desc = ERROR_CODES.get(code, "")
                    full_msg = f"BingX Error {code}: {error_msg}"
                    if error_desc:
                        full_msg += f" ({error_desc})"
                    raise BingXClientError(full_msg)

                return result.get("data", result)

        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise

    # ==================== ABC Implementation ====================

    async def get_account_balance(self) -> Balance:
        """
        Get account balance for USDT perpetual account.

        BingX endpoint: GET /openApi/swap/v3/user/balance
        """
        data = await self._request("GET", ENDPOINTS["account_balance"])

        # V3 balance response can be:
        # - a list of account objects: [{"asset": "VST", "equity": "100000", ...}]
        # - a dict with "balance" key: {"balance": {...}}
        # - a dict directly: {"equity": "...", ...}
        if isinstance(data, list) and data:
            balance_data = data[0]
        elif isinstance(data, dict):
            balance_data = data
            if "balance" in balance_data:
                balance_data = balance_data["balance"]
        else:
            balance_data = {}

        # BingX balance fields:
        # equity = total account equity
        # availableMargin = available for new positions
        # unrealizedProfit = total unrealized PnL
        # balance = wallet balance
        return Balance(
            total=float(balance_data.get("equity", 0) or balance_data.get("balance", 0)),
            available=float(balance_data.get("availableMargin", 0)),
            unrealized_pnl=float(balance_data.get("unrealizedProfit", 0)),
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
        """
        Place a market order on BingX perpetual swap.

        BingX endpoint: POST /openApi/swap/v2/trade/order
        BingX uses dual-side position mode with positionSide (LONG/SHORT)
        and order side (BUY/SELL).

        Opening long: side=BUY, positionSide=LONG
        Opening short: side=SELL, positionSide=SHORT
        """
        # Leverage is set by trade_executor before calling this method

        # Map normalized side to BingX order parameters
        order_side = SIDE_BUY if side == "long" else SIDE_SELL
        position_side = POSITION_LONG if side == "long" else POSITION_SHORT

        # Round quantity to avoid float precision artifacts (e.g. 0.03400000001)
        rounded_size = self._round_quantity(size)

        order_params = {
            "symbol": symbol,
            "side": order_side,
            "positionSide": position_side,
            "type": ORDER_TYPE_MARKET,
            "quantity": str(rounded_size),
        }

        # BingX supports TP/SL as part of the order placement
        if take_profit is not None:
            order_params["takeProfit"] = str(take_profit)
            order_params["takeProfitWorkingType"] = "MARK_PRICE"
        if stop_loss is not None:
            order_params["stopLoss"] = str(stop_loss)
            order_params["stopLossWorkingType"] = "MARK_PRICE"

        result = await self._request("POST", ENDPOINTS["place_order"], data=order_params)

        # Extract order info from response
        order_data = result.get("order", result) if isinstance(result, dict) else result
        order_id = ""
        if isinstance(order_data, dict):
            order_id = str(order_data.get("orderId", ""))
        elif isinstance(result, dict):
            order_id = str(result.get("orderId", ""))

        return Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            size=size,
            price=0.0,  # Market order; fill price obtained separately
            status="filled",
            exchange="bingx",
            leverage=leverage,
            take_profit=take_profit,
            stop_loss=stop_loss,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """
        Cancel an open order.

        BingX endpoint: DELETE /openApi/swap/v2/trade/order
        """
        params = {
            "symbol": symbol,
            "orderId": order_id,
        }
        try:
            await self._request("DELETE", ENDPOINTS["cancel_order"], params=params)
            return True
        except BingXClientError as e:
            logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        """
        Close an open position by placing an opposing market order.

        Closing long: side=SELL, positionSide=LONG
        Closing short: side=BUY, positionSide=SHORT
        """
        # Get current position to determine size
        pos = await self.get_position(symbol)
        if not pos:
            logger.info(f"No open position found for {symbol}")
            return None

        # Determine closing order parameters
        close_side = SIDE_SELL if side == "long" else SIDE_BUY
        position_side = POSITION_LONG if side == "long" else POSITION_SHORT

        order_params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": position_side,
            "type": ORDER_TYPE_MARKET,
            "quantity": str(self._round_quantity(pos.size)),
        }

        result = await self._request("POST", ENDPOINTS["place_order"], data=order_params)

        order_data = result.get("order", result) if isinstance(result, dict) else result
        order_id = ""
        if isinstance(order_data, dict):
            order_id = str(order_data.get("orderId", ""))

        return Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            size=pos.size,
            price=0.0,
            status="filled",
            exchange="bingx",
        )

    async def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get current position for a specific symbol.

        BingX endpoint: GET /openApi/swap/v2/user/positions?symbol=...
        """
        params = {"symbol": symbol}
        data = await self._request("GET", ENDPOINTS["single_position"], params=params)

        positions = self._parse_positions_response(data)
        for pos in positions:
            if abs(float(pos.get("positionAmt", 0))) > 0:
                return self._normalize_position(pos)

        return None

    async def get_open_positions(self) -> List[Position]:
        """
        Get all open positions.

        BingX endpoint: GET /openApi/swap/v2/user/positions
        """
        data = await self._request("GET", ENDPOINTS["all_positions"])

        positions = []
        items = self._parse_positions_response(data)
        for pos in items:
            if abs(float(pos.get("positionAmt", 0))) > 0:
                normalized = self._normalize_position(pos)
                if normalized:
                    positions.append(normalized)
        return positions

    async def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        """
        Set leverage and margin type for a symbol.

        BingX endpoints:
          POST /openApi/swap/v2/trade/marginType - set margin mode
          POST /openApi/swap/v2/trade/leverage - set leverage per side

        Note: BingX VST (demo) API does not support these endpoints and returns
        error 109400. In demo mode we log and proceed — trades use defaults.
        """
        # Set margin type first
        bingx_margin = MARGIN_CROSSED if margin_mode == "cross" else MARGIN_ISOLATED
        try:
            await self._request("POST", ENDPOINTS["set_margin_type"], data={
                "symbol": symbol,
                "marginType": bingx_margin,
            })
        except BingXClientError as e:
            err_msg = str(e).lower()
            if "no need" not in err_msg and "same" not in err_msg:
                if self.demo_mode and ("109400" in str(e) or "invalid param" in err_msg):
                    logger.debug("VST does not support set_margin_type for %s (expected)", symbol)
                else:
                    logger.warning("set_margin_type failed for %s: %s", symbol, e)

        for pos_side in (POSITION_LONG, POSITION_SHORT):
            params = {
                "symbol": symbol,
                "side": pos_side,
                "leverage": str(leverage),
            }
            try:
                await self._request("POST", ENDPOINTS["set_leverage"], data=params)
            except BingXClientError as e:
                err_msg = str(e).lower()
                if "same" in err_msg or "not changed" in err_msg:
                    continue
                if self.demo_mode and ("109400" in str(e) or "invalid param" in err_msg):
                    logger.debug("VST does not support set_leverage for %s %s (expected)", symbol, pos_side)
                    continue
                logger.warning("set_leverage failed for %s %s: %s", symbol, pos_side, e)
                return False
        return True

    async def get_ticker(self, symbol: str) -> Ticker:
        """
        Get current ticker/market data for a symbol.

        BingX endpoint: GET /openApi/swap/v2/quote/ticker?symbol=...
        """
        params = {"symbol": symbol}
        data = await self._request(
            "GET", ENDPOINTS["ticker"], params=params, auth=False
        )

        # Response may be a single dict or a list
        ticker_data = data
        if isinstance(data, list):
            ticker_data = data[0] if data else {}

        return Ticker(
            symbol=symbol,
            last_price=float(ticker_data.get("lastPrice", 0)),
            bid=float(ticker_data.get("bidPrice", 0)),
            ask=float(ticker_data.get("askPrice", 0)),
            volume_24h=float(ticker_data.get("volume", 0) or ticker_data.get("quoteVolume", 0)),
            high_24h=_safe_float(ticker_data.get("highPrice")),
            low_24h=_safe_float(ticker_data.get("lowPrice")),
            change_24h_percent=_safe_float(ticker_data.get("priceChangePercent")),
        )

    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        """
        Get current funding rate information.

        BingX endpoint: GET /openApi/swap/v2/quote/premiumIndex?symbol=...
        (premiumIndex includes current funding rate and next funding time)
        """
        params = {"symbol": symbol}
        data = await self._request(
            "GET", ENDPOINTS["premium_index"], params=params, auth=False
        )

        # May be list or dict
        rate_data = data
        if isinstance(data, list):
            rate_data = data[0] if data else {}

        next_funding_time = None
        next_ts = rate_data.get("nextFundingTime")
        if next_ts:
            try:
                next_funding_time = datetime.fromtimestamp(
                    int(next_ts) / 1000, tz=timezone.utc
                )
            except (ValueError, TypeError):
                pass

        return FundingRateInfo(
            symbol=symbol,
            current_rate=float(rate_data.get("lastFundingRate", 0)),
            next_funding_time=next_funding_time,
            predicted_rate=None,  # BingX estimatedSettlePrice is a price, not a rate
        )

    # ==================== Fee & Fill Methods ====================

    async def get_order_fees(self, symbol: str, order_id: str) -> float:
        """
        Get total fees paid for a single order.

        BingX endpoint: GET /openApi/swap/v2/trade/order?symbol=...&orderId=...
        Returns absolute fee value (always positive). Returns 0.0 on error.
        """
        try:
            params = {
                "symbol": symbol,
                "orderId": order_id,
            }
            detail = await self._request("GET", ENDPOINTS["order_detail"], params=params)
            if not detail:
                return 0.0

            # BingX uses "commission" field for fees
            fee_str = detail.get("commission") or detail.get("fee")
            if fee_str and str(fee_str) != "0":
                return abs(float(fee_str))

            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get order fees for {order_id}: {e}")
            return 0.0

    async def get_trade_total_fees(
        self, symbol: str, entry_order_id: str, close_order_id: Optional[str] = None
    ) -> float:
        """
        Get total fees (entry + exit) for a complete trade.

        Returns total absolute fees (always positive). Returns 0.0 on error.
        """
        total_fees = 0.0

        # Entry fees
        if entry_order_id:
            total_fees += await self.get_order_fees(symbol, entry_order_id)

        # Exit fees
        if close_order_id:
            total_fees += await self.get_order_fees(symbol, close_order_id)
        else:
            # Search fill history for recent close orders
            try:
                params = {
                    "symbol": symbol,
                    "limit": "20",
                }
                data = await self._request("GET", ENDPOINTS["all_fill_orders"], params=params)
                fills = data if isinstance(data, list) else data.get("fills", []) if isinstance(data, dict) else []
                if isinstance(fills, list):
                    for fill in fills:
                        if self._is_close_fill(fill):
                            fee_str = fill.get("commission") or fill.get("fee")
                            if fee_str:
                                total_fees += abs(float(fee_str))
                            break
            except Exception as e:
                logger.warning(f"Failed to get close order fees from history for {symbol}: {e}")

        return round(total_fees, 6)

    async def get_fill_price(
        self, symbol: str, order_id: str, max_retries: int = 3, retry_delay: float = 0.5,
    ) -> Optional[float]:
        """
        Get actual fill price for a completed order with retry.

        BingX endpoint: GET /openApi/swap/v2/trade/order?symbol=...&orderId=...
        """
        for attempt in range(max_retries):
            try:
                params = {
                    "symbol": symbol,
                    "orderId": order_id,
                }
                detail = await self._request("GET", ENDPOINTS["order_detail"], params=params)
                if detail and isinstance(detail, dict):
                    # BingX uses "avgPrice" for fill price
                    fill_price = detail.get("avgPrice") or detail.get("price")
                    if fill_price and float(fill_price) > 0:
                        return float(fill_price)
            except Exception as e:
                logger.warning(f"Error getting fill price (attempt {attempt + 1}): {e}")
            await asyncio.sleep(retry_delay * (2 ** attempt))
        return None

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        """Get fill price of the most recent close order from BingX fills.

        Returns the fill price, or None if not found.
        Also stores the close order ID on self._last_close_order_id for fee lookup.
        """
        self._last_close_order_id = None
        try:
            params = {"symbol": symbol, "limit": "20"}
            data = await self._request("GET", ENDPOINTS["all_fill_orders"], params=params)
            fills = data if isinstance(data, list) else data.get("fills", []) if isinstance(data, dict) else []
            if isinstance(fills, list):
                for fill in fills:
                    if self._is_close_fill(fill):
                        price = fill.get("price") or fill.get("avgPrice")
                        if price and float(price) > 0:
                            self._last_close_order_id = str(fill.get("orderId", ""))
                            return float(price)
        except Exception as e:
            logger.warning(f"Failed to get close fill price for {symbol}: {e}")
        return None

    async def place_trailing_stop(
        self,
        symbol: str,
        hold_side: str,
        size: float,
        callback_ratio: float,
        trigger_price: float,
        margin_mode: str = "cross",
    ) -> Optional[dict]:
        """Place a trailing stop order on BingX.

        Uses TRAILING_STOP_MARKET order type with ``activationPrice`` (the
        price at which the trail starts) and ``priceRate`` (callback rate in
        fractional form, e.g. 0.031 for 3.10%).

        BingX rejects orders that send both ``price`` and ``priceRate`` (error
        109400) because ``price`` means "trail distance in USDT" — an
        alternative to ``priceRate`` rather than an activation trigger. The
        correct field for activation is ``activationPrice``. Refer to
        https://github.com/BingX-API/BingX-swap-api-doc/issues/28 for the
        official confirmation.
        """
        # Closing side is opposite of position side
        close_side = SIDE_SELL if hold_side == "long" else SIDE_BUY
        position_side = POSITION_LONG if hold_side == "long" else POSITION_SHORT

        # Cancel existing TP/SL and trailing stops to prevent orphan duplicates
        await self._cancel_existing_tpsl(symbol)

        order_params = {
            "symbol": symbol,
            "side": close_side,
            "positionSide": position_side,
            "type": ORDER_TYPE_TRAILING_STOP_MARKET,
            "quantity": str(self._round_quantity(size)),
            "activationPrice": str(trigger_price),
            "priceRate": str(round(callback_ratio / 100, 4)),
        }

        result = await self._request("POST", ENDPOINTS["place_order"], data=order_params)
        order_data = result.get("order", result) if isinstance(result, dict) else result
        order_id = ""
        if isinstance(order_data, dict):
            order_id = str(order_data.get("orderId", ""))

        logger.info(
            "Trailing stop placed on BingX: %s %s size=%s callback=%.2f%% activation=$%.2f (orderId=%s)",
            symbol, hold_side, size, callback_ratio, trigger_price, order_id,
        )
        return {"orderId": order_id}

    _TPSL_ORDER_TYPES = frozenset({
        "TAKE_PROFIT_MARKET", "STOP_MARKET", "TAKE_PROFIT", "STOP",
        "TRAILING_STOP_MARKET",
    })

    async def cancel_position_tpsl(
        self,
        symbol: str,
        side: str = "long",
    ) -> bool:
        """Cancel all conditional TP/SL orders for a position on BingX.

        Queries open orders, filters for TAKE_PROFIT_MARKET / STOP_MARKET
        matching the symbol and position side, then cancels each one.
        Best-effort: partial cancel failures are logged but don't fail the operation.
        """
        position_side = POSITION_LONG if side == "long" else POSITION_SHORT

        try:
            data = await self._request("GET", ENDPOINTS["open_orders"], params={"symbol": symbol})
        except Exception as e:
            logger.warning("Failed to query open orders for %s: %s", symbol, e)
            return False

        orders = data.get("orders", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

        to_cancel = [
            o for o in orders
            if isinstance(o, dict)
            and o.get("type") in self._TPSL_ORDER_TYPES
            and o.get("symbol") == symbol
            and o.get("positionSide") == position_side
        ]

        if not to_cancel:
            logger.debug("No conditional TP/SL orders to cancel for %s %s", symbol, side)
            return True

        for order in to_cancel:
            oid = str(order.get("orderId", ""))
            try:
                await self._request("DELETE", ENDPOINTS["cancel_order"], params={
                    "symbol": symbol,
                    "orderId": oid,
                })
                logger.info("Cancelled BingX TP/SL order %s for %s", oid, symbol)
            except Exception as e:
                logger.warning("Failed to cancel BingX order %s for %s: %s", oid, symbol, e)

        return True

    async def _cancel_existing_tpsl(self, symbol: str) -> None:
        """Cancel existing TP/SL conditional orders for a symbol before placing new ones."""
        try:
            data = await self._request("GET", ENDPOINTS["open_orders"], params={"symbol": symbol})
            orders = data if isinstance(data, list) else data.get("orders", []) if isinstance(data, dict) else []
            if not orders:
                return
            logger.debug("BingX open_orders for %s: %d orders found", symbol, len(orders))
            for order in orders:
                order_type = str(order.get("type") or order.get("orderType", "")).upper()
                if order_type in self._TPSL_ORDER_TYPES:
                    oid = str(order.get("orderId", ""))
                    if oid:
                        try:
                            await self.cancel_order(symbol, oid)
                            logger.info("BingX: cancelled old %s order %s for %s", order_type, oid, symbol)
                        except Exception as e:
                            logger.warning("BingX: failed to cancel old %s order %s: %s", order_type, oid, e)
        except Exception as e:
            logger.warning("BingX: failed to query open orders for %s: %s", symbol, e)

    async def set_position_tpsl(
        self,
        symbol: str,
        position_id: str = "",
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        side: str = "long",
        size: Optional[float] = None,
    ) -> Optional[str]:
        """Set TP/SL on an existing position via STOP_MARKET/TAKE_PROFIT_MARKET orders.

        BingX doesn't have a dedicated TP/SL endpoint. Instead, we place
        reduce-only conditional orders on the existing position.
        """
        if take_profit is None and stop_loss is None:
            return None

        # Get position size if not provided
        if size is None:
            pos = await self.get_position(symbol)
            if not pos:
                return None
            size = pos.size
            side = pos.side

        # Cancel existing TP/SL orders to prevent orphan duplicates
        await self._cancel_existing_tpsl(symbol)

        # Closing side is opposite of position
        close_side = SIDE_SELL if side == "long" else SIDE_BUY
        position_side = POSITION_LONG if side == "long" else POSITION_SHORT
        order_ids = []

        if take_profit is not None:
            try:
                result = await self._request("POST", ENDPOINTS["place_order"], data={
                    "symbol": symbol,
                    "side": close_side,
                    "positionSide": position_side,
                    "type": "TAKE_PROFIT_MARKET",
                    "quantity": str(self._round_quantity(size)),
                    "stopPrice": str(take_profit),
                    "workingType": "MARK_PRICE",
                })
                oid = result.get("order", result).get("orderId", "") if isinstance(result, dict) else ""
                order_ids.append(str(oid))
                logger.info("BingX TP set for %s: $%.2f", symbol, take_profit)
            except Exception as e:
                logger.warning("Failed to set TP for %s: %s", symbol, e)

        if stop_loss is not None:
            try:
                result = await self._request("POST", ENDPOINTS["place_order"], data={
                    "symbol": symbol,
                    "side": close_side,
                    "positionSide": position_side,
                    "type": "STOP_MARKET",
                    "quantity": str(self._round_quantity(size)),
                    "stopPrice": str(stop_loss),
                    "workingType": "MARK_PRICE",
                })
                oid = result.get("order", result).get("orderId", "") if isinstance(result, dict) else ""
                order_ids.append(str(oid))
                logger.info("BingX SL set for %s: $%.2f", symbol, stop_loss)
            except Exception as e:
                logger.warning("Failed to set SL for %s: %s", symbol, e)

        return ",".join(order_ids) if order_ids else None

    async def get_funding_fees(
        self, symbol: str, start_time_ms: int, end_time_ms: int
    ) -> float:
        """
        Get total funding fees paid for a symbol between two timestamps.

        BingX endpoint: GET /openApi/swap/v2/user/income?incomeType=FUNDING_FEE
        Funding fees are charged periodically while holding a position.

        Returns net funding cost (positive = paid, negative = received). Returns 0.0 on error.
        """
        try:
            params = {
                "symbol": symbol,
                "incomeType": "FUNDING_FEE",
                "startTime": str(start_time_ms),
                "endTime": str(end_time_ms),
                "limit": "100",
            }
            data = await self._request("GET", ENDPOINTS["account_income"], params=params)
            income_list = data if isinstance(data, list) else []
            if isinstance(data, dict):
                income_list = data.get("incomeList", data.get("data", []))

            if not isinstance(income_list, list):
                return 0.0

            total_funding = 0.0
            for item in income_list:
                amount_str = item.get("income", "0") or item.get("amount", "0")
                if amount_str:
                    total_funding += float(amount_str)

            return round(total_funding, 6)
        except Exception as e:
            logger.warning(f"Failed to get funding fees for {symbol}: {e}")
            return 0.0

    # ==================== Internal Helpers ====================

    def _parse_positions_response(self, data: Any) -> list:
        """Parse the positions API response into a list of position dicts."""
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # BingX may wrap positions in a "data" or "positions" key
            if "positions" in data:
                return data["positions"] if isinstance(data["positions"], list) else []
            return [data] if data else []
        return []

    # ── Affiliate ──────────────────────────────────────────────────

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a UID was referred by us via BingX Agent API.

        Uses GET /openApi/agent/v1/account/inviteRelationCheck with uid param
        to verify the invitation relationship exists.
        """
        try:
            result = await self._request(
                "GET",
                "/openApi/agent/v1/account/inviteRelationCheck",
                params={"uid": str(uid)},
            )
            # Endpoint returns relationship data with uid field if the UID is an invitee.
            # API error responses or empty data mean no relationship.
            if isinstance(result, dict):
                # Must contain actual user data (uid field), not just a status wrapper
                if result.get("uid") or result.get("inviteUid"):
                    return True
            if isinstance(result, list) and len(result) > 0:
                return True
            return False
        except Exception as e:
            logger.warning(f"Affiliate UID check failed for {uid}: {e}")
            return False

    @staticmethod
    def _round_quantity(size: float) -> float:
        """Round quantity to avoid float precision artifacts.

        BingX requires quantities that match contract step sizes. We use 4
        decimal places as a safe default for most perpetual contracts.
        """
        return round(size, 4)

    def _normalize_position(self, pos: Dict[str, Any]) -> Optional[Position]:
        """Convert a BingX position dict to a normalized Position object."""
        try:
            position_amt = abs(float(pos.get("positionAmt", 0)))
            if position_amt <= 0:
                return None

            # Determine side from positionSide
            pos_side = pos.get("positionSide", "").upper()
            if pos_side == "LONG":
                side = "long"
            elif pos_side == "SHORT":
                side = "short"
            else:
                # Fallback: check positionAmt sign (positive=long, negative=short)
                raw_amt = float(pos.get("positionAmt", 0))
                side = "long" if raw_amt > 0 else "short"

            return Position(
                symbol=pos.get("symbol", ""),
                side=side,
                size=position_amt,
                entry_price=float(pos.get("avgPrice", 0) or pos.get("entryPrice", 0)),
                current_price=float(pos.get("markPrice", 0)),
                unrealized_pnl=float(pos.get("unrealizedProfit", 0)),
                leverage=int(float(pos.get("leverage", 1))),
                exchange="bingx",
                margin=float(pos.get("initialMargin", 0) or pos.get("positionInitialMargin", 0)),
                liquidation_price=_safe_float(pos.get("liquidationPrice")),
                take_profit=_safe_float(pos.get("takeProfit")),
                stop_loss=_safe_float(pos.get("stopLoss")),
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to normalize BingX position: {e}")
            return None


# ==================== Module-level helpers ====================

def _safe_float(value: Any) -> Optional[float]:
    """Safely convert a value to float, returning None on failure or zero."""
    if value is None:
        return None
    try:
        result = float(value)
        return result if result != 0 else None
    except (ValueError, TypeError):
        return None
