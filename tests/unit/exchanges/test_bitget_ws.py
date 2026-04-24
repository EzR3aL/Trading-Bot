"""Unit tests for :class:`BitgetWebSocketClient` host selection (#357).

Verifies that ``demo_mode`` routes the private WS handshake to the right
host — ``wspap.bitget.com`` for demo, ``ws.bitget.com`` for live — and
that an explicit ``ws_url`` override wins over ``demo_mode``. Previously
the flag was stored but ignored, so demo users hit live WS and failed
login with code 30017.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bitget.constants import WS_PRIVATE_URL, WS_PRIVATE_URL_DEMO
from src.exchanges.websockets.bitget_ws import BitgetWebSocketClient


async def _noop_event(user_id, exchange, event_type, payload):  # pragma: no cover
    pass


def _make(**overrides) -> BitgetWebSocketClient:
    defaults = dict(
        user_id=1,
        api_key="k",
        api_secret="s",
        passphrase="p",
        on_event=_noop_event,
    )
    defaults.update(overrides)
    return BitgetWebSocketClient(**defaults)


def test_demo_mode_true_dials_demo_host():
    client = _make(demo_mode=True)
    assert client._ws_url == WS_PRIVATE_URL_DEMO
    assert "wspap.bitget.com" in client._ws_url


def test_demo_mode_false_dials_live_host():
    client = _make(demo_mode=False)
    assert client._ws_url == WS_PRIVATE_URL
    assert "wspap.bitget.com" not in client._ws_url


def test_default_is_live_host():
    client = _make()
    assert client._ws_url == WS_PRIVATE_URL


def test_explicit_ws_url_overrides_demo_mode():
    custom = "wss://example.test/ws"
    client = _make(demo_mode=True, ws_url=custom)
    assert client._ws_url == custom
