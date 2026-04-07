"""Tests for the SUPPORTS_NATIVE_TRAILING_STOP capability flag — #133.

Ensures each exchange client correctly advertises whether it can place a
native (exchange-side) trailing stop, so trade_executor and position_monitor
don't waste API calls on unsupported exchanges and don't falsely log
"trailing stop placed" when the base class returned None.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.base import ExchangeClient
from src.exchanges.bingx.client import BingXClient
from src.exchanges.bitget.client import BitgetExchangeClient
from src.exchanges.bitunix.client import BitunixClient
from src.exchanges.hyperliquid.client import HyperliquidClient
from src.exchanges.weex.client import WeexClient


class TestNativeTrailingCapability:
    """Each client must declare its native-trailing support accurately.

    The frontend feature matrix at `frontend/src/pages/GettingStarted.tsx`
    shows:
        bitget        ✓
        weex          ✗
        bingx         ✓
        bitunix       ✗
        hyperliquid   ✗

    These tests lock that in at the class level so trade_executor and
    position_monitor can skip futile attempts (#133 context: BingX was
    retrying every 10 min even though its payload was rejected — that
    was a separate bug, but the capability flag prevents the same kind
    of wasted retry for Weex/Bitunix/Hyperliquid).
    """

    def test_base_defaults_to_unsupported(self):
        assert ExchangeClient.SUPPORTS_NATIVE_TRAILING_STOP is False

    def test_bitget_supports_native_trailing(self):
        assert BitgetExchangeClient.SUPPORTS_NATIVE_TRAILING_STOP is True

    def test_bingx_supports_native_trailing(self):
        assert BingXClient.SUPPORTS_NATIVE_TRAILING_STOP is True

    def test_weex_does_not_support_native_trailing(self):
        assert WeexClient.SUPPORTS_NATIVE_TRAILING_STOP is False

    def test_bitunix_does_not_support_native_trailing(self):
        assert BitunixClient.SUPPORTS_NATIVE_TRAILING_STOP is False

    def test_hyperliquid_does_not_support_native_trailing(self):
        assert HyperliquidClient.SUPPORTS_NATIVE_TRAILING_STOP is False

    def test_unsupported_clients_return_none_from_base_implementation(self):
        """The base class fallback should return None so callers can detect it."""
        # We verify via introspection that the unsupported clients do not
        # override the method (they inherit the base implementation).
        assert WeexClient.place_trailing_stop is ExchangeClient.place_trailing_stop
        assert BitunixClient.place_trailing_stop is ExchangeClient.place_trailing_stop
        assert HyperliquidClient.place_trailing_stop is ExchangeClient.place_trailing_stop

    def test_supported_clients_override_place_trailing_stop(self):
        """Bitget and BingX must actually override the base method."""
        assert BitgetExchangeClient.place_trailing_stop is not ExchangeClient.place_trailing_stop
        assert BingXClient.place_trailing_stop is not ExchangeClient.place_trailing_stop
