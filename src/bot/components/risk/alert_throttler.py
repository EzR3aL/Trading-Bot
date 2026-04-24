"""AlertThrottler: dedupe + midnight reset for risk alerts (ARCH-H2 Phase 1 PR-4, #326).

Extracted from ``BotWorker._risk_alerts_sent`` + ``_risk_alerts_last_reset``
and the inlined alert-emission blocks in ``BotWorker._analyze_and_trade``
(previously lines ~1037-1086 of ``src/bot/bot_worker.py``).

The component owns the dedupe set + last-reset timestamp and exposes two
high-level emission helpers (``emit_global_if_needed`` /
``emit_per_symbol_if_needed``) that fold together:

1. The "halted"/"limit" keyword filter (only these reasons are queued).
2. The dedupe-by-alert-key invariant.
3. The ``TRADE_LIMIT`` vs ``DAILY_LOSS_LIMIT`` alert-type classification.
4. The notifier dispatch + **swallow-on-error** contract.

The swallow-on-error contract is the one behaviour change vs. the Phase 0
characterization: previously a failing notifier propagated out of
``_analyze_and_trade``; the throttler now wraps the call in try/except
and logs a warning, so a flaky Discord/Telegram webhook never kills the
per-symbol analysis loop. See ``tests/unit/bot/components/risk/
test_alert_throttler.py::test_notifier_exception_is_swallowed`` and the
corresponding flipped characterization test.

See ``AlertThrottlerProtocol`` in
``src/bot/components/risk/protocols.py`` for the invariants locked by
the Phase 1 contract tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 24h — reset the dedupe set once a day so a key deduped yesterday fires
# again today (matches the previous inlined behaviour on BotWorker).
_RESET_WINDOW_SECONDS = 86400


def _classify_alert_type(reason_lower: str) -> str:
    """Map a risk reason to a notification ``alert_type`` string.

    Mirrors the original inline logic in ``_analyze_and_trade``:
    ``"trade limit"`` substring → ``TRADE_LIMIT``; anything else that
    passed the ``"halted"``/``"limit"`` filter → ``DAILY_LOSS_LIMIT``.
    """
    if "trade limit" in reason_lower:
        return "TRADE_LIMIT"
    return "DAILY_LOSS_LIMIT"


def _should_queue(reason_lower: str) -> bool:
    """Return True for reasons that should be emitted as risk alerts.

    Frozen behaviour from the Phase 0 characterization: only reasons
    containing ``"halted"`` or ``"limit"`` are queued — everything else
    (e.g. ``"not initialized yet"``) is silently skipped.
    """
    return "halted" in reason_lower or "limit" in reason_lower


# ``NotificationSender`` is the signature of BotWorker._send_notification:
# ``async def send(send_fn, *, event_type, summary) -> None``.
NotificationSender = Callable[..., Awaitable[None]]


class AlertThrottler:
    """Dedupe + midnight-reset component for risk alerts.

    Satisfies ``AlertThrottlerProtocol``. Owns a ``set[str]`` of alert
    keys already emitted in the current window and a ``datetime`` of the
    last reset. Not thread-safe — callers are expected to run on the
    bot's single asyncio loop (same constraint as the inlined BotWorker
    state it replaces).
    """

    def __init__(
        self,
        bot_config_id: Optional[int],
        notification_sender: NotificationSender,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._bot_config_id = bot_config_id
        self._send = notification_sender
        self._now = now
        self._sent: set[str] = set()
        self._last_reset: datetime = now()

    # ── Protocol surface ────────────────────────────────────────────

    def should_emit(self, alert_key: str) -> bool:
        """Return ``True`` iff ``alert_key`` has not been emitted since the
        last reset. Atomic record: second call with the same key returns
        ``False``.
        """
        if alert_key in self._sent:
            return False
        self._sent.add(alert_key)
        return True

    def maybe_reset(self) -> None:
        """Clear the dedupe set if > 24h since the last reset."""
        now = self._now()
        if (now - self._last_reset).total_seconds() > _RESET_WINDOW_SECONDS:
            self._sent.clear()
            self._last_reset = now

    def reset(self) -> None:
        """Unconditional clear — for daily-summary + bot-stop hooks."""
        self._sent.clear()

    # ── Backward-compat accessors (BotWorker-level properties delegate here) ──

    @property
    def sent(self) -> set[str]:
        """Current dedupe set. Exposed as a live reference so existing
        tests can ``.add(...)`` / ``.update(...)`` / ``.clear()`` directly.
        """
        return self._sent

    @sent.setter
    def sent(self, value: set[str]) -> None:
        """Replace the dedupe set wholesale (characterization tests
        assign a brand-new ``set`` to seed stale keys)."""
        self._sent = value

    @property
    def last_reset(self) -> datetime:
        return self._last_reset

    @last_reset.setter
    def last_reset(self, value: datetime) -> None:
        self._last_reset = value

    # ── High-level emission helpers ─────────────────────────────────

    async def emit_global_if_needed(self, reason: str) -> bool:
        """Dispatch a global risk alert if the reason passes the filter
        and the key has not yet fired this window.

        Returns ``True`` iff a notification was dispatched (or attempted —
        notifier exceptions are swallowed here). Returns ``False`` when
        the reason is filtered out or the key is already recorded.
        """
        reason_lower = reason.lower()
        if not _should_queue(reason_lower):
            return False
        alert_key = f"global_{reason}"
        if not self.should_emit(alert_key):
            return False
        alert_type = _classify_alert_type(reason_lower)
        await self._dispatch(
            alert_type=alert_type,
            message=reason,
        )
        return True

    async def emit_per_symbol_if_needed(self, symbol: str, reason: str) -> bool:
        """Per-symbol variant of ``emit_global_if_needed``.

        Alert key is ``f"{symbol}_{reason}"`` — different symbols with
        the same reason fire independently. Notifier message includes
        the symbol prefix (``"{symbol}: {reason}"``).
        """
        reason_lower = reason.lower()
        if not _should_queue(reason_lower):
            return False
        alert_key = f"{symbol}_{reason}"
        if not self.should_emit(alert_key):
            return False
        alert_type = _classify_alert_type(reason_lower)
        message = f"{symbol}: {reason}"
        await self._dispatch(
            alert_type=alert_type,
            message=message,
        )
        return True

    async def _dispatch(self, *, alert_type: str, message: str) -> None:
        """Send a risk alert via the configured notifier, swallowing any
        exception raised by the notifier layer.

        Previously the inlined version let notifier exceptions propagate
        out of ``_analyze_and_trade`` (see the Phase 0 FIXME test). The
        component wraps the call explicitly so a flaky Discord/Telegram
        webhook never aborts the analysis loop.
        """
        log_prefix = f"[Bot:{self._bot_config_id}]" if self._bot_config_id else "[AlertThrottler]"
        try:
            await self._send(
                lambda n, at=alert_type, m=message: n.send_risk_alert(
                    alert_type=at, message=m,
                ),
                event_type="risk_alert",
                summary=f"{alert_type}: {message[:100]}",
            )
        except Exception as e:
            # Frozen contract (Phase 1 change): never propagate notifier
            # failures out of the alert-emission path.
            logger.warning(
                "%s AlertThrottler: notifier raised during risk_alert dispatch: %s",
                log_prefix, e,
            )
