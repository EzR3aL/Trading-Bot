"""
BotWorker: A single autonomous trading bot instance.

Each BotWorker runs its own strategy loop on its own schedule,
trading on a specific exchange with its own parameters.
Managed by the BotOrchestrator.

Mixin architecture (refactored from a 1260 LOC monolithic class). The
class is now assembled from three focused mixins so each concern lives in
its own file and stays under the project's "≤400 LOC per class" rule:

- ``ComponentsMixin`` (`_components_mixin.py`)
  Construction of the ``PositionMonitor`` / ``TradeExecutor`` collaborators
  and every thin async forwarder for them, the ``Notifier``, and the
  ``TradeCloser``. State proxies (``_trailing_stop_backoff`` etc.) live
  here too so external callers see no API change.
- ``LifecycleMixin`` (`_lifecycle_mixin.py`)
  ``initialize`` / ``start`` / ``stop`` / ``graceful_stop`` /
  ``_setup_schedule`` / ``get_status_dict`` — every method that
  mutates run state.
- ``ScheduleMixin`` (`_schedule_mixin.py`)
  The scheduler-driven analyze-and-trade tick: per-symbol fan-out,
  per-asset budget, dedup, daily summary.

Pure composition collaborators continue to live under
``src/bot/components/`` (``Notifier``, ``TradeCloser``,
``PositionMonitor``, ``TradeExecutor``, ``AlertThrottler``) and are
constructed in ``BotWorker.__init__`` exactly as before. Public API of
``BotWorker`` is unchanged.

Hyperliquid pre-start gates live on ``ExchangeClient.pre_start_checks``
(#ARCH-H2, #313).
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.settings import settings
from src.bot._components_mixin import ComponentsMixin
from src.bot._helpers import (  # noqa: F401 — re-exported for back-compat
    _noop_async,
    _safe_json_loads,
    DEFAULT_MARKET_HOURS,
)
from src.bot._lifecycle_mixin import LifecycleMixin
from src.bot._schedule_mixin import ScheduleMixin
from src.bot.components.notifier import Notifier
from src.bot.components.risk import AlertThrottler, RiskComponentDeps
from src.bot.components.trade_closer import TradeCloser
from src.exchanges.base import ExchangeClient
from src.exchanges.factory import create_exchange_client  # noqa: F401 — re-exported for back-compat
from src.models.database import BotConfig
from src.models.enums import BotStatus  # noqa: F401 — re-exported for back-compat
from src.models.session import get_session  # noqa: F401 — re-exported for back-compat
from src.risk.risk_manager import RiskManager
from src.strategy import BaseStrategy, StrategyRegistry  # noqa: F401 — StrategyRegistry re-exported for back-compat
from src.utils.encryption import decrypt_value  # noqa: F401 — re-exported for back-compat
from src.utils.logger import get_logger


logger = get_logger(__name__)


class BotWorker(ComponentsMixin, LifecycleMixin, ScheduleMixin):
    """
    A single bot instance running its own strategy loop.

    Lifecycle:
    1. Created by BotOrchestrator with a BotConfig
    2. Initializes exchange client, strategy, risk manager
    3. Runs strategy loop on configured schedule
    4. Stopped by Orchestrator or on error (with auto-restart)

    Composition: every collaborator under ``src/bot/components/`` is
    owned by ``self`` and reached via thin forwarders provided by
    ``ComponentsMixin``. The lifecycle and tick loop live on
    ``LifecycleMixin`` and ``ScheduleMixin`` respectively.
    """

    def __init__(
        self,
        bot_config_id: int,
        scheduler: Optional[AsyncIOScheduler] = None,
        user_trade_lock: Optional[asyncio.Lock] = None,
    ):
        self.bot_config_id = bot_config_id
        self._config: Optional[BotConfig] = None
        self._client: Optional[ExchangeClient] = None
        self._strategy: Optional[BaseStrategy] = None
        self._risk_manager: Optional[RiskManager] = None
        self._scheduler: Optional[AsyncIOScheduler] = scheduler
        # Notifier component — composition-owned (ARCH-H1 Phase 1 PR-1, #274).
        # Uses a getter because _config is loaded during start(), not __init__.
        self._notifier: Notifier = Notifier(bot_config_id, lambda: self._config)
        self._owns_scheduler = scheduler is None  # Only stop if we created it
        self._task: Optional[asyncio.Task] = None

        self.status = BotStatus.IDLE
        self.error_message: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.last_analysis: Optional[datetime] = None
        self.trades_today: int = 0

        # Per-symbol lock to prevent duplicate position opening
        self._symbol_locks: dict[str, asyncio.Lock] = {}

        # Per-user lock shared across all bots of the same user.
        # Ensures atomic risk-check-then-trade to prevent daily loss bypass.
        self._user_trade_lock: asyncio.Lock = user_trade_lock or asyncio.Lock()

        # Per-mode clients for "both" mode
        self._demo_client: Optional[ExchangeClient] = None
        self._live_client: Optional[ExchangeClient] = None

        # Graceful shutdown support
        self._shutting_down: bool = False
        self._operation_in_progress: asyncio.Event = asyncio.Event()
        self._operation_in_progress.set()  # Not busy initially

        # TradeCloser component — composition-owned (ARCH-H1 Phase 1 PR-3, #279).
        # Getters defer attribute access: _config and _risk_manager are attached
        # during initialize(), and _send_notification is the mixin-bound method.
        self._trade_closer: TradeCloser = TradeCloser(
            bot_config_id=bot_config_id,
            config_getter=lambda: self._config,
            risk_manager_getter=lambda: self._risk_manager,
            notification_sender=self._send_notification,
        )

        # Auto-recovery tracking
        self._consecutive_errors: int = 0

        # Signal deduplication cache
        self._last_signal_keys: dict[str, datetime] = {}
        self._last_signal_cleanup: datetime = datetime.now(timezone.utc)

        # Risk alert deduplication (reset daily) — AlertThrottler component
        # owns the dedupe set + last-reset timestamp + notifier dispatch.
        # The notifier is wired via a thunk so tests that swap
        # ``worker._send_notification`` after construction still route
        # through the mock.
        # See issue #326, ARCH-H2 Phase 1 PR-4 / Phase 2 PR-8 (#339).
        async def _notification_thunk(send_fn, *, event_type, summary):
            await self._send_notification(
                send_fn, event_type=event_type, summary=summary,
            )

        self._risk_component_deps = RiskComponentDeps(
            bot_config_id=bot_config_id,
            notifier=_notification_thunk,
        )
        self._alert_throttler = AlertThrottler(
            bot_config_id=bot_config_id,
            notification_sender=_notification_thunk,
        )

        # Wire the shared RiskStateManager singleton into the close-detection
        # path so `_handle_closed_position` uses exchange-readback classify_close
        # instead of the legacy proximity heuristic. Singleton is intentional —
        # the per-(trade, leg) lock map must be shared with the API path.
        # See issue #218, Epic #188.
        if settings.risk.risk_state_manager_enabled:
            from src.api.dependencies.risk_state import get_risk_state_manager
            self._risk_state_manager = get_risk_state_manager()

        # Initialize per-instance position monitor state via the components
        # mixin — this constructs the PositionMonitor component bound to self.
        # (ARCH-H1 Phase 1 PR-4, #281).
        self._init_monitor_state()

        # Build the composition-owned TradeExecutor (#72, ARCH-H1 Phase 1 PR-5).
        # The mixin holds the construction; the public/private call sites use
        # the forwarders provided by ``ComponentsMixin``.
        self._init_trade_executor_state()

        # Start the Hyperliquid software trailing emulator (#216 Section 3.1).
        # HL has no native trailing primitive. The emulator is a process-wide
        # singleton (one watchdog services every HL trade regardless of which
        # bot opened it) so attempting to start it from each BotWorker is a
        # no-op on duplicate starts. Gated by HL_SOFTWARE_TRAILING_ENABLED.
        if settings.risk.hl_software_trailing_enabled:
            from src.api.dependencies.hl_trailing import get_hl_trailing_emulator
            self._hl_trailing_emulator = get_hl_trailing_emulator()
            try:
                self._hl_trailing_emulator.start(enabled=True)
            except RuntimeError:
                # No running event loop yet — orchestrator will start the
                # emulator explicitly once its loop is alive. Tolerate here
                # so unit tests that construct BotWorker synchronously pass.
                pass
