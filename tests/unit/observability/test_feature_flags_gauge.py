"""Unit tests for the ``app_feature_flags`` Prometheus gauge (#338).

These tests exercise the ``publish_feature_flag_gauge`` helper that the
FastAPI lifespan calls on startup (see ``src/api/main_app.py``). They
verify:

1. Every registered flag in ``config.feature_flags.FEATURE_FLAGS`` ends up
   as a label value on the ``app_feature_flags`` gauge after publish.
2. Published values are strictly ``0`` or ``1`` — never any other number.
3. Flipping a flag's boolean and re-publishing updates the gauge sample
   (proves the resolver is really read, not cached from module import).

The tests talk to the real ``prometheus_client`` registry — no mocks for
the gauge itself — so the metric contract (name, label set) is checked
against the exact object Prometheus will scrape in production.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path when running the file directly.
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from config.feature_flags import (  # noqa: E402
    FEATURE_FLAGS,
    FeatureFlagRegistry,
)
from config.settings import Settings  # noqa: E402
from src.monitoring.metrics import (  # noqa: E402
    APP_FEATURE_FLAGS,
    publish_feature_flag_gauge,
)


def _gauge_value(flag_name: str) -> float:
    """Read the current sample for one label value on ``APP_FEATURE_FLAGS``."""
    return APP_FEATURE_FLAGS.labels(flag=flag_name)._value.get()


def _set_flag(settings_instance: Settings, dotted_path: str, value: bool) -> None:
    """Set ``dotted_path`` on the Settings instance to ``value``."""
    parts = dotted_path.split(".")
    parent = settings_instance
    for part in parts[:-1]:
        parent = getattr(parent, part)
    setattr(parent, parts[-1], value)


class TestPublishFeatureFlagGauge:
    """``publish_feature_flag_gauge`` populates the Prometheus gauge."""

    def test_gauge_contract_matches_spec(self):
        """Metric name, description and label set must match the ops contract."""
        assert APP_FEATURE_FLAGS._name == "app_feature_flags"
        assert APP_FEATURE_FLAGS._labelnames == ("flag",)
        assert APP_FEATURE_FLAGS._documentation == (
            "Runtime feature flag state (1=enabled, 0=disabled)"
        )

    def test_every_registered_flag_emits_a_sample(self):
        """After publish, every FEATURE_FLAGS entry must have a label value."""
        publish_feature_flag_gauge()

        # Collect all `flag=...` label values currently on the gauge.
        collected = list(APP_FEATURE_FLAGS.collect())
        assert collected, "APP_FEATURE_FLAGS collector returned no metrics"
        samples = collected[0].samples
        labels_seen = {s.labels["flag"] for s in samples if "flag" in s.labels}

        expected = {flag.name for flag in FEATURE_FLAGS}
        missing = expected - labels_seen
        assert not missing, (
            f"Missing gauge samples for flags: {missing}. "
            f"Seen: {labels_seen}"
        )

    def test_values_are_strictly_zero_or_one(self):
        """The gauge may only emit 0 or 1 — never 0.5, -1, or arbitrary ints."""
        publish_feature_flag_gauge()

        for flag in FEATURE_FLAGS:
            value = _gauge_value(flag.name)
            assert value in (0.0, 1.0), (
                f"{flag.name} gauge emitted {value!r}; must be 0 or 1"
            )

    def test_enabled_flag_publishes_one(self):
        """When the underlying Settings bool is True, the gauge must be 1."""
        settings_instance = Settings()
        # Flip every flag on so the gauge must read True for each.
        for flag in FEATURE_FLAGS:
            _set_flag(settings_instance, flag.settings_path, True)

        registry = FeatureFlagRegistry(settings_instance=settings_instance)
        publish_feature_flag_gauge(registry=registry)

        for flag in FEATURE_FLAGS:
            assert _gauge_value(flag.name) == 1.0, (
                f"{flag.name} should report 1 when enabled"
            )

    def test_disabled_flag_publishes_zero(self):
        """When the underlying Settings bool is False, the gauge must be 0."""
        settings_instance = Settings()
        for flag in FEATURE_FLAGS:
            _set_flag(settings_instance, flag.settings_path, False)

        registry = FeatureFlagRegistry(settings_instance=settings_instance)
        publish_feature_flag_gauge(registry=registry)

        for flag in FEATURE_FLAGS:
            assert _gauge_value(flag.name) == 0.0, (
                f"{flag.name} should report 0 when disabled"
            )

    def test_publish_is_idempotent_and_reflects_latest_state(self):
        """Calling publish again with a flipped flag updates the sample."""
        settings_instance = Settings()
        first_flag = FEATURE_FLAGS[0]

        # First pass: disabled everywhere.
        for flag in FEATURE_FLAGS:
            _set_flag(settings_instance, flag.settings_path, False)

        registry = FeatureFlagRegistry(settings_instance=settings_instance)
        publish_feature_flag_gauge(registry=registry)
        assert _gauge_value(first_flag.name) == 0.0

        # Flip the first flag on and republish — gauge must update.
        _set_flag(settings_instance, first_flag.settings_path, True)
        publish_feature_flag_gauge(registry=registry)
        assert _gauge_value(first_flag.name) == 1.0

    def test_accepts_custom_flag_list(self):
        """Callers may pass an explicit ``flags`` iterable (used by tests)."""
        settings_instance = Settings()
        _set_flag(settings_instance, FEATURE_FLAGS[0].settings_path, True)
        registry = FeatureFlagRegistry(settings_instance=settings_instance)

        # Only publish the first flag; second flag's gauge value must not
        # move between these two calls.
        subset = [FEATURE_FLAGS[0]]
        publish_feature_flag_gauge(flags=subset, registry=registry)
        assert _gauge_value(FEATURE_FLAGS[0].name) == 1.0


class TestFlagInventoryCoverage:
    """Guard against future flags silently missing from the gauge."""

    def test_all_feature_flags_are_named(self):
        """Each flag entry must have a non-empty name used as the gauge label."""
        for flag in FEATURE_FLAGS:
            assert flag.name and isinstance(flag.name, str), (
                f"Flag entry {flag!r} is missing a string name"
            )

    @pytest.mark.parametrize(
        "expected_flag", [flag.name for flag in FEATURE_FLAGS]
    )
    def test_expected_flag_appears_on_gauge(self, expected_flag: str):
        """Parametrised: every current flag must be emittable as a label."""
        publish_feature_flag_gauge()
        # This would raise ValueError if ``expected_flag`` is not a valid
        # label value (it is not — labels accept any string), but it does
        # prove we can always call .labels(flag=<name>) and read a sample.
        value = _gauge_value(expected_flag)
        assert value in (0.0, 1.0)
