"""
Bitget Exchange Client implementing the ExchangeClient ABC.

Refactored from src/api/bitget_client.py to use normalized types.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import aiohttp

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


class BitgetClientError(Exception):
    """Custom exception for Bitget API errors."""
    pass


class BitgetExchangeClient(ExchangeClient):
    """
    Async client for Bitget Futures API implementing ExchangeClient ABC.

    Supports demo trading via X-SIMULATED-TRADING header.
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
            headers["X-SIMULATED-TRADING"] = "1"
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

        return Balance(
            total=float(data.get("accountEquity", 0) or data.get("usdtEquity", 0)),
            available=float(data.get("available", 0) or data.get("crossedMaxAvailable", 0)),
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
    ) -> Order:
        # Set leverage first
        await self.set_leverage(symbol, leverage)

        order_side = "buy" if side == "long" else "sell"
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "side": order_side,
            "tradeSide": "open",
            "orderType": "market",
            "size": str(size),
        }
        if take_profit is not None:
            data["presetStopSurplusPrice"] = f"{take_profit:.1f}"
        if stop_loss is not None:
            data["presetStopLossPrice"] = f"{stop_loss:.1f}"

        result = await self._request("POST", ENDPOINTS["place_order"], data=data)

        order_id = result.get("orderId", result.get("data", {}).get("orderId", ""))

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
        )

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

    async def close_position(self, symbol: str, side: str) -> Optional[Order]:
        order_side = "sell" if side == "long" else "buy"

        # Get position size
        pos = await self.get_position(symbol)
        if not pos:
            return None

        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": "crossed",
            "marginCoin": "USDT",
            "side": order_side,
            "tradeSide": "close",
            "orderType": "market",
            "size": str(pos.size),
        }
        result = await self._request("POST", ENDPOINTS["place_order"], data=data)
        order_id = result.get("orderId", "")

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

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        for hold_side in ("long", "short"):
            data = {
                "symbol": symbol,
                "productType": PRODUCT_TYPE_USDT,
                "marginCoin": "USDT",
                "leverage": str(leverage),
                "holdSide": hold_side,
            }
            try:
                await self._request("POST", ENDPOINTS["set_leverage"], data=data)
            except BitgetClientError:
                pass  # May fail if already set
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

    # ==================== Additional Bitget-specific methods ====================

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
    ) -> Dict[str, Any]:
        """Place an order using raw Bitget API format."""
        data = {
            "symbol": symbol,
            "productType": PRODUCT_TYPE_USDT,
            "marginMode": "crossed",
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

    def calculate_position_size(
        self, balance: float, price: float, risk_percent: float, leverage: int,
    ) -> float:
        """Calculate position size based on risk parameters."""
        risk_amount = balance * (risk_percent / 100)
        position_value = risk_amount * leverage
        return round(position_value / price, 6)
