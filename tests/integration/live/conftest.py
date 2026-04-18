"""Shared fixtures for the Bitget-demo live integration test suite (#197).

Overview
--------
These fixtures wire up the admin user's live Bitget-demo ``ExchangeClient``
plus a ``RiskStateManager`` backed by the production DB session factory.
Tests using the fixtures run against real Bitget-demo endpoints — they open
a 0.001 BTCUSDT position, exercise the 2-Phase-Commit flow, verify the
state via independent readback, and guarantee teardown closes the position
and cancels every lingering plan.

Gating
------
* The ``bitget_live`` marker skips every test unless applied explicitly
  via ``pytest -m bitget_live`` (or a config override).
* ``BITGET_LIVE_MARKER`` additionally skips tests when
  ``BITGET_LIVE_TEST_USER_ID`` is missing — this protects local machines
  that have no admin credentials from trying (and failing) to hit Bitget.

Cleanup contract
----------------
The ``demo_long_position`` / ``demo_short_position`` fixtures both run a
``finally`` block that calls ``close_position`` and ``cancel_position_tpsl``
on the symbol+side pair. Tests MUST use these fixtures instead of opening
positions inline so the cleanup happens even on assertion failure.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import pytest
import pytest_asyncio


# ── Environment defaults (must be set before importing src.* modules) ──

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "live-integration-test-key-not-for-production",
)
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "bGl2ZS1pbnRlZ3JhdGlvbi1lbmNyeXB0aW9uLWtleQ==",
)


# ── Test constants ─────────────────────────────────────────────────────

# Minimal position config per TEST_MATRIX.md Execution-Plan.
# 0.001 BTC ≈ $75 margin at $75k * 1/1 — well inside the 28k demo balance.
LIVE_TEST_SYMBOL = "BTCUSDT"
LIVE_TEST_SIZE = 0.001
LIVE_TEST_LEVERAGE = 3
LIVE_TEST_MARGIN_MODE = "cross"

# Readback tolerance — Bitget may round to pricePlace (BTC typically 1 decimal).
PRICE_TOLERANCE = 1.0

# How many seconds to wait after placing an order before readback, so the
# exchange has time to register the plan. Tuned for Bitget demo latency.
READBACK_DELAY_SECONDS = 0.5


BITGET_LIVE_MARKER = pytest.mark.skipif(
    not os.getenv("BITGET_LIVE_TEST_USER_ID"),
    reason=(
        "Requires BITGET_LIVE_TEST_USER_ID env var (default admin=1 on "
        "legacy server). These tests hit Bitget Demo — use sparingly."
    ),
)


# ── Helpers ────────────────────────────────────────────────────────────


def _admin_user_id() -> int:
    """Return the user id configured for live tests (default admin=1)."""
    return int(os.getenv("BITGET_LIVE_TEST_USER_ID", "1"))


async def _try_cleanup_position(client, symbol: str, side: str) -> None:
    """Close any open position and cancel every TP/SL/trailing plan.

    Swallows errors because cleanup runs in a ``finally`` and must never
    mask the actual test failure. The next test's fixture guarantees a
    clean slate by doing the same thing before it opens a new position.
    """
    try:
        await client.close_position(symbol, side)
    except Exception:  # noqa: BLE001 — cleanup is best-effort
        pass
    try:
        await client.cancel_position_tpsl(symbol=symbol, side=side)
    except Exception:  # noqa: BLE001 — cleanup is best-effort
        pass


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def admin_bitget_client():
    """Return the admin user's Bitget-demo ``ExchangeClient``.

    Skips the test if no Bitget demo client is configured for the admin
    user — this keeps the suite safe to run on dev machines that only
    hold unit-test fixtures.
    """
    from src.exchanges.factory import get_all_user_clients
    from src.models.session import get_session

    user_id = _admin_user_id()

    async with get_session() as db:
        clients = await get_all_user_clients(user_id=user_id, db=db)

    bitget_demo = [
        client for (ex_type, demo, client) in clients
        if ex_type == "bitget" and demo
    ]
    if not bitget_demo:
        pytest.skip(
            f"No Bitget demo client configured for user_id={user_id}. "
            "Live tests require an admin Bitget-demo connection."
        )

    client = bitget_demo[0]
    try:
        yield client
    finally:
        # Free the HTTP session so pytest doesn't warn about unclosed aiohttp.
        close_fn = getattr(client, "close", None)
        if close_fn is not None:
            try:
                await close_fn()
            except Exception:  # noqa: BLE001 — cleanup is best-effort
                pass


@pytest_asyncio.fixture
async def risk_manager(admin_bitget_client):
    """Build a :class:`RiskStateManager` wired against the admin's demo client.

    The exchange-client factory always returns ``admin_bitget_client`` so
    the manager's Phase B/C calls hit the same exchange-side account the
    test is asserting against. The session factory uses the production
    ``get_session`` contract for real DB writes.
    """
    from src.bot.risk_state_manager import RiskStateManager
    from src.models.session import get_session

    @asynccontextmanager
    async def _session_factory():
        async with get_session() as session:
            yield session

    def _exchange_factory(user_id: int, exchange: str, demo_mode: bool):
        # RiskStateManager accepts either sync or awaitable factories.
        return admin_bitget_client

    return RiskStateManager(
        exchange_client_factory=_exchange_factory,
        session_factory=_session_factory,
    )


async def _open_position(
    client,
    *,
    symbol: str,
    side: str,
) -> dict:
    """Place a market entry and persist the trade to the DB.

    Returns a dict with the keys the tests consume: ``trade_id``, ``symbol``,
    ``side``, ``user_id``, ``size``. The DB row is the same one the
    RiskStateManager will mutate in its 2-Phase-Commit path.
    """
    from sqlalchemy import select

    from src.models.database import BotConfig, ExchangeConnection, TradeRecord
    from src.models.session import get_session

    user_id = _admin_user_id()

    # Clean up any leftover state from a previous test run before opening.
    await _try_cleanup_position(client, symbol, side)

    ticker = await client.get_ticker(symbol)
    assert ticker and ticker.last_price > 0, (
        f"Cannot get a valid ticker for {symbol}; Bitget demo may be down."
    )

    order = await client.place_market_order(
        symbol=symbol,
        side=side,
        size=LIVE_TEST_SIZE,
        leverage=LIVE_TEST_LEVERAGE,
        margin_mode=LIVE_TEST_MARGIN_MODE,
    )
    if order is None or not order.order_id:
        raise RuntimeError(
            f"Bitget demo rejected the market-order for {symbol} {side}: {order}"
        )

    # Give the exchange a brief moment so the position shows up.
    await asyncio.sleep(READBACK_DELAY_SECONDS)

    async with get_session() as db:
        # Resolve the bitget connection to make sure the demo credentials
        # match what the factory returned — this protects against stale
        # DB state where the admin was re-provisioned mid-run.
        conn_row = (await db.execute(
            select(ExchangeConnection).where(
                ExchangeConnection.user_id == user_id,
                ExchangeConnection.exchange_type == "bitget",
            )
        )).scalar_one_or_none()
        if conn_row is None:
            raise RuntimeError(
                f"No Bitget ExchangeConnection for user_id={user_id} — "
                "test database is out of sync with the live credentials."
            )

        # Pick any existing bot_config for this user to satisfy the foreign
        # key; fall back to NULL if the admin has none configured yet.
        bot_row = (await db.execute(
            select(BotConfig).where(BotConfig.user_id == user_id).limit(1)
        )).scalar_one_or_none()
        bot_config_id = bot_row.id if bot_row is not None else None

        trade = TradeRecord(
            user_id=user_id,
            bot_config_id=bot_config_id,
            exchange="bitget",
            symbol=symbol,
            side=side,
            size=LIVE_TEST_SIZE,
            entry_price=ticker.last_price,
            leverage=LIVE_TEST_LEVERAGE,
            confidence=80,
            reason="live_integration_test (#197)",
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
        "size": LIVE_TEST_SIZE,
        "entry_price": ticker.last_price,
        "entry_order_id": str(order.order_id),
    }


async def _teardown_trade(client, trade_info: dict) -> None:
    """Close + cancel on exchange, mark DB row as closed (best-effort)."""
    from src.models.database import TradeRecord
    from src.models.session import get_session

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
async def demo_long_position(admin_bitget_client) -> AsyncIterator[dict]:
    """Open a 0.001 BTCUSDT long demo position, tear it down in ``finally``.

    Yields a dict with ``trade_id``, ``user_id``, ``symbol``, ``side``,
    ``size``, ``entry_price``, and ``entry_order_id``.
    """
    trade_info: Optional[dict] = None
    try:
        trade_info = await _open_position(
            admin_bitget_client, symbol=LIVE_TEST_SYMBOL, side="long",
        )
        yield trade_info
    finally:
        if trade_info is not None:
            await _teardown_trade(admin_bitget_client, trade_info)


@pytest_asyncio.fixture
async def demo_short_position(admin_bitget_client) -> AsyncIterator[dict]:
    """Open a 0.001 BTCUSDT short demo position, tear it down in ``finally``."""
    trade_info: Optional[dict] = None
    try:
        trade_info = await _open_position(
            admin_bitget_client, symbol=LIVE_TEST_SYMBOL, side="short",
        )
        yield trade_info
    finally:
        if trade_info is not None:
            await _teardown_trade(admin_bitget_client, trade_info)
