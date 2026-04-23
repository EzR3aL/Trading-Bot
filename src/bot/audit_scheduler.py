"""Automatic bug-detection audit scheduler (Issue #216 Section 2.4).

Schedules the four ``scripts/audit_*`` scripts hourly (staggered 0/15/30/45
minutes to spread exchange-API load) and pipes any findings into the
existing notification stack (Discord admin webhook and/or Telegram admin
chat from the environment).

The scheduler is **opt-in**: wiring it into the FastAPI lifespan is only
active when ``AUTO_AUDIT_ENABLED=true``. By default it stays dormant so
operator workflows (manual ``--apply`` runs, ad-hoc investigations) are
not drowned in background noise.

Design notes:

* We wrap an ``AsyncIOScheduler`` rather than reusing the orchestrator's
  scheduler. That keeps audit jobs from competing with trading-bot
  scheduling cadence and lets us cleanly ``shutdown()`` on app stop.
* Each scheduled job delegates to the script's ``main_async()`` wrapper
  through a thin runner that captures the ``AuditReport`` and turns it
  into a human-readable notification summary.
* Notification dispatch is best-effort: a failed Discord send never
  crashes the job — the audit outcome is still on disk in ``reports/``.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scripts import (
    audit_classify_method,
    audit_position_size,
    audit_price_sanity,
    audit_tp_sl_flags,
)
from scripts._audit_common import resolve_output_path
from src.utils.logger import get_logger


logger = get_logger(__name__)


# ── Job definitions ────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditJob:
    """Static description of one scheduled audit."""
    job_id: str
    name: str
    minute: int  # 0 | 15 | 30 | 45
    runner: Callable[[], Awaitable[dict]]


def _as_outcome(result) -> dict:
    """Return ``result.as_outcome()`` or the bare result if already a dict."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    as_outcome = getattr(result, "as_outcome", None)
    if callable(as_outcome):
        return as_outcome()
    return {}


async def _run_tp_sl_flags() -> dict:
    started_at = datetime.now(timezone.utc)
    output_path = resolve_output_path(
        audit_tp_sl_flags.AUDIT_NAME, None, started_at,
    )
    report = await audit_tp_sl_flags.run_audit(
        user_id=None, exchange=None, apply_mode=False, output_path=output_path,
    )
    return _as_outcome(report)


async def _run_position_size() -> dict:
    started_at = datetime.now(timezone.utc)
    output_path = resolve_output_path(
        audit_position_size.AUDIT_NAME, None, started_at,
    )
    report = await audit_position_size.run_audit(
        user_id=None, exchange=None, apply_mode=False, output_path=output_path,
    )
    return _as_outcome(report)


async def _run_price_sanity() -> dict:
    started_at = datetime.now(timezone.utc)
    output_path = resolve_output_path(
        audit_price_sanity.AUDIT_NAME, None, started_at,
    )
    report = await audit_price_sanity.run_audit(
        hours=24, user_id=None, exchange=None, apply_mode=False,
        output_path=output_path,
    )
    return _as_outcome(report)


async def _run_classify_method() -> dict:
    started_at = datetime.now(timezone.utc)
    output_path = resolve_output_path(
        audit_classify_method.AUDIT_NAME, None, started_at,
    )
    report = await audit_classify_method.run_audit(
        hours=1,
        log_dir=Path(os.getenv("AUDIT_LOG_DIR", "logs")),
        apply_mode=False,
        output_path=output_path,
    )
    return _as_outcome(report)


# Canonical order drives both registration and tests.
AUDIT_JOBS: tuple[AuditJob, ...] = (
    AuditJob(
        job_id="audit_tp_sl_flags",
        name="TP/SL Flag Audit",
        minute=0,
        runner=_run_tp_sl_flags,
    ),
    AuditJob(
        job_id="audit_position_size",
        name="Position-Size Audit",
        minute=15,
        runner=_run_position_size,
    ),
    AuditJob(
        job_id="audit_price_sanity",
        name="Price Sanity Audit",
        minute=30,
        runner=_run_price_sanity,
    ),
    AuditJob(
        job_id="audit_classify_method",
        name="Classify Method Audit",
        minute=45,
        runner=_run_classify_method,
    ),
)


# ── Finding detection ──────────────────────────────────────────────────


def summarize_outcome(job: AuditJob, outcome: dict) -> Optional[str]:
    """Return a human-readable summary when the audit surfaced a finding.

    Returns ``None`` when the audit passed cleanly — the scheduler only
    notifies on findings, never on clean runs.
    """
    if not outcome:
        return None

    audit = outcome.get("audit", job.job_id)

    if audit == audit_tp_sl_flags.AUDIT_NAME:
        mismatches = outcome.get("mismatches") or []
        if not mismatches:
            return None
        sample = ", ".join(
            f"#{m['trade_id']} {m['kind']}" for m in mismatches[:3]
        )
        return (
            f"{job.name}: {len(mismatches)} TP/SL-Mismatch(es). "
            f"Beispiele: {sample}."
        )

    if audit == audit_position_size.AUDIT_NAME:
        desync = outcome.get("desync", 0)
        missing = outcome.get("missing", 0)
        if not (desync or missing):
            return None
        return (
            f"{job.name}: {desync} Desync + {missing} Missing gefunden. "
            f"Siehe Report."
        )

    if audit == audit_price_sanity.AUDIT_NAME:
        findings = outcome.get("findings") or []
        if not findings:
            return None
        sample = ", ".join(
            f"#{f['trade_id']} {f['kind']} {f['deviation_pct']:+.2f}%"
            for f in findings[:3]
        )
        return (
            f"{job.name}: {len(findings)} Preis-Abweichung(en) > Schwellenwert. "
            f"Beispiele: {sample}."
        )

    if audit == audit_classify_method.AUDIT_NAME:
        alerts = outcome.get("alerts") or []
        if not alerts:
            return None
        return f"{job.name}: {len(alerts)} Exchange(s) über Heuristik-Schwelle: " + \
               "; ".join(alerts)

    # Unknown audit — surface the raw summary.
    return f"{job.name}: unexpected findings: {outcome}"


# ── Scheduler ──────────────────────────────────────────────────────────


class AuditScheduler:
    """Hourly APScheduler-backed runner for the four #216 audit scripts.

    Usage::

        scheduler = AuditScheduler(notifier=my_notifier)
        scheduler.start()
        ...
        await scheduler.shutdown()
    """

    def __init__(
        self,
        *,
        scheduler: Optional[AsyncIOScheduler] = None,
        notifier: Optional[Callable[[str, dict], Awaitable[None]]] = None,
        jobs: tuple[AuditJob, ...] = AUDIT_JOBS,
    ) -> None:
        self._scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
        self._owns_scheduler = scheduler is None
        self._notifier = notifier
        self._jobs = jobs
        self._registered = False

    # ── Lifecycle ─────────────────────────────────────────────────

    def register_jobs(self) -> None:
        """Register one cron job per audit on the underlying scheduler.

        Separated from :meth:`start` so tests can assert on the registry
        without actually starting background event loops.
        """
        if self._registered:
            return
        for job in self._jobs:
            trigger = CronTrigger(minute=job.minute, timezone="UTC")
            self._scheduler.add_job(
                self._wrap_runner(job),
                trigger=trigger,
                id=job.job_id,
                name=job.name,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        self._registered = True
        logger.info(
            "audit_scheduler.registered jobs=%s", [j.job_id for j in self._jobs],
        )

    def start(self) -> None:
        """Register jobs + start the scheduler's event loop."""
        self.register_jobs()
        if self._owns_scheduler and not self._scheduler.running:
            self._scheduler.start()

    async def shutdown(self) -> None:
        """Stop the scheduler (best-effort)."""
        if not self._owns_scheduler:
            return
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
        except Exception:  # pragma: no cover — shutdown is best-effort
            logger.debug("audit_scheduler shutdown raised — ignoring", exc_info=True)

    # ── Introspection (used by tests) ─────────────────────────────

    @property
    def jobs(self) -> tuple[AuditJob, ...]:
        return self._jobs

    def get_job_ids(self) -> list[str]:
        """Return the ids of jobs registered on the underlying scheduler."""
        return [job.id for job in self._scheduler.get_jobs()]

    def get_job_minutes(self) -> dict[str, int]:
        """Return ``{job_id: minute}`` for every registered cron job."""
        minutes: dict[str, int] = {}
        for job in self._scheduler.get_jobs():
            trigger = job.trigger
            minute_field = getattr(trigger, "fields", None)
            if not minute_field:
                continue
            for field in trigger.fields:
                if field.name == "minute":
                    expressions = getattr(field, "expressions", [])
                    if expressions:
                        minutes[job.id] = int(str(expressions[0]))
                        break
        return minutes

    # ── Internals ─────────────────────────────────────────────────

    def _wrap_runner(
        self, job: AuditJob,
    ) -> Callable[[], Awaitable[None]]:
        """Wrap an AuditJob's runner with logging + notification glue."""

        async def _runner() -> None:
            logger.info("audit_scheduler.run start job=%s", job.job_id)
            try:
                outcome = await job.runner()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "audit_scheduler.run error job=%s error=%s",
                    job.job_id, e, exc_info=True,
                )
                return

            summary = summarize_outcome(job, outcome)
            if summary is None:
                logger.info("audit_scheduler.run clean job=%s", job.job_id)
                return

            logger.warning("audit_scheduler.finding job=%s summary=%s", job.job_id, summary)
            if self._notifier is None:
                return
            try:
                await self._notifier(summary, outcome)
            except Exception as e:  # noqa: BLE001 — never crash the job
                logger.warning(
                    "audit_scheduler.notify error job=%s error=%s",
                    job.job_id, e,
                )

        _runner.__name__ = f"run_{job.job_id}"
        return _runner


# ── Default notifier backed by the project's Discord + Telegram stack ──


async def _load_admin_notification_config() -> dict:
    """Resolve admin notifier credentials from DB first, falling back to env.

    Strategy (Issue #242):
    1. Find the first active admin user (``role='admin'`` AND ``is_active=True``).
    2. Pick the newest enabled ``BotConfig`` of that admin that has any of the
       relevant notification fields populated — notifier fields live on
       ``BotConfig`` (per-bot), not on ``User``.
    3. Decrypt each field individually. Missing / undecryptable values fall
       back to the matching ``ADMIN_*`` env var.
    4. If neither DB nor env yields credentials for a channel, that channel is
       skipped by the caller (no-op with warn log).

    Returns a dict with optional keys ``discord_webhook_url``,
    ``telegram_bot_token``, ``telegram_chat_id``.
    """
    resolved: dict[str, str] = {}

    # 1) DB lookup — best-effort, never raises out of the notifier.
    try:
        from sqlalchemy import select

        from src.models.database import BotConfig, User
        from src.models.session import get_session
        from src.utils.encryption import decrypt_value

        async with get_session() as session:
            admin_row = await session.execute(
                select(User)
                .where(User.role == "admin", User.is_active.is_(True))
                .order_by(User.id.asc())
                .limit(1)
            )
            admin = admin_row.scalar_one_or_none()

            if admin is not None:
                bot_row = await session.execute(
                    select(BotConfig)
                    .where(
                        BotConfig.user_id == admin.id,
                        BotConfig.is_enabled.is_(True),
                    )
                    .order_by(BotConfig.updated_at.desc().nullslast(), BotConfig.id.desc())
                )
                for candidate in bot_row.scalars().all():
                    if candidate.discord_webhook_url and "discord_webhook_url" not in resolved:
                        try:
                            plain = decrypt_value(candidate.discord_webhook_url)
                            if plain:
                                resolved["discord_webhook_url"] = plain
                        except Exception as decrypt_err:  # noqa: BLE001
                            logger.warning(
                                "audit default_admin_notifier discord decrypt failed: %s",
                                decrypt_err,
                            )
                    if (
                        candidate.telegram_bot_token
                        and candidate.telegram_chat_id
                        and "telegram_bot_token" not in resolved
                    ):
                        try:
                            token_plain = decrypt_value(candidate.telegram_bot_token)
                            chat_plain = decrypt_value(candidate.telegram_chat_id)
                            if token_plain and chat_plain:
                                resolved["telegram_bot_token"] = token_plain
                                resolved["telegram_chat_id"] = chat_plain
                        except Exception as decrypt_err:  # noqa: BLE001
                            logger.warning(
                                "audit default_admin_notifier telegram decrypt failed: %s",
                                decrypt_err,
                            )
                    if "discord_webhook_url" in resolved and "telegram_bot_token" in resolved:
                        break
    except Exception as db_err:  # noqa: BLE001 — never block the audit path
        logger.warning("audit default_admin_notifier db lookup failed: %s", db_err)

    # 2) Env fallback for any channel the DB did not fill.
    if "discord_webhook_url" not in resolved:
        env_webhook = os.getenv("ADMIN_DISCORD_WEBHOOK_URL", "").strip()
        if env_webhook:
            resolved["discord_webhook_url"] = env_webhook

    if "telegram_bot_token" not in resolved:
        env_token = os.getenv("ADMIN_TELEGRAM_BOT_TOKEN", "").strip()
        env_chat = os.getenv("ADMIN_TELEGRAM_CHAT_ID", "").strip()
        if env_token and env_chat:
            resolved["telegram_bot_token"] = env_token
            resolved["telegram_chat_id"] = env_chat

    return resolved


async def default_admin_notifier(summary: str, outcome: dict) -> None:
    """Send ``summary`` to the admin Discord webhook and Telegram chat.

    Credential lookup (Issue #242): DB-first via the first active admin
    user's newest enabled ``BotConfig`` (same fields the BotBuilder already
    writes/encrypts), with ``ADMIN_*`` env vars as fallback so existing
    deployments keep working until the admin configures the DB values. When
    neither source yields credentials for a channel, that channel is
    skipped — the ``audit_scheduler.finding`` WARN log remains the baseline
    signal.
    """
    config = await _load_admin_notification_config()
    finding_count = float(len(outcome.get("findings", []) or []))

    if not config:
        logger.warning(
            "audit default_admin_notifier: no admin channels configured "
            "(DB admin user/bot + ADMIN_* env vars both empty) — skipping delivery",
        )
        return

    webhook_url = config.get("discord_webhook_url", "")
    if webhook_url:
        try:
            from src.notifications.discord_notifier import DiscordNotifier
            async with DiscordNotifier(webhook_url=webhook_url) as notifier:
                await notifier.send_alert(
                    alert_type="audit",
                    symbol=None,
                    current_value=finding_count,
                    threshold=0.0,
                    message=summary,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("audit default_admin_notifier discord error: %s", e)

    bot_token = config.get("telegram_bot_token", "")
    chat_id = config.get("telegram_chat_id", "")
    if bot_token and chat_id:
        try:
            from src.notifications.telegram_notifier import TelegramNotifier
            notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
            async with notifier:
                await notifier.send_alert(
                    alert_type="audit",
                    symbol=None,
                    current_value=finding_count,
                    threshold=0.0,
                    message=summary,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("audit default_admin_notifier telegram error: %s", e)


def is_enabled() -> bool:
    """Return ``True`` when ``AUTO_AUDIT_ENABLED`` is set to a truthy value."""
    raw = os.getenv("AUTO_AUDIT_ENABLED", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


async def build_and_start_if_enabled() -> Optional[AuditScheduler]:
    """FastAPI lifespan helper: build + start a scheduler when opted-in.

    Returns the running scheduler (for later ``shutdown``) or ``None`` if
    the feature is disabled.
    """
    if not is_enabled():
        logger.info("audit_scheduler disabled (set AUTO_AUDIT_ENABLED=true to opt in)")
        return None
    # Loop probing guards against accidentally starting the scheduler
    # from a non-async context during tests.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("audit_scheduler: no running event loop — skip start")
        return None
    scheduler = AuditScheduler(notifier=default_admin_notifier)
    scheduler.start()
    return scheduler
