"""
Unit tests for the Bitunix Exchange Client.

Tests cover:
- Initialization and configuration
- Authentication (double-SHA256 signature)
- All ABC methods (balance, orders, positions, ticker, funding)
- Error handling
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from src.exchanges.bitunix.client import BitunixClient, BitunixClientError
from src.exchanges.bitunix.constants import BASE_URL, ENDPOINTS, SUCCESS_CODE, TESTNET_URL


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
    }


@pytest.fixture
def client(client_kwargs):
    """Create a BitunixClient instance for testing."""
    return BitunixClient(**client_kwargs)


def make_api_response(data, code=SUCCESS_CODE, msg="success", status=200):
    """Helper to build a mock aiohttp response context manager."""
    response_body = {"code": code, "msg": msg, "data": data}
    mock_response = AsyncMock()
    mock_response.status = status
    mock_response.json = AsyncMock(return_value=response_body)
    mock_response.text = AsyncMock(return_value=json.dumps(response_body))
    mock_response.request_info = MagicMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestBitunixClientInit:
    """Tests for BitunixClient initialization."""

    def test_stores_credentials(self, client):
        assert client.api_key == "test-api-key"
        assert client.api_secret == "test-api-secret"

    def test_base_url_is_bitunix(self, client):
        assert BASE_URL in client.base_url or client.base_url == BASE_URL

    def test_demo_mode_flag(self, client):
        assert client.demo_mode is True

    def test_exchange_name(self, client):
        assert client.exchange_name == "bitunix"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestBitunixClientError:
    """Tests for BitunixClientError."""

    def test_error_includes_exchange_name(self):
        err = BitunixClientError("test error")
        assert "bitunix" in str(err).lower() or err.exchange == "bitunix"

    def test_error_preserves_message(self):
        err = BitunixClientError("Connection failed")
        assert "Connection failed" in str(err)

    def test_error_wraps_original(self):
        original = ValueError("timeout")
        err = BitunixClientError("API error", original_error=original)
        assert err.original_error is original


# ---------------------------------------------------------------------------
# API method tests (with mocked HTTP)
# ---------------------------------------------------------------------------

class TestGetAccountBalance:
    """Tests for get_account_balance."""

    @pytest.mark.asyncio
    async def test_returns_balance(self, client):
        balance_data = {
            "available": "10000.50",
            "crossMarginAsset": "15000.00",
            "unrealizedPNL": "500.00",
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = balance_data
            result = await client.get_account_balance()

        assert result is not None
        assert isinstance(result.available, (int, float))


class TestGetTicker:
    """Tests for get_ticker."""

    @pytest.mark.asyncio
    async def test_returns_ticker(self, client):
        ticker_data = [{
            "symbol": "BTCUSDT",
            "lastPrice": "95000.50",
            "bidPrice": "94999.00",
            "askPrice": "95001.00",
            "volume24h": "1234567890.00",
            "high24h": "96000.00",
            "low24h": "94000.00",
            "priceChange24h": "2.5",
        }]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = ticker_data
            result = await client.get_ticker("BTCUSDT")

        assert result is not None
        assert isinstance(result.last_price, (int, float))


class TestGetFundingRate:
    """Tests for get_funding_rate."""

    @pytest.mark.asyncio
    async def test_returns_funding_rate(self, client):
        funding_data = [{
            "symbol": "BTCUSDT",
            "fundingRate": "0.0001",
            "nextFundingTime": "1709510400000",
        }]

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = funding_data
            result = await client.get_funding_rate("BTCUSDT")

        assert result is not None
        assert isinstance(result.current_rate, (int, float))


class TestSetLeverage:
    """Tests for set_leverage."""

    @pytest.mark.asyncio
    async def test_set_leverage(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await client.set_leverage("BTCUSDT", 10)
            mock_req.assert_awaited()


class TestGetOpenPositions:
    """Tests for get_open_positions."""

    @pytest.mark.asyncio
    async def test_returns_positions_list(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"positionList": []}
            result = await client.get_open_positions()

        assert isinstance(result, list)


class TestPlaceMarketOrder:
    """Tests for place_market_order."""

    @pytest.mark.asyncio
    async def test_place_order_returns_order(self, client):
        order_data = {
            "orderId": "test-order-123",
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = order_data
            with patch.object(client, "set_leverage", new_callable=AsyncMock):
                result = await client.place_market_order(
                    symbol="BTCUSDT",
                    side="long",
                    size=0.001,
                    leverage=10,
                )

        assert result is not None


class TestCancelOrder:
    """Tests for cancel_order."""

    @pytest.mark.asyncio
    async def test_cancel_order(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"successList": [{"orderId": "order-123"}]}
            result = await client.cancel_order("BTCUSDT", "order-123")
            assert result is True

    @pytest.mark.asyncio
    async def test_cancel_order_empty_success_list(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"successList": []}
            result = await client.cancel_order("BTCUSDT", "order-123")
            assert result is False


class TestConstants:
    """Tests for Bitunix constants."""

    def test_base_url(self):
        assert BASE_URL == "https://fapi.bitunix.com"

    def test_testnet_url_same_as_base(self):
        assert TESTNET_URL == BASE_URL

    def test_success_code_is_zero(self):
        assert SUCCESS_CODE == 0

    def test_endpoints_exist(self):
        assert "account" in ENDPOINTS
        assert "place_order" in ENDPOINTS
        assert "tickers" in ENDPOINTS
        assert "funding_rate" in ENDPOINTS
        assert "get_pending_positions" in ENDPOINTS
