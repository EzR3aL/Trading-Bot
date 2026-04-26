"""
Hyperliquid Exchange Client implementing ExchangeClient ABC.

Uses the official hyperliquid-python-sdk for EIP-712 signed trading.
Symbol format: plain asset name (e.g. "BTC", "ETH") or pairs like "BTCUSDT"/"BTCUSDC"
which are normalized to coin names internally.

SECURITY: Only trading operations are allowed. No withdrawals, transfers, or
fund-moving operations. The ALLOWED_METHODS whitelist enforces this.

Module structure
----------------
This file is the **public façade**. The actual implementation lives in
focused modules so each concern can be reviewed and tested in isolation:

* ``_helpers``           — pure value parsers, symbol normalization,
                           order-response decoding
* ``signing``            — :class:`SafeExchange` wrapper, allow/deny
                           method lists, :class:`HyperliquidClientError`,
                           Cloid derivation
* ``fees``               — slippage default, builder-fee math
* ``eip712_validator``   — defense-in-depth EIP-712 payload checks (SEC-005/008)
* ``_read_mixin``        — balance / position / ticker / funding queries
* ``_trade_mixin``       — order placement, leverage, close, TP/SL set/cancel
* ``_builder_mixin``     — builder code, referral, affiliate, user fees
* ``_fees_mixin``        — fill history, fees, funding history
* ``_readback_mixin``    — risk-state probes (#191)
* ``_prestart_mixin``    — bot start gate checks (#ARCH-H2)

Every name a consumer or test imports from
``src.exchanges.hyperliquid.client`` is re-exported below — this file is
the source of truth for the public API surface.
"""

import asyncio
import os
import time
from functools import partial
from typing import TYPE_CHECKING, Any

from eth_account import Account as EthAccount
from hyperliquid.exchange import Exchange as HLExchange
from hyperliquid.info import Info as HLInfo
from hyperliquid.utils.constants import MAINNET_API_URL, TESTNET_API_URL

from src.exchanges.base import ExchangeClient
from src.observability.metrics import (
    EXCHANGE_API_REQUEST_DURATION_SECONDS,
    EXCHANGE_API_REQUESTS_TOTAL,
)
from src.exchanges.hyperliquid._builder_mixin import HyperliquidBuilderMixin
from src.exchanges.hyperliquid._fees_mixin import HyperliquidFeesMixin
from src.exchanges.hyperliquid._helpers import (
    _hl_float,
    _hl_int,
    _hl_ts_to_datetime,
    _normalize_symbol as _normalize_symbol_helper,
    _parse_order_response,
    _QUOTE_SUFFIXES,
)
from src.exchanges.hyperliquid._prestart_mixin import HyperliquidPrestartMixin
from src.exchanges.hyperliquid._read_mixin import HyperliquidReadMixin
from src.exchanges.hyperliquid._readback_mixin import HyperliquidReadbackMixin
from src.exchanges.hyperliquid._trade_mixin import HyperliquidTradeMixin
from src.exchanges.hyperliquid.constants import (
    DEFAULT_BUILDER_FEE,
    MAINNET_CHAIN_ID,
    MAX_BUILDER_FEE_TENTHS_BPS,
    MIN_BUILDER_FEE_TENTHS_BPS,
    TESTNET_CHAIN_ID,
)
from src.exchanges.hyperliquid.eip712_validator import (
    EIP712ValidationError,
    assert_builder_fee_tenths_bps,
    validate_approve_builder_fee,
)
from src.exchanges.hyperliquid.fees import DEFAULT_SLIPPAGE
from src.exchanges.hyperliquid.signing import (
    ALLOWED_METHODS,
    FORBIDDEN_METHODS,
    HyperliquidClientError,
    SafeExchange,
)

if TYPE_CHECKING:
    from src.exchanges.base import GateCheckResult  # noqa: F401
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerError
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Public re-exports kept here so ``from src.exchanges.hyperliquid.client
# import X`` keeps resolving for every prior consumer and test patch site.
__all__ = [
    "ALLOWED_METHODS",
    "FORBIDDEN_METHODS",
    "DEFAULT_SLIPPAGE",
    "EIP712ValidationError",
    "EthAccount",
    "HLExchange",
    "HLInfo",
    "HyperliquidClient",
    "HyperliquidClientError",
    "MAINNET_API_URL",
    "MAINNET_CHAIN_ID",
    "MAX_BUILDER_FEE_TENTHS_BPS",
    "MIN_BUILDER_FEE_TENTHS_BPS",
    "SafeExchange",
    "TESTNET_API_URL",
    "TESTNET_CHAIN_ID",
    "_QUOTE_SUFFIXES",
    "_hl_breaker",
    "_hl_float",
    "_hl_int",
    "_hl_ts_to_datetime",
    "_parse_order_response",
    "assert_builder_fee_tenths_bps",
    "validate_approve_builder_fee",
]


# Circuit breaker for Hyperliquid API calls (consistent with other exchanges)
_hl_breaker = CircuitBreaker(
    name="hyperliquid_api",
    fail_threshold=5,
    reset_timeout=60.0,
)


class HyperliquidClient(
    HyperliquidPrestartMixin,
    HyperliquidReadMixin,
    HyperliquidTradeMixin,
    HyperliquidBuilderMixin,
    HyperliquidFeesMixin,
    HyperliquidReadbackMixin,
    ExchangeClient,
):
    """
    Hyperliquid exchange client with full trading support.

    Uses the official hyperliquid-python-sdk for EIP-712 signed operations.
    All fund-moving operations (withdraw, transfer) are blocked by SafeExchange.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        demo_mode: bool = True,
        **kwargs,
    ):
        # Forward the rate_limiter kwarg so _cb_call can serialize through it.
        super().__init__(
            api_key, api_secret, passphrase, demo_mode,
            rate_limiter=kwargs.get("rate_limiter"),
        )
        self.wallet_address = api_key
        # Execution network: testnet in demo, mainnet in live
        self.base_url = TESTNET_API_URL if demo_mode else MAINNET_API_URL

        # Create eth_account wallet from private key (API wallet)
        try:
            self._wallet = EthAccount.from_key(api_secret)
        except Exception as e:
            raise HyperliquidClientError(f"Invalid private key: {e}")

        # Determine if API wallet differs from main wallet
        # api_key = main wallet address (where funds/positions live)
        # api_secret -> self._wallet = API wallet (signs transactions)
        is_agent_wallet = self.wallet_address.lower() != self._wallet.address.lower()

        # Initialize SDK Exchange (handles EIP-712 signing)
        # Pass empty spot_meta to avoid SDK crash when Hyperliquid adds new
        # spot tokens that cause IndexError in info.py token parsing.
        # We only trade perps, so spot metadata is not needed.
        try:
            raw_exchange = HLExchange(
                wallet=self._wallet,
                base_url=self.base_url,
                account_address=self.wallet_address if is_agent_wallet else None,
            )
        except (IndexError, KeyError):
            # Fallback: skip spot meta entirely
            raw_exchange = HLExchange(
                wallet=self._wallet,
                base_url=self.base_url,
                account_address=self.wallet_address if is_agent_wallet else None,
                spot_meta={"tokens": [], "universe": []},
            )

        # Wrap in SafeExchange to block fund-moving operations
        self._exchange = SafeExchange(raw_exchange)

        # Public price info — ALWAYS mainnet. Testnet mids/funding are
        # detached from real market and corrupt demo PnL reports.
        # Why: user expects demo numbers to match HL mainnet UI 1:1.
        if demo_mode:
            try:
                self._info: HLInfo = HLInfo(base_url=MAINNET_API_URL, skip_ws=True)
            except (IndexError, KeyError):
                self._info = HLInfo(
                    base_url=MAINNET_API_URL, skip_ws=True,
                    spot_meta={"tokens": [], "universe": []},
                )
        else:
            self._info = raw_exchange.info

        # Exec-network info — used for user-specific queries (fills, positions)
        # that only exist on the network where orders were placed.
        self._info_exec: HLInfo = raw_exchange.info

        # ── Builder Code config ──────────────────────────────────────────
        # Earns a small fee on every order (100% to builder, no cap).
        # Accepts kwargs from caller (DB-first) or falls back to ENV.
        builder_address = (kwargs.get("builder_address") or os.environ.get("HL_BUILDER_ADDRESS", "")).strip()
        builder_fee = int(kwargs.get("builder_fee") or os.environ.get("HL_BUILDER_FEE", str(DEFAULT_BUILDER_FEE)))
        within_bounds = (
            MIN_BUILDER_FEE_TENTHS_BPS <= builder_fee <= MAX_BUILDER_FEE_TENTHS_BPS
        )
        if builder_address and within_bounds:
            self._builder = {"b": builder_address.lower(), "f": builder_fee}
            logger.info(
                f"Builder code enabled: {builder_address[:10]}... "
                f"fee={builder_fee} ({builder_fee / 10:.1f} bp = {builder_fee / 1000:.3f}%)"
            )
        else:
            self._builder = None
            if builder_address and not within_bounds:
                logger.warning(
                    f"HL_BUILDER_FEE={builder_fee} out of range "
                    f"[{MIN_BUILDER_FEE_TENTHS_BPS}-{MAX_BUILDER_FEE_TENTHS_BPS}]. "
                    f"Builder code disabled."
                )

        # SEC-005: pin expected signature chain_id so a manipulated SDK
        # cannot produce a cross-chain-replayable approval.
        self._expected_chain_id = TESTNET_CHAIN_ID if demo_mode else MAINNET_CHAIN_ID

        if is_agent_wallet:
            logger.info(
                f"HyperliquidClient initialized ({'TESTNET' if demo_mode else 'MAINNET'}) "
                f"main_wallet={self.wallet_address[:10]}... "
                f"api_wallet={self._wallet.address[:10]}..."
            )
        else:
            logger.info(
                f"HyperliquidClient initialized ({'TESTNET' if demo_mode else 'MAINNET'}) "
                f"wallet={self._wallet.address[:10]}... (direct, no API wallet)"
            )

    @property
    def exchange_name(self) -> str:
        return "hyperliquid"

    @property
    def supports_demo(self) -> bool:
        return True

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize symbol to Hyperliquid coin name. 'BTCUSDT' → 'BTC', 'ETH' → 'ETH'."""
        return _normalize_symbol_helper(symbol)

    async def close(self) -> None:
        pass  # SDK uses requests (sync), no session to close

    async def _cb_call(self, func, *args, **kwargs):
        """Execute a sync SDK function through the circuit breaker without blocking the event loop.

        Acquires a token from the per-exchange rate limiter (#ARCH-C3) so
        HL-bound API calls share the same bucket across every HL client
        instance in the process.
        """
        # Serialize through the per-exchange token bucket when wired.
        if getattr(self, "_rate_limiter", None) is not None:
            await self._rate_limiter.acquire()

        loop = asyncio.get_event_loop()

        async def _wrapper():
            return await loop.run_in_executor(None, partial(func, *args, **kwargs))

        # Prometheus instrumentation (#327 PR-4). The HL SDK does not expose
        # the REST URL to us, so ``endpoint`` is the SDK method name
        # (``market_open``, ``cancel``, ``user_state`` …) which is both
        # stable and low-cardinality.
        endpoint_label = getattr(func, "__name__", "unknown") or "unknown"
        status_label = "error"
        start = time.perf_counter()
        try:
            result = await _hl_breaker.call(_wrapper)
            status_label = "ok"
            return result
        except CircuitBreakerError as e:
            status_label = "circuit_open"
            raise HyperliquidClientError(f"API temporarily unavailable: {e}")
        finally:
            EXCHANGE_API_REQUESTS_TOTAL.labels(
                exchange="hyperliquid",
                endpoint=endpoint_label,
                status=status_label,
            ).inc()
            EXCHANGE_API_REQUEST_DURATION_SECONDS.labels(
                exchange="hyperliquid",
                endpoint=endpoint_label,
            ).observe(time.perf_counter() - start)
