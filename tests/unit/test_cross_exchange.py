"""
Tests for cross-exchange arbitrage module.

Tests ExchangeAdapter base, ExchangeRegistry, and ArbScanner.
"""

import pytest
from datetime import datetime
from typing import Dict, List, Optional

from src.exchanges.base import (
    ExchangeAdapter,
    ExchangeTicker,
    ExchangeBalance,
    ExchangeFundingRate,
)
from src.exchanges.registry import ExchangeRegistry
from src.exchanges.arb_scanner import ArbScanner, ArbOpportunity, ArbType


# ==================== Mock Exchange Adapter ====================


class MockExchangeAdapter(ExchangeAdapter):
    """Mock exchange adapter for testing."""

    def __init__(self, name: str, tickers: Optional[Dict[str, ExchangeTicker]] = None,
                 funding_rates: Optional[Dict[str, ExchangeFundingRate]] = None):
        super().__init__(name)
        self._tickers = tickers or {}
        self._funding_rates = funding_rates or {}
        self._balances: Dict[str, ExchangeBalance] = {}

    async def connect(self):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    async def get_ticker(self, symbol: str) -> ExchangeTicker:
        if symbol in self._tickers:
            return self._tickers[symbol]
        raise ValueError(f"No ticker for {symbol}")

    async def get_tickers(self, symbols: List[str]) -> Dict[str, ExchangeTicker]:
        return {s: self._tickers[s] for s in symbols if s in self._tickers}

    async def get_funding_rate(self, symbol: str) -> ExchangeFundingRate:
        if symbol in self._funding_rates:
            return self._funding_rates[symbol]
        raise ValueError(f"No funding rate for {symbol}")

    async def get_balance(self, currency: str = "USDT") -> ExchangeBalance:
        if currency in self._balances:
            return self._balances[currency]
        return ExchangeBalance(exchange=self.name, currency=currency,
                               available=0.0, locked=0.0, total=0.0)

    async def get_supported_symbols(self) -> List[str]:
        return list(self._tickers.keys())


# ==================== ExchangeTicker Tests ====================


class TestExchangeTicker:
    """Tests for ExchangeTicker dataclass."""

    def test_basic_creation(self):
        ticker = ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=50000.0, ask=50010.0, last=50005.0, volume_24h=1000.0,
        )
        assert ticker.exchange == "bitget"
        assert ticker.symbol == "BTCUSDT"
        assert ticker.bid == 50000.0
        assert ticker.ask == 50010.0

    def test_mid_price(self):
        ticker = ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=50000.0, ask=50010.0, last=50005.0, volume_24h=1000.0,
        )
        assert ticker.mid == pytest.approx(50005.0)

    def test_mid_price_zero_bid_ask(self):
        ticker = ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=0.0, ask=0.0, last=50005.0, volume_24h=1000.0,
        )
        assert ticker.mid == 50005.0

    def test_spread_pct(self):
        ticker = ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=50000.0, ask=50100.0, last=50050.0, volume_24h=1000.0,
        )
        expected = ((50100.0 - 50000.0) / 50050.0) * 100
        assert ticker.spread_pct == pytest.approx(expected)

    def test_spread_pct_zero_mid(self):
        ticker = ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=0.0, ask=0.0, last=0.0, volume_24h=0.0,
        )
        assert ticker.spread_pct == 0.0

    def test_to_dict(self):
        ticker = ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=50000.0, ask=50010.0, last=50005.0, volume_24h=1000.0,
        )
        d = ticker.to_dict()
        assert d["exchange"] == "bitget"
        assert d["symbol"] == "BTCUSDT"
        assert "mid" in d
        assert "spread_pct" in d
        assert "timestamp" in d


# ==================== ExchangeBalance Tests ====================


class TestExchangeBalance:
    """Tests for ExchangeBalance dataclass."""

    def test_basic_creation(self):
        balance = ExchangeBalance(
            exchange="bitget", currency="USDT",
            available=5000.0, locked=1000.0, total=6000.0,
        )
        assert balance.available == 5000.0
        assert balance.locked == 1000.0
        assert balance.total == 6000.0

    def test_to_dict(self):
        balance = ExchangeBalance(
            exchange="bitget", currency="USDT",
            available=5000.0, locked=1000.0, total=6000.0,
        )
        d = balance.to_dict()
        assert d["exchange"] == "bitget"
        assert d["currency"] == "USDT"
        assert d["available"] == 5000.0


# ==================== ExchangeFundingRate Tests ====================


class TestExchangeFundingRate:
    """Tests for ExchangeFundingRate dataclass."""

    def test_basic_creation(self):
        rate = ExchangeFundingRate(
            exchange="bitget", symbol="BTCUSDT", rate=0.0005,
        )
        assert rate.rate == 0.0005
        assert rate.next_funding_time is None

    def test_to_dict(self):
        rate = ExchangeFundingRate(
            exchange="bitget", symbol="BTCUSDT", rate=0.0005,
        )
        d = rate.to_dict()
        assert d["rate"] == 0.0005
        assert d["rate_pct"] == "0.0500%"
        assert d["next_funding_time"] is None

    def test_to_dict_with_funding_time(self):
        funding_time = datetime(2025, 1, 1, 8, 0, 0)
        rate = ExchangeFundingRate(
            exchange="bitget", symbol="BTCUSDT",
            rate=0.0005, next_funding_time=funding_time,
        )
        d = rate.to_dict()
        assert d["next_funding_time"] == "2025-01-01T08:00:00"


# ==================== ExchangeAdapter Tests ====================


class TestExchangeAdapter:
    """Tests for the abstract ExchangeAdapter via MockExchangeAdapter."""

    def test_initial_state(self):
        adapter = MockExchangeAdapter("test_exchange")
        assert adapter.name == "test_exchange"
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        adapter = MockExchangeAdapter("test_exchange")
        await adapter.connect()
        assert adapter.is_connected is True
        await adapter.disconnect()
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_get_ticker(self):
        ticker = ExchangeTicker(
            exchange="test", symbol="BTCUSDT",
            bid=50000.0, ask=50010.0, last=50005.0, volume_24h=1000.0,
        )
        adapter = MockExchangeAdapter("test", tickers={"BTCUSDT": ticker})
        result = await adapter.get_ticker("BTCUSDT")
        assert result.bid == 50000.0

    @pytest.mark.asyncio
    async def test_get_ticker_missing(self):
        adapter = MockExchangeAdapter("test")
        with pytest.raises(ValueError):
            await adapter.get_ticker("BTCUSDT")

    @pytest.mark.asyncio
    async def test_get_funding_rate(self):
        rate = ExchangeFundingRate(exchange="test", symbol="BTCUSDT", rate=0.001)
        adapter = MockExchangeAdapter("test", funding_rates={"BTCUSDT": rate})
        result = await adapter.get_funding_rate("BTCUSDT")
        assert result.rate == 0.001

    @pytest.mark.asyncio
    async def test_get_balance_default(self):
        adapter = MockExchangeAdapter("test")
        balance = await adapter.get_balance("USDT")
        assert balance.total == 0.0

    @pytest.mark.asyncio
    async def test_get_supported_symbols(self):
        ticker = ExchangeTicker(
            exchange="test", symbol="BTCUSDT",
            bid=50000.0, ask=50010.0, last=50005.0, volume_24h=1000.0,
        )
        adapter = MockExchangeAdapter("test", tickers={"BTCUSDT": ticker, "ETHUSDT": ticker})
        symbols = await adapter.get_supported_symbols()
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols


# ==================== ExchangeRegistry Tests ====================


class TestExchangeRegistry:
    """Tests for the ExchangeRegistry."""

    def test_empty_registry(self):
        registry = ExchangeRegistry()
        assert registry.list_exchanges() == []
        assert registry.get_connected() == []

    def test_register_exchange(self):
        registry = ExchangeRegistry()
        adapter = MockExchangeAdapter("bitget")
        registry.register(adapter)
        assert "bitget" in registry.list_exchanges()

    def test_unregister_exchange(self):
        registry = ExchangeRegistry()
        adapter = MockExchangeAdapter("bitget")
        registry.register(adapter)
        registry.unregister("bitget")
        assert "bitget" not in registry.list_exchanges()

    def test_unregister_nonexistent(self):
        registry = ExchangeRegistry()
        registry.unregister("nonexistent")  # Should not raise

    def test_get_exchange(self):
        registry = ExchangeRegistry()
        adapter = MockExchangeAdapter("bitget")
        registry.register(adapter)
        result = registry.get("bitget")
        assert result is adapter

    def test_get_nonexistent(self):
        registry = ExchangeRegistry()
        assert registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_connected(self):
        registry = ExchangeRegistry()
        adapter1 = MockExchangeAdapter("bitget")
        adapter2 = MockExchangeAdapter("binance")
        await adapter1.connect()
        registry.register(adapter1)
        registry.register(adapter2)
        connected = registry.get_connected()
        assert "bitget" in connected
        assert "binance" not in connected

    @pytest.mark.asyncio
    async def test_get_all_tickers(self):
        registry = ExchangeRegistry()
        ticker_bg = ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=50000.0, ask=50010.0, last=50005.0, volume_24h=1000.0,
        )
        ticker_bn = ExchangeTicker(
            exchange="binance", symbol="BTCUSDT",
            bid=50020.0, ask=50030.0, last=50025.0, volume_24h=2000.0,
        )
        adapter1 = MockExchangeAdapter("bitget", tickers={"BTCUSDT": ticker_bg})
        adapter2 = MockExchangeAdapter("binance", tickers={"BTCUSDT": ticker_bn})
        await adapter1.connect()
        await adapter2.connect()
        registry.register(adapter1)
        registry.register(adapter2)

        tickers = await registry.get_all_tickers("BTCUSDT")
        assert len(tickers) == 2
        assert tickers["bitget"].bid == 50000.0
        assert tickers["binance"].bid == 50020.0

    @pytest.mark.asyncio
    async def test_get_all_tickers_skips_disconnected(self):
        registry = ExchangeRegistry()
        ticker = ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=50000.0, ask=50010.0, last=50005.0, volume_24h=1000.0,
        )
        adapter1 = MockExchangeAdapter("bitget", tickers={"BTCUSDT": ticker})
        adapter2 = MockExchangeAdapter("binance", tickers={"BTCUSDT": ticker})
        await adapter1.connect()
        # adapter2 NOT connected
        registry.register(adapter1)
        registry.register(adapter2)

        tickers = await registry.get_all_tickers("BTCUSDT")
        assert len(tickers) == 1
        assert "bitget" in tickers

    @pytest.mark.asyncio
    async def test_get_all_tickers_handles_error(self):
        registry = ExchangeRegistry()
        adapter = MockExchangeAdapter("bitget")  # No tickers set -> raises ValueError
        await adapter.connect()
        registry.register(adapter)

        tickers = await registry.get_all_tickers("BTCUSDT")
        assert len(tickers) == 0

    @pytest.mark.asyncio
    async def test_get_all_funding_rates(self):
        registry = ExchangeRegistry()
        rate_bg = ExchangeFundingRate(exchange="bitget", symbol="BTCUSDT", rate=0.0005)
        rate_bn = ExchangeFundingRate(exchange="binance", symbol="BTCUSDT", rate=0.0008)
        adapter1 = MockExchangeAdapter("bitget", funding_rates={"BTCUSDT": rate_bg})
        adapter2 = MockExchangeAdapter("binance", funding_rates={"BTCUSDT": rate_bn})
        await adapter1.connect()
        await adapter2.connect()
        registry.register(adapter1)
        registry.register(adapter2)

        rates = await registry.get_all_funding_rates("BTCUSDT")
        assert len(rates) == 2
        assert rates["bitget"].rate == 0.0005
        assert rates["binance"].rate == 0.0008

    @pytest.mark.asyncio
    async def test_get_all_funding_rates_handles_error(self):
        registry = ExchangeRegistry()
        adapter = MockExchangeAdapter("bitget")
        await adapter.connect()
        registry.register(adapter)

        rates = await registry.get_all_funding_rates("BTCUSDT")
        assert len(rates) == 0

    def test_get_summary(self):
        registry = ExchangeRegistry()
        adapter = MockExchangeAdapter("bitget")
        registry.register(adapter)
        summary = registry.get_summary()
        assert summary["registered"] == 1
        assert summary["connected"] == 0
        assert "bitget" in summary["exchanges"]

    def test_register_overwrites(self):
        registry = ExchangeRegistry()
        adapter1 = MockExchangeAdapter("bitget")
        adapter2 = MockExchangeAdapter("bitget")
        registry.register(adapter1)
        registry.register(adapter2)
        assert registry.get("bitget") is adapter2
        assert len(registry.list_exchanges()) == 1


# ==================== ArbScanner Tests ====================


class TestArbScanner:
    """Tests for the ArbScanner."""

    def test_default_init(self):
        scanner = ArbScanner()
        assert scanner.min_spread_pct == 0.1
        assert scanner.min_profit_pct == 0.02
        assert scanner.reference_position == 10000.0
        assert "bitget" in scanner.exchange_fees
        assert "binance" in scanner.exchange_fees

    def test_custom_init(self):
        scanner = ArbScanner(
            min_spread_pct=0.2,
            min_profit_pct=0.05,
            reference_position=50000.0,
            exchange_fees={"test_a": 0.05, "test_b": 0.03},
        )
        assert scanner.min_spread_pct == 0.2
        assert scanner.min_profit_pct == 0.05
        assert scanner.reference_position == 50000.0
        assert scanner.exchange_fees == {"test_a": 0.05, "test_b": 0.03}

    def test_scan_spot_arb_insufficient_exchanges(self):
        scanner = ArbScanner()
        result = scanner.scan_spot_arb({"bitget": ExchangeTicker(
            exchange="bitget", symbol="BTCUSDT",
            bid=50000.0, ask=50010.0, last=50005.0, volume_24h=1000.0,
        )})
        assert result == []

    def test_scan_spot_arb_no_opportunity(self):
        """Prices too close, no arb after fees."""
        scanner = ArbScanner(min_spread_pct=0.1)
        tickers = {
            "bitget": ExchangeTicker(
                exchange="bitget", symbol="BTCUSDT",
                bid=50000.0, ask=50001.0, last=50000.5, volume_24h=1000.0,
            ),
            "binance": ExchangeTicker(
                exchange="binance", symbol="BTCUSDT",
                bid=50000.0, ask=50001.0, last=50000.5, volume_24h=2000.0,
            ),
        }
        result = scanner.scan_spot_arb(tickers)
        assert len(result) == 0

    def test_scan_spot_arb_finds_opportunity(self):
        """Clear price discrepancy should yield an arb opportunity."""
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"cheap_exchange": 0.02, "expensive_exchange": 0.02},
        )
        tickers = {
            "cheap_exchange": ExchangeTicker(
                exchange="cheap_exchange", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "expensive_exchange": ExchangeTicker(
                exchange="expensive_exchange", symbol="BTCUSDT",
                bid=50100.0, ask=50150.0, last=50125.0, volume_24h=1000.0,
            ),
        }
        result = scanner.scan_spot_arb(tickers)
        assert len(result) >= 1

        opp = result[0]
        assert opp.arb_type == ArbType.SPOT_SPOT
        assert opp.is_profitable
        assert opp.estimated_profit_pct > 0
        assert opp.buy_exchange == "cheap_exchange"
        assert opp.sell_exchange == "expensive_exchange"

    def test_scan_spot_arb_both_directions(self):
        """Scanner checks both buy/sell directions."""
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"ex_a": 0.01, "ex_b": 0.01},
        )
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50100.0, ask=50150.0, last=50125.0, volume_24h=1000.0,
            ),
        }
        result = scanner.scan_spot_arb(tickers)
        # Buy on ex_a (ask=49950), sell on ex_b (bid=50100) should be profitable
        profitable = [o for o in result if o.buy_exchange == "ex_a"]
        assert len(profitable) >= 1

    def test_scan_spot_arb_three_exchanges(self):
        """Test with three exchanges for all pairwise comparisons."""
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"ex_a": 0.01, "ex_b": 0.01, "ex_c": 0.01},
        )
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50100.0, ask=50150.0, last=50125.0, volume_24h=1000.0,
            ),
            "ex_c": ExchangeTicker(
                exchange="ex_c", symbol="BTCUSDT",
                bid=50200.0, ask=50250.0, last=50225.0, volume_24h=1000.0,
            ),
        }
        result = scanner.scan_spot_arb(tickers)
        assert len(result) >= 2  # At least ex_a->ex_b and ex_a->ex_c

    def test_scan_spot_arb_sorted_by_profit(self):
        """Results should be sorted by estimated_profit_pct descending."""
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"ex_a": 0.01, "ex_b": 0.01, "ex_c": 0.01},
        )
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50050.0, ask=50100.0, last=50075.0, volume_24h=1000.0,
            ),
            "ex_c": ExchangeTicker(
                exchange="ex_c", symbol="BTCUSDT",
                bid=50200.0, ask=50250.0, last=50225.0, volume_24h=1000.0,
            ),
        }
        result = scanner.scan_spot_arb(tickers)
        if len(result) >= 2:
            assert result[0].estimated_profit_pct >= result[1].estimated_profit_pct

    def test_scan_spot_arb_zero_prices_skipped(self):
        scanner = ArbScanner(min_spread_pct=0.01, min_profit_pct=0.001)
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=50000.0, ask=0.0, last=50000.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50100.0, ask=50110.0, last=50105.0, volume_24h=1000.0,
            ),
        }
        # ex_a ask=0 means buy_price=0 -> should be skipped
        result = scanner.scan_spot_arb(tickers)
        # Only valid direction is: buy on ex_b (ask=50110), sell on ex_a (bid=50000) -> negative spread
        # So no profitable arbs
        for opp in result:
            assert opp.buy_price > 0
            assert opp.sell_price > 0

    def test_scan_funding_arb_insufficient_exchanges(self):
        scanner = ArbScanner()
        result = scanner.scan_funding_arb({
            "bitget": ExchangeFundingRate(exchange="bitget", symbol="BTCUSDT", rate=0.001),
        })
        assert result == []

    def test_scan_funding_arb_no_opportunity(self):
        """Rates too similar, no arb."""
        scanner = ArbScanner(min_spread_pct=0.1)
        rates = {
            "bitget": ExchangeFundingRate(exchange="bitget", symbol="BTCUSDT", rate=0.0001),
            "binance": ExchangeFundingRate(exchange="binance", symbol="BTCUSDT", rate=0.00011),
        }
        result = scanner.scan_funding_arb(rates)
        assert len(result) == 0

    def test_scan_funding_arb_finds_opportunity(self):
        """Large funding rate difference should yield opportunity."""
        scanner = ArbScanner(
            min_spread_pct=0.01,
            min_profit_pct=0.001,
            exchange_fees={"bitget": 0.01, "binance": 0.01},
        )
        rates = {
            "bitget": ExchangeFundingRate(exchange="bitget", symbol="BTCUSDT", rate=0.005),
            "binance": ExchangeFundingRate(exchange="binance", symbol="BTCUSDT", rate=0.0001),
        }
        result = scanner.scan_funding_arb(rates)
        assert len(result) >= 1

        opp = result[0]
        assert opp.arb_type == ArbType.FUNDING_DIFF
        assert opp.sell_exchange == "bitget"  # Short the higher rate
        assert opp.buy_exchange == "binance"  # Long the lower rate
        assert opp.metadata["short_funding_rate"] == 0.005
        assert opp.metadata["long_funding_rate"] == 0.0001

    def test_scan_funding_arb_reversed_rates(self):
        """Test when second exchange has higher rate."""
        scanner = ArbScanner(
            min_spread_pct=0.01,
            min_profit_pct=0.001,
            exchange_fees={"bitget": 0.01, "binance": 0.01},
        )
        rates = {
            "bitget": ExchangeFundingRate(exchange="bitget", symbol="BTCUSDT", rate=0.0001),
            "binance": ExchangeFundingRate(exchange="binance", symbol="BTCUSDT", rate=0.005),
        }
        result = scanner.scan_funding_arb(rates)
        assert len(result) >= 1
        opp = result[0]
        assert opp.sell_exchange == "binance"  # Short the higher rate
        assert opp.buy_exchange == "bitget"  # Long the lower rate

    def test_scan_funding_arb_unprofitable_after_fees(self):
        """Small rate diff eaten by high fees."""
        scanner = ArbScanner(
            min_spread_pct=0.01,
            exchange_fees={"bitget": 5.0, "binance": 5.0},  # Extremely high fees
        )
        rates = {
            "bitget": ExchangeFundingRate(exchange="bitget", symbol="BTCUSDT", rate=0.001),
            "binance": ExchangeFundingRate(exchange="binance", symbol="BTCUSDT", rate=0.0005),
        }
        result = scanner.scan_funding_arb(rates)
        assert len(result) == 0


# ==================== ArbOpportunity Tests ====================


class TestArbOpportunity:
    """Tests for ArbOpportunity dataclass."""

    def test_is_profitable_true(self):
        opp = ArbOpportunity(
            id="XARB-0001", arb_type=ArbType.SPOT_SPOT,
            symbol="BTCUSDT", buy_exchange="bitget", sell_exchange="binance",
            buy_price=50000.0, sell_price=50100.0,
            spread_pct=0.2, estimated_profit_pct=0.1,
            estimated_profit_usd=10.0, fees_pct=0.1,
        )
        assert opp.is_profitable is True

    def test_is_profitable_false(self):
        opp = ArbOpportunity(
            id="XARB-0001", arb_type=ArbType.SPOT_SPOT,
            symbol="BTCUSDT", buy_exchange="bitget", sell_exchange="binance",
            buy_price=50000.0, sell_price=50010.0,
            spread_pct=0.02, estimated_profit_pct=-0.08,
            estimated_profit_usd=-8.0, fees_pct=0.1,
        )
        assert opp.is_profitable is False

    def test_to_dict(self):
        opp = ArbOpportunity(
            id="XARB-0001", arb_type=ArbType.SPOT_SPOT,
            symbol="BTCUSDT", buy_exchange="bitget", sell_exchange="binance",
            buy_price=50000.0, sell_price=50100.0,
            spread_pct=0.2, estimated_profit_pct=0.1,
            estimated_profit_usd=10.0, fees_pct=0.1,
        )
        d = opp.to_dict()
        assert d["id"] == "XARB-0001"
        assert d["arb_type"] == "spot_spot"
        assert d["is_profitable"] is True
        assert "timestamp" in d
        assert d["metadata"] == {}

    def test_to_dict_funding_diff(self):
        opp = ArbOpportunity(
            id="XARB-0002", arb_type=ArbType.FUNDING_DIFF,
            symbol="BTCUSDT", buy_exchange="binance", sell_exchange="bitget",
            buy_price=0.0001, sell_price=0.005,
            spread_pct=0.49, estimated_profit_pct=0.3,
            estimated_profit_usd=30.0, fees_pct=0.12,
            metadata={"long_funding_rate": 0.0001, "short_funding_rate": 0.005},
        )
        d = opp.to_dict()
        assert d["arb_type"] == "funding_diff"
        assert d["metadata"]["long_funding_rate"] == 0.0001


# ==================== ArbType Tests ====================


class TestArbType:
    """Tests for ArbType enum."""

    def test_values(self):
        assert ArbType.SPOT_SPOT.value == "spot_spot"
        assert ArbType.FUNDING_DIFF.value == "funding_diff"
        assert ArbType.FUTURES_BASIS.value == "futures_basis"

    def test_string_comparison(self):
        assert ArbType.SPOT_SPOT == "spot_spot"
        assert ArbType.FUNDING_DIFF == "funding_diff"


# ==================== ArbScanner State Tests ====================


class TestArbScannerState:
    """Tests for ArbScanner state management."""

    def test_get_all_opportunities_empty(self):
        scanner = ArbScanner()
        assert scanner.get_all_opportunities() == []

    def test_get_profitable_opportunities(self):
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"ex_a": 0.01, "ex_b": 0.01},
        )
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50200.0, ask=50250.0, last=50225.0, volume_24h=1000.0,
            ),
        }
        scanner.scan_spot_arb(tickers)
        profitable = scanner.get_profitable_opportunities()
        for opp in profitable:
            assert opp.is_profitable

    def test_clear_opportunities(self):
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"ex_a": 0.01, "ex_b": 0.01},
        )
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50200.0, ask=50250.0, last=50225.0, volume_24h=1000.0,
            ),
        }
        scanner.scan_spot_arb(tickers)
        assert len(scanner.get_all_opportunities()) > 0
        scanner.clear_opportunities()
        assert len(scanner.get_all_opportunities()) == 0

    def test_get_summary_empty(self):
        scanner = ArbScanner()
        summary = scanner.get_summary()
        assert summary["total_opportunities"] == 0
        assert summary["profitable_opportunities"] == 0
        assert summary["spot_arb_count"] == 0
        assert summary["funding_arb_count"] == 0
        assert summary["best_opportunity"] is None
        assert "config" in summary

    def test_get_summary_with_opportunities(self):
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"ex_a": 0.01, "ex_b": 0.01},
        )
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50200.0, ask=50250.0, last=50225.0, volume_24h=1000.0,
            ),
        }
        scanner.scan_spot_arb(tickers)
        summary = scanner.get_summary()
        assert summary["total_opportunities"] > 0
        assert summary["spot_arb_count"] > 0

    def test_incremental_ids(self):
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"ex_a": 0.01, "ex_b": 0.01},
        )
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50200.0, ask=50250.0, last=50225.0, volume_24h=1000.0,
            ),
        }
        scanner.scan_spot_arb(tickers)
        opps = scanner.get_all_opportunities()
        ids = [o.id for o in opps]
        assert all(id_.startswith("XARB-") for id_ in ids)

    def test_combined_fees_default_fallback(self):
        scanner = ArbScanner()
        # Unknown exchanges fall back to 0.1%
        fees = scanner._get_combined_fees("unknown_ex", "another_unknown")
        assert fees == 0.2  # 0.1 + 0.1

    def test_combined_fees_known_exchanges(self):
        scanner = ArbScanner()
        fees = scanner._get_combined_fees("bitget", "binance")
        assert fees == pytest.approx(0.10)  # 0.06 + 0.04

    def test_combined_fees_case_insensitive(self):
        scanner = ArbScanner()
        fees = scanner._get_combined_fees("BITGET", "BINANCE")
        assert fees == pytest.approx(0.10)

    def test_accumulates_across_scans(self):
        """Multiple scan calls accumulate opportunities."""
        scanner = ArbScanner(
            min_spread_pct=0.05,
            min_profit_pct=0.01,
            exchange_fees={"ex_a": 0.01, "ex_b": 0.01},
        )
        tickers = {
            "ex_a": ExchangeTicker(
                exchange="ex_a", symbol="BTCUSDT",
                bid=49900.0, ask=49950.0, last=49925.0, volume_24h=1000.0,
            ),
            "ex_b": ExchangeTicker(
                exchange="ex_b", symbol="BTCUSDT",
                bid=50200.0, ask=50250.0, last=50225.0, volume_24h=1000.0,
            ),
        }
        first = scanner.scan_spot_arb(tickers)
        second = scanner.scan_spot_arb(tickers)
        all_opps = scanner.get_all_opportunities()
        assert len(all_opps) == len(first) + len(second)
