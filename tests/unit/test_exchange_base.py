"""Tests for exchange base classes."""

import pytest

from src.exchanges.base import ExchangeClient, ExchangeWebSocket
from src.exchanges.types import Balance, Order, Ticker, FundingRateInfo


class ConcreteClient(ExchangeClient):
    """Minimal concrete implementation for testing the base class."""

    async def get_account_balance(self): return Balance(total=1000, available=500, currency="USDT")
    async def place_market_order(self, symbol, side, size, leverage, take_profit=None, stop_loss=None):
        return Order(order_id="1", symbol=symbol, side=side, size=size)
    async def cancel_order(self, symbol, order_id): return True
    async def close_position(self, symbol, side): return None
    async def get_position(self, symbol): return None
    async def get_open_positions(self): return []
    async def set_leverage(self, symbol, leverage): return True
    async def get_ticker(self, symbol): return Ticker(symbol=symbol, last_price=50000)
    async def get_funding_rate(self, symbol): return FundingRateInfo(symbol=symbol, rate=0.0001)
    async def close(self): pass
    @property
    def exchange_name(self): return "test"
    @property
    def supports_demo(self): return True


class ConcreteWS(ExchangeWebSocket):
    """Minimal concrete implementation for testing the WS base class."""

    async def connect(self): self._connected = True
    async def subscribe_positions(self, symbols, callback): pass
    async def subscribe_orders(self, callback): pass
    async def subscribe_ticker(self, symbols, callback): pass
    async def disconnect(self): self._connected = False


class TestExchangeClientBase:
    """Tests for the ExchangeClient ABC."""

    def test_init_stores_credentials(self):
        client = ConcreteClient(api_key="key", api_secret="secret", passphrase="pass", demo_mode=True)
        assert client.api_key == "key"
        assert client.api_secret == "secret"
        assert client.passphrase == "pass"
        assert client.demo_mode is True

    @pytest.mark.asyncio
    async def test_default_get_order_fees(self):
        client = ConcreteClient(api_key="k", api_secret="s")
        fees = await client.get_order_fees("BTCUSDT", "order123")
        assert fees == 0.0

    @pytest.mark.asyncio
    async def test_default_get_trade_total_fees(self):
        client = ConcreteClient(api_key="k", api_secret="s")
        fees = await client.get_trade_total_fees("BTCUSDT", "entry1", "close1")
        assert fees == 0.0

    @pytest.mark.asyncio
    async def test_default_get_fill_price(self):
        client = ConcreteClient(api_key="k", api_secret="s")
        price = await client.get_fill_price("BTCUSDT", "order1")
        assert price is None

    @pytest.mark.asyncio
    async def test_default_get_funding_fees(self):
        client = ConcreteClient(api_key="k", api_secret="s")
        fees = await client.get_funding_fees("BTCUSDT", 0, 9999999)
        assert fees == 0.0

    def test_exchange_name_property(self):
        client = ConcreteClient(api_key="k", api_secret="s")
        assert client.exchange_name == "test"

    def test_supports_demo_property(self):
        client = ConcreteClient(api_key="k", api_secret="s")
        assert client.supports_demo is True


class TestExchangeWebSocketBase:
    """Tests for the ExchangeWebSocket ABC."""

    def test_init_stores_credentials(self):
        ws = ConcreteWS(api_key="k", api_secret="s", passphrase="p", demo_mode=False)
        assert ws.api_key == "k"
        assert ws.demo_mode is False

    def test_initial_not_connected(self):
        ws = ConcreteWS()
        assert ws.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_sets_connected(self):
        ws = ConcreteWS()
        await ws.connect()
        assert ws.is_connected is True

    @pytest.mark.asyncio
    async def test_disconnect_clears_connected(self):
        ws = ConcreteWS()
        await ws.connect()
        await ws.disconnect()
        assert ws.is_connected is False
