"""Exit-reason taxonomy for the risk-state classifier (Issue #193, Epic #188).

Defines the canonical set of reason codes that may be written to
``TradeRecord.exit_reason`` by :meth:`src.bot.risk_state_manager.RiskStateManager.classify_close`.

Two kinds of codes coexist:

1. **Precise codes** (the new taxonomy from #193): distinguish *who* closed
   the position (exchange-side native plan vs. bot software vs. user) and
   *why* (TP, SL, trailing, liquidation, funding-expiry, manual). These are
   what the classifier emits going forward.
2. **Legacy codes** (``TRAILING_STOP``, ``TAKE_PROFIT``, ``STOP_LOSS``,
   ``MANUAL_CLOSE``, ``EXTERNAL_CLOSE``): retained as enum members because
   historical ``trade_records`` rows already contain these strings. They
   must continue to round-trip cleanly through the helpers below.

Helper functions are intentionally *string*-based (not enum-typed) so DB
strings load directly without needing to coerce through ``ExitReason(...)``.
"""

from __future__ import annotations

from enum import Enum


class ExitReason(str, Enum):
    """Canonical exit-reason codes written to ``TradeRecord.exit_reason``.

    Each member's value matches the i18n key in
    ``frontend/src/i18n/{de,en}.json`` ``exitReasons`` so the frontend can
    look up a human-readable label without a backend round-trip.
    """

    # ── Precise codes (#193 taxonomy) ───────────────────────────────
    TRAILING_STOP_NATIVE = "TRAILING_STOP_NATIVE"
    TRAILING_STOP_SOFTWARE = "TRAILING_STOP_SOFTWARE"
    TAKE_PROFIT_NATIVE = "TAKE_PROFIT_NATIVE"
    STOP_LOSS_NATIVE = "STOP_LOSS_NATIVE"
    MANUAL_CLOSE_UI = "MANUAL_CLOSE_UI"
    MANUAL_CLOSE_EXCHANGE = "MANUAL_CLOSE_EXCHANGE"
    STRATEGY_EXIT = "STRATEGY_EXIT"
    LIQUIDATION = "LIQUIDATION"
    FUNDING_EXPIRY = "FUNDING_EXPIRY"
    EXTERNAL_CLOSE_UNKNOWN = "EXTERNAL_CLOSE_UNKNOWN"

    # ── Legacy aliases (pre-#193 historical trades) ─────────────────
    TRAILING_STOP_LEGACY = "TRAILING_STOP"
    TAKE_PROFIT_LEGACY = "TAKE_PROFIT"
    STOP_LOSS_LEGACY = "STOP_LOSS"
    MANUAL_CLOSE_LEGACY = "MANUAL_CLOSE"
    EXTERNAL_CLOSE_LEGACY = "EXTERNAL_CLOSE"


# Pre-computed lookup sets — keep them aligned with ExitReason members
# above. Tests assert membership so a typo in either side fails CI.

_NATIVE_EXIT_REASONS: frozenset[str] = frozenset({
    ExitReason.TRAILING_STOP_NATIVE.value,
    ExitReason.TAKE_PROFIT_NATIVE.value,
    ExitReason.STOP_LOSS_NATIVE.value,
    ExitReason.MANUAL_CLOSE_EXCHANGE.value,
    ExitReason.LIQUIDATION.value,
    ExitReason.FUNDING_EXPIRY.value,
})

_SOFTWARE_EXIT_REASONS: frozenset[str] = frozenset({
    ExitReason.TRAILING_STOP_SOFTWARE.value,
    ExitReason.STRATEGY_EXIT.value,
})

_MANUAL_EXIT_REASONS: frozenset[str] = frozenset({
    ExitReason.MANUAL_CLOSE_UI.value,
    ExitReason.MANUAL_CLOSE_EXCHANGE.value,
    ExitReason.MANUAL_CLOSE_LEGACY.value,
})


def is_native_exit(reason: str) -> bool:
    """True when the close was triggered by an exchange-side native order.

    Covers TP/SL/trailing native plans, exchange-side manual closes,
    liquidations, and funding expiries. Legacy strings are NOT treated as
    native — they have ambiguous origin and should be migrated explicitly.
    """
    return reason in _NATIVE_EXIT_REASONS


def is_software_exit(reason: str) -> bool:
    """True when the close was triggered by the bot's own logic.

    Covers software trailing stop and strategy-exit signals.
    """
    return reason in _SOFTWARE_EXIT_REASONS


def is_manual_exit(reason: str) -> bool:
    """True when the close was initiated by a human (UI or exchange UI).

    Includes the legacy ``MANUAL_CLOSE`` string for backwards compatibility.
    """
    return reason in _MANUAL_EXIT_REASONS


__all__ = [
    "ExitReason",
    "is_native_exit",
    "is_software_exit",
    "is_manual_exit",
]
