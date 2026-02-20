"""Telegram notification service using Telegram Bot API."""

import logging
import aiohttp
from typing import Optional
from datetime import datetime

from src.notifications.retry import async_retry

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


class TelegramNotifier:
    """Send trade notifications via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._api_url = TELEGRAM_API_BASE.format(token=bot_token)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    @async_retry(max_retries=3)
    async def _send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message via Telegram Bot API."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            async with session.post(
                f"{self._api_url}/sendMessage",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return True
                elif resp.status == 429 or resp.status >= 500:
                    error_text = await resp.text()
                    raise RuntimeError(f"Telegram API error {resp.status}: {error_text}")
                else:
                    error_text = await resp.text()
                    logger.warning("Telegram API error %s: %s", resp.status, error_text)
                    return False

    async def send_trade_entry(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        position_size: float,
        leverage: int = 1,
        strategy: str = "",
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        **kwargs,
    ) -> bool:
        """Send trade entry notification."""
        emoji = "\U0001f7e2" if side.upper() == "LONG" else "\U0001f534"
        lines = [
            f"{emoji} <b>Trade Opened \u2014 {symbol}</b>",
            "",
            f"Direction: <b>{side.upper()}</b>",
            f"Entry: <code>{entry_price}</code>",
            f"Size: <code>{position_size}</code>",
            f"Leverage: <code>{leverage}x</code>",
        ]
        if strategy:
            lines.append(f"Strategy: <code>{strategy}</code>")
        if take_profit:
            lines.append(f"Take Profit: <code>{take_profit}</code>")
        if stop_loss:
            lines.append(f"Stop Loss: <code>{stop_loss}</code>")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_trade_exit(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        pnl_percent: float,
        position_size: float,
        leverage: int = 1,
        strategy: str = "",
        duration: str = "",
        **kwargs,
    ) -> bool:
        """Send trade exit notification."""
        emoji = "\u2705" if pnl >= 0 else "\u274c"
        pnl_sign = "+" if pnl >= 0 else ""
        lines = [
            f"{emoji} <b>Trade Closed \u2014 {symbol}</b>",
            "",
            f"Direction: <b>{side.upper()}</b>",
            f"Entry: <code>{entry_price}</code>",
            f"Exit: <code>{exit_price}</code>",
            f"PnL: <b>{pnl_sign}{pnl:.2f} USDT ({pnl_sign}{pnl_percent:.2f}%)</b>",
            f"Size: <code>{position_size}</code>",
            f"Leverage: <code>{leverage}x</code>",
        ]
        if strategy:
            lines.append(f"Strategy: <code>{strategy}</code>")
        if duration:
            lines.append(f"Duration: <code>{duration}</code>")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_error(self, error_message: str, context: str = "", **kwargs) -> bool:
        """Send error notification."""
        lines = [
            "\u26a0\ufe0f <b>Bot Error</b>",
            "",
            f"<code>{error_message}</code>",
        ]
        if context:
            lines.append(f"\nContext: {context}")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_bot_status(self, bot_name: str, status: str, details: str = "", **kwargs) -> bool:
        """Send bot status change notification."""
        status_lower = status.lower()
        emoji = "\u25b6\ufe0f" if status_lower == "started" else "\u23f9\ufe0f" if status_lower == "stopped" else "\u2139\ufe0f"
        lines = [
            f"{emoji} <b>Bot {status.title()}</b>",
            "",
            f"Name: <b>{bot_name}</b>",
        ]
        if details:
            lines.append(f"Details: {details}")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_alert(
        self,
        alert_type: str,
        symbol: str | None,
        current_value: float,
        threshold: float,
        message: str,
        **kwargs,
    ) -> bool:
        """Send an alert notification."""
        type_emoji = {"price": "\U0001f4b0", "strategy": "\U0001f9e0", "portfolio": "\U0001f4ca"}.get(alert_type, "\U0001f514")
        lines = [
            f"{type_emoji} <b>Alert — {alert_type.upper()}</b>",
            "",
        ]
        if symbol:
            lines.append(f"Symbol: <code>{symbol}</code>")
        lines.extend([
            f"Current: <code>{current_value:,.2f}</code>",
            f"Threshold: <code>{threshold:,.2f}</code>",
            f"\n{message}",
            f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        ])
        return await self._send_message("\n".join(lines))

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
        """Send daily trading summary."""
        net_pnl = total_pnl - total_fees - total_funding
        return_pct = (net_pnl / starting_balance * 100) if starting_balance > 0 else 0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        pnl_emoji = "\U0001f4c8" if net_pnl >= 0 else "\U0001f4c9"
        pnl_sign = "+" if net_pnl >= 0 else ""

        bot_name = kwargs.get("bot_name", "")
        title = f"\U0001f4cb <b>Daily Summary \u2014 {bot_name}</b>" if bot_name else "\U0001f4cb <b>Daily Summary</b>"
        lines = [
            title,
            "",
            f"\U0001f4c5 Date: <b>{date}</b>",
            f"\U0001f4b0 Balance: <code>{starting_balance:,.2f}</code> \u2192 <code>{ending_balance:,.2f}</code>",
            f"\U0001f4ca Trades: <b>{total_trades}</b> (\u2705 {winning_trades} / \u274c {losing_trades})",
            f"\U0001f3af Win Rate: <b>{win_rate:.1f}%</b>",
            f"{pnl_emoji} Net PnL: <b>{pnl_sign}{net_pnl:,.2f} USDT ({pnl_sign}{return_pct:.2f}%)</b>",
            f"\U0001f4b3 Fees: <code>{total_fees:,.2f}</code>",
            f"\U0001f504 Funding: <code>{total_funding:+,.2f}</code>",
            f"\U0001f4c9 Max Drawdown: <code>{max_drawdown:.2f}%</code>",
            f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        ]
        return await self._send_message("\n".join(lines))

    async def send_risk_alert(
        self,
        alert_type: str,
        message: str,
        current_value: Optional[float] = None,
        threshold: Optional[float] = None,
        **kwargs,
    ) -> bool:
        """Send risk alert notification."""
        lines = [
            "\U0001f6a8 <b>Risk Alert</b>",
            "",
            f"Type: <b>{alert_type}</b>",
            f"Message: <code>{message}</code>",
        ]
        if current_value is not None:
            lines.append(f"Current: <code>{current_value:.2f}</code>")
        if threshold is not None:
            lines.append(f"Threshold: <code>{threshold:.2f}</code>")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_test_message(self) -> bool:
        """Send a test message to verify configuration."""
        return await self._send_message(
            "\u2705 <b>Telegram Notification Test</b>\n\n"
            "Your Telegram notifications are configured correctly!\n"
            f"\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )
