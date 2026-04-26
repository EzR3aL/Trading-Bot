"""Schedule / analyze-and-trade tick mixin for BotWorker.

Extracted from ``src/bot/bot_worker.py``. Owns the scheduler-driven tick
loop: analyze markets, run risk checks, dispatch trades and emit the
end-of-day summary.

Pure structural extraction — behaviour unchanged. The mixin reads/writes
the same instance attributes the original methods used (``_strategy``,
``_risk_manager``, ``_alert_throttler``, ``_user_trade_lock``,
``_operation_in_progress``, ``_last_signal_keys``,
``_last_signal_cleanup``, ``trades_today``, ``last_analysis``,
``_consecutive_errors``, etc.) and forwards trade execution through the
component-mixin proxies (``_execute_trade``, ``_send_notification``).
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.models.database import TradeRecord
from src.models.enums import BotStatus
from src.models.session import get_session
from src.utils.json_helpers import parse_json_field
from src.utils.logger import get_logger


logger = get_logger(__name__)


class ScheduleMixin:
    """Schedule-driven analysis + trade tick + per-symbol fan-out."""

    def _cleanup_stale_signal_keys(self) -> None:
        """Remove signal dedup entries older than 24 hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        stale = [k for k, v in self._last_signal_keys.items() if v < cutoff]
        for k in stale:
            del self._last_signal_keys[k]

    async def _analyze_and_trade_safe(self):
        """Wrapper with error handling and auto-recovery for the scheduler."""
        # Skip analysis if bot was paused due to fatal error (e.g. invalid wallet/API key)
        if self.status == BotStatus.ERROR and self.error_message:
            logger.info(
                "[Bot:%s] Skipping analysis — bot paused due to fatal error: %s",
                self.bot_config_id, self.error_message[:100],
            )
            return

        try:
            await self._analyze_and_trade()
            # Reset error tracking on success
            self._consecutive_errors = 0
            self.error_message = None
        except Exception as e:
            self._consecutive_errors += 1
            logger.error(f"[Bot:{self.bot_config_id}] Analysis error ({self._consecutive_errors}/5): {e}")
            self.error_message = str(e)

            if self._consecutive_errors >= 5:
                logger.error(
                    f"[Bot:{self.bot_config_id}] Too many consecutive errors ({self._consecutive_errors}). "
                    f"Pausing for 60s before next attempt."
                )
                # Only notify once at the transition to error status
                if self.status != BotStatus.ERROR:
                    err_msg = f"5 consecutive errors: {str(e)[:300]}"
                    bot_ctx = f"Bot: {self._config.name}"
                    await self._send_notification(
                        lambda n, m=err_msg, c=bot_ctx: n.send_error(
                            error_type="CONSECUTIVE_ERRORS",
                            error_message=m,
                            details=c, context=c,
                        ),
                        event_type="error",
                        summary=f"CONSECUTIVE_ERRORS {self._config.name}",
                    )
                self.status = BotStatus.ERROR
                await asyncio.sleep(60)
                # Verify scheduler is still alive — restart if crashed (only if we own it)
                if self._owns_scheduler and self._scheduler and not self._scheduler.running:
                    logger.warning(f"[Bot:{self.bot_config_id}] Scheduler died — restarting")
                    try:
                        self._scheduler.start()
                    except Exception as sched_err:
                        logger.error(f"[Bot:{self.bot_config_id}] Scheduler restart failed: {sched_err}")
                logger.info(
                    f"[Bot:{self.bot_config_id}] Resuming from error state after cooldown "
                    f"(allowing 2 more attempts before next pause)"
                )
                self.status = BotStatus.RUNNING
                self._consecutive_errors = 3  # Allow 2 more tries before next pause

    def _calculate_asset_budgets(self, total_balance: float, trading_pairs: list[str]) -> dict[str, float]:
        """Calculate per-asset budget based on per_asset_config.

        Assets with a fixed position_usdt get that exact amount.
        Legacy: position_pct is converted to absolute amount.
        Remaining balance is split equally among unconfigured assets.
        If no per_asset_config exists, all assets share equally.
        """
        per_asset_cfg = parse_json_field(
            self._config.per_asset_config,
            field_name="per_asset_config",
            context=f"bot {self.bot_config_id}",
            default={},
        )

        budgets: dict[str, float] = {}
        fixed_total = 0.0
        unfixed_assets = []

        for symbol in trading_pairs:
            asset_cfg = per_asset_cfg.get(symbol, {})
            # Prefer position_usdt (absolute), fall back to position_pct (legacy)
            usdt = asset_cfg.get("position_usdt")
            pct = asset_cfg.get("position_pct")
            if usdt is not None and usdt > 0:
                budgets[symbol] = min(usdt, total_balance)
                fixed_total += budgets[symbol]
            elif pct is not None and pct > 0:
                budgets[symbol] = total_balance * pct / 100
                fixed_total += budgets[symbol]
            else:
                unfixed_assets.append(symbol)

        remaining = max(0.0, total_balance - fixed_total)
        if unfixed_assets:
            per_asset = remaining / len(unfixed_assets)
            for symbol in unfixed_assets:
                budgets[symbol] = per_asset

        log_prefix = f"[Bot:{self.bot_config_id}]"
        for symbol, budget in budgets.items():
            logger.info(f"{log_prefix} Budget {symbol}: ${budget:,.2f}")

        return budgets

    async def _analyze_and_trade(self):
        """Main trading logic — analyze markets and execute trades."""
        log_prefix = f"[Bot:{self.bot_config_id}]"

        # Abort if shutting down — do not start new analysis/trades
        if self._shutting_down:
            logger.info(f"{log_prefix} Shutdown in progress, skipping analysis")
            return

        # Periodic cache cleanup to prevent unbounded memory growth
        now = datetime.now(timezone.utc)
        if (now - self._last_signal_cleanup).total_seconds() > 3600:
            self._cleanup_stale_signal_keys()
            self._last_signal_cleanup = now

        # Reset risk alerts daily (owned by AlertThrottler — #326 Phase 1 PR-4)
        self._alert_throttler.maybe_reset()

        logger.info(f"{log_prefix} Starting analysis...")

        # Self-managed strategies (e.g. copy_trading) handle their own
        # signal generation and trade dispatch — bypass the per-symbol loop.
        if self._strategy is not None and self._strategy.is_self_managed:
            from src.strategy.base import StrategyTickContext
            ctx = StrategyTickContext(
                bot_config=self._config,
                user_id=self._config.user_id,
                exchange_client=self._client,
                trade_executor=self,  # BotWorker is also the TradeExecutorMixin
                send_notification=self._send_notification,
                logger=logger,
                bot_config_id=self.bot_config_id,
            )
            try:
                await self._strategy.run_tick(ctx)
            except Exception as e:
                logger.error("[Bot:%s] Self-managed run_tick error: %s", self.bot_config_id, e)
            self.last_analysis = datetime.now(timezone.utc)
            return  # Skip the per-symbol loop entirely

        # Global halt check (e.g. stats not initialized)
        can_trade, reason = self._risk_manager.can_trade()
        if not can_trade:
            logger.warning(f"{log_prefix} Cannot trade: {reason}")
            await self._alert_throttler.emit_global_if_needed(reason)
            return

        # Parse trading pairs
        try:
            trading_pairs = json.loads(self._config.trading_pairs)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"{log_prefix} Invalid trading_pairs JSON: {e}")
            return

        # Calculate per-asset budgets
        balance = await self._client.get_account_balance()
        budgets = self._calculate_asset_budgets(balance.available, trading_pairs)

        for symbol in trading_pairs:
            # Per-symbol risk check
            can_trade_sym, sym_reason = self._risk_manager.can_trade(symbol)
            if not can_trade_sym:
                logger.info(f"{log_prefix} Skipping {symbol}: {sym_reason}")
                await self._alert_throttler.emit_per_symbol_if_needed(symbol, sym_reason)
                continue

            try:
                await self._analyze_symbol(symbol, asset_budget=budgets.get(symbol))
            except Exception as e:
                logger.error(f"{log_prefix} Error analyzing {symbol}: {e}", exc_info=True)

        self.last_analysis = datetime.now(timezone.utc)

    def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        """Get or create a per-symbol lock to prevent duplicate position opening."""
        # setdefault is atomic — prevents race where two coroutines create
        # separate Lock objects for the same symbol concurrently.
        return self._symbol_locks.setdefault(symbol, asyncio.Lock())

    async def _analyze_symbol(self, symbol: str, force: bool = False, asset_budget: Optional[float] = None):
        """Analyze a single symbol and potentially trade it.

        Args:
            symbol: Trading pair to analyze
            force: If True, skip the open-position check
            asset_budget: Pre-calculated budget for this asset (None = use full balance)
        """
        async with self._get_symbol_lock(symbol):
            await self._analyze_symbol_locked(symbol, force, asset_budget=asset_budget)

    async def _analyze_symbol_locked(self, symbol: str, force: bool = False, asset_budget: Optional[float] = None):
        """Internal: analyze symbol while holding per-symbol lock."""
        log_prefix = f"[Bot:{self.bot_config_id}]"

        # Re-check per-symbol risk inside lock to prevent TOCTOU race
        can_trade_sym, sym_reason = self._risk_manager.can_trade(symbol)
        if not can_trade_sym:
            logger.info(f"{log_prefix} Skipping {symbol} (inside lock): {sym_reason}")
            return

        # Check for existing open positions (per bot) — skip when force-rotating
        if not force:
            async with get_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(TradeRecord).where(
                        TradeRecord.bot_config_id == self.bot_config_id,
                        TradeRecord.symbol == symbol,
                        TradeRecord.status == "open",
                    )
                )
                if result.scalar_one_or_none():
                    logger.info(f"{log_prefix} Already have open position in {symbol}")
                    return

        # Post-trade cooldown — wait before re-entering after a close
        if not force:
            cooldown_hours = self._get_strategy_param("cooldown_hours", 4.0)
            if cooldown_hours > 0:
                async with get_session() as session:
                    from sqlalchemy import select
                    last_closed = await session.execute(
                        select(TradeRecord).where(
                            TradeRecord.bot_config_id == self.bot_config_id,
                            TradeRecord.symbol == symbol,
                            TradeRecord.status == "closed",
                        ).order_by(TradeRecord.exit_time.desc()).limit(1)
                    )
                    last = last_closed.scalar_one_or_none()
                    if last and last.exit_time:
                        elapsed = (datetime.now(timezone.utc) - last.exit_time).total_seconds() / 3600
                        if elapsed < cooldown_hours:
                            logger.info(
                                "%s Cooldown for %s — closed %.1fh ago, need %.1fh",
                                log_prefix, symbol, elapsed, cooldown_hours,
                            )
                            return

        # Generate signal
        signal = await self._strategy.generate_signal(symbol)

        # Observability: count every signal the strategy produced with a
        # concrete direction. Neutral signals are skipped so the counter
        # measures actionable trade intent, not every strategy tick.
        # ``.inc()`` is atomic and cheap — no flag gate needed here.
        if signal is not None and getattr(signal.direction, "value", None) in ("long", "short"):
            try:
                from src.observability.metrics import BOT_SIGNALS_GENERATED_TOTAL
                BOT_SIGNALS_GENERATED_TOTAL.labels(
                    bot_id=str(self.bot_config_id),
                    exchange=self._config.exchange_type,
                    strategy=self._config.strategy_type,
                    side=signal.direction.value,
                ).inc()
            except Exception:  # pragma: no cover — metrics must never break trading
                logger.debug("bot_signals_generated_total inc failed", exc_info=True)

        # Check if we should trade
        should_trade, trade_reason = await self._strategy.should_trade(signal)
        if not should_trade:
            logger.info(f"{log_prefix} Signal rejected: {trade_reason}")
            return

        # Signal deduplication — prevent duplicate trades from rapid re-analysis
        dedup_key = f"{symbol}:{signal.direction.value}:{signal.entry_price:.2f}"
        if dedup_key in self._last_signal_keys:
            elapsed = (datetime.now(timezone.utc) - self._last_signal_keys[dedup_key]).total_seconds()
            if elapsed < 60:  # Ignore duplicate signals within 60s
                logger.info(f"{log_prefix} Duplicate signal for {dedup_key} ({elapsed:.0f}s ago), skipping")
                return
        self._last_signal_keys[dedup_key] = datetime.now(timezone.utc)
        # Prune stale entries (>5min old) to prevent unbounded growth
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
        self._last_signal_keys = {k: v for k, v in self._last_signal_keys.items() if v > cutoff}

        # Abort if shutdown started between analysis and trade execution
        if self._shutting_down:
            logger.info(f"{log_prefix} Shutdown in progress, skipping trade for {symbol}")
            return

        # Execute on appropriate clients under per-user lock.
        # The lock serializes risk-check + order placement across all bots
        # of the same user, preventing concurrent trades from bypassing
        # the daily loss limit.
        self._operation_in_progress.clear()  # Mark: trade in flight
        try:
            async with self._user_trade_lock:
                mode = self._config.mode
                if mode in ("demo", "both") and self._demo_client:
                    await self._execute_trade(signal, self._demo_client, demo_mode=True, asset_budget=asset_budget)
                if mode in ("live", "both") and self._live_client:
                    await self._execute_trade(signal, self._live_client, demo_mode=False, asset_budget=asset_budget)
        finally:
            self._operation_in_progress.set()  # Mark: trade complete

    async def _send_daily_summary(self):
        """Send daily trading summary at end of day and reset risk alerts."""
        log_prefix = f"[Bot:{self.bot_config_id}]"
        try:
            stats = self._risk_manager.get_daily_stats()
            if stats and stats.trades_executed > 0:
                ending_balance = stats.starting_balance + stats.net_pnl

                await self._send_notification(
                    lambda n: n.send_daily_summary(
                        date=stats.date,
                        starting_balance=stats.starting_balance,
                        ending_balance=ending_balance,
                        total_trades=stats.trades_executed,
                        winning_trades=stats.winning_trades,
                        losing_trades=stats.losing_trades,
                        total_pnl=stats.total_pnl,
                        total_fees=stats.total_fees,
                        total_funding=stats.total_funding,
                        max_drawdown=stats.max_drawdown,
                        bot_name=self._config.name,
                    ),
                    event_type="daily_summary",
                    summary=f"Daily {stats.date}: {stats.trades_executed} trades, PnL={stats.total_pnl:+.2f}",
                )
                logger.info(f"{log_prefix} Daily summary sent")
        except Exception as e:
            logger.warning(f"{log_prefix} Failed to send daily summary: {e}")

        # Reset risk alert deduplication for the new day (#326 Phase 1 PR-4)
        self._alert_throttler.reset()

    def _get_strategy_param(self, key: str, default):
        """Read a strategy parameter from the strategy instance."""
        if hasattr(self._strategy, '_p') and isinstance(self._strategy._p, dict):
            return self._strategy._p.get(key, default)
        return default
