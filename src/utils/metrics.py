"""
Risk-state Prometheus metrics (Issue #216 Section 2.3).

Module-level singletons. Importing registers them in the default
registry, so they appear on ``/metrics`` automatically.

* ``risk_exchange_reject_total`` — Counter (exchange, reject_reason).
  Incremented inside exchange clients' ``_parse_response`` on any branch
  that raises ``{Bitget,BingX,Weex}ClientError``.
* ``risk_intent_duration_seconds`` — Histogram (exchange, leg, outcome).
  End-to-end 2PC latency of ``RiskStateManager.apply_intent``.
* ``risk_sync_drift_total`` — Counter (field). One increment per field
  rewritten by ``RiskStateManager.reconcile``.
"""

from __future__ import annotations

from typing import Iterable

from prometheus_client import Counter, Histogram

# ── Label sets (exported for tests + callers) ─────────────────────────
REJECT_LABELS: tuple[str, ...] = ("exchange", "reject_reason")
INTENT_LABELS: tuple[str, ...] = ("exchange", "leg", "outcome")
DRIFT_LABELS: tuple[str, ...] = ("field",)

# Canonical list of fields reconcile() may rewrite. Tests and reconcile
# iterate the same source of truth.
DRIFT_FIELDS: tuple[str, ...] = (
    "take_profit",
    "tp_order_id",
    "tp_status",
    "stop_loss",
    "sl_order_id",
    "sl_status",
    "trailing_callback_rate",
    "trailing_activation_price",
    "trailing_trigger_price",
    "trailing_order_id",
    "trailing_status",
    "risk_source",
)

# Histogram buckets tuned for 2PC latencies (~1ms … 30s).
_INTENT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0,
)


# ── Metric singletons ─────────────────────────────────────────────────
risk_exchange_reject_total: Counter = Counter(
    "risk_exchange_reject_total",
    "Exchange-client rejects (HTTP non-200, non-zero code, unexpected shape)",
    REJECT_LABELS,
)

risk_intent_duration_seconds: Histogram = Histogram(
    "risk_intent_duration_seconds",
    "End-to-end duration of RiskStateManager.apply_intent (2PC)",
    INTENT_LABELS,
    buckets=_INTENT_BUCKETS,
)

risk_sync_drift_total: Counter = Counter(
    "risk_sync_drift_total",
    "Fields corrected by RiskStateManager.reconcile (exchange wins over DB)",
    DRIFT_LABELS,
)


# ── Helpers (best-effort — never raise to the caller) ─────────────────
def record_reject(exchange: str, reject_reason: str) -> None:
    try:
        risk_exchange_reject_total.labels(
            exchange=exchange, reject_reason=reject_reason,
        ).inc()
    except Exception:  # pragma: no cover
        pass


def record_intent_duration(
    exchange: str, leg: str, outcome: str, duration_seconds: float,
) -> None:
    try:
        risk_intent_duration_seconds.labels(
            exchange=exchange, leg=leg, outcome=outcome,
        ).observe(duration_seconds)
    except Exception:  # pragma: no cover
        pass


def record_drift(fields: Iterable[str]) -> None:
    for name in fields:
        try:
            risk_sync_drift_total.labels(field=name).inc()
        except Exception:  # pragma: no cover
            continue


__all__ = [
    "DRIFT_FIELDS",
    "DRIFT_LABELS",
    "INTENT_LABELS",
    "REJECT_LABELS",
    "record_drift",
    "record_intent_duration",
    "record_reject",
    "risk_exchange_reject_total",
    "risk_intent_duration_seconds",
    "risk_sync_drift_total",
]
