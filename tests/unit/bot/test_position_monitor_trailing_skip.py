"""Tests for PositionMonitor auto-trailing-place skip logic (issue #216).

Guards the Phase A→B race window: the monitor must not auto-place a
native trailing while either the user has just cleared it or the API's
RiskStateManager is mid-2PC (status=pending). Verified here as a unit
test against the ``_TRAILING_SKIP_STATES`` constant and the surrounding
branch in ``_check_position``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==",
)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.position_monitor import _TRAILING_SKIP_STATES


def test_trailing_skip_states_contains_cleared_and_pending():
    """The set must cover both user-cleared and API-pending cases."""
    assert "cleared" in _TRAILING_SKIP_STATES
    assert "pending" in _TRAILING_SKIP_STATES


def test_trailing_skip_states_excludes_terminal_outcomes():
    """Terminal non-alive states must NOT skip — auto-place may re-attempt.

    Once an RSM intent resolves to rejected or cancel_failed, the trailing
    leg is not in-flight anymore. The monitor should be free to re-try on
    its own cadence.
    """
    for state in ("rejected", "cancel_failed", "confirmed", None, ""):
        assert state not in _TRAILING_SKIP_STATES, (
            f"{state!r} must not be in _TRAILING_SKIP_STATES — that "
            f"would block legitimate monitor retries"
        )


def test_trailing_skip_states_is_frozen():
    """Guard against mutation — the set is imported at module load time."""
    assert isinstance(_TRAILING_SKIP_STATES, frozenset)
