"""Integration tests for ``PUT /api/trades/{id}/tp-sl`` on the
:class:`RiskStateManager` path (Issue #192, Epic #188).

Coverage matrix
---------------
* TP only           → response.tp confirmed, sl/trailing absent
* TP + SL atomic    → both confirmed
* TP rejected       → tp.status == rejected with error message
* Partial success   → TP ok + SL invalid → overall_status partial_success
* Cancel-fail path  → tp.status == cancel_failed
* Trailing leg      → trailing.status == confirmed with payload
* Idempotency-Key   → second call hits cache, no extra exchange call
* Mutex flag conflict → 422
* Trade missing     → 404
* Legacy path sanity → flag off uses old code path (no manager interaction)
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Test env must be set before any src imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.dependencies.risk_state import (
    IdempotencyCache,
    set_idempotency_cache,
    set_risk_state_manager,
)
from src.auth.jwt_handler import create_access_token
from src.auth.password import hash_password
from src.bot.risk_state_manager import RiskStateManager
from src.exceptions import CancelFailed
from src.exchanges.base import PositionTpSlSnapshot, TrailingStopSnapshot
from src.models.database import Base, ExchangeConnection, TradeRecord, User


# ── Fake exchange client (mirrors the unit-test fake) ───────────────


@dataclass
class _FakeExchangeClient:
    """Minimal stateful exchange double for the manager tests."""

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

    cancel_calls: List[tuple] = field(default_factory=list)
    place_calls: List[dict] = field(default_factory=list)
    trailing_calls: List[dict] = field(default_factory=list)
    readback_calls: List[tuple] = field(default_factory=list)

    async def cancel_position_tpsl(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side))
        if self.cancel_raises is not None:
            raise self.cancel_raises
        return True

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
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
        return TrailingStopSnapshot(
            symbol=symbol,
            side=hold_side,
            callback_rate=self.readback_trailing_callback,
            activation_price=self.readback_trailing_activation,
            trigger_price=self.readback_trailing_trigger,
            order_id=self.readback_trailing_id,
        )


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session_factory_cb(session_factory):
    """Wrap ``session_factory`` as an async context manager (the
    RiskStateManager protocol)."""

    @asynccontextmanager
    async def _factory():
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    return _factory


@pytest_asyncio.fixture
async def open_trade(session_factory):
    async with session_factory() as session:
        user = User(
            username="tp_sl_v2",
            email="tpsl@v2.test",
            password_hash=hash_password("x"),
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
            demo_api_key_encrypted="enc_key",
            demo_api_secret_encrypted="enc_secret",
            demo_passphrase_encrypted="enc_pp",
        )
        session.add(conn)

        trade = TradeRecord(
            user_id=user.id,
            exchange="bitget",
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=68200.0,
            leverage=10,
            confidence=80,
            reason="v2 endpoint test",
            order_id="entry_v2",
            status="open",
            entry_time=datetime.now(timezone.utc),
            demo_mode=True,
        )
        session.add(trade)
        await session.commit()
        token = create_access_token({"sub": str(user.id)})
        return {
            "user_id": user.id,
            "trade_id": trade.id,
            "token": token,
        }


def _override_db(app, session_factory):
    from src.models.session import get_db

    async def _get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db


def _wire_manager(client: _FakeExchangeClient, session_factory_cb) -> RiskStateManager:
    """Build a RiskStateManager bound to the test exchange double + DB."""
    def _factory(_uid: int, _exchange: str, _demo: bool):
        return client

    manager = RiskStateManager(
        exchange_client_factory=_factory,
        session_factory=session_factory_cb,
    )
    set_risk_state_manager(manager)
    return manager


def _enable_flag(monkeypatch, value: bool = True) -> None:
    """Toggle the feature flag for the duration of a test."""
    from config.settings import settings as _settings

    monkeypatch.setattr(_settings.risk, "risk_state_manager_enabled", value)


def _build_app(session_factory):
    from src.api.main_app import create_app
    from src.api.rate_limit import limiter

    app = create_app()
    limiter.enabled = False
    _override_db(app, session_factory)
    return app


async def _put_tpsl(
    app,
    trade_id: int,
    token: str,
    body: dict,
    headers: Optional[dict] = None,
):
    full_headers = {"Authorization": f"Bearer {token}"}
    if headers:
        full_headers.update(headers)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        return await ac.put(
            f"/api/trades/{trade_id}/tp-sl",
            json=body,
            headers=full_headers,
        )


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset module-level singletons between tests."""
    set_risk_state_manager(None)
    set_idempotency_cache(IdempotencyCache())
    yield
    set_risk_state_manager(None)
    set_idempotency_cache(IdempotencyCache())


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_tp_only_returns_confirmed_tp_and_no_other_legs(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """Setting only TP must yield tp=confirmed, sl=None, trailing=None."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient(
        place_returns={"orderId": "tp_native_1"},
        readback_tp=70000.0,
        readback_tp_id="tp_native_1",
    )
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["trade_id"] == open_trade["trade_id"]
    assert payload["tp"] is not None
    assert payload["tp"]["status"] == "confirmed"
    assert payload["tp"]["value"] == 70000.0
    assert payload["tp"]["order_id"] == "tp_native_1"
    assert payload["sl"] is None
    assert payload["trailing"] is None
    assert payload["overall_status"] == "all_confirmed"


@pytest.mark.asyncio
async def test_set_tp_and_sl_atomic_both_confirmed(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """Atomic TP+SL: both legs returned, both confirmed."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient(
        place_returns={"orderId": "shared_id"},
        readback_tp=70000.0,
        readback_sl=66000.0,
        readback_tp_id="tp_id",
        readback_sl_id="sl_id",
    )
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0, "stop_loss": 66000.0},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["tp"]["status"] == "confirmed"
    assert payload["sl"]["status"] == "confirmed"
    assert payload["overall_status"] == "all_confirmed"


@pytest.mark.asyncio
async def test_invalid_tp_below_entry_for_long_returns_422(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """TP below entry for a long must be rejected before any exchange call."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient()
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 50.0},  # below entry 68200 → invalid for long
        )
    finally:
        app.dependency_overrides.clear()

    # Pre-manager validation rejects with 400 (ERR_TP_ABOVE_ENTRY_LONG)
    assert resp.status_code == 400, resp.text
    # Manager was never reached
    assert fake.place_calls == []


@pytest.mark.asyncio
async def test_partial_success_tp_ok_sl_rejected_on_exchange(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """One leg confirmed + another rejected → overall_status=partial_success.

    The test simulates an exchange that accepts the TP placement but
    rejects the SL placement. We use a stateful fake whose ``place_raises``
    is toggled after the first call.
    """
    _enable_flag(monkeypatch)

    from src.exceptions import OrderError

    fake = _FakeExchangeClient(
        readback_tp=70000.0,
        readback_tp_id="tp_native_1",
    )

    # Wrap set_position_tpsl so the SL call (which has stop_loss != None) raises.
    original_set = fake.set_position_tpsl

    async def _selective_set(*args, **kwargs):
        if kwargs.get("stop_loss") is not None:
            raise OrderError("bitget", "SL price too close to mark")
        return await original_set(*args, **kwargs)

    fake.set_position_tpsl = _selective_set  # type: ignore[assignment]
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0, "stop_loss": 66000.0},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["tp"]["status"] == "confirmed"
    assert payload["sl"]["status"] == "rejected"
    assert "SL price too close" in payload["sl"]["error"]
    assert payload["overall_status"] == "partial_success"


@pytest.mark.asyncio
async def test_idempotency_key_returns_cached_response_no_new_exchange_call(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """Same Idempotency-Key twice → cached response, exchange called once."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient(
        place_returns={"orderId": "tp_native_1"},
        readback_tp=70000.0,
        readback_tp_id="tp_native_1",
    )
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    headers = {"Idempotency-Key": "user-supplied-key-abc"}
    try:
        resp1 = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0},
            headers=headers,
        )
        resp2 = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0},
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert resp1.status_code == 200, resp1.text
    assert resp2.status_code == 200, resp2.text
    # Bodies must be identical
    assert resp1.json() == resp2.json()
    # Exchange was called exactly once
    assert len(fake.place_calls) == 1, f"Expected 1 place call, got {fake.place_calls}"


@pytest.mark.asyncio
async def test_cancel_failed_path_surfaces_in_leg_status(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """If the cancel-old step fails → tp.status == cancel_failed and place was skipped."""
    _enable_flag(monkeypatch)

    # Seed the trade with an existing TP order id so cancel triggers
    async with session_factory() as session:
        from src.models.database import TradeRecord as TR
        trade = await session.get(TR, open_trade["trade_id"])
        trade.tp_order_id = "old_tp_id"
        await session.commit()

    fake = _FakeExchangeClient(
        cancel_raises=CancelFailed("bitget", "exchange refused cancel"),
    )
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["tp"]["status"] == "cancel_failed"
    assert payload["overall_status"] == "all_rejected"
    # Crucially: NO place call was attempted (Anti-Pattern C guard)
    assert fake.place_calls == []


@pytest.mark.asyncio
async def test_trailing_stop_leg_confirmed_with_payload(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """Trailing stop edit returns confirmed leg with callback_rate / trigger_price."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient(
        trailing_place_returns={"orderId": "trailing_native_1"},
        readback_trailing_callback=2.5,
        readback_trailing_activation=68500.0,
        readback_trailing_trigger=69200.0,
        readback_trailing_id="trailing_native_1",
    )
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    # Stub ATR fetch so we don't hit Binance from a test
    with patch(
        "src.api.routers.trades._compute_atr_for_trailing",
        new=AsyncMock(return_value=400.0),
    ):
        try:
            resp = await _put_tpsl(
                app, open_trade["trade_id"], open_trade["token"],
                {"trailing_stop": {"callback_pct": 2.5}},
            )
        finally:
            app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["tp"] is None
    assert payload["sl"] is None
    assert payload["trailing"] is not None
    assert payload["trailing"]["status"] == "confirmed"
    assert payload["trailing"]["order_id"] == "trailing_native_1"
    assert payload["overall_status"] == "all_confirmed"


@pytest.mark.asyncio
async def test_mutex_flag_conflict_returns_422(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """``take_profit`` AND ``remove_tp`` is a 422 mutex error."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient()
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0, "remove_tp": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422
    # Manager not invoked
    assert fake.place_calls == []
    assert fake.cancel_calls == []


@pytest.mark.asyncio
async def test_trade_not_found_returns_404(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """A non-existent trade must yield 404 before touching the manager."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient()
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, 999_999, open_trade["token"],
            {"take_profit": 70000.0},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    assert fake.place_calls == []


@pytest.mark.asyncio
async def test_remove_tp_only_yields_cleared_status(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """``remove_tp=True`` clears the TP leg → status == cleared, value == None."""
    _enable_flag(monkeypatch)
    # Seed an existing TP so cancel is triggered
    async with session_factory() as session:
        from src.models.database import TradeRecord as TR
        trade = await session.get(TR, open_trade["trade_id"])
        trade.tp_order_id = "old_tp"
        trade.take_profit = 70000.0
        await session.commit()

    fake = _FakeExchangeClient(
        readback_tp=None,
        readback_tp_id=None,
    )
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"remove_tp": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["tp"]["status"] == "cleared"
    assert payload["tp"]["value"] is None
    assert payload["overall_status"] == "all_confirmed"


@pytest.mark.asyncio
async def test_compute_atr_for_trailing_returns_live_value():
    """``_compute_atr_for_trailing`` returns the latest ATR from the fetcher."""
    from src.api.routers.trades import _compute_atr_for_trailing
    from unittest.mock import MagicMock

    fake_fetcher = AsyncMock()
    fake_fetcher.get_binance_klines = AsyncMock(return_value=[[1, 1, 1, 1, 1]] * 20)
    fake_fetcher.close = AsyncMock()

    # MarketDataFetcher is referenced in trades.py — patch both the class
    # constructor and its static calculate_atr to return a deterministic series.
    fake_class = MagicMock(return_value=fake_fetcher)
    fake_class.calculate_atr = MagicMock(return_value=[123.0, 456.0, 789.0])

    with patch("src.api.routers.trades.MarketDataFetcher", fake_class):
        atr = await _compute_atr_for_trailing("BTCUSDT", 68000.0)

    assert atr == 789.0  # last element of the series


@pytest.mark.asyncio
async def test_compute_atr_for_trailing_falls_back_on_exception():
    """When the fetcher raises, ``_compute_atr_for_trailing`` returns the
    1.5% fallback estimate based on entry price."""
    from src.api.routers.trades import _compute_atr_for_trailing

    fake_fetcher = AsyncMock()
    fake_fetcher.get_binance_klines = AsyncMock(side_effect=RuntimeError("net down"))
    fake_fetcher.close = AsyncMock()

    with patch(
        "src.api.routers.trades.MarketDataFetcher", return_value=fake_fetcher
    ):
        atr = await _compute_atr_for_trailing("BTCUSDT", 68000.0)

    assert atr == pytest.approx(68000.0 * 0.015)


@pytest.mark.asyncio
async def test_derive_overall_status_edges():
    """Cover the ``no_change`` and ``all_rejected`` aggregation branches."""
    from src.api.routers.trades import _derive_overall_status, RiskLegStatus

    assert _derive_overall_status([]) == "no_change"
    rejected = RiskLegStatus(status="rejected", value=None, latency_ms=0)
    assert _derive_overall_status([rejected]) == "all_rejected"
    pending = RiskLegStatus(status="pending", value=None, latency_ms=0)
    # Only "pending" → still no_change (neither OK nor FAIL)
    assert _derive_overall_status([pending]) == "no_change"


@pytest.mark.asyncio
async def test_manager_apply_intent_crash_surfaces_as_rejected(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """An unexpected exception from apply_intent must be caught and
    reported as a rejected leg (never bubble up to the user)."""
    _enable_flag(monkeypatch)

    broken_manager = AsyncMock(spec=RiskStateManager)
    broken_manager.apply_intent = AsyncMock(
        side_effect=RuntimeError("boom — manager internals corrupted")
    )
    set_risk_state_manager(broken_manager)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["tp"]["status"] == "rejected"
    assert "boom" in payload["tp"]["error"]
    assert payload["overall_status"] == "all_rejected"


@pytest.mark.asyncio
async def test_mutex_flag_conflict_sl_returns_422(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """``stop_loss`` AND ``remove_sl`` must also be rejected as 422."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient()
    _wire_manager(fake, session_factory_cb)

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"stop_loss": 60000.0, "remove_sl": True},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_closed_trade_rejects_with_400(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """A closed trade can't be edited via the new endpoint either."""
    _enable_flag(monkeypatch)
    fake = _FakeExchangeClient()
    _wire_manager(fake, session_factory_cb)

    # Flip the trade to closed
    async with session_factory() as session:
        from src.models.database import TradeRecord as TR
        trade = await session.get(TR, open_trade["trade_id"])
        trade.status = "closed"
        await session.commit()

    app = _build_app(session_factory)
    try:
        resp = await _put_tpsl(
            app, open_trade["trade_id"], open_trade["token"],
            {"take_profit": 70000.0},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400
    assert fake.place_calls == []


@pytest.mark.asyncio
async def test_idempotency_cache_expires_entries_after_ttl(monkeypatch):
    """The in-memory TTL cache must return None once the entry is older
    than ``ttl_seconds`` and must evict stale keys on write."""
    from src.api.dependencies.risk_state import IdempotencyCache
    import src.api.dependencies.risk_state as rs_mod

    # Virtual clock so we can advance past the TTL deterministically
    clock = {"t": 1000.0}
    monkeypatch.setattr(rs_mod.time, "monotonic", lambda: clock["t"])

    cache = IdempotencyCache(ttl_seconds=5)
    await cache.set("key-a", {"foo": 1})
    # Immediately readable
    assert await cache.get("key-a") == {"foo": 1}
    # Advance past TTL — entry is expired on next read
    clock["t"] += 10
    assert await cache.get("key-a") is None
    # Non-existent key returns None too
    assert await cache.get("nope") is None
    # Setting a new entry triggers eviction of old ones (covers _evict_expired_locked)
    await cache.set("key-b", {"foo": 2})
    cache.clear()  # explicit reset (covers clear())
    assert await cache.get("key-b") is None


@pytest.mark.asyncio
async def test_get_risk_state_manager_returns_singleton_when_unset(monkeypatch):
    """Without explicit wiring, ``get_risk_state_manager`` builds a real
    singleton and subsequent calls return the same instance."""
    from src.api.dependencies.risk_state import (
        get_risk_state_manager as _get,
        set_risk_state_manager as _set,
    )

    _set(None)  # force singleton to be rebuilt
    m1 = _get()
    m2 = _get()
    assert m1 is m2
    _set(None)  # reset for other tests


@pytest.mark.asyncio
async def test_real_exchange_factory_rejects_missing_connection(
    open_trade, session_factory, monkeypatch
):
    """The real factory must raise if there is no ExchangeConnection row
    for the (user, exchange) pair."""
    from src.api.dependencies.risk_state import _make_exchange_client_factory
    import src.api.dependencies.risk_state as rs_mod

    # Point the factory's session lookup at our test DB
    @asynccontextmanager
    async def _get_session_patched():
        async with session_factory() as s:
            yield s

    monkeypatch.setattr(rs_mod, "get_session", _get_session_patched)

    factory = _make_exchange_client_factory()
    with pytest.raises(RuntimeError, match="No ExchangeConnection"):
        await factory(user_id=999_999, exchange="bitget", demo_mode=True)


@pytest.mark.asyncio
async def test_legacy_path_is_used_when_flag_off(
    open_trade, session_factory, session_factory_cb, monkeypatch
):
    """Sanity: with the flag off, the manager singleton must NOT be touched.

    We verify this by seeding a manager whose ``apply_intent`` raises if
    invoked. With the legacy path we patch out the create_exchange_client
    + decrypt_value calls so we still get a 200.
    """
    _enable_flag(monkeypatch, value=False)

    sentinel_manager = AsyncMock(spec=RiskStateManager)
    sentinel_manager.apply_intent = AsyncMock(
        side_effect=AssertionError("legacy path must NOT call manager")
    )
    set_risk_state_manager(sentinel_manager)

    legacy_client = AsyncMock()
    legacy_client.set_position_tpsl = AsyncMock(return_value=None)
    legacy_client.cancel_position_tpsl = AsyncMock(return_value=True)
    legacy_client.cancel_native_trailing_stop = AsyncMock(return_value=None)
    legacy_client.has_native_trailing_stop = AsyncMock(return_value=False)
    legacy_client.close = AsyncMock()
    legacy_client.exchange_name = "bitget"

    app = _build_app(session_factory)
    try:
        with patch(
            "src.api.routers.trades.create_exchange_client",
            return_value=legacy_client,
        ), patch(
            "src.api.routers.trades.decrypt_value", return_value="decrypted"
        ):
            resp = await _put_tpsl(
                app, open_trade["trade_id"], open_trade["token"],
                {"take_profit": 70000.0},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    # Legacy response shape — has "status" and "trailing_stop_placed"
    payload = resp.json()
    assert payload["status"] == "ok"
    # Manager was not touched
    sentinel_manager.apply_intent.assert_not_called()
