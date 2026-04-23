"""Position monitoring proxy for BotWorker (mixin).

The real logic lives in ``src.bot.components.position_monitor.PositionMonitor``.
This mixin is kept as a thin proxy until the Phase 1 finalize PR removes
all mixin shims. ARCH-H1 Phase 1 PR-4 (#281).

``_init_monitor_state`` constructs a ``PositionMonitor`` component bound to
``self`` via getters, so the mixin works whether used inside a full
``BotWorker`` or in a standalone test harness. Access to state attributes
(e.g. ``_trailing_stop_backoff``) auto-initializes the component when the
harness forgot to call ``_init_monitor_state`` explicitly, preserving the
Phase 0 characterization-test behavior.
"""

from typing import Optional

from src.bot.components.position_monitor import PositionMonitor
# Re-exported for backwards compatibility — older characterization tests
# import these constants directly from this module.
from src.bot.components.position_monitor import (  # noqa: F401
    _GLITCH_ALERT_THRESHOLD,
    _GLITCH_WARN_THRESHOLD,
    _POSITION_GONE_DELAY_S,
    _POSITION_GONE_THRESHOLD,
    _TRAILING_SKIP_STATES,
    _TRAILING_STOP_RETRY_MINUTES,
)
from src.bot.risk_state_manager import RiskStateManager
from src.models.database import TradeRecord


async def _noop_async(*_args, **_kwargs) -> None:  # pragma: no cover - defensive default
    return None


class PositionMonitorMixin:
    """Thin proxy — forwards position monitoring calls to ``self._position_monitor``.

    The component holds all per-instance state (trailing-stop backoff, glitch
    counters, PnL alert cache). Attribute reads/writes on the mixin route to
    the component so existing callers that touch ``self._trailing_stop_backoff``
    etc. continue to work transparently.
    """

    def _init_monitor_state(self) -> None:
        """Create the backing ``PositionMonitor`` component bound to ``self``.

        Uses late-binding lambdas for optional callables so a test harness can
        omit ``_send_notification`` / ``_close_and_record_trade`` without
        breaking construction (they will resolve at call time if present).
        """
        if getattr(self, "_risk_state_manager", None) is None:
            self._risk_state_manager: Optional[RiskStateManager] = None

        self._position_monitor: PositionMonitor = PositionMonitor(
            bot_config_id=getattr(self, "bot_config_id", 0),
            config_getter=lambda: getattr(self, "_config", None),
            strategy_getter=lambda: getattr(self, "_strategy", None),
            risk_state_manager_getter=lambda: getattr(self, "_risk_state_manager", None),
            client_factory=lambda demo_mode: (
                self._get_client(demo_mode)
                if hasattr(self, "_get_client") else None
            ),
            close_trade=lambda *a, **kw: (
                self._close_and_record_trade(*a, **kw)
                if hasattr(self, "_close_and_record_trade")
                else _noop_async(*a, **kw)
            ),
            notification_sender=lambda *a, **kw: (
                self._send_notification(*a, **kw)
                if hasattr(self, "_send_notification")
                else _noop_async(*a, **kw)
            ),
        )

    def _ensure_monitor(self) -> PositionMonitor:
        """Lazily build the component if ``_init_monitor_state`` was skipped."""
        if not hasattr(self, "_position_monitor") or self._position_monitor is None:
            self._init_monitor_state()
        return self._position_monitor

    # --- State access (forwarded to the component so callers stay unchanged) ---

    @property
    def _trailing_stop_backoff(self):
        return self._ensure_monitor()._trailing_stop_backoff

    @_trailing_stop_backoff.setter
    def _trailing_stop_backoff(self, value):
        self._ensure_monitor()._trailing_stop_backoff = value

    @property
    def _trailing_stop_lock(self):
        return self._ensure_monitor()._trailing_stop_lock

    @_trailing_stop_lock.setter
    def _trailing_stop_lock(self, value):
        self._ensure_monitor()._trailing_stop_lock = value

    @property
    def _glitch_counter(self):
        return self._ensure_monitor()._glitch_counter

    @_glitch_counter.setter
    def _glitch_counter(self, value):
        self._ensure_monitor()._glitch_counter = value

    @property
    def _pnl_alerts_sent(self):
        return self._ensure_monitor()._pnl_alerts_sent

    @_pnl_alerts_sent.setter
    def _pnl_alerts_sent(self, value):
        self._ensure_monitor()._pnl_alerts_sent = value

    @property
    def _pnl_alert_parsed(self):
        return self._ensure_monitor()._pnl_alert_parsed

    @_pnl_alert_parsed.setter
    def _pnl_alert_parsed(self, value):
        self._ensure_monitor()._pnl_alert_parsed = value

    # --- Method proxies -------------------------------------------------------

    async def _monitor_positions_safe(self) -> None:
        await self._ensure_monitor().monitor_safe()

    async def _monitor_positions(self) -> None:
        await self._ensure_monitor().monitor()

    async def _check_position(self, trade: TradeRecord, session) -> None:
        await self._ensure_monitor().check_position(trade, session)

    async def _try_place_native_trailing_stop(
        self, trade, client, position, current_price, session,
    ) -> None:
        await self._ensure_monitor().try_place_native_trailing_stop(
            trade, client, position, current_price, session,
        )

    async def _confirm_position_closed(self, trade, client) -> bool:
        return await self._ensure_monitor().confirm_position_closed(trade, client)

    async def _check_pnl_alert(self, trade, current_price) -> None:
        await self._ensure_monitor().check_pnl_alert(trade, current_price)

    @staticmethod
    def _classify_close_heuristic(trade: TradeRecord, exit_price: float) -> str:
        return PositionMonitor.classify_close_heuristic(trade, exit_price)

    async def _handle_closed_position(self, trade, client, session) -> None:
        await self._ensure_monitor().handle_closed_position(trade, client, session)
