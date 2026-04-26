"""Component-collaborator construction and forwarder mixin for BotWorker.

Extracted from ``src/bot/bot_worker.py``. Owns:

* Construction of the ``PositionMonitor`` and ``TradeExecutor`` collaborators
  (the ``Notifier``, ``TradeCloser``, ``AlertThrottler`` and
  ``RiskComponentDeps`` collaborators stay in ``BotWorker.__init__`` because
  they need values that are only available in that constructor's local scope).
* The ``trades_today`` / ``ERROR``-status callbacks the ``TradeExecutor``
  invokes.
* State-proxy properties (``_trailing_stop_backoff`` etc.) that read/write
  through to the bound ``PositionMonitor`` instance.
* Thin async forwarder methods for every public/private call site that used
  to live on the former mixin classes.

This module changes no behaviour — it is a pure mechanical extraction.
"""

from typing import Any, Callable, List, Optional

from src.bot._helpers import _noop_async
from src.bot.components.position_monitor import PositionMonitor
from src.bot.components.trade_executor import TradeExecutor
from src.exchanges.base import ExchangeClient
from src.models.database import TradeRecord
from src.models.enums import BotStatus


class ComponentsMixin:
    """Owns PositionMonitor / TradeExecutor construction + every forwarder."""

    # ── Component construction ─────────────────────────────────────────
    # Formerly on PositionMonitorMixin / TradeExecutorMixin — inlined as
    # part of ARCH-H1 Phase 1 finalize (#285). The callbacks keep the same
    # late-binding semantics so a partially-constructed worker (e.g. in
    # unit-test harnesses) does not blow up.

    def _init_monitor_state(self) -> None:
        """Create the ``PositionMonitor`` component bound to ``self``."""
        from src.bot.risk_state_manager import RiskStateManager
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

    def _init_trade_executor_state(self) -> None:
        """Build the ``TradeExecutor`` component bound to ``self``."""
        self._trade_executor: TradeExecutor = TradeExecutor(
            bot_config_id=getattr(self, "bot_config_id", 0),
            config_getter=lambda: getattr(self, "_config", None),
            risk_manager_getter=lambda: getattr(self, "_risk_manager", None),
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
            client_getter=lambda: (
                getattr(self, "_client", None) or getattr(self, "client", None)
            ),
            on_trade_opened=self._on_trade_opened,
            on_fatal_error=self._on_fatal_trade_error,
        )

    def _ensure_trade_executor(self) -> TradeExecutor:
        if getattr(self, "_trade_executor", None) is None:
            self._init_trade_executor_state()
        return self._trade_executor

    def _on_trade_opened(self) -> None:
        """Bump the per-day counter; tolerated if the worker hasn't initialized it."""
        current = getattr(self, "trades_today", 0) or 0
        self.trades_today = current + 1

    def _on_fatal_trade_error(self, friendly_error: str) -> None:
        """Flip the bot to ERROR state on unrecoverable config failures."""
        self.status = BotStatus.ERROR
        self.error_message = friendly_error

    # ── PositionMonitor state proxies ──────────────────────────────────
    # Formerly PositionMonitorMixin properties. Reads/writes route to the
    # component so existing callers that touch ``self._trailing_stop_backoff``
    # etc. keep working transparently.

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

    # ── PositionMonitor method forwarders ──────────────────────────────

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

    # ── TradeExecutor forwarders ───────────────────────────────────────

    async def _execute_trade(self, signal, client, demo_mode, asset_budget: Optional[float] = None):
        await self._ensure_trade_executor().execute(signal, client, demo_mode, asset_budget)

    async def _resolve_pending_trade(
        self, pending_trade_id: int | None, status: str, error_message: str | None = None,
    ):
        await self._ensure_trade_executor().resolve_pending_trade(
            pending_trade_id, status, error_message,
        )

    async def _notify_trade_failure(self, signal, mode_str: str, error: str):
        await self._ensure_trade_executor().notify_trade_failure(signal, mode_str, error)

    async def get_open_trades_count(self, bot_config_id: int) -> int:
        return await self._ensure_trade_executor().get_open_trades_count(bot_config_id)

    async def get_open_trades_for_bot(self, bot_config_id: int) -> list:
        return await self._ensure_trade_executor().get_open_trades_for_bot(bot_config_id)

    async def execute_trade(
        self,
        *,
        symbol: str,
        side: str,
        notional_usdt: float,
        leverage: int,
        reason: str,
        bot_config_id: int,
        take_profit_pct: Optional[float] = None,
        stop_loss_pct: Optional[float] = None,
    ) -> None:
        await self._ensure_trade_executor().execute_wrapper(
            symbol=symbol,
            side=side,
            notional_usdt=notional_usdt,
            leverage=leverage,
            reason=reason,
            bot_config_id=bot_config_id,
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
        )

    async def close_trade_by_strategy(self, trade, *, reason: str) -> None:
        await self._ensure_trade_executor().close_by_strategy(trade, reason=reason)

    # ── Notifier forwarders (former NotificationsMixin) ────────────────

    async def _get_discord_notifier(self):
        return await self._notifier.get_discord_notifier()

    async def _get_notifiers(self) -> List[Any]:
        return await self._notifier.get_notifiers()

    async def _send_notification(
        self,
        send_fn: Callable,
        event_type: str = "unknown",
        summary: Optional[str] = None,
    ) -> None:
        # Load notifiers through the proxy (not the component directly) so
        # tests that stub ``worker._get_notifiers`` keep working.
        try:
            notifiers = await self._get_notifiers()
        except Exception:
            notifiers = []
        await self._notifier.send_notification(
            send_fn, event_type, summary, notifiers=notifiers
        )

    # ── TradeCloser forwarder (former TradeCloserMixin) ────────────────

    async def _close_and_record_trade(
        self,
        trade: TradeRecord,
        exit_price: float,
        exit_reason: str,
        *,
        fees: Optional[float] = None,
        funding_paid: Optional[float] = None,
        builder_fee: Optional[float] = None,
        strategy_reason: Optional[str] = None,
    ) -> None:
        await self._trade_closer.close_and_record(
            trade,
            exit_price,
            exit_reason,
            fees=fees,
            funding_paid=funding_paid,
            builder_fee=builder_fee,
            strategy_reason=strategy_reason,
        )

    # ── Misc helpers used across mixins ────────────────────────────────

    def _get_client(self, demo_mode: bool) -> Optional[ExchangeClient]:
        """Return the exchange client for the given mode."""
        return self._demo_client if demo_mode else self._live_client
