"""Live WebSocket integration tests — SKIPPED by default (#216).

These tests need real demo credentials and a reachable network. They
verify that the push-mode ``BitgetWebSocketClient`` and
``HyperliquidWebSocketClient`` clients speak the exchanges' protocols
correctly end-to-end:

* Login → subscribe → receive an actual ``orders-algo`` /
  ``orderUpdates`` frame after placing a TP/SL via the REST client.
* Reconnect behaviour when the connection is forcibly closed mid-session.
* Health counter progression in :class:`WebSocketManager.connected_counts`.

Enable by setting the env vars described in
``tests/integration/live/README.md`` and removing the module-level skip
once demo credentials are provisioned.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="needs demo credentials")


def test_bitget_ws_login_then_subscribe_receives_event() -> None:  # pragma: no cover
    """Placeholder: connect to Bitget demo, place TP via REST, expect WS event."""
    raise NotImplementedError


def test_hyperliquid_ws_subscribe_receives_trigger_update() -> None:  # pragma: no cover
    """Placeholder: connect to HL testnet, place TP trigger, expect orderUpdates event."""
    raise NotImplementedError


def test_ws_manager_reconnect_after_forced_drop() -> None:  # pragma: no cover
    """Placeholder: kill socket mid-session, assert reconcile sweep fires."""
    raise NotImplementedError
