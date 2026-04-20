"""Process-wide manager for exchange WebSocket listeners (#216).

Owns one :class:`ExchangeWebSocketClient` per ``(user_id, exchange)``
pair and routes every incoming event into the
:class:`RiskStateManager`. Gated by the env flag
``EXCHANGE_WEBSOCKETS_ENABLED`` so default-off means zero behaviour
change compared to the polling-only baseline.

Architecture decision
---------------------
**Single process-wide manager.** The app has a single orchestrator and
a single RSM — colocating the WS listeners with them keeps lifecycle
management trivial (one ``start``, one ``stop_all``). We considered a
per-user manager and rejected it: the cross-user health counters used
by ``/api/health`` and the shared reconcile sweep on reconnect would
otherwise need a separate registry anyway.

Reconnect handling
------------------
The base-class client calls our :meth:`_on_reconnect` once per
successful reconnect. We respond by scheduling a one-shot
``RiskStateManager.reconcile`` sweep for every open trade of the
affected ``(user_id, exchange)`` pair — we deliberately do NOT replay
missed events. See ``docs/websockets.md`` for the rationale.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import select

from src.bot.risk_state_manager import RiskStateManager
from src.exchanges.websockets.base import ExchangeWebSocketClient
from src.exchanges.websockets.bitget_ws import BitgetWebSocketClient
from src.exchanges.websockets.hyperliquid_ws import HyperliquidWebSocketClient
from src.models.database import TradeRecord
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Env flag — consulted once per start_for_user call so operators can
# flip the feature on without a restart.
_FLAG_ENV_VAR = "EXCHANGE_WEBSOCKETS_ENABLED"

# Factory callable:
#   ``credentials_provider(user_id, exchange) -> dict | None``
# returns either a dict with the credentials each WS needs, or None to
# indicate "no credentials available, skip". Keeps encrypted-key access
# out of this module.
CredentialsProvider = Callable[[int, str], Awaitable[Optional[dict]]]


def is_enabled() -> bool:
    """Read the :envvar:`EXCHANGE_WEBSOCKETS_ENABLED` flag.

    Accepts ``1``, ``true``, ``yes``, ``on`` (case-insensitive) as truthy.
    Anything else — including unset — means disabled.
    """
    raw = os.getenv(_FLAG_ENV_VAR, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


class WebSocketManager:
    """Holds and supervises one WS client per ``(user_id, exchange)``.

    Parameters
    ----------
    risk_state_manager:
        Target of the event dispatch + reconnect sweeps.
    credentials_provider:
        Async callable that returns the per-exchange credentials for a
        user. Keeps the encrypted-key resolution out of this class.
    session_factory:
        Async context manager yielding an :class:`AsyncSession`. Used
        to look up a user's open trades for the reconnect sweep.
    """

    _SUPPORTED_EXCHANGES = ("bitget", "hyperliquid")

    def __init__(
        self,
        *,
        risk_state_manager: RiskStateManager,
        credentials_provider: CredentialsProvider,
        session_factory: Any,
    ) -> None:
        self._rsm = risk_state_manager
        self._credentials_provider = credentials_provider
        self._session_factory = session_factory
        self._clients: Dict[Tuple[int, str], ExchangeWebSocketClient] = {}
        self._lock = asyncio.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start_for_user(
        self,
        user_id: int,
        exchange: str,
    ) -> Optional[ExchangeWebSocketClient]:
        """Instantiate (or reuse) the WS client for ``(user_id, exchange)``.

        Returns the running client, or ``None`` if the feature flag is
        off, the exchange isn't supported, or credentials are missing.
        Errors in credential lookup or transport connect are logged and
        surfaced as ``None`` so callers don't have to wrap each call.
        """
        if not is_enabled():
            logger.debug(
                "ws_manager.disabled user=%s exchange=%s (flag=%s off)",
                user_id, exchange, _FLAG_ENV_VAR,
            )
            return None
        if exchange not in self._SUPPORTED_EXCHANGES:
            logger.debug(
                "ws_manager.unsupported_exchange user=%s exchange=%s",
                user_id, exchange,
            )
            return None

        async with self._lock:
            existing = self._clients.get((user_id, exchange))
            if existing is not None and existing.is_connected:
                return existing

            credentials = await self._credentials_provider(user_id, exchange)
            if credentials is None:
                logger.info(
                    "ws_manager.no_credentials user=%s exchange=%s",
                    user_id, exchange,
                )
                return None

            client = self._build_client(user_id, exchange, credentials)
            self._clients[(user_id, exchange)] = client
            # Fire-and-forget the run loop — base class owns reconnect.
            client.start()
            return client

    async def stop_for_user(self, user_id: int, exchange: str) -> None:
        """Tear down a single WS client (e.g. after user disables an exchange)."""
        async with self._lock:
            client = self._clients.pop((user_id, exchange), None)
        if client is not None:
            await client.disconnect()

    async def stop_all(self) -> None:
        """Disconnect every client and clear the registry.

        Disconnect errors are logged but never re-raised — the manager
        must leave a clean slate even if one transport misbehaves.
        """
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                await client.disconnect()
            except Exception as e:  # noqa: BLE001 — best-effort teardown
                logger.warning(
                    "ws_manager.stop_error user=%s exchange=%s error=%s",
                    client.user_id, client.exchange, e,
                )

    # ── Health ────────────────────────────────────────────────────

    def connected_counts(self) -> Dict[str, int]:
        """Return connected-client counts per exchange for ``/api/health``."""
        counts: Dict[str, int] = {ex: 0 for ex in self._SUPPORTED_EXCHANGES}
        for (_, exchange), client in self._clients.items():
            if client.is_connected:
                counts[exchange] = counts.get(exchange, 0) + 1
        return counts

    # ── Dispatch ──────────────────────────────────────────────────

    async def _on_event(
        self,
        user_id: int,
        exchange: str,
        event_type: str,
        payload: dict,
    ) -> None:
        """Forward a parsed WS event into the RSM.

        Wrapped so any RSM-side exception is logged and doesn't bubble
        into the base-class read loop (which would count it as a
        transport error and trigger reconnect).
        """
        try:
            await self._rsm.on_exchange_event(
                user_id=user_id,
                exchange=exchange,
                event_type=event_type,
                payload=payload,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "ws_manager.rsm_dispatch_error user=%s exchange=%s event=%s error=%s",
                user_id, exchange, event_type, e,
            )

    async def _on_reconnect(self, user_id: int, exchange: str) -> None:
        """One-shot reconcile sweep for every open trade after a reconnect.

        Called by the base class exactly once per successful reconnect.
        Missed events are deliberately NOT replayed — instead we force
        the RSM to re-probe exchange state for every open trade of the
        affected ``(user, exchange)``. This is correct by construction:
        reconcile is idempotent and the exchange is the source of truth.
        """
        trade_ids = await self._open_trade_ids(user_id, exchange)
        if not trade_ids:
            logger.info(
                "ws_manager.reconnect_no_open_trades user=%s exchange=%s",
                user_id, exchange,
            )
            return
        logger.info(
            "ws_manager.reconnect_sweep user=%s exchange=%s trades=%s",
            user_id, exchange, len(trade_ids),
        )
        for trade_id in trade_ids:
            try:
                await self._rsm.reconcile(trade_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "ws_manager.reconcile_sweep_error trade=%s error=%s",
                    trade_id, e,
                )

    async def _open_trade_ids(self, user_id: int, exchange: str) -> List[int]:
        """Return the IDs of all open trades for ``(user, exchange)``."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(TradeRecord.id).where(
                    TradeRecord.user_id == user_id,
                    TradeRecord.exchange == exchange,
                    TradeRecord.status == "open",
                )
            )
            return [row[0] for row in result.all()]

    # ── Client construction ───────────────────────────────────────

    def _build_client(
        self,
        user_id: int,
        exchange: str,
        credentials: dict,
    ) -> ExchangeWebSocketClient:
        """Dispatch to the correct subclass. Kept as a method so tests can monkey-patch."""
        if exchange == "bitget":
            return BitgetWebSocketClient(
                user_id=user_id,
                api_key=credentials["api_key"],
                api_secret=credentials["api_secret"],
                passphrase=credentials.get("passphrase", ""),
                demo_mode=bool(credentials.get("demo_mode", False)),
                on_event=self._on_event,
                on_reconnect=self._on_reconnect,
            )
        if exchange == "hyperliquid":
            return HyperliquidWebSocketClient(
                user_id=user_id,
                wallet_address=credentials["wallet_address"],
                mainnet=bool(credentials.get("mainnet", True)),
                on_event=self._on_event,
                on_reconnect=self._on_reconnect,
            )
        raise ValueError(f"unsupported exchange for ws: {exchange}")  # pragma: no cover


__all__ = ["WebSocketManager", "is_enabled"]
