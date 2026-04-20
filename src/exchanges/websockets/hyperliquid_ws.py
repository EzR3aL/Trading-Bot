"""Hyperliquid push-mode WebSocket client for the RiskStateManager (#216).

Hyperliquid does not run a raw WS we talk to directly — we use the
SDK-provided :class:`hyperliquid.info.Info` which opens a websocket
under the hood when ``skip_ws`` is false. We subscribe to
``{"type": "orderUpdates", "user": <wallet_address>}`` and filter for
trigger-order updates (``isTrigger=true``) because those are the only
events that map to RSM state changes (TP/SL/trailing on HL are all
trigger orders).

The SDK callback is synchronous — we marshal incoming updates onto our
own ``asyncio.Queue`` so the base-class ``run_forever`` loop can stay
async and respect the reconnect contract.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from src.exchanges.hyperliquid.constants import MAINNET_API_URL, TESTNET_API_URL
from src.exchanges.websockets.base import (
    EventCallback,
    ExchangeWebSocketClient,
    ReconnectCallback,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


class HyperliquidWebSocketClient(ExchangeWebSocketClient):
    """Subscribe to HL ``orderUpdates`` filtered for trigger orders.

    Parameters
    ----------
    user_id, on_event, on_reconnect:
        See :class:`ExchangeWebSocketClient`.
    wallet_address:
        The 0x-prefixed EOA the subscription is scoped to. Required —
        HL has no "all users" mode.
    mainnet:
        ``True`` → MAINNET_API_URL, ``False`` → TESTNET_API_URL.
    info_factory:
        Test-only override. When set, must return an object that
        implements ``subscribe(subscription, callback)`` and
        ``disconnect_websocket()``.
    """

    def __init__(
        self,
        *,
        user_id: int,
        wallet_address: str,
        on_event: EventCallback,
        on_reconnect: Optional[ReconnectCallback] = None,
        mainnet: bool = True,
        info_factory: Optional[Any] = None,
    ) -> None:
        super().__init__(
            user_id=user_id,
            exchange="hyperliquid",
            on_event=on_event,
            on_reconnect=on_reconnect,
        )
        if not wallet_address:
            raise ValueError("hyperliquid ws requires a wallet_address")
        self._wallet_address = wallet_address
        self._mainnet = mainnet
        self._info_factory = info_factory
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Base-class transport hooks ─────────────────────────────────

    async def _connect_transport(self) -> Any:
        """Construct an :class:`hyperliquid.info.Info` with an open WS.

        Captures the running loop so the SDK callback (which fires from
        its own thread) can hand messages back to us via
        ``call_soon_threadsafe`` → queue.
        """
        self._loop = asyncio.get_running_loop()
        if self._info_factory is not None:
            info = self._info_factory()
        else:
            # Imported lazily so unit tests that pass ``info_factory``
            # don't need the hyperliquid SDK installed.
            from hyperliquid.info import Info as HLInfo  # noqa: PLC0415

            base_url = MAINNET_API_URL if self._mainnet else TESTNET_API_URL
            info = HLInfo(base_url=base_url, skip_ws=False)
        return info

    async def _subscribe(self) -> None:
        """Register the ``orderUpdates`` subscription.

        The SDK's ``subscribe`` is synchronous and takes a
        ``subscription`` dict + a callable. Our callable shovels the
        message into the async queue so ``_read_once`` can pull it.
        """
        if self._transport is None:
            raise RuntimeError("hyperliquid ws subscribe before connect")
        subscription = {"type": "orderUpdates", "user": self._wallet_address}
        self._transport.subscribe(subscription, self._sdk_callback)

    async def _read_once(self) -> Optional[dict]:
        """Pull one message from the async queue.

        Returns the unwrapped message. Raises ``ConnectionError`` if
        the transport is gone.
        """
        if self._transport is None:
            raise ConnectionError("hyperliquid ws read_once without transport")
        return await self._queue.get()

    def _parse_message(self, raw: Any) -> Optional[dict]:
        """Classify a HL ``orderUpdates`` payload into a canonical event.

        HL delivers a list of order states per push. We emit one event
        per item that passes the ``isTrigger`` filter. The base class
        calls us once per list, so we flatten here and return the first
        qualifying item — subsequent items are dispatched via
        :meth:`_fanout_extra`.
        """
        if raw is None:
            return None
        # The SDK passes ``{"channel": "orderUpdates", "data": [...]}``.
        items: list
        if isinstance(raw, dict):
            channel = raw.get("channel")
            if channel not in (None, "orderUpdates"):
                return None
            items = raw.get("data") or []
        elif isinstance(raw, list):
            items = raw
        else:
            return None

        qualifying = [i for i in items if _is_trigger_item(i)]
        if not qualifying:
            return None

        # Queue any extras so they reach the RSM as separate events.
        for extra in qualifying[1:]:
            event = _hl_item_to_event(extra)
            if event is not None:
                self._fanout_extra(event)

        return _hl_item_to_event(qualifying[0])

    # ── SDK bridge ────────────────────────────────────────────────

    def _sdk_callback(self, message: Any) -> None:
        """Cross-thread bridge from the SDK's WS thread to our asyncio loop.

        The SDK fires this from its own socket thread — we can't call
        ``queue.put_nowait`` directly because that manipulates asyncio
        primitives from the wrong loop. ``call_soon_threadsafe`` is
        the correct bridge.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._queue.put_nowait, message)
        except RuntimeError as e:  # loop already closing
            logger.debug(
                "ws.hl.queue_reject user=%s error=%s", self.user_id, e,
            )

    def _fanout_extra(self, event: dict) -> None:
        """Schedule a secondary dispatch for an extra trigger update.

        Scheduled on the event loop so it interleaves naturally with the
        primary dispatch. Errors are swallowed (caught by the base
        class's ``_handle_message`` inside the scheduled task).
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        event_type = event.get("event_type")
        payload = event.get("payload") or {}
        if not event_type:
            return
        loop.call_soon(
            lambda: asyncio.ensure_future(
                self._on_event(self.user_id, self.exchange, event_type, payload)
            )
        )

    async def _safe_close_transport(self) -> None:
        """HL's ``Info`` exposes ``disconnect_websocket`` rather than ``close``."""
        transport = self._transport
        self._transport = None
        if transport is None:
            return
        disconnect = getattr(transport, "disconnect_websocket", None)
        if disconnect is not None:
            try:
                result = disconnect()
                if asyncio.iscoroutine(result):
                    await result
                return
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    "ws.hl.disconnect_error user=%s error=%s", self.user_id, e,
                )
        # Fall back to the generic close path used by the base class.
        close = getattr(transport, "close", None)
        if close is not None:
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    "ws.hl.close_error user=%s error=%s", self.user_id, e,
                )


# ── Module-level helpers ────────────────────────────────────────────


def _is_trigger_item(item: Any) -> bool:
    """True if the HL order-update refers to a trigger (TP/SL/trailing).

    HL nests the trigger flag under ``order.isTrigger`` in the v2
    schema; older payloads expose it at the top level. Accept both.
    """
    if not isinstance(item, dict):
        return False
    if item.get("isTrigger") is True:
        return True
    order = item.get("order")
    if isinstance(order, dict) and order.get("isTrigger") is True:
        return True
    return False


def _hl_item_to_event(item: dict) -> Optional[dict]:
    """Map a HL order-update to the canonical RSM event shape.

    Status resolution:
    * ``status == "triggered"``          → ``plan_triggered``
    * ``status == "filled"``             → ``order_filled``
    * ``status in {"canceled", "rejected", "marginCanceled"}`` → drop
    * Everything else                    → None (dropped)
    """
    order = item.get("order") if isinstance(item.get("order"), dict) else item
    status = (item.get("status") or order.get("status") or "").lower()
    symbol = order.get("coin") or order.get("symbol") or item.get("symbol")
    if not symbol:
        return None
    if status == "triggered":
        event_type = "plan_triggered"
    elif status == "filled":
        event_type = "order_filled"
    else:
        return None
    return {
        "event_type": event_type,
        "payload": {
            "symbol": symbol,
            "raw": item,
        },
    }


__all__ = ["HyperliquidWebSocketClient"]
