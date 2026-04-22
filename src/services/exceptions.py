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
