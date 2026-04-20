"""Unit tests for :meth:`RiskStateManager.classify_close` (Issue #193, Epic #188).

Covers the 12 scenarios from TEST_MATRIX.md section F plus a handful of
additional helper tests for ``ExitReason`` and the heuristic guard.

The test strategy mirrors ``test_risk_state_manager.py``: in-memory SQLite
with real ``TradeRecord`` rows, plus a configurable fake exchange client
that records every probe call so we can assert on the expected API usage.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.risk_reasons import (
    ExitReason,
    is_manual_exit,
    is_native_exit,
    is_software_exit,
)
from src.bot.risk_state_manager import RiskOpStatus, RiskStateManager
from src.exceptions import ExchangeError
from src.exchanges.base import CloseReasonSnapshot
from src.models.database import Base, TradeRecord, User


# ---------------------------------------------------------------------------
# Fixtures — DB + seeded trade
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory async SQLite per test (isolated, deterministic)."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory_cb(engine):
    """Return a zero-arg callable that yields an ``AsyncSession``."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _factory():
        async with maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    return _factory


@pytest_asyncio.fixture
async def seed_trade(engine):
    """Seed an open LONG BTCUSDT trade with *no* TP/SL/trailing set.

    Returns a ``(trade_id, session_maker)`` pair so individual tests can
    customize fields (order ids, status values, etc.) before classifying.
    """
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user = User(
            username="cls-tester",
            email="cls@example.com",
            password_hash="x",
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        trade = TradeRecord(
            user_id=user.id,
            exchange="bitget",
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=68200.0,
            leverage=10,
            confidence=80,
            reason="classify test fixture",
            order_id="entry_001",
            status="open",
            entry_time=datetime(2026, 4, 18, 9, 0, tzinfo=timezone.utc),
            demo_mode=True,
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)
        return trade.id, maker


async def _patch_trade(maker, trade_id: int, **fields) -> None:
    """Apply ``fields`` as attribute updates on the trade row."""
    async with maker() as session:
        trade = await session.get(TradeRecord, trade_id)
        for key, value in fields.items():
            setattr(trade, key, value)
        await session.commit()


# ---------------------------------------------------------------------------
# Fake exchange client — records probe calls & simulates outcomes
# ---------------------------------------------------------------------------


@dataclass
class FakeClassifierClient:
    """Minimal exchange double for classify_close probing.

    Flags:
    * ``probe_raises``            → raise this from get_close_reason_from_history.
    * ``probe_not_implemented``   → raise NotImplementedError (Weex/Bitunix case).
    * ``snapshot``                → value returned by the probe (None simulates
      "history has no qualifying close").
    """

    snapshot: Optional[CloseReasonSnapshot] = None
    probe_raises: Optional[Exception] = None
    probe_not_implemented: bool = False
    probe_calls: List[tuple] = field(default_factory=list)
    close_calls: int = 0

    async def get_close_reason_from_history(
        self,
        symbol: str,
        since_ts_ms: int,
        until_ts_ms: Optional[int] = None,
    ) -> Optional[CloseReasonSnapshot]:
        self.probe_calls.append((symbol, since_ts_ms, until_ts_ms))
        if self.probe_not_implemented:
            raise NotImplementedError(
                "FakeClassifierClient simulates adapter without probe support",
            )
        if self.probe_raises is not None:
            raise self.probe_raises
        return self.snapshot

    async def close(self) -> None:
        self.close_calls += 1


def _factory_returning(client: FakeClassifierClient):
    """Return a simple factory handing back the fake client."""

    def _f(user_id: int, exchange: str, demo_mode: bool) -> FakeClassifierClient:
        return client

    return _f


# ---------------------------------------------------------------------------
# Helpers for building CloseReasonSnapshot variants
# ---------------------------------------------------------------------------


def _snap(
    plan_type: Optional[str] = None,
    order_id: Optional[str] = None,
    trigger_type: Optional[str] = None,
    fill_price: Optional[float] = 68500.0,
) -> CloseReasonSnapshot:
    return CloseReasonSnapshot(
        symbol="BTCUSDT",
        closed_by_order_id=order_id,
        closed_by_plan_type=plan_type,
        closed_by_trigger_type=trigger_type,
        closed_at=datetime(2026, 4, 18, 9, 5, tzinfo=timezone.utc),
        fill_price=fill_price,
    )


# ===========================================================================
# Scenario 1: closed_by_order_id matches trailing_order_id → TRAILING_STOP_NATIVE
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_1_trailing_order_id_match_yields_trailing_native(
    seed_trade, session_factory_cb,
):
    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, trailing_order_id="trail_99")

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="track_plan", order_id="trail_99"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=68500.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.TRAILING_STOP_NATIVE.value
    assert client.probe_calls, "probe must run before heuristic falls back"


# ===========================================================================
# Scenario 2: closed_by_order_id matches tp_order_id → TAKE_PROFIT_NATIVE
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_2_tp_order_id_match_yields_take_profit_native(
    seed_trade, session_factory_cb,
):
    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, tp_order_id="tp_42", take_profit=70000.0)

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="pos_profit", order_id="tp_42"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=70000.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.TAKE_PROFIT_NATIVE.value


# ===========================================================================
# Scenario 3: closed_by_order_id matches sl_order_id → STOP_LOSS_NATIVE
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_3_sl_order_id_match_yields_stop_loss_native(
    seed_trade, session_factory_cb,
):
    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, sl_order_id="sl_7", stop_loss=67000.0)

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="pos_loss", order_id="sl_7"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=67000.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.STOP_LOSS_NATIVE.value


# ===========================================================================
# Scenario 4: plan_type=track_plan, no order_id match → TRAILING_STOP_NATIVE
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_4_plan_type_track_plan_without_order_match_yields_trailing_native(
    seed_trade, session_factory_cb,
):
    trade_id, maker = seed_trade
    # Old trailing order id that got rotated when the user edited the plan —
    # the closing order id no longer matches anything we stored.
    await _patch_trade(maker, trade_id, trailing_order_id="old_trail_id")

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="track_plan", order_id="new_trail_id_unknown"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=68500.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.TRAILING_STOP_NATIVE.value


# ===========================================================================
# Scenario 5: plan_type=manual → MANUAL_CLOSE_EXCHANGE
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_5_plan_type_manual_yields_manual_close_exchange(
    seed_trade, session_factory_cb,
):
    trade_id, _ = seed_trade

    client = FakeClassifierClient(snapshot=_snap(plan_type="manual", order_id="manual_order_123"))
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=68500.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.MANUAL_CLOSE_EXCHANGE.value


# ===========================================================================
# Scenario 6: plan_type=liquidation → LIQUIDATION
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_6_plan_type_liquidation_yields_liquidation(
    seed_trade, session_factory_cb,
):
    trade_id, _ = seed_trade

    client = FakeClassifierClient(snapshot=_snap(plan_type="liquidation"))
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=50000.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.LIQUIDATION.value


# ===========================================================================
# Scenario 7: risk_source=software_bot + trailing confirmed + no match
#             → TRAILING_STOP_SOFTWARE
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_7_software_bot_with_confirmed_trail_yields_trailing_software(
    seed_trade, session_factory_cb,
):
    trade_id, maker = seed_trade
    await _patch_trade(
        maker, trade_id,
        risk_source="software_bot",
        trailing_status=RiskOpStatus.CONFIRMED.value,
    )

    # Snapshot returned but with no order-id match and no recognized plan_type.
    client = FakeClassifierClient(
        snapshot=_snap(plan_type=None, order_id="random_unknown"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=68500.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.TRAILING_STOP_SOFTWARE.value


# ===========================================================================
# Scenario 8: strategy_exit cache hit → STRATEGY_EXIT (overrides everything)
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_8_strategy_exit_mark_within_window_overrides_snapshot(
    seed_trade, session_factory_cb,
):
    trade_id, maker = seed_trade
    # Pre-load fields that would otherwise classify as TAKE_PROFIT_NATIVE.
    await _patch_trade(maker, trade_id, tp_order_id="tp_99", take_profit=70000.0)

    # Even if the probe returns a TP-match, note_strategy_exit wins.
    client = FakeClassifierClient(
        snapshot=_snap(plan_type="pos_profit", order_id="tp_99"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    manager.note_strategy_exit(trade_id)
    reason = await manager.classify_close(
        trade_id, exit_price=70000.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.STRATEGY_EXIT.value
    # Probe must NOT have been called — strategy signal short-circuits Phase 2.
    assert client.probe_calls == [], "probe should short-circuit on strategy hit"


# ===========================================================================
# Scenario 9: snap=None (no history entry) → heuristic TRAILING_STOP_NATIVE
#             when native_trailing_stop=True on the trade
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_9_no_snapshot_falls_back_to_heuristic_trailing(
    seed_trade, session_factory_cb,
):
    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, native_trailing_stop=True)

    client = FakeClassifierClient(snapshot=None)
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=68500.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.TRAILING_STOP_NATIVE.value
    assert client.probe_calls, "probe must be attempted before heuristic"


# ===========================================================================
# Scenario 10: exchange raises NotImplementedError (Weex/Bitunix)
#              → heuristic fallback
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_10_not_implemented_probe_uses_heuristic(
    seed_trade, session_factory_cb,
):
    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, take_profit=70000.0)

    client = FakeClassifierClient(probe_not_implemented=True)
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    # exit_price is very close to take_profit → heuristic → TAKE_PROFIT_NATIVE.
    reason = await manager.classify_close(
        trade_id, exit_price=69995.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.TAKE_PROFIT_NATIVE.value


# ===========================================================================
# Scenario 11: exchange raises ExchangeError → heuristic fallback + WARN log
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_11_exchange_error_falls_back_with_warning(
    seed_trade, session_factory_cb, caplog,
):
    import logging

    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, stop_loss=67000.0)

    client = FakeClassifierClient(
        probe_raises=ExchangeError("bitget", "simulated 5xx"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    caplog.set_level(logging.WARNING, logger="src.bot.risk_state_manager")
    reason = await manager.classify_close(
        trade_id, exit_price=67005.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.STOP_LOSS_NATIVE.value
    warn_messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "classify_close.exchange_error" in m for m in warn_messages
    ), warn_messages


# ===========================================================================
# Scenario 12: trade.id invalid → EXTERNAL_CLOSE_UNKNOWN
# ===========================================================================


@pytest.mark.asyncio
async def test_scenario_12_missing_trade_returns_external_close_unknown(
    session_factory_cb,
):
    client = FakeClassifierClient()
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id=9_999_999,
        exit_price=68500.0,
        exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.EXTERNAL_CLOSE_UNKNOWN.value
    # Nothing to probe — we short-circuit before touching the exchange.
    assert client.probe_calls == []


# ===========================================================================
# Issue #224 — TP/SL crossover disambiguation
# (Hyperliquid tpsl_ambiguous + oid-unmatched pos_profit/pos_loss)
# ===========================================================================


@pytest.mark.asyncio
async def test_tpsl_ambiguous_long_fill_above_tp_yields_take_profit(
    seed_trade, session_factory_cb,
):
    """LONG, fill_price >= take_profit, ambiguous plan_type → TAKE_PROFIT_NATIVE."""
    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, take_profit=70000.0, stop_loss=66000.0)

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="tpsl_ambiguous", order_id="hl-fill-no-match", fill_price=70123.0),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=70123.0, exit_time=datetime.now(timezone.utc),
    )
    assert reason == ExitReason.TAKE_PROFIT_NATIVE.value


@pytest.mark.asyncio
async def test_tpsl_ambiguous_long_fill_below_sl_yields_stop_loss(
    seed_trade, session_factory_cb,
):
    """LONG, fill_price <= stop_loss, ambiguous plan_type → STOP_LOSS_NATIVE."""
    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, take_profit=70000.0, stop_loss=66000.0)

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="tpsl_ambiguous", order_id="hl-fill-no-match", fill_price=65800.0),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=65800.0, exit_time=datetime.now(timezone.utc),
    )
    assert reason == ExitReason.STOP_LOSS_NATIVE.value


@pytest.mark.asyncio
async def test_tpsl_ambiguous_short_fill_below_tp_yields_take_profit(
    seed_trade, session_factory_cb,
):
    """SHORT inverts: fill_price <= take_profit → TAKE_PROFIT_NATIVE."""
    trade_id, maker = seed_trade
    await _patch_trade(
        maker, trade_id, side="short", take_profit=66000.0, stop_loss=70000.0,
    )

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="tpsl_ambiguous", order_id="hl-fill", fill_price=65500.0),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=65500.0, exit_time=datetime.now(timezone.utc),
    )
    assert reason == ExitReason.TAKE_PROFIT_NATIVE.value


@pytest.mark.asyncio
async def test_pos_loss_without_oid_match_crossover_disambiguates(
    seed_trade, session_factory_cb,
):
    """pos_loss from adapter but oid doesn't match — crossover still returns SL."""
    trade_id, maker = seed_trade
    await _patch_trade(
        maker, trade_id, stop_loss=66000.0, sl_order_id="stored-sl-oid",
    )

    # Snap's closed_by_order_id is "different-fill-oid" → fails oid match.
    # plan_type pos_loss is authoritative but crossover should confirm.
    client = FakeClassifierClient(
        snapshot=_snap(plan_type="pos_loss", order_id="different-fill-oid", fill_price=65900.0),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=65900.0, exit_time=datetime.now(timezone.utc),
    )
    assert reason == ExitReason.STOP_LOSS_NATIVE.value


@pytest.mark.asyncio
async def test_tpsl_ambiguous_without_targets_falls_through(
    seed_trade, session_factory_cb,
):
    """Ambiguous plan_type + no TP/SL targets → falls through to UNKNOWN.

    Guards against crossover silently returning a wrong answer when the
    trade row has no stored targets to compare against.
    """
    trade_id, maker = seed_trade
    # Leave take_profit / stop_loss at seed default (None)

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="tpsl_ambiguous", order_id="no-match", fill_price=70000.0),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=70000.0, exit_time=datetime.now(timezone.utc),
    )
    assert reason == ExitReason.EXTERNAL_CLOSE_UNKNOWN.value


# ===========================================================================
# Additional guards for the classifier contract
# ===========================================================================


@pytest.mark.asyncio
async def test_strategy_exit_mark_outside_window_does_not_override(
    seed_trade, session_factory_cb, monkeypatch,
):
    """Stale strategy-exit marks (>60s old) must not win over a probe result."""
    import src.bot.risk_state_manager as rsm_mod

    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, tp_order_id="tp_9", take_profit=70000.0)

    client = FakeClassifierClient(
        snapshot=_snap(plan_type="pos_profit", order_id="tp_9"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    manager.note_strategy_exit(trade_id)

    # Jump time past the window.
    base = rsm_mod.time.monotonic()
    monkeypatch.setattr(rsm_mod.time, "monotonic", lambda: base + 120.0)

    reason = await manager.classify_close(
        trade_id, exit_price=70000.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.TAKE_PROFIT_NATIVE.value
    # Stale mark must be evicted to keep the cache bounded.
    assert trade_id not in manager._strategy_exit_marks


@pytest.mark.asyncio
async def test_probe_matches_order_id_before_plan_type(
    seed_trade, session_factory_cb,
):
    """Order-id match is more precise than plan_type — it must win."""
    trade_id, maker = seed_trade
    # Trade tracks a TP order_id only.
    await _patch_trade(
        maker, trade_id,
        tp_order_id="tp_exact",
        take_profit=70000.0,
        trailing_order_id=None,
    )

    # Snapshot contradicts plan_type vs. order_id: plan says track_plan, but
    # the id matches our TP. The id is authoritative.
    client = FakeClassifierClient(
        snapshot=_snap(plan_type="track_plan", order_id="tp_exact"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=70000.0, exit_time=datetime.now(timezone.utc),
    )

    assert reason == ExitReason.TAKE_PROFIT_NATIVE.value


@pytest.mark.asyncio
async def test_classify_close_closes_exchange_client_in_finally(
    seed_trade, session_factory_cb,
):
    """Exchange client must be closed even when the probe errors out."""
    trade_id, _ = seed_trade

    client = FakeClassifierClient(probe_raises=RuntimeError("boom"))
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    await manager.classify_close(
        trade_id, exit_price=68500.0, exit_time=datetime.now(timezone.utc),
    )

    assert client.close_calls == 1, "client.close() must run exactly once"


@pytest.mark.asyncio
async def test_classify_close_client_factory_error_falls_back_to_heuristic(
    seed_trade, session_factory_cb,
):
    """When the exchange-client factory itself raises, we must still land on
    a heuristic-derived ExitReason instead of letting the exception bubble up.
    """
    trade_id, maker = seed_trade
    await _patch_trade(maker, trade_id, take_profit=70000.0)

    def _failing_factory(user_id: int, exchange: str, demo_mode: bool):
        raise RuntimeError("no credentials")

    manager = RiskStateManager(_failing_factory, session_factory_cb)

    reason = await manager.classify_close(
        trade_id, exit_price=69998.0, exit_time=datetime.now(timezone.utc),
    )

    # Heuristic proximity → TAKE_PROFIT_NATIVE (exit_price within 0.2% of TP).
    assert reason == ExitReason.TAKE_PROFIT_NATIVE.value


# ---------------------------------------------------------------------------
# ExitReason helper tests
# ---------------------------------------------------------------------------


def test_is_native_exit_recognizes_precise_codes():
    assert is_native_exit(ExitReason.TRAILING_STOP_NATIVE.value)
    assert is_native_exit(ExitReason.TAKE_PROFIT_NATIVE.value)
    assert is_native_exit(ExitReason.STOP_LOSS_NATIVE.value)
    assert is_native_exit(ExitReason.MANUAL_CLOSE_EXCHANGE.value)
    assert is_native_exit(ExitReason.LIQUIDATION.value)
    assert is_native_exit(ExitReason.FUNDING_EXPIRY.value)


def test_is_native_exit_rejects_software_and_legacy_codes():
    assert not is_native_exit(ExitReason.TRAILING_STOP_SOFTWARE.value)
    assert not is_native_exit(ExitReason.STRATEGY_EXIT.value)
    # Legacy strings are ambiguous — not classified as native.
    assert not is_native_exit("TRAILING_STOP")
    assert not is_native_exit("TAKE_PROFIT")


def test_is_software_exit_distinguishes_bot_from_exchange():
    assert is_software_exit(ExitReason.TRAILING_STOP_SOFTWARE.value)
    assert is_software_exit(ExitReason.STRATEGY_EXIT.value)
    assert not is_software_exit(ExitReason.TRAILING_STOP_NATIVE.value)


def test_is_manual_exit_covers_both_ui_paths_and_legacy():
    assert is_manual_exit(ExitReason.MANUAL_CLOSE_UI.value)
    assert is_manual_exit(ExitReason.MANUAL_CLOSE_EXCHANGE.value)
    assert is_manual_exit("MANUAL_CLOSE")  # legacy
    assert not is_manual_exit(ExitReason.STRATEGY_EXIT.value)
    assert not is_manual_exit(ExitReason.LIQUIDATION.value)


def test_exit_reason_string_value_matches_i18n_key():
    """Enum values must round-trip as plain strings for DB/i18n interop."""
    # A regression here means the frontend's exitReasons map breaks.
    assert ExitReason.TRAILING_STOP_NATIVE == "TRAILING_STOP_NATIVE"
    assert str(ExitReason.TAKE_PROFIT_NATIVE.value) == "TAKE_PROFIT_NATIVE"
