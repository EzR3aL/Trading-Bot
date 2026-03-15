"""
Bitunix WebSocket adapter implementing ExchangeWebSocket ABC.

Bitunix uses separate public/private WebSocket URLs.
Auth: double-SHA256 signature (same algorithm as REST API).
Channels: MarketPrice, Ticker, Trade, Depth, Kline (public)
          Balance, Order, Position, TpSl (private)
"""

import asyncio
import hashlib
import json
import secrets
import time
from typing import Callable, Dict, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from src.exchanges.base import ExchangeWebSocket
from src.exchanges.bitunix.constants import WS_PRIVATE_URL, WS_PUBLIC_URL
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BitunixWebSocket(ExchangeWebSocket):
    """Bitunix Futures WebSocket client implementing ExchangeWebSocket ABC."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        passphrase: str = "",
        demo_mode: bool = True,
        **kwargs,
    ):
        super().__init__(api_key, api_secret, passphrase, demo_mode)
        self._ws_private: Optional[websockets.WebSocketClientProtocol] = None
        self._ws_public: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._authenticated = False
        self._tasks: List[asyncio.Task] = []
        self._callbacks: Dict[str, Callable] = {}

    def _generate_signature(self, nonce: str, timestamp: str) -> str:
        """Double-SHA256 signature matching Bitunix REST auth."""
        digest = hashlib.sha256(
            f"{nonce}{timestamp}{self.api_key}".encode()
        ).hexdigest()
        return hashlib.sha256(
            f"{digest}{self.api_secret}".encode()
        ).hexdigest()

    async def connect(self) -> None:
        self._ws_public = await websockets.connect(
            WS_PUBLIC_URL, ping_interval=25, ping_timeout=10,
        )
        logger.info("Connected to Bitunix public WebSocket")

        if self.api_key:
            self._ws_private = await websockets.connect(
                WS_PRIVATE_URL, ping_interval=25, ping_timeout=10,
            )
            await self._authenticate()

        self._connected = True
        self._running = True

        self._tasks.append(asyncio.create_task(self._receive_loop(self._ws_public, "public")))
        if self._ws_private:
            self._tasks.append(asyncio.create_task(self._receive_loop(self._ws_private, "private")))
        self._tasks.append(asyncio.create_task(self._ping_loop()))

    async def _authenticate(self) -> None:
        timestamp = str(int(time.time() * 1000))
        nonce = secrets.token_hex(16)
        sign = self._generate_signature(nonce, timestamp)
        auth_msg = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "timestamp": int(timestamp),
                "nonce": nonce,
                "sign": sign,
            }],
        }
        await self._ws_private.send(json.dumps(auth_msg))
        response = await asyncio.wait_for(self._ws_private.recv(), timeout=10.0)
        data = json.loads(response)
        if data.get("op") == "login" and data.get("code") in (0, "0", None):
            self._authenticated = True
            logger.info("Bitunix WebSocket authenticated")
        else:
            raise ConnectionError(f"Bitunix WS auth failed: {data}")

    async def subscribe_positions(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws_private or not self._authenticated:
            return
        self._callbacks["position"] = callback
        for symbol in symbols:
            msg = {
                "op": "subscribe",
                "args": [{"ch": "position", "symbol": symbol}],
            }
            await self._ws_private.send(json.dumps(msg))
        logger.info("Subscribed to Bitunix position channel: %s", symbols)

    async def subscribe_orders(self, callback: Callable) -> None:
        if not self._ws_private or not self._authenticated:
            return
        self._callbacks["order"] = callback
        msg = {
            "op": "subscribe",
            "args": [{"ch": "order"}],
        }
        await self._ws_private.send(json.dumps(msg))
        logger.info("Subscribed to Bitunix order channel")

    async def subscribe_ticker(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws_public:
            return
        self._callbacks["ticker"] = callback
        for symbol in symbols:
            msg = {
                "op": "subscribe",
                "args": [{"ch": "ticker", "symbol": symbol}],
            }
            await self._ws_public.send(json.dumps(msg))

    async def disconnect(self) -> None:
        self._running = False
        self._connected = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        for ws in (self._ws_private, self._ws_public):
            if ws:
                await ws.close()
        self._ws_private = None
        self._ws_public = None

    async def _receive_loop(self, ws, label: str):
        while self._running and ws:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                data = json.loads(msg)

                # Skip pong responses
                if data.get("op") == "ping":
                    continue

                # Route data to appropriate callback
                ch = data.get("ch", "")
                if ch and ch in self._callbacks:
                    payload = data.get("data")
                    if payload is not None:
                        items = payload if isinstance(payload, list) else [payload]
                        for item in items:
                            cb = self._callbacks[ch]
                            if asyncio.iscoroutinefunction(cb):
                                await cb(item)
                            else:
                                cb(item)
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                logger.warning("Bitunix %s WebSocket disconnected", label)
                break
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error("Bitunix %s WS error: %s", label, e)

    async def _ping_loop(self):
        while self._running:
            await asyncio.sleep(25)
            try:
                ping_msg = json.dumps({
                    "op": "ping",
                    "ping": int(time.time()),
                })
                if self._ws_public:
                    await self._ws_public.send(ping_msg)
                if self._ws_private:
                    await self._ws_private.send(ping_msg)
            except Exception as e:
                logger.debug("Bitunix heartbeat ping failed: %s", e)
