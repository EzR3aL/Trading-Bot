"""
Binance WebSocket Client for real-time market data.

Connects to Binance Futures WebSocket for:
- Mark price updates (real-time price)
- Funding rate updates
- Aggregate trade data

Used for global market direction signals (Binance is the primary market).
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field

import websockets
from websockets.exceptions import ConnectionClosed

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MarketTick:
    """Real-time market tick data."""
    symbol: str
    price: float
    mark_price: float
    index_price: float
    funding_rate: float
    next_funding_time: datetime
    timestamp: datetime


@dataclass
class BinanceWebSocketState:
    """Internal state for WebSocket connection."""
    connected: bool = False
    last_ping: Optional[datetime] = None
    last_message: Optional[datetime] = None
    reconnect_count: int = 0
    subscribed_symbols: List[str] = field(default_factory=list)


class BinanceWebSocket:
    """
    Binance Futures WebSocket client for real-time market data.

    Features:
    - Automatic reconnection with exponential backoff
    - Multiple symbol subscription
    - Mark price and funding rate streams
    - Callbacks for price updates

    Usage:
        ws = BinanceWebSocket()
        ws.on_price_update = my_callback
        await ws.connect()
        await ws.subscribe(["BTCUSDT", "ETHUSDT"])
    """

    # Binance Futures WebSocket endpoints
    WS_BASE_URL = "wss://fstream.binance.com/ws"
    STREAM_BASE_URL = "wss://fstream.binance.com/stream"

    def __init__(self):
        """Initialize the Binance WebSocket client."""
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._state = BinanceWebSocketState()
        self._running = False
        self._receive_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None

        # Latest data cache
        self._latest_prices: Dict[str, MarketTick] = {}

        # Callbacks
        self.on_price_update: Optional[Callable[[MarketTick], None]] = None
        self.on_funding_update: Optional[Callable[[str, float], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None
        self.on_reconnect: Optional[Callable[[], None]] = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._state.connected and self._ws is not None

    @property
    def latest_prices(self) -> Dict[str, MarketTick]:
        """Get cached latest prices for all subscribed symbols."""
        return self._latest_prices

    def get_price(self, symbol: str) -> Optional[float]:
        """Get latest price for a symbol."""
        tick = self._latest_prices.get(symbol)
        return tick.price if tick else None

    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """Get latest funding rate for a symbol."""
        tick = self._latest_prices.get(symbol)
        return tick.funding_rate if tick else None

    async def connect(self, symbols: Optional[List[str]] = None) -> bool:
        """
        Connect to Binance WebSocket and subscribe to symbols.

        Args:
            symbols: List of symbols to subscribe (e.g., ["BTCUSDT", "ETHUSDT"])

        Returns:
            True if connected successfully
        """
        if symbols is None:
            symbols = ["BTCUSDT", "ETHUSDT"]

        try:
            # Build stream URL with mark price streams
            streams = [f"{s.lower()}@markPrice@1s" for s in symbols]
            stream_param = "/".join(streams)
            url = f"{self.STREAM_BASE_URL}?streams={stream_param}"

            logger.info(f"Connecting to Binance WebSocket: {url}")

            self._ws = await websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            )

            self._state.connected = True
            self._state.subscribed_symbols = symbols
            self._state.last_message = datetime.now()
            self._running = True

            # Start receive and ping tasks
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())

            logger.info(f"Connected to Binance WebSocket. Subscribed to: {symbols}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Binance WebSocket: {e}")
            self._state.connected = False
            return False

    async def disconnect(self):
        """Disconnect from WebSocket."""
        self._running = False
        self._state.connected = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        logger.info("Disconnected from Binance WebSocket")

    async def _receive_loop(self):
        """Main receive loop for WebSocket messages."""
        while self._running and self._ws:
            try:
                message = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=30.0
                )
                self._state.last_message = datetime.now()
                await self._handle_message(message)

            except asyncio.TimeoutError:
                logger.warning("Binance WebSocket receive timeout")
                continue

            except ConnectionClosed as e:
                logger.warning(f"Binance WebSocket connection closed: {e}")
                if self._running:
                    await self._reconnect()
                break

            except Exception as e:
                logger.error(f"Error in Binance WebSocket receive loop: {e}")
                if self._running:
                    await asyncio.sleep(1)

    async def _ping_loop(self):
        """Keep-alive ping loop."""
        while self._running:
            try:
                await asyncio.sleep(30)
                if self._ws and self._state.connected:
                    await self._ws.ping()
                    self._state.last_ping = datetime.now()
            except Exception as e:
                logger.debug(f"Ping error: {e}")

    async def _handle_message(self, raw_message: str):
        """
        Handle incoming WebSocket message.

        Args:
            raw_message: Raw JSON message string
        """
        try:
            data = json.loads(raw_message)

            # Combined stream format: {"stream": "...", "data": {...}}
            if "stream" in data:
                stream_name = data["stream"]
                stream_data = data["data"]

                # Mark price stream: btcusdt@markPrice@1s
                if "@markPrice" in stream_name:
                    await self._handle_mark_price(stream_data)

            # Direct format (single stream)
            elif "e" in data:
                event_type = data["e"]
                if event_type == "markPriceUpdate":
                    await self._handle_mark_price(data)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse WebSocket message: {e}")
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")

    async def _handle_mark_price(self, data: Dict[str, Any]):
        """
        Handle mark price update.

        Data format:
        {
            "e": "markPriceUpdate",
            "E": 1562305380000,
            "s": "BTCUSDT",
            "p": "11794.15000000",  # Mark price
            "i": "11784.62659091",  # Index price
            "P": "11784.25641265",  # Estimated settle price (only for delivery)
            "r": "0.00038167",      # Funding rate
            "T": 1562306400000      # Next funding time
        }
        """
        try:
            symbol = data.get("s", "")
            if not symbol:
                return

            tick = MarketTick(
                symbol=symbol,
                price=float(data.get("p", 0)),
                mark_price=float(data.get("p", 0)),
                index_price=float(data.get("i", 0)),
                funding_rate=float(data.get("r", 0)),
                next_funding_time=datetime.fromtimestamp(int(data.get("T", 0)) / 1000),
                timestamp=datetime.now(),
            )

            # Update cache
            self._latest_prices[symbol] = tick

            # Call callback if registered
            if self.on_price_update:
                try:
                    if asyncio.iscoroutinefunction(self.on_price_update):
                        await self.on_price_update(tick)
                    else:
                        self.on_price_update(tick)
                except Exception as e:
                    logger.error(f"Error in price update callback: {e}")

            # Call funding callback if rate changed significantly
            if self.on_funding_update and abs(tick.funding_rate) > 0:
                try:
                    if asyncio.iscoroutinefunction(self.on_funding_update):
                        await self.on_funding_update(symbol, tick.funding_rate)
                    else:
                        self.on_funding_update(symbol, tick.funding_rate)
                except Exception as e:
                    logger.error(f"Error in funding update callback: {e}")

        except Exception as e:
            logger.error(f"Error parsing mark price data: {e}")

    async def _reconnect(self):
        """Attempt to reconnect with exponential backoff."""
        self._state.connected = False

        if self.on_disconnect:
            try:
                self.on_disconnect()
            except Exception:
                pass

        max_retries = 5
        base_delay = 1.0

        for attempt in range(max_retries):
            delay = base_delay * (2 ** attempt)
            logger.info(f"Reconnecting to Binance WebSocket in {delay}s (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)

            if await self.connect(self._state.subscribed_symbols):
                self._state.reconnect_count += 1
                if self.on_reconnect:
                    try:
                        self.on_reconnect()
                    except Exception:
                        pass
                return

        logger.error("Failed to reconnect to Binance WebSocket after max retries")

    async def subscribe(self, symbols: List[str]):
        """
        Subscribe to additional symbols.

        Args:
            symbols: List of symbols to add
        """
        if not self._ws or not self._state.connected:
            logger.warning("Cannot subscribe: WebSocket not connected")
            return

        # Add new symbols to existing subscription
        new_symbols = [s for s in symbols if s not in self._state.subscribed_symbols]
        if not new_symbols:
            return

        # Need to reconnect with new streams (Binance doesn't support dynamic subscription well)
        all_symbols = list(set(self._state.subscribed_symbols + new_symbols))
        await self.disconnect()
        await self.connect(all_symbols)

    async def unsubscribe(self, symbols: List[str]):
        """
        Unsubscribe from symbols.

        Args:
            symbols: List of symbols to remove
        """
        remaining = [s for s in self._state.subscribed_symbols if s not in symbols]
        if remaining:
            await self.disconnect()
            await self.connect(remaining)
        else:
            await self.disconnect()
