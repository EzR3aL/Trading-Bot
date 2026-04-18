"""Dependency wiring for the :class:`RiskStateManager` singleton.

The TP/SL refactor (#192) routes ``PUT /api/trades/{id}/tp-sl`` through
:class:`src.bot.risk_state_manager.RiskStateManager` when the
``risk_state_manager_enabled`` feature flag is on. To keep the router
clean we centralise:

* **Singleton management** — one shared manager per process, so the
  per-(trade, leg) lock map is honoured across requests.
* **Exchange-client factory** — resolves ``ExchangeConnection`` from the
  DB and decrypts the credentials using the same helpers as
  :func:`src.exchanges.factory.get_all_user_clients`.
* **Idempotency cache** — an in-memory TTL store keyed by the
  ``Idempotency-Key`` header so retries do not double-place orders.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from sqlalchemy import select

from src.bot.risk_state_manager import RiskStateManager
from src.exchanges.base import ExchangeClient
from src.exchanges.factory import create_exchange_client
from src.models.database import ExchangeConnection
from src.models.session import get_session
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ── Idempotency cache ──────────────────────────────────────────────

#: TTL for idempotency entries — long enough to swallow normal retries
#: but short enough that stale state cannot poison subsequent requests.
IDEMPOTENCY_TTL_SECONDS = 60


class IdempotencyCache:
    """Simple in-memory TTL cache for idempotent endpoint responses.

    Keys are arbitrary strings (typically the ``Idempotency-Key`` header
    namespaced by the route + trade id). Values are arbitrary objects
    (typically the cached response payload). Entries expire after
    :data:`IDEMPOTENCY_TTL_SECONDS`.
    """

    def __init__(self, ttl_seconds: int = IDEMPOTENCY_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """Return the cached value or ``None`` if missing/expired."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.monotonic() - stored_at > self._ttl:
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key`` for at most ``ttl_seconds``."""
        async with self._lock:
            self._store[key] = (time.monotonic(), value)
            self._evict_expired_locked()

    def _evict_expired_locked(self) -> None:
        """Drop expired entries — caller MUST hold ``self._lock``."""
        now = time.monotonic()
        stale = [k for k, (ts, _) in self._store.items() if now - ts > self._ttl]
        for k in stale:
            self._store.pop(k, None)

    def clear(self) -> None:
        """Best-effort cache reset — used by tests between scenarios."""
        self._store.clear()


# Module-level singletons. Tests may swap these via
# ``set_risk_state_manager`` / ``set_idempotency_cache``.
_manager: Optional[RiskStateManager] = None
_idempotency_cache: IdempotencyCache = IdempotencyCache()


def _make_exchange_client_factory():
    """Return an exchange-client factory compatible with RiskStateManager.

    The manager calls ``factory(user_id, exchange, demo_mode)`` and
    expects a (possibly awaitable) :class:`ExchangeClient`. We shape an
    ``async`` factory so we can do a DB lookup + credential decryption
    on demand.
    """

    async def _factory(user_id: int, exchange: str, demo_mode: bool) -> ExchangeClient:
        async with get_session() as session:
            result = await session.execute(
                select(ExchangeConnection).where(
                    ExchangeConnection.user_id == user_id,
                    ExchangeConnection.exchange_type == exchange,
                )
            )
            conn = result.scalar_one_or_none()

        if conn is None:
            raise RuntimeError(
                f"No ExchangeConnection for user={user_id} exchange={exchange}"
            )

        api_key_enc = (
            conn.demo_api_key_encrypted if demo_mode else conn.api_key_encrypted
        )
        api_secret_enc = (
            conn.demo_api_secret_encrypted if demo_mode else conn.api_secret_encrypted
        )
        passphrase_enc = (
            conn.demo_passphrase_encrypted if demo_mode else conn.passphrase_encrypted
        )

        if not api_key_enc or not api_secret_enc:
            raise RuntimeError(
                f"Missing API credentials for user={user_id} exchange={exchange} "
                f"demo={demo_mode}"
            )

        return create_exchange_client(
            exchange_type=exchange,
            api_key=decrypt_value(api_key_enc),
            api_secret=decrypt_value(api_secret_enc),
            passphrase=decrypt_value(passphrase_enc) if passphrase_enc else "",
            demo_mode=demo_mode,
        )

    return _factory


def get_risk_state_manager() -> RiskStateManager:
    """Return the process-wide :class:`RiskStateManager` singleton.

    The manager keeps an in-memory lock map keyed by ``(trade_id, leg)``.
    Sharing one instance across requests is what guarantees that two
    concurrent edits of the same trade serialise correctly.
    """
    global _manager
    if _manager is None:
        _manager = RiskStateManager(
            exchange_client_factory=_make_exchange_client_factory(),
            session_factory=get_session,
        )
    return _manager


def set_risk_state_manager(manager: Optional[RiskStateManager]) -> None:
    """Override the singleton — intended for tests only."""
    global _manager
    _manager = manager


def get_idempotency_cache() -> IdempotencyCache:
    """Return the process-wide idempotency cache."""
    return _idempotency_cache


def set_idempotency_cache(cache: IdempotencyCache) -> None:
    """Override the cache — intended for tests only."""
    global _idempotency_cache
    _idempotency_cache = cache
