"""
Extra tests for BinanceWebSocket (src/websocket/binance_ws.py).

Targets uncovered lines: 184-185, 198-200, 207-209, 211, 240-241,
294-298, 323-324, 348, 360.

Covers:
- _receive_loop: last_message update, generic error with sleep
- _ping_loop: sends ping, handles exception, updates last_ping
- _handle_message: JSONDecodeError, generic exception
- _handle_mark_price: funding callback error, async funding callback error,
  parse error on malformed data
- _reconnect: reconnect callback error, on_reconnect not set
- subscribe: reconnects with merged symbols
- unsubscribe: reconnects with remaining, disconnects when none left
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def make_mock_ws():
    """Create a fully mocked websockets connection object."""
    ws = AsyncMock()
    ws.close = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock(side_effect=asyncio.TimeoutError)
    ws.ping = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# _receive_loop: updates last_message, generic error continues with sleep
# ---------------------------------------------------------------------------

async def test_receive_loop_updates_last_message():
    """Receive loop updates _state.last_message on successful message."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws._running = True
    mock_ws = make_mock_ws()
    ws._ws = mock_ws

    call_count = 0

    async def recv_side():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return json.dumps({"stream": "test", "data": {}})
        ws._running = False
        raise asyncio.TimeoutError()

    mock_ws.recv = AsyncMock(side_effect=recv_side)

    before = ws._state.last_message
    await ws._receive_loop()
    assert ws._state.last_message is not None
    assert ws._state.last_message != before


async def test_receive_loop_generic_error_sleeps_and_continues():
    """Receive loop sleeps for 1s on generic error and continues."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws._running = True
    mock_ws = make_mock_ws()
    ws._ws = mock_ws

    call_count = 0

    async def recv_side():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("unexpected error")
        ws._running = False
        raise asyncio.TimeoutError()

    mock_ws.recv = AsyncMock(side_effect=recv_side)

    with patch("src.websocket.binance_ws.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await ws._receive_loop()
        # Sleep(1) is called after the generic error
        mock_sleep.assert_awaited_once_with(1)


async def test_receive_loop_generic_error_not_sleeping_when_stopped():
    """Receive loop does NOT sleep if _running is False after error."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws._running = True
    mock_ws = make_mock_ws()
    ws._ws = mock_ws

    async def recv_side():
        ws._running = False
        raise RuntimeError("unexpected error")

    mock_ws.recv = AsyncMock(side_effect=recv_side)

    with patch("src.websocket.binance_ws.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await ws._receive_loop()
        mock_sleep.assert_not_awaited()


# ---------------------------------------------------------------------------
# _ping_loop: sends ping, handles exception, updates last_ping
# ---------------------------------------------------------------------------

async def test_ping_loop_sends_ping():
    """Ping loop sends a websocket ping."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws._running = True
    ws._state.connected = True
    mock_ws = make_mock_ws()
    ws._ws = mock_ws

    iteration = 0

    async def fake_sleep(seconds):
        nonlocal iteration
        iteration += 1
        if iteration >= 2:
            ws._running = False

    with patch("src.websocket.binance_ws.asyncio.sleep", side_effect=fake_sleep):
        await ws._ping_loop()

    mock_ws.ping.assert_awaited()


async def test_ping_loop_updates_last_ping():
    """Ping loop updates _state.last_ping."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws._running = True
    ws._state.connected = True
    mock_ws = make_mock_ws()
    ws._ws = mock_ws

    assert ws._state.last_ping is None

    iteration = 0

    async def fake_sleep(seconds):
        nonlocal iteration
        iteration += 1
        if iteration >= 2:
            ws._running = False

    with patch("src.websocket.binance_ws.asyncio.sleep", side_effect=fake_sleep):
        await ws._ping_loop()

    assert ws._state.last_ping is not None


async def test_ping_loop_handles_exception():
    """Ping loop continues when ws.ping raises an exception."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws._running = True
    ws._state.connected = True
    mock_ws = make_mock_ws()
    mock_ws.ping = AsyncMock(side_effect=Exception("ping failed"))
    ws._ws = mock_ws

    iteration = 0

    async def fake_sleep(seconds):
        nonlocal iteration
        iteration += 1
        if iteration >= 2:
            ws._running = False

    with patch("src.websocket.binance_ws.asyncio.sleep", side_effect=fake_sleep):
        await ws._ping_loop()


async def test_ping_loop_skips_when_not_connected():
    """Ping loop skips ping when state is not connected."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws._running = True
    ws._state.connected = False
    mock_ws = make_mock_ws()
    ws._ws = mock_ws

    iteration = 0

    async def fake_sleep(seconds):
        nonlocal iteration
        iteration += 1
        if iteration >= 2:
            ws._running = False

    with patch("src.websocket.binance_ws.asyncio.sleep", side_effect=fake_sleep):
        await ws._ping_loop()

    mock_ws.ping.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_message: JSONDecodeError, generic exception
# ---------------------------------------------------------------------------

async def test_handle_message_json_decode_error():
    """_handle_message catches JSONDecodeError on malformed JSON."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    # Should not raise
    await ws._handle_message("not valid json{{{")
    assert ws._latest_prices == {}


async def test_handle_message_generic_exception():
    """_handle_message catches generic exceptions in processing."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()

    # A message that will trigger a KeyError or similar in processing
    # by providing a valid stream format but with data that causes an error
    with patch.object(ws, "_handle_mark_price", new_callable=AsyncMock,
                      side_effect=RuntimeError("processing error")):
        msg = json.dumps({
            "stream": "btcusdt@markPrice@1s",
            "data": {"e": "markPriceUpdate", "s": "BTCUSDT"},
        })
        # Should not raise
        await ws._handle_message(msg)


# ---------------------------------------------------------------------------
# _handle_mark_price: funding callback error, async funding error, parse error
# ---------------------------------------------------------------------------

async def test_handle_mark_price_funding_callback_error():
    """Funding callback error is caught and does not crash the handler."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws.on_funding_update = MagicMock(side_effect=RuntimeError("funding cb crash"))

    data = {
        "s": "BTCUSDT",
        "p": "50000",
        "i": "49999",
        "r": "0.0005",
        "T": 1700000000000,
    }
    await ws._handle_mark_price(data)
    # Price should still be cached
    assert "BTCUSDT" in ws._latest_prices


async def test_handle_mark_price_async_funding_callback_error():
    """Async funding callback error is caught and does not crash."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws.on_funding_update = AsyncMock(side_effect=RuntimeError("async funding crash"))

    data = {
        "s": "ETHUSDT",
        "p": "3000",
        "i": "2999",
        "r": "0.0003",
        "T": 1700000000000,
    }
    await ws._handle_mark_price(data)
    assert "ETHUSDT" in ws._latest_prices


async def test_handle_mark_price_parse_error():
    """_handle_mark_price handles malformed numeric data gracefully."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()

    data = {
        "s": "BTCUSDT",
        "p": "not_a_number",
        "i": "invalid",
        "r": "bad",
        "T": "not_timestamp",
    }
    # Should not raise
    await ws._handle_mark_price(data)


async def test_handle_mark_price_async_price_callback_error():
    """Async price callback error is caught and does not crash."""
    from src.websocket.binance_ws import BinanceWebSocket

    ws = BinanceWebSocket()
    ws.on_price_update = AsyncMock(side_effect=RuntimeError("price cb crash"))

    data = {
        "s": "BTCUSDT",
        "p": "50000",
        "i": "49999",
        "r": "0",
        "T": 1700000000000,
    }
    await ws._handle_mark_price(data)
    assert "BTCUSDT" in ws._latest_prices


# ---------------------------------------------------------------------------
# _reconnect: callback errors, no callbacks
# ---------------------------------------------------------------------------

@patch("src.websocket.binance_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_reconnect_callback_error_handled(mock_connect, mock_sleep):
    """_reconnect continues even if on_reconnect callback raises."""
    from src.websocket.binance_ws import BinanceWebSocket

    mock_ws = make_mock_ws()
    mock_connect.return_value = mock_ws

    ws = BinanceWebSocket()
    ws._state.subscribed_symbols = ["BTCUSDT"]
    ws.on_disconnect = MagicMock()
    ws.on_reconnect = MagicMock(side_effect=RuntimeError("reconnect cb crash"))

    await ws._reconnect()

    assert ws._state.reconnect_count == 1
    await ws.disconnect()


@patch("src.websocket.binance_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_no_callbacks_set(mock_connect, mock_sleep):
    """_reconnect works when no callbacks are set."""
    from src.websocket.binance_ws import BinanceWebSocket

    mock_ws = make_mock_ws()
    mock_connect.return_value = mock_ws

    ws = BinanceWebSocket()
    ws._state.subscribed_symbols = ["BTCUSDT"]
    ws.on_disconnect = None
    ws.on_reconnect = None

    await ws._reconnect()

    assert ws._state.reconnect_count == 1
    await ws.disconnect()


@patch("src.websocket.binance_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_exponential_backoff(mock_connect, mock_sleep):
    """_reconnect uses exponential backoff: 1, 2, 4, 8, 16 seconds."""
    from src.websocket.binance_ws import BinanceWebSocket

    mock_connect.side_effect = Exception("connection refused")

    ws = BinanceWebSocket()
    ws._state.subscribed_symbols = ["BTCUSDT"]

    await ws._reconnect()

    sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
    assert sleep_calls == [1.0, 2.0, 4.0, 8.0, 16.0]


# ---------------------------------------------------------------------------
# subscribe: reconnects with merged symbols
# ---------------------------------------------------------------------------

@patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
async def test_subscribe_reconnects_with_new_symbols(mock_connect):
    """subscribe disconnects and reconnects with merged symbol list."""
    from src.websocket.binance_ws import BinanceWebSocket

    mock_ws = make_mock_ws()
    mock_connect.return_value = mock_ws

    ws = BinanceWebSocket()
    await ws.connect(symbols=["BTCUSDT"])

    # Now subscribe to a new symbol
    await ws.subscribe(["SOLUSDT"])

    # Should have connected twice (initial + re-subscribe)
    assert mock_connect.call_count == 2
    # Second connect URL should include both symbols
    second_url = mock_connect.call_args_list[1][0][0]
    assert "btcusdt@markPrice@1s" in second_url
    assert "solusdt@markPrice@1s" in second_url

    await ws.disconnect()


@patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
async def test_subscribe_no_new_symbols_is_noop(mock_connect):
    """subscribe with already subscribed symbols is a no-op."""
    from src.websocket.binance_ws import BinanceWebSocket

    mock_ws = make_mock_ws()
    mock_connect.return_value = mock_ws

    ws = BinanceWebSocket()
    await ws.connect(symbols=["BTCUSDT"])

    await ws.subscribe(["BTCUSDT"])

    # Only the initial connect call
    assert mock_connect.call_count == 1

    await ws.disconnect()


# ---------------------------------------------------------------------------
# unsubscribe: remaining or all
# ---------------------------------------------------------------------------

@patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
async def test_unsubscribe_with_remaining_symbols(mock_connect):
    """unsubscribe reconnects with remaining symbols when some are left."""
    from src.websocket.binance_ws import BinanceWebSocket

    mock_ws = make_mock_ws()
    mock_connect.return_value = mock_ws

    ws = BinanceWebSocket()
    await ws.connect(symbols=["BTCUSDT", "ETHUSDT"])

    await ws.unsubscribe(["ETHUSDT"])

    # Two connects: initial + reconnect with remaining
    assert mock_connect.call_count == 2

    await ws.disconnect()


@patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
async def test_unsubscribe_all_symbols_disconnects(mock_connect):
    """unsubscribe all symbols just disconnects."""
    from src.websocket.binance_ws import BinanceWebSocket

    mock_ws = make_mock_ws()
    mock_connect.return_value = mock_ws

    ws = BinanceWebSocket()
    await ws.connect(symbols=["BTCUSDT"])

    await ws.unsubscribe(["BTCUSDT"])

    # Should be disconnected
    assert ws._state.connected is False
    assert ws._ws is None
