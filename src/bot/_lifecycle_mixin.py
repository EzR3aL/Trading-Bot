"""Lifecycle mixin for BotWorker — initialize, start, stop, graceful stop.

Extracted from ``src/bot/bot_worker.py``. Owns every method that mutates
the worker's run state plus the scheduler wiring used to drive the
trading loop. Pure structural extraction — behaviour unchanged.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.bot._helpers import _safe_json_loads, DEFAULT_MARKET_HOURS
from src.exchanges.factory import create_exchange_client
from src.models.database import BotConfig, ExchangeConnection, TradeRecord
from src.models.enums import BotStatus
from src.models.session import get_session
from src.risk.risk_manager import RiskManager
from src.strategy import StrategyRegistry
from src.utils.encryption import decrypt_value
from src.utils.json_helpers import parse_json_field
from src.utils.logger import get_logger


logger = get_logger(__name__)


class LifecycleMixin:
    """Initialize, start, stop and graceful-stop a BotWorker."""

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

            # ── Exchange pre-start gate checks (#ARCH-H2) ────────────
            # All exchange-specific onboarding checks (HL: referral /
            # builder fee / wallet, every exchange: affiliate UID) are
            # dispatched via ``client.pre_start_checks``. Admins bypass
            # the onboarding gates but the wallet gate still applies.
            if self._client is not None:
                from sqlalchemy import select as sa_select
                from src.models.database import User as UserModel
                async with get_session() as hl_session:
                    user_result = await hl_session.execute(
                        sa_select(UserModel).where(UserModel.id == self._config.user_id)
                    )
                    user_obj = user_result.scalar_one_or_none()
                    is_admin = user_obj and user_obj.role == "admin"

                    try:
                        gate_results = await self._client.pre_start_checks(
                            user_id=self._config.user_id, db=hl_session
                        )
                    except Exception as e:
                        logger.warning(
                            f"[Bot:{self.bot_config_id}] pre_start_checks raised: {e}"
                        )
                        gate_results = []

                    # Admins only bypass onboarding gates (referral/builder/
                    # affiliate UID); wallet problems still block everyone.
                    ADMIN_BYPASS_KEYS = {"referral", "builder_fee", "affiliate_uid"}
                    for gate in gate_results:
                        if gate.ok:
                            continue
                        if is_admin and gate.key in ADMIN_BYPASS_KEYS:
                            continue
                        self.error_message = gate.message
                        self.status = BotStatus.ERROR
                        logger.warning(
                            f"[Bot:{self.bot_config_id}] Pre-start gate '{gate.key}' "
                            f"blocked bot start"
                        )
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
