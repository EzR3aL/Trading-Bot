"""
BotWorker: A single autonomous trading bot instance.

Each BotWorker runs its own strategy loop on its own schedule,
trading on a specific exchange with its own parameters.
Managed by the BotOrchestrator.

Decomposed into focused mixins:
- TradeExecutorMixin: trade execution logic
- PositionMonitorMixin: position monitoring and close handling
- RotationManagerMixin: trade rotation (auto-close and reopen)
- HyperliquidGatesMixin: Hyperliquid-specific pre-start checks
- NotificationsMixin: Discord and Telegram notification dispatch
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.bot.hyperliquid_gates import HyperliquidGatesMixin
from src.bot.notifications import NotificationsMixin
from src.bot.pnl import calculate_pnl  # noqa: F401 — re-export for backward compat
from src.bot.position_monitor import PositionMonitorMixin
from src.bot.rotation_manager import RotationManagerMixin
from src.bot.trade_executor import TradeExecutorMixin

from src.exchanges.base import ExchangeClient
from src.exchanges.factory import create_exchange_client
from src.models.database import BotConfig, ExchangeConnection, LLMConnection, TradeRecord
from src.models.session import get_session
from src.risk.risk_manager import RiskManager
from src.strategy import BaseStrategy, StrategyRegistry, TradeSignal
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default market session schedule (UTC hours)
DEFAULT_MARKET_HOURS = [1, 8, 14, 21]


class BotWorker(
    TradeExecutorMixin,
    PositionMonitorMixin,
    RotationManagerMixin,
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

    def __init__(self, bot_config_id: int):
        self.bot_config_id = bot_config_id
        self._config: Optional[BotConfig] = None
        self._client: Optional[ExchangeClient] = None
        self._strategy: Optional[BaseStrategy] = None
        self._risk_manager: Optional[RiskManager] = None
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._task: Optional[asyncio.Task] = None

        self.status = "idle"  # idle | starting | running | error | stopped
        self.error_message: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.last_analysis: Optional[datetime] = None
        self.trades_today: int = 0

        # Per-symbol lock to prevent duplicate position opening
        self._symbol_locks: dict[str, asyncio.Lock] = {}

        # Per-mode clients for "both" mode
        self._demo_client: Optional[ExchangeClient] = None
        self._live_client: Optional[ExchangeClient] = None

        # Auto-recovery tracking
        self._consecutive_errors: int = 0

        # Signal deduplication cache
        self._last_signal_keys: dict[str, datetime] = {}

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
        self.status = "starting"

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
                    self.status = "error"
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
                    self.status = "error"
                    return False

                # Create exchange client(s) based on mode
                # For Hyperliquid: load builder config from DB (admin-managed)
                extra_kwargs = {}
                if self._config.exchange_type == "hyperliquid":
                    from src.utils.settings import get_hl_config
                    hl_cfg = await get_hl_config()
                    extra_kwargs = {
                        "builder_address": hl_cfg["builder_address"],
                        "builder_fee": hl_cfg["builder_fee"],
                    }

                mode = self._config.mode
                if mode in ("demo", "both"):
                    if not conn.demo_api_key_encrypted:
                        self.error_message = f"No demo API keys for {self._config.exchange_type}"
                        self.status = "error"
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
                        self.status = "error"
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

                # Add TP/SL from trading params so strategy can use them
                strategy_params.setdefault("take_profit_percent", self._config.take_profit_percent)
                strategy_params.setdefault("stop_loss_percent", self._config.stop_loss_percent)

                # If LLM strategy, inject decrypted API key from user's LLMConnection
                if self._config.strategy_type in ("llm_signal", "degen"):
                    llm_provider = strategy_params.get("llm_provider", "groq")
                    llm_conn_result = await session.execute(
                        select(LLMConnection).where(
                            LLMConnection.user_id == self._config.user_id,
                            LLMConnection.provider_type == llm_provider,
                        )
                    )
                    llm_conn = llm_conn_result.scalar_one_or_none()
                    if not llm_conn:
                        self.error_message = f"No API key configured for LLM provider: {llm_provider}. Go to Settings → LLM Keys."
                        self.status = "error"
                        return False
                    strategy_params["llm_api_key"] = decrypt_value(llm_conn.api_key_encrypted)

                self._strategy = StrategyRegistry.create(
                    self._config.strategy_type,
                    params=strategy_params,
                )

                # Build per-symbol risk limits from per_asset_config
                per_symbol_limits: dict = {}
                if self._config.per_asset_config:
                    try:
                        pac = json.loads(self._config.per_asset_config) if isinstance(
                            self._config.per_asset_config, str
                        ) else self._config.per_asset_config
                        for sym, cfg in pac.items():
                            sym_lim: dict = {}
                            if cfg.get("max_trades") is not None:
                                sym_lim["max_trades"] = int(cfg["max_trades"])
                            if cfg.get("loss_limit") is not None:
                                sym_lim["loss_limit"] = float(cfg["loss_limit"])
                            if sym_lim:
                                per_symbol_limits[sym] = sym_lim
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning("Failed to parse per_symbol_limits for bot %s: %s", self.bot_config_id, e)

                # Initialize risk manager with bot-specific params
                self._risk_manager = RiskManager(
                    max_trades_per_day=self._config.max_trades_per_day,
                    daily_loss_limit_percent=self._config.daily_loss_limit_percent,
                    position_size_percent=self._config.position_size_percent,
                    data_dir=f"data/risk/bot_{self.bot_config_id}",
                    per_symbol_limits=per_symbol_limits if per_symbol_limits else None,
                )

            # ── Hyperliquid pre-start checks ──────────────────────────
            if self._config.exchange_type == "hyperliquid":
                async with get_session() as hl_session:
                    builder_ok = await self._check_builder_approval(self._client, hl_session)
                    if not builder_ok:
                        return False
                    referral_ok = await self._check_referral_gate(self._client, hl_session)
                    if not referral_ok:  # pragma: no cover — HL-specific gate
                        return False

            # Initialize daily session with balance
            try:
                balance = await self._client.get_account_balance()
                self._risk_manager.initialize_day(balance.available)
                logger.info(f"[Bot:{self.bot_config_id}] Balance: ${balance.available:,.2f}")
            except Exception as e:
                logger.warning(f"[Bot:{self.bot_config_id}] Could not fetch balance: {e}")
                self._risk_manager.initialize_day(0)

            # Setup scheduler
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
            self.status = "error"
            logger.error(f"[Bot:{self.bot_config_id}] Init failed: {e}")
            return False

    def _setup_schedule(self):
        """Configure the scheduler based on bot config."""
        schedule_type = self._config.schedule_type
        schedule_config = {}
        if self._config.schedule_config:
            schedule_config = json.loads(self._config.schedule_config)

        if schedule_type == "rotation_only":
            # Rotation-only mode: no regular analysis schedule.
            # The bot opens its first trade on start, then the rotation
            # checker handles closing + re-opening on the configured interval.
            logger.info(f"[Bot:{self.bot_config_id}] Rotation-only mode — no regular schedule")
        elif schedule_type == "interval":
            minutes = schedule_config.get("interval_minutes", 60)
            self._scheduler.add_job(
                self._analyze_and_trade_safe,
                IntervalTrigger(minutes=minutes),
                id=f"bot_{self.bot_config_id}_analysis",
                name=f"Bot {self.bot_config_id} Analysis",
                replace_existing=True,
                max_instances=1,
            )
        elif schedule_type == "custom_cron":
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
        else:
            # Default: market_sessions
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

        # Position monitoring every 5 minutes
        self._scheduler.add_job(
            self._monitor_positions_safe,
            CronTrigger(minute="*/5"),
            id=f"bot_{self.bot_config_id}_monitor",
            name=f"Bot {self.bot_config_id} Position Monitor",
            replace_existing=True,
            max_instances=1,
        )

        # Trade rotation (auto-close & reopen) — check every minute if enabled
        # Automatically enabled for rotation_only schedule type
        rotation_on = getattr(self._config, "rotation_enabled", False) or schedule_type == "rotation_only"
        rotation_mins = getattr(self._config, "rotation_interval_minutes", None)
        if rotation_on and rotation_mins:
            self._scheduler.add_job(
                self._check_rotation_safe,
                IntervalTrigger(minutes=1),
                id=f"bot_{self.bot_config_id}_rotation",
                name=f"Bot {self.bot_config_id} Trade Rotation",
                replace_existing=True,
                max_instances=1,
            )
            start_time = getattr(self._config, "rotation_start_time", None) or "now"
            logger.info(
                f"[Bot:{self.bot_config_id}] Trade rotation enabled: "
                f"every {rotation_mins}min (anchor: {start_time} UTC)"
            )

    async def start(self):
        """Start the bot's strategy loop."""
        if self.status == "running":
            return

        self._scheduler.start()
        self.status = "running"
        self.started_at = datetime.utcnow()
        self.error_message = None

        # Run initial analysis
        await self._analyze_and_trade_safe()

        logger.info(f"[Bot:{self.bot_config_id}] Started: {self._config.name}")

    async def stop(self):
        """Stop the bot gracefully."""
        logger.info(f"[Bot:{self.bot_config_id}] Stopping...")

        if self._scheduler and self._scheduler.running:
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

        self.status = "stopped"
        logger.info(f"[Bot:{self.bot_config_id}] Stopped")

    async def _analyze_and_trade_safe(self):
        """Wrapper with error handling and auto-recovery for the scheduler."""
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
                self.status = "error"
                await asyncio.sleep(60)
                # Verify scheduler is still alive — restart if crashed
                if self._scheduler and not self._scheduler.running:
                    logger.warning(f"[Bot:{self.bot_config_id}] Scheduler died — restarting")
                    try:
                        self._scheduler.start()
                    except Exception as sched_err:
                        logger.error(f"[Bot:{self.bot_config_id}] Scheduler restart failed: {sched_err}")
                self.status = "running"
                self._consecutive_errors = 3  # Allow 2 more tries before next pause

    def _calculate_asset_budgets(self, total_balance: float, trading_pairs: list[str]) -> dict[str, float]:
        """Calculate per-asset budget based on per_asset_config.

        Assets with a fixed position_pct get that share of the total balance.
        Remaining balance is split equally among unconfigured assets.
        If no per_asset_config exists, all assets share equally.
        """
        per_asset_cfg = {}
        if self._config.per_asset_config:
            try:
                per_asset_cfg = json.loads(self._config.per_asset_config) if isinstance(
                    self._config.per_asset_config, str
                ) else self._config.per_asset_config
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Failed to parse per_asset_config for bot %s: %s", self.bot_config_id, e)
                per_asset_cfg = {}

        budgets: dict[str, float] = {}
        fixed_total = 0.0
        unfixed_assets = []

        for symbol in trading_pairs:
            asset_cfg = per_asset_cfg.get(symbol, {})
            pct = asset_cfg.get("position_pct")
            if pct is not None and pct > 0:
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
        logger.info(f"{log_prefix} Starting analysis...")

        # Global halt check (e.g. stats not initialized)
        can_trade, reason = self._risk_manager.can_trade()
        if not can_trade:
            logger.warning(f"{log_prefix} Cannot trade: {reason}")
            return

        # Parse trading pairs
        trading_pairs = json.loads(self._config.trading_pairs)

        # Calculate per-asset budgets
        balance = await self._client.get_account_balance()
        budgets = self._calculate_asset_budgets(balance.available, trading_pairs)

        for symbol in trading_pairs:
            # Per-symbol risk check
            can_trade_sym, sym_reason = self._risk_manager.can_trade(symbol)
            if not can_trade_sym:
                logger.info(f"{log_prefix} Skipping {symbol}: {sym_reason}")
                continue

            try:
                await self._analyze_symbol(symbol, asset_budget=budgets.get(symbol))
            except Exception as e:
                logger.error(f"{log_prefix} Error analyzing {symbol}: {e}")

        self.last_analysis = datetime.utcnow()

    def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        """Get or create a per-symbol lock to prevent duplicate position opening."""
        if symbol not in self._symbol_locks:
            self._symbol_locks[symbol] = asyncio.Lock()
        return self._symbol_locks[symbol]

    async def _analyze_symbol(self, symbol: str, force: bool = False, asset_budget: Optional[float] = None):
        """Analyze a single symbol and potentially trade it.

        Args:
            symbol: Trading pair to analyze
            force: If True, skip the open-position check (used after rotation close)
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
            elapsed = (datetime.utcnow() - self._last_signal_keys[dedup_key]).total_seconds()
            if elapsed < 60:  # Ignore duplicate signals within 60s
                logger.info(f"{log_prefix} Duplicate signal for {dedup_key} ({elapsed:.0f}s ago), skipping")
                return
        self._last_signal_keys[dedup_key] = datetime.utcnow()
        # Prune stale entries (>5min old) to prevent unbounded growth
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        self._last_signal_keys = {k: v for k, v in self._last_signal_keys.items() if v > cutoff}

        # Execute on appropriate clients
        mode = self._config.mode
        if mode in ("demo", "both") and self._demo_client:
            await self._execute_trade(signal, self._demo_client, demo_mode=True, asset_budget=asset_budget)
        if mode in ("live", "both") and self._live_client:
            await self._execute_trade(signal, self._live_client, demo_mode=False, asset_budget=asset_budget)

    def get_status_dict(self) -> dict:
        """Return status info for API responses."""
        config = self._config
        return {
            "bot_config_id": self.bot_config_id,
            "name": config.name if config else "Unknown",
            "strategy_type": config.strategy_type if config else "",
            "exchange_type": config.exchange_type if config else "",
            "mode": config.mode if config else "",
            "trading_pairs": json.loads(config.trading_pairs) if config else [],
            "status": self.status,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_analysis": self.last_analysis.isoformat() if self.last_analysis else None,
            "trades_today": self.trades_today,
        }
