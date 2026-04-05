"""WhatsApp Business Cloud API notification service using Meta Graph API."""

import logging
import aiohttp
from typing import Optional
from datetime import datetime

from src.notifications.retry import async_retry

logger = logging.getLogger(__name__)

WHATSAPP_API_BASE = "https://graph.facebook.com/v21.0/{phone_number_id}/messages"


class WhatsAppNotifier:
    """Send trade notifications via WhatsApp Business Cloud API."""

    def __init__(self, phone_number_id: str, access_token: str, recipient_number: str):
        """
        Initialize the WhatsApp notifier.

        Args:
            phone_number_id: WhatsApp Business phone number ID from Meta dashboard.
            access_token: Permanent access token for the WhatsApp Business API.
            recipient_number: Recipient phone number in international format (e.g. "491701234567").
        """
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.recipient_number = recipient_number
        self._api_url = WHATSAPP_API_BASE.format(phone_number_id=phone_number_id)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry — create the HTTP session."""
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit — close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _ensure_session(self):
        """Ensure an aiohttp session exists (for usage outside context manager)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                }
            )

    @async_retry(max_retries=3)
    async def _send_message(self, text: str) -> bool:
        """
        Send a plain-text message via the WhatsApp Business Cloud API.

        Args:
            text: The message body (plain text, no HTML).

        Returns:
            True if the message was sent successfully, False otherwise.

        Raises:
            RuntimeError: On rate-limit (429) or server errors (5xx) to trigger retry.
        """
        await self._ensure_session()

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.recipient_number,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text,
            },
        }

        async with self._session.post(
            self._api_url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                logger.info("WhatsApp message sent successfully to %s", self.recipient_number)
                return True
            elif resp.status == 429 or resp.status >= 500:
                error_text = await resp.text()
                raise RuntimeError(f"WhatsApp API error {resp.status}: {error_text}")
            else:
                error_text = await resp.text()
                logger.warning("WhatsApp API error %s: %s", resp.status, error_text)
                return False

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    async def send_trade_entry(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        size: float,
        leverage: int = 1,
        strategy: str = "",
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        confidence: Optional[int] = None,
        reasoning: Optional[str] = None,
        order_id: Optional[str] = None,
        mode: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """Send trade entry notification."""
        emoji = "\U0001f7e2" if side.upper() == "LONG" else "\U0001f534"
        lines = [
            f"{emoji} *Trade Opened -- {symbol}*",
            "",
            f"Direction: {side.upper()}",
            f"Entry: {entry_price}",
            f"Size: {size}",
            f"Leverage: {leverage}x",
        ]
        if strategy:
            lines.append(f"Strategy: {strategy}")
        if take_profit is not None:
            lines.append(f"\U0001f3af Take Profit: {take_profit}")
        if stop_loss is not None:
            lines.append(f"\U0001f6d1 Stop Loss: {stop_loss}")
        if confidence is not None:
            lines.append(f"\U0001f4ca Confidence: {confidence}%")
        if reasoning:
            lines.append(f"\U0001f9e0 Reasoning: {reasoning}")
        if order_id:
            lines.append(f"\U0001f4cb Order ID: {order_id}")
        if mode:
            lines.append(f"\U0001f4a1 Mode: {mode}")
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
        size: float,
        leverage: int = 1,
        duration: str = "",
        fees: float = 0.0,
        funding: float = 0.0,
        mode: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """Send trade exit notification."""
        net_pnl = pnl - fees - funding
        emoji = "\u2705" if net_pnl >= 0 else "\u274c"
        pnl_sign = "+" if pnl >= 0 else ""
        net_sign = "+" if net_pnl >= 0 else ""
        lines = [
            f"{emoji} *Trade Closed -- {symbol}*",
            "",
            f"Direction: {side.upper()}",
            f"Entry: {entry_price}",
            f"Exit: {exit_price}",
            f"PnL: {pnl_sign}{pnl:.2f} USDT ({pnl_sign}{pnl_percent:.2f}%)",
            f"Size: {size}",
            f"Leverage: {leverage}x",
        ]
        if fees:
            lines.append(f"\U0001f4b3 Fees: {fees:.2f} USDT")
        if funding:
            lines.append(f"\U0001f504 Funding: {funding:+.2f} USDT")
        if fees or funding:
            lines.append(f"\U0001f4b0 Net PnL: {net_sign}{net_pnl:.2f} USDT")
        if duration:
            lines.append(f"\u23f1 Duration: {duration}")
        if mode:
            lines.append(f"\U0001f4a1 Mode: {mode}")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_daily_summary(
        self,
        date: str = "",
        starting_balance: float = 0.0,
        ending_balance: float = 0.0,
        total_trades: int = 0,
        winning_trades: int = 0,
        losing_trades: int = 0,
        total_pnl: float = 0.0,
        total_fees: float = 0.0,
        total_funding: float = 0.0,
        max_drawdown: float = 0.0,
        **kwargs,
    ) -> bool:
        """Send daily trading summary."""
        net_pnl = total_pnl - total_fees - total_funding
        return_pct = (net_pnl / starting_balance * 100) if starting_balance > 0 else 0.0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        pnl_emoji = "\U0001f4c8" if net_pnl >= 0 else "\U0001f4c9"
        pnl_sign = "+" if net_pnl >= 0 else ""

        bot_name = kwargs.get("bot_name", "")
        title = f"\U0001f4cb *Daily Summary -- {bot_name}*" if bot_name else "\U0001f4cb *Daily Summary*"
        lines = [
            title,
            "",
            f"\U0001f4c5 Date: {date}",
            f"\U0001f4b0 Balance: {starting_balance:,.2f} -> {ending_balance:,.2f}",
            f"\U0001f4ca Trades: {total_trades} (\u2705 {winning_trades} / \u274c {losing_trades})",
            f"\U0001f3af Win Rate: {win_rate:.1f}%",
            f"{pnl_emoji} Gross PnL: {pnl_sign}{total_pnl:,.2f} USDT",
            f"\U0001f4b3 Fees: {total_fees:,.2f} USDT",
            f"\U0001f504 Funding: {total_funding:+,.2f} USDT",
            f"\U0001f4b0 Net PnL: {pnl_sign}{net_pnl:,.2f} USDT ({pnl_sign}{return_pct:.2f}%)",
            f"\U0001f4c9 Max Drawdown: {max_drawdown:.2f}%",
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
            "\U0001f6a8 *Risk Alert*",
            "",
            f"Type: {alert_type}",
            f"Message: {message}",
        ]
        if current_value is not None:
            lines.append(f"Current: {current_value:.2f}")
        if threshold is not None:
            lines.append(f"Threshold: {threshold:.2f}")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_bot_status(
        self,
        bot_name: str,
        status: str,
        details: str = "",
        **kwargs,
    ) -> bool:
        """Send bot status change notification."""
        status_lower = status.lower()
        if status_lower == "started":
            emoji = "\u25b6\ufe0f"
        elif status_lower == "stopped":
            emoji = "\u23f9\ufe0f"
        else:
            emoji = "\u2139\ufe0f"

        lines = [
            f"{emoji} *Bot {status.title()}*",
            "",
            f"Name: {bot_name}",
        ]
        if details:
            lines.append(f"Details: {details}")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_alert(
        self,
        alert_type: str,
        symbol: Optional[str],
        current_value: float,
        threshold: float,
        message: str,
        **kwargs,
    ) -> bool:
        """Send an alert notification."""
        type_emoji = {
            "price": "\U0001f4b0",
            "strategy": "\U0001f9e0",
            "portfolio": "\U0001f4ca",
        }.get(alert_type, "\U0001f514")

        lines = [
            f"{type_emoji} *Alert -- {alert_type.upper()}*",
            "",
        ]
        if symbol:
            lines.append(f"Symbol: {symbol}")
        lines.extend([
            f"Current: {current_value:,.2f}",
            f"Threshold: {threshold:,.2f}",
            f"\n{message}",
            f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        ])
        return await self._send_message("\n".join(lines))

    async def send_error(
        self,
        error_message: str,
        error_type: str = "",
        context: str = "",
        details: str = "",
        **kwargs,
    ) -> bool:
        """Send error notification."""
        lines = [
            "\u26a0\ufe0f *Bot Error*",
            "",
        ]
        if error_type:
            lines.append(f"Type: {error_type}")
        lines.append(error_message)
        ctx = context or details
        if ctx:
            lines.append(f"\nContext: {ctx}")
        lines.append(f"\n\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        return await self._send_message("\n".join(lines))

    async def send_test_message(self) -> bool:
        """Send a test message to verify WhatsApp configuration."""
        return await self._send_message(
            "\u2705 *WhatsApp Notification Test*\n\n"
            "Your WhatsApp notifications are configured correctly!\n"
            f"\U0001f550 {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        )
