"""Comprehensive unit tests for HyperliquidClient.

Covers:
- Client initialization (demo/mainnet, agent wallet, direct wallet, invalid key)
- Symbol normalization
- Properties (exchange_name, supports_demo)
- Read operations (balance, position, open_positions, ticker, funding_rate)
- Trading operations (set_leverage, place_market_order, close_position, cancel_order)
- Trigger orders (_place_trigger_order) with TP/SL validation
- Fee tracking (get_trade_total_fees, get_funding_fees)
- User fees (get_user_fees)
- _parse_order_response helper (filled, resting, error, unknown formats)
- _round_price and _get_tick_size helpers
- SafeExchange security wrapper
- close() no-op
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.exchanges.hyperliquid.client import (
    ALLOWED_METHODS,
    DEFAULT_SLIPPAGE,
    FORBIDDEN_METHODS,
    HyperliquidClient,
    HyperliquidClientError,
    SafeExchange,
    _parse_order_response,
)
from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker


# ---------------------------------------------------------------------------
# Helpers: create a client without hitting real SDK constructors
# ---------------------------------------------------------------------------

def _make_client(builder=None, wallet_address="0xaaaa", wallet_obj_address="0xbbbb"):
    """Create a HyperliquidClient via object.__new__ with mocked internals."""
    client = object.__new__(HyperliquidClient)
    client.api_key = wallet_address
    client.api_secret = "fake_secret"
    client.passphrase = ""
    client.demo_mode = True
    client.wallet_address = wallet_address

    mock_wallet = MagicMock()
    mock_wallet.address = wallet_obj_address
    client._wallet = mock_wallet

    client._exchange = MagicMock()
    client._info = MagicMock()
    client._builder = builder
    return client


# ===========================================================================
# Initialization Tests
# ===========================================================================


class TestHyperliquidClientInit:
    """Tests for __init__ covering demo mode, mainnet, agent wallet, errors."""

    @patch.dict(os.environ, {"HL_BUILDER_ADDRESS": "", "HL_BUILDER_FEE": "10"}, clear=False)
    @patch("src.exchanges.hyperliquid.client.HLExchange")
    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_init_demo_mode_uses_testnet_url(self, mock_eth, mock_exchange):
        """Demo mode should use TESTNET_API_URL."""
        mock_wallet = MagicMock()
        mock_wallet.address = "0x1111111111111111111111111111111111111111"
        mock_eth.from_key.return_value = mock_wallet
        mock_exchange_instance = MagicMock()
        mock_exchange_instance.info = MagicMock()
        mock_exchange.return_value = mock_exchange_instance

        client = HyperliquidClient(
            api_key="0x1111111111111111111111111111111111111111",
            api_secret="0x" + "ab" * 32,
            demo_mode=True,
        )

        from hyperliquid.utils.constants import TESTNET_API_URL
        assert client.base_url == TESTNET_API_URL
        assert client.demo_mode is True

    @patch.dict(os.environ, {"HL_BUILDER_ADDRESS": "", "HL_BUILDER_FEE": "10"}, clear=False)
    @patch("src.exchanges.hyperliquid.client.HLExchange")
    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_init_mainnet_mode_uses_mainnet_url(self, mock_eth, mock_exchange):
        """Non-demo mode should use MAINNET_API_URL."""
        mock_wallet = MagicMock()
        mock_wallet.address = "0x1111111111111111111111111111111111111111"
        mock_eth.from_key.return_value = mock_wallet
        mock_exchange_instance = MagicMock()
        mock_exchange_instance.info = MagicMock()
        mock_exchange.return_value = mock_exchange_instance

        client = HyperliquidClient(
            api_key="0x1111111111111111111111111111111111111111",
            api_secret="0x" + "ab" * 32,
            demo_mode=False,
        )

        from hyperliquid.utils.constants import MAINNET_API_URL
        assert client.base_url == MAINNET_API_URL
        assert client.demo_mode is False

    @patch.dict(os.environ, {"HL_BUILDER_ADDRESS": "", "HL_BUILDER_FEE": "10"}, clear=False)
    @patch("src.exchanges.hyperliquid.client.HLExchange")
    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_init_agent_wallet_different_from_main(self, mock_eth, mock_exchange):
        """When api_key (main wallet) differs from derived wallet, agent mode is used."""
        mock_wallet = MagicMock()
        mock_wallet.address = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        mock_eth.from_key.return_value = mock_wallet
        mock_exchange_instance = MagicMock()
        mock_exchange_instance.info = MagicMock()
        mock_exchange.return_value = mock_exchange_instance

        _client = HyperliquidClient(
            api_key="0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            api_secret="0x" + "cd" * 32,
            demo_mode=True,
        )

        # HLExchange should be called with account_address set
        call_kwargs = mock_exchange.call_args
        assert call_kwargs.kwargs.get("account_address") == "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"

    @patch.dict(os.environ, {"HL_BUILDER_ADDRESS": "", "HL_BUILDER_FEE": "10"}, clear=False)
    @patch("src.exchanges.hyperliquid.client.HLExchange")
    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_init_direct_wallet_no_agent(self, mock_eth, mock_exchange):
        """When api_key matches derived wallet address, no agent mode."""
        same_address = "0x1111111111111111111111111111111111111111"
        mock_wallet = MagicMock()
        mock_wallet.address = same_address
        mock_eth.from_key.return_value = mock_wallet
        mock_exchange_instance = MagicMock()
        mock_exchange_instance.info = MagicMock()
        mock_exchange.return_value = mock_exchange_instance

        _client = HyperliquidClient(
            api_key=same_address,
            api_secret="0x" + "ab" * 32,
            demo_mode=True,
        )

        call_kwargs = mock_exchange.call_args
        assert call_kwargs.kwargs.get("account_address") is None

    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_init_invalid_private_key_raises_error(self, mock_eth):
        """Invalid private key should raise HyperliquidClientError."""
        mock_eth.from_key.side_effect = ValueError("bad key")

        with pytest.raises(HyperliquidClientError, match="Invalid private key"):
            HyperliquidClient(
                api_key="0xwallet",
                api_secret="not-a-valid-key",
                demo_mode=True,
            )

    @patch.dict(os.environ, {
        "HL_BUILDER_ADDRESS": "0xABCDEF1234567890ABCDEF1234567890ABCDEF12",
        "HL_BUILDER_FEE": "10",
    }, clear=False)
    @patch("src.exchanges.hyperliquid.client.HLExchange")
    @patch("src.exchanges.hyperliquid.client.EthAccount")
    def test_init_builder_from_kwargs_overrides_env(self, mock_eth, mock_exchange):
        """Builder kwargs should take priority over ENV."""
        mock_wallet = MagicMock()
        mock_wallet.address = "0x1111111111111111111111111111111111111111"
        mock_eth.from_key.return_value = mock_wallet
        mock_exchange_instance = MagicMock()
        mock_exchange_instance.info = MagicMock()
        mock_exchange.return_value = mock_exchange_instance

        client = HyperliquidClient(
            api_key="0x1111111111111111111111111111111111111111",
            api_secret="0x" + "ab" * 32,
            demo_mode=True,
            builder_address="0xKWARG_BUILDER",
            builder_fee=50,
        )

        assert client._builder is not None
        assert client._builder["b"] == "0xkwarg_builder"
        assert client._builder["f"] == 50


# ===========================================================================
# Property Tests
# ===========================================================================


class TestProperties:
    def test_exchange_name_returns_hyperliquid(self):
        client = _make_client()
        assert client.exchange_name == "hyperliquid"

    def test_supports_demo_returns_true(self):
        client = _make_client()
        assert client.supports_demo is True


# ===========================================================================
# Symbol Normalization Tests
# ===========================================================================


class TestNormalizeSymbol:
    def test_strips_usdt_suffix(self):
        assert HyperliquidClient._normalize_symbol("BTCUSDT") == "BTC"

    def test_strips_usdc_suffix(self):
        assert HyperliquidClient._normalize_symbol("ETHUSDC") == "ETH"

    def test_strips_usd_suffix(self):
        assert HyperliquidClient._normalize_symbol("SOLUSD") == "SOL"

    def test_strips_perp_suffix(self):
        assert HyperliquidClient._normalize_symbol("BTCPERP") == "BTC"

    def test_plain_coin_unchanged(self):
        assert HyperliquidClient._normalize_symbol("BTC") == "BTC"

    def test_lowercase_input_uppercased(self):
        assert HyperliquidClient._normalize_symbol("ethusdt") == "ETH"

    def test_mixed_case_input(self):
        assert HyperliquidClient._normalize_symbol("SolUsdc") == "SOL"


# ===========================================================================
# close() Tests
# ===========================================================================


class TestClose:
    async def test_close_is_noop(self):
        """close() should complete without error (SDK uses sync requests)."""
        client = _make_client()
        result = await client.close()
        assert result is None


# ===========================================================================
# get_account_balance Tests
# ===========================================================================


class TestGetAccountBalance:
    async def test_returns_balance_from_user_state(self):
        """Should parse marginSummary, withdrawable, and sum unrealizedPnl from positions."""
        client = _make_client()
        client._info.user_state.return_value = {
            "marginSummary": {
                "accountValue": "10000.0",
                "totalRawUsd": "5000.0",
                "totalNtlPos": "1500.0",
            },
            "withdrawable": "8000.0",
            "assetPositions": [
                {"position": {"unrealizedPnl": "300.0"}},
                {"position": {"unrealizedPnl": "-50.0"}},
            ],
        }

        balance = await client.get_account_balance()

        assert isinstance(balance, Balance)
        assert balance.total == 10000.0
        assert balance.available == 8000.0
        assert balance.unrealized_pnl == 250.0  # 300 + (-50)
        assert balance.currency == "USDC"

    async def test_falls_back_to_spot_when_perp_total_is_zero(self):
        """When perp accountValue is 0, should check spot balances."""
        client = _make_client()
        client._info.user_state.return_value = {
            "marginSummary": {
                "accountValue": "0",
                "totalRawUsd": "0",
                "totalNtlPos": "0",
            },
            "withdrawable": "0",
        }
        client._info.spot_user_state.return_value = {
            "balances": [
                {"coin": "USDC", "total": "5000.0"},
                {"coin": "ETH", "total": "1.5"},
            ]
        }

        balance = await client.get_account_balance()

        assert balance.total == 5000.0
        assert balance.available == 5000.0

    async def test_handles_spot_error_gracefully(self):
        """Spot fallback error should not crash; returns 0 spot balance."""
        client = _make_client()
        client._info.user_state.return_value = {
            "marginSummary": {
                "accountValue": "0",
                "totalRawUsd": "0",
                "totalNtlPos": "0",
            },
            "withdrawable": "0",
        }
        client._info.spot_user_state.side_effect = Exception("spot API down")

        balance = await client.get_account_balance()

        assert balance.total == 0.0
        assert balance.available == 0.0

    async def test_uses_wallet_address_for_query(self):
        """Should use wallet_address for the user_state call."""
        client = _make_client(wallet_address="0xMyWallet")
        client._info.user_state.return_value = {
            "marginSummary": {"accountValue": "100", "totalRawUsd": "50", "totalNtlPos": "10"},
            "withdrawable": "80",
        }

        await client.get_account_balance()

        client._info.user_state.assert_called_once_with("0xMyWallet")

    async def test_falls_back_to_wallet_obj_address_when_no_wallet_address(self):
        """If wallet_address is empty, should use _wallet.address."""
        client = _make_client(wallet_address="", wallet_obj_address="0xFromKey")
        client._info.user_state.return_value = {
            "marginSummary": {"accountValue": "100", "totalRawUsd": "50", "totalNtlPos": "0"},
            "withdrawable": "80",
        }

        await client.get_account_balance()

        client._info.user_state.assert_called_once_with("0xFromKey")


# ===========================================================================
# get_position Tests
# ===========================================================================


class TestGetPosition:
    async def test_returns_long_position(self):
        """Should return Position with side='long' for positive szi."""
        client = _make_client()
        client._info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "0.5",
                        "entryPx": "95000.0",
                        "unrealizedPnl": "500.0",
                        "leverage": {"value": "10"},
                        "liquidationPx": "85000.0",
                    }
                }
            ]
        }
        client._info.all_mids.return_value = {"BTC": "96000.0"}

        pos = await client.get_position("BTCUSDT")

        assert isinstance(pos, Position)
        assert pos.symbol == "BTC"
        assert pos.side == "long"
        assert pos.size == 0.5
        assert pos.entry_price == 95000.0
        assert pos.current_price == 96000.0
        assert pos.unrealized_pnl == 500.0
        assert pos.leverage == 10
        assert pos.liquidation_price == 85000.0
        assert pos.exchange == "hyperliquid"

    async def test_returns_short_position(self):
        """Should return Position with side='short' for negative szi."""
        client = _make_client()
        client._info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "ETH",
                        "szi": "-2.0",
                        "entryPx": "3500.0",
                        "unrealizedPnl": "-50.0",
                        "leverage": {"value": "5"},
                        "liquidationPx": "4000.0",
                    }
                }
            ]
        }
        client._info.all_mids.return_value = {"ETH": "3550.0"}

        pos = await client.get_position("ETH")

        assert pos.side == "short"
        assert pos.size == 2.0

    async def test_returns_none_when_zero_size(self):
        """Position with szi=0 should return None."""
        client = _make_client()
        client._info.user_state.return_value = {
            "assetPositions": [
                {"position": {"coin": "BTC", "szi": "0", "entryPx": "95000"}}
            ]
        }

        pos = await client.get_position("BTC")
        assert pos is None

    async def test_returns_none_when_no_matching_coin(self):
        """No matching position should return None."""
        client = _make_client()
        client._info.user_state.return_value = {
            "assetPositions": [
                {"position": {"coin": "ETH", "szi": "1.0", "entryPx": "3500"}}
            ]
        }

        pos = await client.get_position("BTC")
        assert pos is None

    async def test_returns_none_when_no_positions(self):
        """Empty assetPositions should return None."""
        client = _make_client()
        client._info.user_state.return_value = {"assetPositions": []}

        pos = await client.get_position("BTC")
        assert pos is None

    async def test_uses_entry_price_when_ticker_fails(self):
        """If get_ticker fails, current_price should fall back to entry_price."""
        client = _make_client()
        client._info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "1.0",
                        "entryPx": "95000.0",
                        "unrealizedPnl": "0",
                        "leverage": {"value": "1"},
                        "liquidationPx": "0",
                    }
                }
            ]
        }
        client._info.all_mids.side_effect = Exception("API down")

        pos = await client.get_position("BTC")

        assert pos.current_price == 95000.0


# ===========================================================================
# get_open_positions Tests
# ===========================================================================


class TestGetOpenPositions:
    async def test_returns_multiple_positions(self):
        """Should return all positions with non-zero size."""
        client = _make_client()
        client._info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "0.5",
                        "entryPx": "95000",
                        "unrealizedPnl": "100",
                        "leverage": {"value": "10"},
                        "liquidationPx": "85000",
                    }
                },
                {
                    "position": {
                        "coin": "ETH",
                        "szi": "-2.0",
                        "entryPx": "3500",
                        "unrealizedPnl": "-50",
                        "leverage": {"value": "5"},
                        "liquidationPx": "4000",
                    }
                },
                {
                    "position": {
                        "coin": "SOL",
                        "szi": "0",
                        "entryPx": "150",
                        "unrealizedPnl": "0",
                        "leverage": {"value": "1"},
                        "liquidationPx": "0",
                    }
                },
            ]
        }

        positions = await client.get_open_positions()

        assert len(positions) == 2
        assert positions[0].symbol == "BTC"
        assert positions[0].side == "long"
        assert positions[1].symbol == "ETH"
        assert positions[1].side == "short"

    async def test_returns_empty_list_when_no_positions(self):
        client = _make_client()
        client._info.user_state.return_value = {"assetPositions": []}

        positions = await client.get_open_positions()
        assert positions == []

    async def test_handles_none_liquidation_price(self):
        """liquidationPx can be None or 0; should handle both."""
        client = _make_client()
        client._info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "1.0",
                        "entryPx": "95000",
                        "unrealizedPnl": "0",
                        "leverage": {"value": "1"},
                        "liquidationPx": None,
                    }
                }
            ]
        }

        positions = await client.get_open_positions()
        assert len(positions) == 1
        assert positions[0].liquidation_price == 0


# ===========================================================================
# get_ticker Tests
# ===========================================================================


class TestGetTicker:
    async def test_returns_ticker_with_price(self):
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96500.5"}

        ticker = await client.get_ticker("BTCUSDT")

        assert isinstance(ticker, Ticker)
        assert ticker.symbol == "BTC"
        assert ticker.last_price == 96500.5
        assert ticker.bid == 96500.5
        assert ticker.ask == 96500.5
        assert ticker.volume_24h == 0.0

    async def test_returns_zero_price_for_unknown_symbol(self):
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}

        ticker = await client.get_ticker("UNKNOWNUSDT")

        assert ticker.last_price == 0

    async def test_normalizes_symbol(self):
        client = _make_client()
        client._info.all_mids.return_value = {"ETH": "3500"}

        ticker = await client.get_ticker("ethusdc")
        assert ticker.symbol == "ETH"


# ===========================================================================
# get_funding_rate Tests
# ===========================================================================


class TestGetFundingRate:
    async def test_returns_funding_rate_when_found(self):
        client = _make_client()
        client._info.meta_and_asset_ctxs.return_value = [
            {"universe": [
                {"name": "BTC"},
                {"name": "ETH"},
            ]},
            [
                {"funding": "0.0001"},
                {"funding": "0.00005"},
            ],
        ]

        rate = await client.get_funding_rate("BTCUSDT")

        assert isinstance(rate, FundingRateInfo)
        assert rate.symbol == "BTC"
        assert rate.current_rate == 0.0001

    async def test_returns_zero_rate_when_not_found(self):
        client = _make_client()
        client._info.meta_and_asset_ctxs.return_value = [
            {"universe": [{"name": "BTC"}]},
            [{"funding": "0.0001"}],
        ]

        rate = await client.get_funding_rate("SOLPERP")

        assert rate.symbol == "SOL"
        assert rate.current_rate == 0.0


# ===========================================================================
# set_leverage Tests
# ===========================================================================


class TestSetLeverage:
    async def test_set_leverage_success(self):
        client = _make_client()
        client._exchange.update_leverage.return_value = {"status": "ok"}

        result = await client.set_leverage("BTCUSDT", 10)

        assert result is True
        client._exchange.update_leverage.assert_called_once_with(
            leverage=10, name="BTC", is_cross=True
        )

    async def test_set_leverage_failure(self):
        client = _make_client()
        client._exchange.update_leverage.side_effect = Exception("leverage error")

        result = await client.set_leverage("BTC", 100)

        assert result is False


# ===========================================================================
# place_market_order Tests
# ===========================================================================


class TestPlaceMarketOrder:
    async def test_place_long_order_success(self):
        """Should call market_open with is_buy=True for 'long' side."""
        client = _make_client()
        client._exchange.update_leverage.return_value = {"status": "ok"}
        client._exchange.market_open.return_value = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"filled": {"oid": 12345, "avgPx": "96000.0", "totalSz": "0.01"}}
                    ]
                }
            },
        }

        order = await client.place_market_order(
            symbol="BTCUSDT", side="long", size=0.01, leverage=10
        )

        assert isinstance(order, Order)
        assert order.order_id == "12345"
        assert order.symbol == "BTC"
        assert order.side == "long"
        assert order.size == 0.01
        assert order.price == 96000.0
        assert order.status == "filled"
        assert order.exchange == "hyperliquid"
        assert order.leverage == 10

        client._exchange.market_open.assert_called_once_with(
            name="BTC", is_buy=True, sz=0.01, slippage=DEFAULT_SLIPPAGE,
        )

    async def test_place_short_order_success(self):
        """Should call market_open with is_buy=False for 'short' side."""
        client = _make_client()
        client._exchange.update_leverage.return_value = {"status": "ok"}
        client._exchange.market_open.return_value = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"filled": {"oid": 99999, "avgPx": "3500.0", "totalSz": "1.0"}}
                    ]
                }
            },
        }

        order = await client.place_market_order(
            symbol="ETH", side="short", size=1.0, leverage=5
        )

        assert order.side == "short"
        client._exchange.market_open.assert_called_once_with(
            name="ETH", is_buy=False, sz=1.0, slippage=DEFAULT_SLIPPAGE,
        )

    async def test_place_order_with_builder(self):
        """When builder is configured, should pass builder kwarg."""
        builder = {"b": "0xbuilder", "f": 10}
        client = _make_client(builder=builder)
        client._exchange.update_leverage.return_value = {"status": "ok"}
        client._exchange.market_open.return_value = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"filled": {"oid": 1, "avgPx": "96000", "totalSz": "0.01"}}
                    ]
                }
            },
        }

        await client.place_market_order(
            symbol="BTC", side="long", size=0.01, leverage=10
        )

        client._exchange.market_open.assert_called_once_with(
            name="BTC", is_buy=True, sz=0.01, slippage=DEFAULT_SLIPPAGE,
            builder=builder,
        )

    async def test_place_order_with_tp_sl_triggers(self):
        """Should place TP and SL trigger orders when specified."""
        client = _make_client()
        client._exchange.update_leverage.return_value = {"status": "ok"}
        client._exchange.market_open.return_value = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"filled": {"oid": 1, "avgPx": "96000", "totalSz": "0.01"}}
                    ]
                }
            },
        }
        # Mock get_ticker for trigger validation
        client._info.all_mids.return_value = {"BTC": "96000"}
        # Mock meta for tick size
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}
        # Mock the trigger order call
        client._exchange.order.return_value = {"status": "ok"}

        order = await client.place_market_order(
            symbol="BTC", side="long", size=0.01, leverage=10,
            take_profit=100000.0, stop_loss=90000.0,
        )

        assert order.take_profit == 100000.0
        assert order.stop_loss == 90000.0
        # Should have called _exchange.order twice (TP + SL)
        assert client._exchange.order.call_count == 2


# ===========================================================================
# close_position Tests
# ===========================================================================


class TestClosePosition:
    async def test_close_existing_position(self):
        """Should call market_close with correct parameters."""
        client = _make_client()
        # Mock get_position to return an existing position
        client._info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "0.5",
                        "entryPx": "95000",
                        "unrealizedPnl": "500",
                        "leverage": {"value": "10"},
                        "liquidationPx": "85000",
                    }
                }
            ]
        }
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._exchange.market_close.return_value = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"filled": {"oid": 54321, "avgPx": "96000.0", "totalSz": "0.5"}}
                    ]
                }
            },
        }

        order = await client.close_position("BTCUSDT", "long")

        assert isinstance(order, Order)
        assert order.order_id == "54321"
        assert order.symbol == "BTC"
        assert order.size == 0.5
        assert order.price == 96000.0
        assert order.status == "filled"

        client._exchange.market_close.assert_called_once_with(
            coin="BTC", sz=0.5, slippage=DEFAULT_SLIPPAGE,
        )

    async def test_close_position_returns_none_when_no_position(self):
        """Should return None when no position exists for the symbol."""
        client = _make_client()
        client._info.user_state.return_value = {"assetPositions": []}

        result = await client.close_position("BTC", "long")

        assert result is None
        client._exchange.market_close.assert_not_called()

    async def test_close_position_with_builder(self):
        """Should pass builder kwarg when configured."""
        builder = {"b": "0xbuilder", "f": 10}
        client = _make_client(builder=builder)
        client._info.user_state.return_value = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "1.0",
                        "entryPx": "95000",
                        "unrealizedPnl": "0",
                        "leverage": {"value": "1"},
                        "liquidationPx": "0",
                    }
                }
            ]
        }
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._exchange.market_close.return_value = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"filled": {"oid": 1, "avgPx": "96000", "totalSz": "1.0"}}
                    ]
                }
            },
        }

        await client.close_position("BTC", "long")

        client._exchange.market_close.assert_called_once_with(
            coin="BTC", sz=1.0, slippage=DEFAULT_SLIPPAGE, builder=builder,
        )


# ===========================================================================
# cancel_order Tests
# ===========================================================================


class TestCancelOrder:
    async def test_cancel_order_success(self):
        client = _make_client()
        client._exchange.cancel.return_value = {"status": "ok"}

        result = await client.cancel_order("BTCUSDT", "12345")

        assert result is True
        client._exchange.cancel.assert_called_once_with(name="BTC", oid=12345)

    async def test_cancel_order_failure(self):
        client = _make_client()
        client._exchange.cancel.side_effect = Exception("cancel failed")

        result = await client.cancel_order("BTC", "99999")

        assert result is False


# ===========================================================================
# _place_trigger_order Tests
# ===========================================================================


class TestPlaceTriggerOrder:
    async def test_tp_long_position_valid(self):
        """TP for long (is_buy=False): trigger above market should succeed."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}
        client._exchange.order.return_value = {"status": "ok"}

        await client._place_trigger_order("BTC", is_buy=False, size=0.01, trigger_px=100000.0, tpsl="tp")

        client._exchange.order.assert_called_once()
        call_kwargs = client._exchange.order.call_args.kwargs
        assert call_kwargs["name"] == "BTC"
        assert call_kwargs["is_buy"] is False
        assert call_kwargs["reduce_only"] is True

    async def test_tp_long_position_invalid_below_market(self):
        """TP for long (is_buy=False): trigger below market should be skipped."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._exchange.order.return_value = {"status": "ok"}

        await client._place_trigger_order("BTC", is_buy=False, size=0.01, trigger_px=90000.0, tpsl="tp")

        client._exchange.order.assert_not_called()

    async def test_sl_long_position_valid(self):
        """SL for long (is_buy=False): trigger below market should succeed."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}
        client._exchange.order.return_value = {"status": "ok"}

        await client._place_trigger_order("BTC", is_buy=False, size=0.01, trigger_px=90000.0, tpsl="sl")

        client._exchange.order.assert_called_once()

    async def test_sl_long_position_invalid_above_market(self):
        """SL for long (is_buy=False): trigger above market should be skipped."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}

        await client._place_trigger_order("BTC", is_buy=False, size=0.01, trigger_px=100000.0, tpsl="sl")

        client._exchange.order.assert_not_called()

    async def test_tp_short_position_valid(self):
        """TP for short (is_buy=True): trigger below market should succeed."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}
        client._exchange.order.return_value = {"status": "ok"}

        await client._place_trigger_order("BTC", is_buy=True, size=0.01, trigger_px=90000.0, tpsl="tp")

        client._exchange.order.assert_called_once()

    async def test_tp_short_position_invalid_above_market(self):
        """TP for short (is_buy=True): trigger above market should be skipped."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}

        await client._place_trigger_order("BTC", is_buy=True, size=0.01, trigger_px=100000.0, tpsl="tp")

        client._exchange.order.assert_not_called()

    async def test_sl_short_position_valid(self):
        """SL for short (is_buy=True): trigger above market should succeed."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}
        client._exchange.order.return_value = {"status": "ok"}

        await client._place_trigger_order("BTC", is_buy=True, size=0.01, trigger_px=100000.0, tpsl="sl")

        client._exchange.order.assert_called_once()

    async def test_sl_short_position_invalid_below_market(self):
        """SL for short (is_buy=True): trigger below market should be skipped."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}

        await client._place_trigger_order("BTC", is_buy=True, size=0.01, trigger_px=90000.0, tpsl="sl")

        client._exchange.order.assert_not_called()

    async def test_trigger_order_handles_exchange_error(self):
        """Exchange error during trigger placement should not raise."""
        client = _make_client()
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}
        client._exchange.order.side_effect = Exception("signing error")

        # Should not raise
        await client._place_trigger_order("BTC", is_buy=False, size=0.01, trigger_px=100000.0, tpsl="tp")

    async def test_trigger_order_handles_ticker_error(self):
        """Ticker error should not prevent trigger order placement."""
        client = _make_client()
        client._info.all_mids.side_effect = Exception("API down")
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}
        client._exchange.order.return_value = {"status": "ok"}

        # Should still attempt the order (validation skipped)
        await client._place_trigger_order("BTC", is_buy=False, size=0.01, trigger_px=100000.0, tpsl="tp")

        client._exchange.order.assert_called_once()

    async def test_trigger_order_with_builder(self):
        """Builder should be passed to trigger orders."""
        builder = {"b": "0xbuilder", "f": 10}
        client = _make_client(builder=builder)
        client._info.all_mids.return_value = {"BTC": "96000"}
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}
        client._exchange.order.return_value = {"status": "ok"}

        await client._place_trigger_order("BTC", is_buy=False, size=0.01, trigger_px=100000.0, tpsl="tp")

        call_kwargs = client._exchange.order.call_args.kwargs
        assert call_kwargs["builder"] == builder


# ===========================================================================
# _get_tick_size Tests
# ===========================================================================


class TestGetTickSize:
    def test_returns_tick_size_from_meta(self):
        client = _make_client()
        client._info.meta.return_value = {
            "universe": [
                {"name": "BTC", "szDecimals": 5},
                {"name": "ETH", "szDecimals": 3},
            ]
        }

        tick = client._get_tick_size("BTC")
        assert tick == 1e-5

    def test_returns_default_when_coin_not_found(self):
        client = _make_client()
        client._info.meta.return_value = {"universe": [{"name": "BTC", "szDecimals": 5}]}

        tick = client._get_tick_size("UNKNOWN")
        assert tick == 0.01

    def test_returns_default_on_api_error(self):
        client = _make_client()
        client._info.meta.side_effect = Exception("meta API down")

        tick = client._get_tick_size("BTC")
        assert tick == 0.01


# ===========================================================================
# _round_price Tests
# ===========================================================================


class TestRoundPrice:
    def test_round_to_tick_size(self):
        assert HyperliquidClient._round_price(96123.456, 0.01) == 96123.46

    def test_round_to_whole_number(self):
        assert HyperliquidClient._round_price(96123.456, 1.0) == 96123.0

    def test_round_to_small_tick(self):
        assert HyperliquidClient._round_price(0.12345, 0.001) == 0.123

    def test_zero_tick_returns_original(self):
        assert HyperliquidClient._round_price(96000.123, 0) == 96000.123

    def test_negative_tick_returns_original(self):
        assert HyperliquidClient._round_price(96000.123, -1) == 96000.123


# ===========================================================================
# get_trade_total_fees Tests
# ===========================================================================


class TestGetTradeTotalFees:
    async def test_returns_total_fees_for_matching_orders(self):
        client = _make_client()
        client._info.user_fills.return_value = [
            {"oid": "100", "coin": "BTC", "fee": "0.5"},
            {"oid": "200", "coin": "BTC", "fee": "0.3"},
            {"oid": "300", "coin": "ETH", "fee": "0.1"},  # different coin
            {"oid": "400", "coin": "BTC", "fee": "0.2"},  # different order
        ]

        fees = await client.get_trade_total_fees("BTCUSDT", "100", "200")

        assert fees == 0.8

    async def test_returns_zero_when_no_matching_fills(self):
        client = _make_client()
        client._info.user_fills.return_value = [
            {"oid": "999", "coin": "BTC", "fee": "0.5"},
        ]

        fees = await client.get_trade_total_fees("BTC", "100")

        assert fees == 0.0

    async def test_handles_api_error(self):
        client = _make_client()
        client._info.user_fills.side_effect = Exception("API error")

        fees = await client.get_trade_total_fees("BTC", "100")

        assert fees == 0.0

    async def test_entry_only_no_close(self):
        """When close_order_id is None, only entry order fees counted."""
        client = _make_client()
        client._info.user_fills.return_value = [
            {"oid": "100", "coin": "BTC", "fee": "0.5"},
            {"oid": "200", "coin": "BTC", "fee": "0.3"},
        ]

        fees = await client.get_trade_total_fees("BTC", "100", None)

        assert fees == 0.5


# ===========================================================================
# get_funding_fees Tests
# ===========================================================================


class TestGetFundingFees:
    async def test_returns_total_funding(self):
        client = _make_client()
        client._info.user_funding_history.return_value = [
            {"coin": "BTC", "delta": "0.5"},
            {"coin": "BTC", "delta": "-0.3"},
            {"coin": "ETH", "delta": "0.1"},  # different coin
        ]

        funding = await client.get_funding_fees("BTCUSDT", 1000, 2000)

        assert funding == 0.8

    async def test_matches_on_asset_field_too(self):
        """Some responses use 'asset' instead of 'coin'."""
        client = _make_client()
        client._info.user_funding_history.return_value = [
            {"asset": "BTC", "delta": "0.25"},
        ]

        funding = await client.get_funding_fees("BTC", 1000, 2000)

        assert funding == 0.25

    async def test_returns_zero_on_error(self):
        client = _make_client()
        client._info.user_funding_history.side_effect = Exception("API error")

        funding = await client.get_funding_fees("BTC", 1000, 2000)

        assert funding == 0.0

    async def test_handles_non_list_response(self):
        """Non-list response should return 0."""
        client = _make_client()
        client._info.user_funding_history.return_value = "unexpected"

        funding = await client.get_funding_fees("BTC", 1000, 2000)

        assert funding == 0.0


# ===========================================================================
# get_user_fees Tests
# ===========================================================================


class TestGetUserFees:
    async def test_returns_dict_result(self):
        client = _make_client()
        client._info.user_fees.return_value = {"dailyUserVlm": "50000", "feeSchedule": {}}

        result = await client.get_user_fees()

        assert isinstance(result, dict)
        assert result["dailyUserVlm"] == "50000"

    async def test_returns_none_on_non_dict(self):
        client = _make_client()
        client._info.user_fees.return_value = "not a dict"

        result = await client.get_user_fees()

        assert result is None

    async def test_returns_none_on_error(self):
        client = _make_client()
        client._info.user_fees.side_effect = Exception("fail")

        result = await client.get_user_fees()

        assert result is None

    async def test_uses_provided_address(self):
        client = _make_client(wallet_address="0xMain")
        client._info.user_fees.return_value = {"data": "ok"}

        await client.get_user_fees(user_address="0xCustom")

        client._info.user_fees.assert_called_once_with("0xcustom")


# ===========================================================================
# _parse_order_response Tests
# ===========================================================================


class TestParseOrderResponse:
    def test_parse_filled_order(self):
        result = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"filled": {"oid": 12345, "avgPx": "96000.5", "totalSz": "0.01"}}
                    ]
                }
            },
        }

        parsed = _parse_order_response(result)

        assert parsed["oid"] == 12345
        assert parsed["avgPx"] == "96000.5"
        assert parsed["totalSz"] == "0.01"

    def test_parse_resting_order(self):
        result = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"resting": {"oid": 67890}}
                    ]
                }
            },
        }

        parsed = _parse_order_response(result)

        assert parsed["oid"] == 67890
        assert parsed["avgPx"] == "0"

    def test_parse_error_status_raises(self):
        result = {"status": "err", "response": "Order too large"}

        with pytest.raises(HyperliquidClientError, match="Order rejected"):
            _parse_order_response(result)

    def test_parse_error_in_statuses_raises(self):
        result = {
            "status": "ok",
            "response": {
                "data": {
                    "statuses": [
                        {"error": "Insufficient margin"}
                    ]
                }
            },
        }

        with pytest.raises(HyperliquidClientError, match="Insufficient margin"):
            _parse_order_response(result)

    def test_parse_unknown_format_returns_defaults(self):
        result = {"unexpected": "data"}

        parsed = _parse_order_response(result)

        assert parsed["oid"] == "hl-unknown"
        assert parsed["avgPx"] == "0"

    def test_parse_non_dict_returns_defaults(self):
        parsed = _parse_order_response("some string response")

        assert parsed["oid"] == "hl-unknown"
        assert parsed["avgPx"] == "0"

    def test_parse_empty_statuses_returns_defaults(self):
        result = {
            "status": "ok",
            "response": {"data": {"statuses": []}},
        }

        parsed = _parse_order_response(result)

        assert parsed["oid"] == "hl-unknown"


# ===========================================================================
# SafeExchange Tests
# ===========================================================================


class TestSafeExchangeExtended:
    def test_blocks_all_forbidden_methods(self):
        """Every method in FORBIDDEN_METHODS should raise HyperliquidClientError."""
        mock_exchange = MagicMock()
        safe = SafeExchange(mock_exchange)

        for method_name in FORBIDDEN_METHODS:
            with pytest.raises(HyperliquidClientError, match="BLOCKED"):
                getattr(safe, method_name)

    def test_allows_all_whitelisted_methods(self):
        """Every method in ALLOWED_METHODS should be accessible."""
        mock_exchange = MagicMock()
        safe = SafeExchange(mock_exchange)

        for method_name in ALLOWED_METHODS:
            # Should not raise
            getattr(safe, method_name)

    def test_allows_private_methods(self):
        """Methods starting with _ should be passed through."""
        mock_exchange = MagicMock()
        mock_exchange._internal_method = MagicMock()
        safe = SafeExchange(mock_exchange)

        # Should not raise
        safe._internal_method

    def test_warns_on_non_whitelisted_public_method(self):
        """Non-whitelisted public callable method should log warning but still work."""
        mock_exchange = MagicMock()
        mock_exchange.some_unknown_method = MagicMock()
        safe = SafeExchange(mock_exchange)

        # Should not raise, but will log a warning
        result = safe.some_unknown_method
        assert result is not None


# ===========================================================================
# Constants Sanity Tests
# ===========================================================================


class TestConstantsSanity:
    def test_allowed_methods_is_frozenset(self):
        assert isinstance(ALLOWED_METHODS, frozenset)

    def test_forbidden_methods_is_frozenset(self):
        assert isinstance(FORBIDDEN_METHODS, frozenset)

    def test_no_overlap_between_allowed_and_forbidden(self):
        """ALLOWED_METHODS and FORBIDDEN_METHODS must not overlap."""
        overlap = ALLOWED_METHODS & FORBIDDEN_METHODS
        assert overlap == frozenset(), f"Overlap found: {overlap}"

    def test_default_slippage_is_five_percent(self):
        assert DEFAULT_SLIPPAGE == 0.05
