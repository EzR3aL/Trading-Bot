"""Comprehensive unit tests for src/exchanges/weex/client.py (WeexClient).

Targets: increase coverage from 28% to 70%+.
All HTTP calls are mocked via aiohttp.ClientSession -- no real API calls.
"""

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from src.exchanges.weex.client import WeexClient, WeexClientError
from src.exchanges.weex.constants import BASE_URL, SUCCESS_CODE
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api_response(data, code=SUCCESS_CODE, msg="success", status=200):
    """Build a mock aiohttp response context manager returning the given data."""
    response = AsyncMock()
    response.status = status
    response.json = AsyncMock(return_value={"code": code, "msg": msg, "data": data})

    # Works as an async context manager (async with session.request(...) as resp)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_error_response(msg="Server error", code="50000", status=200):
    """Build a mock response that triggers WeexClientError."""
    return _make_api_response(None, code=code, msg=msg, status=status)


def _make_http_error_response(status=500):
    """Build a mock response with non-200 HTTP status."""
    return _make_api_response(None, code=SUCCESS_CODE, msg="Internal", status=status)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Return a WeexClient in demo mode with fake credentials."""
    return WeexClient(
        api_key="test-api-key",
        api_secret="test-api-secret",
        passphrase="test-passphrase",
        demo_mode=True,
    )


@pytest.fixture
def live_client():
    """Return a WeexClient in live mode."""
    return WeexClient(
        api_key="live-key",
        api_secret="live-secret",
        passphrase="live-pass",
        demo_mode=False,
    )


@pytest.fixture
def mock_session():
    """Return a mock aiohttp.ClientSession with a configurable request method."""
    session = MagicMock(spec=aiohttp.ClientSession)
    session.closed = False
    session.close = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# Initialization & properties
# ---------------------------------------------------------------------------

class TestWeexClientInit:
    def test_init_demo_mode_uses_base_url(self, client):
        assert client.base_url == BASE_URL
        assert client.demo_mode is True
        assert client.api_key == "test-api-key"
        assert client.api_secret == "test-api-secret"
        assert client.passphrase == "test-passphrase"

    def test_init_live_mode_uses_base_url(self, live_client):
        assert live_client.base_url == BASE_URL
        assert live_client.demo_mode is False

    def test_exchange_name_returns_weex(self, client):
        assert client.exchange_name == "weex"

    def test_supports_demo_returns_true(self, client):
        assert client.supports_demo is True

    def test_session_initially_none(self, client):
        assert client._session is None

    def test_default_passphrase_is_empty_string(self):
        c = WeexClient(api_key="k", api_secret="s")
        assert c.passphrase == ""


# ---------------------------------------------------------------------------
# Signature & headers
# ---------------------------------------------------------------------------

class TestSignatureGeneration:
    def test_generate_signature_produces_valid_hmac(self, client):
        # Arrange
        timestamp = "1700000000000"
        method = "GET"
        request_path = "/api/v2/mix/market/ticker"
        body = ""

        # Act
        sig = client._generate_signature(timestamp, method, request_path, body)

        # Assert - replicate the expected signature manually
        message = timestamp + method.upper() + request_path + body
        expected_mac = hmac.new(
            b"test-api-secret", message.encode("utf-8"), digestmod=hashlib.sha256
        )
        expected = base64.b64encode(expected_mac.digest()).decode()
        assert sig == expected

    def test_generate_signature_includes_body_for_post(self, client):
        timestamp = "1700000000000"
        body = json.dumps({"symbol": "BTCUSDT"})
        sig = client._generate_signature(timestamp, "POST", "/api/v2/mix/order/place-order", body)
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_get_headers_returns_required_keys(self, client):
        headers = client._get_headers("GET", "/capi/v2/market/ticker")
        assert headers["ACCESS-KEY"] == "test-api-key"
        assert headers["ACCESS-PASSPHRASE"] == "test-passphrase"
        assert headers["Content-Type"] == "application/json"
        assert "ACCESS-SIGN" in headers
        assert "ACCESS-TIMESTAMP" in headers
        assert headers["locale"] == "en-US"

    def test_get_headers_timestamp_is_numeric_string(self, client):
        headers = client._get_headers("GET", "/path")
        assert headers["ACCESS-TIMESTAMP"].isdigit()


# ---------------------------------------------------------------------------
# _ensure_session
# ---------------------------------------------------------------------------

class TestEnsureSession:
    async def test_creates_session_when_none(self, client):
        # Arrange
        assert client._session is None

        # Act
        with patch("src.exchanges.weex.client.aiohttp.ClientSession") as mock_cls:
            mock_cls.return_value = MagicMock(closed=False)
            await client._ensure_session()

        # Assert
        assert client._session is not None

    async def test_creates_session_when_closed(self, client):
        # Arrange - set a closed session
        closed_session = MagicMock()
        closed_session.closed = True
        client._session = closed_session

        # Act
        with patch("src.exchanges.weex.client.aiohttp.ClientSession") as mock_cls:
            new_session = MagicMock(closed=False)
            mock_cls.return_value = new_session
            await client._ensure_session()

        # Assert
        assert client._session is new_session

    async def test_does_not_recreate_when_open(self, client, mock_session):
        # Arrange
        client._session = mock_session

        # Act
        await client._ensure_session()

        # Assert - same session, no new one created
        assert client._session is mock_session


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestClose:
    async def test_close_closes_open_session(self, client, mock_session):
        # Arrange
        client._session = mock_session

        # Act
        await client.close()

        # Assert
        mock_session.close.assert_awaited_once()

    async def test_close_does_nothing_when_no_session(self, client):
        # Arrange - _session is None
        # Act / Assert - should not raise
        await client.close()

    async def test_close_does_nothing_when_session_already_closed(self, client):
        # Arrange
        session = MagicMock()
        session.closed = True
        client._session = session

        # Act
        await client.close()

        # Assert - close should NOT be called on an already-closed session
        session.close.assert_not_called()


# ---------------------------------------------------------------------------
# _request
# ---------------------------------------------------------------------------

class TestRequest:
    async def test_request_get_success(self, client, mock_session):
        # Arrange
        client._session = mock_session
        expected_data = {"accountEquity": "1000"}
        mock_session.request = MagicMock(
            return_value=_make_api_response(expected_data)
        )

        # Act
        result = await client._request("GET", "/api/v2/mix/account/account")

        # Assert
        assert result == expected_data

    async def test_request_post_with_data(self, client, mock_session):
        # Arrange
        client._session = mock_session
        post_data = {"symbol": "BTCUSDT", "side": "buy"}
        expected = {"orderId": "123456"}
        mock_session.request = MagicMock(
            return_value=_make_api_response(expected)
        )

        # Act
        result = await client._request("POST", "/api/v2/mix/order/place-order", data=post_data)

        # Assert
        assert result == expected
        call_kwargs = mock_session.request.call_args
        assert call_kwargs.kwargs["data"] == json.dumps(post_data)

    async def test_request_with_params_appends_query_string(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({"ticker": True})
        )

        # Act
        await client._request("GET", "/api/v2/mix/market/ticker", params={"symbol": "BTCUSDT"})

        # Assert
        call_kwargs = mock_session.request.call_args
        assert "symbol=BTCUSDT" in call_kwargs.kwargs["url"]

    async def test_request_raises_on_api_error_code(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_error_response(msg="Invalid symbol", code="40001")
        )

        # Act / Assert
        with pytest.raises(WeexClientError, match="Invalid symbol"):
            await client._request("GET", "/api/v2/mix/market/ticker")

    async def test_request_raises_on_http_non_200(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_http_error_response(status=500)
        )

        # Act / Assert
        with pytest.raises(WeexClientError):
            await client._request("GET", "/api/v2/mix/market/ticker")

    async def test_request_no_auth_uses_simple_headers(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({"lastPr": "95000"})
        )

        # Act
        await client._request("GET", "/api/v2/mix/market/ticker", auth=False)

        # Assert
        call_kwargs = mock_session.request.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "ACCESS-KEY" not in headers
        assert headers["Content-Type"] == "application/json"

    async def test_request_returns_full_result_when_no_data_key(self, client, mock_session):
        # Arrange - response has code=SUCCESS_CODE but no "data" key
        client._session = mock_session
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value={"code": SUCCESS_CODE, "msg": "ok"})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=ctx)

        # Act
        result = await client._request("GET", "/api/v2/test")

        # Assert - returns the full dict when "data" is missing (via .get default)
        assert result == {"code": SUCCESS_CODE, "msg": "ok"}

    async def test_request_with_empty_body_sends_none(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({"ok": True})
        )

        # Act
        await client._request("GET", "/api/v2/test")

        # Assert
        call_kwargs = mock_session.request.call_args
        assert call_kwargs.kwargs["data"] is None


# ---------------------------------------------------------------------------
# get_account_balance
# ---------------------------------------------------------------------------

class TestGetAccountBalance:
    async def test_returns_balance_from_list_with_usdt(self, client, mock_session):
        # Arrange - Weex returns list of coin balances
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([{
                "coinName": "USDT",
                "equity": "1500.50",
                "available": "1200.00",
                "unrealizePnl": "300.50",
            }])
        )

        # Act
        balance = await client.get_account_balance()

        # Assert
        assert isinstance(balance, Balance)
        assert balance.total == 1500.50
        assert balance.available == 1200.00
        assert balance.unrealized_pnl == 300.50

    async def test_returns_balance_from_list_with_susdt(self, client, mock_session):
        # Arrange - demo mode uses SUSDT
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([{
                "coinName": "SUSDT",
                "equity": "50000",
                "available": "48000",
                "unrealizePnl": "200",
            }])
        )

        # Act
        balance = await client.get_account_balance()

        # Assert
        assert balance.total == 50000.0
        assert balance.available == 48000.0

    async def test_returns_zero_balance_from_empty_list(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([])
        )

        # Act
        balance = await client.get_account_balance()

        # Assert
        assert balance.total == 0.0
        assert balance.available == 0.0
        assert balance.unrealized_pnl == 0.0


# ---------------------------------------------------------------------------
# place_market_order
# ---------------------------------------------------------------------------

class TestPlaceMarketOrder:
    async def test_place_long_market_order(self, client, mock_session):
        # Arrange
        client._session = mock_session
        # Leverage is set by trade_executor, not internally
        call_count = 0
        responses = [
            _make_api_response({"orderId": "ORD001"}),  # place order
        ]

        def side_effect(*args, **kwargs):
            nonlocal call_count
            resp = responses[min(call_count, len(responses) - 1)]
            call_count += 1
            return resp

        mock_session.request = MagicMock(side_effect=side_effect)

        # Act
        order = await client.place_market_order(
            symbol="BTCUSDT", side="long", size=0.01, leverage=10,
        )

        # Assert
        assert isinstance(order, Order)
        assert order.order_id == "ORD001"
        assert order.symbol == "BTCUSDT"
        assert order.side == "long"
        assert order.size == 0.01
        assert order.leverage == 10
        assert order.status == "filled"
        assert order.exchange == "weex"

    async def test_place_short_market_order(self, client, mock_session):
        # Arrange
        client._session = mock_session
        responses = [
            _make_api_response({"orderId": "ORD002"}),
        ]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            resp = responses[min(call_count, len(responses) - 1)]
            call_count += 1
            return resp

        mock_session.request = MagicMock(side_effect=side_effect)

        # Act
        order = await client.place_market_order(
            symbol="ETHUSDT", side="short", size=0.5, leverage=5,
        )

        # Assert
        assert order.order_id == "ORD002"
        assert order.side == "short"

    async def test_place_market_order_with_tp_sl(self, client, mock_session):
        # Arrange
        client._session = mock_session
        responses = [
            _make_api_response({}),
            _make_api_response({"orderId": "ORD003"}),
        ]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            resp = responses[min(call_count, len(responses) - 1)]
            call_count += 1
            return resp

        mock_session.request = MagicMock(side_effect=side_effect)

        # Act
        order = await client.place_market_order(
            symbol="BTCUSDT", side="long", size=0.01, leverage=10,
            take_profit=100000.0, stop_loss=90000.0,
        )

        # Assert
        assert order.take_profit == 100000.0
        assert order.stop_loss == 90000.0

    async def test_place_market_order_sends_correct_body(self, client, mock_session):
        # Arrange
        client._session = mock_session
        captured_bodies = []

        def capturing_side_effect(*args, **kwargs):
            body_str = kwargs.get("data", None)
            if body_str:
                captured_bodies.append(json.loads(body_str))
            return _make_api_response({"orderId": "ORD004"})

        mock_session.request = MagicMock(side_effect=capturing_side_effect)

        # Act
        await client.place_market_order(
            symbol="BTCUSDT", side="long", size=0.05, leverage=20,
            take_profit=96000.0, stop_loss=93000.0,
        )

        # Assert - the last POST should be the V3 order placement
        order_body = captured_bodies[-1]
        assert order_body["symbol"] == "BTCUSDT"  # V3 uses plain symbol
        assert order_body["side"] == "BUY"
        assert order_body["positionSide"] == "LONG"
        assert order_body["type"] == "MARKET"
        assert order_body["quantity"] == "0.05"
        assert order_body["tpTriggerPrice"] == "96000.0"
        assert order_body["slTriggerPrice"] == "93000.0"


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------

class TestCancelOrder:
    async def test_cancel_order_success(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({})
        )

        # Act
        result = await client.cancel_order("BTCUSDT", "ORD001")

        # Assert
        assert result is True

    async def test_cancel_order_returns_false_on_api_error(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_error_response(msg="Order not found", code="40001")
        )

        # Act
        result = await client.cancel_order("BTCUSDT", "INVALID_ORDER")

        # Assert
        assert result is False


# ---------------------------------------------------------------------------
# get_position
# ---------------------------------------------------------------------------

class TestGetPosition:
    async def test_returns_position_when_total_greater_than_zero(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([{
                "total": "0.5",
                "holdSide": "long",
                "openPriceAvg": "95000",
                "markPrice": "96000",
                "unrealizedPL": "500",
                "leverage": "10",
            }])
        )

        # Act
        pos = await client.get_position("BTCUSDT")

        # Assert
        assert isinstance(pos, Position)
        assert pos.symbol == "BTCUSDT"
        assert pos.side == "long"
        assert pos.size == 0.5
        assert pos.entry_price == 95000.0
        assert pos.current_price == 96000.0
        assert pos.unrealized_pnl == 500.0
        assert pos.leverage == 10
        assert pos.exchange == "weex"

    async def test_returns_none_when_no_positions(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([])
        )

        # Act
        pos = await client.get_position("BTCUSDT")

        # Assert
        assert pos is None

    async def test_returns_none_when_total_is_zero(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([{
                "total": "0",
                "holdSide": "long",
                "openPriceAvg": "95000",
                "markPrice": "96000",
                "unrealizedPL": "0",
                "leverage": "10",
            }])
        )

        # Act
        pos = await client.get_position("BTCUSDT")

        # Assert
        assert pos is None

    async def test_returns_position_from_dict_response(self, client, mock_session):
        # Arrange - API returns a dict instead of list
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({
                "total": "1.0",
                "holdSide": "short",
                "openPriceAvg": "3500",
                "markPrice": "3400",
                "unrealizedPL": "100",
                "leverage": "5",
            })
        )

        # Act
        pos = await client.get_position("ETHUSDT")

        # Assert
        assert pos is not None
        assert pos.side == "short"
        assert pos.size == 1.0

    async def test_returns_none_when_data_is_empty_dict(self, client, mock_session):
        # Arrange - data is None/falsy
        client._session = mock_session
        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(return_value={"code": SUCCESS_CODE, "data": None})
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=ctx)

        # Act
        pos = await client.get_position("BTCUSDT")

        # Assert
        assert pos is None

    async def test_skips_zero_positions_and_returns_first_nonzero(self, client, mock_session):
        # Arrange - multiple positions, first has total=0
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([
                {"total": "0", "holdSide": "long", "openPriceAvg": "0",
                 "markPrice": "0", "unrealizedPL": "0", "leverage": "1"},
                {"total": "2.5", "holdSide": "short", "openPriceAvg": "3500",
                 "markPrice": "3400", "unrealizedPL": "250", "leverage": "5"},
            ])
        )

        # Act
        pos = await client.get_position("ETHUSDT")

        # Assert
        assert pos is not None
        assert pos.side == "short"
        assert pos.size == 2.5


# ---------------------------------------------------------------------------
# get_open_positions
# ---------------------------------------------------------------------------

class TestGetOpenPositions:
    async def test_returns_list_of_positions(self, client, mock_session):
        # Arrange - symbols come back in Weex API format (demo: cmt_btcusdt)
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([
                {"symbol": "cmt_btcusdt", "total": "0.5", "holdSide": "long",
                 "openPriceAvg": "95000", "markPrice": "96000",
                 "unrealizedPL": "500", "leverage": "10"},
                {"symbol": "cmt_ethusdt", "total": "2.0", "holdSide": "short",
                 "openPriceAvg": "3500", "markPrice": "3400",
                 "unrealizedPL": "200", "leverage": "5"},
            ])
        )

        # Act
        positions = await client.get_open_positions()

        # Assert
        assert len(positions) == 2
        assert all(isinstance(p, Position) for p in positions)
        assert positions[0].symbol == "BTCUSDT"
        assert positions[1].symbol == "ETHUSDT"

    async def test_filters_out_zero_total_positions(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([
                {"symbol": "cmt_btcusdt", "total": "0", "holdSide": "long",
                 "openPriceAvg": "0", "markPrice": "0",
                 "unrealizedPL": "0", "leverage": "1"},
                {"symbol": "cmt_ethusdt", "total": "1.0", "holdSide": "short",
                 "openPriceAvg": "3500", "markPrice": "3400",
                 "unrealizedPL": "100", "leverage": "5"},
            ])
        )

        # Act
        positions = await client.get_open_positions()

        # Assert
        assert len(positions) == 1
        assert positions[0].symbol == "ETHUSDT"

    async def test_returns_empty_list_when_no_positions(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([])
        )

        # Act
        positions = await client.get_open_positions()

        # Assert
        assert positions == []

    async def test_returns_empty_list_when_data_is_dict(self, client, mock_session):
        # Arrange - if API returns a dict instead of list, iteration yields empty
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({"some": "dict"})
        )

        # Act
        positions = await client.get_open_positions()

        # Assert
        assert positions == []


# ---------------------------------------------------------------------------
# set_leverage
# ---------------------------------------------------------------------------

class TestSetLeverage:
    async def test_set_leverage_success(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({})
        )

        # Act
        result = await client.set_leverage("BTCUSDT", 20)

        # Assert
        assert result is True
        assert mock_session.request.call_count == 1

    async def test_set_leverage_returns_true_on_error(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_error_response(msg="Already set", code="40001")
        )

        # Act
        result = await client.set_leverage("BTCUSDT", 10)

        # Assert - returns False on API error
        assert result is False


# ---------------------------------------------------------------------------
# close_position
# ---------------------------------------------------------------------------

class TestClosePosition:
    async def test_close_long_position(self, client, mock_session):
        # Arrange
        client._session = mock_session
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # get_position
                return _make_api_response([{
                    "total": "0.5", "holdSide": "long",
                    "openPriceAvg": "95000", "markPrice": "96000",
                    "unrealizedPL": "500", "leverage": "10",
                }])
            else:
                # place close order
                return _make_api_response({"orderId": "CLOSE001"})

        mock_session.request = MagicMock(side_effect=side_effect)

        # Act
        order = await client.close_position("BTCUSDT", "long")

        # Assert
        assert isinstance(order, Order)
        assert order.order_id == "CLOSE001"
        assert order.side == "long"
        assert order.size == 0.5

    async def test_close_short_position(self, client, mock_session):
        # Arrange
        client._session = mock_session
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_api_response([{
                    "total": "2.0", "holdSide": "short",
                    "openPriceAvg": "3500", "markPrice": "3400",
                    "unrealizedPL": "200", "leverage": "5",
                }])
            else:
                return _make_api_response({"orderId": "CLOSE002"})

        mock_session.request = MagicMock(side_effect=side_effect)

        # Act
        order = await client.close_position("ETHUSDT", "short")

        # Assert
        assert order is not None
        assert order.order_id == "CLOSE002"

    async def test_close_position_returns_none_when_no_position(self, client, mock_session):
        # Arrange - get_position returns no open position
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([])
        )

        # Act
        result = await client.close_position("BTCUSDT", "long")

        # Assert
        assert result is None

    async def test_close_position_sends_flash_close_body(self, client, mock_session):
        # Arrange
        client._session = mock_session
        captured_bodies = []
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            body_str = kwargs.get("data", None)
            if body_str:
                captured_bodies.append(json.loads(body_str))
            if call_count == 1:
                return _make_api_response([{
                    "total": "1.0", "holdSide": "long",
                    "openPriceAvg": "95000", "markPrice": "96000",
                    "unrealizedPL": "100", "leverage": "10",
                }])
            return _make_api_response({"orderId": "CLOSE003"})

        mock_session.request = MagicMock(side_effect=side_effect)

        # Act
        await client.close_position("BTCUSDT", "long")

        # Assert - V3 flash-close sends plain symbol
        close_body = captured_bodies[-1]
        assert close_body["symbol"] == "BTCUSDT"  # V3 plain symbol


# ---------------------------------------------------------------------------
# get_ticker
# ---------------------------------------------------------------------------

class TestGetTicker:
    async def test_get_ticker_from_dict(self, client, mock_session):
        # Arrange - Weex ticker returns raw data with 'last', 'best_bid', 'best_ask'
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({
                "last": "95000.5",
                "best_bid": "94999.0",
                "best_ask": "95001.0",
                "volume_24h": "12345.678",
            })
        )

        # Act
        ticker = await client.get_ticker("BTCUSDT")

        # Assert
        assert isinstance(ticker, Ticker)
        assert ticker.symbol == "BTCUSDT"
        assert ticker.last_price == 95000.5
        assert ticker.bid == 94999.0
        assert ticker.ask == 95001.0
        assert ticker.volume_24h == 12345.678

    async def test_get_ticker_from_list(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([{
                "last": "3500.0",
                "best_bid": "3499.0",
                "best_ask": "3501.0",
                "volume_24h": "50000.0",
            }])
        )

        # Act
        ticker = await client.get_ticker("ETHUSDT")

        # Assert
        assert ticker.last_price == 3500.0

    async def test_get_ticker_from_empty_list(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([])
        )

        # Act
        ticker = await client.get_ticker("BTCUSDT")

        # Assert - all zeros from empty dict
        assert ticker.last_price == 0.0
        assert ticker.bid == 0.0
        assert ticker.ask == 0.0
        assert ticker.volume_24h == 0.0

    async def test_get_ticker_uses_no_auth(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({"last": "95000"})
        )

        # Act
        await client.get_ticker("BTCUSDT")

        # Assert - check that auth=False means no ACCESS-KEY header
        call_kwargs = mock_session.request.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "ACCESS-KEY" not in headers


# ---------------------------------------------------------------------------
# get_funding_rate
# ---------------------------------------------------------------------------

class TestGetFundingRate:
    async def test_get_funding_rate_finds_matching_currency(self, client, mock_session):
        # V3: GET /capi/v3/market/premiumIndex?symbol=BTCUSDT returns single dict
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response(
                {"symbol": "BTCUSDT", "lastFundingRate": "0.0001", "markPrice": "60000"}
            )
        )

        rate = await client.get_funding_rate("BTCUSDT")

        assert isinstance(rate, FundingRateInfo)
        assert rate.symbol == "BTCUSDT"
        assert rate.current_rate == 0.0001

    async def test_get_funding_rate_matches_eth(self, client, mock_session):
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response(
                {"symbol": "ETHUSDT", "lastFundingRate": "-0.0005"}
            )
        )

        rate = await client.get_funding_rate("ETHUSDT")

        assert rate.current_rate == -0.0005

    async def test_get_funding_rate_from_empty_list(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([])
        )

        # Act
        rate = await client.get_funding_rate("BTCUSDT")

        # Assert
        assert rate.current_rate == 0.0

    async def test_get_funding_rate_uses_no_auth(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([
                {"baseCurrency": "BTC_USDT", "fundingRate": "0.0001"},
            ])
        )

        # Act
        await client.get_funding_rate("BTCUSDT")

        # Assert
        call_kwargs = mock_session.request.call_args
        headers = call_kwargs.kwargs["headers"]
        assert "ACCESS-KEY" not in headers


# ---------------------------------------------------------------------------
# check_affiliate_uid
# ---------------------------------------------------------------------------

class TestCheckAffiliateUid:
    async def test_returns_true_when_uid_found_in_list(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([
                {"uid": "12345", "volume": "1000"},
                {"uid": "67890", "volume": "500"},
            ])
        )

        # Act
        result = await client.check_affiliate_uid("12345")

        # Assert
        assert result is True

    async def test_returns_false_when_uid_not_found(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([
                {"uid": "99999", "volume": "1000"},
            ])
        )

        # Act
        result = await client.check_affiliate_uid("12345")

        # Assert
        assert result is False

    async def test_returns_true_from_records_dict(self, client, mock_session):
        # Arrange - data is a dict with "channelUserInfoItemList" key
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({
                "channelUserInfoItemList": [{"uid": "54321", "volume": "200"}]
            })
        )

        # Act
        result = await client.check_affiliate_uid("54321")

        # Assert
        assert result is True

    async def test_returns_false_on_exception(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_error_response(msg="Auth error", code="40100")
        )

        # Act
        result = await client.check_affiliate_uid("12345")

        # Assert
        assert result is False

    async def test_returns_false_on_unexpected_exception(self, client, mock_session):
        # Arrange - simulate a completely unexpected error
        client._session = mock_session

        response = AsyncMock()
        response.status = 200
        response.json = AsyncMock(side_effect=Exception("Network timeout"))
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session.request = MagicMock(return_value=ctx)

        # Act
        result = await client.check_affiliate_uid("12345")

        # Assert
        assert result is False

    async def test_returns_false_from_empty_records(self, client, mock_session):
        # Arrange
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({"records": []})
        )

        # Act
        result = await client.check_affiliate_uid("12345")

        # Assert
        assert result is False

    async def test_uid_comparison_uses_string_matching(self, client, mock_session):
        # Arrange - uid stored as int in response
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([{"uid": 12345, "volume": "100"}])
        )

        # Act
        result = await client.check_affiliate_uid("12345")

        # Assert
        assert result is True


# ---------------------------------------------------------------------------
# WeexClientError
# ---------------------------------------------------------------------------

class TestWeexClientError:
    def test_is_exception_subclass(self):
        from src.exceptions import ExchangeError
        assert issubclass(WeexClientError, Exception)
        assert issubclass(WeexClientError, ExchangeError)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(WeexClientError, match=r"test error"):
            raise WeexClientError("test error")
        err = WeexClientError("test error")
        assert err.exchange == "weex"


# ---------------------------------------------------------------------------
# V3 Migration (issue #114)
# ---------------------------------------------------------------------------

class TestV3Migration:
    async def test_account_balance_uses_v3_endpoint_and_shape(self, client, mock_session):
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([{
                "asset": "USDT",
                "balance": "1000.50",
                "availableBalance": "950.00",
                "frozen": "50.50",
                "unrealizePnl": "12.34",
            }])
        )

        bal = await client.get_account_balance()

        assert bal.total == 1000.50
        assert bal.available == 950.00
        assert bal.unrealized_pnl == 12.34
        call_url = mock_session.request.call_args.kwargs.get("url") or mock_session.request.call_args[1]["url"]
        assert "/capi/v3/account/balance" in call_url

    async def test_funding_rate_uses_v3_premium_index(self, client, mock_session):
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({
                "symbol": "BTCUSDT",
                "lastFundingRate": "0.0002",
            })
        )

        rate = await client.get_funding_rate("BTCUSDT")

        assert rate.current_rate == 0.0002
        call_url = mock_session.request.call_args.kwargs.get("url") or mock_session.request.call_args[1]["url"]
        assert "/capi/v3/market/premiumIndex" in call_url
        assert "symbol=BTCUSDT" in call_url

    async def test_cancel_order_uses_delete_method(self, client, mock_session):
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response({"orderId": "123", "success": True})
        )

        result = await client.cancel_order("BTCUSDT", "123")

        assert result is True
        method = mock_session.request.call_args.kwargs.get("method") or mock_session.request.call_args[1]["method"]
        url = mock_session.request.call_args.kwargs.get("url") or mock_session.request.call_args[1]["url"]
        assert method == "DELETE"
        assert "/capi/v3/order" in url

    async def test_get_position_uses_v3_path_and_plain_symbol(self, client, mock_session):
        client._session = mock_session
        mock_session.request = MagicMock(
            return_value=_make_api_response([{
                "symbol": "BTCUSDT",
                "side": "LONG",
                "size": "0.5",
                "leverage": 10,
                "openValue": "30000",
                "markPrice": "61000",
                "unrealizePnl": "500",
            }])
        )

        pos = await client.get_position("BTCUSDT")

        assert pos is not None
        assert pos.symbol == "BTCUSDT"
        assert pos.side == "long"
        assert pos.size == 0.5
        url = mock_session.request.call_args.kwargs.get("url") or mock_session.request.call_args[1]["url"]
        assert "/capi/v3/account/position/singlePosition" in url
        assert "symbol=BTCUSDT" in url
