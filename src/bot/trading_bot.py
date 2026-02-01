"""
Main Trading Bot Orchestrator.

Coordinates all components:
- Bitget API client for trading
- Market data fetching
- Strategy execution
- Risk management
- Discord notifications
- Trade tracking

The bot runs on a schedule, analyzing markets and executing trades
based on the Contrarian Liquidation Hunter strategy.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.api.bitget_client import BitgetClient, BitgetClientError
from src.data.market_data import MarketDataFetcher, DataFetchError
from src.strategy.liquidation_hunter import LiquidationHunterStrategy, TradeSignal, SignalDirection
from src.risk.risk_manager import RiskManager
from src.notifications.discord_notifier import DiscordNotifier
from src.models.trade_database import TradeDatabase
from src.data.funding_tracker import FundingTracker
from src.utils.logger import get_logger, setup_logging
from config.settings import settings, ConfigValidationError

logger = get_logger(__name__)


class TradingBot:
    """
    Main trading bot orchestrator.

    Manages the complete trading lifecycle:
    1. Initialize all components
    2. Analyze markets periodically
    3. Generate trading signals
    4. Execute trades via Bitget API
    5. Monitor open positions
    6. Send notifications to Discord
    7. Track all trades in database
    """

    def __init__(self):
        """Initialize the trading bot."""
        # Setup logging
        setup_logging(
            log_level=settings.logging.level,
            log_file=settings.logging.file,
        )

        logger.info("=" * 60)
        logger.info("BITGET TRADING BOT - Contrarian Liquidation Hunter")
        logger.info("=" * 60)

        # Initialize components
        self.bitget_client: Optional[BitgetClient] = None
        self.data_fetcher: Optional[MarketDataFetcher] = None
        self.strategy: Optional[LiquidationHunterStrategy] = None
        self.risk_manager: Optional[RiskManager] = None
        self.discord: Optional[DiscordNotifier] = None
        self.trade_db: Optional[TradeDatabase] = None
        self.funding_tracker: Optional[FundingTracker] = None
        self.scheduler: Optional[AsyncIOScheduler] = None

        # State
        self._running = False
        self._initialized = False

    async def initialize(self) -> bool:
        """
        Initialize all bot components.

        Returns:
            True if initialization successful
        """
        logger.info("Initializing trading bot components...")

        try:
            # Validate configuration with strict checks
            try:
                is_valid, errors = settings.validate_strict(raise_on_error=False)
                if errors:
                    for error in errors:
                        if "optional" in error.lower():
                            logger.warning(f"Config: {error}")
                        else:
                            logger.error(f"Config: {error}")
                if not is_valid:
                    logger.error("Configuration validation failed!")
                    return False
            except ConfigValidationError as e:
                logger.error(f"Configuration error: {e}")
                return False

            # Log trading mode
            if settings.is_demo_mode:
                logger.info("=" * 40)
                logger.info("  DEMO MODE - No real trades will execute")
                logger.info("=" * 40)
            else:
                logger.warning("=" * 40)
                logger.warning("  LIVE MODE - Real trades will execute!")
                logger.warning("=" * 40)

            # Initialize Bitget client
            self.bitget_client = BitgetClient()
            await self.bitget_client._ensure_session()
            logger.info("Bitget client initialized")

            # Initialize market data fetcher
            self.data_fetcher = MarketDataFetcher()
            await self.data_fetcher._ensure_session()
            logger.info("Market data fetcher initialized")

            # Initialize strategy
            self.strategy = LiquidationHunterStrategy(self.data_fetcher)
            logger.info("Liquidation Hunter strategy initialized")

            # Initialize risk manager
            self.risk_manager = RiskManager()
            logger.info("Risk manager initialized")

            # Initialize Discord notifier
            self.discord = DiscordNotifier()
            await self.discord._ensure_session()
            logger.info("Discord notifier initialized")

            # Initialize trade database
            self.trade_db = TradeDatabase()
            await self.trade_db.initialize()
            logger.info("Trade database initialized")

            # Initialize funding tracker
            self.funding_tracker = FundingTracker()
            await self.funding_tracker.initialize()
            logger.info("Funding tracker initialized")

            # Initialize scheduler
            self.scheduler = AsyncIOScheduler()
            self._setup_scheduled_jobs()
            logger.info("Scheduler initialized")

            # Get account balance and initialize daily stats
            await self._initialize_daily_session()

            self._initialized = True
            logger.info("All components initialized successfully!")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            return False

    async def _initialize_daily_session(self):
        """Initialize the daily trading session."""
        try:
            # Get current balance
            balance_data = await self.bitget_client.get_account_balance()
            if balance_data:
                available = float(balance_data.get("available", 0))
                equity = float(balance_data.get("usdtEquity", available))
                logger.info(f"Account Balance: ${equity:,.2f} (Available: ${available:,.2f})")

                # Initialize risk manager with starting balance
                self.risk_manager.initialize_day(equity)
            else:
                logger.warning("Could not fetch account balance")
                self.risk_manager.initialize_day(0)

        except Exception as e:
            logger.error(f"Error initializing daily session: {e}")

    def _setup_scheduled_jobs(self):
        """Set up scheduled analysis and trading jobs."""
        # Main analysis job - aligned with major market sessions for optimal liquidation hunting
        #
        # Schedule (all times UTC):
        # - 01:00: Asia Session (1h after Tokyo open) - Reaction to US session, liquidation cascades
        # - 08:00: EU Open (London) - European traders enter, potential reversals
        # - 14:00: US Open + ETFs (30min after NYSE) - Critical! BTC ETF flows (IBIT, FBTC, etc.)
        # - 21:00: US Close - End-of-day profit-taking and position adjustments
        #
        self.scheduler.add_job(
            self.analyze_and_trade,
            CronTrigger(hour="1,8,14,21", minute=0),
            id="main_analysis",
            name="Main Market Analysis",
            replace_existing=True,
        )

        # Position monitoring - every 5 minutes
        self.scheduler.add_job(
            self.monitor_positions,
            CronTrigger(minute="*/5"),
            id="position_monitor",
            name="Position Monitor",
            replace_existing=True,
        )

        # Daily summary - at 23:55 UTC
        self.scheduler.add_job(
            self.send_daily_summary,
            CronTrigger(hour=23, minute=55),
            id="daily_summary",
            name="Daily Summary",
            replace_existing=True,
        )

        logger.info("Scheduled jobs configured")

    async def start(self):
        """Start the trading bot."""
        if not self._initialized:
            success = await self.initialize()
            if not success:
                logger.error("Failed to initialize bot. Exiting.")
                return

        self._running = True
        logger.info("Starting trading bot...")

        # Send startup notification
        await self.discord.send_bot_status(
            "STARTED",
            "Trading bot is now running and monitoring markets.",
            {
                "Trading Pairs": ", ".join(settings.trading.trading_pairs),
                "Max Daily Trades": settings.trading.max_trades_per_day,
                "Daily Loss Limit": f"{settings.trading.daily_loss_limit_percent}%",
            },
        )

        # Start the scheduler
        self.scheduler.start()

        # Run initial analysis
        await self.analyze_and_trade()

        # Keep running
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Bot shutdown requested")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the trading bot gracefully."""
        logger.info("Stopping trading bot...")
        self._running = False

        # Stop scheduler
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown()

        # Close all connections
        if self.bitget_client:
            await self.bitget_client.close()
        if self.data_fetcher:
            await self.data_fetcher.close()
        if self.strategy:
            await self.strategy.close()
        if self.discord:
            await self.discord.send_bot_status("STOPPED", "Trading bot has been stopped.")
            await self.discord.close()

        logger.info("Trading bot stopped")

    async def analyze_and_trade(self):
        """
        Main trading logic - analyze markets and potentially execute trades.

        This is the core method that:
        1. Checks if trading is allowed (risk limits)
        2. Analyzes each trading pair
        3. Generates signals
        4. Executes trades if signals are strong enough
        """
        logger.info("=" * 50)
        logger.info("Starting market analysis...")
        logger.info("=" * 50)

        # Check if we can trade
        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            logger.warning(f"Trading not allowed: {reason}")
            return

        remaining_trades = self.risk_manager.get_remaining_trades()
        logger.info(f"Remaining trades today: {remaining_trades}")

        # Analyze each trading pair
        for symbol in settings.trading.trading_pairs:
            if remaining_trades <= 0:
                logger.info("No remaining trades for today")
                break

            try:
                await self._analyze_symbol(symbol)
                remaining_trades = self.risk_manager.get_remaining_trades()
            except DataFetchError as e:
                # Critical: market data unavailable - do NOT trade with unreliable data
                logger.error(f"Market data unreliable for {symbol}: {e}")
                await self.discord.send_error(
                    "DATA_FETCH_ERROR",
                    f"Cannot trade {symbol} - market data unavailable",
                    f"Failed sources: {e.source}\n{e.message}"
                )
                # Continue to next symbol, don't crash the bot
            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                await self.discord.send_error("ANALYSIS_ERROR", f"Failed to analyze {symbol}", str(e))

    async def _analyze_symbol(self, symbol: str):
        """
        Analyze a single symbol and potentially trade it.

        Args:
            symbol: Trading pair to analyze
        """
        logger.info(f"Analyzing {symbol}...")

        # Check for existing open positions
        open_trades = await self.trade_db.get_open_trades(symbol)
        if open_trades:
            logger.info(f"Already have open position in {symbol}, skipping")
            return

        # Generate signal
        signal = await self.strategy.generate_signal(symbol)

        # Check if we should trade
        should_trade, trade_reason = await self.strategy.should_trade(signal)

        if not should_trade:
            logger.info(f"Signal rejected: {trade_reason}")
            return

        # Send signal alert to Discord
        await self.discord.send_signal_alert(
            symbol=signal.symbol,
            direction=signal.direction.value,
            confidence=signal.confidence,
            reason=signal.reason,
            entry_price=signal.entry_price,
            target_price=signal.target_price,
            stop_loss=signal.stop_loss,
            metrics=signal.metrics_snapshot,
        )

        # Execute the trade
        await self._execute_trade(signal)

    async def _execute_trade(self, signal: TradeSignal):
        """
        Execute a trade based on the signal.

        Args:
            signal: Trade signal to execute
        """
        is_demo = settings.is_demo_mode
        mode_prefix = "[DEMO] " if is_demo else ""

        logger.info(f"{mode_prefix}Executing {signal.direction.value.upper()} trade on {signal.symbol}")

        try:
            # Get current account balance
            if is_demo:
                # In demo mode, use simulated balance (skip API call)
                available_balance = 10000.0  # Simulated $10k for demo
                logger.info(f"{mode_prefix}Using simulated balance: ${available_balance:.2f}")
            else:
                # In live mode, get real balance from API
                balance_data = await self.bitget_client.get_account_balance()
                available_balance = float(balance_data.get("available", 0))

            # Calculate position size
            position_usdt, position_size = self.risk_manager.calculate_position_size(
                balance=available_balance,
                entry_price=signal.entry_price,
                confidence=signal.confidence,
                leverage=settings.trading.leverage,
            )

            # Validate minimum order size
            if position_usdt < 10:  # Minimum $10 position
                logger.warning(f"{mode_prefix}Position size too small: ${position_usdt:.2f}")
                return

            # In demo mode, skip actual order placement
            if is_demo:
                logger.info(f"{mode_prefix}Would place order: {signal.direction.value.upper()} {position_size:.6f} {signal.symbol}")
                logger.info(f"{mode_prefix}Entry: ${signal.entry_price:.2f}, TP: ${signal.target_price:.2f}, SL: ${signal.stop_loss:.2f}")

                # Generate a demo order ID
                import time
                order_id = f"DEMO_{int(time.time() * 1000)}"
                order_result = {"orderId": order_id}
                entry_price = signal.entry_price  # Use signal price in demo mode
            else:
                # LIVE MODE: Actually place the order
                # Set leverage
                await self.bitget_client.set_leverage(
                    symbol=signal.symbol,
                    leverage=settings.trading.leverage,
                    product_type="USDT-FUTURES",
                )

                # Place market order
                order_result = await self.bitget_client.place_market_order(
                    symbol=signal.symbol,
                    side="buy" if signal.direction.value == "long" else "sell",
                    size=position_size,
                    product_type="USDT-FUTURES",
                )

                if not order_result:
                    logger.error(f"Failed to place order for {signal.symbol}")
                    return

                order_id = order_result.get("orderId", "unknown")

                # Get actual fill price from exchange (with retries)
                actual_entry_price = await self.bitget_client.get_fill_price(
                    symbol=signal.symbol,
                    order_id=order_id,
                )

                # Use actual fill price if available, otherwise fall back to signal price
                if actual_entry_price:
                    entry_price = actual_entry_price
                    slippage = actual_entry_price - signal.entry_price
                    slippage_pct = (slippage / signal.entry_price) * 100
                    logger.info(
                        f"Fill price: ${actual_entry_price:.2f} "
                        f"(Signal: ${signal.entry_price:.2f}, Slippage: {slippage_pct:+.3f}%)"
                    )
                else:
                    entry_price = signal.entry_price
                    logger.warning(
                        f"Could not get fill price, using signal price: ${signal.entry_price:.2f}"
                    )

            if order_result:
                trade_id = await self.trade_db.create_trade(
                    symbol=signal.symbol,
                    side=signal.direction.value,
                    size=position_size,
                    entry_price=entry_price,
                    take_profit=signal.target_price,
                    stop_loss=signal.stop_loss,
                    leverage=settings.trading.leverage,
                    confidence=signal.confidence,
                    reason=signal.reason,
                    order_id=order_id,
                    metrics_snapshot=json.dumps(signal.metrics_snapshot),
                )

                # Record in risk manager with actual entry price
                self.risk_manager.record_trade_entry(
                    symbol=signal.symbol,
                    side=signal.direction.value,
                    size=position_size,
                    entry_price=entry_price,
                    leverage=settings.trading.leverage,
                    confidence=signal.confidence,
                    reason=signal.reason,
                    order_id=order_id,
                )

                # Send Discord notification with actual entry price
                await self.discord.send_trade_entry(
                    symbol=signal.symbol,
                    side=signal.direction.value,
                    size=position_size,
                    entry_price=entry_price,
                    leverage=settings.trading.leverage,
                    take_profit=signal.target_price,
                    stop_loss=signal.stop_loss,
                    confidence=signal.confidence,
                    reason=signal.reason,
                    order_id=order_id,
                )

                logger.info(f"Trade executed successfully! Order ID: {order_id}, Trade ID: {trade_id}")

        except BitgetClientError as e:
            logger.error(f"Bitget API error executing trade: {e}")
            await self.discord.send_error("TRADE_EXECUTION_ERROR", str(e))
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            await self.discord.send_error("TRADE_ERROR", str(e))

    async def monitor_positions(self):
        """
        Monitor open positions and handle exits.

        Checks:
        - If TP/SL have been hit
        - If positions need manual closing
        - Updates trade records
        - Records funding payments at funding times
        """
        try:
            # Get open trades from database
            open_trades = await self.trade_db.get_open_trades()

            if not open_trades:
                return

            logger.debug(f"Monitoring {len(open_trades)} open positions")

            # Check if it's funding time and record payments
            if self.funding_tracker.is_funding_time():
                await self._record_funding_payments(open_trades)

            for trade in open_trades:
                await self._check_position(trade)

        except Exception as e:
            logger.error(f"Error monitoring positions: {e}")

    async def _record_funding_payments(self, open_trades):
        """
        Record funding payments for all open positions.

        Called when current time is near a funding payment time (00:00, 08:00, 16:00 UTC).
        """
        logger.info("Recording funding payments for open positions...")

        for trade in open_trades:
            try:
                # Get current funding rate for the symbol
                funding_rate = await self.data_fetcher.get_funding_rate(trade.symbol)

                if funding_rate is None:
                    continue

                # Calculate position value
                current_price = await self.data_fetcher.get_ticker(trade.symbol)
                if current_price:
                    position_value = trade.size * current_price.get("last", trade.entry_price)
                else:
                    position_value = trade.size * trade.entry_price

                # Record the funding payment
                await self.funding_tracker.record_funding_payment(
                    symbol=trade.symbol,
                    funding_rate=funding_rate,
                    position_size=trade.size,
                    position_value=position_value,
                    side=trade.side,
                    trade_id=trade.id
                )

                # Also record the funding rate for historical tracking
                await self.funding_tracker.record_funding_rate(trade.symbol, funding_rate)

            except Exception as e:
                logger.error(f"Error recording funding for {trade.symbol}: {e}")

    async def _check_position(self, trade):
        """
        Check a single open position.

        Args:
            trade: Trade object to check
        """
        try:
            # Get current position from exchange
            positions = await self.bitget_client.get_position(trade.symbol)

            if not positions:
                # Position might be closed
                await self._handle_closed_position(trade)
                return

            # Find matching position
            for pos in positions if isinstance(positions, list) else [positions]:
                if pos.get("holdSide") == trade.side:
                    # Position still open
                    unrealized_pnl = float(pos.get("unrealizedPL", 0))
                    logger.debug(f"{trade.symbol} {trade.side}: Unrealized PnL = ${unrealized_pnl:.2f}")
                    return

            # Position not found - likely closed
            await self._handle_closed_position(trade)

        except Exception as e:
            logger.error(f"Error checking position {trade.id}: {e}")

    async def _handle_closed_position(self, trade):
        """
        Handle a position that has been closed (by TP/SL or manually).

        Args:
            trade: Trade object that was closed
        """
        logger.info(f"Position closed for trade #{trade.id} ({trade.symbol})")

        try:
            # Get order history to find exit details
            order_history = await self.bitget_client.get_order_history(trade.symbol, limit=10)

            exit_price = trade.entry_price  # Default
            fees = 0
            exit_reason = "UNKNOWN"

            # Find the closing order
            for order in order_history if order_history else []:
                if order.get("tradeSide") == "close":
                    exit_price = float(order.get("priceAvg", trade.entry_price))
                    fees = float(order.get("fee", 0))

                    # Determine exit reason
                    if abs(exit_price - trade.take_profit) < trade.entry_price * 0.001:
                        exit_reason = "TAKE_PROFIT"
                    elif abs(exit_price - trade.stop_loss) < trade.entry_price * 0.001:
                        exit_reason = "STOP_LOSS"
                    else:
                        exit_reason = "MANUAL_CLOSE"
                    break

            # Calculate PnL
            if trade.side == "long":
                pnl = (exit_price - trade.entry_price) * trade.size
            else:
                pnl = (trade.entry_price - exit_price) * trade.size

            pnl_percent = (pnl / (trade.entry_price * trade.size)) * 100

            # Get total funding paid for this trade from tracker
            funding_paid = await self.funding_tracker.get_total_funding_for_trade(trade.id)

            # Update database
            await self.trade_db.close_trade(
                trade_id=trade.id,
                exit_price=exit_price,
                pnl=pnl,
                pnl_percent=pnl_percent,
                fees=fees,
                funding_paid=funding_paid,
                exit_reason=exit_reason,
                close_order_id="auto_close",
            )

            # Update risk manager
            self.risk_manager.record_trade_exit(
                symbol=trade.symbol,
                side=trade.side,
                size=trade.size,
                entry_price=trade.entry_price,
                exit_price=exit_price,
                fees=fees,
                funding_paid=funding_paid,
                reason=exit_reason,
                order_id="auto_close",
            )

            # Calculate duration
            duration_minutes = None
            if trade.entry_time:
                duration = datetime.now() - trade.entry_time
                duration_minutes = int(duration.total_seconds() / 60)

            # Send Discord notification
            await self.discord.send_trade_exit(
                symbol=trade.symbol,
                side=trade.side,
                size=trade.size,
                entry_price=trade.entry_price,
                exit_price=exit_price,
                pnl=pnl,
                pnl_percent=pnl_percent,
                fees=fees,
                funding_paid=funding_paid,
                reason=exit_reason,
                order_id=trade.order_id,
                duration_minutes=duration_minutes,
            )

            logger.info(
                f"Trade #{trade.id} closed: {exit_reason} | "
                f"PnL: ${pnl:.2f} ({pnl_percent:+.2f}%)"
            )

        except Exception as e:
            logger.error(f"Error handling closed position: {e}")

    async def send_daily_summary(self):
        """Send the daily trading summary to Discord."""
        logger.info("Generating daily summary...")

        try:
            stats = self.risk_manager.get_daily_stats()

            if stats:
                await self.discord.send_daily_summary(
                    date=stats.date,
                    starting_balance=stats.starting_balance,
                    ending_balance=stats.current_balance,
                    total_trades=stats.trades_executed,
                    winning_trades=stats.winning_trades,
                    losing_trades=stats.losing_trades,
                    total_pnl=stats.total_pnl,
                    total_fees=stats.total_fees,
                    total_funding=stats.total_funding,
                    max_drawdown=stats.max_drawdown,
                )

            logger.info("Daily summary sent")

        except Exception as e:
            logger.error(f"Error sending daily summary: {e}")

    async def close_all_positions(self):
        """Emergency function to close all open positions."""
        logger.warning("CLOSING ALL POSITIONS!")

        try:
            positions = await self.bitget_client.get_all_positions()

            for pos in positions if positions else []:
                symbol = pos.get("symbol")
                side = pos.get("holdSide")
                size = pos.get("total")

                if size and float(size) > 0:
                    await self.bitget_client.close_position(symbol, side)
                    logger.info(f"Closed {side} position on {symbol}")

            await self.discord.send_bot_status(
                "EMERGENCY_CLOSE",
                "All positions have been closed.",
            )

        except Exception as e:
            logger.error(f"Error closing positions: {e}")
            await self.discord.send_error("EMERGENCY_CLOSE_ERROR", str(e))

    async def run_once(self):
        """
        Run a single analysis cycle (useful for testing).

        Returns:
            Generated signals
        """
        if not self._initialized:
            await self.initialize()

        signals = []
        for symbol in settings.trading.trading_pairs:
            signal = await self.strategy.generate_signal(symbol)
            signals.append(signal)

        return signals
