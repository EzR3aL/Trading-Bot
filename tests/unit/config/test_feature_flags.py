"""Tests for the central feature-flag registry (ARCH-M2, issue #247).

The registry is an inventory of every boolean on/off toggle exposed by
``config.settings.Settings``. These tests enforce:

1. Every flag in ``FEATURE_FLAGS`` maps to a real Settings field.
2. Every boolean field on Settings with an ``enabled``/``disable`` name
   is registered (parity check — stops a future flag from slipping in
   without being documented in the registry).
3. ``FeatureFlagRegistry.get(name)`` returns the same value as the raw
   ``settings.<path>`` attribute access, for both the default value and
   a flipped value.
"""

from dataclasses import fields, is_dataclass

import pytest

from config.feature_flags import (
    FEATURE_FLAGS,
    FeatureFlag,
    FeatureFlagRegistry,
    feature_flags,
)
from config.settings import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_path(instance, dotted_path: str):
    node = instance
    for part in dotted_path.split("."):
        node = getattr(node, part)
    return node


def _iter_bool_fields(settings_instance):
    """Yield (dotted_path, field_name) for every bool field in the Settings tree."""
    for top_field in fields(settings_instance):
        section = getattr(settings_instance, top_field.name)
        if not is_dataclass(section):
            # top-level bool (e.g. a future Settings.debug: bool)
            value = getattr(settings_instance, top_field.name)
            if isinstance(value, bool):
                yield (top_field.name, top_field.name)
            continue
        for sub_field in fields(section):
            value = getattr(section, sub_field.name)
            if isinstance(value, bool):
                yield (f"{top_field.name}.{sub_field.name}", sub_field.name)


# ---------------------------------------------------------------------------
# Registry structure
# ---------------------------------------------------------------------------

class TestFeatureFlagsShape:
    """Sanity checks that the registry itself is well-formed."""

    def test_registry_is_non_empty(self):
        assert len(FEATURE_FLAGS) > 0, "FEATURE_FLAGS must list at least one flag"

    def test_entries_are_feature_flag_instances(self):
        for flag in FEATURE_FLAGS:
            assert isinstance(flag, FeatureFlag)

    def test_names_are_unique(self):
        names = [flag.name for flag in FEATURE_FLAGS]
        assert len(names) == len(set(names)), f"Duplicate flag names: {names}"

    def test_env_vars_are_unique(self):
        env_vars = [flag.env_var for flag in FEATURE_FLAGS]
        assert len(env_vars) == len(set(env_vars)), f"Duplicate env vars: {env_vars}"

    def test_descriptions_non_empty(self):
        for flag in FEATURE_FLAGS:
            assert flag.description.strip(), f"{flag.name} is missing a description"

    def test_defaults_are_bool(self):
        for flag in FEATURE_FLAGS:
            assert isinstance(flag.default, bool), (
                f"{flag.name}.default must be bool, got {type(flag.default).__name__}"
            )


# ---------------------------------------------------------------------------
# Settings <-> registry parity
# ---------------------------------------------------------------------------

class TestRegistryMatchesSettings:
    """The registry and Settings must stay in sync."""

    def test_every_flag_resolves_on_settings(self):
        """Every flag.settings_path must point at a real bool on Settings()."""
        instance = Settings()
        for flag in FEATURE_FLAGS:
            value = _resolve_path(instance, flag.settings_path)
            assert isinstance(value, bool), (
                f"{flag.settings_path} on Settings is not a bool (got {type(value).__name__})"
            )

    def test_every_enabled_field_is_registered(self):
        """
        Every bool on Settings whose name contains 'enabled' or 'disable'
        must be listed in FEATURE_FLAGS. This is the parity check that
        prevents a future ``foo_enabled`` field from slipping in without
        being documented in the registry.
        """
        instance = Settings()
        registered_paths = {flag.settings_path for flag in FEATURE_FLAGS}
        missing = []
        for path, field_name in _iter_bool_fields(instance):
            lowered = field_name.lower()
            if "enabled" in lowered or "disable" in lowered:
                if path not in registered_paths:
                    missing.append(path)
        assert not missing, (
            "Settings bool fields with 'enabled'/'disable' in the name "
            "must be registered in FEATURE_FLAGS. Missing: "
            f"{missing}"
        )


# ---------------------------------------------------------------------------
# FeatureFlagRegistry.get behaviour
# ---------------------------------------------------------------------------

class TestRegistryGet:
    """``registry.get(name)`` must mirror direct attribute access."""

    def test_get_returns_default_from_fresh_settings(self):
        instance = Settings()
        registry = FeatureFlagRegistry(settings_instance=instance)
        for flag in FEATURE_FLAGS:
            expected = _resolve_path(instance, flag.settings_path)
            assert registry.get(flag.name) is expected, (
                f"{flag.name}: registry.get() != direct access"
            )

    def test_get_tracks_runtime_mutation(self):
        """Mutating the Settings field must flip what ``get`` returns."""
        instance = Settings()
        registry = FeatureFlagRegistry(settings_instance=instance)
        for flag in FEATURE_FLAGS:
            current = _resolve_path(instance, flag.settings_path)
            new_value = not current

            # Walk to the parent and set the child attribute.
            parts = flag.settings_path.split(".")
            parent = instance
            for part in parts[:-1]:
                parent = getattr(parent, part)
            setattr(parent, parts[-1], new_value)

            assert registry.get(flag.name) is new_value

            # Restore so subsequent flags see a clean slate.
            setattr(parent, parts[-1], current)

    def test_get_unknown_flag_raises(self):
        registry = FeatureFlagRegistry(settings_instance=Settings())
        with pytest.raises(KeyError, match="Unknown feature flag"):
            registry.get("this_flag_does_not_exist")

    def test_module_level_singleton_uses_global_settings(self):
        """``feature_flags.get(name)`` must resolve against ``config.settings.settings``."""
        from config.settings import settings as global_settings

        for flag in FEATURE_FLAGS:
            expected = _resolve_path(global_settings, flag.settings_path)
            assert feature_flags.get(flag.name) is expected

    def test_explicit_instance_overrides_bound_instance(self):
        """Passing ``settings_instance`` to ``get`` must take precedence."""
        bound = Settings()
        override = Settings()

        # Flip every flag on override so the two instances disagree.
        for flag in FEATURE_FLAGS:
            parts = flag.settings_path.split(".")
            parent = override
            for part in parts[:-1]:
                parent = getattr(parent, part)
            setattr(parent, parts[-1], not getattr(parent, parts[-1]))

        registry = FeatureFlagRegistry(settings_instance=bound)
        for flag in FEATURE_FLAGS:
            assert registry.get(flag.name, settings_instance=override) == _resolve_path(
                override, flag.settings_path
            )


# ---------------------------------------------------------------------------
# Metadata lookup
# ---------------------------------------------------------------------------

class TestGetFlagMetadata:
    def test_get_flag_returns_metadata(self):
        registry = FeatureFlagRegistry()
        for flag in FEATURE_FLAGS:
            assert registry.get_flag(flag.name) is flag

    def test_get_flag_unknown_raises(self):
        registry = FeatureFlagRegistry()
        with pytest.raises(KeyError):
            registry.get_flag("nope_nope_nope")

    def test_names_returns_every_flag(self):
        registry = FeatureFlagRegistry()
        assert set(registry.names()) == {flag.name for flag in FEATURE_FLAGS}
