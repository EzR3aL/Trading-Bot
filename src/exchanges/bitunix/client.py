"""
Bitunix Exchange Client implementing the ExchangeClient ABC.

Bitunix Futures REST API (v1) with double-SHA256 signature authentication.
API docs: https://openapidoc.bitunix.com/
"""

import asyncio
import hashlib
import json
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from src.exceptions import ExchangeError
from src.exchanges.base import ExchangeClient, HTTPExchangeClientMixin
from src.exchanges.bitunix.constants import (
    BASE_URL,
    ENDPOINTS,
    SUCCESS_CODE,
    TESTNET_URL,
)
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.utils.circuit_breaker import circuit_registry, with_retry
from src.utils.logger import get_logger

logger = get_logger(__name__)

_bitunix_breaker = circuit_registry.get(
    "bitunix_api", fail_threshold=5, reset_timeout=60
)


class BitunixClientError(ExchangeError):
    """Custom exception for Bitunix API errors."""

    def __init__(self, message: str, original_error: Exception = None):
        super().__init__("bitunix", message, original_error)


class BitunixClient(HTTPExchangeClientMixin, ExchangeClient):
    """
    Async client for Bitunix Futures API implementing ExchangeClient ABC.

    Authentication uses a two-step SHA256 signature:
        digest = SHA256(nonce + timestamp + apiKey + queryParams + body)
        sign   = SHA256(digest + secretKey)

    Uses HTTPExchangeClientMixin for session management and circuit breaker.
    Overrides _raw_request because Bitunix uses a different signing scheme
    (nonce-based double-SHA256 with sorted params/body).

    Demo mode: Bitunix does not have a dedicated demo domain or header toggle.
    Users must supply separate demo API keys; this flag is tracked for metadata
    purposes and future support if Bitunix introduces a testnet.
    """

    _client_error_class = BitunixClientError

    @property
    def _circuit_breaker(self):
        return _bitunix_breaker

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
        self.base_url = TESTNET_URL if testnet else BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None
        mode_str = "DEMO" if demo_mode else "LIVE"
        logger.info(f"BitunixClient initialized in {mode_str} mode")

    # ==================== Properties ====================

    @property
    def exchange_name(self) -> str:
        return "bitunix"

    @property
    def supports_demo(self) -> bool:
        # Bitunix supports demo via separate API keys, not a protocol flag
        return True

    # ==================== Auth / Signature ====================

    @staticmethod
    def _generate_nonce() -> str:
        """Generate a random 32-character hex nonce."""
        return secrets.token_hex(16)

    def _generate_signature(
        self,
        nonce: str,
        timestamp: str,
        query_string: str = "",
        body: str = "",
    ) -> str:
        """
        Two-step SHA256 signature per Bitunix spec.

        Step 1: digest = SHA256(nonce + timestamp + apiKey + queryString + body)
        Step 2: sign   = SHA256(digest + secretKey)

        Returns hex-encoded signature.
        """
        # Build digest input: nonce + timestamp + api_key + sorted query params + body
        message = f"{nonce}{timestamp}{self.api_key}{query_string}{body}"
        digest = hashlib.sha256(message.encode("utf-8")).hexdigest()

        # Sign with secret key
        sign_input = digest + self.api_secret
        signature = hashlib.sha256(sign_input.encode("utf-8")).hexdigest()
        return signature

    def _get_headers(
        self,
        method: str,
        query_string: str = "",
        body: str = "",
    ) -> Dict[str, str]:
        """Build authenticated headers for a request."""
        timestamp = str(int(time.time() * 1000))
        nonce = self._generate_nonce()
        signature = self._generate_signature(nonce, timestamp, query_string, body)
        headers = {
            "api-key": self.api_key,
            "sign": signature,
            "nonce": nonce,
            "timestamp": timestamp,
            "Content-Type": "application/json",
            "language": "en-US",
        }
        return headers

    # ==================== HTTP ====================
    # _request is inherited from HTTPExchangeClientMixin (circuit breaker wrapper).
    # _raw_request is overridden because Bitunix uses a different signing scheme.

    @with_retry(
        max_attempts=3,
        min_wait=1.0,
        max_wait=10.0,
        retry_on=(aiohttp.ClientError, asyncio.TimeoutError),
    )
    async def _raw_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth: bool = True,
    ) -> Any:
        """
        Perform the actual HTTP request against the Bitunix API.

        GET  -> params sent as query string
        POST -> data sent as JSON body
        """
        await self._ensure_session()
        url = f"{self.base_url}{endpoint}"

        # Build query string (sorted alphabetically for signature consistency)
        query_string = ""
        if params:
            sorted_params = sorted(params.items())
            query_string = urlencode(sorted_params)
            url = f"{url}?{query_string}"

        # Build body (compact JSON, keys sorted for deterministic signing)
        body = ""
        if data:
            body = json.dumps(data, separators=(",", ":"), sort_keys=True)

        if auth:
            headers = self._get_headers(method, query_string, body)
        else:
            headers = {"Content-Type": "application/json"}

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
                        response.request_info,
                        response.history,
                        status=429,
                        message="Rate limited",
                    )

                if response.status != 200:
                    raise BitunixClientError(
                        f"HTTP {response.status}: {result.get('msg', 'Unknown error')}"
                    )

                # Bitunix uses code=0 for success
                response_code = result.get("code")
                if response_code != SUCCESS_CODE:
                    raise BitunixClientError(
                        f"Bitunix Error (code={response_code}): "
                        f"{result.get('msg', 'Unknown error')}"
                    )

                return result.get("data", result)

        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise

    # ==================== ABC Implementation ====================

    async def get_account_balance(self) -> Balance:
        """Get account balance for USDT margin coin."""
        params = {"marginCoin": "USDT"}
        data = await self._request("GET", ENDPOINTS["account"], params=params)

        # Response is a list; take first item
        if isinstance(data, list):
            data = data[0] if data else {}

        available = float(data.get("available", 0))
        margin = float(data.get("margin", 0))
        frozen = float(data.get("frozen", 0))
        cross_upnl = float(data.get("crossUnrealizedPNL", 0))
        iso_upnl = float(data.get("isolationUnrealizedPNL", 0))
        bonus = float(data.get("bonus", 0))
        total_unrealized = cross_upnl + iso_upnl
        # Total equity = available + margin + frozen + unrealized PnL + bonus
        total = available + margin + frozen + total_unrealized + bonus

        return Balance(
            total=total,
            available=available,
            unrealized_pnl=total_unrealized,
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
        client_order_id: Optional[str] = None,
    ) -> Order:
        """
        Place a market order with optional TP/SL.

        Args:
            symbol: Trading pair (e.g. BTCUSDT)
            side: "long" or "short"
            size: Order quantity in base coin
            leverage: Leverage multiplier
            take_profit: Optional take profit price
            stop_loss: Optional stop loss price
            client_order_id: Optional idempotency key forwarded as ``clientId``.
        """
        # Set leverage first
        await self.set_leverage(symbol, leverage)

        # Map normalized side to Bitunix API side
        order_side = "BUY" if side == "long" else "SELL"

        order_data: Dict[str, Any] = {
            "symbol": symbol,
            "qty": str(round(size, 4)),
            "side": order_side,
            "tradeSide": "OPEN",
            "orderType": "MARKET",
        }

        # Attach TP/SL directly to the order if provided
        if take_profit is not None:
            order_data["tpPrice"] = str(take_profit)
            order_data["tpStopType"] = "LAST_PRICE"
            order_data["tpOrderType"] = "MARKET"

        if stop_loss is not None:
            order_data["slPrice"] = str(stop_loss)
            order_data["slStopType"] = "LAST_PRICE"
            order_data["slOrderType"] = "MARKET"

        # Idempotency: Bitunix exposes this as ``clientId`` on the place-order
        # payload. Docs cap the length at 32 chars (#ARCH-C2).
        if client_order_id:
            order_data["clientId"] = str(client_order_id)[:32]

        result = await self._request("POST", ENDPOINTS["place_order"], data=order_data)

        order_id = ""
        if isinstance(result, dict):
            order_id = result.get("orderId", "")

        return Order(
            order_id=str(order_id),
            symbol=symbol,
            side=side,
            size=size,
            price=0.0,  # Market order; fill price obtained via get_fill_price()
            status="filled",
            exchange="bitunix",
            leverage=leverage,
            take_profit=take_profit,
            stop_loss=stop_loss,
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an open order by ID."""
        data = {
            "symbol": symbol,
            "orderList": [{"orderId": order_id}],
        }
        try:
            result = await self._request(
                "POST", ENDPOINTS["cancel_orders"], data=data
            )
            # Check if the order appears in the success list
            if isinstance(result, dict):
                success_list = result.get("successList", [])
                return len(success_list) > 0
            return True
        except BitunixClientError:
            return False

    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        """Close an open position for a symbol."""
        pos = await self.get_position(symbol)
        if not pos:
            return None

        # To close: sell if long, buy if short
        close_side = "SELL" if pos.side == "long" else "BUY"

        data: Dict[str, Any] = {
            "symbol": symbol,
            "qty": str(round(pos.size, 4)),
            "side": close_side,
            "tradeSide": "CLOSE",
            "orderType": "MARKET",
        }

        result = await self._request("POST", ENDPOINTS["place_order"], data=data)
        order_id = ""
        if isinstance(result, dict):
            order_id = result.get("orderId", "")

        if not order_id:
            logger.warning(
                "Bitunix close_position for %s returned empty orderId — "
                "close may not have executed. Response: %s",
                symbol, result,
            )

        return Order(
            order_id=str(order_id),
            symbol=symbol,
            side=pos.side,
            size=pos.size,
            price=0.0,
            status="filled",
            exchange="bitunix",
        )

    async def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol."""
        params = {"symbol": symbol}
        data = await self._request(
            "GET", ENDPOINTS["get_pending_positions"], params=params
        )

        positions = data if isinstance(data, list) else []
        for pos in positions:
            qty = float(pos.get("qty", 0))
            if qty > 0:
                raw_side = pos.get("side", "LONG").upper()
                side = "long" if raw_side == "LONG" else "short"
                return Position(
                    symbol=pos.get("symbol", symbol),
                    side=side,
                    size=qty,
                    entry_price=float(pos.get("avgOpenPrice", 0)),
                    current_price=float(pos.get("markPrice", 0) or 0),
                    unrealized_pnl=float(pos.get("unrealizedPNL", 0)),
                    leverage=int(pos.get("leverage", 1)),
                    exchange="bitunix",
                    margin=float(pos.get("margin", 0)),
                    liquidation_price=float(pos.get("liqPrice", 0) or 0),
                    position_id=pos.get("positionId"),
                )
        return None

    async def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        data = await self._request("GET", ENDPOINTS["get_pending_positions"])

        positions: List[Position] = []
        items = data if isinstance(data, list) else []
        for pos in items:
            qty = float(pos.get("qty", 0))
            if qty > 0:
                raw_side = pos.get("side", "LONG").upper()
                side = "long" if raw_side == "LONG" else "short"
                positions.append(
                    Position(
                        symbol=pos.get("symbol", ""),
                        side=side,
                        size=qty,
                        entry_price=float(pos.get("avgOpenPrice", 0)),
                        current_price=float(pos.get("markPrice", 0) or 0),
                        unrealized_pnl=float(pos.get("unrealizedPNL", 0)),
                        leverage=int(pos.get("leverage", 1)),
                        exchange="bitunix",
                        margin=float(pos.get("margin", 0)),
                        liquidation_price=float(pos.get("liqPrice", 0) or 0),
                        position_id=pos.get("positionId"),
                    )
                )
        return positions

    async def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        """Set leverage for a trading pair."""
        data = {
            "marginCoin": "USDT",
            "symbol": symbol,
            "leverage": leverage,
        }
        try:
            await self._request("POST", ENDPOINTS["change_leverage"], data=data)
            return True
        except BitunixClientError as e:
            # May fail if leverage is already set to same value
            logger.debug(f"Set leverage for {symbol} to {leverage}x: {e}")
            return False

    async def get_ticker(self, symbol: str) -> Ticker:
        """Get current ticker data for a symbol."""
        params = {"symbols": symbol}
        data = await self._request(
            "GET", ENDPOINTS["tickers"], params=params, auth=False
        )

        if isinstance(data, list):
            data = data[0] if data else {}

        last_price = float(data.get("lastPrice", 0) or data.get("last", 0))

        # Bitunix tickers do not include bid/ask; use last price as fallback
        return Ticker(
            symbol=symbol,
            last_price=last_price,
            bid=last_price,  # Not provided by Bitunix ticker endpoint
            ask=last_price,  # Not provided by Bitunix ticker endpoint
            volume_24h=float(data.get("baseVol", 0) or data.get("quoteVol", 0)),
            high_24h=float(data.get("high", 0)) if data.get("high") else None,
            low_24h=float(data.get("low", 0)) if data.get("low") else None,
            change_24h_percent=_calc_change_pct(data),
        )

    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        """Get current funding rate info for a symbol."""
        params = {"symbol": symbol}
        data = await self._request(
            "GET", ENDPOINTS["funding_rate"], params=params, auth=False
        )

        if isinstance(data, list):
            data = data[0] if data else {}

        next_time_ms = data.get("nextFundingTime")
        next_funding_time = None
        if next_time_ms:
            try:
                next_funding_time = datetime.utcfromtimestamp(int(next_time_ms) / 1000)
            except (ValueError, TypeError, OSError):
                pass

        return FundingRateInfo(
            symbol=symbol,
            current_rate=float(data.get("fundingRate", 0)),
            next_funding_time=next_funding_time,
        )

    # ==================== Fee / Fill Tracking ====================

    async def get_order_fees(self, symbol: str, order_id: str) -> float:
        """
        Get total fees paid for a single order via order detail API.

        Returns absolute fee value (always positive). Returns 0.0 on error.
        """
        try:
            params = {"orderId": order_id}
            detail = await self._request(
                "GET", ENDPOINTS["get_order_detail"], params=params
            )
            if not detail:
                return 0.0

            fee_str = detail.get("fee")
            if fee_str:
                return abs(float(fee_str))

            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get order fees for {order_id}: {e}")
            return 0.0

    async def get_trade_total_fees(
        self,
        symbol: str,
        entry_order_id: str,
        close_order_id: Optional[str] = None,
    ) -> float:
        """
        Get total fees (entry + exit) for a complete trade.

        Uses entry_order_id for entry fees directly.
        If close_order_id is provided, uses it for exit fees.
        Otherwise, searches order history for the most recent close order.
        """
        total_fees = 0.0

        # 1. Entry fees
        if entry_order_id:
            total_fees += await self.get_order_fees(symbol, entry_order_id)

        # 2. Exit fees
        if close_order_id:
            total_fees += await self.get_order_fees(symbol, close_order_id)
        else:
            # Search history for close orders on this symbol
            try:
                params = {"symbol": symbol, "limit": "20"}
                data = await self._request(
                    "GET", ENDPOINTS["get_history_orders"], params=params
                )
                orders = (
                    data.get("orderList", data) if isinstance(data, dict) else data
                )
                if isinstance(orders, list):
                    for order in orders:
                        trade_side = order.get("tradeSide", "")
                        status = order.get("status", "")
                        # Match close orders
                        if trade_side == "CLOSE" and status == "FILLED":
                            fee_str = order.get("fee")
                            if fee_str:
                                total_fees += abs(float(fee_str))
                            break  # Most recent close order
            except Exception as e:
                logger.warning(
                    f"Failed to get close order fees from history for {symbol}: {e}"
                )

        return round(total_fees, 6)

    async def get_fill_price(
        self,
        symbol: str,
        order_id: str,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ) -> Optional[float]:
        """
        Get actual fill price for a completed order with retry.

        Bitunix order detail does not include an explicit avgFillPrice field.
        We derive it from the trade history matching the order.
        """
        for attempt in range(max_retries):
            try:
                # First try order detail for price info
                params = {"orderId": order_id}
                detail = await self._request(
                    "GET", ENDPOINTS["get_order_detail"], params=params
                )
                if detail:
                    # For limit orders, price is the fill price
                    # For market orders, check trade history
                    price_str = detail.get("price")
                    if price_str and float(price_str) > 0:
                        return float(price_str)

                # Fallback: check trade history for this order
                trade_params = {"orderId": order_id, "limit": "1"}
                trades = await self._request(
                    "GET", ENDPOINTS["get_history_trades"], params=trade_params
                )
                trade_list = (
                    trades.get("tradeList", trades)
                    if isinstance(trades, dict)
                    else trades
                )
                if isinstance(trade_list, list) and trade_list:
                    fill_price = trade_list[0].get("price")
                    if fill_price and float(fill_price) > 0:
                        return float(fill_price)

            except Exception as e:
                logger.warning(
                    f"Error getting fill price (attempt {attempt + 1}): {e}"
                )
            await asyncio.sleep(retry_delay * (2**attempt))
        return None

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        """Get fill price of the most recent close order from Bitunix history."""
        try:
            params = {"symbol": symbol, "limit": "20"}
            data = await self._request("GET", ENDPOINTS["get_history_orders"], params=params)
            orders = data.get("orderList", data) if isinstance(data, dict) else data
            if isinstance(orders, list):
                for order in orders:
                    trade_side = order.get("tradeSide", "")
                    status = order.get("status", "")
                    if trade_side == "CLOSE" and status == "FILLED":
                        price = order.get("avgPrice") or order.get("filledPrice") or order.get("price")
                        if price and float(price) > 0:
                            return float(price)
        except Exception as e:
            logger.warning(f"Failed to get close fill price for {symbol}: {e}")
        return None

    async def get_funding_fees(
        self, symbol: str, start_time_ms: int, end_time_ms: int
    ) -> float:
        """
        Get total funding fees for a symbol between two timestamps.

        Uses the pending positions endpoint which tracks cumulative funding
        during the position's lifetime. Since Bitunix does not expose a
        granular account-bill / funding-history API, we approximate from
        the position's 'funding' field for active positions, or fall back
        to trade history for closed positions.

        Returns total absolute funding paid (always positive). Returns 0.0 on error.
        """
        try:
            # Try active positions first (they have a cumulative funding field)
            params = {"symbol": symbol}
            data = await self._request(
                "GET", ENDPOINTS["get_pending_positions"], params=params
            )
            positions = data if isinstance(data, list) else []
            for pos in positions:
                funding_str = pos.get("funding", "0")
                if funding_str:
                    return abs(float(funding_str))

            # Fallback: check history positions for closed ones in time range
            history_params = {
                "symbol": symbol,
                "startTime": str(start_time_ms),
                "endTime": str(end_time_ms),
                "limit": "50",
            }
            history_data = await self._request(
                "GET", ENDPOINTS["get_history_positions"], params=history_params
            )
            history_positions = (
                history_data if isinstance(history_data, list) else []
            )
            total_funding = 0.0
            for hp in history_positions:
                funding_str = hp.get("funding", "0")
                if funding_str:
                    total_funding += abs(float(funding_str))
            return round(total_funding, 6)

        except Exception as e:
            logger.warning(f"Failed to get funding fees for {symbol}: {e}")
            return 0.0

    # ==================== TP/SL Helpers ====================

    async def set_position_tpsl(
        self,
        symbol: str,
        position_id: Optional[str] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        side: str = "long",
        size: float = 0,
        **kwargs,
    ) -> Optional[str]:
        """Set position-level TP/SL via /tpsl/position/place_order.

        Position-level TP/SL automatically adjusts to the current position
        size at trigger time (closes at market price). Only 1 per position.
        Falls back to regular /tpsl/place_order if position endpoint fails.
        """
        if take_profit is None and stop_loss is None:
            return None

        # Auto-fetch position_id if not provided
        if not position_id:
            try:
                positions = await self.get_open_positions()
                for pos in positions:
                    if pos.symbol == symbol and pos.side == side:
                        position_id = getattr(pos, 'position_id', None) or f"{symbol}_{side}"
                        break
            except Exception:
                position_id = f"{symbol}_{side}"

        tpsl_data: Dict[str, Any] = {
            "symbol": symbol,
            "positionId": position_id or f"{symbol}_{side}",
        }
        if take_profit is not None:
            tpsl_data["tpPrice"] = str(take_profit)
            tpsl_data["tpStopType"] = "MARK_PRICE"
        if stop_loss is not None:
            tpsl_data["slPrice"] = str(stop_loss)
            tpsl_data["slStopType"] = "MARK_PRICE"

        # Try position-level endpoint first (auto-adjusts to position size)
        try:
            result = await self._request(
                "POST", ENDPOINTS["tpsl_position_place"], data=tpsl_data
            )
            order_id = result.get("orderId", "") if isinstance(result, dict) else ""
            logger.info(
                "Position TP/SL set for %s positionId=%s: TP=%s, SL=%s (orderId=%s)",
                symbol, position_id, take_profit, stop_loss, order_id,
            )
            return order_id or None
        except Exception as e:
            logger.info("Position TP/SL endpoint failed for %s, trying regular: %s", symbol, e)

        # Fallback to regular TP/SL endpoint (fixed quantity)
        tpsl_data_regular: Dict[str, Any] = {
            "symbol": symbol,
            "positionId": position_id,
        }
        if take_profit is not None:
            tpsl_data_regular["tpPrice"] = str(take_profit)
            tpsl_data_regular["tpStopType"] = "LAST_PRICE"
            tpsl_data_regular["tpOrderType"] = "MARKET"
        if stop_loss is not None:
            tpsl_data_regular["slPrice"] = str(stop_loss)
            tpsl_data_regular["slStopType"] = "LAST_PRICE"
            tpsl_data_regular["slOrderType"] = "MARKET"

        try:
            result = await self._request(
                "POST", ENDPOINTS["tpsl_place_order"], data=tpsl_data_regular
            )
            order_id = result.get("orderId", "") if isinstance(result, dict) else ""
            logger.info(
                "Regular TP/SL set for %s positionId=%s: TP=%s, SL=%s (orderId=%s)",
                symbol, position_id, take_profit, stop_loss, order_id,
            )
            return order_id or None
        except Exception as e:
            logger.warning("Failed to set TP/SL for %s: %s", symbol, e)
            return None

    async def modify_position_tpsl(
        self,
        symbol: str,
        position_id: str,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
    ) -> Optional[str]:
        """Modify position-level TP/SL prices on an existing position."""
        if take_profit is None and stop_loss is None:
            return None

        data: Dict[str, Any] = {
            "symbol": symbol,
            "positionId": position_id,
        }
        if take_profit is not None:
            data["tpPrice"] = str(take_profit)
            data["tpStopType"] = "MARK_PRICE"
        if stop_loss is not None:
            data["slPrice"] = str(stop_loss)
            data["slStopType"] = "MARK_PRICE"

        try:
            result = await self._request(
                "POST", ENDPOINTS["tpsl_position_modify"], data=data
            )
            order_id = result.get("orderId", "") if isinstance(result, dict) else ""
            logger.info(
                "Position TP/SL modified for %s: TP=%s, SL=%s",
                symbol, take_profit, stop_loss,
            )
            return order_id or None
        except Exception as e:
            logger.warning("Failed to modify position TP/SL for %s: %s", symbol, e)
            return None

    async def cancel_position_tpsl(
        self,
        symbol: str,
        side: str = "long",
    ) -> bool:
        """Cancel all pending TP/SL orders for a position on Bitunix.

        Queries /api/v1/futures/tpsl/get_pending_orders, filters by symbol
        and position side, then cancels each via /api/v1/futures/tpsl/cancel_order.
        Best-effort: partial failures are logged but don't fail the operation.
        """
        position_side = "LONG" if side == "long" else "SHORT"

        try:
            data = await self._request(
                "GET", ENDPOINTS["tpsl_get_pending_orders"], params={
                    "symbol": symbol,
                }
            )
        except Exception as e:
            logger.warning(
                "Failed to query pending TP/SL orders for %s: %s", symbol, e
            )
            return False

        orders = data if isinstance(data, list) else (
            data.get("data", data.get("orders", []))
            if isinstance(data, dict) else []
        )

        to_cancel = [
            o for o in orders
            if isinstance(o, dict)
            and o.get("positionSide", "").upper() == position_side
        ]

        if not to_cancel:
            logger.debug(
                "No pending TP/SL orders to cancel for %s %s on Bitunix",
                symbol, side,
            )
            return True

        for order in to_cancel:
            oid = str(order.get("orderId", ""))
            try:
                await self._request(
                    "POST", ENDPOINTS["tpsl_cancel_order"], data={
                        "symbol": symbol,
                        "orderId": oid,
                    }
                )
                logger.info(
                    "Cancelled Bitunix TP/SL order %s for %s", oid, symbol
                )
            except Exception as e:
                logger.warning(
                    "Failed to cancel Bitunix TP/SL order %s for %s: %s",
                    oid, symbol, e,
                )

        return True

    async def cancel_tp_only(self, symbol: str, side: str = "long") -> bool:
        """Not supported on Bitunix — TP and SL share one pending order row.

        Epic #188 follow-up: the dashboard must be able to clear only TP
        without collateral-cancelling the SL leg. On Bitunix this is
        genuinely impossible via the public API:

        - ``/api/v1/futures/tpsl/place_order`` accepts ``tpPrice`` and
          ``slPrice`` in the same call and stores the pair as a single
          order row in ``/tpsl/get_pending_orders`` (verified via Bitunix
          OpenAPI docs, 2026-04-18).
        - ``/api/v1/futures/tpsl/cancel_order`` takes only ``orderId`` —
          there is no field to target just the TP or SL leg.
        - ``/api/v1/futures/tpsl/modify_order`` requires "at least one of
          tpPrice or slPrice"; the semantic of omitting a field (clear vs
          keep) is undocumented and testing on live would risk clearing
          the SL leg we want to preserve.

        Raising ``NotImplementedError`` surfaces as :class:`CancelFailed`
        in :class:`RiskStateManager`, marking the leg as ``cancel_failed``
        in the DB and returning a clear error to the UI. That is strictly
        safer than guessing at partial-modify semantics that could silently
        drop the user's stop-loss.
        """
        raise NotImplementedError(
            "Bitunix stores TP+SL as a single combined order; its cancel API "
            "has no leg selector. Cancelling TP alone is not possible without "
            "risking collateral cancel of SL."
        )

    async def cancel_sl_only(self, symbol: str, side: str = "long") -> bool:
        """Not supported on Bitunix — see :meth:`cancel_tp_only` for rationale.

        Same limitation applies symmetrically: cancelling only SL while
        preserving TP cannot be expressed in Bitunix's pending-TP/SL API.
        """
        raise NotImplementedError(
            "Bitunix stores TP+SL as a single combined order; its cancel API "
            "has no leg selector. Cancelling SL alone is not possible without "
            "risking collateral cancel of TP."
        )

    # ── Affiliate ──────────────────────────────────────────────────

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Bitunix has no public affiliate/referral API.

        UID verification must be done manually by an admin.
        Always returns False — admin can approve via the admin panel.
        """
        logger.info(
            "Bitunix has no affiliate API. UID %s requires manual admin verification.",
            uid,
        )
        return False


# ==================== Module-level helpers ====================


def _calc_change_pct(data: Dict[str, Any]) -> Optional[float]:
    """Calculate 24h change percent from open and last price."""
    try:
        open_price = float(data.get("open", 0))
        last_price = float(data.get("lastPrice", 0) or data.get("last", 0))
        if open_price > 0 and last_price > 0:
            return round(((last_price - open_price) / open_price) * 100, 4)
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    return None
