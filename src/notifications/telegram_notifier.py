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
        emoji = "\u25b6\ufe0f" if status == "started" else "\u23f9\ufe0f" if status == "stopped" else "\u2139\ufe0f"
        lines = [
            f"{emoji} <b>Bot {status.title()}</b>",
            "",
            f"Name: <b>{bot_name}</b>",
        ]
        if details:
            lines.append(f"Details: {details}")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_test_message(self) -> bool:
        """Send a test message to verify configuration."""
        return await self._send_message(
            "\u2705 <b>Telegram Notification Test</b>\n\n"
            "Your Telegram notifications are configured correctly!\n"
            f"\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )
