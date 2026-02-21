"""Hyperliquid WebSocket adapter implementing ExchangeWebSocket ABC."""

import asyncio
import json
from typing import Callable, Dict, List

import websockets
from websockets.exceptions import ConnectionClosed

from src.exchanges.base import ExchangeWebSocket
from src.exchanges.hyperliquid.constants import WS_TESTNET_URL, WS_URL
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidWebSocket(ExchangeWebSocket):
    """
    Hyperliquid WebSocket client.

    Hyperliquid uses a different subscription model than Bitget/Weex.
    No separate auth step; subscriptions include the wallet address.
    """

    def __init__(self, api_key: str = "", api_secret: str = "",
                 passphrase: str = "", demo_mode: bool = True, **kwargs):
        super().__init__(api_key, api_secret, passphrase, demo_mode)
        self.wallet_address = api_key
        self.ws_url = WS_TESTNET_URL if demo_mode else WS_URL
        self._ws = None
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._callbacks: Dict[str, Callable] = {}

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.ws_url, ping_interval=20)
        self._connected = True
        self._running = True
        self._tasks.append(asyncio.create_task(self._receive_loop()))
        logger.info("Connected to Hyperliquid WebSocket")

    async def subscribe_positions(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws:
            return
        self._callbacks["userEvents"] = callback
        msg = {
            "method": "subscribe",
            "subscription": {"type": "userEvents", "user": self.wallet_address},
        }
        await self._ws.send(json.dumps(msg))

    async def subscribe_orders(self, callback: Callable) -> None:
        if not self._ws:
            return
        self._callbacks["userFills"] = callback
        msg = {
            "method": "subscribe",
            "subscription": {"type": "userFills", "user": self.wallet_address},
        }
        await self._ws.send(json.dumps(msg))

    async def subscribe_ticker(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws:
            return
        self._callbacks["allMids"] = callback
        msg = {"method": "subscribe", "subscription": {"type": "allMids"}}
        await self._ws.send(json.dumps(msg))

    async def disconnect(self) -> None:
        self._running = False
        self._connected = False
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()

    async def _receive_loop(self):
        while self._running and self._ws:
            try:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=30)
                data = json.loads(msg)
                channel = data.get("channel", "")
                cb = self._callbacks.get(channel)
                if cb and "data" in data:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(data["data"])
                    else:
                        cb(data["data"])
            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                break
            except Exception as e:
                logger.error(f"Hyperliquid WS error: {e}")
