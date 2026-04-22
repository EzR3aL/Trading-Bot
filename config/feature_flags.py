"""
Central feature-flag registry (ARCH-M2, issue #247).

This module is the single source of truth for every boolean on/off toggle
that the runtime reads from ``config.settings.settings``. It does NOT
duplicate defaults — the actual value still lives on the ``Settings``
instance and is read lazily via ``FeatureFlagRegistry.get(name)``.

Scope
-----
A "feature flag" here is a read-only boolean toggle that gates a code
path (e.g. ``risk_state_manager_enabled``). Operational config such as
timeouts, URLs, credentials, or numeric limits is NOT a flag and must
NOT be listed here.

Usage
-----
    from config.feature_flags import FEATURE_FLAGS, feature_flags

    feature_flags.get("risk_state_manager_enabled")  # → bool
    [f.name for f in FEATURE_FLAGS]                  # → inventory

The registry exists for inventory and documentation. Existing call sites
that read ``settings.risk.risk_state_manager_enabled`` directly continue
to work and are NOT migrated in this PR — migration to the read-through
API is an optional follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class FeatureFlag:
    """A single feature flag.

    Attributes:
        name: Stable identifier (matches the Settings field name).
        settings_path: Dotted path on the ``Settings`` instance
            (e.g. ``"risk.risk_state_manager_enabled"``).
        env_var: Environment variable that seeds the default value.
        default: Default boolean value when the env var is unset.
        description: One-sentence summary of what the flag gates.
    """

    name: str
    settings_path: str
    env_var: str
    default: bool
    description: str


FEATURE_FLAGS: List[FeatureFlag] = [
    FeatureFlag(
        name="risk_state_manager_enabled",
        settings_path="risk.risk_state_manager_enabled",
        env_var="RISK_STATE_MANAGER_ENABLED",
        default=False,
        description=(
            "Gate for the 2-Phase-Commit RiskStateManager (#190). When on, "
            "TP/SL/trailing changes go through intent -> exchange -> "
            "readback -> DB with reconcile() healing drift."
        ),
    ),
    FeatureFlag(
        name="hl_software_trailing_enabled",
        settings_path="risk.hl_software_trailing_enabled",
        env_var="HL_SOFTWARE_TRAILING_ENABLED",
        default=False,
        description=(
            "Gate for the Hyperliquid software trailing-stop emulator "
            "(#216 3.1). HL has no native trailing primitive; when on, "
            "HLTrailingEmulator ratchets highest_price and rewrites SL "
            "from the bot process."
        ),
    ),
]


def _split_path(path: str) -> Tuple[str, ...]:
    return tuple(part for part in path.split(".") if part)


class FeatureFlagRegistry:
    """Read-through view of ``FEATURE_FLAGS`` backed by the Settings instance.

    The registry holds no state of its own. ``get(name)`` walks the
    dotted ``settings_path`` of the matching ``FeatureFlag`` on the
    supplied ``Settings`` instance (or the process-global ``settings``
    when none is supplied). This means the ``FEATURE_FLAGS`` list is
    metadata (inventory + docs + env-var names) while the actual value
    still lives on ``config.settings.Settings``.
    """

    def __init__(
        self,
        flags: List[FeatureFlag] = FEATURE_FLAGS,
        settings_instance=None,
    ) -> None:
        self._flags = {flag.name: flag for flag in flags}
        self._settings = settings_instance

    @property
    def flags(self) -> List[FeatureFlag]:
        """Return the flags in registration order."""
        return list(self._flags.values())

    def names(self) -> List[str]:
        """Return every registered flag name."""
        return list(self._flags.keys())

    def get_flag(self, name: str) -> FeatureFlag:
        """Return the ``FeatureFlag`` metadata for ``name``."""
        try:
            return self._flags[name]
        except KeyError as exc:
            raise KeyError(f"Unknown feature flag: {name}") from exc

    def get(self, name: str, settings_instance=None) -> bool:
        """Return the current boolean value of ``name`` from the Settings.

        ``settings_instance`` takes precedence over the instance the
        registry was constructed with. When both are ``None``, we import
        the module-level ``settings`` from ``config.settings`` lazily so
        that test code can monkey-patch it before the first call.
        """
        flag = self.get_flag(name)
        instance = settings_instance or self._settings
        if instance is None:
            from config.settings import settings as _default_settings
            instance = _default_settings

        node = instance
        for part in _split_path(flag.settings_path):
            node = getattr(node, part)
        return bool(node)


# Module-level singleton — mirrors the ``config.settings.settings`` pattern.
feature_flags = FeatureFlagRegistry()


__all__ = [
    "FeatureFlag",
    "FeatureFlagRegistry",
    "FEATURE_FLAGS",
    "feature_flags",
]
