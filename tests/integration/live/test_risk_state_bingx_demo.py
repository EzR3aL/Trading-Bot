"""Live integration smoke test for ``RiskStateManager`` against BingX VST (#216 S1).

Single long-position smoke sequence covering the TP/SL/Trailing roundtrip
against BingX's VST (Virtual Simulated Trading) demo. Mirrors
``test_risk_state_bitget_demo.py`` but narrower — the per-exchange
cancel-failure C-path specs (C01/C03) in the Bitget file apply equally at
the ``RiskStateManager`` level and are not duplicated here.

Gating: ``pytest.mark.bingx_live`` + ``BINGX_LIVE_TEST_USER_ID`` env var.
``BINGX_LIVE_TEST_SYMBOL`` defaults to ``BTC-USDT`` (BingX's hyphenated
convention; Bitget uses ``BTCUSDT``).

BingX quirks encoded here:
* Symbol format is hyphenated (``BTC-USDT``).
* ``callback_rate`` is passed in percent (1.4 = 1.4%); the BingX client
  converts to the fractional ``priceRate`` BingX's API expects, and the
  readback re-normalises back to percent.
* BingX has no position-level TP/SL endpoint — ``set_position_tpsl`` places
  reduce-only ``TAKE_PROFIT_MARKET`` / ``STOP_MARKET`` orders, read back
  via ``openOrders``. The RiskStateManager 2-PC contract is exchange-
  agnostic so the assertions are identical to Bitget's.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.risk_state_manager import (
    RiskLeg,
    RiskOpStatus,
    RiskStateManager,
)
from src.models.database import TradeRecord
from src.models.session import get_session
from tests.integration.live.conftest import (
    BINGX_LIVE_MARKER,
    PRICE_TOLERANCE,
    READBACK_DELAY_SECONDS,
)


# ── Marker applied to every live test in this module ──────────────────

pytestmark = [pytest.mark.bingx_live, BINGX_LIVE_MARKER]


# ── BingX-specific test constants ──────────────────────────────────────

# BingX's symbol convention is hyphenated (BTC-USDT) unlike Bitget (BTCUSDT).
# Overridable via env var to let ops point the suite at a different
# symbol (e.g. a lower-value contract) if BTC margin becomes an issue.
DEFAULT_BINGX_SYMBOL = "BTC-USDT"
BINGX_TEST_SIZE = 0.001
BINGX_TEST_LEVERAGE = 3
BINGX_TEST_MARGIN_MODE = "cross"

# Price offsets — same shape as the Bitget test, long-only since this is
# a smoke test.
_LONG_TP_OFFSET_PCT = 0.06   # +6% from entry
_LONG_SL_OFFSET_PCT = -0.04  # -4% from entry


def _bingx_symbol() -> str:
    return os.getenv("BINGX_LIVE_TEST_SYMBOL", DEFAULT_BINGX_SYMBOL)


def _bingx_user_id() -> int:
    return int(os.getenv("BINGX_LIVE_TEST_USER_ID", "1"))


def _tp_long(entry: float) -> float:
    return round(entry * (1 + _LONG_TP_OFFSET_PCT), 1)


def _sl_long(entry: float) -> float:
    return round(entry * (1 + _LONG_SL_OFFSET_PCT), 1)


# ── Shared assertions ──────────────────────────────────────────────────


def _assert_price_close(actual: float | None, expected: float, msg: str = "") -> None:
    """Asserts a live-returned price matches within BingX rounding tolerance."""
    assert actual is not None, f"{msg} — value was None"
    assert abs(actual - expected) < PRICE_TOLERANCE, (
        f"{msg} — expected {expected} ± {PRICE_TOLERANCE}, got {actual}"
    )


async def _fetch_trade(trade_id: int) -> TradeRecord:
    """Load the current DB row for ``trade_id`` with eager attribute touches."""
    async with get_session() as db:
        trade = await db.get(TradeRecord, trade_id)
        assert trade is not None, f"trade {trade_id} vanished mid-test"
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
        )
        return trade


# ── Fixtures ───────────────────────────────────────────────────────────
#
# Kept local to this file (instead of in conftest.py) so the Bitget suite
# stays untouched. The Bitget suite's fixtures are bitget-only by design
# and share the ``admin_bitget_client`` name — we would collide if we
# promoted these to conftest.


async def _try_cleanup_position(client, symbol: str, side: str) -> None:
    """Close any open position and cancel every TP/SL/trailing plan.

    Swallows errors because cleanup runs in a ``finally`` and must never
    mask the actual test failure.
    """
    try:
        await client.close_position(symbol, side)
    except Exception:  # noqa: BLE001 — cleanup is best-effort
        pass
    try:
        await client.cancel_position_tpsl(symbol=symbol, side=side)
    except Exception:  # noqa: BLE001 — cleanup is best-effort
        pass


@pytest_asyncio.fixture
async def admin_bingx_client():
    """Return the admin user's BingX VST ``ExchangeClient``.

    Skips the test if no BingX demo client is configured for the admin
    user — keeps the suite safe on dev machines without credentials.
    """
    from src.exchanges.factory import get_all_user_clients

    user_id = _bingx_user_id()

    async with get_session() as db:
        clients = await get_all_user_clients(user_id=user_id, db=db)

    bingx_demo = [
        client for (ex_type, demo, client) in clients
        if ex_type == "bingx" and demo
    ]
    if not bingx_demo:
        pytest.skip(
            f"No BingX demo client configured for user_id={user_id}. "
            "Live tests require an admin BingX VST connection."
        )

    client = bingx_demo[0]
    try:
        yield client
    finally:
        close_fn = getattr(client, "close", None)
        if close_fn is not None:
            try:
                await close_fn()
            except Exception:  # noqa: BLE001 — cleanup is best-effort
                pass


@pytest_asyncio.fixture
async def bingx_risk_manager(admin_bingx_client):
    """Build a :class:`RiskStateManager` wired against the admin's BingX client."""

    @asynccontextmanager
    async def _session_factory():
        async with get_session() as session:
            yield session

    def _exchange_factory(user_id: int, exchange: str, demo_mode: bool):
        return admin_bingx_client

    return RiskStateManager(
        exchange_client_factory=_exchange_factory,
        session_factory=_session_factory,
    )


async def _open_bingx_long(client, symbol: str) -> dict:
    """Place a market-entry long on BingX VST and persist the trade row.

    Returns a dict with ``trade_id``, ``symbol``, ``side``, ``user_id``,
    ``size``, ``entry_price``, ``entry_order_id``.
    """
    from sqlalchemy import select

    from src.models.database import BotConfig, ExchangeConnection

    user_id = _bingx_user_id()
    side = "long"

    # Clean up any leftover state from a previous test run before opening.
    await _try_cleanup_position(client, symbol, side)

    ticker = await client.get_ticker(symbol)
    assert ticker and ticker.last_price > 0, (
        f"Cannot get a valid ticker for {symbol}; BingX VST may be down."
    )

    order = await client.place_market_order(
        symbol=symbol,
        side=side,
        size=BINGX_TEST_SIZE,
        leverage=BINGX_TEST_LEVERAGE,
        margin_mode=BINGX_TEST_MARGIN_MODE,
    )
    if order is None or not order.order_id:
        raise RuntimeError(
            f"BingX VST rejected the market-order for {symbol} {side}: {order}"
        )

    await asyncio.sleep(READBACK_DELAY_SECONDS)

    async with get_session() as db:
        conn_row = (await db.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user_id,
                ExchangeConnection.exchange_type == "bingx",
            )
        )).scalar_one_or_none()
        if conn_row is None:
            raise RuntimeError(
                f"No BingX ExchangeConnection for user_id={user_id} — "
                "test database is out of sync with the live credentials."
            )

        bot_row = (await db.execute(
            select(BotConfig).where(BotConfig.user_id == user_id).limit(1)
        )).scalar_one_or_none()
        bot_config_id = bot_row.id if bot_row is not None else None

        trade = TradeRecord(
            user_id=user_id,
            bot_config_id=bot_config_id,
            exchange="bingx",
            symbol=symbol,
            side=side,
            size=BINGX_TEST_SIZE,
            entry_price=ticker.last_price,
            leverage=BINGX_TEST_LEVERAGE,
            confidence=80,
            reason="live_integration_test (#216 S1)",
            order_id=str(order.order_id),
            status="open",
            demo_mode=True,
            entry_time=datetime.now(timezone.utc),
        )
        db.add(trade)
        await db.flush()
        await db.refresh(trade)
        trade_id = trade.id

    return {
        "trade_id": trade_id,
        "user_id": user_id,
        "symbol": symbol,
        "side": side,
        "size": BINGX_TEST_SIZE,
        "entry_price": ticker.last_price,
        "entry_order_id": str(order.order_id),
    }


async def _teardown_trade(client, trade_info: dict) -> None:
    """Close + cancel on exchange, mark DB row as closed (best-effort)."""
    symbol = trade_info["symbol"]
    side = trade_info["side"]
    trade_id = trade_info["trade_id"]

    await _try_cleanup_position(client, symbol, side)

    try:
        async with get_session() as db:
            trade = await db.get(TradeRecord, trade_id)
            if trade is not None and trade.status == "open":
                trade.status = "closed"
                trade.exit_time = datetime.now(timezone.utc)
                trade.exit_reason = "live_test_teardown"
    except Exception:  # noqa: BLE001 — cleanup failure must not mask tests
        pass


@pytest_asyncio.fixture
async def bingx_long_position(admin_bingx_client) -> AsyncIterator[dict]:
    """Open a 0.001 BTC-USDT long on BingX VST; tear down in ``finally``."""
    trade_info: Optional[dict] = None
    try:
        trade_info = await _open_bingx_long(admin_bingx_client, _bingx_symbol())
        yield trade_info
    finally:
        if trade_info is not None:
            await _teardown_trade(admin_bingx_client, trade_info)


# ===========================================================================
# Smoke test — TP/SL/Trailing roundtrip on a single long position
# ===========================================================================


async def test_bingx_tp_sl_trailing_roundtrip_on_long(
    bingx_risk_manager: RiskStateManager,
    admin_bingx_client,
    bingx_long_position: dict,
) -> None:
    """End-to-end roundtrip: open → TP → SL → Trailing → clear all → close.

    Each apply_intent call must return CONFIRMED (or CLEARED for clears),
    and every state change must be visible on BingX via an independent
    readback within ``PRICE_TOLERANCE``.
    """
    trade = bingx_long_position
    entry = trade["entry_price"]
    symbol = trade["symbol"]
    side = trade["side"]
    trade_id = trade["trade_id"]

    # ── Step 1: set TP ────────────────────────────────────────────────
    tp = _tp_long(entry)

    tp_result = await bingx_risk_manager.apply_intent(trade_id, RiskLeg.TP, tp)

    assert tp_result.status == RiskOpStatus.CONFIRMED, (
        f"Expected CONFIRMED for TP, got {tp_result.status} — "
        f"error={tp_result.error}"
    )
    assert tp_result.order_id is not None
    _assert_price_close(tp_result.value, tp, "RiskOpResult.value (TP)")

    db_trade = await _fetch_trade(trade_id)
    _assert_price_close(db_trade.take_profit, tp, "DB take_profit")
    assert db_trade.tp_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.tp_order_id == tp_result.order_id

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bingx_client.get_position_tpsl(symbol, side)
    _assert_price_close(snap.tp_price, tp, "BingX tp_price readback")
    assert snap.tp_order_id == tp_result.order_id

    # ── Step 2: set SL ────────────────────────────────────────────────
    sl = _sl_long(entry)

    sl_result = await bingx_risk_manager.apply_intent(trade_id, RiskLeg.SL, sl)

    assert sl_result.status == RiskOpStatus.CONFIRMED, (
        f"Expected CONFIRMED for SL, got {sl_result.status} — "
        f"error={sl_result.error}"
    )
    assert sl_result.order_id is not None
    _assert_price_close(sl_result.value, sl, "RiskOpResult.value (SL)")

    db_trade = await _fetch_trade(trade_id)
    _assert_price_close(db_trade.stop_loss, sl, "DB stop_loss")
    assert db_trade.sl_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.sl_order_id == sl_result.order_id

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bingx_client.get_position_tpsl(symbol, side)
    # TP should still be live (leg-isolation invariant).
    _assert_price_close(snap.tp_price, tp, "BingX tp_price after SL set")
    _assert_price_close(snap.sl_price, sl, "BingX sl_price readback")
    assert snap.sl_order_id == sl_result.order_id

    # ── Step 3: set Trailing ──────────────────────────────────────────
    # callback_rate in percent (1.4 = 1.4%). BingX client converts to
    # fractional priceRate internally.
    callback_rate = 1.4
    trailing_payload = {
        "callback_rate": callback_rate,
        "activation_price": round(entry * 1.002, 1),
        "trigger_price": round(entry * 1.002, 1),
    }

    tr_result = await bingx_risk_manager.apply_intent(
        trade_id, RiskLeg.TRAILING, trailing_payload,
    )

    assert tr_result.status == RiskOpStatus.CONFIRMED, (
        f"Expected CONFIRMED for Trailing, got {tr_result.status} — "
        f"error={tr_result.error}"
    )
    assert tr_result.order_id is not None

    db_trade = await _fetch_trade(trade_id)
    assert db_trade.trailing_order_id == tr_result.order_id
    assert db_trade.trailing_status == RiskOpStatus.CONFIRMED.value
    assert db_trade.trailing_callback_rate is not None
    assert abs(db_trade.trailing_callback_rate - callback_rate) < 0.5, (
        f"callback mismatch: expected ~{callback_rate}%, "
        f"got {db_trade.trailing_callback_rate}"
    )

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    trail_snap = await admin_bingx_client.get_trailing_stop(symbol, side)
    assert trail_snap is not None, "BingX readback returned no trailing plan"
    assert trail_snap.order_id == tr_result.order_id
    assert trail_snap.callback_rate is not None
    assert abs(trail_snap.callback_rate - callback_rate) < 0.5, (
        f"BingX trailing callback mismatch: expected ~{callback_rate}%, "
        f"got {trail_snap.callback_rate}"
    )

    # ── Step 4: clear Trailing ────────────────────────────────────────
    tr_clear = await bingx_risk_manager.apply_intent(
        trade_id, RiskLeg.TRAILING, None,
    )

    assert tr_clear.status == RiskOpStatus.CLEARED
    assert tr_clear.order_id is None

    db_trade = await _fetch_trade(trade_id)
    assert db_trade.trailing_order_id is None
    assert db_trade.trailing_status == RiskOpStatus.CLEARED.value

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    trail_snap = await admin_bingx_client.get_trailing_stop(symbol, side)
    assert trail_snap is None, (
        f"Expected no trailing plan after clear, got {trail_snap}"
    )

    # ── Step 5: clear TP and SL ───────────────────────────────────────
    tp_clear = await bingx_risk_manager.apply_intent(trade_id, RiskLeg.TP, None)
    sl_clear = await bingx_risk_manager.apply_intent(trade_id, RiskLeg.SL, None)

    assert tp_clear.status == RiskOpStatus.CLEARED
    assert sl_clear.status == RiskOpStatus.CLEARED

    db_trade = await _fetch_trade(trade_id)
    assert db_trade.tp_status == RiskOpStatus.CLEARED.value
    assert db_trade.sl_status == RiskOpStatus.CLEARED.value
    assert db_trade.tp_order_id is None
    assert db_trade.sl_order_id is None

    await asyncio.sleep(READBACK_DELAY_SECONDS)
    snap = await admin_bingx_client.get_position_tpsl(symbol, side)
    assert snap.tp_price is None, (
        f"Expected no TP on BingX after clear, got {snap.tp_price}"
    )
    assert snap.sl_price is None, (
        f"Expected no SL on BingX after clear, got {snap.sl_price}"
    )
    # Fixture teardown closes the position + sweeps any residual plans.
