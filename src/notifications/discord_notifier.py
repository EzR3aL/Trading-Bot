"""
Discord Notification System for the Bitget Trading Bot.

Sends formatted trade notifications to a Discord channel including:
- Trade entries with asset, direction, size, entry price
- Trade exits with PnL, ROI%, fees, funding
- Daily summaries
- Risk alerts
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any

import aiohttp

from src.notifications.retry import async_retry
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DiscordNotifier:
    """
    Discord notification handler using webhooks.

    Sends formatted embed messages with trade information.
    """

    # Colors for embeds
    COLOR_LONG = 0x00FF00  # Green for long positions
    COLOR_SHORT = 0xFF0000  # Red for short positions
    COLOR_PROFIT = 0x00FF00  # Green for profit
    COLOR_LOSS = 0xFF0000  # Red for loss
    COLOR_INFO = 0x0099FF  # Blue for info
    COLOR_WARNING = 0xFFCC00  # Yellow for warnings
    COLOR_ERROR = 0xFF0000  # Red for errors
    COLOR_ALERT = 0xFF6600  # Orange for alerts

    def __init__(self, webhook_url: Optional[str] = None):
        """
        Initialize the Discord notifier.

        Args:
            webhook_url: Per-bot Discord webhook URL (required)
        """
        self.webhook_url = webhook_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self):
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @async_retry(max_retries=3)
    async def _send_webhook(self, payload: Dict[str, Any]) -> bool:
        """
        Send a message via Discord webhook.

        Args:
            payload: Discord webhook payload

        Returns:
            True if sent successfully
        """
        if not self.webhook_url:
            raise RuntimeError("Discord webhook URL not configured")

        await self._ensure_session()

        async with self._session.post(
            self.webhook_url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status in (200, 204):
                logger.info("Discord notification sent successfully")
                return True
            error_text = await response.text()
            if response.status == 429 or response.status >= 500:
                # Retriable errors
                raise RuntimeError(f"Discord webhook error {response.status}: {error_text}")
            # Client errors (400, 401, 403, 404) — permanent failures
            logger.error("Discord webhook error: %s - %s", response.status, error_text)
            raise RuntimeError(f"Discord webhook error {response.status}: {error_text}")

    def _create_embed(
        self,
        title: str,
        description: str,
        color: int,
        fields: list,
        footer: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a Discord embed object.

        Args:
            title: Embed title
            description: Embed description
            color: Embed color
            fields: List of field dictionaries
            footer: Optional footer text
            thumbnail_url: Optional thumbnail image URL

        Returns:
            Discord embed dictionary
        """
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if footer:
            embed["footer"] = {"text": footer}

        if thumbnail_url:
            embed["thumbnail"] = {"url": thumbnail_url}

        return embed

    async def send_trade_entry(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        leverage: int,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        confidence: int = 0,
        reason: str = "",
        order_id: str = "",
        demo_mode: Optional[bool] = None,
        **kwargs,
    ) -> bool:
        """
        Send a trade entry notification.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: long or short
            size: Position size in base currency
            entry_price: Entry price
            leverage: Leverage used
            take_profit: Take profit price
            stop_loss: Stop loss price
            confidence: Strategy confidence (0-100)
            reason: Trade reasoning
            order_id: Exchange order ID
            demo_mode: If True, mark as DEMO; if False, mark as LIVE; if None, use settings

        Returns:
            True if sent successfully
        """
        # Import here to avoid circular dependency
        from config import settings

        # Determine trading mode
        if demo_mode is None:
            demo_mode = settings.is_demo_mode

        mode_label = "🧪 DEMO" if demo_mode else "⚡ LIVE"
        mode_badge = "DEMO" if demo_mode else "LIVE"

        # Determine direction emoji and color
        if side.lower() == "long":
            emoji = "📈"
            direction = "LONG"
            color = self.COLOR_LONG
        else:
            emoji = "📉"
            direction = "SHORT"
            color = self.COLOR_SHORT

        # Calculate position value
        position_value = size * entry_price

        # Create fields (mode as first field for visibility)
        fields = [
            {"name": "🔸 Mode", "value": f"**`{mode_badge}`**", "inline": True},
            {"name": "📊 Asset", "value": f"`{symbol}`", "inline": True},
            {"name": "📍 Direction", "value": f"`{direction}`", "inline": True},
            {"name": "💰 Entry Price", "value": f"`${entry_price:,.2f}`", "inline": True},
            {"name": "📦 Size", "value": f"`{size:.6f}`", "inline": True},
            {"name": "⚡ Leverage", "value": f"`{leverage}x`", "inline": True},
            {"name": "💵 Value", "value": f"`${position_value:,.2f}`", "inline": True},
            {"name": "🎯 Take Profit", "value": f"`${take_profit:,.2f}`" if take_profit is not None else "`—`", "inline": True},
            {"name": "🛑 Stop Loss", "value": f"`${stop_loss:,.2f}`" if stop_loss is not None else "`—`", "inline": True},
            {"name": "📊 Confidence", "value": f"`{confidence}%`", "inline": True},
            {"name": "📝 Reasoning", "value": f"```{reason[:500]}```", "inline": False},
        ]

        embed = self._create_embed(
            title=f"{emoji} {mode_label} - NEW TRADE OPENED - {direction} {symbol}",
            description=f"A new **{direction}** position has been opened on **{symbol}** in **{mode_badge} mode**",
            color=color,
            fields=fields,
            footer=f"Order ID: {order_id} | Mode: {mode_badge}",
        )

        payload = {
            "username": "Bitget Trading Bot",
            "embeds": [embed],
        }

        return await self._send_webhook(payload)

    async def send_trade_exit(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        exit_price: float,
        pnl: float,
        pnl_percent: float,
        fees: float,
        funding_paid: float,
        reason: str,
        order_id: str,
        duration_minutes: Optional[int] = None,
        demo_mode: Optional[bool] = None,
        strategy_reason: Optional[str] = None,
    ) -> bool:
        """
        Send a trade exit notification.

        Args:
            symbol: Trading pair
            side: long or short
            size: Position size
            entry_price: Entry price
            exit_price: Exit price
            pnl: Absolute PnL
            pnl_percent: PnL percentage
            fees: Trading fees
            funding_paid: Funding payments
            reason: Exit reason
            order_id: Exchange order ID
            duration_minutes: Trade duration in minutes
            demo_mode: If True, mark as DEMO; if False, mark as LIVE; if None, use settings

        Returns:
            True if sent successfully
        """
        # Import here to avoid circular dependency
        from config import settings

        # Determine trading mode
        if demo_mode is None:
            demo_mode = settings.is_demo_mode

        mode_label = "🧪 DEMO" if demo_mode else "⚡ LIVE"
        mode_badge = "DEMO" if demo_mode else "LIVE"

        # Determine if profit or loss
        # funding_paid: positive = paid (reduces profit), negative = received (increases profit)
        net_pnl = pnl - fees - funding_paid

        if net_pnl >= 0:
            emoji = "✅"
            result = "PROFIT"
            color = self.COLOR_PROFIT
        else:
            emoji = "❌"
            result = "LOSS"
            color = self.COLOR_LOSS

        # Direction emoji
        _direction_emoji = "📈" if side.lower() == "long" else "📉"

        fields = [
            {"name": "🔸 Mode", "value": f"**`{mode_badge}`**", "inline": True},
            {"name": "📊 Asset", "value": f"`{symbol}`", "inline": True},
            {"name": "📍 Direction", "value": f"`{side.upper()}`", "inline": True},
            {"name": "💰 Entry Price", "value": f"`${entry_price:,.2f}`", "inline": True},
            {"name": "💸 Exit Price", "value": f"`${exit_price:,.2f}`", "inline": True},
            {"name": "📈 Price Change", "value": f"`{((exit_price - entry_price) / entry_price * 100):+.2f}%`", "inline": True},
            {"name": "📦 Size", "value": f"`{size:.6f}`", "inline": True},
            {"name": "💵 Gross PnL", "value": f"`${pnl:+,.2f}`", "inline": True},
            {"name": "📊 ROI", "value": f"`{pnl_percent:+.2f}%`", "inline": True},
            {"name": "💳 Fees", "value": f"`${fees:.2f}`", "inline": True},
            {"name": "🔄 Funding", "value": f"`${funding_paid:+.2f}`", "inline": True},
            {"name": f"{emoji} Net PnL", "value": f"**`${net_pnl:+,.2f}`**", "inline": True},
            {"name": "📝 Exit Reason", "value": f"`{reason}`", "inline": True},
        ]

        if duration_minutes:
            hours = duration_minutes // 60
            mins = duration_minutes % 60
            duration_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
            fields.append({"name": "⏱️ Duration", "value": f"`{duration_str}`", "inline": True})

        if strategy_reason:
            fields.append({"name": "🧠 Strategy Decision", "value": f"```{strategy_reason[:500]}```", "inline": False})

        embed = self._create_embed(
            title=f"{emoji} {mode_label} - TRADE CLOSED - {result} on {symbol}",
            description=f"**{side.upper()}** position on **{symbol}** has been closed with a **{result}** in **{mode_badge} mode**",
            color=color,
            fields=fields,
            footer=f"Order ID: {order_id} | Mode: {mode_badge}",
        )

        payload = {
            "username": "Bitget Trading Bot",
            "embeds": [embed],
        }

        return await self._send_webhook(payload)

    async def send_daily_summary(
        self,
        date: str,
        starting_balance: float,
        ending_balance: float,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        total_pnl: float,
        total_fees: float,
        total_funding: float,
        max_drawdown: float,
        **kwargs,
    ) -> bool:
        """
        Send a daily trading summary.

        Args:
            date: Date of the summary
            starting_balance: Balance at start of day
            ending_balance: Balance at end of day
            total_trades: Number of trades executed
            winning_trades: Number of winning trades
            losing_trades: Number of losing trades
            total_pnl: Total PnL
            total_fees: Total fees paid
            total_funding: Total funding paid
            max_drawdown: Maximum drawdown percentage

        Returns:
            True if sent successfully
        """
        # total_funding: positive = paid (reduces profit), negative = received (increases profit)
        net_pnl = total_pnl - total_fees - total_funding
        return_pct = (net_pnl / starting_balance) * 100 if starting_balance > 0 else 0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        # Determine overall color
        color = self.COLOR_PROFIT if net_pnl >= 0 else self.COLOR_LOSS
        emoji = "📈" if net_pnl >= 0 else "📉"

        fields = [
            {"name": "📅 Date", "value": f"`{date}`", "inline": True},
            {"name": "📊 Total Trades", "value": f"`{total_trades}`", "inline": True},
            {"name": "✅ Wins / ❌ Losses", "value": f"`{winning_trades} / {losing_trades}`", "inline": True},
            {"name": "🎯 Win Rate", "value": f"`{win_rate:.1f}%`", "inline": True},
            {"name": "💰 Starting Balance", "value": f"`${starting_balance:,.2f}`", "inline": True},
            {"name": "💵 Ending Balance", "value": f"`${ending_balance:,.2f}`", "inline": True},
            {"name": "📈 Gross PnL", "value": f"`${total_pnl:+,.2f}`", "inline": True},
            {"name": "💳 Total Fees", "value": f"`${total_fees:.2f}`", "inline": True},
            {"name": "🔄 Total Funding", "value": f"`${total_funding:+.2f}`", "inline": True},
            {"name": f"{emoji} Net PnL", "value": f"**`${net_pnl:+,.2f}`**", "inline": True},
            {"name": "📊 Daily Return", "value": f"**`{return_pct:+.2f}%`**", "inline": True},
            {"name": "📉 Max Drawdown", "value": f"`{max_drawdown:.2f}%`", "inline": True},
        ]

        embed = self._create_embed(
            title=f"📋 DAILY TRADING SUMMARY - {date}",
            description=f"Daily performance report for **{date}**",
            color=color,
            fields=fields,
            footer="Bitget Trading Bot - Contrarian Liquidation Hunter",
        )

        payload = {
            "username": "Bitget Trading Bot",
            "embeds": [embed],
        }

        return await self._send_webhook(payload)

    async def send_risk_alert(
        self,
        alert_type: str,
        message: str,
        current_value: Optional[float] = None,
        threshold: Optional[float] = None,
        is_fatal: bool = False,
    ) -> bool:
        """
        Send a risk alert notification.

        Args:
            alert_type: Type of alert (e.g., "DAILY_LOSS_LIMIT", "MAX_TRADES")
            message: Alert message
            current_value: Current value that triggered the alert
            threshold: Threshold that was exceeded
            is_fatal: If True, the bot has been paused and requires user action

        Returns:
            True if sent successfully
        """
        fields = [
            {"name": "⚠️ Alert Type", "value": f"`{alert_type}`", "inline": False},
            {"name": "📝 Message", "value": f"```{message[:500]}```", "inline": False},
        ]

        if current_value is not None:
            fields.append({"name": "📊 Current Value", "value": f"`{current_value:.2f}`", "inline": True})

        if threshold is not None:
            fields.append({"name": "🎯 Threshold", "value": f"`{threshold:.2f}`", "inline": True})

        if is_fatal:
            footer = "Bot wurde gestoppt — bitte Konfiguration prüfen und Bot neu starten"
        elif alert_type in ("DAILY_LOSS_LIMIT", "MAX_TRADES", "CONSECUTIVE_ERRORS"):
            footer = "Trading has been paused for safety"
        else:
            footer = "Bot versucht es beim nächsten Zyklus erneut"

        embed = self._create_embed(
            title="🚨 RISK ALERT",
            description="A risk management alert has been triggered",
            color=self.COLOR_WARNING,
            fields=fields,
            footer=footer,
        )

        payload = {
            "username": "Bitget Trading Bot",
            "embeds": [embed],
        }

        return await self._send_webhook(payload)

    async def send_signal_alert(
        self,
        symbol: str,
        direction: str,
        confidence: int,
        reason: str,
        entry_price: float,
        target_price: float,
        stop_loss: float,
        metrics: Dict[str, Any],
    ) -> bool:
        """
        Send a trading signal alert (before execution).

        Args:
            symbol: Trading pair
            direction: long or short
            confidence: Strategy confidence
            reason: Signal reasoning
            entry_price: Suggested entry price
            target_price: Target price
            stop_loss: Stop loss price
            metrics: Market metrics snapshot

        Returns:
            True if sent successfully
        """
        emoji = "📈" if direction.lower() == "long" else "📉"
        color = self.COLOR_LONG if direction.lower() == "long" else self.COLOR_SHORT

        fields = [
            {"name": "📊 Asset", "value": f"`{symbol}`", "inline": True},
            {"name": "📍 Signal", "value": f"`{direction.upper()}`", "inline": True},
            {"name": "📊 Confidence", "value": f"`{confidence}%`", "inline": True},
            {"name": "💰 Entry Price", "value": f"`${entry_price:,.2f}`", "inline": True},
            {"name": "🎯 Target", "value": f"`${target_price:,.2f}`", "inline": True},
            {"name": "🛑 Stop Loss", "value": f"`${stop_loss:,.2f}`", "inline": True},
            {"name": "😱 Fear & Greed", "value": f"`{metrics.get('fear_greed_index', 'N/A')}`", "inline": True},
            {"name": "📊 L/S Ratio", "value": f"`{metrics.get('long_short_ratio', 'N/A'):.2f}`", "inline": True},
            {"name": "💸 Funding Rate", "value": f"`{metrics.get('funding_rate_btc', 0) * 100:.4f}%`", "inline": True},
            {"name": "📝 Analysis", "value": f"```{reason[:800]}```", "inline": False},
        ]

        embed = self._create_embed(
            title=f"{emoji} TRADING SIGNAL - {direction.upper()} {symbol}",
            description=f"New **{direction.upper()}** signal generated with **{confidence}%** confidence",
            color=color,
            fields=fields,
            footer="Signal generated by Contrarian Liquidation Hunter Strategy",
        )

        payload = {
            "username": "Bitget Trading Bot",
            "embeds": [embed],
        }

        return await self._send_webhook(payload)

    async def send_error(self, error_type: str, error_message: str, details: Optional[str] = None, **kwargs) -> bool:
        """
        Send an error notification.

        Args:
            error_type: Type of error
            error_message: Error message
            details: Additional details

        Returns:
            True if sent successfully
        """
        fields = [
            {"name": "❌ Error Type", "value": f"`{error_type}`", "inline": False},
            {"name": "📝 Message", "value": f"```{error_message[:500]}```", "inline": False},
        ]

        if details:
            fields.append({"name": "📋 Details", "value": f"```{details[:500]}```", "inline": False})

        embed = self._create_embed(
            title="❌ BOT ERROR",
            description="An error occurred in the trading bot",
            color=self.COLOR_ERROR,
            fields=fields,
            footer="Please check the logs for more information",
        )

        payload = {
            "username": "Bitget Trading Bot",
            "embeds": [embed],
        }

        return await self._send_webhook(payload)

    async def send_alert(
        self,
        alert_type: str,
        symbol: Optional[str],
        current_value: float,
        threshold: float,
        message: str,
    ) -> bool:
        """
        Send an alert notification.

        Args:
            alert_type: Type of alert (price, strategy, portfolio)
            symbol: Trading pair (for price alerts)
            current_value: Value that triggered the alert
            threshold: Configured threshold
            message: Alert message

        Returns:
            True if sent successfully
        """
        type_emoji = {"price": "💰", "strategy": "🧠", "portfolio": "📊"}.get(alert_type, "🔔")

        fields = [
            {"name": "🔔 Alert Type", "value": f"`{alert_type.upper()}`", "inline": True},
        ]
        if symbol:
            fields.append({"name": "📊 Symbol", "value": f"`{symbol}`", "inline": True})
        fields.extend([
            {"name": "📈 Current Value", "value": f"`{current_value:,.2f}`", "inline": True},
            {"name": "🎯 Threshold", "value": f"`{threshold:,.2f}`", "inline": True},
            {"name": "📝 Details", "value": f"```{message[:500]}```", "inline": False},
        ])

        embed = self._create_embed(
            title=f"{type_emoji} ALERT TRIGGERED — {alert_type.upper()}",
            description=message[:200],
            color=self.COLOR_ALERT,
            fields=fields,
            footer="Trading Bot Alert System",
        )

        payload = {
            "username": "Bitget Trading Bot",
            "embeds": [embed],
        }

        return await self._send_webhook(payload)

    async def send_bot_status(self, status: str, message: str, stats: Optional[Dict] = None, bot_name: str = "", **kwargs) -> bool:
        """
        Send a bot status update.

        Args:
            status: Status type (STARTED, STOPPED, PAUSED, etc.)
            message: Status message
            stats: Optional statistics to include

        Returns:
            True if sent successfully
        """
        emoji_map = {
            "STARTED": "🟢",
            "STOPPED": "🔴",
            "PAUSED": "🟡",
            "RESUMED": "🟢",
            "ERROR": "❌",
        }

        emoji = emoji_map.get(status, "ℹ️")
        color = self.COLOR_INFO

        fields = [
            {"name": "📊 Status", "value": f"`{status}`", "inline": True},
            {"name": "📝 Message", "value": f"{message}", "inline": False},
        ]

        if stats:
            for key, value in stats.items():
                fields.append({"name": f"📈 {key}", "value": f"`{value}`", "inline": True})

        title_suffix = f" — {bot_name}" if bot_name else ""
        embed = self._create_embed(
            title=f"{emoji} BOT STATUS UPDATE{title_suffix}",
            description=f"Trading bot status: **{status}**",
            color=color,
            fields=fields,
            footer=f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        )

        payload = {
            "username": "Bitget Trading Bot",
            "embeds": [embed],
        }

        return await self._send_webhook(payload)
