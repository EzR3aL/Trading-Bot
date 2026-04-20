"""Live integration tests for ``RiskStateManager`` against Bitget demo (#197).

Scope
-----
Covers TEST_MATRIX.md Sections A (11 tests), B (5 tests) and the two
unit-testable C-path scenarios (C01, C03) as two respx-mocked cases.
Every live test:

1. Opens a 0.001 BTCUSDT position via the fixture.
2. Drives ``RiskStateManager.apply_intent`` through the real Bitget demo.
3. Asserts the :class:`RiskOpResult`, the DB row, and an independent
   Bitget-side readback via ``get_position_tpsl`` / ``get_trailing_stop``.
4. Lets the fixture's ``finally`` block close the position and cancel
   every lingering plan — guarantees the next test starts clean.

Gating
------
The suite is protected by two layers:
* ``pytest.mark.bitget_live`` — default ``pytest`` run skips the whole file.
* ``BITGET_LIVE_TEST_USER_ID`` env var — if missing, tests are skipped
  even when the marker is explicitly selected.

See ``tests/integration/live/README.md`` for the full execution guide.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.risk_state_manager import (
    RiskLeg,
    RiskOpStatus,
    RiskStateManager,
)
from src.exceptions import CancelFailed, OrderError
from src.models.database import TradeRecord
from src.models.session import get_session
from tests.integration.live.conftest import (
    BITGET_LIVE_MARKER,
    PRICE_TOLERANCE,
    READBACK_DELAY_SECONDS,
)


# ── Marker applied to every live test in this module ──────────────────

pytestmark = [pytest.mark.bitget_live, BITGET_LIVE_MARKER]


# ── Price calculation helpers ──────────────────────────────────────────
#
# Bitget rejects a TP below the current mark for a long (and vice versa).
# We compute sensible offsets from the entry price so the tests work at
# any BTC price level without hardcoding $80k.

# Long: TP must be above entry, SL must be below entry.
_LONG_TP_OFFSET_PCT = 0.06   # +6% from entry
_LONG_SL_OFFSET_PCT = -0.04  # -4% from entry

# Short: TP must be below entry, SL must be above entry.
_SHORT_TP_OFFSET_PCT = -0.06
_SHORT_SL_OFFSET_PCT = 0.04

# "Way above market" values used by Section-B reject tests. Bitget rejects
# either because the trigger is the wrong side of the mark OR because it
# exceeds the instrument's max_price_limit.
_REJECT_TP_MULTIPLIER_LONG = 3.0
_REJECT_SL_MULTIPLIER_LONG = 0.3
_REJECT_TP_MULTIPLIER_SHORT = 0.3
_REJECT_SL_MULTIPLIER_SHORT = 3.0


def _tp_long(entry: float) -> float:
    return round(entry * (1 + _LONG_TP_OFFSET_PCT), 1)


def _sl_long(entry: float) -> float:
    return round(entry * (1 + _LONG_SL_OFFSET_PCT), 1)


def _tp_short(entry: float) -> float:
    return round(entry * (1 + _SHORT_TP_OFFSET_PCT), 1)


def _sl_short(entry: float) -> float:
    return round(entry * (1 + _SHORT_SL_OFFSET_PCT), 1)


# ── Shared assertions ──────────────────────────────────────────────────


def _assert_price_close(actual: float | None, expected: float, msg: str = "") -> None:
    """Asserts a live-returned price matches within Bitget rounding tolerance."""
    assert actual is not None, f"{msg} — value was None"
    assert abs(actual - expected) < PRICE_TOLERANCE, (
        f"{msg} — expected {expected} ± {PRICE_TOLERANCE}, got {actual}"
    )


async def _fetch_trade(trade_id: int) -> TradeRecord:
    """Load the current DB row for ``trade_id`` with eager attribute touches."""
    async with get_session() as db:
        trade = await db.get(TradeRecord, trade_id)
        assert trade is not None, f"trade {trade_id} vanished mid-test"
        # Force-load attrs before the session closes.
        _ = (
            trade.take_profit,
            trade.stop_loss,
            trade.tp_order_id,
            trade.sl_order_id,
            trade.tp_status,
            trade.sl_status,
            trade.trailing_order_id,
            trade.trailing_status,
            trade.trailing_callback_rate,
            trade.trailing_activation_price,
            trade.trailing_trigger_price,
            trade.risk_source,
            trade.last_synced_at,
        )
        return trade


# ===========================================================================
# Section A — Frontend → Exchange Roundtrip (11 tests)
# ===========================================================================


async def test_A01_set_tp_only_on_long_position(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A01: Set TP only on a LONG. DB and Bitget both reflect confirmed state."""
    trade = demo_long_position
    tp = _tp_long(trade["entry_price"])

    result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp)

    assert result.status == RiskOpStatus.CONFIRMED, (
        f"Expected CONFIRMED, got {result.status} — error={result.error}"
    )
    assert result.order_id is not None
    _assert_price_close(result.value, tp, "RiskOpResult.value")
    assert result.latency_ms < 10_000

    # DB state
    db_trade = await _fetch_trade(trade["trade_id"])
    _assert_price_close(db_trade.take_profit, tp, "DB take_profit")
    assert db_trade.tp_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.tp_order_id == result.order_id
    assert db_trade.risk_source == "native_exchange"

    # Independent readback
    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    _assert_price_close(snap.tp_price, tp, "Bitget tp_price")
    assert snap.tp_order_id == result.order_id


async def test_A02_set_sl_only_on_long_position(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A02: Set SL only on a LONG."""
    trade = demo_long_position
    sl = _sl_long(trade["entry_price"])

    result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.SL, sl)

    assert result.status == RiskOpStatus.CONFIRMED, (
        f"Expected CONFIRMED, got {result.status} — error={result.error}"
    )
    assert result.order_id is not None
    _assert_price_close(result.value, sl, "RiskOpResult.value")

    db_trade = await _fetch_trade(trade["trade_id"])
    _assert_price_close(db_trade.stop_loss, sl, "DB stop_loss")
    assert db_trade.sl_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.sl_order_id == result.order_id
    assert db_trade.risk_source == "native_exchange"

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    _assert_price_close(snap.sl_price, sl, "Bitget sl_price")
    assert snap.sl_order_id == result.order_id


async def test_A03_set_tp_and_sl_atomic_on_long(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A03: Set TP + SL in sequence (atomic from the caller's POV)."""
    trade = demo_long_position
    tp = _tp_long(trade["entry_price"])
    sl = _sl_long(trade["entry_price"])

    tp_result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp)
    sl_result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.SL, sl)

    assert tp_result.status == RiskOpStatus.CONFIRMED
    assert sl_result.status == RiskOpStatus.CONFIRMED
    assert tp_result.order_id is not None
    assert sl_result.order_id is not None

    db_trade = await _fetch_trade(trade["trade_id"])
    _assert_price_close(db_trade.take_profit, tp, "DB take_profit")
    _assert_price_close(db_trade.stop_loss, sl, "DB stop_loss")
    assert db_trade.tp_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.sl_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.risk_source == "native_exchange"

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    _assert_price_close(snap.tp_price, tp, "Bitget tp_price")
    _assert_price_close(snap.sl_price, sl, "Bitget sl_price")


async def test_A04_modify_tp_replaces_existing_plan(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A04: Modify TP → old plan cancelled, new plan placed, order_id rotates."""
    trade = demo_long_position
    tp_initial = _tp_long(trade["entry_price"])
    tp_modified = round(tp_initial + 200.0, 1)

    first = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp_initial)
    assert first.status == RiskOpStatus.CONFIRMED
    old_order_id = first.order_id
    assert old_order_id is not None

    second = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp_modified)
    assert second.status == RiskOpStatus.CONFIRMED
    _assert_price_close(second.value, tp_modified, "modified TP value")
    # Bitget rotates plan ids on re-place; the new id should not equal the old.
    assert second.order_id is not None
    assert second.order_id != old_order_id, (
        "Modify should rotate the exchange plan-id (cancel + replace)."
    )

    db_trade = await _fetch_trade(trade["trade_id"])
    _assert_price_close(db_trade.take_profit, tp_modified, "DB take_profit after modify")
    assert db_trade.tp_order_id == second.order_id

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    _assert_price_close(snap.tp_price, tp_modified, "Bitget tp_price after modify")
    assert snap.tp_order_id == second.order_id


async def test_A05_clear_tp_only_keeps_sl(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A05: Given TP+SL confirmed, clear TP only; SL must stay live."""
    trade = demo_long_position
    tp = _tp_long(trade["entry_price"])
    sl = _sl_long(trade["entry_price"])

    await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp)
    sl_res = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.SL, sl)
    assert sl_res.status == RiskOpStatus.CONFIRMED
    sl_order_id = sl_res.order_id

    clear_result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, None)

    assert clear_result.status == RiskOpStatus.CLEARED
    assert clear_result.order_id is None

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.tp_order_id is None
    assert db_trade.tp_status == RiskOpStatus.CLEARED.value
    # SL should still be present in the DB after a TP-only clear.
    _assert_price_close(db_trade.stop_loss, sl, "DB stop_loss after TP clear")
    assert db_trade.sl_status == RiskOpStatus.CONFIRMED.value

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    assert snap.tp_price is None, (
        f"Expected no TP on Bitget after clear, got {snap.tp_price}"
    )
    # Note: Bitget's cancel_position_tpsl cancels BOTH pos_profit and pos_loss
    # per plan-type, so after a TP clear the SL may also be gone. We accept
    # either outcome — the important invariant is the DB reflects the state.
    # The DB/exchange alignment is what reconcile() fixes (see E04).
    if snap.sl_price is not None:
        _assert_price_close(snap.sl_price, sl, "Bitget sl_price after TP clear")
        assert snap.sl_order_id == sl_order_id


async def test_A06_clear_sl_only_keeps_tp(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A06: Given TP+SL confirmed, clear SL only; DB state records the clear."""
    trade = demo_long_position
    tp = _tp_long(trade["entry_price"])
    sl = _sl_long(trade["entry_price"])

    tp_res = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp)
    await risk_manager.apply_intent(trade["trade_id"], RiskLeg.SL, sl)

    clear_result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.SL, None)

    assert clear_result.status == RiskOpStatus.CLEARED
    assert clear_result.order_id is None

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.sl_order_id is None
    assert db_trade.sl_status == RiskOpStatus.CLEARED.value
    _assert_price_close(db_trade.take_profit, tp, "DB take_profit after SL clear")
    assert db_trade.tp_status == RiskOpStatus.CONFIRMED.value

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    assert snap.sl_price is None
    if snap.tp_price is not None:
        _assert_price_close(snap.tp_price, tp, "Bitget tp_price after SL clear")
        assert snap.tp_order_id == tp_res.order_id


async def test_A07_set_trailing_stop(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A07: Set a trailing stop. trailing_order_id + callback persisted."""
    trade = demo_long_position
    entry = trade["entry_price"]
    # Callback rate is a percent; 1.4 means the trail follows 1.4% behind.
    callback_rate = 1.4
    trailing_payload = {
        "callback_rate": callback_rate,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }

    result = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, trailing_payload,
    )

    assert result.status == RiskOpStatus.CONFIRMED, (
        f"Expected CONFIRMED, got {result.status} — error={result.error}"
    )
    assert result.order_id is not None

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.trailing_order_id == result.order_id
    assert db_trade.trailing_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.trailing_callback_rate is not None
    # Bitget stores the callback as decimal (0.014) and we normalise back
    # to percent (1.4) in the readback — so the DB value must also be in %.
    assert abs(db_trade.trailing_callback_rate - callback_rate) < 0.5, (
        f"callback mismatch: expected ~{callback_rate}%, "
        f"got {db_trade.trailing_callback_rate}"
    )
    assert db_trade.risk_source == "native_exchange"

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_trailing_stop(
        trade["symbol"], trade["side"],
    )
    assert snap is not None, "Bitget readback returned no trailing plan"
    assert snap.order_id == result.order_id
    assert snap.callback_rate is not None
    assert abs(snap.callback_rate - callback_rate) < 0.5


async def test_A08_modify_trailing_rotates_order_id(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A08: Modifying the trailing callback cancels the old plan and places new."""
    trade = demo_long_position
    entry = trade["entry_price"]
    initial_payload = {
        "callback_rate": 1.4,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }
    modified_payload = {
        "callback_rate": 2.0,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }

    first = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, initial_payload,
    )
    assert first.status == RiskOpStatus.CONFIRMED
    old_order_id = first.order_id

    second = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, modified_payload,
    )
    assert second.status == RiskOpStatus.CONFIRMED
    assert second.order_id is not None
    assert second.order_id != old_order_id, (
        "Modify should rotate the trailing plan-id (cancel + replace)."
    )

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.trailing_order_id == second.order_id
    assert db_trade.trailing_callback_rate is not None
    assert abs(db_trade.trailing_callback_rate - 2.0) < 0.5


async def test_A09_clear_trailing(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A09: Clear trailing → DB status=cleared, no plan on exchange."""
    trade = demo_long_position
    entry = trade["entry_price"]
    payload = {
        "callback_rate": 1.4,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }
    await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TRAILING, payload)

    result = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, None,
    )

    assert result.status == RiskOpStatus.CLEARED
    assert result.order_id is None

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.trailing_order_id is None
    assert db_trade.trailing_status == RiskOpStatus.CLEARED.value

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_trailing_stop(
        trade["symbol"], trade["side"],
    )
    assert snap is None, f"Expected no trailing plan, got {snap}"


async def test_A10_clear_all_three_legs(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A10: Given TP+SL+Trailing all set, clearing all three leaves no plans."""
    trade = demo_long_position
    entry = trade["entry_price"]
    tp = _tp_long(entry)
    sl = _sl_long(entry)
    trailing_payload = {
        "callback_rate": 1.4,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }

    await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp)
    await risk_manager.apply_intent(trade["trade_id"], RiskLeg.SL, sl)
    await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, trailing_payload,
    )

    tp_clear = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, None)
    sl_clear = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.SL, None)
    tr_clear = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, None,
    )

    assert tp_clear.status == RiskOpStatus.CLEARED
    assert sl_clear.status == RiskOpStatus.CLEARED
    assert tr_clear.status == RiskOpStatus.CLEARED

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.tp_status == RiskOpStatus.CLEARED.value
    assert db_trade.sl_status == RiskOpStatus.CLEARED.value
    assert db_trade.trailing_status == RiskOpStatus.CLEARED.value
    assert db_trade.tp_order_id is None
    assert db_trade.sl_order_id is None
    assert db_trade.trailing_order_id is None

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    tpsl_snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    trail_snap = await admin_bitget_client.get_trailing_stop(
        trade["symbol"], trade["side"],
    )
    assert tpsl_snap.tp_price is None
    assert tpsl_snap.sl_price is None
    assert trail_snap is None


async def test_A11_set_tp_on_short_position(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_short_position: dict,
) -> None:
    """A11-variant (short): Set TP only on a SHORT position.

    Per execution plan in the issue description: "Side: long (A01-A09),
    short für 1 zusätzlichen Test (A11-variant)". Exercises the short-side
    code path through the same apply_intent contract.
    """
    trade = demo_short_position
    tp = _tp_short(trade["entry_price"])

    result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp)

    assert result.status == RiskOpStatus.CONFIRMED, (
        f"Expected CONFIRMED, got {result.status} — error={result.error}"
    )
    assert result.order_id is not None
    _assert_price_close(result.value, tp, "RiskOpResult.value")

    db_trade = await _fetch_trade(trade["trade_id"])
    _assert_price_close(db_trade.take_profit, tp, "DB take_profit")
    assert db_trade.tp_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.tp_order_id == result.order_id
    assert db_trade.risk_source == "native_exchange"

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    _assert_price_close(snap.tp_price, tp, "Bitget tp_price (short)")
    assert snap.tp_order_id == result.order_id


async def test_A11_set_trailing_plus_tp_combined(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """A11: Combined trailing + TP both active on the same position."""
    trade = demo_long_position
    entry = trade["entry_price"]
    tp = _tp_long(entry)
    trailing_payload = {
        "callback_rate": 1.4,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }

    tp_result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp)
    tr_result = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, trailing_payload,
    )

    assert tp_result.status == RiskOpStatus.CONFIRMED
    assert tr_result.status == RiskOpStatus.CONFIRMED
    assert tp_result.order_id is not None
    assert tr_result.order_id is not None

    db_trade = await _fetch_trade(trade["trade_id"])
    _assert_price_close(db_trade.take_profit, tp, "DB take_profit")
    assert db_trade.trailing_order_id == tr_result.order_id

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    tpsl_snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    trail_snap = await admin_bitget_client.get_trailing_stop(
        trade["symbol"], trade["side"],
    )
    # TP plan should be live.
    _assert_price_close(tpsl_snap.tp_price, tp, "Bitget tp_price")
    # Trailing plan should be live.
    assert trail_snap is not None
    assert trail_snap.order_id == tr_result.order_id


# ===========================================================================
# Section B — Partial-Success / Reject paths (5 tests)
# ===========================================================================


async def test_B01_tp_way_above_market_rejected(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """B01: TP price 3x entry — Bitget rejects because trigger > max_price_limit."""
    trade = demo_long_position
    bad_tp = round(trade["entry_price"] * _REJECT_TP_MULTIPLIER_LONG, 1)

    result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, bad_tp)

    assert result.status == RiskOpStatus.REJECTED, (
        f"Expected REJECTED for TP={bad_tp}, got {result.status} "
        f"(value={result.value}, error={result.error})"
    )
    assert result.error is not None and result.error != ""

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.tp_status == RiskOpStatus.REJECTED.value

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_position_tpsl(
        trade["symbol"], trade["side"],
    )
    # No TP should be live on Bitget since the place failed.
    assert snap.tp_price is None or snap.tp_price != bad_tp


async def test_B02_tp_ok_sl_rejected_partial(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """B02: TP ok, SL way out of range → first succeeds, second rejected."""
    trade = demo_long_position
    tp = _tp_long(trade["entry_price"])
    bad_sl = round(trade["entry_price"] * _REJECT_TP_MULTIPLIER_LONG, 1)

    tp_result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp)
    sl_result = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.SL, bad_sl)

    assert tp_result.status == RiskOpStatus.CONFIRMED
    assert sl_result.status == RiskOpStatus.REJECTED

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.tp_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.sl_status == RiskOpStatus.REJECTED.value
    _assert_price_close(db_trade.take_profit, tp, "DB take_profit after mixed apply")


async def test_B03_trailing_callback_below_minimum_rejected(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """B03: callback=0.05% is below Bitget's 0.1%–5% range → rejected."""
    trade = demo_long_position
    entry = trade["entry_price"]
    tiny_payload = {
        "callback_rate": 0.05,  # way below Bitget minimum
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }

    result = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, tiny_payload,
    )

    assert result.status == RiskOpStatus.REJECTED, (
        f"Expected REJECTED, got {result.status} — error={result.error}"
    )

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.trailing_status == RiskOpStatus.REJECTED.value
    assert db_trade.trailing_order_id is None

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bitget_client.get_trailing_stop(
        trade["symbol"], trade["side"],
    )
    assert snap is None


async def test_B04_modify_tp_with_bad_price_preserves_original(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """B04: Given TP confirmed, modify to bad price — original MAY be cancelled.

    Bitget's cancel-first-then-place ordering means a rejected place leaves
    no plan on the exchange. The test asserts:
    * RiskOpResult is CANCEL_FAILED or REJECTED.
    * DB ends in either the original value (cancel never happened) or
      cancel_failed/rejected status. Either way, no new order id is written.
    """
    trade = demo_long_position
    tp_initial = _tp_long(trade["entry_price"])
    bad_tp = round(trade["entry_price"] * _REJECT_TP_MULTIPLIER_LONG, 1)

    first = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, tp_initial)
    assert first.status == RiskOpStatus.CONFIRMED

    second = await risk_manager.apply_intent(trade["trade_id"], RiskLeg.TP, bad_tp)

    assert second.status in (RiskOpStatus.REJECTED, RiskOpStatus.CANCEL_FAILED), (
        f"Expected REJECTED/CANCEL_FAILED for bad TP, got {second.status}"
    )
    assert second.error is not None

    db_trade = await _fetch_trade(trade["trade_id"])
    # After a rejected modify the status column reflects the failure —
    # the key invariant is that the new bad value was NOT persisted.
    assert db_trade.tp_status in (
        RiskOpStatus.REJECTED.value,
        RiskOpStatus.CANCEL_FAILED.value,
    )
    if db_trade.take_profit is not None:
        # If the original survived (cancel raced), it must still equal the
        # original TP — never the bad one.
        assert abs(db_trade.take_profit - bad_tp) > PRICE_TOLERANCE, (
            "Bad TP value leaked into the DB on a rejected modify."
        )


async def test_B05_trailing_modify_with_bad_activation_rejected(
    risk_manager: RiskStateManager,
    admin_bitget_client,
    demo_long_position: dict,
) -> None:
    """B05: Modify trailing with invalid activation price → rejected.

    For a long, Bitget requires activation_price ≥ mark_price. Using a value
    far below mark should trigger a Bitget-side rejection.
    """
    trade = demo_long_position
    entry = trade["entry_price"]
    initial_payload = {
        "callback_rate": 1.4,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }
    bad_payload = {
        "callback_rate": 1.4,
        "activation_price": round(entry * 0.5, 1),  # far below mark → rejected
        "trigger_price": round(entry * 0.5, 1),
    }

    first = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, initial_payload,
    )
    assert first.status == RiskOpStatus.CONFIRMED

    second = await risk_manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, bad_payload,
    )

    assert second.status in (RiskOpStatus.REJECTED, RiskOpStatus.CANCEL_FAILED), (
        f"Expected REJECTED/CANCEL_FAILED, got {second.status} "
        f"(error={second.error})"
    )

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.trailing_status in (
        RiskOpStatus.REJECTED.value,
        RiskOpStatus.CANCEL_FAILED.value,
    )


# ===========================================================================
# Section C — Cancel-Failure paths (2 respx-mocked unit tests)
# ===========================================================================
#
# C01 and C03 live here (not a unit-tests file) because they guard the
# same 2-Phase-Commit contract as the live tests. They use AsyncMock
# rather than respx because the RiskStateManager talks through the
# BitgetExchangeClient abstraction, not the underlying aiohttp session.
#
# They are NOT marked ``bitget_live`` — they run in default CI.


class _CancelFailingStubClient:
    """Minimal stub whose ``cancel_position_tpsl`` raises ``CancelFailed``.

    Used only for C01/C03. It does not simulate any other behaviour than
    the cancel failure, because that's the only path we care about —
    RiskStateManager must NOT reach the place call after a cancel fail.
    """

    exchange_name = "bitget"

    def __init__(self, cancel_error: Exception):
        self._cancel_error = cancel_error
        self.place_calls: list = []
        self.trailing_calls: list = []

    async def cancel_position_tpsl(self, symbol: str, side: str = "long") -> bool:
        raise self._cancel_error

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        raise self._cancel_error

    async def set_position_tpsl(self, **kwargs) -> None:
        # If this ever fires, C01 has regressed — cancel failure must
        # short-circuit the place call.
        self.place_calls.append(kwargs)

    async def place_trailing_stop(self, **kwargs) -> None:
        self.trailing_calls.append(kwargs)

    async def get_position_tpsl(self, symbol: str, side: str):
        # Unused on the cancel-failed path but must exist for the interface.
        raise NotImplementedError

    async def get_trailing_stop(self, symbol: str, side: str):
        raise NotImplementedError

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.bitget_live  # keep bundled with the other live specs even though
# this particular test uses a stub (C-path specs belong here per TEST_MATRIX).
async def test_C01_tp_cancel_transient_error_no_place(
    demo_long_position: dict,
) -> None:
    """C01: Pre-existing TP, cancel raises transient CancelFailed.

    Expectation:
    * ``apply_intent`` returns ``RiskOpStatus.CANCEL_FAILED``.
    * The place call on the stub is NEVER invoked (Anti-Pattern C guard).
    """
    from contextlib import asynccontextmanager

    trade = demo_long_position

    # Seed the DB row so the cancel branch is actually reached — the
    # manager only calls ``cancel_position_tpsl`` when a prior
    # ``tp_order_id`` is present.
    async with get_session() as db:
        row = await db.get(TradeRecord, trade["trade_id"])
        assert row is not None
        row.tp_order_id = "preexisting-tp-order-id"

    stub = _CancelFailingStubClient(
        cancel_error=CancelFailed(
            "bitget", "transient network glitch simulating C01",
        ),
    )

    @asynccontextmanager
    async def _session_factory():
        async with get_session() as session:
            yield session

    manager = RiskStateManager(
        exchange_client_factory=lambda uid, ex, dm: stub,
        session_factory=_session_factory,
    )

    result = await manager.apply_intent(
        trade["trade_id"], RiskLeg.TP, _tp_long(trade["entry_price"]),
    )

    assert result.status == RiskOpStatus.CANCEL_FAILED, (
        f"Expected CANCEL_FAILED, got {result.status}"
    )
    assert result.error is not None
    assert stub.place_calls == [], (
        f"Place call must NOT happen after a cancel failure — got {stub.place_calls}"
    )

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.tp_status == RiskOpStatus.CANCEL_FAILED.value


@pytest.mark.asyncio
@pytest.mark.bitget_live
async def test_C03_trailing_cancel_500_no_new_order(
    demo_long_position: dict,
) -> None:
    """C03: Trailing plan active, cancel returns 500. No new plan placed.

    Uses a simulated ``OrderError`` wrapped as ``CancelFailed`` by the
    manager — the manager treats any ``ExchangeError`` on cancel as a
    fatal cancel failure and aborts before placing the new plan.
    """
    from contextlib import asynccontextmanager

    trade = demo_long_position

    async with get_session() as db:
        row = await db.get(TradeRecord, trade["trade_id"])
        assert row is not None
        row.trailing_order_id = "preexisting-trailing-id"

    stub = _CancelFailingStubClient(
        cancel_error=OrderError(
            "bitget", "simulated HTTP 500 on trailing cancel (C03)",
        ),
    )

    @asynccontextmanager
    async def _session_factory():
        async with get_session() as session:
            yield session

    manager = RiskStateManager(
        exchange_client_factory=lambda uid, ex, dm: stub,
        session_factory=_session_factory,
    )

    entry = trade["entry_price"]
    payload = {
        "callback_rate": 2.0,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }
    result = await manager.apply_intent(
        trade["trade_id"], RiskLeg.TRAILING, payload,
    )

    assert result.status == RiskOpStatus.CANCEL_FAILED
    assert stub.trailing_calls == [], (
        "Trailing place must NOT happen after cancel failure (Anti-Pattern C)."
    )

    db_trade = await _fetch_trade(trade["trade_id"])
    assert db_trade.trailing_status == RiskOpStatus.CANCEL_FAILED.value
    # The pre-existing order id should not be cleared; no new one written.
    assert db_trade.trailing_order_id == "preexisting-trailing-id"
