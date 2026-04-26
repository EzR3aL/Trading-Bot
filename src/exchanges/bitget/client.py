"""
Bitget Exchange Client implementing the ExchangeClient ABC.

This file is the **public façade**. The actual implementation lives in
focused modules so each concern can be reviewed and tested in isolation:

* ``_helpers``           — pure value parsers, cancel-outcome classifier,
                           orderSource → plan_type mapping
* ``signing``            — :class:`BitgetClientError`
* ``_read_mixin``        — balance / position / ticker / funding queries
* ``_trade_mixin``       — order placement, leverage, close, TP/SL,
                           native trailing stop, contract precision helpers
* ``_fees_mixin``        — order/trade fees, fill price, funding history
* ``_affiliate_mixin``   — broker affiliate UID lookup, sizing helper
* ``_readback_mixin``    — risk-state readback probes (#191)

The HMAC-SHA256 signature, headers and ``_parse_response`` stay on this
class because tests patch ``src.exchanges.bitget.client.time`` and
``src.exchanges.bitget.client.aiohttp``; relocating those imports would
break the patch path. Likewise the module-level ``_bitget_breaker`` and
``BitgetExchangeClient`` symbol must be importable from this module.

Every name a consumer or test imports from
``src.exchanges.bitget.client`` is re-exported below — this file is the
source of truth for the public API surface.
"""

from __future__ import annotations

# ``asyncio`` and ``time`` are kept as module-level imports so existing
# tests can patch ``src.exchanges.bitget.client.asyncio`` /
# ``src.exchanges.bitget.client.time``.
import asyncio  # noqa: F401  (test patch site)
import base64
import hashlib
import hmac
import time
from typing import Any, Dict, Optional

# ``aiohttp`` kept at module scope as a test patch site.
import aiohttp

from src.exchanges.base import ExchangeClient, HTTPExchangeClientMixin
from src.exchanges.bitget._affiliate_mixin import BitgetAffiliateMixin
from src.exchanges.bitget._fees_mixin import BitgetFeesMixin
from src.exchanges.bitget._helpers import (
    _bitget_order_source_to_plan_type,
    _BITGET_BENIGN_CANCEL_TOKENS,
    _BITGET_ORDER_SOURCE_PREFIXES,
    _log_bitget_cancel_outcome,
    _parse_float,
    _parse_int,
    _ts_to_datetime,
)
from src.exchanges.bitget._read_mixin import BitgetReadMixin
from src.exchanges.bitget._readback_mixin import BitgetReadbackMixin
from src.exchanges.bitget._trade_mixin import BitgetTradeMixin
from src.exchanges.bitget.constants import (
    BASE_URL,
    SUCCESS_CODE,
    TESTNET_URL,
)
from src.exchanges.bitget.signing import BitgetClientError
from src.utils.circuit_breaker import circuit_registry
from src.utils.logger import get_logger
from src.utils.metrics import record_reject

logger = get_logger(__name__)

# Public re-exports kept here so ``from src.exchanges.bitget.client
# import X`` keeps resolving for every prior consumer and test patch site.
__all__ = [
    "BASE_URL",
    "BitgetClientError",
    "BitgetExchangeClient",
    "SUCCESS_CODE",
    "TESTNET_URL",
    "_BITGET_BENIGN_CANCEL_TOKENS",
    "_BITGET_ORDER_SOURCE_PREFIXES",
    "_bitget_breaker",
    "_bitget_order_source_to_plan_type",
    "_log_bitget_cancel_outcome",
    "_parse_float",
    "_parse_int",
    "_ts_to_datetime",
]

_bitget_breaker = circuit_registry.get("bitget_api", fail_threshold=5, reset_timeout=60)


class BitgetExchangeClient(
    BitgetReadMixin,
    BitgetTradeMixin,
    BitgetFeesMixin,
    BitgetAffiliateMixin,
    BitgetReadbackMixin,
    HTTPExchangeClientMixin,
    ExchangeClient,
):
    """
    Async client for Bitget Futures API implementing ExchangeClient ABC.

    Supports demo trading via paptrading header.
    Uses HTTPExchangeClientMixin for session management, circuit breaker,
    and the standard REST request flow.
    """

    SUPPORTS_NATIVE_TRAILING_STOP = True
    SUPPORTS_NATIVE_TRAILING_PROBE = True

    _client_error_class = BitgetClientError

    @property
    def _circuit_breaker(self):
        return _bitget_breaker

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        demo_mode: bool = True,
        testnet: bool = False,
        **kwargs,
    ):
        super().__init__(api_key, api_secret, passphrase, demo_mode)
        self.testnet = testnet
        self.base_url = TESTNET_URL if testnet else BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None
        mode_str = "DEMO" if demo_mode else "LIVE"
        logger.info(f"BitgetExchangeClient initialized in {mode_str} mode")

    @property
    def exchange_name(self) -> str:
        return "bitget"

    @property
    def supports_demo(self) -> bool:
        return True

    # ==================== Auth ====================

    def _generate_signature(self, timestamp: str, method: str,
                            request_path: str, body: str = "") -> str:
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method: str, request_path: str,
                     body: str = "") -> Dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, request_path, body)
        headers = {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }
        if self.demo_mode:
            headers["paptrading"] = "1"
        return headers

    # ==================== Response parsing ====================

    def _parse_response(self, result: Any, response: aiohttp.ClientResponse) -> Any:
        """Parse Bitget API response — checks HTTP status and code field."""
        if response.status != 200:
            record_reject("bitget", "http_status")
            raise BitgetClientError(
                f"API Error: {result.get('msg', 'Unknown error')}"
            )
        if result.get("code") != SUCCESS_CODE:
            record_reject("bitget", "error_code")
            raise BitgetClientError(
                f"Bitget Error: {result.get('msg', 'Unknown error')}"
            )
        return result.get("data", result)
