"""
Broadcast Sender — async background send loop.

Sends pre-rendered broadcast messages to all resolved targets,
grouped by channel (Discord, Telegram) with per-channel
rate limiting and concurrency control.
"""

import asyncio
import json
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import select, update, and_

from src.models.broadcast import Broadcast, BroadcastTarget
from src.models.session import get_session
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Telegram API base URL template
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"

# Rate-limit delays between sends (seconds)
DISCORD_DELAY = 2.5
TELEGRAM_DELAY = 3.5

# Max concurrent Telegram bot-token groups
TELEGRAM_MAX_CONCURRENT_GROUPS = 5

# Progress event interval (every N targets)
PROGRESS_INTERVAL = 10

# Retry settings for individual target sends
MAX_RETRIES = 2
RETRY_BASE_DELAY = 1.0

# Module-level rate-limit semaphores (shared across concurrent broadcasts)
_discord_semaphore = asyncio.Semaphore(1)
_telegram_semaphores: dict[str, asyncio.Semaphore] = {}


# ------------------------------------------------------------------
# Main orchestrator
# ------------------------------------------------------------------

async def send_broadcast(broadcast_id: int) -> None:
    """Send a broadcast to all resolved targets.

    Runs as a background task (not inside a FastAPI request).
    Creates its own DB sessions for each operation.
    """
    logger.info("Starting broadcast send: broadcast_id=%d", broadcast_id)

    # Mark broadcast as sending
    async with get_session() as db:
        broadcast = await db.get(Broadcast, broadcast_id)
        if not broadcast:
            logger.error("Broadcast %d not found", broadcast_id)
            return
        broadcast.status = "sending"
        broadcast.started_at = datetime.now(timezone.utc)

    await _send_ws_progress(broadcast_id, "sending", 0, 0, 0)

    # Load targets grouped by channel
    discord_targets: list[dict] = []
    telegram_targets: list[dict] = []

    async with get_session() as db:
        broadcast = await db.get(Broadcast, broadcast_id)
        if not broadcast:
            return

        messages = {
            "discord": broadcast.message_discord,
            "telegram": broadcast.message_telegram,
            "image_url": broadcast.image_url,
        }

        q = select(BroadcastTarget).where(
            and_(
                BroadcastTarget.broadcast_id == broadcast_id,
                BroadcastTarget.status == "pending",
            )
        )
        result = await db.execute(q)
        for target in result.scalars().all():
            target_data = {
                "id": target.id,
                "credentials_encrypted": target.credentials_encrypted,
            }
            if target.channel == "discord":
                discord_targets.append(target_data)
            elif target.channel == "telegram":
                telegram_targets.append(target_data)

    # Launch channel workers in parallel
    workers = []
    if discord_targets:
        workers.append(_send_discord_targets(broadcast_id, discord_targets, messages))
    if telegram_targets:
        workers.append(_send_telegram_targets(broadcast_id, telegram_targets, messages))
    if workers:
        try:
            await asyncio.gather(*workers, return_exceptions=True)
        except asyncio.CancelledError:
            logger.warning("Broadcast %d was cancelled", broadcast_id)

    # Finalize broadcast status
    async with get_session() as db:
        broadcast = await db.get(Broadcast, broadcast_id)
        if broadcast:
            broadcast.completed_at = datetime.now(timezone.utc)
            if broadcast.failed_count > 0 and broadcast.sent_count == 0:
                broadcast.status = "failed"
            else:
                broadcast.status = "completed"
            final_status = broadcast.status
            sent = broadcast.sent_count
            failed = broadcast.failed_count
            total = broadcast.total_targets

    await _send_ws_progress(broadcast_id, final_status, sent, failed, total)
    logger.info(
        "Broadcast %d finished: status=%s sent=%d failed=%d total=%d",
        broadcast_id, final_status, sent, failed, total,
    )


# ------------------------------------------------------------------
# Discord channel worker
# ------------------------------------------------------------------

async def _send_discord_targets(
    broadcast_id: int,
    targets: list[dict],
    messages: dict,
) -> None:
    """Send broadcast to all Discord webhook targets."""
    embed_json = messages.get("discord")
    if not embed_json:
        logger.warning("No Discord message rendered for broadcast %d", broadcast_id)
        return

    embed = json.loads(embed_json)
    payload = {"username": "Trading Bot", "embeds": [embed]}

    async with aiohttp.ClientSession() as session:
        for idx, target in enumerate(targets):
            # Check for cancellation
            if await _is_cancelled(broadcast_id):
                logger.info("Broadcast %d cancelled, stopping Discord worker", broadcast_id)
                return

            target_id = target["id"]
            try:
                creds = json.loads(target["credentials_encrypted"])
                webhook_url = decrypt_value(creds["webhook_url"])
            except Exception as exc:
                await _mark_target_failed(broadcast_id, target_id, f"Decrypt error: {exc}")
                continue

            success = False
            last_error = ""
            for attempt in range(MAX_RETRIES + 1):
                try:
                    async with _discord_semaphore:
                        async with session.post(
                            webhook_url,
                            json=payload,
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            if resp.status == 204:
                                success = True
                                break
                            elif resp.status == 429 or resp.status >= 500:
                                last_error = f"HTTP {resp.status}: {await resp.text()}"
                                if attempt < MAX_RETRIES:
                                    await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                            else:
                                last_error = f"HTTP {resp.status}: {await resp.text()}"
                                break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = str(exc)
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))

            if success:
                await _mark_target_sent(broadcast_id, target_id)
            else:
                await _mark_target_failed(broadcast_id, target_id, last_error)

            # Progress update
            if (idx + 1) % PROGRESS_INTERVAL == 0:
                await _send_ws_progress_from_db(broadcast_id)

            # Rate limiting between sends
            if idx < len(targets) - 1:
                await asyncio.sleep(DISCORD_DELAY)


# ------------------------------------------------------------------
# Telegram channel worker
# ------------------------------------------------------------------

async def _send_telegram_targets(
    broadcast_id: int,
    targets: list[dict],
    messages: dict,
) -> None:
    """Send broadcast to all Telegram targets, grouped by bot_token."""
    telegram_text = messages.get("telegram")
    image_url = messages.get("image_url")
    if not telegram_text:
        logger.warning("No Telegram message rendered for broadcast %d", broadcast_id)
        return

    # Group targets by bot_token for per-token rate limiting
    token_groups: dict[str, list[dict]] = {}
    for target in targets:
        try:
            creds = json.loads(target["credentials_encrypted"])
            decrypted_token = decrypt_value(creds["bot_token"])
            target["_decrypted_token"] = decrypted_token
            target["_decrypted_chat_id"] = decrypt_value(creds["chat_id"])
        except Exception as exc:
            await _mark_target_failed(broadcast_id, target["id"], f"Decrypt error: {exc}")
            continue

        if decrypted_token not in token_groups:
            token_groups[decrypted_token] = []
        token_groups[decrypted_token].append(target)

    # Process token groups with bounded concurrency
    group_semaphore = asyncio.Semaphore(TELEGRAM_MAX_CONCURRENT_GROUPS)

    async def _process_token_group(token: str, group_targets: list[dict]) -> None:
        async with group_semaphore:
            # Get or create per-token semaphore
            if token not in _telegram_semaphores:
                _telegram_semaphores[token] = asyncio.Semaphore(1)
            token_sem = _telegram_semaphores[token]

            api_url = TELEGRAM_API_BASE.format(token=token)

            async with aiohttp.ClientSession() as session:
                for idx, target in enumerate(group_targets):
                    if await _is_cancelled(broadcast_id):
                        return

                    target_id = target["id"]
                    chat_id = target["_decrypted_chat_id"]

                    success = False
                    last_error = ""
                    for attempt in range(MAX_RETRIES + 1):
                        try:
                            async with token_sem:
                                if image_url:
                                    # Use sendPhoto with caption
                                    send_payload = {
                                        "chat_id": chat_id,
                                        "photo": image_url,
                                        "caption": telegram_text,
                                        "parse_mode": "HTML",
                                    }
                                    url = f"{api_url}/sendPhoto"
                                else:
                                    send_payload = {
                                        "chat_id": chat_id,
                                        "text": telegram_text,
                                        "parse_mode": "HTML",
                                    }
                                    url = f"{api_url}/sendMessage"

                                async with session.post(
                                    url,
                                    json=send_payload,
                                    timeout=aiohttp.ClientTimeout(total=10),
                                ) as resp:
                                    if resp.status == 200:
                                        success = True
                                        break
                                    elif resp.status == 429 or resp.status >= 500:
                                        last_error = f"HTTP {resp.status}: {await resp.text()}"
                                        if attempt < MAX_RETRIES:
                                            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                                    else:
                                        last_error = f"HTTP {resp.status}: {await resp.text()}"
                                        break
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            last_error = str(exc)
                            if attempt < MAX_RETRIES:
                                await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))

                    if success:
                        await _mark_target_sent(broadcast_id, target_id)
                    else:
                        await _mark_target_failed(broadcast_id, target_id, last_error)

                    # Rate limiting between sends within same token
                    if idx < len(group_targets) - 1:
                        await asyncio.sleep(TELEGRAM_DELAY)

    group_tasks = [
        _process_token_group(token, group_targets)
        for token, group_targets in token_groups.items()
    ]
    if group_tasks:
        await asyncio.gather(*group_tasks, return_exceptions=True)

    await _send_ws_progress_from_db(broadcast_id)


# ------------------------------------------------------------------
# Helpers: target status updates (each in its own mini-transaction)
# ------------------------------------------------------------------

async def _mark_target_sent(broadcast_id: int, target_id: int) -> None:
    """Mark a single target as sent and increment broadcast.sent_count."""
    try:
        async with get_session() as db:
            target = await db.get(BroadcastTarget, target_id)
            if target:
                target.status = "sent"
                target.sent_at = datetime.now(timezone.utc)

            await db.execute(
                update(Broadcast)
                .where(Broadcast.id == broadcast_id)
                .values(sent_count=Broadcast.sent_count + 1)
            )
    except Exception as exc:
        logger.error("Failed to mark target %d as sent: %s", target_id, exc)


async def _mark_target_failed(broadcast_id: int, target_id: int, error_msg: str) -> None:
    """Mark a single target as failed and increment broadcast.failed_count."""
    try:
        async with get_session() as db:
            target = await db.get(BroadcastTarget, target_id)
            if target:
                target.status = "failed"
                target.error_message = error_msg[:1000]

            await db.execute(
                update(Broadcast)
                .where(Broadcast.id == broadcast_id)
                .values(failed_count=Broadcast.failed_count + 1)
            )
    except Exception as exc:
        logger.error("Failed to mark target %d as failed: %s", target_id, exc)


async def _is_cancelled(broadcast_id: int) -> bool:
    """Check if the broadcast has been cancelled by an admin."""
    try:
        async with get_session() as db:
            broadcast = await db.get(Broadcast, broadcast_id)
            return broadcast is not None and broadcast.status == "cancelled"
    except Exception:
        return False


# ------------------------------------------------------------------
# WebSocket progress events
# ------------------------------------------------------------------

async def _send_ws_progress(
    broadcast_id: int,
    status: str,
    sent: int,
    failed: int,
    total: int,
) -> None:
    """Push a broadcast progress event to all admin WebSocket clients."""
    try:
        from src.api.websocket.manager import ws_manager
        await ws_manager.broadcast_all("broadcast_progress", {
            "broadcast_id": broadcast_id,
            "status": status,
            "sent": sent,
            "failed": failed,
            "total": total,
        })
    except Exception as exc:
        logger.debug("WS progress send failed (non-critical): %s", exc)


async def _send_ws_progress_from_db(broadcast_id: int) -> None:
    """Read current counts from DB and push a WS progress event."""
    try:
        async with get_session() as db:
            broadcast = await db.get(Broadcast, broadcast_id)
            if broadcast:
                await _send_ws_progress(
                    broadcast_id,
                    broadcast.status,
                    broadcast.sent_count,
                    broadcast.failed_count,
                    broadcast.total_targets,
                )
    except Exception as exc:
        logger.debug("WS progress DB read failed (non-critical): %s", exc)
