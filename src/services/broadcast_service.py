"""
Broadcast Notification Service — core business logic.

Resolves notification targets from bot_configs, renders per-channel messages,
and provides helpers for target summaries and duration estimation.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.broadcast import Broadcast, BroadcastTarget
from src.models.database import BotConfig, User
from src.utils.encryption import decrypt_value
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Rate estimates (seconds per target) for duration estimation
RATE_DISCORD = 2.5
RATE_TELEGRAM = 3.5

# Batch size for processing bot_configs
_BATCH_SIZE = 100


def _sha256(value: str) -> str:
    """Return hex-encoded SHA-256 digest of a string."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------
# resolve_targets
# ------------------------------------------------------------------

async def resolve_targets(
    broadcast_id: int,
    exchange_filter: Optional[str],
    db: AsyncSession,
) -> dict:
    """Discover notification targets from bot_configs and insert into broadcast_targets.

    For each bot_config that has at least one notification channel configured,
    extracts credentials, computes a dedup_key (SHA-256 of decrypted values),
    and inserts a BroadcastTarget row (skipping duplicates via ON CONFLICT).

    Args:
        broadcast_id: The broadcast to resolve targets for.
        exchange_filter: If set, only include bot_configs matching this exchange_type.
        db: Active async database session.

    Returns:
        Dict with ``total`` count and ``by_channel`` breakdown.
    """
    by_channel: dict[str, int] = {"discord": 0, "telegram": 0}

    # Build base query: bot_configs joined to active, non-deleted users
    base_q = (
        select(BotConfig)
        .join(User, BotConfig.user_id == User.id)
        .where(
            and_(
                User.is_active.is_(True),
                User.is_deleted.is_(False),
            )
        )
    )
    if exchange_filter:
        base_q = base_q.where(BotConfig.exchange_type == exchange_filter)

    # Order by id for deterministic batching
    base_q = base_q.order_by(BotConfig.id)

    offset = 0
    while True:
        batch_q = base_q.offset(offset).limit(_BATCH_SIZE)
        result = await db.execute(batch_q)
        configs = result.scalars().all()
        if not configs:
            break

        targets_to_insert: list[dict] = []

        for cfg in configs:
            # --- Discord ---
            if cfg.discord_webhook_url:
                try:
                    decrypted_url = decrypt_value(cfg.discord_webhook_url)
                    dedup = _sha256(decrypted_url)
                    targets_to_insert.append({
                        "broadcast_id": broadcast_id,
                        "channel": "discord",
                        "dedup_key": dedup,
                        "credentials_encrypted": json.dumps({
                            "webhook_url": cfg.discord_webhook_url,
                        }),
                        "user_id": cfg.user_id,
                        "bot_config_id": cfg.id,
                    })
                except Exception as exc:
                    logger.warning("Failed to decrypt Discord creds for bot_config=%s: %s", cfg.id, exc)

            # --- Telegram ---
            if cfg.telegram_bot_token and cfg.telegram_chat_id:
                try:
                    decrypted_token = decrypt_value(cfg.telegram_bot_token)
                    decrypted_chat = decrypt_value(cfg.telegram_chat_id)
                    dedup = _sha256(f"{decrypted_token}:{decrypted_chat}")
                    targets_to_insert.append({
                        "broadcast_id": broadcast_id,
                        "channel": "telegram",
                        "dedup_key": dedup,
                        "credentials_encrypted": json.dumps({
                            "bot_token": cfg.telegram_bot_token,
                            "chat_id": cfg.telegram_chat_id,
                        }),
                        "user_id": cfg.user_id,
                        "bot_config_id": cfg.id,
                    })
                except Exception as exc:
                    logger.warning("Failed to decrypt Telegram creds for bot_config=%s: %s", cfg.id, exc)

        # Bulk upsert (ON CONFLICT DO NOTHING) for this batch
        if targets_to_insert:
            stmt = pg_insert(BroadcastTarget).values(targets_to_insert)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_broadcast_target_dedup",
            )
            await db.execute(stmt)
            await db.flush()

        offset += _BATCH_SIZE

    # Count final targets per channel
    count_q = (
        select(BroadcastTarget.channel, func.count(BroadcastTarget.id))
        .where(BroadcastTarget.broadcast_id == broadcast_id)
        .group_by(BroadcastTarget.channel)
    )
    count_result = await db.execute(count_q)
    for channel, count in count_result.all():
        by_channel[channel] = count

    total = sum(by_channel.values())

    # Update broadcast.total_targets
    broadcast = await db.get(Broadcast, broadcast_id)
    if broadcast:
        broadcast.total_targets = total
        await db.flush()

    logger.info(
        "Resolved %d targets for broadcast=%d (discord=%d, telegram=%d)",
        total, broadcast_id, by_channel["discord"], by_channel["telegram"],
    )

    return {"total": total, "by_channel": by_channel}


# ------------------------------------------------------------------
# render_messages
# ------------------------------------------------------------------

def render_messages(
    title: str,
    message_markdown: str,
    image_url: Optional[str] = None,
) -> dict:
    """Pre-render broadcast content for each notification channel.

    Args:
        title: Broadcast title.
        message_markdown: Body text in Markdown.
        image_url: Optional image URL to attach.

    Returns:
        Dict with keys ``discord``, ``telegram`` containing
        the channel-specific message representation.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # --- Discord embed (JSON string) ---
    embed: dict = {
        "title": title,
        "description": message_markdown,
        "color": 0x0099FF,
        "footer": {"text": "Admin Broadcast"},
        "timestamp": now_iso,
    }
    if image_url:
        embed["image"] = {"url": image_url}
    discord_payload = json.dumps(embed)

    # --- Telegram HTML ---
    telegram_body = _markdown_to_telegram_html(message_markdown)
    telegram_lines = [f"<b>{_escape_html(title)}</b>", "", telegram_body]
    telegram_text = "\n".join(telegram_lines)

    return {
        "discord": discord_payload,
        "telegram": telegram_text,
        "has_image": image_url is not None,
        "image_url": image_url,
    }


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _markdown_to_telegram_html(md: str) -> str:
    """Convert basic Markdown to Telegram-compatible HTML.

    Handles: [text](url) -> <a>, **bold** -> <b>, *italic* -> <i>.
    """
    # Links: [text](url) -> <a href="url">text</a>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', md)
    # Bold: **text** -> <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic: *text* -> <i>text</i> (single asterisks not already consumed)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    return text


# ------------------------------------------------------------------
# get_target_summary
# ------------------------------------------------------------------

async def get_target_summary(broadcast_id: int, db: AsyncSession) -> dict:
    """Query broadcast_targets grouped by channel and status.

    Returns:
        Dict like ``{"discord": {"pending": 5, "sent": 3}, ...}``
    """
    q = (
        select(
            BroadcastTarget.channel,
            BroadcastTarget.status,
            func.count(BroadcastTarget.id),
        )
        .where(BroadcastTarget.broadcast_id == broadcast_id)
        .group_by(BroadcastTarget.channel, BroadcastTarget.status)
    )
    result = await db.execute(q)

    summary: dict = {}
    for channel, status, count in result.all():
        if channel not in summary:
            summary[channel] = {}
        summary[channel][status] = count

    return summary


# ------------------------------------------------------------------
# estimate_duration
# ------------------------------------------------------------------

def estimate_duration(by_channel: dict) -> int:
    """Estimate broadcast duration in seconds based on target counts.

    Channels are sent in parallel, so the estimate is the maximum
    of all individual channel durations.

    Args:
        by_channel: Dict mapping channel name to target count.

    Returns:
        Estimated seconds (rounded up).
    """
    rates = {
        "discord": RATE_DISCORD,
        "telegram": RATE_TELEGRAM,
    }
    max_duration = 0.0
    for channel, count in by_channel.items():
        rate = rates.get(channel, 3.0)
        max_duration = max(max_duration, count * rate)
    return int(max_duration) + 1 if max_duration > 0 else 0
