"""
Background metric collectors.

Periodically samples bot orchestrator state and updates Prometheus gauges.
"""

import asyncio

from src.monitoring.metrics import BOTS_BY_STATUS, BOTS_RUNNING, BOT_CONSECUTIVE_ERRORS
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLLECT_INTERVAL_SECONDS = 15


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
        except Exception:
            logger.debug("Bot metrics collection cycle skipped", exc_info=True)

        await asyncio.sleep(COLLECT_INTERVAL_SECONDS)
