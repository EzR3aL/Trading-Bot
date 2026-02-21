"""
Extra tests for BitgetWebSocket (src/websocket/bitget_ws.py).

Targets uncovered lines: 363-380, 385-398, 403-412, 439-440, 458-459,
490-491, 521-525, 550-554, 564-565, 579-584, 589-590.

Covers:
- _receive_loop_private: timeout, ConnectionClosed, generic error
- _receive_loop_public: timeout, ConnectionClosed, generic error
- _ping_loop: sends ping to both connections, handles errors
- _handle_private_message: generic exception in handler
- _handle_public_message: generic exception in handler
- _handle_ticker_update: parse error for malformed ticker data
- _handle_position_update: callback error, parse error
- _handle_order_update: callback error, parse error
- _reconnect: disconnect callback error, re-subscribe channels,
  reconnect callback error
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
# _receive_loop_private
# ---------------------------------------------------------------------------

async def test_receive_loop_private_timeout_continues():
    """Private receive loop continues on TimeoutError."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    mock_private = make_mock_ws()
    ws._ws_private = mock_private

    call_count = 0

    async def recv_side():
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            ws._running = False
        raise asyncio.TimeoutError()

    mock_private.recv = AsyncMock(side_effect=recv_side)

    await ws._receive_loop_private()
    assert call_count >= 3


async def test_receive_loop_private_connection_closed_triggers_reconnect():
    """Private receive loop calls _reconnect on ConnectionClosed."""
    from src.websocket.bitget_ws import BitgetWebSocket
    from websockets.exceptions import ConnectionClosed

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(side_effect=ConnectionClosed(None, None))
    ws._ws_private = mock_private

    with patch.object(ws, "_reconnect", new_callable=AsyncMock) as mock_reconnect:
        await ws._receive_loop_private()
        mock_reconnect.assert_awaited_once()


async def test_receive_loop_private_connection_closed_no_reconnect_when_stopped():
    """Private receive loop does NOT reconnect when _running is False."""
    from src.websocket.bitget_ws import BitgetWebSocket
    from websockets.exceptions import ConnectionClosed

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = False  # Already stopping
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(side_effect=ConnectionClosed(None, None))
    ws._ws_private = mock_private

    with patch.object(ws, "_reconnect", new_callable=AsyncMock) as mock_reconnect:
        await ws._receive_loop_private()
        mock_reconnect.assert_not_awaited()


async def test_receive_loop_private_generic_error_handled():
    """Private receive loop handles generic exceptions without crashing."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    mock_private = make_mock_ws()
    call_count = 0

    async def recv_side():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("unexpected error")
        ws._running = False
        raise asyncio.TimeoutError()

    mock_private.recv = AsyncMock(side_effect=recv_side)
    ws._ws_private = mock_private

    await ws._receive_loop_private()
    assert call_count >= 2


async def test_receive_loop_private_processes_message():
    """Private receive loop calls _handle_private_message on valid recv."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    mock_private = make_mock_ws()
    call_count = 0

    async def recv_side():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "pong"
        ws._running = False
        raise asyncio.TimeoutError()

    mock_private.recv = AsyncMock(side_effect=recv_side)
    ws._ws_private = mock_private

    with patch.object(ws, "_handle_private_message", new_callable=AsyncMock) as mock_handler:
        await ws._receive_loop_private()
        mock_handler.assert_awaited_once_with("pong")


# ---------------------------------------------------------------------------
# _receive_loop_public
# ---------------------------------------------------------------------------

async def test_receive_loop_public_timeout_continues():
    """Public receive loop continues on TimeoutError."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    mock_public = make_mock_ws()
    ws._ws_public = mock_public

    call_count = 0

    async def recv_side():
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            ws._running = False
        raise asyncio.TimeoutError()

    mock_public.recv = AsyncMock(side_effect=recv_side)

    await ws._receive_loop_public()
    assert call_count >= 3


async def test_receive_loop_public_connection_closed_breaks():
    """Public receive loop breaks on ConnectionClosed."""
    from src.websocket.bitget_ws import BitgetWebSocket
    from websockets.exceptions import ConnectionClosed

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    mock_public = make_mock_ws()
    mock_public.recv = AsyncMock(side_effect=ConnectionClosed(None, None))
    ws._ws_public = mock_public

    await ws._receive_loop_public()
    # Should exit cleanly without calling _reconnect (public loop does not reconnect)


async def test_receive_loop_public_generic_error_handled():
    """Public receive loop handles generic exceptions without crashing."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    mock_public = make_mock_ws()
    call_count = 0

    async def recv_side():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("public error")
        ws._running = False
        raise asyncio.TimeoutError()

    mock_public.recv = AsyncMock(side_effect=recv_side)
    ws._ws_public = mock_public

    await ws._receive_loop_public()
    assert call_count >= 2


async def test_receive_loop_public_processes_message():
    """Public receive loop calls _handle_public_message on valid recv."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    mock_public = make_mock_ws()
    call_count = 0

    async def recv_side():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "pong"
        ws._running = False
        raise asyncio.TimeoutError()

    mock_public.recv = AsyncMock(side_effect=recv_side)
    ws._ws_public = mock_public

    with patch.object(ws, "_handle_public_message", new_callable=AsyncMock) as mock_handler:
        await ws._receive_loop_public()
        mock_handler.assert_awaited_once_with("pong")


# ---------------------------------------------------------------------------
# _ping_loop
# ---------------------------------------------------------------------------

async def test_ping_loop_sends_to_both_connections():
    """Ping loop sends 'ping' to both private and public WebSockets."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    ws._state.connected = True
    mock_private = make_mock_ws()
    mock_public = make_mock_ws()
    ws._ws_private = mock_private
    ws._ws_public = mock_public

    iteration = 0

    async def fake_sleep(seconds):
        nonlocal iteration
        iteration += 1
        if iteration >= 2:
            ws._running = False

    with patch("src.websocket.bitget_ws.asyncio.sleep", side_effect=fake_sleep):
        await ws._ping_loop()

    mock_private.send.assert_awaited_with("ping")
    mock_public.send.assert_awaited_with("ping")


async def test_ping_loop_handles_send_error():
    """Ping loop continues even when send raises an exception."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    ws._state.connected = True
    mock_private = make_mock_ws()
    mock_private.send = AsyncMock(side_effect=Exception("send failed"))
    ws._ws_private = mock_private

    iteration = 0

    async def fake_sleep(seconds):
        nonlocal iteration
        iteration += 1
        if iteration >= 2:
            ws._running = False

    with patch("src.websocket.bitget_ws.asyncio.sleep", side_effect=fake_sleep):
        await ws._ping_loop()


async def test_ping_loop_skips_when_not_connected():
    """Ping loop skips sending when state is not connected."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    ws._state.connected = False  # Not connected
    mock_private = make_mock_ws()
    mock_public = make_mock_ws()
    ws._ws_private = mock_private
    ws._ws_public = mock_public

    iteration = 0

    async def fake_sleep(seconds):
        nonlocal iteration
        iteration += 1
        if iteration >= 2:
            ws._running = False

    with patch("src.websocket.bitget_ws.asyncio.sleep", side_effect=fake_sleep):
        await ws._ping_loop()

    # Private send is guarded by _state.connected, so it should not be called
    mock_private.send.assert_not_awaited()
    # Public send is not guarded by connected state, only by _ws_public existence
    mock_public.send.assert_awaited()


async def test_ping_loop_updates_last_ping():
    """Ping loop updates _state.last_ping after successful ping."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._running = True
    ws._state.connected = True
    mock_private = make_mock_ws()
    mock_public = make_mock_ws()
    ws._ws_private = mock_private
    ws._ws_public = mock_public

    assert ws._state.last_ping is None

    iteration = 0

    async def fake_sleep(seconds):
        nonlocal iteration
        iteration += 1
        if iteration >= 2:
            ws._running = False

    with patch("src.websocket.bitget_ws.asyncio.sleep", side_effect=fake_sleep):
        await ws._ping_loop()

    assert ws._state.last_ping is not None


# ---------------------------------------------------------------------------
# _handle_private_message: exception in handler
# ---------------------------------------------------------------------------

async def test_handle_private_message_generic_exception_in_inner_handler():
    """_handle_private_message catches exceptions from position handler."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")

    # Construct a message that will cause an exception in position parsing
    msg = json.dumps({
        "action": "update",
        "arg": {"channel": "positions"},
        "data": [{"instId": "BTCUSDT", "total": "not_a_number"}],
    })

    # Should not raise; the inner exception is caught
    await ws._handle_private_message(msg)


async def test_handle_private_message_outer_exception():
    """_handle_private_message outer except catches exceptions from handler method."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")

    # Patch _handle_position_update to raise an exception that bubbles
    # past the inner try/except
    with patch.object(ws, "_handle_position_update", new_callable=AsyncMock,
                      side_effect=RuntimeError("outer handler crash")):
        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "positions"},
            "data": [{"instId": "BTCUSDT"}],
        })
        # Should not raise; caught by outer except Exception
        await ws._handle_private_message(msg)


# ---------------------------------------------------------------------------
# _handle_public_message: exception in handler
# ---------------------------------------------------------------------------

async def test_handle_public_message_generic_exception_in_inner_handler():
    """_handle_public_message catches exceptions from ticker handler."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")

    # A message with valid JSON but ticker data that causes parse error
    msg = json.dumps({
        "action": "update",
        "arg": {"channel": "ticker"},
        "data": [{"instId": "BTCUSDT", "last": "not_a_float"}],
    })

    # Should not raise
    await ws._handle_public_message(msg)


async def test_handle_public_message_outer_exception():
    """_handle_public_message outer except catches exceptions from handler method."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")

    # Patch _handle_ticker_update to raise an exception that bubbles
    # past the inner try/except
    with patch.object(ws, "_handle_ticker_update", new_callable=AsyncMock,
                      side_effect=RuntimeError("outer handler crash")):
        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "ticker"},
            "data": [{"instId": "BTCUSDT"}],
        })
        # Should not raise; caught by outer except Exception
        await ws._handle_public_message(msg)


# ---------------------------------------------------------------------------
# _handle_ticker_update: parse error
# ---------------------------------------------------------------------------

async def test_handle_ticker_update_parse_error():
    """_handle_ticker_update handles malformed ticker data gracefully."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")

    # Data with invalid numeric fields
    data_list = [{"instId": "BTCUSDT", "last": "invalid_price"}]
    # Should not raise
    await ws._handle_ticker_update(data_list)
    # BTCUSDT should not be in cache due to parse error
    assert "BTCUSDT" not in ws._latest_ticks


# ---------------------------------------------------------------------------
# _handle_position_update: callback error, parse error
# ---------------------------------------------------------------------------

async def test_handle_position_update_callback_error():
    """Position callback error is caught and does not crash the handler."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws.on_position_update = MagicMock(side_effect=RuntimeError("callback crash"))

    data_list = [{
        "instId": "BTCUSDT",
        "holdSide": "long",
        "total": "1.0",
        "openPriceAvg": "50000",
        "markPrice": "51000",
        "unrealizedPL": "500",
        "marginMode": "crossed",
        "leverage": "10",
    }]

    await ws._handle_position_update(data_list)
    # Position should still be cached despite callback error
    assert "BTCUSDT" in ws._positions


async def test_handle_position_update_async_callback_error():
    """Async position callback error is caught and does not crash."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws.on_position_update = AsyncMock(side_effect=RuntimeError("async crash"))

    data_list = [{
        "instId": "ETHUSDT",
        "holdSide": "short",
        "total": "2.0",
        "openPriceAvg": "3000",
        "markPrice": "2900",
        "unrealizedPL": "200",
        "marginMode": "isolated",
        "leverage": "5",
    }]

    await ws._handle_position_update(data_list)
    assert "ETHUSDT" in ws._positions


async def test_handle_position_update_parse_error():
    """_handle_position_update handles malformed position data gracefully."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")

    data_list = [{"instId": "BTCUSDT", "total": "not_a_number"}]
    await ws._handle_position_update(data_list)
    assert "BTCUSDT" not in ws._positions


# ---------------------------------------------------------------------------
# _handle_order_update: callback error, parse error
# ---------------------------------------------------------------------------

async def test_handle_order_update_callback_error():
    """Order callback error is caught and does not crash the handler."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws.on_order_update = MagicMock(side_effect=RuntimeError("order cb crash"))

    data_list = [{
        "orderId": "order123",
        "instId": "BTCUSDT",
        "side": "buy",
        "orderType": "market",
        "status": "filled",
        "price": "50000",
        "size": "0.1",
        "accFillSz": "0.1",
        "avgPx": "50010",
    }]

    await ws._handle_order_update(data_list)


async def test_handle_order_update_async_callback_error():
    """Async order callback error is caught and does not crash."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws.on_order_update = AsyncMock(side_effect=RuntimeError("async order crash"))

    data_list = [{
        "orderId": "order456",
        "instId": "ETHUSDT",
        "side": "sell",
        "orderType": "limit",
        "status": "new",
        "price": "3000",
        "size": "0.5",
        "accFillSz": "0",
        "avgPx": "0",
    }]

    await ws._handle_order_update(data_list)


async def test_handle_order_update_parse_error():
    """_handle_order_update handles malformed order data gracefully."""
    from src.websocket.bitget_ws import BitgetWebSocket

    ws = BitgetWebSocket(api_key="key", api_secret="secret")

    # Missing required numeric fields will cause a ValueError
    data_list = [{"orderId": "o1", "price": "not_a_number"}]
    await ws._handle_order_update(data_list)


# ---------------------------------------------------------------------------
# _reconnect: disconnect callback error, re-subscribe, reconnect callback error
# ---------------------------------------------------------------------------

@patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_disconnect_callback_error_handled(mock_connect, mock_sleep):
    """_reconnect continues even if on_disconnect callback raises."""
    from src.websocket.bitget_ws import BitgetWebSocket

    mock_public = make_mock_ws()
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(return_value=json.dumps({
        "event": "login", "code": "0"
    }))
    mock_connect.side_effect = [mock_public, mock_private]

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws.on_disconnect = MagicMock(side_effect=RuntimeError("disconnect cb crash"))

    await ws._reconnect()

    assert ws._state.reconnect_count == 1
    await ws.disconnect()


@patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_reconnect_callback_error_handled(mock_connect, mock_sleep):
    """_reconnect continues even if on_reconnect callback raises."""
    from src.websocket.bitget_ws import BitgetWebSocket

    mock_public = make_mock_ws()
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(return_value=json.dumps({
        "event": "login", "code": "0"
    }))
    mock_connect.side_effect = [mock_public, mock_private]

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws.on_reconnect = MagicMock(side_effect=RuntimeError("reconnect cb crash"))

    await ws._reconnect()

    assert ws._state.reconnect_count == 1
    await ws.disconnect()


@patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_resubscribes_positions(mock_connect, mock_sleep):
    """_reconnect re-subscribes to position channels."""
    from src.websocket.bitget_ws import BitgetWebSocket

    mock_public = make_mock_ws()
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(return_value=json.dumps({
        "event": "login", "code": "0"
    }))
    mock_connect.side_effect = [mock_public, mock_private]

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._state.subscribed_channels = [{"type": "positions"}]

    with patch.object(ws, "subscribe_positions", new_callable=AsyncMock) as mock_sub:
        await ws._reconnect()
        mock_sub.assert_awaited_once()

    await ws.disconnect()


@patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_resubscribes_orders(mock_connect, mock_sleep):
    """_reconnect re-subscribes to order channels."""
    from src.websocket.bitget_ws import BitgetWebSocket

    mock_public = make_mock_ws()
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(return_value=json.dumps({
        "event": "login", "code": "0"
    }))
    mock_connect.side_effect = [mock_public, mock_private]

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._state.subscribed_channels = [{"type": "orders"}]

    with patch.object(ws, "subscribe_orders", new_callable=AsyncMock) as mock_sub:
        await ws._reconnect()
        mock_sub.assert_awaited_once()

    await ws.disconnect()


@patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_resubscribes_ticker(mock_connect, mock_sleep):
    """_reconnect re-subscribes to ticker channels with correct symbols."""
    from src.websocket.bitget_ws import BitgetWebSocket

    mock_public = make_mock_ws()
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(return_value=json.dumps({
        "event": "login", "code": "0"
    }))
    mock_connect.side_effect = [mock_public, mock_private]

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._state.subscribed_channels = [
        {"type": "ticker", "symbols": ["BTCUSDT", "ETHUSDT"]}
    ]

    with patch.object(ws, "subscribe_ticker", new_callable=AsyncMock) as mock_sub:
        await ws._reconnect()
        mock_sub.assert_awaited_once_with(["BTCUSDT", "ETHUSDT"])

    await ws.disconnect()


@patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_resubscribes_all_channel_types(mock_connect, mock_sleep):
    """_reconnect re-subscribes to all channel types."""
    from src.websocket.bitget_ws import BitgetWebSocket

    mock_public = make_mock_ws()
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(return_value=json.dumps({
        "event": "login", "code": "0"
    }))
    mock_connect.side_effect = [mock_public, mock_private]

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws._state.subscribed_channels = [
        {"type": "positions"},
        {"type": "orders"},
        {"type": "ticker", "symbols": ["BTCUSDT"]},
    ]

    with patch.object(ws, "subscribe_positions", new_callable=AsyncMock) as mock_pos, \
         patch.object(ws, "subscribe_orders", new_callable=AsyncMock) as mock_ord, \
         patch.object(ws, "subscribe_ticker", new_callable=AsyncMock) as mock_tick:
        await ws._reconnect()
        mock_pos.assert_awaited_once()
        mock_ord.assert_awaited_once()
        mock_tick.assert_awaited_once_with(["BTCUSDT"])

    await ws.disconnect()


@patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_no_disconnect_callback(mock_connect, mock_sleep):
    """_reconnect works when on_disconnect is not set."""
    from src.websocket.bitget_ws import BitgetWebSocket

    mock_public = make_mock_ws()
    mock_private = make_mock_ws()
    mock_private.recv = AsyncMock(return_value=json.dumps({
        "event": "login", "code": "0"
    }))
    mock_connect.side_effect = [mock_public, mock_private]

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    ws.on_disconnect = None
    ws.on_reconnect = None

    await ws._reconnect()
    assert ws._state.reconnect_count == 1

    await ws.disconnect()


@patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
@patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
async def test_reconnect_exponential_backoff(mock_connect, mock_sleep):
    """_reconnect uses exponential backoff delays."""
    from src.websocket.bitget_ws import BitgetWebSocket

    mock_connect.side_effect = Exception("connection refused")

    ws = BitgetWebSocket(api_key="key", api_secret="secret")
    await ws._reconnect()

    # Check sleep was called with increasing delays: 1, 2, 4, 8, 16
    sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
    assert sleep_calls == [1.0, 2.0, 4.0, 8.0, 16.0]
