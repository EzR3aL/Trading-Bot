"""Abstract base classes for exchange clients and websockets."""

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Type

import aiohttp

from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker
from src.utils.circuit_breaker import CircuitBreakerError, with_retry


# ── Risk-state readback snapshots (#190 / #191) ────────────────────────────
# These dataclasses are returned by the per-exchange readback methods on
# ``ExchangeClient`` and consumed by RiskStateManager (#190) as the source
# of truth — the exchange always wins over the local DB state.


@dataclass
class PositionTpSlSnapshot:
    """Normalized snapshot of an exchange-side position TP/SL pair.

    All fields are optional except symbol+side because each exchange may
    expose only one (TP-only, SL-only, neither) for a given position.
    """

    symbol: str
    side: str  # "long" or "short"
    tp_price: Optional[float]
    tp_order_id: Optional[str]
    tp_trigger_type: Optional[str]  # "mark_price" / "fill_price" / exchange-specific
    sl_price: Optional[float]
    sl_order_id: Optional[str]
    sl_trigger_type: Optional[str]


@dataclass
class TrailingStopSnapshot:
    """Normalized snapshot of an exchange-side trailing stop plan.

    callback_rate is normalized to percent (e.g. 1.4 means 1.4%) regardless
    of how the source exchange encodes it (Bitget=decimal, BingX=decimal).
    """

    symbol: str
    side: str  # "long" or "short"
    callback_rate: Optional[float]  # in percent
    activation_price: Optional[float]
    trigger_price: Optional[float]  # current trigger if exchange exposes it
    order_id: Optional[str]


@dataclass
class CloseReasonSnapshot:
    """Normalized snapshot of the most recent close event for a position.

    closed_by_plan_type is one of:
        "track_plan"   — trailing stop triggered
        "pos_profit"   — take-profit triggered
        "pos_loss"     — stop-loss triggered
        "manual"       — operator/script close (reduce-only market order)
        "liquidation"  — forced close by exchange
    """

    symbol: str
    closed_by_order_id: Optional[str]
    closed_by_plan_type: Optional[str]
    closed_by_trigger_type: Optional[str]
    closed_at: Optional[datetime]
    fill_price: Optional[float]


if TYPE_CHECKING:
    from src.exchanges.rate_limiter import ExchangeRateLimiter
    from src.utils.circuit_breaker import CircuitBreaker


class ExchangeClient(ABC):
    """
    Unified interface for all exchange REST API clients.

    Each exchange adapter must implement these methods, returning
    normalized types from src.exchanges.types.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str = "",
        demo_mode: bool = True,
        rate_limiter: Optional["ExchangeRateLimiter"] = None,
        **kwargs,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.demo_mode = demo_mode
        self._rate_limiter = rate_limiter

    async def _rate_limited_request(self, coro):
        """Acquire a rate limit token before executing the coroutine."""
        if self._rate_limiter:
            await self._rate_limiter.acquire()
        return await coro

    @abstractmethod
    async def get_account_balance(self) -> Balance:
        """Get account balance."""
        ...

    @abstractmethod
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        size: float,
        leverage: int,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        margin_mode: str = "cross",
    ) -> Order:
        """Place a market order with optional TP/SL."""
        ...

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an open order."""
        ...

    @abstractmethod
    async def close_position(self, symbol: str, side: str, margin_mode: str = "cross") -> Optional[Order]:
        """Close an open position."""
        ...

    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol."""
        ...

    @abstractmethod
    async def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        ...

    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int, margin_mode: str = "cross") -> bool:
        """Set leverage for a symbol."""
        ...

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """Get current ticker data."""
        ...

    @abstractmethod
    async def get_funding_rate(self, symbol: str) -> FundingRateInfo:
        """Get current funding rate info."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close HTTP session and clean up resources."""
        ...

    async def set_position_tpsl(
        self,
        symbol: str,
        position_id: Optional[str] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        side: str = "long",
        size: float = 0,
    ) -> None:
        """Set/update TP/SL for an open position. Override in exchange-specific client."""
        raise NotImplementedError(f"{self.exchange_name} does not support set_position_tpsl")

    async def cancel_position_tpsl(
        self,
        symbol: str,
        side: str = "long",
    ) -> bool:
        """Cancel all TP/SL orders for a position.

        Position-level exchanges (Bitget, Hyperliquid, Bitunix) don't need this
        because set_position_tpsl implicitly replaces. Order-based exchanges
        (BingX, Weex) must override to cancel existing conditional orders.

        Returns True if cancellation succeeded or no orders to cancel.
        """
        return True

    # Class-level capability flag: set to True in subclasses that implement
    # a real native trailing stop via the exchange API (Bitget, BingX). Used
    # by trade_executor and position_monitor to skip unnecessary attempts on
    # exchanges that fall back to software trailing (Weex, Bitunix, Hyperliquid).
    SUPPORTS_NATIVE_TRAILING_STOP: bool = False

    # True when the subclass implements a meaningful ``has_native_trailing_stop``
    # probe. Callers should only treat a False return as authoritative when
    # this flag is True — otherwise False means "not probed" rather than
    # "confirmed absent".
    SUPPORTS_NATIVE_TRAILING_PROBE: bool = False

    async def place_trailing_stop(
        self,
        symbol: str,
        hold_side: str,
        size: float,
        callback_ratio: float,
        trigger_price: float,
        margin_mode: str = "cross",
    ) -> Optional[dict]:
        """Place a native trailing stop on the exchange.

        Default implementation returns ``None`` — meaning "not supported",
        the caller should fall back to software trailing in
        ``strategy.should_exit``. Subclasses that implement this must also
        set ``SUPPORTS_NATIVE_TRAILING_STOP = True``.
        """
        return None

    async def has_native_trailing_stop(self, symbol: str, hold_side: str) -> bool:
        """Return True if a native trailing-stop plan is already live for
        (symbol, hold_side) on the exchange.

        Used by position_monitor to detect DB/exchange drift — an existing
        plan on the exchange with ``native_trailing_stop=False`` in the DB
        means a previous placement succeeded but the flag failed to persist
        (e.g. a failed TP/SL edit that wrongly zeroed the flag). Default
        implementation returns False so exchanges without native trailing
        behave as before.
        """
        return False

    async def get_order_fees(self, symbol: str, order_id: str) -> float:
        """Get fees for a single order. Override in exchange-specific client."""
        return 0.0

    async def get_trade_total_fees(
        self, symbol: str, entry_order_id: str, close_order_id: Optional[str] = None
    ) -> float:
        """Get total fees (entry + exit) for a complete trade. Override in exchange-specific client."""
        return 0.0

    async def get_fill_price(
        self, symbol: str, order_id: str, **kwargs
    ) -> Optional[float]:
        """Get actual fill price for a completed order. Override in exchange-specific client."""
        return None

    async def get_close_fill_price(self, symbol: str) -> Optional[float]:
        """Get fill price of the most recent close order. Override in exchange-specific client."""
        return None

    async def get_funding_fees(
        self, symbol: str, start_time_ms: int, end_time_ms: int
    ) -> float:
        """Get total funding fees for a symbol between two timestamps. Override in exchange-specific client."""
        return 0.0

    async def check_affiliate_uid(self, uid: str) -> bool:
        """Check if a UID is in our affiliate/referral list. Override in exchange-specific client."""
        return False

    async def validate_symbol(self, symbol: str) -> bool:
        """Verify that a symbol is actually tradeable by fetching its ticker.

        This catches cases where the symbol list says a pair exists but the
        demo/testnet account cannot actually trade it.
        """
        try:
            ticker = await self.get_ticker(symbol)
            return ticker is not None and ticker.last_price > 0
        except Exception:
            return False

    # ── Risk-state readback (#191) ───────────────────────────────────
    # These three methods are the "source of truth" hook for
    # RiskStateManager (#190). Each exchange that supports the relevant
    # surface must override; the base class raises so omissions show up
    # immediately rather than silently returning empty snapshots.
    # Weex and Bitunix intentionally inherit the NotImplementedError —
    # there is NO automatic fallback. RiskStateManager handles those
    # exchanges by skipping the corresponding probe.

    async def get_position_tpsl(
        self, symbol: str, side: str
    ) -> "PositionTpSlSnapshot":
        """Return the live position TP/SL snapshot from the exchange.

        Implementations MUST return an empty snapshot (all order/price
        fields ``None``) when no plan exists — never raise on "not found".
        Genuine API errors must propagate.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_position_tpsl"
        )

    async def get_trailing_stop(
        self, symbol: str, side: str
    ) -> Optional["TrailingStopSnapshot"]:
        """Return the live trailing-stop snapshot from the exchange.

        Returns ``None`` when no native trailing plan exists or the exchange
        does not support native trailing at all (e.g. Hyperliquid).
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_trailing_stop"
        )

    async def get_close_reason_from_history(
        self, symbol: str, since_ts_ms: int
    ) -> Optional["CloseReasonSnapshot"]:
        """Return the most recent close event for ``symbol`` since ``since_ts_ms``.

        Returns ``None`` when no qualifying close was found. Used by
        RiskStateManager to attribute closes to TP/SL/trailing/manual.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement get_close_reason_from_history"
        )

    @property
    @abstractmethod
    def exchange_name(self) -> str:
        """Return the exchange identifier (e.g. 'bitget', 'weex')."""
        ...

    @property
    @abstractmethod
    def supports_demo(self) -> bool:
        """Whether this exchange supports demo/paper trading."""
        ...


class HTTPExchangeClientMixin:
    """Shared HTTP session management, circuit breaker integration, and request
    handling for REST-API-based exchange clients (Bitget, Weex, BingX, Bitunix).

    Subclasses must define:
        _session: Optional[aiohttp.ClientSession]
        _circuit_breaker: CircuitBreaker  — exchange-specific circuit breaker
        _client_error_class: Type[Exception]  — e.g. BitgetClientError
        base_url: str

    Subclasses must implement:
        _get_headers(...)  -> Dict[str, str]  — exchange-specific auth headers
        _parse_response(result, response) -> Any  — extract data from response JSON
    """

    _session: Optional[aiohttp.ClientSession] = None
    _client_error_class: Type[Exception]
    base_url: str

    @property
    def _circuit_breaker(self) -> "CircuitBreaker":
        """Return the exchange-specific circuit breaker.

        Subclasses must override this to return the module-level breaker
        instance (e.g. ``_bitget_breaker``).  Using a property ensures
        that tests patching the module-level variable are respected.
        """
        raise NotImplementedError(
            "Subclass must override _circuit_breaker property"
        )

    # ── Session management ────────────────────────────────────────

    async def _ensure_session(self) -> None:
        """Create an aiohttp session if none exists or the current one is closed."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        """Close the HTTP session and clean up resources."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # ── Circuit-breaker wrapper ───────────────────────────────────

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth: bool = True,
        use_circuit_breaker: bool = True,
    ) -> Any:
        """Execute an API request, optionally through the circuit breaker."""
        if use_circuit_breaker:
            async def _do():
                return await self._raw_request(method, endpoint, params, data, auth)
            try:
                return await self._circuit_breaker.call(_do)
            except CircuitBreakerError as e:
                raise self._client_error_class(f"API temporarily unavailable: {e}")
        return await self._raw_request(method, endpoint, params, data, auth)

    # ── Raw HTTP request (standard REST pattern) ──────────────────
    # Suitable for exchanges that sign (method + request_path + body).
    # Exchanges with different signing (BingX, Bitunix) override this.

    @with_retry(
        max_attempts=3,
        min_wait=1.0,
        max_wait=10.0,
        retry_on=(aiohttp.ClientError, asyncio.TimeoutError),
    )
    async def _raw_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        auth: bool = True,
    ) -> Any:
        """Perform the actual HTTP request and delegate response parsing."""
        await self._ensure_session()
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(data) if data else ""

        if params:
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            request_path = f"{endpoint}?{query_string}"
            url = f"{url}?{query_string}"
        else:
            request_path = endpoint

        headers = (
            self._get_headers(method, request_path, body)
            if auth
            else {"Content-Type": "application/json"}
        )

        try:
            async with self._session.request(
                method=method,
                url=url,
                headers=headers,
                data=body if body else None,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                result = await response.json()

                if response.status == 429:
                    raise aiohttp.ClientResponseError(
                        response.request_info,
                        response.history,
                        status=429,
                        message="Rate limited",
                    )

                return self._parse_response(result, response)

        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise
        except Exception as e:
            # Re-raise exchange-specific errors as-is
            if isinstance(e, self._client_error_class):
                raise
            raise self._client_error_class(f"Request failed: {e}") from e

    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """Build authenticated request headers. Must be overridden by subclasses."""
        raise NotImplementedError

    def _parse_response(self, result: Any, response: aiohttp.ClientResponse) -> Any:
        """Extract data from response JSON. Must be overridden by subclasses."""
        raise NotImplementedError


class ExchangeWebSocket(ABC):
    """
    Unified WebSocket interface for real-time exchange data.

    Each exchange adapter must implement connect/subscribe/disconnect.
    """

    def __init__(self, api_key: str = "", api_secret: str = "",
                 passphrase: str = "", demo_mode: bool = True, **kwargs):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.demo_mode = demo_mode
        self._connected = False

    @abstractmethod
    async def connect(self) -> None:
        """Establish WebSocket connection."""
        ...

    @abstractmethod
    async def subscribe_positions(
        self, symbols: List[str], callback: Callable
    ) -> None:
        """Subscribe to position updates."""
        ...

    @abstractmethod
    async def subscribe_orders(self, callback: Callable) -> None:
        """Subscribe to order updates."""
        ...

    @abstractmethod
    async def subscribe_ticker(
        self, symbols: List[str], callback: Callable
    ) -> None:
        """Subscribe to ticker/price updates."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect and clean up."""
        ...

    @property
    def is_connected(self) -> bool:
        return self._connected
