"""Unit tests for :mod:`src.api.dependencies.hl_trailing`.

Covers:
- get_hl_trailing_emulator: returns singleton on first call
- get_hl_trailing_emulator: second call returns SAME instance (singleton)
- set_hl_trailing_emulator: overrides singleton (test helper)
- set_hl_trailing_emulator: setting None resets singleton so next get creates fresh
- get_hl_trailing_emulator: constructed with RSM from get_risk_state_manager
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "8P5tm7omM-7rNyRwE0VT2HQjZ08Q5Q-IgOyfTnf8_Ts="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

import src.api.dependencies.hl_trailing as hl_mod
from src.api.dependencies.hl_trailing import (
    get_hl_trailing_emulator,
    set_hl_trailing_emulator,
)
from src.bot.hl_trailing_emulator import HLTrailingEmulator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset():
    """Reset the module-level singleton for test isolation."""
    set_hl_trailing_emulator(None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_hl_trailing_emulator_returns_instance():
    _reset()
    emulator = get_hl_trailing_emulator()
    assert isinstance(emulator, HLTrailingEmulator)
    _reset()


def test_get_hl_trailing_emulator_returns_singleton():
    _reset()
    e1 = get_hl_trailing_emulator()
    e2 = get_hl_trailing_emulator()
    assert e1 is e2
    _reset()


def test_set_hl_trailing_emulator_overrides_singleton():
    _reset()
    mock_emulator = MagicMock(spec=HLTrailingEmulator)
    set_hl_trailing_emulator(mock_emulator)

    result = get_hl_trailing_emulator()
    assert result is mock_emulator
    _reset()


def test_set_hl_trailing_emulator_none_triggers_fresh_creation():
    _reset()
    e1 = get_hl_trailing_emulator()
    set_hl_trailing_emulator(None)
    e2 = get_hl_trailing_emulator()

    assert e1 is not e2
    assert isinstance(e2, HLTrailingEmulator)
    _reset()


def test_get_hl_trailing_emulator_uses_risk_state_manager():
    """Verify the emulator is wired to the RSM singleton."""
    _reset()

    mock_rsm = MagicMock()
    with patch.object(hl_mod, "get_risk_state_manager", return_value=mock_rsm):
        with patch.object(hl_mod, "_make_exchange_client_factory", return_value=MagicMock()):
            with patch("src.api.dependencies.hl_trailing.HLTrailingEmulator") as mock_cls:
                mock_cls.return_value = MagicMock(spec=HLTrailingEmulator)
                get_hl_trailing_emulator()

    # HLTrailingEmulator was called with the mock RSM
    mock_cls.assert_called_once()
    call_kwargs = mock_cls.call_args[1]
    assert call_kwargs.get("risk_state_manager") is mock_rsm

    _reset()


def test_set_hl_trailing_emulator_accepts_none():
    """set_hl_trailing_emulator(None) is allowed (used for test teardown)."""
    _reset()
    set_hl_trailing_emulator(None)  # must not raise
    assert hl_mod._emulator is None
