"""Weex WebSocket adapter implementing ExchangeWebSocket ABC."""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Callable, Dict, List

import websockets
from websockets.exceptions import ConnectionClosed

from src.exchanges.base import ExchangeWebSocket
from src.exchanges.weex.constants import WS_PRIVATE_URL, WS_PUBLIC_URL
from src.observability.metrics import EXCHANGE_WEBSOCKET_CONNECTED
from src.utils.logger import get_logger

logger = get_logger(__name__)


class WeexWebSocket(ExchangeWebSocket):
    """Weex Futures WebSocket client (similar to Bitget protocol)."""

    def __init__(self, api_key: str = "", api_secret: str = "",
                 passphrase: str = "", demo_mode: bool = True, **kwargs):
        super().__init__(api_key, api_secret, passphrase, demo_mode)
        self._ws_private = None
        self._ws_public = None
        self._running = False
        self._authenticated = False
        self._tasks: List[asyncio.Task] = []
        self._callbacks: Dict[str, Callable] = {}

    def _generate_signature(self, timestamp: str) -> str:
        message = f"{timestamp}GET/user/verify"
        mac = hmac.new(
            self.api_secret.encode(), message.encode(), digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    async def connect(self) -> None:
        self._ws_public = await websockets.connect(WS_PUBLIC_URL, ping_interval=25)
        if self.api_key:
            self._ws_private = await websockets.connect(WS_PRIVATE_URL, ping_interval=25)
            timestamp = str(int(time.time()))
            auth_msg = {
                "op": "login",
                "args": [{
                    "apiKey": self.api_key, "passphrase": self.passphrase,
                    "timestamp": timestamp, "sign": self._generate_signature(timestamp),
                }],
            }
            await self._ws_private.send(json.dumps(auth_msg))
            resp = await asyncio.wait_for(self._ws_private.recv(), timeout=10)
            data = json.loads(resp)
            self._authenticated = data.get("event") == "login" and data.get("code") == "0"

        self._connected = True
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange="weex").set(1)
        self._running = True
        self._tasks.append(asyncio.create_task(self._receive_loop(self._ws_public, "public")))
        if self._ws_private:
            self._tasks.append(asyncio.create_task(self._receive_loop(self._ws_private, "private")))

    async def subscribe_positions(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws_private:
            return
        self._callbacks["positions"] = callback
        msg = {"op": "subscribe", "args": [{"instType": "USDT-FUTURES", "channel": "positions", "instId": "default"}]}
        await self._ws_private.send(json.dumps(msg))

    async def subscribe_orders(self, callback: Callable) -> None:
        if not self._ws_private:
            return
        self._callbacks["orders"] = callback
        msg = {"op": "subscribe", "args": [{"instType": "USDT-FUTURES", "channel": "orders", "instId": "default"}]}
        await self._ws_private.send(json.dumps(msg))

    async def subscribe_ticker(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws_public:
            return
        self._callbacks["ticker"] = callback
        args = [{"instType": "USDT-FUTURES", "channel": "ticker", "instId": s} for s in symbols]
        await self._ws_public.send(json.dumps({"op": "subscribe", "args": args}))

    async def disconnect(self) -> None:
        self._running = False
        self._connected = False
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange="weex").set(0)
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        for ws in (self._ws_private, self._ws_public):
            if ws:
                await ws.close()

    async def _receive_loop(self, ws, label: str):
        while self._running and ws:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
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
                logger.error(f"Weex {label} WS error: {e}")
