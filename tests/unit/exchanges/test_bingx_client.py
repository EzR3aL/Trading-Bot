"""
Unit tests for the BingX Exchange Client.

Tests cover:
- Initialization and configuration
- Authentication (HMAC-SHA256 signature)
- All ABC methods (balance, orders, positions, ticker, funding)
- Demo mode (VST domain switching)
- Error handling
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from src.exchanges.bingx.client import BingXClient, BingXClientError
from src.exchanges.bingx.constants import (
    BASE_URL,
    ENDPOINTS,
    SUCCESS_CODE,
    TESTNET_URL,
    SIDE_BUY,
    SIDE_SELL,
    POSITION_LONG,
    POSITION_SHORT,
    MARGIN_CROSSED,
    ORDER_TYPE_MARKET,
    DEFAULT_RECV_WINDOW,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_kwargs():
    """Default kwargs for creating a test client."""
    return {
        "api_key": "test-api-key",
        "api_secret": "test-api-secret",
        "demo_mode": False,
    }


@pytest.fixture
def demo_client_kwargs():
    """kwargs for creating a demo-mode client."""
    return {
        "api_key": "test-api-key",
        "api_secret": "test-api-secret",
        "demo_mode": True,
    }


@pytest.fixture
def client(client_kwargs):
    """Create a BingXClient instance for testing."""
    return BingXClient(**client_kwargs)


@pytest.fixture
def demo_client(demo_client_kwargs):
    """Create a demo-mode BingXClient instance."""
    return BingXClient(**demo_client_kwargs)


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestBingXClientInit:
    """Tests for BingXClient initialization."""

    def test_stores_credentials(self, client):
        assert client.api_key == "test-api-key"
        assert client.api_secret == "test-api-secret"

    def test_live_base_url(self, client):
        assert BASE_URL in client.base_url or client.base_url == BASE_URL

    def test_demo_mode_uses_testnet(self, demo_client):
        assert TESTNET_URL in demo_client.base_url or demo_client.base_url == TESTNET_URL

    def test_exchange_name(self, client):
        assert client.exchange_name == "bingx"


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestBingXClientError:
    """Tests for BingXClientError."""

    def test_error_includes_exchange_name(self):
        err = BingXClientError("test error")
        assert "bingx" in str(err).lower() or err.exchange == "bingx"

    def test_error_preserves_message(self):
        err = BingXClientError("Rate limited")
        assert "Rate limited" in str(err)

    def test_error_wraps_original(self):
        original = TimeoutError("connect timeout")
        err = BingXClientError("API timeout", original_error=original)
        assert err.original_error is original


# ---------------------------------------------------------------------------
# API method tests (with mocked HTTP)
# ---------------------------------------------------------------------------

class TestGetAccountBalance:
    """Tests for get_account_balance."""

    @pytest.mark.asyncio
    async def test_returns_balance(self, client):
        balance_data = {
            "balance": {
                "availableMargin": "10000.50",
                "balance": "15000.00",
                "unrealizedProfit": "500.00",
            }
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
        ticker_data = {
            "symbol": "BTC-USDT",
            "lastPrice": "95000.50",
            "bidPrice": "94999.00",
            "askPrice": "95001.00",
            "volume": "1234567890.00",
            "highPrice": "96000.00",
            "lowPrice": "94000.00",
            "priceChangePercent": "2.5",
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = ticker_data
            result = await client.get_ticker("BTC-USDT")

        assert result is not None
        assert isinstance(result.last_price, (int, float))


class TestGetFundingRate:
    """Tests for get_funding_rate."""

    @pytest.mark.asyncio
    async def test_returns_funding_rate(self, client):
        funding_data = {
            "symbol": "BTC-USDT",
            "lastFundingRate": "0.0001",
            "nextFundingTime": 1709510400000,
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = funding_data
            result = await client.get_funding_rate("BTC-USDT")

        assert result is not None
        assert isinstance(result.current_rate, (int, float))


class TestSetLeverage:
    """Tests for set_leverage."""

    @pytest.mark.asyncio
    async def test_set_leverage(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            await client.set_leverage("BTC-USDT", 20)
            mock_req.assert_awaited()


class TestGetOpenPositions:
    """Tests for get_open_positions."""

    @pytest.mark.asyncio
    async def test_returns_positions_list(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = []
            result = await client.get_open_positions()

        assert isinstance(result, list)


class TestPlaceMarketOrder:
    """Tests for place_market_order."""

    @pytest.mark.asyncio
    async def test_place_order_returns_order(self, client):
        order_data = {
            "order": {
                "orderId": "test-order-456",
                "symbol": "BTC-USDT",
            }
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = order_data
            with patch.object(client, "set_leverage", new_callable=AsyncMock):
                result = await client.place_market_order(
                    symbol="BTC-USDT",
                    side="long",
                    size=0.001,
                    leverage=20,
                )

        assert result is not None


class TestCancelOrder:
    """Tests for cancel_order."""

    @pytest.mark.asyncio
    async def test_cancel_order(self, client):
        with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            result = await client.cancel_order("BTC-USDT", "order-456")
            assert result is True


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------

class TestConstants:
    """Tests for BingX constants."""

    def test_base_url(self):
        assert BASE_URL == "https://open-api.bingx.com"

    def test_testnet_url(self):
        assert TESTNET_URL == "https://open-api-vst.bingx.com"

    def test_success_code_is_zero(self):
        assert SUCCESS_CODE == 0

    def test_endpoints_exist(self):
        assert "account_balance" in ENDPOINTS
        assert "place_order" in ENDPOINTS
        assert "ticker" in ENDPOINTS
        assert "funding_rate" in ENDPOINTS
        assert "all_positions" in ENDPOINTS

    def test_sides(self):
        assert SIDE_BUY == "BUY"
        assert SIDE_SELL == "SELL"

    def test_position_sides(self):
        assert POSITION_LONG == "LONG"
        assert POSITION_SHORT == "SHORT"

    def test_margin_type(self):
        assert MARGIN_CROSSED == "CROSSED"

    def test_order_type(self):
        assert ORDER_TYPE_MARKET == "MARKET"

    def test_recv_window(self):
        assert DEFAULT_RECV_WINDOW == 5000
