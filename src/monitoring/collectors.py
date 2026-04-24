"""
Background metric collectors.

Periodically samples bot orchestrator state, process memory,
and disk usage, updating Prometheus gauges.
"""

import asyncio
import os
import shutil
from datetime import datetime, timezone

import aiohttp

from src.monitoring.metrics import (
    BOTS_BY_STATUS,
    BOTS_RUNNING,
    BOT_CONSECUTIVE_ERRORS,
    DISK_USAGE_PERCENT,
    PROCESS_MEMORY_BYTES,
)
from src.observability.metrics import (
    BOT_DAILY_PNL as OBS_BOT_DAILY_PNL,
    BOT_OPEN_POSITIONS as OBS_BOT_OPEN_POSITIONS,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLLECT_INTERVAL_SECONDS = 15

# Disk usage alert state
_disk_alert_sent = False
_DISK_ALERT_THRESHOLD = 90  # percent


async def _send_disk_alert(usage_percent: float) -> None:
    """Send a disk-full warning to Discord via webhook (fire-and-forget)."""
    webhook_url = os.getenv("DISK_ALERT_WEBHOOK", "")
    if not webhook_url:
        logger.warning("DISK_ALERT_WEBHOOK not configured — skipping disk alert")
        return

    embed = {
        "title": "\u26a0\ufe0f DISK USAGE ALERT",
        "description": "Disk usage has exceeded the configured threshold.",
        "color": 0xFF6600,  # Orange
        "fields": [
            {"name": "Usage", "value": f"`{usage_percent:.1f}%`", "inline": True},
            {"name": "Threshold", "value": f"`{_DISK_ALERT_THRESHOLD}%`", "inline": True},
            {"name": "Data Dir", "value": f"`{os.getenv('DATA_DIR', 'data')}`", "inline": True},
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Edge Bots Monitoring"},
    }

    payload = {"username": "Edge Bots Monitor", "embeds": [embed]}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status in (200, 204):
                    logger.info("Disk alert sent to Discord (%.1f%%)", usage_percent)
                else:
                    text = await resp.text()
                    logger.warning("Disk alert webhook returned %s: %s", resp.status, text)
    except Exception:
        logger.warning("Failed to send disk alert to Discord", exc_info=True)


async def _collect_observability_bot_gauges(workers: dict) -> None:
    """Update the per-bot gauges on the observability registry (#327 PR-3).

    Samples two facts per bot per tick:

    * ``bot_open_positions{bot_id, exchange}`` — count of ``TradeRecord``
      rows with ``status="open"`` for that bot. Pulled from the DB so the
      gauge reflects the ground truth shared with the rest of the app.
    * ``bot_daily_pnl{bot_id, exchange}`` — ``DailyStats.net_pnl`` from
      the worker's own ``RiskManager``, which is already updated on every
      trade exit.

    Failures are logged at debug level and never raised — the collector
    loop must survive a single broken worker.
    """
    from sqlalchemy import func, select

    from src.models.database import TradeRecord
    from src.models.session import get_session

    for bot_id, worker in workers.items():
        try:
            cfg = getattr(worker, "_config", None)
            exchange_label = (
                getattr(cfg, "exchange_type", None) or "unknown"
            )

            try:
                async with get_session() as session:
                    result = await session.execute(
                        select(func.count(TradeRecord.id)).where(
                            TradeRecord.bot_config_id == bot_id,
                            TradeRecord.status == "open",
                        )
                    )
                    open_positions = int(result.scalar_one() or 0)
            except Exception:
                open_positions = 0

            OBS_BOT_OPEN_POSITIONS.labels(
                bot_id=str(bot_id), exchange=exchange_label,
            ).set(open_positions)

            daily_pnl = 0.0
            rsm = getattr(worker, "_risk_manager", None)
            if rsm is not None and hasattr(rsm, "get_daily_stats"):
                try:
                    stats = rsm.get_daily_stats()
                    if stats is not None:
                        daily_pnl = float(getattr(stats, "net_pnl", 0.0) or 0.0)
                except Exception:
                    daily_pnl = 0.0

            OBS_BOT_DAILY_PNL.labels(
                bot_id=str(bot_id), exchange=exchange_label,
            ).set(daily_pnl)
        except Exception:
            logger.debug(
                "observability gauge update failed for bot %s",
                bot_id, exc_info=True,
            )


async def collect_bot_metrics(app) -> None:
    """Periodically update bot gauge metrics from orchestrator state."""
    while True:
        try:
            orch = getattr(app.state, "orchestrator", None)
            if orch:
                workers = orch._workers

                # Total running bots
                BOTS_RUNNING.set(
                    sum(1 for w in workers.values() if w.status == "running")
                )

                # Count by status
                status_counts: dict[str, int] = {}
                for w in workers.values():
                    status_counts[w.status] = status_counts.get(w.status, 0) + 1
                for status, count in status_counts.items():
                    BOTS_BY_STATUS.labels(status).set(count)

                # Per-bot error gauge
                for bot_id, w in workers.items():
                    BOT_CONSECUTIVE_ERRORS.labels(str(bot_id)).set(
                        getattr(w, "_consecutive_errors", 0)
                    )

                # Observability registry (#327 PR-3): per-bot open position
                # count + current-day realised PnL. Open count comes from DB
                # (TradeRecord, status=open), PnL from the worker's own
                # ``_risk_manager.get_daily_stats()`` which already tracks it.
                # Wrapped so a single broken worker doesn't starve the whole
                # cycle.
                await _collect_observability_bot_gauges(workers)

            # Process memory (cross-platform)
            try:
                import resource
                rusage = resource.getrusage(resource.RUSAGE_SELF)
                PROCESS_MEMORY_BYTES.set(rusage.ru_maxrss * 1024)
            except (ImportError, AttributeError):
                # Windows fallback
                try:
                    import ctypes
                    ctypes.windll.kernel32  # type: ignore[attr-defined]  # noqa: B018
                except Exception:
                    pass

            # Disk usage for data directory
            try:
                global _disk_alert_sent
                data_dir = os.getenv("DATA_DIR", "data")
                usage = shutil.disk_usage(data_dir)
                usage_percent = (usage.used / usage.total) * 100
                DISK_USAGE_PERCENT.set(usage_percent)

                if usage_percent > _DISK_ALERT_THRESHOLD and not _disk_alert_sent:
                    _disk_alert_sent = True
                    # Fire-and-forget alert
                    asyncio.create_task(_send_disk_alert(usage_percent))
                elif usage_percent < _DISK_ALERT_THRESHOLD - 5:
                    # Reset when back to safe level (hysteresis)
                    _disk_alert_sent = False
            except Exception:
                pass

        except Exception:
            logger.debug("Bot metrics collection cycle skipped", exc_info=True)

        await asyncio.sleep(COLLECT_INTERVAL_SECONDS)
