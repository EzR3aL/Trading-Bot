"""Telegram long-polling service for interactive bot commands.

Polls Telegram's getUpdates API for incoming messages, routes commands
to handlers, and sends responses. Runs as a background asyncio task.
"""

import asyncio
from collections import defaultdict

import aiohttp
from sqlalchemy import select

from src.models.database import BotConfig
from src.models.session import get_session
from src.telegram.commands import COMMANDS, handle_command
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"
POLL_INTERVAL = 3  # seconds between polls when idle
POLL_TIMEOUT = 30  # long-poll timeout (Telegram holds connection)
REFRESH_INTERVAL = 300  # refresh token→chat mappings every 5 min


class TelegramPoller:
    """Background service that polls Telegram for user commands."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        # {bot_token: {chat_id: user_id}}
        self._token_map: dict[str, dict[str, int]] = {}
        # {bot_token: last_update_id}
        self._offsets: dict[str, int] = defaultdict(int)
        self._commands_registered: set[str] = set()
        self._running = False

    async def start(self):
        """Start the polling background task."""
        if self._task and not self._task.done():
            return
        self._running = True
        await self._refresh_token_map()
        if not self._token_map:
            logger.info("TelegramPoller: No Telegram bots configured, skipping start")
            return
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "TelegramPoller: Started with %d token(s), %d chat(s)",
            len(self._token_map),
            sum(len(chats) for chats in self._token_map.values()),
        )

    async def stop(self):
        """Stop the polling background task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TelegramPoller: Stopped")

    async def _refresh_token_map(self):
        """Load all unique telegram bot_token → chat_id → user_id mappings from DB."""
        try:
            async with get_session() as db:
                result = await db.execute(
                    select(
                        BotConfig.telegram_bot_token,
                        BotConfig.telegram_chat_id,
                        BotConfig.user_id,
                    ).where(
                        BotConfig.telegram_bot_token.isnot(None),
                        BotConfig.telegram_chat_id.isnot(None),
                    )
                )
                rows = result.all()

            new_map: dict[str, dict[str, int]] = {}
            for enc_token, enc_chat_id, user_id in rows:
                try:
                    token = decrypt_value(enc_token)
                    chat_id = decrypt_value(enc_chat_id)
                except Exception:
                    continue
                if token not in new_map:
                    new_map[token] = {}
                new_map[token][chat_id] = user_id

            self._token_map = new_map
        except Exception as e:
            logger.warning("TelegramPoller: Failed to refresh token map: %s", e)

    async def _register_commands(self, token: str):
        """Register bot commands with Telegram so they appear in the menu."""
        if token in self._commands_registered:
            return
        url = f"{TELEGRAM_API.format(token=token)}/setMyCommands"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={"commands": COMMANDS},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        self._commands_registered.add(token)
                        logger.info("TelegramPoller: Commands registered for token ...%s", token[-6:])
                    else:
                        text = await resp.text()
                        logger.warning("TelegramPoller: setMyCommands failed: %s", text)
        except Exception as e:
            logger.warning("TelegramPoller: setMyCommands error: %s", e)

    async def _poll_loop(self):
        """Main polling loop — runs until stopped."""
        cycle = 0
        while self._running:
            try:
                # Refresh mappings periodically
                if cycle % (REFRESH_INTERVAL // POLL_INTERVAL) == 0 and cycle > 0:
                    await self._refresh_token_map()

                for token, chat_map in self._token_map.items():
                    await self._register_commands(token)
                    await self._poll_token(token, chat_map)

                cycle += 1
                await asyncio.sleep(POLL_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("TelegramPoller: Poll loop error: %s", e)
                await asyncio.sleep(POLL_INTERVAL * 3)

    async def _poll_token(self, token: str, chat_map: dict[str, int]):
        """Poll updates for a single bot token."""
        url = f"{TELEGRAM_API.format(token=token)}/getUpdates"
        params = {
            "offset": self._offsets[token],
            "timeout": 1,  # short timeout to not block other tokens
            "allowed_updates": ["message"],
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()

            if not data.get("ok") or not data.get("result"):
                return

            for update in data["result"]:
                self._offsets[token] = update["update_id"] + 1
                await self._handle_update(token, update, chat_map)

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.debug("TelegramPoller: Poll error for ...%s: %s", token[-6:], e)

    async def _handle_update(self, token: str, update: dict, chat_map: dict[str, int]):
        """Process a single Telegram update."""
        message = update.get("message")
        if not message or not message.get("text"):
            return

        chat_id = str(message["chat"]["id"])
        text = message["text"].strip()

        # Only respond to known chat IDs
        user_id = chat_map.get(chat_id)
        if user_id is None:
            return

        # Parse command (handle /command@botname format)
        if not text.startswith("/"):
            return
        parts = text.split(maxsplit=1)
        command = parts[0].split("@")[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        logger.info(
            "TelegramPoller: Command '%s' from user %d (chat %s)",
            command, user_id, chat_id,
        )

        try:
            response = await handle_command(command, user_id, args)
        except Exception as e:
            logger.error("TelegramPoller: Command handler error: %s", e)
            response = "Ein Fehler ist aufgetreten. Bitte versuche es erneut."

        # Send response
        await self._send_response(token, chat_id, response)

    async def _send_response(self, token: str, chat_id: str, text: str):
        """Send a response message to a Telegram chat."""
        url = f"{TELEGRAM_API.format(token=token)}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        error = await resp.text()
                        logger.warning("TelegramPoller: Send failed: %s", error)
        except Exception as e:
            logger.warning("TelegramPoller: Send error: %s", e)
