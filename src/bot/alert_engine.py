"""
AlertEngine: Background task that checks and triggers user-defined alerts.

Runs as a singleton within the BotOrchestrator, periodically checking:
- Price alerts (every 60s)
- Portfolio alerts (every 300s)

Strategy alerts are checked inline by BotWorker after signal generation.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from src.models.database import Alert, AlertHistory
from src.models.session import get_session
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AlertEngine:
    """Checks active alerts and triggers notifications when conditions are met."""

    def __init__(self):
        self._running = False
        self._price_task: Optional[asyncio.Task] = None
        self._portfolio_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start alert checking loops."""
        if self._running:
            return
        self._running = True
        self._price_task = asyncio.create_task(self._price_loop())
        self._portfolio_task = asyncio.create_task(self._portfolio_loop())
        logger.info("AlertEngine started")

    async def stop(self):
        """Stop alert checking loops."""
        self._running = False
        for task in (self._price_task, self._portfolio_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("AlertEngine stopped")

    async def _price_loop(self):
        """Check price alerts every 60 seconds."""
        while self._running:
            try:
                await self._check_price_alerts()
            except Exception as e:
                logger.error(f"AlertEngine price check error: {e}")
            await asyncio.sleep(60)

    async def _portfolio_loop(self):
        """Check portfolio alerts every 5 minutes."""
        while self._running:
            try:
                await self._check_portfolio_alerts()
            except Exception as e:
                logger.error(f"AlertEngine portfolio check error: {e}")
            await asyncio.sleep(300)

    async def _check_price_alerts(self):
        """Check all active price alerts against current prices."""
        async with get_session() as db:
            result = await db.execute(
                select(Alert).where(
                    Alert.alert_type == "price",
                    Alert.is_enabled == True,
                    Alert.symbol.isnot(None),
                )
            )
            alerts = result.scalars().all()

        if not alerts:
            return

        # Group alerts by symbol to minimize API calls
        symbols = set(a.symbol for a in alerts if a.symbol)
        prices = {}

        try:
            from src.data.market_data import MarketDataFetcher
            fetcher = MarketDataFetcher()
            await fetcher._ensure_session()
            try:
                for symbol in symbols:
                    try:
                        price = await fetcher.get_current_price(symbol)
                        if price and price > 0:
                            prices[symbol] = price
                    except Exception as e:
                        logger.debug(f"Price fetch failed for {symbol}: {e}")
            finally:
                await fetcher.close()
        except Exception as e:
            logger.warning(f"AlertEngine: MarketDataFetcher error: {e}")
            return

        for alert in alerts:
            if alert.symbol not in prices:
                continue

            current_price = prices[alert.symbol]
            triggered = False

            if alert.category == "price_above" or alert.direction == "above":
                triggered = current_price >= alert.threshold
            elif alert.category == "price_below" or alert.direction == "below":
                triggered = current_price <= alert.threshold
            elif alert.category == "price_change_percent":
                # Would need baseline price tracking; skip for now
                pass

            if triggered:
                await self._trigger_alert(
                    alert,
                    current_price,
                    f"{alert.symbol} price is ${current_price:,.2f} "
                    f"({alert.direction} threshold ${alert.threshold:,.2f})",
                )

    async def _check_portfolio_alerts(self):
        """Check portfolio alerts against aggregated stats."""
        async with get_session() as db:
            result = await db.execute(
                select(Alert).where(
                    Alert.alert_type == "portfolio",
                    Alert.is_enabled == True,
                )
            )
            alerts = result.scalars().all()

        if not alerts:
            return

        # Group by user_id to compute stats once per user
        user_alerts: dict[int, list[Alert]] = {}
        for alert in alerts:
            user_alerts.setdefault(alert.user_id, []).append(alert)

        for user_id, user_alert_list in user_alerts.items():
            try:
                stats = await self._get_user_daily_stats(user_id)
                if not stats:
                    continue

                for alert in user_alert_list:
                    triggered = False
                    current_value = 0.0

                    if alert.category == "daily_loss":
                        daily_loss_pct = abs(stats.get("daily_pnl_percent", 0))
                        current_value = daily_loss_pct
                        triggered = daily_loss_pct >= alert.threshold

                    elif alert.category == "drawdown":
                        drawdown = abs(stats.get("max_drawdown", 0))
                        current_value = drawdown
                        triggered = drawdown >= alert.threshold

                    elif alert.category == "profit_target":
                        daily_pnl = stats.get("daily_pnl", 0)
                        current_value = daily_pnl
                        triggered = daily_pnl >= alert.threshold

                    if triggered:
                        await self._trigger_alert(
                            alert,
                            current_value,
                            f"Portfolio alert: {alert.category} "
                            f"(current: {current_value:.2f}, threshold: {alert.threshold:.2f})",
                        )
            except Exception as e:
                logger.warning(f"AlertEngine: Portfolio check for user {user_id} failed: {e}")

    async def _get_user_daily_stats(self, user_id: int) -> dict:
        """Get today's aggregated PnL stats for a user."""
        from datetime import date
        from sqlalchemy import func, case
        from src.models.database import TradeRecord

        today = date.today()
        async with get_session() as db:
            result = await db.execute(
                select(
                    func.sum(TradeRecord.pnl).label("daily_pnl"),
                    func.count().label("trade_count"),
                ).where(
                    TradeRecord.user_id == user_id,
                    TradeRecord.status == "closed",
                    func.date(TradeRecord.exit_time) == str(today),
                )
            )
            row = result.one()

        daily_pnl = row.daily_pnl or 0
        return {
            "daily_pnl": daily_pnl,
            "daily_pnl_percent": 0,  # Would need balance context
            "max_drawdown": 0,
            "trade_count": row.trade_count or 0,
        }

    async def _trigger_alert(self, alert: Alert, current_value: float, message: str):
        """Trigger an alert: update DB, log history, send notifications."""
        now = datetime.utcnow()

        # Cooldown check
        if alert.last_triggered_at:
            cooldown_end = alert.last_triggered_at + timedelta(minutes=alert.cooldown_minutes)
            if now < cooldown_end:
                return

        async with get_session() as db:
            # Re-fetch alert in this session to update it
            from sqlalchemy import update
            await db.execute(
                update(Alert)
                .where(Alert.id == alert.id)
                .values(
                    last_triggered_at=now,
                    trigger_count=Alert.trigger_count + 1,
                )
            )

            # Record history
            history = AlertHistory(
                alert_id=alert.id,
                triggered_at=now,
                current_value=current_value,
                message=message,
            )
            db.add(history)

        logger.info(f"Alert {alert.id} triggered: {message}")

        # Send notifications
        await self._send_alert_notifications(alert, current_value, message)

        # Broadcast WebSocket event
        try:
            from src.api.websocket.manager import ws_manager
            asyncio.create_task(
                ws_manager.broadcast_to_user(
                    alert.user_id,
                    "alert_triggered",
                    {
                        "alert_id": alert.id,
                        "alert_type": alert.alert_type,
                        "category": alert.category,
                        "symbol": alert.symbol,
                        "current_value": current_value,
                        "message": message,
                    },
                )
            )
        except Exception:
            pass

    async def _send_alert_notifications(
        self, alert: Alert, current_value: float, message: str
    ):
        """Send alert via Discord and Telegram for the bot or user."""
        try:
            from src.models.database import BotConfig
            from src.notifications.discord_notifier import DiscordNotifier
            from src.notifications.telegram_notifier import TelegramNotifier
            from src.utils.encryption import decrypt_value

            # Try bot-specific notifiers first, then skip (no global fallback)
            if not alert.bot_config_id:
                return

            async with get_session() as db:
                result = await db.execute(
                    select(BotConfig).where(BotConfig.id == alert.bot_config_id)
                )
                bot_config = result.scalar_one_or_none()

            if not bot_config:
                return

            # Discord
            if bot_config.discord_webhook_url:
                try:
                    webhook_url = decrypt_value(bot_config.discord_webhook_url)
                    notifier = DiscordNotifier(webhook_url=webhook_url)
                    async with notifier:
                        await notifier.send_alert(
                            alert_type=alert.alert_type,
                            symbol=alert.symbol,
                            current_value=current_value,
                            threshold=alert.threshold,
                            message=message,
                        )
                except Exception as e:
                    logger.warning(f"Discord alert notification failed: {e}")

            # Telegram
            if bot_config.telegram_bot_token and bot_config.telegram_chat_id:
                try:
                    notifier = TelegramNotifier(
                        bot_token=decrypt_value(bot_config.telegram_bot_token),
                        chat_id=bot_config.telegram_chat_id,
                    )
                    await notifier.send_alert(
                        alert_type=alert.alert_type,
                        symbol=alert.symbol,
                        current_value=current_value,
                        threshold=alert.threshold,
                        message=message,
                    )
                except Exception as e:
                    logger.warning(f"Telegram alert notification failed: {e}")

        except Exception as e:
            logger.warning(f"Alert notification dispatch error: {e}")


async def check_strategy_alerts(
    user_id: int,
    bot_config_id: int,
    category: str,
    current_value: float,
    message: str,
):
    """Check and trigger strategy alerts inline from BotWorker.

    Called after signal generation to check for strategy-related alerts like
    signal_missed, low_confidence, consecutive_losses.
    """
    async with get_session() as db:
        result = await db.execute(
            select(Alert).where(
                Alert.user_id == user_id,
                Alert.alert_type == "strategy",
                Alert.is_enabled == True,
                Alert.category == category,
                (Alert.bot_config_id == bot_config_id) | (Alert.bot_config_id.is_(None)),
            )
        )
        alerts = result.scalars().all()

    engine = AlertEngine()
    for alert in alerts:
        should_trigger = False

        if category == "low_confidence":
            should_trigger = current_value <= alert.threshold
        elif category == "consecutive_losses":
            should_trigger = current_value >= alert.threshold
        elif category == "signal_missed":
            should_trigger = True  # Always trigger if alert exists

        if should_trigger:
            await engine._trigger_alert(alert, current_value, message)
