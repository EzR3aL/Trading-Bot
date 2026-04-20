"""Unit tests for :mod:`src.utils.metrics` (Issue #216 Section 2.3).

These tests check the metric CONTRACT (name, label set, increment/observe
semantics) against the real prometheus-client registry instead of
re-implementing it with mocks. Each metric under test is sampled via its
``_metrics`` dict so the tests stay independent of other processes that
may also be writing to the default registry.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.utils.metrics import (
    DRIFT_FIELDS,
    DRIFT_LABELS,
    INTENT_LABELS,
    REJECT_LABELS,
    record_drift,
    record_intent_duration,
    record_reject,
    risk_exchange_reject_total,
    risk_intent_duration_seconds,
    risk_sync_drift_total,
)


def _counter_value(counter, **labels) -> float:
    """Read current value of a labeled Counter sample."""
    return counter.labels(**labels)._value.get()


def _histogram_sample_count(histogram, **labels) -> float:
    """Total number of samples observed for a labeled Histogram.

    ``prometheus_client`` stores per-bucket deltas (not cumulative
    counts) on ``_buckets``, so the true sample count is their sum.
    """
    labeled = histogram.labels(**labels)
    return labeled._sum.get(), sum(b.get() for b in labeled._buckets)


def test_counter_and_histogram_label_sets_match_contract():
    """Label names on each metric must match the documented contract.

    The Grafana dashboard and alert rules rely on these exact label
    names (``exchange``, ``leg``, ``outcome`` …). Changing one without
    updating the other breaks every downstream panel.
    """
    assert REJECT_LABELS == ("exchange", "reject_reason")
    assert INTENT_LABELS == ("exchange", "leg", "outcome")
    assert DRIFT_LABELS == ("field",)

    assert risk_exchange_reject_total._labelnames == REJECT_LABELS
    assert risk_intent_duration_seconds._labelnames == INTENT_LABELS
    assert risk_sync_drift_total._labelnames == DRIFT_LABELS


def test_record_reject_increments_counter_per_call():
    """Two calls with the same labels produce a delta of 2."""
    labels = {"exchange": "bitget", "reject_reason": "http_status_unit_test_a"}
    before = _counter_value(risk_exchange_reject_total, **labels)

    record_reject(**labels)
    record_reject(**labels)

    after = _counter_value(risk_exchange_reject_total, **labels)
    assert after - before == pytest.approx(2.0)


def test_record_intent_duration_observes_sample():
    """Observing a duration must bump the histogram's sample count."""
    labels = {
        "exchange": "bingx",
        "leg": "trailing",
        "outcome": "confirmed",
    }
    _, before_count = _histogram_sample_count(risk_intent_duration_seconds, **labels)

    record_intent_duration(duration_seconds=0.123, **labels)
    record_intent_duration(duration_seconds=2.5, **labels)
    record_intent_duration(duration_seconds=0.001, **labels)

    _, after_count = _histogram_sample_count(risk_intent_duration_seconds, **labels)
    assert after_count - before_count == pytest.approx(3.0)


def test_record_drift_increments_once_per_field():
    """``record_drift`` emits exactly one increment per field name."""
    canonical = list(DRIFT_FIELDS)
    # Use a subset so the test stays deterministic even if someone adds
    # new fields to DRIFT_FIELDS later.
    sample_fields = [canonical[0], canonical[3]]  # take_profit + stop_loss

    before = {
        f: _counter_value(risk_sync_drift_total, field=f) for f in sample_fields
    }

    record_drift(sample_fields)

    for f in sample_fields:
        after = _counter_value(risk_sync_drift_total, field=f)
        assert after - before[f] == pytest.approx(1.0), (
            f"expected drift counter for {f!r} to advance by 1"
        )
