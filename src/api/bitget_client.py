"""
Bitget Exchange API Client.
Handles all interactions with Bitget's Futures API for trading operations.
"""

import json
import time
import hmac
import hashlib
import base64
from typing import Optional, Dict, Any, Literal
from datetime import datetime

import aiohttp

from config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BitgetClientError(Exception):
    """Custom exception for Bitget API errors."""
    pass


class BitgetClient:
    """
    Async client for Bitget Futures API.

    Supports:
    - Account balance queries
    - Market data retrieval
    - Order placement (market, limit)
    - Position management
    - Funding rate queries
    """

    BASE_URL = "https://api.bitget.com"
    TESTNET_URL = "https://api.bitget.com"  # Bitget uses same URL for demo trading

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
        testnet: bool = False,
        demo_mode: bool = False,
    ):
        """
        Initialize the Bitget client.

        Args:
            api_key: API key (if None, loads from settings based on demo_mode)
            api_secret: API secret (if None, loads from settings based on demo_mode)
            passphrase: API passphrase (if None, loads from settings based on demo_mode)
            testnet: Use testnet (different from demo mode)
            demo_mode: Use demo trading API (paper trading on Bitget Demo Account)
        """
        self.demo_mode = demo_mode if demo_mode is not None else settings.is_demo_mode

        # Load appropriate credentials based on trading mode
        if self.demo_mode:
            self.api_key = api_key or settings.bitget.demo_api_key
            self.api_secret = api_secret or settings.bitget.demo_api_secret
            self.passphrase = passphrase or settings.bitget.demo_passphrase
            logger.info("BitgetClient initialized in DEMO mode (paper trading)")
        else:
            self.api_key = api_key or settings.bitget.api_key
            self.api_secret = api_secret or settings.bitget.api_secret
            self.passphrase = passphrase or settings.bitget.passphrase
            logger.info("BitgetClient initialized in LIVE mode (real trading)")

        self.testnet = testnet or settings.bitget.testnet
        self.base_url = self.TESTNET_URL if self.testnet else self.BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """Generate HMAC SHA256 signature for API authentication."""
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(
            bytes(self.api_secret, encoding="utf-8"),
            bytes(message, encoding="utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """Generate authenticated headers for API requests."""
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

        # Add demo trading header if in demo mode
        # Note: Bitget's exact demo trading implementation may vary
        # This header is a common pattern used by many exchanges
        if self.demo_mode:
            headers["X-SIMULATED-TRADING"] = "1"

        return headers

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth: bool = True,
    ) -> Dict[str, Any]:
        """Make an API request to Bitget."""
        await self._ensure_session()

        url = f"{self.base_url}{endpoint}"
        body = ""

        if data:
            body = json.dumps(data)

        if params:
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            request_path = f"{endpoint}?{query_string}"
            url = f"{url}?{query_string}"
        else:
            request_path = endpoint

        headers = self._get_headers(method, request_path, body) if auth else {"Content-Type": "application/json"}

        try:
            async with self._session.request(
                method=method,
                url=url,
                headers=headers,
                data=body if body else None,
            ) as response:
                result = await response.json()

                if response.status != 200:
                    logger.error(f"API Error: {response.status} - {result}")
                    raise BitgetClientError(f"API Error: {result.get('msg', 'Unknown error')}")

                if result.get("code") != "00000":
                    logger.error(f"Bitget Error: {result}")
                    raise BitgetClientError(f"Bitget Error: {result.get('msg', 'Unknown error')}")

                return result.get("data", result)

        except aiohttp.ClientError as e:
            logger.error(f"HTTP Error: {e}")
            raise BitgetClientError(f"HTTP Error: {e}")

    # ==================== Account Methods ====================

    async def get_account_balance(self, margin_coin: str = "USDT") -> Dict[str, Any]:
        """
        Get account balance for futures trading.

        Args:
            margin_coin: The margin coin (default: USDT)

        Returns:
            Account balance information including available, frozen, and equity
        """
        endpoint = "/api/v2/mix/account/account"
        params = {
            "symbol": "BTCUSDT",  # Required param
            "productType": "USDT-FUTURES",
            "marginCoin": margin_coin,
        }
        return await self._request("GET", endpoint, params=params)

    async def get_all_positions(self, product_type: str = "USDT-FUTURES") -> list:
        """
        Get all open positions.

        Args:
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            List of open positions
        """
        endpoint = "/api/v2/mix/position/all-position"
        params = {
            "productType": product_type,
            "marginCoin": "USDT",
        }
        return await self._request("GET", endpoint, params=params)

    async def get_position(self, symbol: str, product_type: str = "USDT-FUTURES") -> Dict[str, Any]:
        """
        Get position for a specific symbol.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            Position information
        """
        endpoint = "/api/v2/mix/position/single-position"
        params = {
            "symbol": symbol,
            "productType": product_type,
            "marginCoin": "USDT",
        }
        return await self._request("GET", endpoint, params=params)

    # ==================== Market Data Methods ====================

    async def get_ticker(self, symbol: str, product_type: str = "USDT-FUTURES") -> Dict[str, Any]:
        """
        Get current ticker information for a symbol.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            Ticker data including last price, 24h change, volume
        """
        endpoint = "/api/v2/mix/market/ticker"
        params = {
            "symbol": symbol,
            "productType": product_type,
        }
        return await self._request("GET", endpoint, params=params, auth=False)

    async def get_funding_rate(self, symbol: str, product_type: str = "USDT-FUTURES") -> Dict[str, Any]:
        """
        Get current funding rate for a symbol.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            Funding rate information
        """
        endpoint = "/api/v2/mix/market/current-fund-rate"
        params = {
            "symbol": symbol,
            "productType": product_type,
        }
        return await self._request("GET", endpoint, params=params, auth=False)

    async def get_historical_funding_rates(
        self, symbol: str, product_type: str = "USDT-FUTURES", limit: int = 100
    ) -> list:
        """
        Get historical funding rates.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            product_type: USDT-FUTURES or COIN-FUTURES
            limit: Number of records to fetch

        Returns:
            List of historical funding rates
        """
        endpoint = "/api/v2/mix/market/history-fund-rate"
        params = {
            "symbol": symbol,
            "productType": product_type,
            "pageSize": str(limit),
        }
        return await self._request("GET", endpoint, params=params, auth=False)

    async def get_candlesticks(
        self,
        symbol: str,
        granularity: str = "1H",
        product_type: str = "USDT-FUTURES",
        limit: int = 100,
    ) -> list:
        """
        Get candlestick/kline data.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            granularity: Timeframe (1m, 5m, 15m, 30m, 1H, 4H, 1D, etc.)
            product_type: USDT-FUTURES or COIN-FUTURES
            limit: Number of candles to fetch

        Returns:
            List of candlestick data
        """
        endpoint = "/api/v2/mix/market/candles"
        params = {
            "symbol": symbol,
            "productType": product_type,
            "granularity": granularity,
            "limit": str(limit),
        }
        return await self._request("GET", endpoint, params=params, auth=False)

    async def get_open_interest(self, symbol: str, product_type: str = "USDT-FUTURES") -> Dict[str, Any]:
        """
        Get open interest for a symbol.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            Open interest data
        """
        endpoint = "/api/v2/mix/market/open-interest"
        params = {
            "symbol": symbol,
            "productType": product_type,
        }
        return await self._request("GET", endpoint, params=params, auth=False)

    # ==================== Trading Methods ====================

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        product_type: str = "USDT-FUTURES",
        margin_coin: str = "USDT",
        hold_side: str = "long",
    ) -> Dict[str, Any]:
        """
        Set leverage for a symbol.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            leverage: Leverage value (1-125)
            product_type: USDT-FUTURES or COIN-FUTURES
            margin_coin: Margin coin (default: USDT)
            hold_side: long or short

        Returns:
            Leverage setting confirmation
        """
        endpoint = "/api/v2/mix/account/set-leverage"
        data = {
            "symbol": symbol,
            "productType": product_type,
            "marginCoin": margin_coin,
            "leverage": str(leverage),
            "holdSide": hold_side,
        }
        return await self._request("POST", endpoint, data=data)

    async def place_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        trade_side: Literal["open", "close"],
        size: str,
        order_type: Literal["market", "limit"] = "market",
        price: Optional[str] = None,
        product_type: str = "USDT-FUTURES",
        margin_coin: str = "USDT",
        client_oid: Optional[str] = None,
        take_profit: Optional[str] = None,
        stop_loss: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Place a futures order.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: buy or sell
            trade_side: open (new position) or close (close position)
            size: Order size in base currency
            order_type: market or limit
            price: Price for limit orders
            product_type: USDT-FUTURES or COIN-FUTURES
            margin_coin: Margin coin (default: USDT)
            client_oid: Custom order ID
            take_profit: Take profit trigger price
            stop_loss: Stop loss trigger price

        Returns:
            Order placement result with order ID
        """
        endpoint = "/api/v2/mix/order/place-order"

        data = {
            "symbol": symbol,
            "productType": product_type,
            "marginMode": "crossed",
            "marginCoin": margin_coin,
            "side": side,
            "tradeSide": trade_side,
            "orderType": order_type,
            "size": size,
        }

        if price and order_type == "limit":
            data["price"] = price

        if client_oid:
            data["clientOid"] = client_oid

        # Add TP/SL if provided
        if take_profit:
            data["presetStopSurplusPrice"] = take_profit
        if stop_loss:
            data["presetStopLossPrice"] = stop_loss

        logger.info(f"Placing order: {data}")
        return await self._request("POST", endpoint, data=data)

    async def place_market_order(
        self,
        symbol: str,
        side: Literal["long", "short"],
        size: str,
        take_profit: Optional[str] = None,
        stop_loss: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convenience method to place a market order.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: long or short
            size: Order size in base currency
            take_profit: Take profit price
            stop_loss: Stop loss price

        Returns:
            Order result
        """
        # Determine order side based on position direction
        order_side = "buy" if side == "long" else "sell"

        return await self.place_order(
            symbol=symbol,
            side=order_side,
            trade_side="open",
            size=size,
            order_type="market",
            take_profit=take_profit,
            stop_loss=stop_loss,
        )

    async def close_position(
        self,
        symbol: str,
        hold_side: Literal["long", "short"],
        size: Optional[str] = None,
        product_type: str = "USDT-FUTURES",
    ) -> Dict[str, Any]:
        """
        Close an existing position.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            hold_side: long or short (the position to close)
            size: Size to close (None = close all)
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            Close order result
        """
        # To close a long, we sell; to close a short, we buy
        order_side = "sell" if hold_side == "long" else "buy"

        # If no size specified, get current position size
        if size is None:
            position = await self.get_position(symbol, product_type)
            if position:
                for pos in position if isinstance(position, list) else [position]:
                    if pos.get("holdSide") == hold_side:
                        size = pos.get("total", "0")
                        break

        if not size or size == "0":
            logger.warning(f"No position to close for {symbol} {hold_side}")
            return {"msg": "No position to close"}

        return await self.place_order(
            symbol=symbol,
            side=order_side,
            trade_side="close",
            size=size,
            order_type="market",
            product_type=product_type,
        )

    async def cancel_order(
        self,
        symbol: str,
        order_id: str,
        product_type: str = "USDT-FUTURES",
    ) -> Dict[str, Any]:
        """
        Cancel an open order.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            order_id: Order ID to cancel
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            Cancellation result
        """
        endpoint = "/api/v2/mix/order/cancel-order"
        data = {
            "symbol": symbol,
            "productType": product_type,
            "orderId": order_id,
        }
        return await self._request("POST", endpoint, data=data)

    async def get_order(
        self,
        symbol: str,
        order_id: str,
        product_type: str = "USDT-FUTURES",
    ) -> Dict[str, Any]:
        """
        Get order details.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            order_id: Order ID
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            Order details
        """
        endpoint = "/api/v2/mix/order/detail"
        params = {
            "symbol": symbol,
            "productType": product_type,
            "orderId": order_id,
        }
        return await self._request("GET", endpoint, params=params)

    async def get_open_orders(
        self,
        symbol: Optional[str] = None,
        product_type: str = "USDT-FUTURES",
    ) -> list:
        """
        Get all open orders.

        Args:
            symbol: Trading pair (optional, None = all symbols)
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            List of open orders
        """
        endpoint = "/api/v2/mix/order/orders-pending"
        params = {
            "productType": product_type,
        }
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", endpoint, params=params)

    async def get_order_history(
        self,
        symbol: str,
        product_type: str = "USDT-FUTURES",
        limit: int = 100,
    ) -> list:
        """
        Get order history.

        Args:
            symbol: Trading pair
            product_type: USDT-FUTURES or COIN-FUTURES
            limit: Number of records

        Returns:
            List of historical orders
        """
        endpoint = "/api/v2/mix/order/orders-history"
        params = {
            "symbol": symbol,
            "productType": product_type,
            "pageSize": str(limit),
        }
        return await self._request("GET", endpoint, params=params)

    async def get_fill_price(
        self,
        symbol: str,
        order_id: str,
        product_type: str = "USDT-FUTURES",
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ) -> Optional[float]:
        """
        Get the actual fill price for a completed order.

        For market orders, the fill price may not be immediately available.
        This method retries with exponential backoff.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            order_id: Order ID
            product_type: USDT-FUTURES or COIN-FUTURES
            max_retries: Maximum number of retries
            retry_delay: Initial delay between retries (doubles each retry)

        Returns:
            Fill price as float, or None if not available
        """
        import asyncio

        for attempt in range(max_retries):
            try:
                order_detail = await self.get_order(symbol, order_id, product_type)

                if order_detail:
                    # Bitget returns 'priceAvg' for average fill price
                    fill_price = order_detail.get("priceAvg") or order_detail.get("fillPrice")
                    if fill_price and float(fill_price) > 0:
                        logger.info(f"Order {order_id} fill price: ${float(fill_price):.2f}")
                        return float(fill_price)

                    # Check order state - if still pending, wait
                    state = order_detail.get("state", "")
                    if state in ["live", "new", "pending"]:
                        logger.debug(f"Order {order_id} still pending (attempt {attempt + 1})")
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue

            except Exception as e:
                logger.warning(f"Error getting fill price (attempt {attempt + 1}): {e}")

            await asyncio.sleep(retry_delay * (2 ** attempt))

        logger.warning(f"Could not get fill price for order {order_id} after {max_retries} attempts")
        return None

    # ==================== Utility Methods ====================

    async def get_symbol_info(self, symbol: str, product_type: str = "USDT-FUTURES") -> Dict[str, Any]:
        """
        Get trading pair information (min size, tick size, etc.).

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            product_type: USDT-FUTURES or COIN-FUTURES

        Returns:
            Symbol specifications
        """
        endpoint = "/api/v2/mix/market/contracts"
        params = {
            "productType": product_type,
        }
        result = await self._request("GET", endpoint, params=params, auth=False)

        # Find the specific symbol
        for contract in result if isinstance(result, list) else []:
            if contract.get("symbol") == symbol:
                return contract

        return {}

    def calculate_position_size(
        self,
        balance: float,
        price: float,
        risk_percent: float,
        leverage: int,
    ) -> float:
        """
        Calculate position size based on risk parameters.

        Args:
            balance: Account balance in USDT
            price: Current asset price
            risk_percent: Percentage of balance to risk
            leverage: Leverage to use

        Returns:
            Position size in base currency
        """
        risk_amount = balance * (risk_percent / 100)
        position_value = risk_amount * leverage
        position_size = position_value / price
        return round(position_size, 6)
