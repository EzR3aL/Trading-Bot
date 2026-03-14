"""Abstract base classes for exchange clients and websockets."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, List, Optional

from src.exchanges.types import Balance, FundingRateInfo, Order, Position, Ticker

if TYPE_CHECKING:
    from src.exchanges.rate_limiter import ExchangeRateLimiter


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

    async def place_trailing_stop(
        self,
        symbol: str,
        hold_side: str,
        size: float,
        callback_ratio: float,
        trigger_price: float,
        margin_mode: str = "cross",
    ) -> Optional[dict]:
        """Place a native trailing stop on the exchange. Override in exchange-specific client."""
        return None

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
