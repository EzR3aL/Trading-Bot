"""
Bitget WebSocket Client for real-time trading data.

Connects to Bitget Futures WebSocket for:
- Real-time ticker prices (for execution)
- Position updates
- Order updates
- Account updates

Used for local execution since trades are placed on Bitget.
"""

import asyncio
import hashlib
import hmac
import base64
import json
import time
from datetime import datetime
from typing import Optional, Callable, Dict, List
from dataclasses import dataclass, field

import websockets
from websockets.exceptions import ConnectionClosed

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BitgetTick:
    """Real-time Bitget ticker data."""
    symbol: str
    last_price: float
    mark_price: float
    best_bid: float
    best_ask: float
    volume_24h: float
    timestamp: datetime


@dataclass
class PositionUpdate:
    """Position update from WebSocket."""
    symbol: str
    side: str  # long or short
    size: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    margin_mode: str
    leverage: int
    timestamp: datetime


@dataclass
class OrderUpdate:
    """Order update from WebSocket."""
    order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    price: float
    size: float
    filled_size: float
    avg_fill_price: float
    timestamp: datetime


@dataclass
class BitgetWebSocketState:
    """Internal state for WebSocket connection."""
    connected: bool = False
    authenticated: bool = False
    last_ping: Optional[datetime] = None
    last_message: Optional[datetime] = None
    reconnect_count: int = 0
    subscribed_channels: List[Dict] = field(default_factory=list)


class BitgetWebSocket:
    """
    Bitget Futures WebSocket client for real-time trading data.

    Features:
    - Authenticated connection for private data
    - Position and order updates
    - Real-time ticker prices
    - Automatic reconnection

    Usage:
        ws = BitgetWebSocket(api_key, api_secret, passphrase)
        ws.on_position_update = my_callback
        await ws.connect()
        await ws.subscribe_positions()
    """

    # Bitget Futures WebSocket endpoint
    WS_URL = "wss://ws.bitget.com/v2/ws/private"
    WS_PUBLIC_URL = "wss://ws.bitget.com/v2/ws/public"

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
    ):
        """
        Initialize the Bitget WebSocket client.

        Args:
            api_key: Bitget API key (uses config if not provided)
            api_secret: Bitget API secret
            passphrase: Bitget API passphrase
        """
        if not api_key or not api_secret:
            raise ValueError(
                "Bitget WebSocket requires explicit api_key and api_secret. "
                "Credentials are loaded from the database, not environment variables."
            )
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase or ""

        self._ws_private: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_public: Optional[websockets.WebSocketClientProtocol] = None
        self._state = BitgetWebSocketState()
        self._running = False
        self._receive_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._public_task: Optional[asyncio.Task] = None

        # Latest data cache
        self._latest_ticks: Dict[str, BitgetTick] = {}
        self._positions: Dict[str, PositionUpdate] = {}

        # Callbacks
        self.on_tick_update: Optional[Callable[[BitgetTick], None]] = None
        self.on_position_update: Optional[Callable[[PositionUpdate], None]] = None
        self.on_order_update: Optional[Callable[[OrderUpdate], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None
        self.on_reconnect: Optional[Callable[[], None]] = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._state.connected

    @property
    def is_authenticated(self) -> bool:
        """Check if WebSocket is authenticated."""
        return self._state.authenticated

    def get_price(self, symbol: str) -> Optional[float]:
        """Get latest price for a symbol."""
        tick = self._latest_ticks.get(symbol)
        return tick.last_price if tick else None

    def get_position(self, symbol: str) -> Optional[PositionUpdate]:
        """Get current position for a symbol."""
        return self._positions.get(symbol)

    def _generate_signature(self, timestamp: str) -> str:
        """
        Generate HMAC-SHA256 signature for authentication.

        Args:
            timestamp: Unix timestamp in seconds

        Returns:
            Base64 encoded signature
        """
        message = f"{timestamp}GET/user/verify"
        mac = hmac.new(
            bytes(self.api_secret, encoding="utf-8"),
            bytes(message, encoding="utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    async def connect(self) -> bool:
        """
        Connect to Bitget WebSocket (both public and private).

        Returns:
            True if connected successfully
        """
        try:
            # Connect to public WebSocket for tickers
            self._ws_public = await websockets.connect(
                self.WS_PUBLIC_URL,
                ping_interval=25,
                ping_timeout=10,
            )
            logger.info("Connected to Bitget public WebSocket")

            # Connect to private WebSocket for positions/orders
            self._ws_private = await websockets.connect(
                self.WS_URL,
                ping_interval=25,
                ping_timeout=10,
            )
            logger.info("Connected to Bitget private WebSocket")

            # Authenticate private connection
            if not await self._authenticate():
                logger.error("Failed to authenticate Bitget WebSocket")
                return False

            self._state.connected = True
            self._running = True

            # Start receive tasks
            self._receive_task = asyncio.create_task(self._receive_loop_private())
            self._public_task = asyncio.create_task(self._receive_loop_public())
            self._ping_task = asyncio.create_task(self._ping_loop())

            logger.info("Connected to Bitget WebSocket successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Bitget WebSocket: {e}")
            self._state.connected = False
            return False

    async def _authenticate(self) -> bool:
        """
        Authenticate the private WebSocket connection.

        Returns:
            True if authenticated successfully
        """
        try:
            timestamp = str(int(time.time()))
            signature = self._generate_signature(timestamp)

            auth_message = {
                "op": "login",
                "args": [
                    {
                        "apiKey": self.api_key,
                        "passphrase": self.passphrase,
                        "timestamp": timestamp,
                        "sign": signature,
                    }
                ],
            }

            await self._ws_private.send(json.dumps(auth_message))

            # Wait for auth response
            response = await asyncio.wait_for(
                self._ws_private.recv(),
                timeout=10.0
            )

            data = json.loads(response)
            if data.get("event") == "login" and data.get("code") == "0":
                self._state.authenticated = True
                logger.info("Bitget WebSocket authenticated successfully")
                return True
            else:
                logger.error(f"Bitget WebSocket auth failed: {data}")
                return False

        except Exception as e:
            logger.error(f"Error during Bitget WebSocket authentication: {e}")
            return False

    async def disconnect(self):
        """Disconnect from WebSocket."""
        self._running = False
        self._state.connected = False
        self._state.authenticated = False

        for task in [self._receive_task, self._public_task, self._ping_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._ws_private:
            await self._ws_private.close()
            self._ws_private = None

        if self._ws_public:
            await self._ws_public.close()
            self._ws_public = None

        logger.info("Disconnected from Bitget WebSocket")

    async def subscribe_ticker(self, symbols: List[str]):
        """
        Subscribe to ticker updates for symbols.

        Args:
            symbols: List of symbols (e.g., ["BTCUSDT", "ETHUSDT"])
        """
        if not self._ws_public:
            logger.warning("Cannot subscribe: Public WebSocket not connected")
            return

        args = [
            {
                "instType": "USDT-FUTURES",
                "channel": "ticker",
                "instId": symbol,
            }
            for symbol in symbols
        ]

        subscribe_msg = {"op": "subscribe", "args": args}
        await self._ws_public.send(json.dumps(subscribe_msg))
        logger.info(f"Subscribed to Bitget tickers: {symbols}")

    async def subscribe_positions(self):
        """Subscribe to position updates (requires authentication)."""
        if not self._ws_private or not self._state.authenticated:
            logger.warning("Cannot subscribe: Private WebSocket not authenticated")
            return

        subscribe_msg = {
            "op": "subscribe",
            "args": [
                {
                    "instType": "USDT-FUTURES",
                    "channel": "positions",
                    "instId": "default",
                }
            ],
        }

        await self._ws_private.send(json.dumps(subscribe_msg))
        logger.info("Subscribed to Bitget position updates")

    async def subscribe_orders(self):
        """Subscribe to order updates (requires authentication)."""
        if not self._ws_private or not self._state.authenticated:
            logger.warning("Cannot subscribe: Private WebSocket not authenticated")
            return

        subscribe_msg = {
            "op": "subscribe",
            "args": [
                {
                    "instType": "USDT-FUTURES",
                    "channel": "orders",
                    "instId": "default",
                }
            ],
        }

        await self._ws_private.send(json.dumps(subscribe_msg))
        logger.info("Subscribed to Bitget order updates")

    async def _receive_loop_private(self):
        """Receive loop for private WebSocket."""
        while self._running and self._ws_private:
            try:
                message = await asyncio.wait_for(
                    self._ws_private.recv(),
                    timeout=30.0
                )
                self._state.last_message = datetime.now()
                await self._handle_private_message(message)

            except asyncio.TimeoutError:
                continue
            except ConnectionClosed as e:
                logger.warning(f"Bitget private WebSocket closed: {e}")
                if self._running:
                    await self._reconnect()
                break
            except Exception as e:
                logger.error(f"Error in Bitget private receive loop: {e}")

    async def _receive_loop_public(self):
        """Receive loop for public WebSocket."""
        while self._running and self._ws_public:
            try:
                message = await asyncio.wait_for(
                    self._ws_public.recv(),
                    timeout=30.0
                )
                await self._handle_public_message(message)

            except asyncio.TimeoutError:
                continue
            except ConnectionClosed as e:
                logger.warning(f"Bitget public WebSocket closed: {e}")
                break
            except Exception as e:
                logger.error(f"Error in Bitget public receive loop: {e}")

    async def _ping_loop(self):
        """Keep-alive ping loop."""
        while self._running:
            try:
                await asyncio.sleep(25)
                ping_msg = "ping"
                if self._ws_private and self._state.connected:
                    await self._ws_private.send(ping_msg)
                if self._ws_public:
                    await self._ws_public.send(ping_msg)
                self._state.last_ping = datetime.now()
            except Exception as e:
                logger.debug(f"Ping error: {e}")

    async def _handle_private_message(self, raw_message: str):
        """Handle private WebSocket message."""
        try:
            if raw_message == "pong":
                return

            data = json.loads(raw_message)

            # Handle subscription confirmation
            if data.get("event") == "subscribe":
                logger.debug(f"Subscription confirmed: {data}")
                return

            # Handle data updates
            if "action" in data and "data" in data:
                _action = data["action"]
                channel = data.get("arg", {}).get("channel", "")

                if channel == "positions":
                    await self._handle_position_update(data["data"])
                elif channel == "orders":
                    await self._handle_order_update(data["data"])

        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"Error handling private message: {e}")

    async def _handle_public_message(self, raw_message: str):
        """Handle public WebSocket message."""
        try:
            if raw_message == "pong":
                return

            data = json.loads(raw_message)

            if "action" in data and "data" in data:
                channel = data.get("arg", {}).get("channel", "")

                if channel == "ticker":
                    await self._handle_ticker_update(data["data"])

        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"Error handling public message: {e}")

    async def _handle_ticker_update(self, data_list: List[Dict]):
        """Handle ticker update."""
        for data in data_list:
            try:
                symbol = data.get("instId", "")
                if not symbol:
                    continue

                tick = BitgetTick(
                    symbol=symbol,
                    last_price=float(data.get("last", 0)),
                    mark_price=float(data.get("markPrice", data.get("last", 0))),
                    best_bid=float(data.get("bidPr", 0)),
                    best_ask=float(data.get("askPr", 0)),
                    volume_24h=float(data.get("vol24h", 0)),
                    timestamp=datetime.now(),
                )

                self._latest_ticks[symbol] = tick

                if self.on_tick_update:
                    try:
                        if asyncio.iscoroutinefunction(self.on_tick_update):
                            await self.on_tick_update(tick)
                        else:
                            self.on_tick_update(tick)
                    except Exception as e:
                        logger.error(f"Error in tick callback: {e}")

            except Exception as e:
                logger.error(f"Error parsing ticker: {e}")

    async def _handle_position_update(self, data_list: List[Dict]):
        """Handle position update."""
        for data in data_list:
            try:
                symbol = data.get("instId", "")
                if not symbol:
                    continue

                position = PositionUpdate(
                    symbol=symbol,
                    side=data.get("holdSide", ""),
                    size=float(data.get("total", 0)),
                    entry_price=float(data.get("openPriceAvg", 0)),
                    mark_price=float(data.get("markPrice", 0)),
                    unrealized_pnl=float(data.get("unrealizedPL", 0)),
                    margin_mode=data.get("marginMode", "crossed"),
                    leverage=int(data.get("leverage", 1)),
                    timestamp=datetime.now(),
                )

                self._positions[symbol] = position

                if self.on_position_update:
                    try:
                        if asyncio.iscoroutinefunction(self.on_position_update):
                            await self.on_position_update(position)
                        else:
                            self.on_position_update(position)
                    except Exception as e:
                        logger.error(f"Error in position callback: {e}")

            except Exception as e:
                logger.error(f"Error parsing position: {e}")

    async def _handle_order_update(self, data_list: List[Dict]):
        """Handle order update."""
        for data in data_list:
            try:
                order = OrderUpdate(
                    order_id=data.get("orderId", ""),
                    symbol=data.get("instId", ""),
                    side=data.get("side", ""),
                    order_type=data.get("orderType", ""),
                    status=data.get("status", ""),
                    price=float(data.get("price", 0)),
                    size=float(data.get("size", 0)),
                    filled_size=float(data.get("accFillSz", 0)),
                    avg_fill_price=float(data.get("avgPx", 0)),
                    timestamp=datetime.now(),
                )

                if self.on_order_update:
                    try:
                        if asyncio.iscoroutinefunction(self.on_order_update):
                            await self.on_order_update(order)
                        else:
                            self.on_order_update(order)
                    except Exception as e:
                        logger.error(f"Error in order callback: {e}")

            except Exception as e:
                logger.error(f"Error parsing order: {e}")

    async def _reconnect(self):
        """Attempt to reconnect with exponential backoff."""
        self._state.connected = False
        self._state.authenticated = False

        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception:
                pass

        max_retries = 5
        base_delay = 1.0

        for attempt in range(max_retries):
            delay = base_delay * (2 ** attempt)
            logger.info(f"Reconnecting to Bitget WebSocket in {delay}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)

            if await self.connect():
                self._state.reconnect_count += 1
                # Re-subscribe to channels
                for channel in self._state.subscribed_channels:
                    if channel.get("type") == "positions":
                        await self.subscribe_positions()
                    elif channel.get("type") == "orders":
                        await self.subscribe_orders()
                    elif channel.get("type") == "ticker":
                        await self.subscribe_ticker(channel.get("symbols", []))

                if self.on_reconnect:
                    try:
                        self.on_reconnect()
                    except Exception:
                        pass
                return

        logger.error("Failed to reconnect to Bitget WebSocket after max retries")
