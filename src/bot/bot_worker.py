"""
BotWorker: A single autonomous trading bot instance.

Each BotWorker runs its own strategy loop on its own schedule,
trading on a specific exchange with its own parameters.
Managed by the BotOrchestrator.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.exchanges.base import ExchangeClient
from src.exchanges.factory import create_exchange_client
from src.models.database import BotConfig, ExchangeConnection, LLMConnection, TradeRecord
from src.models.session import get_session
from src.notifications.discord_notifier import DiscordNotifier
from src.risk.risk_manager import RiskManager
from src.strategy.base import BaseStrategy, StrategyRegistry, TradeSignal
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Default market session schedule (UTC hours)
DEFAULT_MARKET_HOURS = [1, 8, 14, 21]


class BotWorker:
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
                if self._config.strategy_type == "llm_signal":
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

                # Initialize risk manager with bot-specific params
                self._risk_manager = RiskManager(
                    max_trades_per_day=self._config.max_trades_per_day,
                    daily_loss_limit_percent=self._config.daily_loss_limit_percent,
                    position_size_percent=self._config.position_size_percent,
                    data_dir=f"data/risk/bot_{self.bot_config_id}",
                )

            # ── Hyperliquid pre-start checks ──────────────────────────
            if self._config.exchange_type == "hyperliquid":
                async with get_session() as hl_session:
                    builder_ok = await self._check_builder_approval(self._client, hl_session)
                    if not builder_ok:
                        return False
                    referral_ok = await self._check_referral_gate(self._client, hl_session)
                    if not referral_ok:
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
            )

        # Position monitoring every 5 minutes
        self._scheduler.add_job(
            self._monitor_positions_safe,
            CronTrigger(minute="*/5"),
            id=f"bot_{self.bot_config_id}_monitor",
            name=f"Bot {self.bot_config_id} Position Monitor",
            replace_existing=True,
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
            except Exception:
                pass

        if self._live_client:
            try:
                await self._live_client.close()
            except Exception:
                pass

        self.status = "stopped"
        logger.info(f"[Bot:{self.bot_config_id}] Stopped")

    async def _analyze_and_trade_safe(self):
        """Wrapper with error handling for the scheduler."""
        try:
            await self._analyze_and_trade()
        except Exception as e:
            logger.error(f"[Bot:{self.bot_config_id}] Analysis error: {e}")
            self.error_message = str(e)

    async def _analyze_and_trade(self):
        """Main trading logic — analyze markets and execute trades."""
        log_prefix = f"[Bot:{self.bot_config_id}]"
        logger.info(f"{log_prefix} Starting analysis...")

        # Check risk limits
        can_trade, reason = self._risk_manager.can_trade()
        if not can_trade:
            logger.warning(f"{log_prefix} Cannot trade: {reason}")
            return

        # Parse trading pairs
        trading_pairs = json.loads(self._config.trading_pairs)
        remaining = self._risk_manager.get_remaining_trades()

        for symbol in trading_pairs:
            if remaining <= 0:
                logger.info(f"{log_prefix} No remaining trades today")
                break

            try:
                await self._analyze_symbol(symbol)
                remaining = self._risk_manager.get_remaining_trades()
            except Exception as e:
                logger.error(f"{log_prefix} Error analyzing {symbol}: {e}")

        self.last_analysis = datetime.utcnow()

    def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        """Get or create a per-symbol lock to prevent duplicate position opening."""
        if symbol not in self._symbol_locks:
            self._symbol_locks[symbol] = asyncio.Lock()
        return self._symbol_locks[symbol]

    async def _analyze_symbol(self, symbol: str, force: bool = False):
        """Analyze a single symbol and potentially trade it.

        Args:
            symbol: Trading pair to analyze
            force: If True, skip the open-position check (used after rotation close)
        """
        async with self._get_symbol_lock(symbol):
            await self._analyze_symbol_locked(symbol, force)

    async def _analyze_symbol_locked(self, symbol: str, force: bool = False):
        """Internal: analyze symbol while holding per-symbol lock."""
        log_prefix = f"[Bot:{self.bot_config_id}]"

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

        # Execute on appropriate clients
        mode = self._config.mode
        if mode in ("demo", "both") and self._demo_client:
            await self._execute_trade(signal, self._demo_client, demo_mode=True)
        if mode in ("live", "both") and self._live_client:
            await self._execute_trade(signal, self._live_client, demo_mode=False)

    async def _execute_trade(self, signal: TradeSignal, client: ExchangeClient, demo_mode: bool):
        """Execute a trade on a specific exchange client."""
        log_prefix = f"[Bot:{self.bot_config_id}]"
        mode_str = "DEMO" if demo_mode else "LIVE"

        try:
            # Get balance
            balance = await client.get_account_balance()
            available = balance.available

            # Calculate position size
            position_usdt, position_size = self._risk_manager.calculate_position_size(
                balance=available,
                entry_price=signal.entry_price,
                confidence=signal.confidence,
                leverage=self._config.leverage,
            )

            if position_usdt < 5:
                logger.warning(f"{log_prefix} [{mode_str}] Position too small: ${position_usdt:.2f} (min 5 USDT)")
                return

            # Set leverage
            await client.set_leverage(signal.symbol, self._config.leverage)

            # Place order
            side = "long" if signal.direction.value == "long" else "short"
            order = await client.place_market_order(
                symbol=signal.symbol,
                side=side,
                size=position_size,
                leverage=self._config.leverage,
                take_profit=signal.target_price,
                stop_loss=signal.stop_loss,
            )

            if not order:
                logger.error(f"{log_prefix} [{mode_str}] Failed to place order")
                return

            # Get fill price — prefer order.price (avgPx from exchange)
            fill_price = order.price if order.price > 0 else signal.entry_price
            if order.order_id:
                try:
                    actual = await client.get_fill_price(signal.symbol, order.order_id)
                    if actual:
                        fill_price = actual
                except Exception:
                    pass

            # Record trade in database
            async with get_session() as session:
                trade = TradeRecord(
                    user_id=self._config.user_id,
                    bot_config_id=self.bot_config_id,
                    exchange=self._config.exchange_type,
                    symbol=signal.symbol,
                    side=signal.direction.value,
                    size=position_size,
                    entry_price=fill_price,
                    take_profit=signal.target_price,
                    stop_loss=signal.stop_loss,
                    leverage=self._config.leverage,
                    confidence=signal.confidence,
                    reason=signal.reason,
                    order_id=order.order_id,
                    status="open",
                    entry_time=datetime.utcnow(),
                    demo_mode=demo_mode,
                    metrics_snapshot=json.dumps(signal.metrics_snapshot),
                )
                session.add(trade)

            # Record in risk manager
            self._risk_manager.record_trade_entry(
                symbol=signal.symbol,
                side=signal.direction.value,
                size=position_size,
                entry_price=fill_price,
                leverage=self._config.leverage,
                confidence=signal.confidence,
                reason=signal.reason,
                order_id=order.order_id,
            )

            self.trades_today += 1
            logger.info(
                f"{log_prefix} [{mode_str}] Trade opened: {signal.direction.value.upper()} "
                f"{signal.symbol} @ ${fill_price:,.2f} (conf: {signal.confidence}%)"
            )

            # Send notifications (Discord + Telegram)
            try:
                for notifier in await self._get_notifiers():
                    try:
                        async with notifier:
                            await notifier.send_trade_entry(
                                symbol=signal.symbol,
                                side=signal.direction.value,
                                size=position_size,
                                entry_price=fill_price,
                                leverage=self._config.leverage,
                                take_profit=signal.target_price,
                                stop_loss=signal.stop_loss,
                                confidence=signal.confidence,
                                reason=f"[{self._config.name}] {signal.reason}",
                                order_id=order.order_id or "",
                                demo_mode=demo_mode,
                            )
                    except Exception as ne:
                        logger.warning(f"{log_prefix} Notification failed: {ne}")
            except Exception as notify_err:
                logger.warning(f"{log_prefix} Notifier setup failed: {notify_err}")

        except Exception as e:
            err_msg = str(e).lower()
            if "minimum amount" in err_msg or "minimum order" in err_msg:
                logger.warning(f"{log_prefix} [{mode_str}] Order below exchange minimum: {e}")
            else:
                logger.error(f"{log_prefix} [{mode_str}] Trade execution failed: {e}")

    async def _monitor_positions_safe(self):
        """Wrapper with error handling for position monitoring."""
        try:
            await self._monitor_positions()
        except Exception as e:
            logger.error(f"[Bot:{self.bot_config_id}] Monitor error: {e}")

    async def _monitor_positions(self):
        """Check open positions for this bot."""
        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TradeRecord).where(
                    TradeRecord.bot_config_id == self.bot_config_id,
                    TradeRecord.status == "open",
                )
            )
            open_trades = result.scalars().all()

            if not open_trades:
                return

            for trade in open_trades:
                await self._check_position(trade, session)

    async def _check_position(self, trade: TradeRecord, session):
        """Check a single open position."""
        # Determine which client to use
        client = self._demo_client if trade.demo_mode else self._live_client
        if not client:
            return

        try:
            position = await client.get_position(trade.symbol)

            if not position:
                # Position closed (TP/SL hit or manual)
                await self._handle_closed_position(trade, client, session)
                return

            # Check if position side matches
            if hasattr(position, 'side') and position.side != trade.side:
                await self._handle_closed_position(trade, client, session)

        except Exception as e:
            logger.error(f"[Bot:{self.bot_config_id}] Position check error: {e}")

    async def _handle_closed_position(self, trade: TradeRecord, client: ExchangeClient, session):
        """Handle a position that was closed externally (TP/SL/manual)."""
        log_prefix = f"[Bot:{self.bot_config_id}]"

        try:
            # Get current price as exit price estimate
            ticker = await client.get_ticker(trade.symbol)
            exit_price = ticker.last_price if ticker else trade.entry_price

            # Calculate PnL
            if trade.side == "long":
                pnl = (exit_price - trade.entry_price) * trade.size
            else:
                pnl = (trade.entry_price - exit_price) * trade.size

            pnl_percent = (pnl / (trade.entry_price * trade.size)) * 100

            # Determine exit reason
            if abs(exit_price - trade.take_profit) < trade.entry_price * 0.002:
                exit_reason = "TAKE_PROFIT"
            elif abs(exit_price - trade.stop_loss) < trade.entry_price * 0.002:
                exit_reason = "STOP_LOSS"
            else:
                exit_reason = "EXTERNAL_CLOSE"

            # Fetch trading fees from exchange (entry + exit via orders-history)
            try:
                if trade.order_id:
                    trade.fees = await client.get_trade_total_fees(
                        symbol=trade.symbol,
                        entry_order_id=trade.order_id,
                        close_order_id=trade.close_order_id,
                    )
            except Exception:
                trade.fees = 0

            # Fetch funding fees (charged every 8h while position was open)
            try:
                if trade.entry_time:
                    entry_ms = int(trade.entry_time.timestamp() * 1000)
                    exit_ms = int(datetime.utcnow().timestamp() * 1000)
                    trade.funding_paid = await client.get_funding_fees(
                        symbol=trade.symbol,
                        start_time_ms=entry_ms,
                        end_time_ms=exit_ms,
                    )
            except Exception:
                trade.funding_paid = 0

            # Calculate builder fee revenue (Hyperliquid only)
            try:
                if hasattr(client, 'calculate_builder_fee'):
                    trade.builder_fee = client.calculate_builder_fee(
                        entry_price=trade.entry_price,
                        exit_price=exit_price,
                        size=trade.size,
                    )
                else:
                    trade.builder_fee = 0
            except Exception:
                trade.builder_fee = 0

            # Update trade record
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.pnl_percent = pnl_percent
            trade.exit_time = datetime.utcnow()
            trade.exit_reason = exit_reason
            trade.status = "closed"

            # Record in risk manager
            self._risk_manager.record_trade_exit(
                symbol=trade.symbol,
                side=trade.side,
                size=trade.size,
                entry_price=trade.entry_price,
                exit_price=exit_price,
                fees=trade.fees or 0,
                funding_paid=trade.funding_paid or 0,
                reason=exit_reason,
                order_id=trade.order_id,
            )

            logger.info(
                f"{log_prefix} Trade #{trade.id} closed: {exit_reason} | "
                f"PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)"
            )

            # Send notifications (Discord + Telegram)
            try:
                duration_minutes = None
                if trade.entry_time:
                    duration_minutes = int((datetime.utcnow() - trade.entry_time).total_seconds() / 60)
                for notifier in await self._get_notifiers():
                    try:
                        async with notifier:
                            await notifier.send_trade_exit(
                                symbol=trade.symbol,
                                side=trade.side,
                                size=trade.size,
                                entry_price=trade.entry_price,
                                exit_price=exit_price,
                                pnl=pnl,
                                pnl_percent=pnl_percent,
                                fees=trade.fees or 0,
                                funding_paid=trade.funding_paid or 0,
                                reason=exit_reason,
                                order_id=trade.order_id or "",
                                duration_minutes=duration_minutes,
                                demo_mode=trade.demo_mode,
                                strategy_reason=f"[{self._config.name}]",
                            )
                    except Exception as ne:
                        logger.warning(f"{log_prefix} Notification failed: {ne}")
            except Exception as notify_err:
                logger.warning(f"{log_prefix} Notifier setup failed: {notify_err}")

        except Exception as e:
            logger.error(f"{log_prefix} Handle closed position error: {e}")

    # ── Trade Rotation ───────────────────────────────────────────

    async def _check_rotation_safe(self):
        """Wrapper with error handling for rotation check."""
        try:
            await self._check_rotation()
        except Exception as e:
            logger.error(f"[Bot:{self.bot_config_id}] Rotation check error: {e}")

    async def _check_rotation(self):
        """Check if any open trades have exceeded their rotation interval and need closing.

        If rotation_start_time is set (e.g. "08:00"), rotation windows are anchored
        to that UTC time. Otherwise, elapsed time since entry_time is used.
        In rotation_only mode with no open trades, triggers a new analysis.
        """
        rotation_minutes = getattr(self._config, "rotation_interval_minutes", None)
        if not rotation_minutes:
            return

        log_prefix = f"[Bot:{self.bot_config_id}]"
        now = datetime.utcnow()

        async with get_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(TradeRecord).where(
                    TradeRecord.bot_config_id == self.bot_config_id,
                    TradeRecord.status == "open",
                )
            )
            open_trades = result.scalars().all()

            if not open_trades:
                # In rotation_only mode, if no open trades exist, open one now
                if self._config.schedule_type == "rotation_only":
                    logger.info(f"{log_prefix} ROTATION: No open trades — triggering analysis")
                    pairs = json.loads(self._config.trading_pairs) if isinstance(self._config.trading_pairs, str) else self._config.trading_pairs
                    for symbol in pairs:
                        try:
                            await self._analyze_symbol(symbol, force=True)
                        except Exception as e:
                            logger.error(f"{log_prefix} ROTATION: Analysis failed for {symbol}: {e}")
                return

            # Determine if we use anchored rotation (start_time) or elapsed-based
            start_time_str = getattr(self._config, "rotation_start_time", None)

            for trade in open_trades:
                if not trade.entry_time:
                    continue

                should_rotate = False
                if start_time_str:
                    # Anchored rotation: calculate next rotation boundary from start_time
                    try:
                        sh, sm = int(start_time_str[:2]), int(start_time_str[3:5])
                        # Build today's anchor at start_time UTC
                        anchor = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                        # If anchor is in the future, go back one day
                        if anchor > now:
                            anchor = anchor - timedelta(days=1)
                        # How many intervals since anchor?
                        elapsed_since_anchor = (now - anchor).total_seconds() / 60
                        # Find the last rotation boundary
                        intervals_passed = int(elapsed_since_anchor // rotation_minutes)
                        last_boundary = anchor + timedelta(minutes=intervals_passed * rotation_minutes)
                        # Trade should rotate if it was opened before the last boundary
                        if trade.entry_time < last_boundary:
                            should_rotate = True
                            elapsed = (now - trade.entry_time).total_seconds() / 60
                    except (ValueError, IndexError):
                        # Fall back to elapsed-based
                        elapsed = (now - trade.entry_time).total_seconds() / 60
                        should_rotate = elapsed >= rotation_minutes
                else:
                    # Simple elapsed-based rotation
                    elapsed = (now - trade.entry_time).total_seconds() / 60
                    should_rotate = elapsed >= rotation_minutes

                if not should_rotate:
                    continue

                elapsed = (now - trade.entry_time).total_seconds() / 60
                logger.info(
                    f"{log_prefix} ROTATION: Trade #{trade.id} {trade.symbol} "
                    f"open for {elapsed:.0f}min (limit: {rotation_minutes}min) — closing"
                )

                # Force-close the trade
                client = self._demo_client if trade.demo_mode else self._live_client
                if not client:
                    continue

                closed = await self._force_close_trade(trade, client, session)

                if closed:
                    # Re-analyze and open a new trade for this symbol
                    logger.info(f"{log_prefix} ROTATION: Re-analyzing {trade.symbol}...")
                    try:
                        await self._analyze_symbol(trade.symbol, force=True)
                    except Exception as e:
                        logger.error(f"{log_prefix} ROTATION: Re-analysis failed for {trade.symbol}: {e}")

    async def _force_close_trade(
        self, trade: TradeRecord, client: ExchangeClient, session
    ) -> bool:
        """Force-close an open trade via the exchange. Returns True on success.

        Handles the case where the position was already closed (TP/SL hit)
        by marking the trade as ROTATION_ALREADY_CLOSED instead of retrying.
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        mode_str = "DEMO" if trade.demo_mode else "LIVE"

        try:
            # Close position via exchange client
            order = await client.close_position(trade.symbol, trade.side)

            if order is None:
                # Position already closed (TP/SL triggered before rotation)
                logger.info(
                    f"{log_prefix} [{mode_str}] ROTATION: Trade #{trade.id} {trade.symbol} "
                    f"already closed on exchange (TP/SL hit). Marking as ROTATION_ALREADY_CLOSED."
                )
                # Get current price for approximate PnL
                exit_price = trade.entry_price
                try:
                    ticker = await client.get_ticker(trade.symbol)
                    if ticker:
                        exit_price = ticker.last_price
                except Exception:
                    pass

                if trade.side == "long":
                    pnl = (exit_price - trade.entry_price) * trade.size
                else:
                    pnl = (trade.entry_price - exit_price) * trade.size
                pnl_percent = (pnl / (trade.entry_price * trade.size)) * 100

                trade.exit_price = exit_price
                trade.pnl = pnl
                trade.pnl_percent = pnl_percent
                trade.exit_time = datetime.utcnow()
                trade.exit_reason = "ROTATION_ALREADY_CLOSED"
                trade.status = "closed"

                self._risk_manager.record_trade_exit(
                    symbol=trade.symbol, side=trade.side, size=trade.size,
                    entry_price=trade.entry_price, exit_price=exit_price,
                    fees=trade.fees or 0, funding_paid=trade.funding_paid or 0,
                    reason="ROTATION_ALREADY_CLOSED", order_id=trade.order_id,
                )
                return True

            # Get exit price from the close order
            exit_price = trade.entry_price
            if order.price and order.price > 0:
                exit_price = order.price
            else:
                try:
                    ticker = await client.get_ticker(trade.symbol)
                    if ticker:
                        exit_price = ticker.last_price
                except Exception:
                    pass

            # Calculate PnL
            if trade.side == "long":
                pnl = (exit_price - trade.entry_price) * trade.size
            else:
                pnl = (trade.entry_price - exit_price) * trade.size
            pnl_percent = (pnl / (trade.entry_price * trade.size)) * 100

            # Update trade record
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.pnl_percent = pnl_percent
            trade.exit_time = datetime.utcnow()
            trade.exit_reason = "ROTATION"
            trade.status = "closed"

            # Record in risk manager
            self._risk_manager.record_trade_exit(
                symbol=trade.symbol, side=trade.side, size=trade.size,
                entry_price=trade.entry_price, exit_price=exit_price,
                fees=trade.fees or 0, funding_paid=trade.funding_paid or 0,
                reason="ROTATION", order_id=trade.order_id,
            )

            logger.info(
                f"{log_prefix} [{mode_str}] ROTATION closed trade #{trade.id}: "
                f"{trade.side.upper()} {trade.symbol} | PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)"
            )

            # Send notifications (Discord + Telegram)
            try:
                duration_minutes = int((datetime.utcnow() - trade.entry_time).total_seconds() / 60) if trade.entry_time else None
                for notifier in await self._get_notifiers():
                    try:
                        async with notifier:
                            await notifier.send_trade_exit(
                                symbol=trade.symbol, side=trade.side, size=trade.size,
                                entry_price=trade.entry_price, exit_price=exit_price,
                                pnl=pnl, pnl_percent=pnl_percent,
                                fees=trade.fees or 0, funding_paid=trade.funding_paid or 0,
                                reason="ROTATION", order_id=trade.order_id or "",
                                duration_minutes=duration_minutes, demo_mode=trade.demo_mode,
                                strategy_reason=f"[{self._config.name}] Auto-rotation ({self._config.rotation_interval_minutes}min)",
                            )
                    except Exception as ne:
                        logger.warning(f"{log_prefix} Notification failed: {ne}")
            except Exception as notify_err:
                logger.warning(f"{log_prefix} Notifier setup failed: {notify_err}")

            return True

        except Exception as e:
            err_msg = str(e).lower()
            # Handle "no position" errors from exchange API explicitly
            if any(phrase in err_msg for phrase in ("no position", "position not exist", "does not exist")):
                logger.info(
                    f"{log_prefix} [{mode_str}] ROTATION: Trade #{trade.id} {trade.symbol} "
                    f"position not found on exchange. Marking as ROTATION_ALREADY_CLOSED."
                )
                trade.exit_price = trade.entry_price
                trade.pnl = 0
                trade.pnl_percent = 0
                trade.exit_time = datetime.utcnow()
                trade.exit_reason = "ROTATION_ALREADY_CLOSED"
                trade.status = "closed"
                self._risk_manager.record_trade_exit(
                    symbol=trade.symbol, side=trade.side, size=trade.size,
                    entry_price=trade.entry_price, exit_price=trade.entry_price,
                    fees=trade.fees or 0, funding_paid=trade.funding_paid or 0,
                    reason="ROTATION_ALREADY_CLOSED", order_id=trade.order_id,
                )
                return True

            logger.error(f"{log_prefix} [{mode_str}] ROTATION close failed for trade #{trade.id}: {e}")
            return False

    async def _get_discord_notifier(self) -> Optional[DiscordNotifier]:
        """Load Discord webhook from bot-specific config only."""
        try:
            if self._config and self._config.discord_webhook_url:
                webhook_url = decrypt_value(self._config.discord_webhook_url)
                return DiscordNotifier(webhook_url=webhook_url)
        except Exception as e:
            logger.warning(f"[Bot:{self.bot_config_id}] Could not load Discord config: {e}")
        return None

    async def _get_notifiers(self) -> list:
        """Return all configured notifiers (Discord + Telegram)."""
        notifiers = []
        discord = await self._get_discord_notifier()
        if discord:
            notifiers.append(discord)
        try:
            if self._config and self._config.telegram_bot_token and self._config.telegram_chat_id:
                from src.notifications.telegram_notifier import TelegramNotifier
                notifiers.append(TelegramNotifier(
                    bot_token=decrypt_value(self._config.telegram_bot_token),
                    chat_id=self._config.telegram_chat_id,
                ))
        except Exception as e:
            logger.warning(f"[Bot:{self.bot_config_id}] Could not load Telegram config: {e}")
        return notifiers

    async def _check_referral_gate(self, client: ExchangeClient, db) -> bool:
        """HARD gate: block bot start unless user is referred via our affiliate link.

        Always enforced when HL_REFERRAL_CODE is set.
        Checks DB flag first (fast path), then live HL API, saves result to DB.
        Returns True if OK to proceed, False if blocked.
        """
        from src.utils.settings import get_hl_config
        hl_cfg = await get_hl_config()
        referral_code = hl_cfg["referral_code"]
        if not referral_code:
            return True

        log_prefix = f"[Bot:{self.bot_config_id}]"

        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient

            if not isinstance(client, HyperliquidClient):
                return True

            # Check DB flag first (fast path)
            from src.models.database import ExchangeConnection
            from sqlalchemy import select as sa_select
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == self._config.user_id,
                    ExchangeConnection.exchange_type == "hyperliquid",
                )
            )
            conn = result.scalar_one_or_none()

            if conn and conn.referral_verified:
                logger.info(f"{log_prefix} Referral verified (DB flag)")
                return True

            # Live check via HL API
            info = await client.get_referral_info()
            referred_by = None
            if info:
                referred_by = info.get("referredBy") or info.get("referred_by")

            if referred_by:
                # Save to DB so API-level checks work
                if conn:
                    conn.referral_verified = True
                    conn.referral_verified_at = datetime.utcnow()
                    await db.commit()
                logger.info(f"{log_prefix} User is referred (by {referred_by}), saved to DB")
                return True

            link = f"https://app.hyperliquid.xyz/join/{referral_code}"
            self.error_message = (
                f"Referral erforderlich: Bitte registriere dich ueber {link} "
                f"bevor du Hyperliquid Bots nutzen kannst."
            )
            self.status = "error"
            logger.warning(f"{log_prefix} {self.error_message}")
            return False
        except Exception as e:
            # On error: BLOCK to be safe (no silent bypass)
            logger.warning(f"{log_prefix} Referral check failed: {e}")
            self.error_message = (
                f"Referral-Pruefung fehlgeschlagen. Bitte versuche es erneut. "
                f"Falls das Problem bestehen bleibt, registriere dich ueber "
                f"https://app.hyperliquid.xyz/join/{referral_code}"
            )
            self.status = "error"
            return False

    async def _check_builder_approval(self, client: ExchangeClient, db) -> bool:
        """HARD gate: block bot start if builder fee not approved.

        Returns True if OK to proceed, False if blocked.
        """
        log_prefix = f"[Bot:{self.bot_config_id}]"
        try:
            from src.exchanges.hyperliquid.client import HyperliquidClient

            if not isinstance(client, HyperliquidClient):
                return True
            if not client.builder_config:
                return True

            # Check DB flag first (fast path)
            from src.models.database import ExchangeConnection
            from sqlalchemy import select as sa_select
            result = await db.execute(
                sa_select(ExchangeConnection).where(
                    ExchangeConnection.user_id == self._config.user_id,
                    ExchangeConnection.exchange_type == "hyperliquid",
                )
            )
            conn = result.scalar_one_or_none()

            if conn and conn.builder_fee_approved:
                logger.info(f"{log_prefix} Builder fee approved (DB flag)")
                return True

            # Fallback: verify on-chain
            approved = await client.check_builder_fee_approval()
            if approved is not None and approved >= client.builder_config["f"]:
                if conn:
                    conn.builder_fee_approved = True
                    conn.builder_fee_approved_at = datetime.utcnow()
                    await db.commit()
                logger.info(f"{log_prefix} Builder fee approved (on-chain verified)")
                return True

            # NOT APPROVED — block bot start
            self.error_message = (
                "Builder Fee nicht genehmigt. Bitte genehmige die Builder Fee "
                "auf der Website unter 'Meine Bots' bevor du einen Hyperliquid Bot starten kannst."
            )
            self.status = "error"
            logger.warning(f"{log_prefix} Builder fee NOT approved — bot start blocked")
            return False

        except Exception as e:
            logger.warning(f"{log_prefix} Builder approval check failed: {e}")
            self.error_message = f"Builder Fee Pruefung fehlgeschlagen: {e}"
            self.status = "error"
            return False

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
