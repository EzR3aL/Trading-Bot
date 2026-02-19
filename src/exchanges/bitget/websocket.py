"""
Bitget WebSocket adapter implementing ExchangeWebSocket ABC.

Refactored from src/websocket/bitget_ws.py.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from src.exchanges.base import ExchangeWebSocket
from src.exchanges.bitget.constants import WS_PRIVATE_URL, WS_PUBLIC_URL
from src.utils.logger import get_logger

logger = get_logger(__name__)


class BitgetExchangeWebSocket(ExchangeWebSocket):
    """Bitget Futures WebSocket client implementing ExchangeWebSocket ABC."""

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
        self._latest_ticks: Dict[str, dict] = {}

    def _generate_signature(self, timestamp: str) -> str:
        message = f"{timestamp}GET/user/verify"
        mac = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    async def connect(self) -> None:
        self._ws_public = await websockets.connect(
            WS_PUBLIC_URL, ping_interval=25, ping_timeout=10,
        )
        logger.info("Connected to Bitget public WebSocket")

        if self.api_key:
            self._ws_private = await websockets.connect(
                WS_PRIVATE_URL, ping_interval=25, ping_timeout=10,
            )
            await self._authenticate()

        self._connected = True
        self._running = True

        self._tasks.append(asyncio.create_task(self._receive_public()))
        if self._ws_private:
            self._tasks.append(asyncio.create_task(self._receive_private()))
        self._tasks.append(asyncio.create_task(self._ping_loop()))

    async def _authenticate(self) -> None:
        timestamp = str(int(time.time()))
        signature = self._generate_signature(timestamp)
        auth_msg = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": timestamp,
                "sign": signature,
            }],
        }
        await self._ws_private.send(json.dumps(auth_msg))
        response = await asyncio.wait_for(self._ws_private.recv(), timeout=10.0)
        data = json.loads(response)
        if data.get("event") == "login" and data.get("code") == "0":
            self._authenticated = True
            logger.info("Bitget WebSocket authenticated")
        else:
            raise ConnectionError(f"Bitget WS auth failed: {data}")

    async def subscribe_positions(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws_private or not self._authenticated:
            return
        self._callbacks["positions"] = callback
        msg = {
            "op": "subscribe",
            "args": [{"instType": "USDT-FUTURES", "channel": "positions", "instId": "default"}],
        }
        await self._ws_private.send(json.dumps(msg))

    async def subscribe_orders(self, callback: Callable) -> None:
        if not self._ws_private or not self._authenticated:
            return
        self._callbacks["orders"] = callback
        msg = {
            "op": "subscribe",
            "args": [{"instType": "USDT-FUTURES", "channel": "orders", "instId": "default"}],
        }
        await self._ws_private.send(json.dumps(msg))

    async def subscribe_ticker(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws_public:
            return
        self._callbacks["ticker"] = callback
        args = [{"instType": "USDT-FUTURES", "channel": "ticker", "instId": s} for s in symbols]
        msg = {"op": "subscribe", "args": args}
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

    async def _receive_public(self):
        while self._running and self._ws_public:
            try:
                msg = await asyncio.wait_for(self._ws_public.recv(), timeout=30.0)
                if msg == "pong":
                    continue
                data = json.loads(msg)
                if "data" in data:
                    channel = data.get("arg", {}).get("channel", "")
                    if channel == "ticker" and "ticker" in self._callbacks:
                        for item in data["data"]:
                            self._callbacks["ticker"](item)
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                break
            except Exception as e:
                logger.error(f"Public WS error: {e}")

    async def _receive_private(self):
        while self._running and self._ws_private:
            try:
                msg = await asyncio.wait_for(self._ws_private.recv(), timeout=30.0)
                if msg == "pong":
                    continue
                data = json.loads(msg)
                if "data" in data:
                    channel = data.get("arg", {}).get("channel", "")
                    cb = self._callbacks.get(channel)
                    if cb:
                        for item in data["data"]:
                            if asyncio.iscoroutinefunction(cb):
                                await cb(item)
                            else:
                                cb(item)
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                break
            except Exception as e:
                logger.error(f"Private WS error: {e}")

    async def _ping_loop(self):
        while self._running:
            await asyncio.sleep(25)
            try:
                if self._ws_public:
                    await self._ws_public.send("ping")
                if self._ws_private:
                    await self._ws_private.send("ping")
            except Exception as e:
                logger.debug("Heartbeat ping failed: %s", e)
