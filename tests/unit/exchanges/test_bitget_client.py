"""
Comprehensive unit tests for BitgetExchangeClient.

Tests cover:
- Initialization and configuration
- Authentication (signature generation, headers)
- HTTP request handling (_request, _raw_request)
- All ABC methods (balance, orders, positions, ticker, funding)
- Bitget-specific methods (fees, fill price, affiliate, position sizing)
- Error handling (API errors, timeouts, circuit breaker)
- Edge cases (empty data, list responses, missing fields)
"""

import asyncio
import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from src.exchanges.bitget.client import (
    BitgetClientError,
    BitgetExchangeClient,
)
from src.exchanges.bitget.constants import (
    BASE_URL,
    SUCCESS_CODE,
    TESTNET_URL,
)
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_kwargs():
    """Default kwargs for creating a test client."""
    return {
        "api_key": "test-api-key",
        "api_secret": "test-api-secret",
        "passphrase": "test-passphrase",
        "demo_mode": True,
        "testnet": False,
    }


@pytest.fixture
def client(client_kwargs):
    """Create a BitgetExchangeClient instance for testing."""
    return BitgetExchangeClient(**client_kwargs)


@pytest.fixture
def mock_session():
    """Create a mock aiohttp.ClientSession."""
    session = AsyncMock(spec=aiohttp.ClientSession)
    session.closed = False
    return session


def make_api_response(data, code=SUCCESS_CODE, msg="success", status=200):
    """Helper to build a mock aiohttp response context manager."""
    response_body = {"code": code, "msg": msg, "data": data}
    mock_response = AsyncMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=response_body)
    mock_response.request_info = MagicMock()
    mock_response.history = ()

    # aiohttp returns a context manager from session.request(...)
    ctx_manager = AsyncMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=mock_response)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)
    return ctx_manager, mock_response


# ---------------------------------------------------------------------------
# Initialization Tests
# ---------------------------------------------------------------------------

class TestBitgetClientInit:
    """Tests for client initialization and properties."""

    def test_init_default_demo_mode(self, client):
        """Client initializes with demo mode enabled by default."""
        assert client.api_key == "test-api-key"
        assert client.api_secret == "test-api-secret"
        assert client.passphrase == "test-passphrase"
        assert client.demo_mode is True
        assert client.testnet is False
        assert client.base_url == BASE_URL
        assert client._session is None

    def test_init_live_mode(self):
        """Client initializes in live mode when demo_mode=False."""
        c = BitgetExchangeClient(
            api_key="k", api_secret="s", passphrase="p", demo_mode=False,
        )
        assert c.demo_mode is False

    def test_init_testnet_mode(self):
        """Client uses testnet URL when testnet=True."""
        c = BitgetExchangeClient(
            api_key="k", api_secret="s", passphrase="p", testnet=True,
        )
        assert c.testnet is True
        assert c.base_url == TESTNET_URL

    def test_exchange_name_property(self, client):
        """exchange_name returns 'bitget'."""
        assert client.exchange_name == "bitget"

    def test_supports_demo_property(self, client):
        """supports_demo returns True."""
        assert client.supports_demo is True


# ---------------------------------------------------------------------------
# Authentication Tests
# ---------------------------------------------------------------------------

class TestBitgetClientAuth:
    """Tests for signature generation and header construction."""

    def test_generate_signature_produces_valid_hmac(self, client):
        """Signature matches manual HMAC-SHA256 + base64 computation."""
        timestamp = "1700000000000"
        method = "GET"
        request_path = "/api/v2/mix/account/account?symbol=BTCUSDT"
        body = ""

        # Arrange: compute expected signature manually
        message = timestamp + method.upper() + request_path + body
        expected_mac = hmac.new(
            client.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        expected_sig = base64.b64encode(expected_mac.digest()).decode()

        # Act
        result = client._generate_signature(timestamp, method, request_path, body)

        # Assert
        assert result == expected_sig

    def test_generate_signature_with_body(self, client):
        """Signature includes body when provided."""
        timestamp = "1700000000000"
        method = "POST"
        path = "/api/v2/mix/order/place-order"
        body = '{"symbol":"BTCUSDT","side":"buy"}'

        result = client._generate_signature(timestamp, method, path, body)
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("src.exchanges.bitget.client.time")
    def test_get_headers_demo_mode(self, mock_time, client):
        """Headers include paptrading header in demo mode."""
        mock_time.time.return_value = 1700000.0

        headers = client._get_headers("GET", "/api/test")

        assert headers["ACCESS-KEY"] == "test-api-key"
        assert headers["ACCESS-PASSPHRASE"] == "test-passphrase"
        assert headers["Content-Type"] == "application/json"
        assert headers["locale"] == "en-US"
        assert headers["paptrading"] == "1"
        assert "ACCESS-SIGN" in headers
        assert "ACCESS-TIMESTAMP" in headers

    @patch("src.exchanges.bitget.client.time")
    def test_get_headers_live_mode_no_paptrading(self, mock_time):
        """Headers omit paptrading header in live mode."""
        mock_time.time.return_value = 1700000.0
        c = BitgetExchangeClient(
            api_key="k", api_secret="s", passphrase="p", demo_mode=False,
        )

        headers = c._get_headers("GET", "/api/test")

        assert "paptrading" not in headers


# ---------------------------------------------------------------------------
# Session Management Tests
# ---------------------------------------------------------------------------

class TestSessionManagement:
    """Tests for session creation and cleanup."""

    async def test_ensure_session_creates_new_session(self, client):
        """_ensure_session creates a session when none exists."""
        assert client._session is None

        with patch("src.exchanges.bitget.client.aiohttp.ClientSession") as MockSession:
            mock_instance = MagicMock()
            MockSession.return_value = mock_instance
            await client._ensure_session()

            MockSession.assert_called_once()
            assert client._session is mock_instance

    async def test_ensure_session_reuses_open_session(self, client, mock_session):
        """_ensure_session does not recreate an open session."""
        client._session = mock_session

        with patch("src.exchanges.bitget.client.aiohttp.ClientSession") as MockSession:
            await client._ensure_session()
            MockSession.assert_not_called()

    async def test_close_closes_open_session(self, client, mock_session):
        """close() closes the active session."""
        client._session = mock_session
        await client.close()
        mock_session.close.assert_called_once()

    async def test_close_noop_when_no_session(self, client):
        """close() does nothing when no session exists."""
        await client.close()  # Should not raise

    async def test_close_noop_when_session_already_closed(self, client):
        """close() does nothing when session is already closed."""
        mock_sess = AsyncMock()
        mock_sess.closed = True
        client._session = mock_sess
        await client.close()
        mock_sess.close.assert_not_called()

    async def test_async_context_manager(self, client):
        """Client works as an async context manager."""
        with patch.object(client, "_ensure_session", new_callable=AsyncMock) as mock_ensure:
            with patch.object(client, "close", new_callable=AsyncMock) as mock_close:
                async with client as c:
                    assert c is client
                mock_ensure.assert_called_once()
                mock_close.assert_called_once()


# ---------------------------------------------------------------------------
# HTTP Request Tests
# ---------------------------------------------------------------------------

class TestHttpRequest:
    """Tests for _request and _raw_request."""

    async def test_request_delegates_to_circuit_breaker(self, client):
        """_request uses circuit breaker by default."""
        expected = {"key": "value"}

        with patch("src.exchanges.bitget.client._bitget_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(return_value=expected)

            result = await client._request("GET", "/api/test")

            mock_breaker.call.assert_called_once()
            assert result == expected

    async def test_request_bypasses_circuit_breaker_when_disabled(self, client):
        """_request calls _raw_request directly when use_circuit_breaker=False."""
        expected = {"key": "value"}

        with patch.object(client, "_raw_request", new_callable=AsyncMock, return_value=expected):
            result = await client._request(
                "GET", "/api/test", use_circuit_breaker=False,
            )
            assert result == expected

    async def test_request_wraps_circuit_breaker_error(self, client):
        """_request wraps CircuitBreakerError in BitgetClientError."""
        from src.utils.circuit_breaker import CircuitBreakerError, CircuitState

        with patch("src.exchanges.bitget.client._bitget_breaker") as mock_breaker:
            mock_breaker.call = AsyncMock(
                side_effect=CircuitBreakerError("bitget_api", CircuitState.OPEN, 30.0)
            )

            with pytest.raises(BitgetClientError, match="temporarily unavailable"):
                await client._request("GET", "/api/test")

    async def test_raw_request_get_success(self, client, mock_session):
        """_raw_request handles a successful GET response."""
        client._session = mock_session
        response_data = {"accountEquity": "1000.0"}
        ctx, _ = make_api_response(response_data)
        mock_session.request.return_value = ctx

        # Bypass the @with_retry decorator by calling the underlying function
        # We need to call the wrapped function's inner implementation
        result = await client._raw_request.__wrapped__(
            client, "GET", "/api/v2/mix/account/account",
            params={"symbol": "BTCUSDT"},
        )

        assert result == response_data
        mock_session.request.assert_called_once()
        call_kwargs = mock_session.request.call_args
        assert call_kwargs.kwargs["method"] == "GET"

    async def test_raw_request_post_with_data(self, client, mock_session):
        """_raw_request sends JSON body for POST requests."""
        client._session = mock_session
        response_data = {"orderId": "12345"}
        ctx, _ = make_api_response(response_data)
        mock_session.request.return_value = ctx

        post_data = {"symbol": "BTCUSDT", "side": "buy"}
        result = await client._raw_request.__wrapped__(
            client, "POST", "/api/v2/mix/order/place-order",
            data=post_data,
        )

        assert result == response_data
        call_kwargs = mock_session.request.call_args.kwargs
        assert call_kwargs["method"] == "POST"
        assert call_kwargs["data"] == json.dumps(post_data)

    async def test_raw_request_no_auth_headers(self, client, mock_session):
        """_raw_request uses minimal headers when auth=False."""
        client._session = mock_session
        ctx, _ = make_api_response({"lastPr": "95000.0"})
        mock_session.request.return_value = ctx

        await client._raw_request.__wrapped__(
            client, "GET", "/api/test", auth=False,
        )

        call_kwargs = mock_session.request.call_args.kwargs
        headers = call_kwargs["headers"]
        assert "ACCESS-KEY" not in headers
        assert headers["Content-Type"] == "application/json"

    async def test_raw_request_api_error_non_200_status(self, client, mock_session):
        """_raw_request raises BitgetClientError for non-200 status."""
        client._session = mock_session
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.json = AsyncMock(return_value={"code": "40034", "msg": "Invalid API key"})
        mock_response.request_info = MagicMock()
        mock_response.history = ()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request.return_value = ctx

        with pytest.raises(BitgetClientError, match="Invalid API key"):
            await client._raw_request.__wrapped__(
                client, "GET", "/api/test",
            )

    async def test_raw_request_api_error_bad_code(self, client, mock_session):
        """_raw_request raises BitgetClientError when code != SUCCESS_CODE."""
        client._session = mock_session
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"code": "43011", "msg": "Insufficient balance"}
        )

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request.return_value = ctx

        with pytest.raises(BitgetClientError, match="Insufficient balance"):
            await client._raw_request.__wrapped__(
                client, "GET", "/api/test",
            )

    async def test_raw_request_rate_limited_429(self, client, mock_session):
        """_raw_request raises ClientResponseError on 429 status."""
        client._session = mock_session
        mock_response = AsyncMock()
        mock_response.status = 429
        mock_response.json = AsyncMock(return_value={"code": "429", "msg": "Rate limited"})
        mock_response.request_info = MagicMock()
        mock_response.history = ()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request.return_value = ctx

        with pytest.raises(aiohttp.ClientResponseError):
            await client._raw_request.__wrapped__(
                client, "GET", "/api/test",
            )

    async def test_raw_request_timeout_propagates(self, client, mock_session):
        """_raw_request re-raises asyncio.TimeoutError."""
        client._session = mock_session
        mock_session.request.side_effect = asyncio.TimeoutError()

        with pytest.raises(asyncio.TimeoutError):
            await client._raw_request.__wrapped__(
                client, "GET", "/api/test",
            )

    async def test_raw_request_client_error_propagates(self, client, mock_session):
        """_raw_request re-raises aiohttp.ClientError."""
        client._session = mock_session
        mock_session.request.side_effect = aiohttp.ClientError("Connection failed")

        with pytest.raises(aiohttp.ClientError):
            await client._raw_request.__wrapped__(
                client, "GET", "/api/test",
            )


# ---------------------------------------------------------------------------
# get_account_balance Tests
# ---------------------------------------------------------------------------

class TestGetAccountBalance:
    """Tests for the get_account_balance method."""

    async def test_get_balance_dict_response(self, client):
        """Parses balance from dict response."""
        mock_data = {
            "accountEquity": "10000.50",
            "available": "8000.25",
            "unrealizedPL": "150.75",
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            balance = await client.get_account_balance()

        assert isinstance(balance, Balance)
        assert balance.total == 10000.50
        assert balance.available == 8000.25
        assert balance.unrealized_pnl == 150.75
        assert balance.currency == "USDT"

    async def test_get_balance_list_response(self, client):
        """Parses balance from list response (takes first element)."""
        mock_data = [
            {
                "accountEquity": "5000.0",
                "available": "4000.0",
                "unrealizedPL": "100.0",
            }
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            balance = await client.get_account_balance()

        assert balance.total == 5000.0
        assert balance.available == 4000.0
        assert balance.unrealized_pnl == 100.0

    async def test_get_balance_empty_list(self, client):
        """Returns zero values for empty list response."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=[]):
            balance = await client.get_account_balance()

        assert balance.total == 0.0
        assert balance.available == 0.0
        assert balance.unrealized_pnl == 0.0

    async def test_get_balance_fallback_fields(self, client):
        """Uses fallback fields (usdtEquity, crossedMaxAvailable)."""
        mock_data = {
            "usdtEquity": "7500.0",
            "crossedMaxAvailable": "6000.0",
            "unrealizedPL": "0",
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            balance = await client.get_account_balance()

        assert balance.total == 7500.0
        assert balance.available == 6000.0


# ---------------------------------------------------------------------------
# place_market_order Tests
# ---------------------------------------------------------------------------

class TestPlaceMarketOrder:
    """Tests for the place_market_order method."""

    async def test_place_long_order(self, client):
        """Places a long market order with correct side mapping."""
        mock_result = {"orderId": "order-123"}

        with patch.object(client, "set_leverage", new_callable=AsyncMock, return_value=True):
            with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result):
                order = await client.place_market_order(
                    symbol="BTCUSDT", side="long", size=0.01, leverage=10,
                )

        assert isinstance(order, Order)
        assert order.order_id == "order-123"
        assert order.symbol == "BTCUSDT"
        assert order.side == "long"
        assert order.size == 0.01
        assert order.leverage == 10
        assert order.status == "filled"
        assert order.exchange == "bitget"
        assert order.price == 0.0

    async def test_place_short_order(self, client):
        """Places a short market order with correct side mapping."""
        mock_result = {"orderId": "order-456"}

        with patch.object(client, "set_leverage", new_callable=AsyncMock, return_value=True):
            with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result):
                order = await client.place_market_order(
                    symbol="ETHUSDT", side="short", size=0.5, leverage=5,
                )

        assert order.order_id == "order-456"
        assert order.side == "short"

    async def test_place_order_with_tp_sl(self, client):
        """Places order and sets TP/SL via dedicated endpoint."""
        mock_result = {"orderId": "order-789"}

        with patch.object(client, "set_leverage", new_callable=AsyncMock, return_value=True):
            with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result):
                with patch.object(client, "_set_position_tpsl", new_callable=AsyncMock) as mock_tpsl:
                    order = await client.place_market_order(
                        symbol="BTCUSDT",
                        side="long",
                        size=0.01,
                        leverage=10,
                        take_profit=100000.0,
                        stop_loss=90000.0,
                    )

                    mock_tpsl.assert_called_once_with(
                        symbol="BTCUSDT",
                        hold_side="long",
                        take_profit=100000.0,
                        stop_loss=90000.0,
                    )

        assert order.take_profit == 100000.0
        assert order.stop_loss == 90000.0

    async def test_place_order_tpsl_failure_does_not_raise(self, client):
        """Order succeeds even when TP/SL setting fails."""
        mock_result = {"orderId": "order-789"}

        with patch.object(client, "set_leverage", new_callable=AsyncMock, return_value=True):
            with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result):
                with patch.object(
                    client, "_set_position_tpsl",
                    new_callable=AsyncMock,
                    side_effect=Exception("TP/SL API error"),
                ):
                    order = await client.place_market_order(
                        symbol="BTCUSDT",
                        side="long",
                        size=0.01,
                        leverage=10,
                        take_profit=100000.0,
                        stop_loss=90000.0,
                    )

        assert order.order_id == "order-789"

    async def test_place_order_sets_leverage_first(self, client):
        """set_leverage is called before placing the order."""
        call_order = []

        async def mock_set_leverage(symbol, leverage, margin_mode="cross"):
            call_order.append("set_leverage")
            return True

        async def mock_request(method, endpoint, **kwargs):
            call_order.append("place_order")
            return {"orderId": "order-001"}

        with patch.object(client, "set_leverage", side_effect=mock_set_leverage):
            with patch.object(client, "_request", side_effect=mock_request):
                await client.place_market_order(
                    symbol="BTCUSDT", side="long", size=0.01, leverage=10,
                )

        assert call_order == ["set_leverage", "place_order"]

    async def test_place_order_nested_order_id(self, client):
        """Extracts orderId from nested data structure."""
        mock_result = {"data": {"orderId": "nested-id"}}

        with patch.object(client, "set_leverage", new_callable=AsyncMock, return_value=True):
            with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result):
                order = await client.place_market_order(
                    symbol="BTCUSDT", side="long", size=0.01, leverage=10,
                )

        assert order.order_id == "nested-id"


# ---------------------------------------------------------------------------
# _set_position_tpsl Tests
# ---------------------------------------------------------------------------

class TestSetPositionTpsl:
    """Tests for the _set_position_tpsl method."""

    async def test_set_tp_and_sl(self, client):
        """Sets both take profit and stop loss."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            await client._set_position_tpsl(
                symbol="BTCUSDT",
                hold_side="long",
                take_profit=100000.0,
                stop_loss=90000.0,
            )

            call_data = mock_req.call_args.kwargs["data"]
            assert call_data["stopSurplusTriggerPrice"] == "100000.0"
            assert call_data["stopLossTriggerPrice"] == "90000.0"
            assert call_data["holdSide"] == "long"

    async def test_set_tp_only(self, client):
        """Sets take profit only when stop loss is None."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            await client._set_position_tpsl(
                symbol="BTCUSDT",
                hold_side="long",
                take_profit=100000.0,
                stop_loss=None,
            )

            call_data = mock_req.call_args.kwargs["data"]
            assert "stopSurplusTriggerPrice" in call_data
            assert "stopLossTriggerPrice" not in call_data

    async def test_set_sl_only(self, client):
        """Sets stop loss only when take profit is None."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            await client._set_position_tpsl(
                symbol="BTCUSDT",
                hold_side="short",
                take_profit=None,
                stop_loss=90000.0,
            )

            call_data = mock_req.call_args.kwargs["data"]
            assert "stopSurplusTriggerPrice" not in call_data
            assert "stopLossTriggerPrice" in call_data


# ---------------------------------------------------------------------------
# cancel_order Tests
# ---------------------------------------------------------------------------

class TestCancelOrder:
    """Tests for the cancel_order method."""

    async def test_cancel_order_success(self, client):
        """Returns True on successful cancellation."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}):
            result = await client.cancel_order("BTCUSDT", "order-123")

        assert result is True

    async def test_cancel_order_failure(self, client):
        """Returns False when API returns error."""
        with patch.object(
            client, "_request",
            new_callable=AsyncMock,
            side_effect=BitgetClientError("Order does not exist"),
        ):
            result = await client.cancel_order("BTCUSDT", "bad-order")

        assert result is False


# ---------------------------------------------------------------------------
# close_position Tests
# ---------------------------------------------------------------------------

class TestClosePosition:
    """Tests for the close_position method."""

    async def test_close_long_position(self, client):
        """Closes a long position by selling."""
        mock_position = Position(
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            current_price=96000.0,
            unrealized_pnl=10.0,
            leverage=10,
            exchange="bitget",
        )

        with patch.object(client, "get_position", new_callable=AsyncMock, return_value=mock_position):
            with patch.object(
                client, "_request", new_callable=AsyncMock,
                return_value={"successList": [{"orderId": "close-order-1"}]},
            ):
                order = await client.close_position("BTCUSDT", "long")

        assert isinstance(order, Order)
        assert order.order_id == "close-order-1"
        assert order.side == "long"
        assert order.size == 0.01

    async def test_close_short_position(self, client):
        """Closes a short position by buying."""
        mock_position = Position(
            symbol="ETHUSDT",
            side="short",
            size=0.5,
            entry_price=3500.0,
            current_price=3400.0,
            unrealized_pnl=50.0,
            leverage=5,
            exchange="bitget",
        )

        with patch.object(client, "get_position", new_callable=AsyncMock, return_value=mock_position):
            with patch.object(
                client, "_request", new_callable=AsyncMock,
                return_value={"successList": [{"orderId": "close-order-2"}]},
            ) as mock_req:
                _order = await client.close_position("ETHUSDT", "short")

        # Verify flash-close uses holdSide from position
        call_data = mock_req.call_args.kwargs["data"]
        assert call_data["holdSide"] == "short"

    async def test_close_position_no_position_returns_none(self, client):
        """Returns None when no position exists."""
        with patch.object(client, "get_position", new_callable=AsyncMock, return_value=None):
            result = await client.close_position("BTCUSDT", "long")

        assert result is None


# ---------------------------------------------------------------------------
# get_position Tests
# ---------------------------------------------------------------------------

class TestGetPosition:
    """Tests for the get_position method."""

    async def test_get_position_found(self, client):
        """Returns a Position when data has total > 0."""
        mock_data = [
            {
                "total": "0.01",
                "holdSide": "long",
                "openPriceAvg": "95000.0",
                "markPrice": "96000.0",
                "unrealizedPL": "10.0",
                "leverage": "10",
                "margin": "95.0",
                "liquidationPrice": "85000.0",
            }
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            pos = await client.get_position("BTCUSDT")

        assert isinstance(pos, Position)
        assert pos.symbol == "BTCUSDT"
        assert pos.side == "long"
        assert pos.size == 0.01
        assert pos.entry_price == 95000.0
        assert pos.current_price == 96000.0
        assert pos.unrealized_pnl == 10.0
        assert pos.leverage == 10
        assert pos.margin == 95.0
        assert pos.liquidation_price == 85000.0

    async def test_get_position_empty_returns_none(self, client):
        """Returns None when position list is empty."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=[]):
            pos = await client.get_position("BTCUSDT")

        assert pos is None

    async def test_get_position_zero_total_returns_none(self, client):
        """Returns None when all positions have total=0."""
        mock_data = [{"total": "0", "holdSide": "long"}]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            pos = await client.get_position("BTCUSDT")

        assert pos is None

    async def test_get_position_dict_response(self, client):
        """Handles dict (non-list) response by wrapping it."""
        mock_data = {
            "total": "0.05",
            "holdSide": "short",
            "openPriceAvg": "3500.0",
            "markPrice": "3400.0",
            "unrealizedPL": "50.0",
            "leverage": "5",
            "margin": "35.0",
            "liquidationPrice": "3800.0",
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            pos = await client.get_position("ETHUSDT")

        assert pos is not None
        assert pos.side == "short"
        assert pos.size == 0.05

    async def test_get_position_null_liquidation_price(self, client):
        """Handles null liquidation price gracefully."""
        mock_data = [
            {
                "total": "0.01",
                "holdSide": "long",
                "openPriceAvg": "95000.0",
                "markPrice": "96000.0",
                "unrealizedPL": "10.0",
                "leverage": "10",
                "margin": "95.0",
                "liquidationPrice": None,
            }
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            pos = await client.get_position("BTCUSDT")

        assert pos.liquidation_price == 0


# ---------------------------------------------------------------------------
# get_open_positions Tests
# ---------------------------------------------------------------------------

class TestGetOpenPositions:
    """Tests for the get_open_positions method."""

    async def test_get_open_positions_multiple(self, client):
        """Returns multiple open positions."""
        mock_data = [
            {
                "symbol": "BTCUSDT",
                "total": "0.01",
                "holdSide": "long",
                "openPriceAvg": "95000.0",
                "markPrice": "96000.0",
                "unrealizedPL": "10.0",
                "leverage": "10",
                "margin": "95.0",
                "liquidationPrice": "85000.0",
            },
            {
                "symbol": "ETHUSDT",
                "total": "0.5",
                "holdSide": "short",
                "openPriceAvg": "3500.0",
                "markPrice": "3400.0",
                "unrealizedPL": "50.0",
                "leverage": "5",
                "margin": "350.0",
                "liquidationPrice": "3800.0",
            },
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            positions = await client.get_open_positions()

        assert len(positions) == 2
        assert positions[0].symbol == "BTCUSDT"
        assert positions[1].symbol == "ETHUSDT"

    async def test_get_open_positions_filters_zero_total(self, client):
        """Filters out positions with total=0."""
        mock_data = [
            {"symbol": "BTCUSDT", "total": "0.01", "holdSide": "long",
             "openPriceAvg": "95000", "markPrice": "96000",
             "unrealizedPL": "10", "leverage": "10", "margin": "95",
             "liquidationPrice": "85000"},
            {"symbol": "ETHUSDT", "total": "0", "holdSide": "long",
             "openPriceAvg": "0", "markPrice": "0",
             "unrealizedPL": "0", "leverage": "1", "margin": "0",
             "liquidationPrice": "0"},
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            positions = await client.get_open_positions()

        assert len(positions) == 1
        assert positions[0].symbol == "BTCUSDT"

    async def test_get_open_positions_empty(self, client):
        """Returns empty list when no positions exist."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=[]):
            positions = await client.get_open_positions()

        assert positions == []

    async def test_get_open_positions_non_list_response(self, client):
        """Returns empty list for non-list response."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}):
            positions = await client.get_open_positions()

        assert positions == []


# ---------------------------------------------------------------------------
# set_leverage Tests
# ---------------------------------------------------------------------------

class TestSetLeverage:
    """Tests for the set_leverage method."""

    async def test_set_leverage_both_sides(self, client):
        """Sets leverage for both long and short sides."""
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            result = await client.set_leverage("BTCUSDT", 10)

        assert result is True
        assert mock_req.call_count == 2

        # Verify both sides were set
        calls_data = [call.kwargs["data"] for call in mock_req.call_args_list]
        hold_sides = {d["holdSide"] for d in calls_data}
        assert hold_sides == {"long", "short"}
        assert all(d["leverage"] == "10" for d in calls_data)

    async def test_set_leverage_ignores_errors(self, client):
        """Returns True even if setting leverage fails (already set)."""
        with patch.object(
            client, "_request",
            new_callable=AsyncMock,
            side_effect=BitgetClientError("Leverage not changed, same as current"),
        ):
            result = await client.set_leverage("BTCUSDT", 10)

        assert result is True


# ---------------------------------------------------------------------------
# get_ticker Tests
# ---------------------------------------------------------------------------

class TestGetTicker:
    """Tests for the get_ticker method."""

    async def test_get_ticker_success(self, client):
        """Returns a Ticker with correct field mapping."""
        mock_data = {
            "lastPr": "95500.0",
            "bidPr": "95499.0",
            "askPr": "95501.0",
            "baseVolume": "12345.67",
            "high24h": "96000.0",
            "low24h": "94000.0",
            "change24h": "0.015",
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            ticker = await client.get_ticker("BTCUSDT")

        assert isinstance(ticker, Ticker)
        assert ticker.symbol == "BTCUSDT"
        assert ticker.last_price == 95500.0
        assert ticker.bid == 95499.0
        assert ticker.ask == 95501.0
        assert ticker.volume_24h == 12345.67
        assert ticker.high_24h == 96000.0
        assert ticker.low_24h == 94000.0
        assert ticker.change_24h_percent == 0.015

    async def test_get_ticker_list_response(self, client):
        """Handles list response by taking first element."""
        mock_data = [
            {"lastPr": "3500.0", "bidPr": "3499.0", "askPr": "3501.0", "baseVolume": "5000.0"}
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            ticker = await client.get_ticker("ETHUSDT")

        assert ticker.last_price == 3500.0

    async def test_get_ticker_fallback_fields(self, client):
        """Uses fallback fields (last, bestBid, bestAsk, volume24h)."""
        mock_data = {
            "last": "95000.0",
            "bestBid": "94999.0",
            "bestAsk": "95001.0",
            "volume24h": "10000.0",
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            ticker = await client.get_ticker("BTCUSDT")

        assert ticker.last_price == 95000.0
        assert ticker.bid == 94999.0
        assert ticker.ask == 95001.0
        assert ticker.volume_24h == 10000.0

    async def test_get_ticker_missing_optional_fields(self, client):
        """Optional fields are None when not present."""
        mock_data = {
            "lastPr": "95000.0",
            "bidPr": "94999.0",
            "askPr": "95001.0",
            "baseVolume": "10000.0",
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            ticker = await client.get_ticker("BTCUSDT")

        assert ticker.high_24h is None
        assert ticker.low_24h is None
        assert ticker.change_24h_percent is None

    async def test_get_ticker_uses_no_auth(self, client):
        """get_ticker calls _request with auth=False."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}) as mock_req:
            await client.get_ticker("BTCUSDT")

        _, kwargs = mock_req.call_args
        assert kwargs.get("auth") is False


# ---------------------------------------------------------------------------
# get_funding_rate Tests
# ---------------------------------------------------------------------------

class TestGetFundingRate:
    """Tests for the get_funding_rate method."""

    async def test_get_funding_rate_success(self, client):
        """Returns FundingRateInfo with correct rate."""
        mock_data = {"fundingRate": "0.0001"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            info = await client.get_funding_rate("BTCUSDT")

        assert isinstance(info, FundingRateInfo)
        assert info.symbol == "BTCUSDT"
        assert info.current_rate == 0.0001

    async def test_get_funding_rate_list_response(self, client):
        """Handles list response for funding rate."""
        mock_data = [{"fundingRate": "-0.0005"}]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            info = await client.get_funding_rate("ETHUSDT")

        assert info.current_rate == -0.0005

    async def test_get_funding_rate_empty_list(self, client):
        """Returns 0 rate for empty list response."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=[]):
            info = await client.get_funding_rate("BTCUSDT")

        assert info.current_rate == 0.0

    async def test_get_funding_rate_no_auth(self, client):
        """get_funding_rate calls _request with auth=False."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}) as mock_req:
            await client.get_funding_rate("BTCUSDT")

        _, kwargs = mock_req.call_args
        assert kwargs.get("auth") is False


# ---------------------------------------------------------------------------
# get_order_fees Tests
# ---------------------------------------------------------------------------

class TestGetOrderFees:
    """Tests for the get_order_fees method."""

    async def test_get_order_fees_primary_field(self, client):
        """Returns absolute fee from primary 'fee' field."""
        mock_data = {"fee": "-0.50"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            fees = await client.get_order_fees("BTCUSDT", "order-1")

        assert fees == 0.50

    async def test_get_order_fees_fallback_to_fee_detail(self, client):
        """Falls back to feeDetail when fee is '0'."""
        mock_data = {
            "fee": "0",
            "feeDetail": [
                {"totalFee": "-0.30"},
                {"totalFee": "-0.20"},
            ],
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            fees = await client.get_order_fees("BTCUSDT", "order-2")

        assert fees == 0.50

    async def test_get_order_fees_no_fee_data(self, client):
        """Returns 0.0 when no fee data is available."""
        mock_data = {}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            fees = await client.get_order_fees("BTCUSDT", "order-3")

        assert fees == 0.0

    async def test_get_order_fees_empty_response(self, client):
        """Returns 0.0 for empty/falsy response."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=None):
            fees = await client.get_order_fees("BTCUSDT", "order-4")

        assert fees == 0.0

    async def test_get_order_fees_exception_returns_zero(self, client):
        """Returns 0.0 when an exception occurs."""
        with patch.object(
            client, "_request",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ):
            fees = await client.get_order_fees("BTCUSDT", "order-5")

        assert fees == 0.0


# ---------------------------------------------------------------------------
# get_trade_total_fees Tests
# ---------------------------------------------------------------------------

class TestGetTradeTotalFees:
    """Tests for the get_trade_total_fees method."""

    async def test_total_fees_with_both_order_ids(self, client):
        """Sums entry + exit fees when both order IDs are provided."""
        async def mock_get_fees(symbol, order_id):
            if order_id == "entry-1":
                return 0.30
            if order_id == "exit-1":
                return 0.25
            return 0.0

        with patch.object(client, "get_order_fees", side_effect=mock_get_fees):
            total = await client.get_trade_total_fees("BTCUSDT", "entry-1", "exit-1")

        assert total == 0.55

    async def test_total_fees_searches_history_without_close_id(self, client):
        """Searches order history when no close_order_id is provided."""
        mock_history = {
            "orderList": [
                {"tradeSide": "close", "status": "filled", "fee": "-0.40"},
                {"tradeSide": "open", "status": "filled", "fee": "-0.30"},
            ]
        }

        async def mock_get_fees(symbol, order_id):
            return 0.30

        async def mock_request(method, endpoint, **kwargs):
            return mock_history

        with patch.object(client, "get_order_fees", side_effect=mock_get_fees):
            with patch.object(client, "_request", side_effect=mock_request):
                total = await client.get_trade_total_fees("BTCUSDT", "entry-1")

        assert total == 0.7

    async def test_total_fees_history_search_exception(self, client):
        """Returns only entry fees when history search fails."""
        async def mock_get_fees(symbol, order_id):
            return 0.30

        with patch.object(client, "get_order_fees", side_effect=mock_get_fees):
            with patch.object(
                client, "_request",
                new_callable=AsyncMock,
                side_effect=Exception("Network error"),
            ):
                total = await client.get_trade_total_fees("BTCUSDT", "entry-1")

        assert total == 0.3

    async def test_total_fees_empty_entry_id(self, client):
        """Handles empty entry_order_id gracefully."""
        total = await client.get_trade_total_fees("BTCUSDT", "")
        assert total == 0.0

    async def test_total_fees_history_list_response(self, client):
        """Handles order history returned as a plain list."""
        mock_history = [
            {"tradeSide": "close", "status": "filled", "fee": "-0.25"},
            {"tradeSide": "open", "status": "filled", "fee": "-0.20"},
        ]

        async def mock_get_fees(symbol, order_id):
            return 0.30

        async def mock_request(method, endpoint, **kwargs):
            return mock_history

        with patch.object(client, "get_order_fees", side_effect=mock_get_fees):
            with patch.object(client, "_request", side_effect=mock_request):
                total = await client.get_trade_total_fees("BTCUSDT", "entry-1")

        assert total == 0.55


# ---------------------------------------------------------------------------
# get_funding_fees Tests
# ---------------------------------------------------------------------------

class TestGetFundingFees:
    """Tests for the get_funding_fees method."""

    async def test_get_funding_fees_success(self, client):
        """Returns sum of absolute funding fee amounts."""
        mock_data = {
            "bills": [
                {"amount": "-0.10"},
                {"amount": "-0.15"},
                {"amount": "0.05"},
            ]
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            fees = await client.get_funding_fees("BTCUSDT", 1700000000000, 1700100000000)

        assert fees == 0.3

    async def test_get_funding_fees_list_response(self, client):
        """Handles list response directly (no 'bills' key)."""
        mock_data = [
            {"amount": "-0.20"},
            {"amount": "-0.10"},
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            fees = await client.get_funding_fees("BTCUSDT", 1700000000000, 1700100000000)

        assert fees == 0.3

    async def test_get_funding_fees_empty(self, client):
        """Returns 0.0 when no bills exist."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value={"bills": []}):
            fees = await client.get_funding_fees("BTCUSDT", 1700000000000, 1700100000000)

        assert fees == 0.0

    async def test_get_funding_fees_exception_returns_zero(self, client):
        """Returns 0.0 on exception."""
        with patch.object(
            client, "_request",
            new_callable=AsyncMock,
            side_effect=Exception("API error"),
        ):
            fees = await client.get_funding_fees("BTCUSDT", 1700000000000, 1700100000000)

        assert fees == 0.0

    async def test_get_funding_fees_non_list_bills(self, client):
        """Returns 0.0 when bills is not a list."""
        with patch.object(
            client, "_request",
            new_callable=AsyncMock,
            return_value={"bills": "not_a_list"},
        ):
            fees = await client.get_funding_fees("BTCUSDT", 1700000000000, 1700100000000)

        assert fees == 0.0


# ---------------------------------------------------------------------------
# get_fill_price Tests
# ---------------------------------------------------------------------------

class TestGetFillPrice:
    """Tests for the get_fill_price method."""

    async def test_get_fill_price_success(self, client):
        """Returns fill price on first attempt."""
        mock_data = {"priceAvg": "95500.0"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            with patch("src.exchanges.bitget.client.asyncio.sleep", new_callable=AsyncMock):
                price = await client.get_fill_price("BTCUSDT", "order-1")

        assert price == 95500.0

    async def test_get_fill_price_uses_fill_price_fallback(self, client):
        """Falls back to fillPrice field when priceAvg is missing."""
        mock_data = {"fillPrice": "95000.0"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            with patch("src.exchanges.bitget.client.asyncio.sleep", new_callable=AsyncMock):
                price = await client.get_fill_price("BTCUSDT", "order-1")

        assert price == 95000.0

    async def test_get_fill_price_retries_on_failure(self, client):
        """Retries on exception before returning None."""
        with patch.object(
            client, "_request",
            new_callable=AsyncMock,
            side_effect=Exception("Temporary error"),
        ):
            with patch("src.exchanges.bitget.client.asyncio.sleep", new_callable=AsyncMock):
                price = await client.get_fill_price(
                    "BTCUSDT", "order-1", max_retries=2, retry_delay=0.01,
                )

        assert price is None

    async def test_get_fill_price_retries_then_succeeds(self, client):
        """Succeeds on second retry after first attempt fails."""
        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Temp failure")
            return {"priceAvg": "96000.0"}

        with patch.object(client, "_request", side_effect=mock_request):
            with patch("src.exchanges.bitget.client.asyncio.sleep", new_callable=AsyncMock):
                price = await client.get_fill_price(
                    "BTCUSDT", "order-1", max_retries=3, retry_delay=0.01,
                )

        assert price == 96000.0

    async def test_get_fill_price_zero_price_retries(self, client):
        """Retries when fill price is 0."""
        with patch.object(
            client, "_request",
            new_callable=AsyncMock,
            return_value={"priceAvg": "0"},
        ):
            with patch("src.exchanges.bitget.client.asyncio.sleep", new_callable=AsyncMock):
                price = await client.get_fill_price(
                    "BTCUSDT", "order-1", max_retries=2, retry_delay=0.01,
                )

        assert price is None

    async def test_get_fill_price_empty_response(self, client):
        """Returns None when response is empty."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value=None):
            with patch("src.exchanges.bitget.client.asyncio.sleep", new_callable=AsyncMock):
                price = await client.get_fill_price(
                    "BTCUSDT", "order-1", max_retries=1, retry_delay=0.01,
                )

        assert price is None


# ---------------------------------------------------------------------------
# get_raw_account_balance Tests
# ---------------------------------------------------------------------------

class TestGetRawAccountBalance:
    """Tests for the get_raw_account_balance method."""

    async def test_returns_raw_data(self, client):
        """Returns raw API response without normalization."""
        mock_data = {"accountEquity": "10000", "available": "8000"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data) as mock_req:
            result = await client.get_raw_account_balance()

        assert result == mock_data
        call_kwargs = mock_req.call_args.kwargs
        assert call_kwargs["params"]["marginCoin"] == "USDT"

    async def test_custom_margin_coin(self, client):
        """Passes custom margin coin parameter."""
        with patch.object(client, "_request", new_callable=AsyncMock, return_value={}) as mock_req:
            await client.get_raw_account_balance(margin_coin="BTC")

        call_kwargs = mock_req.call_args.kwargs
        assert call_kwargs["params"]["marginCoin"] == "BTC"


# ---------------------------------------------------------------------------
# get_raw_position Tests
# ---------------------------------------------------------------------------

class TestGetRawPosition:
    """Tests for the get_raw_position method."""

    async def test_returns_raw_position_data(self, client):
        """Returns raw API response for single position."""
        mock_data = {"total": "0.01", "holdSide": "long"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            result = await client.get_raw_position("BTCUSDT")

        assert result == mock_data


# ---------------------------------------------------------------------------
# place_raw_order Tests
# ---------------------------------------------------------------------------

class TestPlaceRawOrder:
    """Tests for the place_raw_order method."""

    async def test_place_raw_market_order(self, client):
        """Places a raw market order with correct data."""
        mock_result = {"orderId": "raw-order-1"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result) as mock_req:
            result = await client.place_raw_order(
                symbol="BTCUSDT",
                side="buy",
                trade_side="open",
                size="0.01",
            )

        assert result == mock_result
        call_data = mock_req.call_args.kwargs["data"]
        assert call_data["symbol"] == "BTCUSDT"
        assert call_data["side"] == "buy"
        assert call_data["tradeSide"] == "open"
        assert call_data["orderType"] == "market"
        assert call_data["size"] == "0.01"
        assert "price" not in call_data

    async def test_place_raw_limit_order_with_price(self, client):
        """Places a raw limit order with price."""
        mock_result = {"orderId": "raw-order-2"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result) as mock_req:
            _result = await client.place_raw_order(
                symbol="BTCUSDT",
                side="sell",
                trade_side="close",
                size="0.01",
                order_type="limit",
                price="96000.0",
            )

        call_data = mock_req.call_args.kwargs["data"]
        assert call_data["orderType"] == "limit"
        assert call_data["price"] == "96000.0"

    async def test_place_raw_order_with_tp_sl(self, client):
        """Includes TP/SL preset prices when provided."""
        mock_result = {"orderId": "raw-order-3"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result) as mock_req:
            await client.place_raw_order(
                symbol="BTCUSDT",
                side="buy",
                trade_side="open",
                size="0.01",
                take_profit="100000.0",
                stop_loss="90000.0",
            )

        call_data = mock_req.call_args.kwargs["data"]
        assert call_data["presetStopSurplusPrice"] == "100000.0"
        assert call_data["presetStopLossPrice"] == "90000.0"

    async def test_place_raw_market_order_ignores_price(self, client):
        """Market order does not include price even if provided."""
        mock_result = {"orderId": "raw-order-4"}

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_result) as mock_req:
            await client.place_raw_order(
                symbol="BTCUSDT",
                side="buy",
                trade_side="open",
                size="0.01",
                order_type="market",
                price="95000.0",
            )

        call_data = mock_req.call_args.kwargs["data"]
        assert "price" not in call_data


# ---------------------------------------------------------------------------
# check_affiliate_uid Tests
# ---------------------------------------------------------------------------

class TestCheckAffiliateUid:
    """Tests for the check_affiliate_uid method."""

    async def test_uid_found(self, client):
        """Returns True when UID is found in affiliate list."""
        mock_data = [
            {"uid": "111"},
            {"uid": "222"},
            {"uid": "333"},
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            result = await client.check_affiliate_uid("222")

        assert result is True

    async def test_uid_not_found(self, client):
        """Returns False when UID is not in affiliate list."""
        mock_data = [
            {"uid": "111"},
            {"uid": "222"},
        ]

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            result = await client.check_affiliate_uid("999")

        assert result is False

    async def test_uid_found_in_dict_response(self, client):
        """Handles dict response with 'list' key."""
        mock_data = {
            "list": [
                {"uid": "444"},
                {"uid": "555"},
            ]
        }

        with patch.object(client, "_request", new_callable=AsyncMock, return_value=mock_data):
            result = await client.check_affiliate_uid("555")

        assert result is True

    async def test_uid_check_exception_returns_false(self, client):
        """Returns False when API call fails."""
        with patch.object(
            client, "_request",
            new_callable=AsyncMock,
            side_effect=Exception("Network error"),
        ):
            result = await client.check_affiliate_uid("123")

        assert result is False

    async def test_uid_found_via_direct_filter(self, client):
        """UID found via direct uid filter on subaccounts endpoint."""
        async def mock_request(method, endpoint, **kwargs):
            return [{"uid": "target_uid"}]

        with patch.object(client, "_request", side_effect=mock_request):
            result = await client.check_affiliate_uid("target_uid")

        assert result is True


# ---------------------------------------------------------------------------
# calculate_position_size Tests
# ---------------------------------------------------------------------------

class TestCalculatePositionSize:
    """Tests for the calculate_position_size method."""

    def test_basic_calculation(self, client):
        """Calculates correct position size."""
        # balance=10000, price=50000, risk=1%, leverage=10
        # risk_amount = 10000 * 0.01 = 100
        # position_value = 100 * 10 = 1000
        # size = 1000 / 50000 = 0.02
        result = client.calculate_position_size(
            balance=10000.0,
            price=50000.0,
            risk_percent=1.0,
            leverage=10,
        )
        assert result == 0.02

    def test_fractional_result_rounded(self, client):
        """Result is rounded to 6 decimal places."""
        result = client.calculate_position_size(
            balance=1000.0,
            price=95000.0,
            risk_percent=2.0,
            leverage=5,
        )
        # risk_amount = 1000 * 0.02 = 20
        # position_value = 20 * 5 = 100
        # size = 100 / 95000 = 0.001052631...
        assert result == round(100 / 95000, 6)

    def test_high_leverage(self, client):
        """Works with high leverage values."""
        result = client.calculate_position_size(
            balance=5000.0,
            price=100000.0,
            risk_percent=5.0,
            leverage=100,
        )
        # risk_amount = 5000 * 0.05 = 250
        # position_value = 250 * 100 = 25000
        # size = 25000 / 100000 = 0.25
        assert result == 0.25

    def test_zero_risk_returns_zero(self, client):
        """Returns 0 when risk percent is 0."""
        result = client.calculate_position_size(
            balance=10000.0,
            price=50000.0,
            risk_percent=0.0,
            leverage=10,
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# BitgetClientError Tests
# ---------------------------------------------------------------------------

class TestBitgetClientError:
    """Tests for the custom exception class."""

    def test_error_is_exception_subclass(self):
        """BitgetClientError is an Exception and ExchangeError."""
        from src.exceptions import ExchangeError
        assert issubclass(BitgetClientError, Exception)
        assert issubclass(BitgetClientError, ExchangeError)

    def test_error_message(self):
        """Error carries the correct message with exchange prefix."""
        error = BitgetClientError("Something went wrong")
        assert str(error) == "[bitget] Something went wrong"
        assert error.exchange == "bitget"

    def test_error_can_be_caught(self):
        """Error can be caught as BitgetClientError, ExchangeError, and Exception."""
        from src.exceptions import ExchangeError
        with pytest.raises(BitgetClientError):
            raise BitgetClientError("test")

        with pytest.raises(ExchangeError):
            raise BitgetClientError("test")

        with pytest.raises(Exception):
            raise BitgetClientError("test")
