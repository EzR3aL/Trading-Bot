"""Domain exceptions for the service layer.

Routers map these to HTTP status codes; this module must not import FastAPI.
"""


class ServiceError(Exception):
    """Base for all service-layer domain errors. Router maps these to HTTP status codes."""


class TradeNotFound(ServiceError):
    """Raised when a requested trade does not exist in the database."""


class NotOwnedByUser(ServiceError):
    """Raised when the authenticated user does not own the requested trade."""


class SyncInProgress(ServiceError):
    """Raised when a trade sync is already running for the user."""


class InvalidTpSlIntent(ServiceError):
    """Raised when a TP/SL/trailing intent fails validation before RSM dispatch."""


class BotNotFound(ServiceError):
    """Raised when the requested bot does not exist or is not owned by the user."""


class MaxBotsReached(ServiceError):
    """Raised when the user has reached the per-user bot limit."""


class StrategyNotFound(ServiceError):
    """Raised when a bot create/update references an unknown strategy type."""

    def __init__(self, strategy_name: str) -> None:
        super().__init__(strategy_name)
        self.strategy_name = strategy_name


class InvalidSymbols(ServiceError):
    """Raised when one or more requested trading pairs are not listed on the exchange.

    Carries the exchange, demo/live mode label, and the rejected symbol list so
    the router can render a user-facing detail string without re-deriving it.
    """

    def __init__(
        self,
        exchange: str,
        mode_label: str,
        invalid_symbols: list[str],
    ) -> None:
        super().__init__(
            f"Symbols not available on {exchange} ({mode_label}): {invalid_symbols}"
        )
        self.exchange = exchange
        self.mode_label = mode_label
        self.invalid_symbols = invalid_symbols


class BotIsRunning(ServiceError):
    """Raised when an update is attempted against a bot that is currently running."""

    def __init__(self, bot_id: int) -> None:
        super().__init__(f"Bot {bot_id} is running")
        self.bot_id = bot_id


class TradeNotOpen(ServiceError):
    """Raised when a write operation targets a trade that is not currently open.

    Carries the trade id so the router can compose a user-friendly error
    detail without re-querying.
    """

    def __init__(self, trade_id: int) -> None:
        super().__init__(f"Trade {trade_id} is not open")
        self.trade_id = trade_id


class ExchangeConnectionMissing(ServiceError):
    """Raised when the user has no :class:`ExchangeConnection` for the trade's exchange.

    Also raised when the connection exists but has no usable API keys
    (neither demo nor live credentials). The router maps this to a 400.
    """


class TpSlExchangeNotSupported(ServiceError):
    """Raised when the exchange client does not support native TP/SL orders.

    Carries the exchange name so the router can surface it in the detail
    string (``ERR_TPSL_EXCHANGE_NOT_SUPPORTED.format(exchange=...)``).
    """

    def __init__(self, exchange: str) -> None:
        super().__init__(f"TP/SL not supported on {exchange}")
        self.exchange = exchange


class TpSlUpdateFailed(ServiceError):
    """Raised when the exchange rejects a TP/SL update with an opaque error.

    Carries the raw exchange error message so the router can decide
    whether to surface it as 400 (validation-ish) or 502 (upstream).
    """

    def __init__(self, raw_error: str) -> None:
        super().__init__(raw_error)
        self.raw_error = raw_error
