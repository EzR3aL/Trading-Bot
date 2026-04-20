"""Exchange WebSocket clients for push-updating the RiskStateManager (#216).

This package contains the Phase-2 push-mode WebSocket infrastructure that
replaces the RSM reconcile polling loop with near-real-time events from
Bitget and Hyperliquid.

Public surface:

* :class:`ExchangeWebSocketClient` — abstract base with reconnect-with-
  exponential-backoff and the canonical ``on_exchange_event`` dispatch.
* :class:`BitgetWebSocketClient` — Bitget ``orders-algo`` subscriber.
* :class:`HyperliquidWebSocketClient` — Hyperliquid ``orderUpdates`` subscriber
  filtered for ``isTrigger=true``.

All clients are gated behind ``EXCHANGE_WEBSOCKETS_ENABLED`` (see
``src.bot.ws_manager``). Default-off means no behaviour change.
"""

from src.exchanges.websockets.base import ExchangeWebSocketClient
from src.exchanges.websockets.bitget_ws import BitgetWebSocketClient
from src.exchanges.websockets.hyperliquid_ws import HyperliquidWebSocketClient

__all__ = [
    "ExchangeWebSocketClient",
    "BitgetWebSocketClient",
    "HyperliquidWebSocketClient",
]
