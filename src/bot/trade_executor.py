"""Trade execution proxy for BotWorker (mixin).

The real logic lives in ``src.bot.components.trade_executor.TradeExecutor``.
This mixin is kept as a thin proxy until the Phase 1 finalize PR removes
all mixin shims. ARCH-H1 Phase 1 PR-5 (#72).

``_init_trade_executor_state`` constructs a ``TradeExecutor`` component
bound to ``self`` via getters and callbacks. The callbacks deliver the
two side effects the mixin used to mutate directly:

* ``on_trade_opened`` — increments ``self.trades_today`` after a
  successful open.
* ``on_fatal_error`` — flips ``self.status`` to ``BotStatus.ERROR`` and
  stores the friendly message on ``self.error_message`` when a fatal
  configuration error is detected.

The free-standing helpers ``_make_user_friendly`` / ``_is_fatal_error``
and the pattern constants are re-exported for backwards compatibility
with any callers that imported them directly from this module.
"""

from typing import Optional

from src.bot.components.trade_executor import TradeExecutor
# Re-exported for backwards compatibility — older call sites/tests import
# these directly from this module.
from src.bot.components.trade_executor import (  # noqa: F401
    _FATAL_ERROR_PATTERNS,
    _USER_FRIENDLY_ERRORS,
    _is_fatal_error,
    _make_user_friendly,
)


async def _noop_async(*_args, **_kwargs) -> None:  # pragma: no cover - defensive default
    return None


class TradeExecutorMixin:
    """Thin proxy — forwards trade execution calls to ``self._trade_executor``."""

    def _init_trade_executor_state(self) -> None:
        """Build the backing ``TradeExecutor`` component bound to ``self``."""
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
        """Lazily build the component if ``_init_trade_executor_state`` was skipped."""
        if getattr(self, "_trade_executor", None) is None:
            self._init_trade_executor_state()
        return self._trade_executor

    # --- worker-state callbacks ----------------------------------------

    def _on_trade_opened(self) -> None:
        """Bump the per-day counter; tolerated if the worker hasn't initialized it."""
        current = getattr(self, "trades_today", 0) or 0
        self.trades_today = current + 1

    def _on_fatal_trade_error(self, friendly_error: str) -> None:
        """Flip the bot to ERROR state on unrecoverable config failures."""
        from src.bot.bot_worker import BotStatus  # late import avoids circular dep
        self.status = BotStatus.ERROR
        self.error_message = friendly_error

    # --- method proxies ------------------------------------------------

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

    # --- public wrappers used by self-managed strategies ---------------

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
