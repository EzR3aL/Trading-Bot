"""
Comprehensive unit tests for all WebSocket modules.

Covers:
- src/websocket/binance_ws.py (BinanceWebSocket)
- src/websocket/bitget_ws.py (BitgetWebSocket)
- src/exchanges/bitget/websocket.py (BitgetExchangeWebSocket)
- src/exchanges/hyperliquid/websocket.py (HyperliquidWebSocket)
- src/exchanges/weex/websocket.py (WeexWebSocket)

Tests cover: connection lifecycle, message handling/parsing, subscription
management, heartbeat/ping-pong, error handling, callback invocation,
and authentication for private channels.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set env vars before any src imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# ---------------------------------------------------------------------------
# Helper: Create a mock WebSocket connection
# ---------------------------------------------------------------------------

def make_mock_ws():
    """Create a fully mocked websockets connection object."""
    ws = AsyncMock()
    ws.close = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock(side_effect=asyncio.TimeoutError)
    ws.ping = AsyncMock()
    return ws


# ===========================================================================
# SECTION 1: BinanceWebSocket (src/websocket/binance_ws.py)
# ===========================================================================

class TestBinanceWebSocketInit:
    """Test BinanceWebSocket initialisation and properties."""

    def test_init_default_state(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()

        assert ws._ws is None
        assert ws._state.connected is False
        assert ws._running is False
        assert ws._latest_prices == {}
        assert ws.on_price_update is None
        assert ws.on_funding_update is None
        assert ws.on_disconnect is None
        assert ws.on_reconnect is None

    def test_is_connected_false_when_no_ws(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        assert ws.is_connected is False

    def test_is_connected_false_when_state_disconnected(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        ws._ws = MagicMock()
        ws._state.connected = False
        assert ws.is_connected is False

    def test_is_connected_true(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        ws._ws = MagicMock()
        ws._state.connected = True
        assert ws.is_connected is True

    def test_get_price_returns_none_when_no_data(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        assert ws.get_price("BTCUSDT") is None

    def test_get_price_returns_cached_price(self):
        from src.websocket.binance_ws import BinanceWebSocket, MarketTick
        ws = BinanceWebSocket()
        tick = MarketTick(
            symbol="BTCUSDT", price=50000.0, mark_price=50000.0,
            index_price=49999.0, funding_rate=0.0001,
            next_funding_time=datetime.now(), timestamp=datetime.now(),
        )
        ws._latest_prices["BTCUSDT"] = tick
        assert ws.get_price("BTCUSDT") == 50000.0

    def test_get_funding_rate_returns_none_when_no_data(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        assert ws.get_funding_rate("BTCUSDT") is None

    def test_get_funding_rate_returns_cached_rate(self):
        from src.websocket.binance_ws import BinanceWebSocket, MarketTick
        ws = BinanceWebSocket()
        tick = MarketTick(
            symbol="BTCUSDT", price=50000.0, mark_price=50000.0,
            index_price=49999.0, funding_rate=0.0005,
            next_funding_time=datetime.now(), timestamp=datetime.now(),
        )
        ws._latest_prices["BTCUSDT"] = tick
        assert ws.get_funding_rate("BTCUSDT") == 0.0005

    def test_latest_prices_property(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        assert ws.latest_prices == {}


class TestBinanceWebSocketConnect:
    """Test BinanceWebSocket connect/disconnect lifecycle."""

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_connect_success_default_symbols(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        result = await ws.connect()

        assert result is True
        assert ws._state.connected is True
        assert ws._state.subscribed_symbols == ["BTCUSDT", "ETHUSDT"]
        assert ws._running is True

        # Verify URL includes both streams
        call_url = mock_connect.call_args[0][0]
        assert "btcusdt@markPrice@1s" in call_url
        assert "ethusdt@markPrice@1s" in call_url

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_connect_success_custom_symbols(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        result = await ws.connect(symbols=["SOLUSDT"])

        assert result is True
        assert ws._state.subscribed_symbols == ["SOLUSDT"]
        call_url = mock_connect.call_args[0][0]
        assert "solusdt@markPrice@1s" in call_url

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_connect_failure_returns_false(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_connect.side_effect = Exception("Connection refused")

        ws = BinanceWebSocket()
        result = await ws.connect()

        assert result is False
        assert ws._state.connected is False

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_disconnect_cleans_up(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        await ws.connect()
        await ws.disconnect()

        assert ws._running is False
        assert ws._state.connected is False
        assert ws._ws is None
        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_without_connect(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        # Should not raise
        await ws.disconnect()
        assert ws._running is False


class TestBinanceWebSocketMessageHandling:
    """Test BinanceWebSocket message parsing and callback invocation."""

    @pytest.mark.asyncio
    async def test_handle_message_combined_stream_mark_price(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()

        msg = json.dumps({
            "stream": "btcusdt@markPrice@1s",
            "data": {
                "e": "markPriceUpdate",
                "s": "BTCUSDT",
                "p": "50000.50",
                "i": "49999.00",
                "r": "0.00010000",
                "T": 1700000000000,
            },
        })

        await ws._handle_message(msg)

        assert "BTCUSDT" in ws._latest_prices
        tick = ws._latest_prices["BTCUSDT"]
        assert tick.price == 50000.50
        assert tick.mark_price == 50000.50
        assert tick.index_price == 49999.0
        assert tick.funding_rate == 0.0001

    @pytest.mark.asyncio
    async def test_handle_message_direct_format(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()

        msg = json.dumps({
            "e": "markPriceUpdate",
            "s": "ETHUSDT",
            "p": "3000.00",
            "i": "2999.00",
            "r": "0.00020000",
            "T": 1700000000000,
        })

        await ws._handle_message(msg)

        assert "ETHUSDT" in ws._latest_prices
        tick = ws._latest_prices["ETHUSDT"]
        assert tick.price == 3000.0

    @pytest.mark.asyncio
    async def test_handle_message_invalid_json(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        # Should not raise, just log
        await ws._handle_message("not-json{{{")
        assert ws._latest_prices == {}

    @pytest.mark.asyncio
    async def test_handle_mark_price_empty_symbol_skipped(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        await ws._handle_mark_price({"s": "", "p": "100", "i": "100", "r": "0", "T": 0})
        assert ws._latest_prices == {}

    @pytest.mark.asyncio
    async def test_handle_mark_price_calls_sync_price_callback(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        callback = MagicMock()
        ws.on_price_update = callback

        data = {"s": "BTCUSDT", "p": "50000", "i": "49999", "r": "0.0001", "T": 1700000000000}
        await ws._handle_mark_price(data)

        callback.assert_called_once()
        tick = callback.call_args[0][0]
        assert tick.symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_handle_mark_price_calls_async_price_callback(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        callback = AsyncMock()
        ws.on_price_update = callback

        data = {"s": "BTCUSDT", "p": "50000", "i": "49999", "r": "0.0001", "T": 1700000000000}
        await ws._handle_mark_price(data)

        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_mark_price_calls_funding_callback(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        funding_cb = MagicMock()
        ws.on_funding_update = funding_cb

        data = {"s": "BTCUSDT", "p": "50000", "i": "49999", "r": "0.0005", "T": 1700000000000}
        await ws._handle_mark_price(data)

        funding_cb.assert_called_once_with("BTCUSDT", 0.0005)

    @pytest.mark.asyncio
    async def test_handle_mark_price_calls_async_funding_callback(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        funding_cb = AsyncMock()
        ws.on_funding_update = funding_cb

        data = {"s": "BTCUSDT", "p": "50000", "i": "49999", "r": "0.0005", "T": 1700000000000}
        await ws._handle_mark_price(data)

        funding_cb.assert_awaited_once_with("BTCUSDT", 0.0005)

    @pytest.mark.asyncio
    async def test_handle_mark_price_zero_funding_skips_callback(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        funding_cb = MagicMock()
        ws.on_funding_update = funding_cb

        data = {"s": "BTCUSDT", "p": "50000", "i": "49999", "r": "0", "T": 1700000000000}
        await ws._handle_mark_price(data)

        funding_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_mark_price_callback_error_handled(self):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        ws.on_price_update = MagicMock(side_effect=ValueError("callback error"))

        data = {"s": "BTCUSDT", "p": "50000", "i": "49999", "r": "0.0001", "T": 1700000000000}
        # Should not raise
        await ws._handle_mark_price(data)
        assert "BTCUSDT" in ws._latest_prices


class TestBinanceWebSocketSubscription:
    """Test subscribe/unsubscribe logic for BinanceWebSocket."""

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_subscribe_when_not_connected(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        ws = BinanceWebSocket()
        # Should not raise, just log warning
        await ws.subscribe(["SOLUSDT"])

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_subscribe_adds_new_symbols(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        await ws.connect(symbols=["BTCUSDT"])

        # Subscribe to new symbol - triggers reconnect
        await ws.subscribe(["ETHUSDT"])

        # Should have connected twice (initial + re-subscribe)
        assert mock_connect.call_count == 2

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_subscribe_already_subscribed_is_noop(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        await ws.connect(symbols=["BTCUSDT"])

        # Subscribe to same symbol - should be a no-op
        await ws.subscribe(["BTCUSDT"])

        # Only initial connect call
        assert mock_connect.call_count == 1

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_unsubscribe_with_remaining(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        await ws.connect(symbols=["BTCUSDT", "ETHUSDT"])
        await ws.unsubscribe(["ETHUSDT"])

        # Should have reconnected with remaining symbols
        assert mock_connect.call_count == 2
        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_unsubscribe_all_disconnects(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        await ws.connect(symbols=["BTCUSDT"])
        await ws.unsubscribe(["BTCUSDT"])

        assert ws._state.connected is False


class TestBinanceWebSocketReconnect:
    """Test reconnection logic for BinanceWebSocket."""

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_reconnect_success_calls_callbacks(self, mock_connect, mock_sleep):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        ws._state.subscribed_symbols = ["BTCUSDT"]
        disconnect_cb = MagicMock()
        reconnect_cb = MagicMock()
        ws.on_disconnect = disconnect_cb
        ws.on_reconnect = reconnect_cb

        await ws._reconnect()

        disconnect_cb.assert_called_once()
        reconnect_cb.assert_called_once()
        assert ws._state.reconnect_count == 1

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_reconnect_all_retries_fail(self, mock_connect, mock_sleep):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_connect.side_effect = Exception("Connection refused")

        ws = BinanceWebSocket()
        ws._state.subscribed_symbols = ["BTCUSDT"]

        await ws._reconnect()

        # 5 retries attempted (connect returns False each time via exception)
        assert mock_connect.call_count == 5

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_reconnect_disconnect_callback_error_handled(self, mock_connect, mock_sleep):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        ws._state.subscribed_symbols = ["BTCUSDT"]
        ws.on_disconnect = MagicMock(side_effect=RuntimeError("callback crash"))

        # Should not raise despite callback error
        await ws._reconnect()
        assert ws._state.reconnect_count == 1

        await ws.disconnect()


class TestBinanceWebSocketReceiveLoop:
    """Test the receive loop for BinanceWebSocket."""

    @pytest.mark.asyncio
    @patch("src.websocket.binance_ws.websockets.connect", new_callable=AsyncMock)
    async def test_receive_loop_timeout_continues(self, mock_connect):
        from src.websocket.binance_ws import BinanceWebSocket
        mock_ws = make_mock_ws()
        call_count = 0

        async def recv_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()
            raise asyncio.TimeoutError()

        mock_ws.recv = AsyncMock(side_effect=recv_side_effect)
        mock_connect.return_value = mock_ws

        ws = BinanceWebSocket()
        await ws.connect()
        # Wait briefly for loop to execute
        await asyncio.sleep(0.1)
        await ws.disconnect()

    @pytest.mark.asyncio
    async def test_receive_loop_connection_closed_triggers_reconnect(self):
        from src.websocket.binance_ws import BinanceWebSocket
        from websockets.exceptions import ConnectionClosed

        ws = BinanceWebSocket()
        ws._running = True
        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=ConnectionClosed(None, None))
        ws._ws = mock_ws

        with patch.object(ws, "_reconnect", new_callable=AsyncMock) as mock_reconnect:
            await ws._receive_loop()
            mock_reconnect.assert_awaited_once()


class TestBinanceMarketTickDataclass:
    """Test MarketTick and BinanceWebSocketState dataclasses."""

    def test_market_tick_creation(self):
        from src.websocket.binance_ws import MarketTick
        tick = MarketTick(
            symbol="BTCUSDT", price=50000.0, mark_price=50001.0,
            index_price=49999.0, funding_rate=0.0001,
            next_funding_time=datetime(2024, 1, 1),
            timestamp=datetime(2024, 1, 1),
        )
        assert tick.symbol == "BTCUSDT"
        assert tick.price == 50000.0

    def test_binance_ws_state_defaults(self):
        from src.websocket.binance_ws import BinanceWebSocketState
        state = BinanceWebSocketState()
        assert state.connected is False
        assert state.last_ping is None
        assert state.last_message is None
        assert state.reconnect_count == 0
        assert state.subscribed_symbols == []


# ===========================================================================
# SECTION 2: BitgetWebSocket (src/websocket/bitget_ws.py)
# ===========================================================================

class TestBitgetWebSocketInit:
    """Test BitgetWebSocket initialisation and properties."""

    def test_init_requires_credentials(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        with pytest.raises(ValueError, match="requires explicit"):
            BitgetWebSocket()

    def test_init_requires_api_secret(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        with pytest.raises(ValueError, match="requires explicit"):
            BitgetWebSocket(api_key="key")

    def test_init_with_credentials(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret", passphrase="pass")
        assert ws.api_key == "key"
        assert ws.api_secret == "secret"
        assert ws.passphrase == "pass"
        assert ws.is_connected is False
        assert ws.is_authenticated is False

    def test_init_passphrase_defaults_empty(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        assert ws.passphrase == ""

    def test_get_price_returns_none_when_empty(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        assert ws.get_price("BTCUSDT") is None

    def test_get_price_returns_cached(self):
        from src.websocket.bitget_ws import BitgetWebSocket, BitgetTick
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        ws._latest_ticks["BTCUSDT"] = BitgetTick(
            symbol="BTCUSDT", last_price=50000.0, mark_price=50001.0,
            best_bid=49999.0, best_ask=50001.0, volume_24h=1000000.0,
            timestamp=datetime.now(),
        )
        assert ws.get_price("BTCUSDT") == 50000.0

    def test_get_position_returns_none_when_empty(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        assert ws.get_position("BTCUSDT") is None


class TestBitgetWebSocketSignature:
    """Test signature generation for BitgetWebSocket."""

    def test_generate_signature_format(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="test_secret")
        sig = ws._generate_signature("1700000000")
        # The result should be a base64-encoded string
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_generate_signature_deterministic(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="test_secret")
        sig1 = ws._generate_signature("1700000000")
        sig2 = ws._generate_signature("1700000000")
        assert sig1 == sig2

    def test_generate_signature_changes_with_timestamp(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="test_secret")
        sig1 = ws._generate_signature("1700000000")
        sig2 = ws._generate_signature("1700000001")
        assert sig1 != sig2


class TestBitgetWebSocketConnect:
    """Test BitgetWebSocket connect/disconnect lifecycle."""

    @pytest.mark.asyncio
    @patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
    async def test_connect_success(self, mock_connect):
        from src.websocket.bitget_ws import BitgetWebSocket

        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        # Auth response
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "0"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = BitgetWebSocket(api_key="key", api_secret="secret", passphrase="pass")
        result = await ws.connect()

        assert result is True
        assert ws.is_connected is True
        assert ws.is_authenticated is True

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
    async def test_connect_auth_failure(self, mock_connect):
        from src.websocket.bitget_ws import BitgetWebSocket

        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "40034", "msg": "Invalid API key"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = BitgetWebSocket(api_key="bad_key", api_secret="secret")
        result = await ws.connect()

        assert result is False
        assert ws.is_authenticated is False

    @pytest.mark.asyncio
    @patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
    async def test_connect_exception_returns_false(self, mock_connect):
        from src.websocket.bitget_ws import BitgetWebSocket
        mock_connect.side_effect = Exception("Network error")

        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        result = await ws.connect()

        assert result is False
        assert ws._state.connected is False

    @pytest.mark.asyncio
    @patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
    async def test_disconnect_cleans_up(self, mock_connect):
        from src.websocket.bitget_ws import BitgetWebSocket

        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "0"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        await ws.connect()
        await ws.disconnect()

        assert ws._running is False
        assert ws._state.connected is False
        assert ws._state.authenticated is False
        assert ws._ws_private is None
        assert ws._ws_public is None

    @pytest.mark.asyncio
    @patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
    async def test_authenticate_timeout_returns_false(self, mock_connect):
        from src.websocket.bitget_ws import BitgetWebSocket

        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_connect.side_effect = [mock_public, mock_private]

        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        result = await ws.connect()

        assert result is False


class TestBitgetWebSocketSubscription:
    """Test subscription methods for BitgetWebSocket."""

    @pytest.mark.asyncio
    async def test_subscribe_ticker_when_not_connected(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        # Should not raise, just log
        await ws.subscribe_ticker(["BTCUSDT"])

    @pytest.mark.asyncio
    async def test_subscribe_ticker_sends_message(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        mock_public = make_mock_ws()
        ws._ws_public = mock_public

        await ws.subscribe_ticker(["BTCUSDT", "ETHUSDT"])

        mock_public.send.assert_awaited_once()
        sent = json.loads(mock_public.send.call_args[0][0])
        assert sent["op"] == "subscribe"
        assert len(sent["args"]) == 2
        assert sent["args"][0]["channel"] == "ticker"

    @pytest.mark.asyncio
    async def test_subscribe_positions_when_not_authenticated(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        # Should not raise, just log
        await ws.subscribe_positions()

    @pytest.mark.asyncio
    async def test_subscribe_positions_sends_message(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        mock_private = make_mock_ws()
        ws._ws_private = mock_private
        ws._state.authenticated = True

        await ws.subscribe_positions()

        mock_private.send.assert_awaited_once()
        sent = json.loads(mock_private.send.call_args[0][0])
        assert sent["op"] == "subscribe"
        assert sent["args"][0]["channel"] == "positions"

    @pytest.mark.asyncio
    async def test_subscribe_orders_when_not_authenticated(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        await ws.subscribe_orders()

    @pytest.mark.asyncio
    async def test_subscribe_orders_sends_message(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        mock_private = make_mock_ws()
        ws._ws_private = mock_private
        ws._state.authenticated = True

        await ws.subscribe_orders()

        sent = json.loads(mock_private.send.call_args[0][0])
        assert sent["args"][0]["channel"] == "orders"


class TestBitgetWebSocketPrivateMessages:
    """Test private message handling for BitgetWebSocket."""

    @pytest.mark.asyncio
    async def test_handle_pong_message(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        # Should return early without error
        await ws._handle_private_message("pong")

    @pytest.mark.asyncio
    async def test_handle_subscribe_confirmation(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        msg = json.dumps({"event": "subscribe", "arg": {"channel": "positions"}})
        await ws._handle_private_message(msg)

    @pytest.mark.asyncio
    async def test_handle_position_update(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        callback = MagicMock()
        ws.on_position_update = callback

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "positions"},
            "data": [{
                "instId": "BTCUSDT",
                "holdSide": "long",
                "total": "0.5",
                "openPriceAvg": "50000",
                "markPrice": "51000",
                "unrealizedPL": "500",
                "marginMode": "crossed",
                "leverage": "10",
            }],
        })

        await ws._handle_private_message(msg)

        assert "BTCUSDT" in ws._positions
        callback.assert_called_once()
        pos = callback.call_args[0][0]
        assert pos.symbol == "BTCUSDT"
        assert pos.side == "long"
        assert pos.size == 0.5
        assert pos.leverage == 10

    @pytest.mark.asyncio
    async def test_handle_position_update_async_callback(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        callback = AsyncMock()
        ws.on_position_update = callback

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "positions"},
            "data": [{"instId": "BTCUSDT", "holdSide": "long", "total": "1",
                       "openPriceAvg": "50000", "markPrice": "50500",
                       "unrealizedPL": "250", "marginMode": "crossed", "leverage": "5"}],
        })

        await ws._handle_private_message(msg)
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_order_update(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        callback = MagicMock()
        ws.on_order_update = callback

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "orders"},
            "data": [{
                "orderId": "order123",
                "instId": "BTCUSDT",
                "side": "buy",
                "orderType": "market",
                "status": "filled",
                "price": "50000",
                "size": "0.1",
                "accFillSz": "0.1",
                "avgPx": "50010",
            }],
        })

        await ws._handle_private_message(msg)
        callback.assert_called_once()
        order = callback.call_args[0][0]
        assert order.order_id == "order123"
        assert order.status == "filled"

    @pytest.mark.asyncio
    async def test_handle_order_update_async_callback(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        callback = AsyncMock()
        ws.on_order_update = callback

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "orders"},
            "data": [{"orderId": "o1", "instId": "BTCUSDT", "side": "buy",
                       "orderType": "market", "status": "filled",
                       "price": "50000", "size": "0.1", "accFillSz": "0.1", "avgPx": "50010"}],
        })
        await ws._handle_private_message(msg)
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_private_invalid_json(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        # Should not raise
        await ws._handle_private_message("invalid json{{{")

    @pytest.mark.asyncio
    async def test_handle_position_empty_instid_skipped(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        callback = MagicMock()
        ws.on_position_update = callback

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "positions"},
            "data": [{"instId": "", "holdSide": "long", "total": "1",
                       "openPriceAvg": "50000", "markPrice": "50000",
                       "unrealizedPL": "0", "leverage": "1"}],
        })
        await ws._handle_private_message(msg)
        callback.assert_not_called()


class TestBitgetWebSocketPublicMessages:
    """Test public message handling for BitgetWebSocket."""

    @pytest.mark.asyncio
    async def test_handle_public_pong(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        # Should return without error
        await ws._handle_public_message("pong")

    @pytest.mark.asyncio
    async def test_handle_ticker_update(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        callback = MagicMock()
        ws.on_tick_update = callback

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "ticker"},
            "data": [{
                "instId": "BTCUSDT",
                "last": "50000",
                "markPrice": "50001",
                "bidPr": "49999",
                "askPr": "50001",
                "vol24h": "1000000",
            }],
        })

        await ws._handle_public_message(msg)

        assert "BTCUSDT" in ws._latest_ticks
        callback.assert_called_once()
        tick = callback.call_args[0][0]
        assert tick.symbol == "BTCUSDT"
        assert tick.last_price == 50000.0

    @pytest.mark.asyncio
    async def test_handle_ticker_update_async_callback(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        callback = AsyncMock()
        ws.on_tick_update = callback

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "ticker"},
            "data": [{"instId": "ETHUSDT", "last": "3000", "bidPr": "2999",
                       "askPr": "3001", "vol24h": "500000"}],
        })
        await ws._handle_public_message(msg)
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_ticker_empty_instid_skipped(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        callback = MagicMock()
        ws.on_tick_update = callback

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "ticker"},
            "data": [{"instId": "", "last": "100"}],
        })
        await ws._handle_public_message(msg)
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_public_invalid_json(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        # Should not raise
        await ws._handle_public_message("invalid{{{")

    @pytest.mark.asyncio
    async def test_handle_ticker_callback_error_handled(self):
        from src.websocket.bitget_ws import BitgetWebSocket
        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        ws.on_tick_update = MagicMock(side_effect=RuntimeError("cb crash"))

        msg = json.dumps({
            "action": "update",
            "arg": {"channel": "ticker"},
            "data": [{"instId": "BTCUSDT", "last": "50000", "bidPr": "49999",
                       "askPr": "50001", "vol24h": "1000"}],
        })
        # Should not raise
        await ws._handle_public_message(msg)
        assert "BTCUSDT" in ws._latest_ticks


class TestBitgetWebSocketReconnect:
    """Test reconnection logic for BitgetWebSocket."""

    @pytest.mark.asyncio
    @patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
    async def test_reconnect_success(self, mock_connect, mock_sleep):
        from src.websocket.bitget_ws import BitgetWebSocket
        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "0"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        disconnect_cb = MagicMock()
        reconnect_cb = MagicMock()
        ws.on_disconnect = disconnect_cb
        ws.on_reconnect = reconnect_cb

        await ws._reconnect()

        disconnect_cb.assert_called_once()
        reconnect_cb.assert_called_once()
        assert ws._state.reconnect_count == 1

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.websocket.bitget_ws.asyncio.sleep", new_callable=AsyncMock)
    @patch("src.websocket.bitget_ws.websockets.connect", new_callable=AsyncMock)
    async def test_reconnect_failure_all_retries(self, mock_connect, mock_sleep):
        from src.websocket.bitget_ws import BitgetWebSocket
        mock_connect.side_effect = Exception("refused")

        ws = BitgetWebSocket(api_key="key", api_secret="secret")
        await ws._reconnect()

        # connect() catches the exception and returns False, so websockets.connect
        # is called once per attempt (fails on the first ws.connect call each time)
        assert mock_connect.call_count == 5


class TestBitgetWebSocketDataclasses:
    """Test BitgetWebSocket dataclasses."""

    def test_bitget_tick_creation(self):
        from src.websocket.bitget_ws import BitgetTick
        tick = BitgetTick(
            symbol="BTCUSDT", last_price=50000.0, mark_price=50001.0,
            best_bid=49999.0, best_ask=50001.0, volume_24h=1e6,
            timestamp=datetime.now(),
        )
        assert tick.symbol == "BTCUSDT"

    def test_position_update_creation(self):
        from src.websocket.bitget_ws import PositionUpdate
        pos = PositionUpdate(
            symbol="BTCUSDT", side="long", size=1.0, entry_price=50000.0,
            mark_price=51000.0, unrealized_pnl=1000.0,
            margin_mode="crossed", leverage=10, timestamp=datetime.now(),
        )
        assert pos.leverage == 10

    def test_order_update_creation(self):
        from src.websocket.bitget_ws import OrderUpdate
        order = OrderUpdate(
            order_id="123", symbol="BTCUSDT", side="buy", order_type="market",
            status="filled", price=50000.0, size=0.1, filled_size=0.1,
            avg_fill_price=50010.0, timestamp=datetime.now(),
        )
        assert order.order_id == "123"

    def test_bitget_ws_state_defaults(self):
        from src.websocket.bitget_ws import BitgetWebSocketState
        state = BitgetWebSocketState()
        assert state.connected is False
        assert state.authenticated is False
        assert state.subscribed_channels == []


# ===========================================================================
# SECTION 3: BitgetExchangeWebSocket (src/exchanges/bitget/websocket.py)
# ===========================================================================

class TestBitgetExchangeWebSocketInit:
    """Test BitgetExchangeWebSocket initialisation."""

    def test_init_defaults(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        assert ws.api_key == ""
        assert ws.api_secret == ""
        assert ws.passphrase == ""
        assert ws.demo_mode is True
        assert ws._running is False
        assert ws._authenticated is False
        assert ws._tasks == []
        assert ws._callbacks == {}

    def test_init_with_credentials(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket(api_key="k", api_secret="s", passphrase="p")
        assert ws.api_key == "k"
        assert ws.api_secret == "s"
        assert ws.passphrase == "p"


class TestBitgetExchangeWebSocketSignature:
    """Test signature generation for BitgetExchangeWebSocket."""

    def test_signature_deterministic(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket(api_key="k", api_secret="test_secret")
        s1 = ws._generate_signature("1700000000")
        s2 = ws._generate_signature("1700000000")
        assert s1 == s2

    def test_signature_changes_with_timestamp(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket(api_key="k", api_secret="test_secret")
        s1 = ws._generate_signature("1700000000")
        s2 = ws._generate_signature("1700000001")
        assert s1 != s2


class TestBitgetExchangeWebSocketConnect:
    """Test BitgetExchangeWebSocket connect/disconnect."""

    @pytest.mark.asyncio
    @patch("src.exchanges.bitget.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_connect_public_only(self, mock_connect):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BitgetExchangeWebSocket()  # No api_key, public only
        await ws.connect()

        assert ws._connected is True
        assert ws._running is True
        assert ws._ws_public is mock_ws
        assert ws._ws_private is None

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.exchanges.bitget.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_connect_with_auth(self, mock_connect):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "0"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = BitgetExchangeWebSocket(api_key="key", api_secret="secret", passphrase="pass")
        await ws.connect()

        assert ws._connected is True
        assert ws._authenticated is True
        assert ws._ws_private is mock_private

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.exchanges.bitget.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_connect_auth_failure_raises(self, mock_connect):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "40034"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = BitgetExchangeWebSocket(api_key="bad", api_secret="secret")
        with pytest.raises(ConnectionError, match="auth failed"):
            await ws.connect()

    @pytest.mark.asyncio
    @patch("src.exchanges.bitget.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_disconnect_cleans_up(self, mock_connect):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = BitgetExchangeWebSocket()
        await ws.connect()
        await ws.disconnect()

        assert ws._connected is False
        assert ws._running is False
        assert ws._ws_public is None
        assert ws._ws_private is None
        assert ws._tasks == []


class TestBitgetExchangeWebSocketSubscriptions:
    """Test subscription methods for BitgetExchangeWebSocket."""

    @pytest.mark.asyncio
    async def test_subscribe_ticker_sends_message(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        mock_public = make_mock_ws()
        ws._ws_public = mock_public
        callback = MagicMock()

        await ws.subscribe_ticker(["BTCUSDT"], callback)

        assert ws._callbacks["ticker"] is callback
        mock_public.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subscribe_ticker_no_public_ws_is_noop(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        await ws.subscribe_ticker(["BTCUSDT"], MagicMock())
        assert "ticker" not in ws._callbacks

    @pytest.mark.asyncio
    async def test_subscribe_positions_sends_message(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket(api_key="k", api_secret="s")
        mock_private = make_mock_ws()
        ws._ws_private = mock_private
        ws._authenticated = True
        callback = MagicMock()

        await ws.subscribe_positions(["BTCUSDT"], callback)

        assert ws._callbacks["positions"] is callback
        sent = json.loads(mock_private.send.call_args[0][0])
        assert sent["args"][0]["channel"] == "positions"

    @pytest.mark.asyncio
    async def test_subscribe_positions_not_authenticated_is_noop(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        await ws.subscribe_positions(["BTCUSDT"], MagicMock())
        assert "positions" not in ws._callbacks

    @pytest.mark.asyncio
    async def test_subscribe_orders_sends_message(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket(api_key="k", api_secret="s")
        mock_private = make_mock_ws()
        ws._ws_private = mock_private
        ws._authenticated = True
        callback = MagicMock()

        await ws.subscribe_orders(callback)

        assert ws._callbacks["orders"] is callback
        sent = json.loads(mock_private.send.call_args[0][0])
        assert sent["args"][0]["channel"] == "orders"

    @pytest.mark.asyncio
    async def test_subscribe_orders_not_authenticated_is_noop(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        await ws.subscribe_orders(MagicMock())
        assert "orders" not in ws._callbacks


class TestBitgetExchangeWebSocketReceive:
    """Test receive loops for BitgetExchangeWebSocket."""

    @pytest.mark.asyncio
    async def test_receive_public_pong_skipped(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        ws._running = True
        mock_ws = make_mock_ws()
        call_count = 0

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "pong"
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws_public = mock_ws

        await ws._receive_public()

    @pytest.mark.asyncio
    async def test_receive_public_ticker_callback_invoked(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        ws._running = True
        callback = MagicMock()
        ws._callbacks["ticker"] = callback

        call_count = 0
        ticker_msg = json.dumps({
            "arg": {"channel": "ticker"},
            "data": [{"instId": "BTCUSDT", "last": "50000"}],
        })

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ticker_msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws_public = mock_ws

        await ws._receive_public()
        callback.assert_called_once_with({"instId": "BTCUSDT", "last": "50000"})

    @pytest.mark.asyncio
    async def test_receive_public_connection_closed_breaks(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        from websockets.exceptions import ConnectionClosed
        ws = BitgetExchangeWebSocket()
        ws._running = True
        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=ConnectionClosed(None, None))
        ws._ws_public = mock_ws

        await ws._receive_public()
        # Should exit cleanly

    @pytest.mark.asyncio
    async def test_receive_private_invokes_async_callback(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        ws._running = True
        callback = AsyncMock()
        ws._callbacks["positions"] = callback

        call_count = 0
        pos_msg = json.dumps({
            "arg": {"channel": "positions"},
            "data": [{"instId": "BTCUSDT", "holdSide": "long"}],
        })

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return pos_msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws_private = mock_ws

        await ws._receive_private()
        callback.assert_awaited_once_with({"instId": "BTCUSDT", "holdSide": "long"})

    @pytest.mark.asyncio
    async def test_receive_private_pong_skipped(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        ws._running = True
        call_count = 0

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "pong"
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws_private = mock_ws

        await ws._receive_private()

    @pytest.mark.asyncio
    async def test_receive_private_connection_closed_breaks(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        from websockets.exceptions import ConnectionClosed
        ws = BitgetExchangeWebSocket()
        ws._running = True
        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=ConnectionClosed(None, None))
        ws._ws_private = mock_ws

        await ws._receive_private()


class TestBitgetExchangeWebSocketPing:
    """Test ping loop for BitgetExchangeWebSocket."""

    @pytest.mark.asyncio
    async def test_ping_loop_sends_to_both(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        ws._running = True
        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        ws._ws_public = mock_public
        ws._ws_private = mock_private

        iteration = 0

        original_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                ws._running = False
            await original_sleep(0)

        with patch("src.exchanges.bitget.websocket.asyncio.sleep", side_effect=fake_sleep):
            await ws._ping_loop()

        mock_public.send.assert_awaited_with("ping")
        mock_private.send.assert_awaited_with("ping")

    @pytest.mark.asyncio
    async def test_ping_loop_handles_exception(self):
        from src.exchanges.bitget.websocket import BitgetExchangeWebSocket
        ws = BitgetExchangeWebSocket()
        ws._running = True
        mock_public = make_mock_ws()
        mock_public.send = AsyncMock(side_effect=Exception("send failed"))
        ws._ws_public = mock_public

        iteration = 0

        async def fake_sleep(seconds):
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                ws._running = False

        with patch("src.exchanges.bitget.websocket.asyncio.sleep", side_effect=fake_sleep):
            # Should not raise
            await ws._ping_loop()


# ===========================================================================
# SECTION 4: HyperliquidWebSocket (src/exchanges/hyperliquid/websocket.py)
# ===========================================================================

class TestHyperliquidWebSocketInit:
    """Test HyperliquidWebSocket initialisation."""

    @patch("src.exchanges.hyperliquid.websocket.WS_TESTNET_URL", "wss://testnet.test/ws")
    @patch("src.exchanges.hyperliquid.websocket.WS_URL", "wss://main.test/ws")
    def test_init_demo_mode(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket(api_key="0xWallet", demo_mode=True)
        assert ws.wallet_address == "0xWallet"
        assert ws.ws_url == "wss://testnet.test/ws"
        assert ws._running is False
        assert ws._callbacks == {}

    @patch("src.exchanges.hyperliquid.websocket.WS_TESTNET_URL", "wss://testnet.test/ws")
    @patch("src.exchanges.hyperliquid.websocket.WS_URL", "wss://main.test/ws")
    def test_init_production_mode(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket(api_key="0xWallet", demo_mode=False)
        assert ws.ws_url == "wss://main.test/ws"


class TestHyperliquidWebSocketConnect:
    """Test HyperliquidWebSocket connect/disconnect."""

    @pytest.mark.asyncio
    @patch("src.exchanges.hyperliquid.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_connect_success(self, mock_connect):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = HyperliquidWebSocket(api_key="0xWallet")
        await ws.connect()

        assert ws._connected is True
        assert ws._running is True
        assert ws._ws is mock_ws

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.exchanges.hyperliquid.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_disconnect_cleans_up(self, mock_connect):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = HyperliquidWebSocket()
        await ws.connect()
        await ws.disconnect()

        assert ws._connected is False
        assert ws._running is False
        mock_ws.close.assert_awaited_once()


class TestHyperliquidWebSocketSubscriptions:
    """Test subscription methods for HyperliquidWebSocket."""

    @pytest.mark.asyncio
    async def test_subscribe_positions_sends_correct_message(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket(api_key="0xABC")
        mock_ws = make_mock_ws()
        ws._ws = mock_ws
        callback = MagicMock()

        await ws.subscribe_positions(["BTC"], callback)

        assert ws._callbacks["userEvents"] is callback
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["method"] == "subscribe"
        assert sent["subscription"]["type"] == "userEvents"
        assert sent["subscription"]["user"] == "0xABC"

    @pytest.mark.asyncio
    async def test_subscribe_positions_no_ws_is_noop(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        await ws.subscribe_positions(["BTC"], MagicMock())
        assert "userEvents" not in ws._callbacks

    @pytest.mark.asyncio
    async def test_subscribe_orders_sends_correct_message(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket(api_key="0xABC")
        mock_ws = make_mock_ws()
        ws._ws = mock_ws
        callback = MagicMock()

        await ws.subscribe_orders(callback)

        assert ws._callbacks["userFills"] is callback
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["subscription"]["type"] == "userFills"

    @pytest.mark.asyncio
    async def test_subscribe_orders_no_ws_is_noop(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        await ws.subscribe_orders(MagicMock())
        assert "userFills" not in ws._callbacks

    @pytest.mark.asyncio
    async def test_subscribe_ticker_sends_correct_message(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        mock_ws = make_mock_ws()
        ws._ws = mock_ws
        callback = MagicMock()

        await ws.subscribe_ticker(["BTC"], callback)

        assert ws._callbacks["allMids"] is callback
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["subscription"]["type"] == "allMids"

    @pytest.mark.asyncio
    async def test_subscribe_ticker_no_ws_is_noop(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        await ws.subscribe_ticker(["BTC"], MagicMock())
        assert "allMids" not in ws._callbacks


class TestHyperliquidWebSocketReceive:
    """Test receive loop for HyperliquidWebSocket."""

    @pytest.mark.asyncio
    async def test_receive_invokes_sync_callback(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        ws._running = True
        callback = MagicMock()
        ws._callbacks["allMids"] = callback

        call_count = 0
        ticker_msg = json.dumps({
            "channel": "allMids",
            "data": {"mids": {"BTC": "50000"}},
        })

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ticker_msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws = mock_ws

        await ws._receive_loop()
        callback.assert_called_once_with({"mids": {"BTC": "50000"}})

    @pytest.mark.asyncio
    async def test_receive_invokes_async_callback(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        ws._running = True
        callback = AsyncMock()
        ws._callbacks["userEvents"] = callback

        call_count = 0
        event_msg = json.dumps({
            "channel": "userEvents",
            "data": [{"type": "position"}],
        })

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return event_msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws = mock_ws

        await ws._receive_loop()
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_receive_timeout_continues(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        ws._running = True
        call_count = 0

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws = mock_ws

        await ws._receive_loop()
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_receive_connection_closed_breaks(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        from websockets.exceptions import ConnectionClosed
        ws = HyperliquidWebSocket()
        ws._running = True
        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=ConnectionClosed(None, None))
        ws._ws = mock_ws

        await ws._receive_loop()
        # Should exit cleanly

    @pytest.mark.asyncio
    async def test_receive_no_matching_callback_silent(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        ws._running = True

        call_count = 0
        msg = json.dumps({"channel": "unknown", "data": {"foo": "bar"}})

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws = mock_ws

        await ws._receive_loop()
        # No callbacks registered, should not error

    @pytest.mark.asyncio
    async def test_receive_no_data_key_no_callback(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        ws._running = True
        callback = MagicMock()
        ws._callbacks["allMids"] = callback

        call_count = 0
        msg = json.dumps({"channel": "allMids"})  # no "data" key

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws = mock_ws

        await ws._receive_loop()
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_receive_generic_exception_handled(self):
        from src.exchanges.hyperliquid.websocket import HyperliquidWebSocket
        ws = HyperliquidWebSocket()
        ws._running = True
        call_count = 0

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("bad message")
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)
        ws._ws = mock_ws

        # Should not raise
        await ws._receive_loop()


# ===========================================================================
# SECTION 5: WeexWebSocket (src/exchanges/weex/websocket.py)
# ===========================================================================

class TestWeexWebSocketInit:
    """Test WeexWebSocket initialisation."""

    def test_init_defaults(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        assert ws.api_key == ""
        assert ws._running is False
        assert ws._authenticated is False
        assert ws._callbacks == {}

    def test_init_with_credentials(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket(api_key="k", api_secret="s", passphrase="p")
        assert ws.api_key == "k"
        assert ws.api_secret == "s"


class TestWeexWebSocketSignature:
    """Test signature generation for WeexWebSocket."""

    def test_signature_deterministic(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket(api_secret="test_secret")
        s1 = ws._generate_signature("1700000000")
        s2 = ws._generate_signature("1700000000")
        assert s1 == s2

    def test_signature_changes_with_timestamp(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket(api_secret="test_secret")
        s1 = ws._generate_signature("1700000000")
        s2 = ws._generate_signature("1700000001")
        assert s1 != s2


class TestWeexWebSocketConnect:
    """Test WeexWebSocket connect/disconnect."""

    @pytest.mark.asyncio
    @patch("src.exchanges.weex.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_connect_public_only(self, mock_connect):
        from src.exchanges.weex.websocket import WeexWebSocket
        mock_ws = make_mock_ws()
        mock_connect.return_value = mock_ws

        ws = WeexWebSocket()  # No api_key
        await ws.connect()

        assert ws._connected is True
        assert ws._running is True
        assert ws._ws_public is mock_ws
        assert ws._ws_private is None

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.exchanges.weex.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_connect_with_auth_success(self, mock_connect):
        from src.exchanges.weex.websocket import WeexWebSocket
        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "0"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = WeexWebSocket(api_key="key", api_secret="secret", passphrase="pass")
        await ws.connect()

        assert ws._connected is True
        assert ws._authenticated is True

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.exchanges.weex.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_connect_with_auth_failure(self, mock_connect):
        from src.exchanges.weex.websocket import WeexWebSocket
        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "40034"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = WeexWebSocket(api_key="bad", api_secret="secret")
        await ws.connect()

        assert ws._connected is True  # Still connected, just not authenticated
        assert ws._authenticated is False

        await ws.disconnect()

    @pytest.mark.asyncio
    @patch("src.exchanges.weex.websocket.websockets.connect", new_callable=AsyncMock)
    async def test_disconnect_closes_both(self, mock_connect):
        from src.exchanges.weex.websocket import WeexWebSocket
        mock_public = make_mock_ws()
        mock_private = make_mock_ws()
        mock_private.recv = AsyncMock(return_value=json.dumps({
            "event": "login", "code": "0"
        }))
        mock_connect.side_effect = [mock_public, mock_private]

        ws = WeexWebSocket(api_key="key", api_secret="secret")
        await ws.connect()
        await ws.disconnect()

        assert ws._connected is False
        assert ws._running is False
        mock_public.close.assert_awaited_once()
        mock_private.close.assert_awaited_once()


class TestWeexWebSocketSubscriptions:
    """Test subscription methods for WeexWebSocket."""

    @pytest.mark.asyncio
    async def test_subscribe_positions_sends_message(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        mock_private = make_mock_ws()
        ws._ws_private = mock_private
        callback = MagicMock()

        await ws.subscribe_positions(["BTCUSDT"], callback)

        assert ws._callbacks["positions"] is callback
        sent = json.loads(mock_private.send.call_args[0][0])
        assert sent["op"] == "subscribe"
        assert sent["args"][0]["channel"] == "positions"

    @pytest.mark.asyncio
    async def test_subscribe_positions_no_private_is_noop(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        await ws.subscribe_positions(["BTCUSDT"], MagicMock())
        assert "positions" not in ws._callbacks

    @pytest.mark.asyncio
    async def test_subscribe_orders_sends_message(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        mock_private = make_mock_ws()
        ws._ws_private = mock_private
        callback = MagicMock()

        await ws.subscribe_orders(callback)

        assert ws._callbacks["orders"] is callback
        sent = json.loads(mock_private.send.call_args[0][0])
        assert sent["args"][0]["channel"] == "orders"

    @pytest.mark.asyncio
    async def test_subscribe_orders_no_private_is_noop(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        await ws.subscribe_orders(MagicMock())
        assert "orders" not in ws._callbacks

    @pytest.mark.asyncio
    async def test_subscribe_ticker_sends_message(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        mock_public = make_mock_ws()
        ws._ws_public = mock_public
        callback = MagicMock()

        await ws.subscribe_ticker(["BTCUSDT", "ETHUSDT"], callback)

        assert ws._callbacks["ticker"] is callback
        sent = json.loads(mock_public.send.call_args[0][0])
        assert sent["op"] == "subscribe"
        assert len(sent["args"]) == 2

    @pytest.mark.asyncio
    async def test_subscribe_ticker_no_public_is_noop(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        await ws.subscribe_ticker(["BTCUSDT"], MagicMock())
        assert "ticker" not in ws._callbacks


class TestWeexWebSocketReceive:
    """Test receive loop for WeexWebSocket."""

    @pytest.mark.asyncio
    async def test_receive_pong_skipped(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        ws._running = True
        call_count = 0

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "pong"
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)

        await ws._receive_loop(mock_ws, "public")

    @pytest.mark.asyncio
    async def test_receive_invokes_sync_callback(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        ws._running = True
        callback = MagicMock()
        ws._callbacks["ticker"] = callback

        call_count = 0
        msg = json.dumps({
            "arg": {"channel": "ticker"},
            "data": [{"instId": "BTCUSDT", "last": "50000"}],
        })

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)

        await ws._receive_loop(mock_ws, "public")
        callback.assert_called_once_with({"instId": "BTCUSDT", "last": "50000"})

    @pytest.mark.asyncio
    async def test_receive_invokes_async_callback(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        ws._running = True
        callback = AsyncMock()
        ws._callbacks["positions"] = callback

        call_count = 0
        msg = json.dumps({
            "arg": {"channel": "positions"},
            "data": [{"instId": "BTCUSDT", "holdSide": "long"}],
        })

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)

        await ws._receive_loop(mock_ws, "private")
        callback.assert_awaited_once_with({"instId": "BTCUSDT", "holdSide": "long"})

    @pytest.mark.asyncio
    async def test_receive_connection_closed_breaks(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        from websockets.exceptions import ConnectionClosed
        ws = WeexWebSocket()
        ws._running = True
        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=ConnectionClosed(None, None))

        await ws._receive_loop(mock_ws, "public")

    @pytest.mark.asyncio
    async def test_receive_timeout_continues(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        ws._running = True
        call_count = 0

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)

        await ws._receive_loop(mock_ws, "public")
        assert call_count >= 3

    @pytest.mark.asyncio
    async def test_receive_generic_error_handled(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        ws._running = True
        call_count = 0

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("unexpected error")
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)

        await ws._receive_loop(mock_ws, "public")

    @pytest.mark.asyncio
    async def test_receive_no_data_key_no_callback(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        ws._running = True
        callback = MagicMock()
        ws._callbacks["ticker"] = callback

        call_count = 0
        msg = json.dumps({"arg": {"channel": "ticker"}})  # No "data" key

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)

        await ws._receive_loop(mock_ws, "public")
        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_receive_no_matching_channel_no_callback(self):
        from src.exchanges.weex.websocket import WeexWebSocket
        ws = WeexWebSocket()
        ws._running = True
        callback = MagicMock()
        ws._callbacks["ticker"] = callback

        call_count = 0
        msg = json.dumps({
            "arg": {"channel": "orders"},
            "data": [{"orderId": "123"}],
        })

        async def recv_side():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return msg
            ws._running = False
            raise asyncio.TimeoutError()

        mock_ws = make_mock_ws()
        mock_ws.recv = AsyncMock(side_effect=recv_side)

        await ws._receive_loop(mock_ws, "private")
        callback.assert_not_called()
