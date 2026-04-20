"""Unit tests for :mod:`src.bot.hl_trailing_emulator` (Issue #216 Section 3.1).

The emulator's contract has five load-bearing properties:

1. ``highest_price`` ratchets up for a long and down for a short.
2. ``highest_price`` does NOT move against the direction of the position.
3. A *tighter* candidate SL wins; a looser one is a no-op.
4. Side inversion (short) uses the mirrored formula.
5. The watchdog does not start when the feature flag is off.

The tests use an in-memory SQLite DB with the real ``TradeRecord`` model so
assertions hit actual columns. Exchange interaction is faked via a dataclass
that mimics the one-public-method surface the emulator actually touches
(``_info.all_mids``) — this keeps the tests isolated from hyperliquid-sdk
imports.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.hl_trailing_emulator import HLTrailingEmulator
from src.bot.risk_state_manager import RiskOpStatus, RiskStateManager
from src.exchanges.base import PositionTpSlSnapshot
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
    """Return a zero-arg callable yielding an ``AsyncSession`` context manager."""
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


async def _seed_hl_trailing_trade(
    engine,
    *,
    side: str = "long",
    entry_price: float = 100.0,
    stop_loss: Optional[float] = None,
    highest_price: Optional[float] = None,
    callback_rate: float = 2.0,
    trailing_status: str = RiskOpStatus.CONFIRMED.value,
    symbol: str = "ETH",
) -> int:
    """Seed an open HL trade the emulator considers eligible and return its id."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user = User(
            username=f"hl-trail-{side}-{symbol}",
            email=f"hl-{side}-{symbol}@example.com",
            password_hash="x",
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        trade = TradeRecord(
            user_id=user.id,
            exchange="hyperliquid",
            symbol=symbol,
            side=side,
            size=1.0,
            entry_price=entry_price,
            stop_loss=stop_loss,
            highest_price=highest_price,
            leverage=5,
            confidence=80,
            reason="hl trailing emulator test",
            order_id=f"entry_{side}_{symbol}",
            status="open",
            entry_time=datetime.now(timezone.utc),
            demo_mode=True,
            trailing_callback_rate=callback_rate,
            trailing_intent_callback=callback_rate,
            trailing_status=trailing_status,
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)
        return trade.id


# ---------------------------------------------------------------------------
# Fake HL client — only what the emulator touches
# ---------------------------------------------------------------------------


@dataclass
class FakeHLInfo:
    """Stub for ``HyperliquidClient._info`` — exposes ``all_mids``."""

    mids: Dict[str, float] = field(default_factory=dict)
    calls: int = 0

    def all_mids(self) -> Dict[str, float]:
        self.calls += 1
        return dict(self.mids)


@dataclass
class FakeHLClient:
    """Minimal HL client for the emulator + RSM SL-write path.

    The emulator reads ``client._info.all_mids()``. The SL update flows
    through :meth:`RiskStateManager.apply_intent` which in turn calls
    ``cancel_sl_only``, ``set_position_tpsl``, and the ``get_position_tpsl``
    readback — all stubbed here.
    """

    exchange_name: str = "hyperliquid"
    _info: FakeHLInfo = field(default_factory=FakeHLInfo)

    # Track the SL updates RSM routes through us
    sl_place_calls: List[dict] = field(default_factory=list)
    cancel_calls: List[tuple] = field(default_factory=list)
    readback_sl: Optional[float] = None
    readback_sl_id: Optional[str] = "hl_sl_trail_1"

    async def cancel_sl_only(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "sl_only"))
        return True

    async def cancel_tp_only(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "tp_only"))
        return True

    async def cancel_position_tpsl(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "all"))
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
        self.sl_place_calls.append(
            {
                "symbol": symbol,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "side": side,
                "size": size,
            }
        )
        # Echo the intended SL back in the readback so RSM's Phase-D
        # persists exactly what we requested.
        self.readback_sl = stop_loss
        return {"orderId": self.readback_sl_id}

    async def get_position_tpsl(
        self, symbol: str, hold_side: str,
    ) -> PositionTpSlSnapshot:
        return PositionTpSlSnapshot(
            symbol=symbol,
            side=hold_side,
            tp_price=None,
            tp_order_id=None,
            tp_trigger_type=None,
            sl_price=self.readback_sl,
            sl_order_id=self.readback_sl_id if self.readback_sl is not None else None,
            sl_trigger_type="mark_price" if self.readback_sl is not None else None,
        )

    async def get_trailing_stop(self, symbol: str, hold_side: str):
        # HL has no native trailing — mirror production behaviour.
        return None


def _factory_returning(client: FakeHLClient):
    """Build an exchange-client factory that hands back ``client``."""

    def _f(user_id: int, exchange: str, demo_mode: bool) -> FakeHLClient:
        return client

    return _f


def _build_emulator(
    client: FakeHLClient, session_factory_cb,
) -> HLTrailingEmulator:
    """Assemble emulator + RSM with the same factory (production wiring)."""
    factory = _factory_returning(client)
    rsm = RiskStateManager(factory, session_factory_cb)
    return HLTrailingEmulator(
        exchange_client_factory=factory,
        session_factory=session_factory_cb,
        risk_state_manager=rsm,
        tick_seconds=0.01,
    )


async def _fetch_trade(session_factory_cb, trade_id: int) -> TradeRecord:
    """Fresh DB read helper for assertions."""
    async with session_factory_cb() as session:
        trade = await session.get(TradeRecord, trade_id)
        assert trade is not None, f"trade {trade_id} missing"
        # Force-load attrs before session closes
        _ = (
            trade.stop_loss,
            trade.highest_price,
            trade.risk_source,
            trade.trailing_callback_rate,
            trade.trailing_status,
            trade.sl_status,
        )
        return trade


# ===========================================================================
# Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_tick_ratchets_highest_price_up_for_long_when_mark_ticks_up(
    engine, session_factory_cb,
) -> None:
    """Long position + mark > highest_price → highest_price advances."""
    trade_id = await _seed_hl_trailing_trade(
        engine,
        side="long",
        entry_price=100.0,
        stop_loss=98.0,
        highest_price=100.0,
        callback_rate=2.0,
        symbol="ETH",
    )
    client = FakeHLClient()
    client._info.mids = {"ETH": 105.0}
    emu = _build_emulator(client, session_factory_cb)

    await emu.tick()

    trade = await _fetch_trade(session_factory_cb, trade_id)
    assert trade.highest_price == pytest.approx(105.0)
    # Candidate SL = 105 * (1 - 0.02) = 102.9 > 98.0 → SL tightened
    assert trade.stop_loss == pytest.approx(102.9)
    assert trade.risk_source == "software_bot"
    assert len(client.sl_place_calls) == 1
    assert client.sl_place_calls[0]["stop_loss"] == pytest.approx(102.9)


@pytest.mark.asyncio
async def test_tick_does_not_shift_highest_price_for_long_when_mark_ticks_down(
    engine, session_factory_cb,
) -> None:
    """Long + mark below highest_price → highest_price unchanged, no SL update."""
    trade_id = await _seed_hl_trailing_trade(
        engine,
        side="long",
        entry_price=100.0,
        stop_loss=103.0,  # SL already tight from previous ratchet
        highest_price=105.0,
        callback_rate=2.0,
    )
    client = FakeHLClient()
    client._info.mids = {"ETH": 103.5}  # below highest
    emu = _build_emulator(client, session_factory_cb)

    await emu.tick()

    trade = await _fetch_trade(session_factory_cb, trade_id)
    # Extreme unchanged
    assert trade.highest_price == pytest.approx(105.0)
    # Candidate SL = 105 * 0.98 = 102.9 which is LOOSER than current 103.0
    # → no SL update emitted
    assert trade.stop_loss == pytest.approx(103.0)
    assert len(client.sl_place_calls) == 0


@pytest.mark.asyncio
async def test_tight_new_sl_wins_over_looser_current_sl(
    engine, session_factory_cb,
) -> None:
    """A tighter candidate SL MUST replace a looser current SL."""
    trade_id = await _seed_hl_trailing_trade(
        engine,
        side="long",
        entry_price=100.0,
        stop_loss=90.0,  # deliberately loose
        highest_price=100.0,
        callback_rate=1.0,
    )
    client = FakeHLClient()
    client._info.mids = {"ETH": 110.0}
    emu = _build_emulator(client, session_factory_cb)

    await emu.tick()

    trade = await _fetch_trade(session_factory_cb, trade_id)
    # Candidate SL = 110 * (1 - 0.01) = 108.9 >> 90.0
    assert trade.stop_loss == pytest.approx(108.9)
    assert trade.highest_price == pytest.approx(110.0)
    assert len(client.sl_place_calls) == 1


@pytest.mark.asyncio
async def test_looser_candidate_sl_is_a_no_op(
    engine, session_factory_cb,
) -> None:
    """When the candidate SL is LOOSER than current, no exchange call is made."""
    trade_id = await _seed_hl_trailing_trade(
        engine,
        side="long",
        entry_price=100.0,
        stop_loss=109.0,  # already tighter than any candidate at mark=110, cb=1%
        highest_price=110.0,
        callback_rate=1.0,
    )
    client = FakeHLClient()
    client._info.mids = {"ETH": 110.0}  # no ratchet
    emu = _build_emulator(client, session_factory_cb)

    await emu.tick()

    trade = await _fetch_trade(session_factory_cb, trade_id)
    # Candidate 108.9 < current 109.0 → no update
    assert trade.stop_loss == pytest.approx(109.0)
    assert len(client.sl_place_calls) == 0


@pytest.mark.asyncio
async def test_short_side_inversion_ratchets_down_and_places_higher_sl(
    engine, session_factory_cb,
) -> None:
    """Short + mark below highest → highest decreases; SL = extreme*(1+cb/100)."""
    trade_id = await _seed_hl_trailing_trade(
        engine,
        side="short",
        entry_price=100.0,
        stop_loss=102.0,
        highest_price=100.0,  # for a short, this is the running MINIMUM
        callback_rate=2.0,
    )
    client = FakeHLClient()
    client._info.mids = {"ETH": 95.0}
    emu = _build_emulator(client, session_factory_cb)

    await emu.tick()

    trade = await _fetch_trade(session_factory_cb, trade_id)
    # Short: min(100, 95) = 95; candidate SL = 95 * (1 + 0.02) = 96.9
    assert trade.highest_price == pytest.approx(95.0)
    assert trade.stop_loss == pytest.approx(96.9)
    assert len(client.sl_place_calls) == 1
    assert client.sl_place_calls[0]["stop_loss"] == pytest.approx(96.9)
    # Short side flows through the SL update with side='short'
    assert client.sl_place_calls[0]["side"] == "short"


@pytest.mark.asyncio
async def test_start_is_noop_when_flag_is_off(
    engine, session_factory_cb,
) -> None:
    """``start(enabled=False)`` MUST NOT spawn the watchdog task."""
    client = FakeHLClient()
    emu = _build_emulator(client, session_factory_cb)

    emu.start(enabled=False)

    assert emu._task is None, "flag-off start should not spawn a task"


@pytest.mark.asyncio
async def test_start_spawns_watchdog_when_flag_is_on(
    engine, session_factory_cb,
) -> None:
    """``start(enabled=True)`` spawns exactly one watchdog task and stop() reaps it."""
    client = FakeHLClient()
    emu = _build_emulator(client, session_factory_cb)

    emu.start(enabled=True)
    try:
        assert emu._task is not None
        assert not emu._task.done()
        # Duplicate start is a no-op — same task
        original_task = emu._task
        emu.start(enabled=True)
        assert emu._task is original_task
    finally:
        await emu.stop()

    assert emu._task is None


@pytest.mark.asyncio
async def test_tick_skips_trades_with_unconfirmed_trailing_status(
    engine, session_factory_cb,
) -> None:
    """Only ``trailing_status='confirmed'`` trades are emulated — pending/cleared are skipped."""
    # Pending: emulator should ignore (awaiting first SL place)
    pending_id = await _seed_hl_trailing_trade(
        engine,
        side="long",
        entry_price=100.0,
        stop_loss=98.0,
        highest_price=100.0,
        callback_rate=2.0,
        trailing_status=RiskOpStatus.PENDING.value,
        symbol="BTC",
    )
    client = FakeHLClient()
    client._info.mids = {"BTC": 110.0, "ETH": 110.0}
    emu = _build_emulator(client, session_factory_cb)

    await emu.tick()

    trade = await _fetch_trade(session_factory_cb, pending_id)
    # Highest unchanged, SL unchanged, no exchange call
    assert trade.highest_price == pytest.approx(100.0)
    assert trade.stop_loss == pytest.approx(98.0)
    assert len(client.sl_place_calls) == 0


@pytest.mark.asyncio
async def test_persistence_across_restart_reconstructs_from_highest_price(
    engine, session_factory_cb,
) -> None:
    """After a restart the emulator keeps ratcheting from the DB's highest_price.

    Regression guard for the "no new columns" contract: the trailing state
    MUST reconstruct from ``highest_price`` + ``trailing_callback_rate`` +
    ``stop_loss`` alone.
    """
    trade_id = await _seed_hl_trailing_trade(
        engine,
        side="long",
        entry_price=100.0,
        stop_loss=107.0,
        highest_price=108.0,  # from a previous session
        callback_rate=1.0,
    )
    client = FakeHLClient()
    client._info.mids = {"ETH": 112.0}  # further ratchet
    emu = _build_emulator(client, session_factory_cb)  # brand-new instance

    await emu.tick()

    trade = await _fetch_trade(session_factory_cb, trade_id)
    assert trade.highest_price == pytest.approx(112.0)
    # Candidate SL = 112 * 0.99 = 110.88 > 107.0 → update
    assert trade.stop_loss == pytest.approx(110.88)
    assert trade.risk_source == "software_bot"
