"""Unit tests for :mod:`src.bot.risk_state_manager` (Issue #190).

These tests verify the 2-Phase-Commit contract:

* Phase A writes intent + ``*_status=pending`` before talking to the
  exchange.
* Phase B respects the cancel-before-place ordering and refuses to
  place a new order when the cancel fails (Anti-Pattern C).
* Phase C's probe result is ALWAYS written back to the DB in Phase D
  (Anti-Pattern A).
* Concurrent callers serialize through the per-(trade, leg) lock.
* ``reconcile`` pulls exchange state and heals DB drift.

The tests use an in-memory SQLite DB with the real TradeRecord model
so assertions hit actual columns, not mock call records.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.risk_state_manager import (
    RiskLeg,
    RiskOpStatus,
    RiskStateManager,
    RiskStateSnapshot,
)
from src.exceptions import OrderError
from src.exchanges.base import PositionTpSlSnapshot, TrailingStopSnapshot
from src.models.database import Base, TradeRecord, User


# ---------------------------------------------------------------------------
# Fixtures
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
    """Return a zero-arg callable that yields an ``AsyncSession``.

    The RiskStateManager expects ``session_factory()`` to be an async
    context manager, so we wrap ``async_sessionmaker`` accordingly.
    """
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
async def open_trade(engine):
    """Seed an open LONG BTCUSDT trade and return its id + shape."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user = User(
            username="rsm-tester",
            email="rsm@example.com",
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
            reason="rsm test fixture",
            order_id="entry_001",
            status="open",
            entry_time=datetime.now(timezone.utc),
            demo_mode=True,
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)
        return trade.id


# ---------------------------------------------------------------------------
# Fake exchange client
# ---------------------------------------------------------------------------


@dataclass
class FakeExchangeClient:
    """Minimal stateful exchange double tuned for the 2PC flow.

    Configurable flags:
    * ``cancel_raises``     → ``cancel_position_tpsl`` raises.
    * ``place_raises``      → ``set_position_tpsl`` raises.
    * ``readback_tp``       → readback returns this TP price.
    * ``readback_sl``       → readback returns this SL price.
    * ``readback_tp_id``    → readback TP order id.
    * ``readback_sl_id``    → readback SL order id.
    * ``place_returns``     → value returned by the place call.
    * ``raise_not_impl_readback`` → readback raises ``NotImplementedError``.
    """

    exchange_name: str = "fake"

    cancel_raises: Optional[Exception] = None
    place_raises: Optional[Exception] = None
    trailing_place_raises: Optional[Exception] = None

    readback_tp: Optional[float] = None
    readback_sl: Optional[float] = None
    readback_tp_id: Optional[str] = None
    readback_sl_id: Optional[str] = None
    readback_trailing_callback: Optional[float] = None
    readback_trailing_activation: Optional[float] = None
    readback_trailing_trigger: Optional[float] = None
    readback_trailing_id: Optional[str] = None

    place_returns: Any = None
    trailing_place_returns: Any = None
    raise_not_impl_readback: bool = False

    # Call tracking
    cancel_calls: List[tuple] = field(default_factory=list)
    place_calls: List[dict] = field(default_factory=list)
    trailing_calls: List[dict] = field(default_factory=list)
    cancel_order_calls: List[tuple] = field(default_factory=list)
    readback_calls: List[tuple] = field(default_factory=list)

    async def cancel_position_tpsl(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "all"))
        if self.cancel_raises is not None:
            raise self.cancel_raises
        return True

    async def cancel_tp_only(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "tp_only"))
        if self.cancel_raises is not None:
            raise self.cancel_raises
        return True

    async def cancel_sl_only(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "sl_only"))
        if self.cancel_raises is not None:
            raise self.cancel_raises
        return True

    async def cancel_native_trailing_stop(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "trailing_only"))
        if self.cancel_raises is not None:
            raise self.cancel_raises
        return True

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        self.cancel_order_calls.append((symbol, order_id))
        if self.cancel_raises is not None:
            raise self.cancel_raises
        return True

    async def set_position_tpsl(
        self,
        symbol: str,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        side: str = "long",
        size: float = 0,
        **_,
    ) -> Any:
        self.place_calls.append(
            {
                "symbol": symbol,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "side": side,
                "size": size,
            }
        )
        if self.place_raises is not None:
            raise self.place_raises
        return self.place_returns

    async def place_trailing_stop(
        self,
        symbol: str,
        hold_side: str,
        size: float,
        callback_ratio: float,
        trigger_price: float,
        margin_mode: str = "cross",
    ) -> Any:
        self.trailing_calls.append(
            {
                "symbol": symbol,
                "hold_side": hold_side,
                "size": size,
                "callback_ratio": callback_ratio,
                "trigger_price": trigger_price,
            }
        )
        if self.trailing_place_raises is not None:
            raise self.trailing_place_raises
        return self.trailing_place_returns

    async def get_position_tpsl(self, symbol: str, hold_side: str) -> PositionTpSlSnapshot:
        self.readback_calls.append(("tpsl", symbol, hold_side))
        if self.raise_not_impl_readback:
            raise NotImplementedError("fake adapter has no probe yet")
        return PositionTpSlSnapshot(
            symbol=symbol,
            side=hold_side,
            tp_price=self.readback_tp,
            tp_order_id=self.readback_tp_id,
            tp_trigger_type="mark_price",
            sl_price=self.readback_sl,
            sl_order_id=self.readback_sl_id,
            sl_trigger_type="mark_price",
        )

    async def get_trailing_stop(self, symbol: str, hold_side: str) -> TrailingStopSnapshot:
        self.readback_calls.append(("trailing", symbol, hold_side))
        if self.raise_not_impl_readback:
            raise NotImplementedError("fake adapter has no probe yet")
        return TrailingStopSnapshot(
            symbol=symbol,
            side=hold_side,
            callback_rate=self.readback_trailing_callback,
            activation_price=self.readback_trailing_activation,
            trigger_price=self.readback_trailing_trigger,
            order_id=self.readback_trailing_id,
        )


def _factory_returning(client: FakeExchangeClient):
    """Build a simple exchange-client factory that hands back ``client``."""

    def _f(user_id: int, exchange: str, demo_mode: bool) -> FakeExchangeClient:
        return client

    return _f


async def _fetch_trade(session_factory_cb, trade_id: int) -> TradeRecord:
    """Fresh DB read helper for assertions."""
    async with session_factory_cb() as session:
        trade = await session.get(TradeRecord, trade_id)
        assert trade is not None, f"trade {trade_id} missing"
        # Force-load attrs before session closes
        _ = (
            trade.take_profit,
            trade.stop_loss,
            trade.tp_order_id,
            trade.sl_order_id,
            trade.tp_status,
            trade.sl_status,
            trade.tp_intent,
            trade.sl_intent,
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
# Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_apply_intent_tp_success_persists_confirmed_state(
    open_trade: int, session_factory_cb
) -> None:
    """TP intent set → DB has take_profit=value, tp_status=confirmed, tp_order_id set."""
    client = FakeExchangeClient(
        place_returns={"orderId": "tp_native_123"},
        readback_tp=70246.0,
        readback_tp_id="tp_native_123",
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, 70246.0)

    assert result.status is RiskOpStatus.CONFIRMED
    assert result.value == pytest.approx(70246.0)
    assert result.order_id == "tp_native_123"
    assert result.latency_ms >= 0
    assert result.error is None

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.take_profit == pytest.approx(70246.0)
    assert trade.tp_intent == pytest.approx(70246.0)
    assert trade.tp_order_id == "tp_native_123"
    assert trade.tp_status == RiskOpStatus.CONFIRMED.value
    assert trade.risk_source == "native_exchange"
    assert trade.last_synced_at is not None

    # Exchange was called exactly once with the right args
    assert len(client.place_calls) == 1
    assert client.place_calls[0]["take_profit"] == pytest.approx(70246.0)
    assert client.place_calls[0]["stop_loss"] is None


@pytest.mark.asyncio
async def test_apply_intent_tp_clear_none_clears_dbfields(
    open_trade: int, session_factory_cb
) -> None:
    """TP intent value=None → DB take_profit=NULL, tp_status=cleared, tp_order_id=NULL."""
    # First: plant an existing tp_order_id so the cancel path is exercised.
    async with session_factory_cb() as session:
        trade = await session.get(TradeRecord, open_trade)
        trade.tp_order_id = "prev_tp_id"
        trade.take_profit = 70000.0
        await session.commit()

    client = FakeExchangeClient(raise_not_impl_readback=True)
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, None)

    assert result.status is RiskOpStatus.CLEARED
    assert result.value is None
    assert result.order_id is None

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.take_profit is None
    assert trade.tp_order_id is None
    assert trade.tp_status == RiskOpStatus.CLEARED.value
    assert trade.risk_source == "software_bot"

    # Cancel was invoked (TP-only, not all legs); place was NOT.
    assert len(client.cancel_calls) == 1
    assert client.cancel_calls[0] == ("BTCUSDT", "long", "tp_only")
    assert len(client.place_calls) == 0


@pytest.mark.asyncio
async def test_clear_tp_leaves_sl_and_trailing_untouched_on_exchange(
    open_trade: int, session_factory_cb
) -> None:
    """Regression A05: clearing TP must never collateral-cancel SL or trailing.

    Before the Epic #188 follow-up fix, clearing the TP leg called the
    broad ``cancel_position_tpsl`` on the client, which on Bitget wipes
    ``pos_profit`` + ``pos_loss`` + ``moving_plan`` in one call. That
    silently collapsed any active SL or trailing leg on the exchange
    while the DB still showed them as ``confirmed``.

    After the fix, clearing TP goes through ``cancel_tp_only`` which
    only touches the TP plan types. This test asserts the routing.
    """
    async with session_factory_cb() as session:
        trade = await session.get(TradeRecord, open_trade)
        trade.tp_order_id = "tp_plan_1"
        trade.take_profit = 80000.0
        trade.sl_order_id = "sl_plan_1"
        trade.stop_loss = 72000.0
        trade.trailing_order_id = "trail_plan_1"
        trade.trailing_callback_rate = 2.0
        trade.native_trailing_stop = True
        await session.commit()

    client = FakeExchangeClient(raise_not_impl_readback=True)
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, None)

    assert result.status is RiskOpStatus.CLEARED

    # Exactly one cancel, targeting ONLY the TP plan-types.
    assert client.cancel_calls == [("BTCUSDT", "long", "tp_only")]

    # DB: only tp-* fields touched. sl and trailing remain exactly as seeded.
    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.take_profit is None
    assert trade.tp_order_id is None
    assert trade.tp_status == RiskOpStatus.CLEARED.value
    assert trade.stop_loss == 72000.0
    assert trade.sl_order_id == "sl_plan_1"
    assert trade.trailing_order_id == "trail_plan_1"
    assert trade.trailing_callback_rate == 2.0


@pytest.mark.asyncio
async def test_clear_sl_routes_to_cancel_sl_only(
    open_trade: int, session_factory_cb
) -> None:
    """Analog to the TP test — clearing SL must use cancel_sl_only."""
    async with session_factory_cb() as session:
        trade = await session.get(TradeRecord, open_trade)
        trade.sl_order_id = "sl_plan_x"
        trade.stop_loss = 72000.0
        await session.commit()

    client = FakeExchangeClient(raise_not_impl_readback=True)
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.SL, None)

    assert result.status is RiskOpStatus.CLEARED
    assert client.cancel_calls == [("BTCUSDT", "long", "sl_only")]


@pytest.mark.asyncio
async def test_apply_intent_sl_success_persists_confirmed_state(
    open_trade: int, session_factory_cb
) -> None:
    """SL intent set → DB stop_loss=value, sl_status=confirmed, sl_order_id set."""
    client = FakeExchangeClient(
        place_returns={"order_id": "sl_native_456"},
        readback_sl=67177.0,
        readback_sl_id="sl_native_456",
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.SL, 67177.0)

    assert result.status is RiskOpStatus.CONFIRMED
    assert result.value == pytest.approx(67177.0)
    assert result.order_id == "sl_native_456"

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.stop_loss == pytest.approx(67177.0)
    assert trade.sl_intent == pytest.approx(67177.0)
    assert trade.sl_order_id == "sl_native_456"
    assert trade.sl_status == RiskOpStatus.CONFIRMED.value
    # TP fields untouched
    assert trade.take_profit is None
    assert trade.tp_status is None


@pytest.mark.asyncio
async def test_apply_intent_trailing_sets_all_three_fields(
    open_trade: int, session_factory_cb
) -> None:
    """Trailing intent set → DB has callback_rate + activation + trigger populated."""
    client = FakeExchangeClient(
        trailing_place_returns={"orderId": "tr_789"},
        readback_trailing_callback=2.5,
        readback_trailing_activation=69000.0,
        readback_trailing_trigger=68500.0,
        readback_trailing_id="tr_789",
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    trailing_value = {
        "callback_rate": 2.5,
        "activation_price": 69000.0,
        "trigger_price": 68500.0,
    }
    result = await manager.apply_intent(open_trade, RiskLeg.TRAILING, trailing_value)

    assert result.status is RiskOpStatus.CONFIRMED
    assert result.order_id == "tr_789"
    assert result.value == {
        "callback_rate": 2.5,
        "activation_price": 69000.0,
        "trigger_price": 68500.0,
    }

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.trailing_callback_rate == pytest.approx(2.5)
    assert trade.trailing_activation_price == pytest.approx(69000.0)
    assert trade.trailing_trigger_price == pytest.approx(68500.0)
    assert trade.trailing_order_id == "tr_789"
    assert trade.trailing_status == RiskOpStatus.CONFIRMED.value
    assert trade.trailing_intent_callback == pytest.approx(2.5)
    assert trade.risk_source == "native_exchange"


@pytest.mark.asyncio
async def test_apply_intent_cancel_failure_sets_status_and_skips_place(
    open_trade: int, session_factory_cb, caplog
) -> None:
    """When cancel fails: status=CANCEL_FAILED, no place attempted, warning logged."""
    # Seed existing order so a cancel is attempted.
    async with session_factory_cb() as session:
        trade = await session.get(TradeRecord, open_trade)
        trade.tp_order_id = "stale_tp_id"
        await session.commit()

    client = FakeExchangeClient(
        cancel_raises=OrderError("bitget", "cancel rejected: permission denied"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    import logging

    caplog.set_level(logging.WARNING, logger="src.bot.risk_state_manager")
    result = await manager.apply_intent(open_trade, RiskLeg.TP, 70246.0)

    assert result.status is RiskOpStatus.CANCEL_FAILED
    assert result.error is not None
    # Anti-Pattern C guard: no new place attempted.
    assert len(client.place_calls) == 0

    # Warning (not debug) log was emitted.
    warning_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "cancel_failed" in r.getMessage()
    ]
    assert warning_records, (
        "Expected a WARNING-level 'cancel_failed' log, got: "
        f"{[r.getMessage() for r in caplog.records]}"
    )

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.tp_status == RiskOpStatus.CANCEL_FAILED.value


@pytest.mark.asyncio
async def test_apply_intent_place_rejection_sets_status_rejected(
    open_trade: int, session_factory_cb
) -> None:
    """When exchange rejects the place call: status=REJECTED with error message."""
    client = FakeExchangeClient(
        place_raises=OrderError("bitget", "invalid tp price"),
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, 70246.0)

    assert result.status is RiskOpStatus.REJECTED
    assert result.error is not None
    assert "invalid tp price" in result.error

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.tp_status == RiskOpStatus.REJECTED.value
    # Pattern A: intent was persisted even though the place failed.
    assert trade.tp_intent == pytest.approx(70246.0)
    # But take_profit was not written because Phase D never ran.
    assert trade.take_profit is None


@pytest.mark.asyncio
async def test_apply_intent_readback_drift_uses_exchange_truth(
    open_trade: int, session_factory_cb
) -> None:
    """Exchange readback disagrees with intent → DB takes exchange's values.

    This is the Pattern A test: the probe returns a slightly different
    TP (e.g. after rounding) and a different order id, and BOTH must
    make it into the DB instead of the intended inputs.
    """
    client = FakeExchangeClient(
        place_returns={"orderId": "ignored_by_probe"},
        # Drift: exchange rounded our intent of 70246.0 to 70246.5
        readback_tp=70246.5,
        readback_tp_id="exchange_truth_id",
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, 70246.0)

    assert result.status is RiskOpStatus.CONFIRMED
    assert result.value == pytest.approx(70246.5), "Result must reflect exchange truth"
    assert result.order_id == "exchange_truth_id"

    trade = await _fetch_trade(session_factory_cb, open_trade)
    # Persisted take_profit must match readback, NOT the intended value.
    assert trade.take_profit == pytest.approx(70246.5)
    assert trade.tp_order_id == "exchange_truth_id"
    # Intent field still reflects what the caller wanted.
    assert trade.tp_intent == pytest.approx(70246.0)


@pytest.mark.asyncio
async def test_apply_intent_concurrent_calls_serialize_via_lock(
    open_trade: int, session_factory_cb
) -> None:
    """Two concurrent apply_intent calls on the same (trade, leg) must not overlap."""
    events: List[str] = []

    class _SlowClient(FakeExchangeClient):
        async def set_position_tpsl(self, **kwargs):  # type: ignore[override]
            events.append(f"enter_{kwargs.get('take_profit')}")
            await asyncio.sleep(0.05)
            events.append(f"exit_{kwargs.get('take_profit')}")
            return await super().set_position_tpsl(**kwargs)

    client = _SlowClient(
        place_returns={"orderId": "stub"},
        readback_tp=0.0,
        readback_tp_id="stub",
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    # Two overlapping calls with distinct TP values so we can tell them apart.
    first_task = asyncio.create_task(
        manager.apply_intent(open_trade, RiskLeg.TP, 70000.0)
    )
    second_task = asyncio.create_task(
        manager.apply_intent(open_trade, RiskLeg.TP, 71000.0)
    )
    await asyncio.gather(first_task, second_task)

    # No interleaving: each call must complete (enter→exit) before the next begins.
    # Expected either 70000 pair first or 71000 pair first, never mixed.
    assert len(events) == 4
    first_value = events[0].split("_")[1]
    assert events[1] == f"exit_{first_value}", (
        f"Lock was not held across exchange call — events: {events}"
    )


@pytest.mark.asyncio
async def test_reconcile_rewrites_db_from_exchange_truth(
    open_trade: int, session_factory_cb
) -> None:
    """Reconcile: DB has stale values → exchange probe is authoritative."""
    # Plant DB state that disagrees with the exchange.
    async with session_factory_cb() as session:
        trade = await session.get(TradeRecord, open_trade)
        trade.take_profit = 99999.0
        trade.tp_order_id = "stale"
        trade.stop_loss = 60000.0
        trade.sl_order_id = "stale_sl"
        trade.risk_source = "unknown"
        await session.commit()

    client = FakeExchangeClient(
        readback_tp=70246.0,
        readback_tp_id="real_tp",
        readback_sl=67177.0,
        readback_sl_id="real_sl",
        readback_trailing_callback=None,
        readback_trailing_id=None,
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    snap = await manager.reconcile(open_trade)

    assert isinstance(snap, RiskStateSnapshot)
    assert snap.trade_id == open_trade
    assert snap.tp is not None
    assert snap.tp["value"] == pytest.approx(70246.0)
    assert snap.tp["order_id"] == "real_tp"
    assert snap.sl is not None
    assert snap.sl["value"] == pytest.approx(67177.0)
    assert snap.risk_source == "native_exchange"

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.take_profit == pytest.approx(70246.0)
    assert trade.tp_order_id == "real_tp"
    assert trade.stop_loss == pytest.approx(67177.0)
    assert trade.sl_order_id == "real_sl"
    assert trade.risk_source == "native_exchange"
    assert trade.last_synced_at is not None


@pytest.mark.asyncio
async def test_reconcile_with_no_native_risk_marks_software_bot(
    open_trade: int, session_factory_cb
) -> None:
    """When exchange has no TP/SL/trailing, risk_source flips to software_bot."""
    client = FakeExchangeClient()  # all readbacks return None
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    snap = await manager.reconcile(open_trade)

    assert snap.risk_source == "software_bot"

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.risk_source == "software_bot"
    assert trade.take_profit is None
    assert trade.tp_order_id is None


@pytest.mark.asyncio
async def test_apply_intent_readback_not_implemented_falls_back_to_intended(
    open_trade: int, session_factory_cb
) -> None:
    """NotImplementedError on readback → best-effort: DB gets intended value + new order id."""
    client = FakeExchangeClient(
        place_returns={"orderId": "fallback_id"},
        raise_not_impl_readback=True,
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, 70246.0)

    assert result.status is RiskOpStatus.CONFIRMED
    assert result.value == pytest.approx(70246.0)
    assert result.order_id == "fallback_id"

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.take_profit == pytest.approx(70246.0)
    assert trade.tp_order_id == "fallback_id"
    assert trade.tp_status == RiskOpStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_apply_intent_missing_trade_returns_rejected(session_factory_cb) -> None:
    """Unknown trade_id → REJECTED, no exchange call attempted."""
    client = FakeExchangeClient()
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(999_999, RiskLeg.TP, 70000.0)

    assert result.status is RiskOpStatus.REJECTED
    assert "not found" in (result.error or "")
    assert len(client.place_calls) == 0
    assert len(client.cancel_calls) == 0


@pytest.mark.asyncio
async def test_get_lock_returns_same_instance_per_key(
    open_trade: int, session_factory_cb
) -> None:
    """Lock coalescing: (trade_id, leg) → same Lock object across calls."""
    manager = RiskStateManager(
        _factory_returning(FakeExchangeClient()), session_factory_cb
    )

    tp_lock_a = manager._get_lock(open_trade, RiskLeg.TP)
    tp_lock_b = manager._get_lock(open_trade, RiskLeg.TP)
    sl_lock = manager._get_lock(open_trade, RiskLeg.SL)

    assert tp_lock_a is tp_lock_b, "Same key must return same lock"
    assert tp_lock_a is not sl_lock, "Different legs must use distinct locks"


@pytest.mark.asyncio
async def test_apply_intent_clears_software_bot_when_no_order_id(
    open_trade: int, session_factory_cb
) -> None:
    """Place returns None order_id and readback returns None → risk_source=software_bot."""
    client = FakeExchangeClient(
        place_returns=None,  # some adapters return nothing
        raise_not_impl_readback=True,
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, 70246.0)

    assert result.status is RiskOpStatus.CONFIRMED
    assert result.order_id is None

    trade = await _fetch_trade(session_factory_cb, open_trade)
    # Value is persisted even without an order id (software trailing scenario).
    assert trade.take_profit == pytest.approx(70246.0)
    assert trade.tp_order_id is None
    assert trade.risk_source == "software_bot"


@pytest.mark.asyncio
async def test_classify_close_without_probe_support_falls_back(
    open_trade: int, session_factory_cb
) -> None:
    """classify_close falls back to the heuristic when the adapter has no probe.

    Detailed probe/match/snapshot behaviour is covered in
    tests/unit/bot/test_classify_close.py; this test just guards the contract
    that a classic FakeExchangeClient without ``get_close_reason_from_history``
    still produces a valid ExitReason string instead of raising.
    """
    from src.bot.risk_reasons import ExitReason

    manager = RiskStateManager(
        _factory_returning(FakeExchangeClient()), session_factory_cb
    )
    reason = await manager.classify_close(
        open_trade, exit_price=70246.0, exit_time=datetime.now(timezone.utc),
    )
    # No TP/SL/trailing on the fixture → heuristic lands on EXTERNAL_CLOSE_UNKNOWN.
    assert reason == ExitReason.EXTERNAL_CLOSE_UNKNOWN.value


@pytest.mark.asyncio
async def test_on_exchange_event_is_logging_only_stub(
    open_trade: int, session_factory_cb, caplog
) -> None:
    """on_exchange_event logs the event but does not touch the DB."""
    import logging

    manager = RiskStateManager(
        _factory_returning(FakeExchangeClient()), session_factory_cb
    )

    caplog.set_level(logging.INFO, logger="src.bot.risk_state_manager")
    await manager.on_exchange_event({"foo": "bar"})

    messages = [r.getMessage() for r in caplog.records]
    assert any("ws_event_received" in m for m in messages), messages

    # Stub must not have touched the DB.
    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.take_profit is None
    assert trade.tp_order_id is None


@pytest.mark.asyncio
async def test_apply_intent_place_generic_exception_sets_rejected(
    open_trade: int, session_factory_cb
) -> None:
    """Unknown exception from the place call → REJECTED (never leaked)."""
    client = FakeExchangeClient(place_raises=RuntimeError("boom"))
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, 70246.0)

    assert result.status is RiskOpStatus.REJECTED
    assert "boom" in (result.error or "")

    trade = await _fetch_trade(session_factory_cb, open_trade)
    assert trade.tp_status == RiskOpStatus.REJECTED.value


@pytest.mark.asyncio
async def test_apply_intent_trailing_rejects_non_dict_value(
    open_trade: int, session_factory_cb
) -> None:
    """Passing a non-dict trailing value surfaces as REJECTED (defensive)."""
    client = FakeExchangeClient()
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    # 42 is not a dict — the manager catches the ValueError and reports REJECTED.
    result = await manager.apply_intent(open_trade, RiskLeg.TRAILING, 42)

    assert result.status is RiskOpStatus.REJECTED
    assert result.error is not None


@pytest.mark.asyncio
async def test_apply_intent_trailing_cancel_old_uses_cancel_order(
    open_trade: int, session_factory_cb
) -> None:
    """Trailing replace: manager cancels the old trailing-order-id, then places."""
    async with session_factory_cb() as session:
        trade = await session.get(TradeRecord, open_trade)
        trade.trailing_order_id = "old_trailing_id"
        await session.commit()

    client = FakeExchangeClient(
        trailing_place_returns={"planOrderId": "new_trailing_id"},
        readback_trailing_callback=2.0,
        readback_trailing_activation=69500.0,
        readback_trailing_trigger=68800.0,
        readback_trailing_id="new_trailing_id",
    )
    manager = RiskStateManager(_factory_returning(client), session_factory_cb)

    result = await manager.apply_intent(
        open_trade,
        RiskLeg.TRAILING,
        {"callback_rate": 2.0, "activation_price": 69500.0, "trigger_price": 68800.0},
    )

    assert result.status is RiskOpStatus.CONFIRMED
    assert result.order_id == "new_trailing_id"
    # Cancel was invoked via the trailing-only path (cancel_native_trailing_stop
    # preferred over cancel_order so other legs can never be collateral damage).
    assert client.cancel_calls == [("BTCUSDT", "long", "trailing_only")]
    assert client.cancel_order_calls == []


@pytest.mark.asyncio
async def test_apply_intent_async_factory_is_awaited(
    open_trade: int, session_factory_cb
) -> None:
    """The exchange-client factory can be an async coroutine — manager awaits it."""
    client = FakeExchangeClient(
        place_returns="raw_string_id",
        readback_tp=70246.0,
        readback_tp_id="raw_string_id",
    )

    async def _async_factory(user_id: int, exchange: str, demo_mode: bool):
        return client

    manager = RiskStateManager(_async_factory, session_factory_cb)

    result = await manager.apply_intent(open_trade, RiskLeg.TP, 70246.0)

    assert result.status is RiskOpStatus.CONFIRMED
    assert result.order_id == "raw_string_id"


def test_extract_order_id_accepts_string_and_object() -> None:
    """The order-id extractor handles strings, objects, and None."""
    from src.bot.risk_state_manager import _extract_order_id

    assert _extract_order_id(None) is None
    assert _extract_order_id("ord_xyz") == "ord_xyz"
    assert _extract_order_id({"orderId": "123"}) == "123"
    assert _extract_order_id({"order_id": 42}) == "42"
    assert _extract_order_id({"planOrderId": "plan_1"}) == "plan_1"
    assert _extract_order_id({"nothing": True}) is None

    class _Obj:
        order_id = "attr_id"

    assert _extract_order_id(_Obj()) == "attr_id"

    class _Empty:
        pass

    assert _extract_order_id(_Empty()) is None
