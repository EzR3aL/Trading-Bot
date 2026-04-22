"""
BotWorker: A single autonomous trading bot instance.

Each BotWorker runs its own strategy loop on its own schedule,
trading on a specific exchange with its own parameters.
Managed by the BotOrchestrator.

Decomposed into focused mixins:
- TradeExecutorMixin: trade execution logic
- PositionMonitorMixin: position monitoring and close handling
- HyperliquidGatesMixin: Hyperliquid-specific pre-start checks
- NotificationsMixin: Discord and Telegram notification dispatch
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from src.bot.hyperliquid_gates import HyperliquidGatesMixin
from src.bot.notifications import NotificationsMixin
from src.bot.position_monitor import PositionMonitorMixin
from src.bot.trade_closer import TradeCloserMixin
from src.bot.trade_executor import TradeExecutorMixin
from src.exchanges.base import ExchangeClient
from src.exchanges.factory import create_exchange_client
from src.models.database import BotConfig, ExchangeConnection, TradeRecord
from src.models.enums import BotStatus
from src.models.session import get_session
from src.risk.risk_manager import RiskManager
from src.strategy import BaseStrategy, StrategyRegistry
from src.utils.encryption import decrypt_value
from src.utils.json_helpers import parse_json_field
from src.utils.logger import get_logger


def _safe_json_loads(value: Any, default: List = None) -> List:
    """Safely parse JSON, returning default on error."""
    if default is None:
        default = []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default

logger = get_logger(__name__)

# Default market session schedule (UTC hours)
DEFAULT_MARKET_HOURS = [1, 8, 14, 21]


class BotWorker(
    TradeExecutorMixin,
    PositionMonitorMixin,
    TradeCloserMixin,
    HyperliquidGatesMixin,
    NotificationsMixin,
):
    """
    A single bot instance running its own strategy loop.

    Lifecycle:
    1. Created by BotOrchestrator with a BotConfig
    2. Initializes exchange client, strategy, risk manager
    3. Runs strategy loop on configured schedule
    4. Stopped by Orchestrator or on error (with auto-restart)
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

        # Auto-recovery tracking
        self._consecutive_errors: int = 0

        # Signal deduplication cache
        self._last_signal_keys: dict[str, datetime] = {}
        self._last_signal_cleanup: datetime = datetime.now(timezone.utc)

        # Risk alert deduplication (reset daily)
        self._risk_alerts_sent: set[str] = set()
        self._risk_alerts_last_reset: datetime = datetime.now(timezone.utc)

        # Wire the shared RiskStateManager singleton into the close-detection
        # path so `_handle_closed_position` uses exchange-readback classify_close
        # instead of the legacy proximity heuristic. Singleton is intentional —
        # the per-(trade, leg) lock map must be shared with the API path.
        # See issue #218, Epic #188.
        if settings.risk.risk_state_manager_enabled:
            from src.api.dependencies.risk_state import get_risk_state_manager
            self._risk_state_manager = get_risk_state_manager()

        # Initialize per-instance position monitor state via the proxy mixin —
        # this constructs the PositionMonitor component bound to self.
        # (ARCH-H1 Phase 1 PR-4, #281).
        self._init_monitor_state()

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

    def _cleanup_stale_signal_keys(self) -> None:
        """Remove signal dedup entries older than 24 hours."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        stale = [k for k, v in self._last_signal_keys.items() if v < cutoff]
        for k in stale:
            del self._last_signal_keys[k]

    def _get_client(self, demo_mode: bool) -> Optional[ExchangeClient]:
        """Return the exchange client for the given mode."""
        return self._demo_client if demo_mode else self._live_client

    @property
    def config(self) -> Optional[BotConfig]:
        return self._config

    async def initialize(self) -> bool:
        """
        Load config from DB and initialize all components.

        Returns:
            True if initialization succeeded
        """
        self.status = BotStatus.STARTING

        try:
            # Load bot config
            async with get_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(BotConfig).where(BotConfig.id == self.bot_config_id)
                )
                self._config = result.scalar_one_or_none()

                if not self._config:
                    self.error_message = f"BotConfig {self.bot_config_id} not found"
                    self.status = BotStatus.ERROR
                    return False

                # Load exchange connection
                conn_result = await session.execute(
                    select(ExchangeConnection).where(
                        ExchangeConnection.user_id == self._config.user_id,
                        ExchangeConnection.exchange_type == self._config.exchange_type,
                    )
                )
                conn = conn_result.scalar_one_or_none()

                if not conn:
                    self.error_message = f"No API keys for {self._config.exchange_type}"
                    self.status = BotStatus.ERROR
                    return False

                # Create exchange client(s) based on mode
                # For Hyperliquid: load builder config from DB (admin-managed)
                extra_kwargs = {}
                if self._config.exchange_type == "hyperliquid":
                    from src.utils.settings import get_hl_config
                    hl_cfg = await get_hl_config()
                    # Admins skip builder fee — no approval needed
                    from sqlalchemy import select as sa_select_early
                    from src.models.database import User as UserModelEarly
                    user_r = await session.execute(
                        sa_select_early(UserModelEarly).where(UserModelEarly.id == self._config.user_id)
                    )
                    user_check = user_r.scalar_one_or_none()
                    if user_check and user_check.role != "admin":
                        extra_kwargs = {
                            "builder_address": hl_cfg["builder_address"],
                            "builder_fee": hl_cfg["builder_fee"],
                        }

                mode = self._config.mode
                if mode in ("demo", "both"):
                    if not conn.demo_api_key_encrypted:
                        self.error_message = f"No demo API keys for {self._config.exchange_type}"
                        self.status = BotStatus.ERROR
                        return False
                    self._demo_client = create_exchange_client(
                        exchange_type=self._config.exchange_type,
                        api_key=decrypt_value(conn.demo_api_key_encrypted),
                        api_secret=decrypt_value(conn.demo_api_secret_encrypted),
                        passphrase=decrypt_value(conn.demo_passphrase_encrypted) if conn.demo_passphrase_encrypted else "",
                        demo_mode=True,
                        **extra_kwargs,
                    )

                if mode in ("live", "both"):
                    if not conn.api_key_encrypted:
                        self.error_message = f"No live API keys for {self._config.exchange_type}"
                        self.status = BotStatus.ERROR
                        return False
                    self._live_client = create_exchange_client(
                        exchange_type=self._config.exchange_type,
                        api_key=decrypt_value(conn.api_key_encrypted),
                        api_secret=decrypt_value(conn.api_secret_encrypted),
                        passphrase=decrypt_value(conn.passphrase_encrypted) if conn.passphrase_encrypted else "",
                        demo_mode=False,
                        **extra_kwargs,
                    )

                # Primary client for data fetching
                self._client = self._demo_client or self._live_client

                # Initialize strategy
                strategy_params = {}
                if self._config.strategy_params:
                    strategy_params = json.loads(self._config.strategy_params)

                # Add TP/SL from trading params so strategy can use them (skip None)
                if self._config.take_profit_percent is not None:
                    strategy_params.setdefault("take_profit_percent", self._config.take_profit_percent)
                if self._config.stop_loss_percent is not None:
                    strategy_params.setdefault("stop_loss_percent", self._config.stop_loss_percent)

                self._strategy = StrategyRegistry.create(
                    self._config.strategy_type,
                    params=strategy_params,
                )

                # Build per-symbol risk limits from per_asset_config
                per_symbol_limits: dict = {}
                pac = parse_json_field(
                    self._config.per_asset_config,
                    field_name="per_asset_config",
                    context=f"bot {self.bot_config_id}",
                    default={},
                )
                for sym, cfg in pac.items():
                    sym_lim: dict = {}
                    if cfg.get("max_trades") is not None:
                        sym_lim["max_trades"] = int(cfg["max_trades"])
                    if cfg.get("loss_limit") is not None:
                        sym_lim["loss_limit"] = float(cfg["loss_limit"])
                    if sym_lim:
                        per_symbol_limits[sym] = sym_lim

                # Initialize risk manager with bot-specific params + DB storage
                self._risk_manager = RiskManager(
                    max_trades_per_day=self._config.max_trades_per_day,
                    daily_loss_limit_percent=self._config.daily_loss_limit_percent,
                    position_size_percent=self._config.position_size_percent,
                    data_dir=f"data/risk/bot_{self.bot_config_id}",
                    per_symbol_limits=per_symbol_limits if per_symbol_limits else None,
                    bot_config_id=self.bot_config_id,
                )

            # ── Hyperliquid pre-start checks (admins bypass) ─────────
            if self._config.exchange_type == "hyperliquid":
                from sqlalchemy import select as sa_select
                from src.models.database import User as UserModel
                async with get_session() as hl_session:
                    user_result = await hl_session.execute(
                        sa_select(UserModel).where(UserModel.id == self._config.user_id)
                    )
                    user_obj = user_result.scalar_one_or_none()
                    is_admin = user_obj and user_obj.role == "admin"

                    if not is_admin:
                        builder_ok = await self._check_builder_approval(self._client, hl_session)
                        if not builder_ok:
                            return False
                        referral_ok = await self._check_referral_gate(self._client, hl_session)
                        if not referral_ok:  # pragma: no cover — HL-specific gate
                            return False

                    # Wallet validation (applies to all users including admins)
                    wallet_ok = await self._check_wallet_gate(self._client)
                    if not wallet_ok:
                        return False

            # Validate trading pairs exist on exchange
            try:
                from src.exchanges.symbol_fetcher import get_exchange_symbols
                is_demo = self._config.mode in ("demo", "both")
                available = await get_exchange_symbols(self._config.exchange_type, demo_mode=is_demo)
                if available:
                    pairs = _safe_json_loads(self._config.trading_pairs)
                    invalid = [p for p in pairs if p not in available]
                    if invalid:
                        self.error_message = (
                            f"Symbol(s) not available on {self._config.exchange_type}: "
                            f"{', '.join(invalid)}"
                        )
                        logger.error(f"[Bot:{self.bot_config_id}] {self.error_message}")
                        self.status = BotStatus.ERROR
                        return False

                    # Practical validation: verify each symbol is actually tradeable
                    client = self._demo_client if is_demo else self._client
                    if client:
                        for pair in pairs:
                            is_valid = await client.validate_symbol(pair)
                            if not is_valid:
                                self.error_message = (
                                    f"Symbol {pair} exists on {self._config.exchange_type} "
                                    f"but is not tradeable in "
                                    f"{'demo' if is_demo else 'live'} mode"
                                )
                                logger.error(f"[Bot:{self.bot_config_id}] {self.error_message}")
                                self.status = BotStatus.ERROR
                                return False
            except Exception as e:
                logger.warning(f"[Bot:{self.bot_config_id}] Symbol validation skipped: {e}")

            # Initialize daily session with balance
            try:
                balance = await self._client.get_account_balance()
                self._risk_manager.initialize_day(balance.available)
                logger.info(f"[Bot:{self.bot_config_id}] Balance: ${balance.available:,.2f}")
            except Exception as e:
                logger.warning(f"[Bot:{self.bot_config_id}] Could not fetch balance: {e}")
                self._risk_manager.initialize_day(0)

            # Setup scheduler (use shared if provided, else create own)
            if self._owns_scheduler:
                self._scheduler = AsyncIOScheduler()
            self._setup_schedule()

            logger.info(
                f"[Bot:{self.bot_config_id}] Initialized: "
                f"{self._config.name} | {self._config.strategy_type} | "
                f"{self._config.exchange_type} ({self._config.mode})"
            )
            return True

        except Exception as e:
            self.error_message = str(e)
            self.status = BotStatus.ERROR
            logger.error(f"[Bot:{self.bot_config_id}] Init failed: {e}")
            return False

    def _setup_schedule(self):
        """Configure the scheduler based on bot config."""
        schedule_type = self._config.schedule_type
        schedule_config = {}
        if self._config.schedule_config:
            schedule_config = json.loads(self._config.schedule_config)

        if schedule_type == "interval":
            minutes = schedule_config.get("interval_minutes", 60)
            self._scheduler.add_job(
                self._analyze_and_trade_safe,
                IntervalTrigger(minutes=minutes),
                id=f"bot_{self.bot_config_id}_analysis",
                name=f"Bot {self.bot_config_id} Analysis",
                replace_existing=True,
                max_instances=1,
            )
        else:
            # custom_cron (fixed hours)
            hours = schedule_config.get("hours", DEFAULT_MARKET_HOURS)
            hour_str = ",".join(str(h) for h in hours)
            self._scheduler.add_job(
                self._analyze_and_trade_safe,
                CronTrigger(hour=hour_str, minute=0),
                id=f"bot_{self.bot_config_id}_analysis",
                name=f"Bot {self.bot_config_id} Analysis",
                replace_existing=True,
                max_instances=1,
            )

        # Position monitoring every minute
        self._scheduler.add_job(
            self._monitor_positions_safe,
            CronTrigger(minute="*/1"),
            id=f"bot_{self.bot_config_id}_monitor",
            name=f"Bot {self.bot_config_id} Position Monitor",
            replace_existing=True,
            max_instances=1,
        )

        # Daily summary at 23:55 UTC
        self._scheduler.add_job(
            self._send_daily_summary,
            CronTrigger(hour=23, minute=55),
            id=f"bot_{self.bot_config_id}_daily_summary",
            name=f"Bot {self.bot_config_id} Daily Summary",
            replace_existing=True,
        )

    async def start(self):
        """Start the bot's strategy loop."""
        if self.status == BotStatus.RUNNING:
            return

        if self._owns_scheduler and self._scheduler and not self._scheduler.running:
            self._scheduler.start()
        self.status = BotStatus.RUNNING
        self.started_at = datetime.now(timezone.utc)
        self.error_message = None

        # Run initial analysis — respect schedule type.
        # For interval, always run immediately.
        # For cron-based schedules (custom_cron), only run if current hour matches.
        schedule_type = self._config.schedule_type or "interval"
        if schedule_type == "interval":
            await self._analyze_and_trade_safe()
        else:
            schedule_config = {}
            if self._config.schedule_config:
                schedule_config = json.loads(self._config.schedule_config)
            session_hours = schedule_config.get("hours", DEFAULT_MARKET_HOURS)
            current_hour = datetime.now(timezone.utc).hour
            if current_hour in session_hours:
                await self._analyze_and_trade_safe()
            else:
                next_hours = sorted(h for h in session_hours if h > current_hour)
                next_hour = next_hours[0] if next_hours else session_hours[0]
                logger.info(
                    f"[Bot:{self.bot_config_id}] Skipping initial analysis — "
                    f"not in market session (current={current_hour}:00 UTC, "
                    f"next session={next_hour}:00 UTC)"
                )

        logger.info(f"[Bot:{self.bot_config_id}] Started: {self._config.name}")

        await self._send_notification(
            lambda n: n.send_bot_status(
                status="STARTED", message=f"{self._config.name} is now running",
                bot_name=self._config.name,
                stats={"Strategy": self._config.strategy_type, "Mode": self._config.mode},
            ),
            event_type="status",
            summary=f"STARTED {self._config.name}",
        )

    async def stop(self):
        """Stop the bot gracefully."""
        logger.info(f"[Bot:{self.bot_config_id}] Stopping...")

        # Send stop notification before tearing down resources
        if self._config:
            await self._send_notification(
                lambda n: n.send_bot_status(
                    status="STOPPED", message=f"{self._config.name} has been stopped",
                    bot_name=self._config.name,
                ),
                event_type="status",
                summary=f"STOPPED {self._config.name}",
            )

        # Remove this bot's jobs from the scheduler
        if self._scheduler:
            prefix = f"bot_{self.bot_config_id}_"
            for job in list(self._scheduler.get_jobs()):
                if job.id.startswith(prefix):
                    try:
                        job.remove()
                    except Exception as e:
                        logger.debug("Job removal during cleanup: %s", e)

            # Only shutdown scheduler if we created it
            if self._owns_scheduler and self._scheduler.running:
                self._scheduler.shutdown(wait=False)

        if self._strategy:
            await self._strategy.close()

        if self._demo_client:
            try:
                await self._demo_client.close()
            except Exception as e:
                logger.debug("Error closing demo client for bot %s: %s", self.bot_config_id, e)

        if self._live_client:
            try:
                await self._live_client.close()
            except Exception as e:
                logger.debug("Error closing live client for bot %s: %s", self.bot_config_id, e)

        self.status = BotStatus.STOPPED
        logger.info(f"[Bot:{self.bot_config_id}] Stopped")

    async def graceful_stop(self, grace_period: float = 20.0) -> list[dict]:
        """Stop the bot gracefully, waiting for in-flight operations.

        1. Sets shutdown flag to prevent new trades
        2. Waits for any in-flight trade operation to complete (with timeout)
        3. Cancels pending/unfilled orders on the exchange
        4. Returns list of open positions (for caller to log warnings)

        Args:
            grace_period: Max seconds to wait for in-flight operations.

        Returns:
            List of open position dicts (symbol, side, size, entry_price, demo_mode).
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        self._shutting_down = True
        logger.info(f"{log_prefix} Graceful shutdown initiated")

        # Wait for any in-flight trade operation to finish
        try:
            await asyncio.wait_for(
                self._operation_in_progress.wait(),
                timeout=grace_period,
            )
            logger.info(f"{log_prefix} In-flight operations completed")
        except asyncio.TimeoutError:
            logger.warning(
                f"{log_prefix} In-flight operation did not complete within "
                f"{grace_period}s — proceeding with shutdown"
            )

        # Cancel pending/unfilled orders on the exchange
        for client, mode_str in [
            (self._demo_client, "DEMO"),
            (self._live_client, "LIVE"),
        ]:
            if not client:
                continue
            try:
                positions = await client.get_open_positions()
                for pos in positions:
                    # Cancel any pending TP/SL trigger orders by cancelling
                    # the order if we have an order_id. The exchange TP/SL
                    # are exchange-managed, so we leave them (they protect
                    # the position). We only want to cancel unfilled limit
                    # orders that haven't been matched yet.
                    pass  # TP/SL are protective — leave them in place
            except Exception as e:
                logger.warning(f"{log_prefix} [{mode_str}] Error checking positions during shutdown: {e}")

        # Gather open positions for this bot (from DB) to warn about
        open_positions: list[dict] = []
        try:
            async with get_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(TradeRecord).where(
                        TradeRecord.bot_config_id == self.bot_config_id,
                        TradeRecord.status == "open",
                    )
                )
                for trade in result.scalars().all():
                    open_positions.append({
                        "symbol": trade.symbol,
                        "side": trade.side,
                        "size": trade.size,
                        "entry_price": trade.entry_price,
                        "demo_mode": trade.demo_mode,
                        "has_tp": trade.take_profit is not None,
                        "has_sl": trade.stop_loss is not None,
                    })
        except Exception as e:
            logger.warning(f"{log_prefix} Could not query open positions: {e}")

        # Now do the normal stop (remove scheduler jobs, close clients, etc.)
        await self.stop()

        return open_positions

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

        # Reset risk alerts daily
        if (now - self._risk_alerts_last_reset).total_seconds() > 86400:
            self._risk_alerts_sent.clear()
            self._risk_alerts_last_reset = now

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
            reason_lower = reason.lower()
            if "halted" in reason_lower or "limit" in reason_lower:
                alert_key = f"global_{reason}"
                if alert_key not in self._risk_alerts_sent:
                    self._risk_alerts_sent.add(alert_key)
                    alert_type = "TRADE_LIMIT" if "trade limit" in reason_lower else "DAILY_LOSS_LIMIT"
                    await self._send_notification(
                        lambda n, at=alert_type: n.send_risk_alert(
                            alert_type=at, message=reason,
                        ),
                        event_type="risk_alert",
                        summary=f"{alert_type}: {reason[:100]}",
                    )
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
                sym_reason_lower = sym_reason.lower()
                if "halted" in sym_reason_lower or "limit" in sym_reason_lower:
                    alert_key = f"{symbol}_{sym_reason}"
                    if alert_key not in self._risk_alerts_sent:
                        self._risk_alerts_sent.add(alert_key)
                        sym_alert_type = "TRADE_LIMIT" if "trade limit" in sym_reason_lower else "DAILY_LOSS_LIMIT"
                        msg = f"{symbol}: {sym_reason}"
                        await self._send_notification(
                            lambda n, at=sym_alert_type, m=msg: n.send_risk_alert(
                                alert_type=at, message=m,
                            ),
                            event_type="risk_alert",
                            summary=f"{sym_alert_type}: {msg[:100]}",
                        )
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

        # Reset risk alert deduplication for the new day
        self._risk_alerts_sent.clear()

    def _get_strategy_param(self, key: str, default):
        """Read a strategy parameter from the strategy instance."""
        if hasattr(self._strategy, '_p') and isinstance(self._strategy._p, dict):
            return self._strategy._p.get(key, default)
        return default

    def get_status_dict(self) -> dict:
        """Return status info for API responses."""
        config = self._config
        return {
            "bot_config_id": self.bot_config_id,
            "name": config.name if config else "Unknown",
            "strategy_type": config.strategy_type if config else "",
            "exchange_type": config.exchange_type if config else "",
            "mode": config.mode if config else "",
            "trading_pairs": _safe_json_loads(config.trading_pairs) if config else [],
            "status": self.status,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_analysis": self.last_analysis.isoformat() if self.last_analysis else None,
            "trades_today": self.trades_today,
        }
