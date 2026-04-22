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
