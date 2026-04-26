"""Bitget push-mode WebSocket client for the RiskStateManager (#216).

Subscribes to the ``orders-algo`` private channel so the RSM learns
about plan-trigger / fill / close events without polling. Each parsed
frame is normalized to the canonical event shape expected by
:meth:`RiskStateManager.on_exchange_event`:

``{"event_type": "plan_triggered" | "order_filled" | "position_closed",
   "payload": {"symbol": "...", "raw": <original bitget data>}}``

The auth flow mirrors :mod:`src.exchanges.bitget.websocket` — an HMAC
login frame is sent immediately after connect using the same secret the
REST client signs with. We do NOT share the REST session; this module
owns its own ``websockets`` connection.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from src.exchanges.bitget.constants import (
    PRODUCT_TYPE_USDT,
    WS_PRIVATE_URL,
    WS_PRIVATE_URL_DEMO,
)
from src.exchanges.websockets.base import (
    EventCallback,
    ExchangeWebSocketClient,
    ReconnectCallback,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Server sends "pong" string frames in response to "ping". Treat them as
# heartbeats, not events.
_HEARTBEAT_FRAMES = {"pong", "ping"}

# How long to wait for the login response before giving up on auth.
_LOGIN_TIMEOUT_SECONDS = 10.0

# Receive-side timeout — if Bitget goes silent for this long we bail out
# so the base-class reconnect loop can redial. Matches the 30s cap.
_RECV_TIMEOUT_SECONDS = 35.0


class BitgetWebSocketClient(ExchangeWebSocketClient):
    """Subscribe to Bitget ``orders-algo`` → RSM events.

    Parameters
    ----------
    user_id, exchange, on_event, on_reconnect:
        See :class:`ExchangeWebSocketClient`.
    api_key, api_secret, passphrase:
        Credentials for the private channel login. Never logged.
    demo_mode:
        Selects the WS host: ``True`` dials ``wspap.bitget.com`` (paper
        trading), ``False`` dials ``ws.bitget.com`` (live). Live credentials
        are rejected on the demo host and vice versa with error 30017 —
        the REST ``paptrading`` header does NOT apply to WS (#357).
    ws_url:
        Explicit URL override (tests + one-off routing). Takes precedence
        over ``demo_mode`` when set.
    """

    def __init__(
        self,
        *,
        user_id: int,
        api_key: str,
        api_secret: str,
        passphrase: str,
        on_event: EventCallback,
        on_reconnect: Optional[ReconnectCallback] = None,
        demo_mode: bool = False,
        ws_url: Optional[str] = None,
    ) -> None:
        super().__init__(
            user_id=user_id,
            exchange="bitget",
            on_event=on_event,
            on_reconnect=on_reconnect,
        )
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._demo_mode = demo_mode
        self._ws_url = ws_url or (WS_PRIVATE_URL_DEMO if demo_mode else WS_PRIVATE_URL)

    # ── Base-class transport hooks ─────────────────────────────────

    async def _connect_transport(self) -> Any:
        """Open the private websocket and complete the HMAC login handshake."""
        ws = await websockets.connect(
            self._ws_url,
            ping_interval=25,
            ping_timeout=10,
        )
        await self._authenticate(ws)
        return ws

    async def _subscribe(self) -> None:
        """Subscribe to ``orders-algo`` for every USDT-M contract (``default``)."""
        if self._transport is None:
            raise RuntimeError("bitget ws subscribe before connect")
        msg = {
            "op": "subscribe",
            "args": [
                {
                    "instType": PRODUCT_TYPE_USDT,
                    "channel": "orders-algo",
                    "instId": "default",
                }
            ],
        }
        await self._transport.send(json.dumps(msg))

    async def _read_once(self) -> Optional[str]:
        """Read one frame with a recv timeout.

        Returns the raw string; the base class passes it to
        :meth:`_parse_message`. Raises ``ConnectionClosed`` so the base
        class flips into reconnect.
        """
        if self._transport is None:
            raise ConnectionError("bitget ws read_once without transport")
        try:
            return await asyncio.wait_for(
                self._transport.recv(), timeout=_RECV_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as e:
            raise ConnectionError("bitget ws recv timeout") from e
        except ConnectionClosed as e:
            raise ConnectionError(f"bitget ws closed: {e}") from e

    def _parse_message(self, raw: Any) -> Optional[dict]:
        """Translate a raw Bitget ``orders-algo`` frame to canonical form.

        Returns ``None`` for heartbeats and subscribe-ack frames so the
        base class drops them silently.
        """
        if isinstance(raw, str) and raw in _HEARTBEAT_FRAMES:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None

        # Subscribe ack / login ack / error frames have no "data" list.
        items = data.get("data")
        if not isinstance(items, list) or not items:
            return None

        arg = data.get("arg") or {}
        channel = arg.get("channel", "")
        if channel != "orders-algo":
            return None

        # Bitget pushes one item per frame for orders-algo but the schema
        # is a list. We emit events for the FIRST item — the base class
        # will dispatch per frame, so a burst of N items still produces
        # N dispatches because Bitget sends one frame each.
        first = items[0]
        event_type = _classify_bitget_event(first)
        if event_type is None:
            return None
        symbol = first.get("instId") or first.get("symbol")
        if not symbol:
            return None
        return {
            "event_type": event_type,
            "payload": {
                "symbol": symbol,
                "raw": first,
            },
        }

    # ── Auth ──────────────────────────────────────────────────────

    async def _authenticate(self, ws: Any) -> None:
        """Send the HMAC login frame and wait for the ``event=login`` ack.

        Never logs the signature or secret. Raises on any non-success
        response so the caller can back off.
        """
        timestamp = str(int(time.time()))
        signature = self._generate_signature(timestamp)
        auth_msg = {
            "op": "login",
            "args": [
                {
                    "apiKey": self._api_key,
                    "passphrase": self._passphrase,
                    "timestamp": timestamp,
                    "sign": signature,
                }
            ],
        }
        await ws.send(json.dumps(auth_msg))
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=_LOGIN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as e:
            raise ConnectionError("bitget ws login timeout") from e
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as e:
            raise ConnectionError(f"bitget ws login: non-json response: {raw!r}") from e
        if data.get("event") == "login" and str(data.get("code")) == "0":
            logger.info(
                "ws.bitget.login_ok user=%s",
                self.user_id,
                extra={"event_type": "exchange_ws", "exchange": "bitget",
                       "user_id": self.user_id, "phase": "login"},
            )
            return
        # Do NOT log the auth message — may leak key/sign. Log only the
        # sanitized server response code/event.
        raise ConnectionError(
            f"bitget ws login failed: code={data.get('code')} event={data.get('event')}"
        )

    def _generate_signature(self, timestamp: str) -> str:
        """HMAC-SHA256 over ``{ts}GET/user/verify`` — Bitget v2 WS login.

        Matches ``src.exchanges.bitget.websocket`` so a single secret
        rotation covers both modules.
        """
        message = f"{timestamp}GET/user/verify"
        mac = hmac.new(
            self._api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()


# ── Event classification ────────────────────────────────────────────


def _classify_bitget_event(item: dict) -> Optional[str]:
    """Map a Bitget orders-algo item to one of the RSM event_types.

    Rules:
    * ``status == "executing"`` or ``"live"``            → ``plan_triggered``
    * ``status == "filled"``                             → ``order_filled``
    * ``status in {"closed", "not_trigger", "cancelled", "canceled"}``
      AND ``state == "closed"`` (position closed)        → ``position_closed``
    * Anything else (e.g. plan placement ack)            → ``None``
    """
    status = (item.get("status") or "").lower()
    state = (item.get("state") or "").lower()
    if status in {"executing", "live"}:
        return "plan_triggered"
    if status == "filled":
        return "order_filled"
    if state == "closed" or status == "closed":
        return "position_closed"
    return None


__all__ = ["BitgetWebSocketClient"]
