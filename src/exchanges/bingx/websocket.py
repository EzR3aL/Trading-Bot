"""
BingX WebSocket adapter implementing ExchangeWebSocket ABC.

BingX uses a listenKey mechanism for private channels:
1. Create listenKey via REST POST /openApi/user/auth/userDataStream
2. Connect to WS URL with ?listenKey={key} — all private events auto-push
3. Refresh listenKey every 25 min (valid 60 min)

Messages are gzip-compressed. Server sends "Ping", client responds "Pong".
"""

import asyncio
import gzip
import json
import time
from typing import Callable, Dict, List, Optional

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed

from src.exchanges.base import ExchangeWebSocket
from src.observability.metrics import EXCHANGE_WEBSOCKET_CONNECTED
from src.exchanges.bingx.constants import (
    BASE_URL,
    ENDPOINTS,
    TESTNET_URL,
    WS_PRIVATE_URL,
    WS_PRIVATE_URL_VST,
    WS_PUBLIC_URL,
    WS_PUBLIC_URL_VST,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ListenKey refresh interval (25 minutes)
LISTEN_KEY_REFRESH_INTERVAL = 25 * 60


class BingXWebSocket(ExchangeWebSocket):
    """BingX Perpetual Swap WebSocket client implementing ExchangeWebSocket ABC."""

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
        self._tasks: List[asyncio.Task] = []
        self._callbacks: Dict[str, Callable] = {}
        self._listen_key: Optional[str] = None
        self._rest_base = TESTNET_URL if demo_mode else BASE_URL
        self._ws_public_url = WS_PUBLIC_URL_VST if demo_mode else WS_PUBLIC_URL
        self._ws_private_url = WS_PRIVATE_URL_VST if demo_mode else WS_PRIVATE_URL

    async def _create_listen_key(self) -> Optional[str]:
        """Create a listenKey via REST API for private WebSocket auth."""
        import hashlib
        import hmac
        from urllib.parse import urlencode

        params = {"timestamp": str(int(time.time() * 1000))}
        query = urlencode(sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        url = f"{self._rest_base}{ENDPOINTS['listen_key']}?{query}&signature={signature}"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers={"X-BX-APIKEY": self.api_key}
            ) as resp:
                data = await resp.json()
                listen_key = data.get("listenKey") or data.get("data", {}).get("listenKey")
                if listen_key:
                    logger.info("BingX listenKey created")
                    return listen_key
                logger.warning("Failed to create BingX listenKey: %s", data)
                return None

    async def _refresh_listen_key(self) -> bool:
        """Extend the listenKey validity (PUT request)."""
        import hashlib
        import hmac
        from urllib.parse import urlencode

        params = {
            "listenKey": self._listen_key,
            "timestamp": str(int(time.time() * 1000)),
        }
        query = urlencode(sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        url = f"{self._rest_base}{ENDPOINTS['listen_key']}?{query}&signature={signature}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url, headers={"X-BX-APIKEY": self.api_key}
                ) as resp:
                    if resp.status == 200:
                        return True
        except Exception as e:
            logger.warning("Failed to refresh BingX listenKey: %s", e)
        return False

    async def connect(self) -> None:
        self._ws_public = await websockets.connect(
            self._ws_public_url, ping_interval=None,
        )
        logger.info("Connected to BingX public WebSocket")

        if self.api_key:
            self._listen_key = await self._create_listen_key()
            if self._listen_key:
                private_url = f"{self._ws_private_url}?listenKey={self._listen_key}"
                self._ws_private = await websockets.connect(
                    private_url, ping_interval=None,
                )
                logger.info("Connected to BingX private WebSocket")

        self._connected = True
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange="bingx").set(1)
        self._running = True

        self._tasks.append(asyncio.create_task(self._receive_loop(self._ws_public, "public")))
        if self._ws_private:
            self._tasks.append(asyncio.create_task(self._receive_loop(self._ws_private, "private")))
        self._tasks.append(asyncio.create_task(self._ping_loop()))
        if self._listen_key:
            self._tasks.append(asyncio.create_task(self._listen_key_refresh_loop()))

    async def subscribe_positions(self, symbols: List[str], callback: Callable) -> None:
        # Private events auto-push with listenKey — no subscription needed
        self._callbacks["ACCOUNT_UPDATE"] = callback

    async def subscribe_orders(self, callback: Callable) -> None:
        # Private events auto-push with listenKey — no subscription needed
        self._callbacks["ORDER_TRADE_UPDATE"] = callback

    async def subscribe_ticker(self, symbols: List[str], callback: Callable) -> None:
        if not self._ws_public:
            return
        self._callbacks["ticker"] = callback
        for symbol in symbols:
            msg = {
                "id": f"ticker_{symbol}_{int(time.time())}",
                "reqType": "sub",
                "dataType": f"{symbol}@ticker",
            }
            await self._ws_public.send(json.dumps(msg))

    async def disconnect(self) -> None:
        self._running = False
        self._connected = False
        EXCHANGE_WEBSOCKET_CONNECTED.labels(exchange="bingx").set(0)
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

    def _decompress(self, raw: bytes) -> str:
        """Decompress gzip message from BingX."""
        try:
            if isinstance(raw, bytes) and raw[:2] == b"\x1f\x8b":
                return gzip.decompress(raw).decode("utf-8")
            return raw.decode("utf-8") if isinstance(raw, bytes) else raw
        except Exception:
            return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)

    async def _receive_loop(self, ws, label: str):
        while self._running and ws:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                text = self._decompress(raw)

                # Handle ping/pong (BingX sends compressed "Ping")
                if text.strip() == "Ping":
                    await ws.send("Pong")
                    continue

                data = json.loads(text)

                # Private events (ACCOUNT_UPDATE, ORDER_TRADE_UPDATE)
                event_type = data.get("e", "")
                if event_type and event_type in self._callbacks:
                    cb = self._callbacks[event_type]
                    if asyncio.iscoroutinefunction(cb):
                        await cb(data)
                    else:
                        cb(data)
                    continue

                # Public events (ticker, depth, etc.)
                data_type = data.get("dataType", "")
                if "@ticker" in data_type and "ticker" in self._callbacks:
                    payload = data.get("data")
                    if payload:
                        cb = self._callbacks["ticker"]
                        if asyncio.iscoroutinefunction(cb):
                            await cb(payload)
                        else:
                            cb(payload)

            except asyncio.TimeoutError:
                continue
            except ConnectionClosed:
                logger.warning("BingX %s WebSocket disconnected", label)
                break
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error("BingX %s WS error: %s", label, e)

    async def _ping_loop(self):
        while self._running:
            await asyncio.sleep(25)
            try:
                if self._ws_public:
                    await self._ws_public.send("Ping")
                if self._ws_private:
                    await self._ws_private.send("Ping")
            except Exception as e:
                logger.debug("BingX heartbeat failed: %s", e)

    async def _listen_key_refresh_loop(self):
        """Refresh listenKey every 25 minutes to keep private WS alive."""
        while self._running and self._listen_key:
            await asyncio.sleep(LISTEN_KEY_REFRESH_INTERVAL)
            try:
                if await self._refresh_listen_key():
                    logger.debug("BingX listenKey refreshed")
                else:
                    logger.warning("BingX listenKey refresh failed, recreating")
                    self._listen_key = await self._create_listen_key()
            except Exception as e:
                logger.warning("BingX listenKey refresh error: %s", e)
