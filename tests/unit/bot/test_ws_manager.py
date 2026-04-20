"""Unit tests for :class:`src.bot.ws_manager.WebSocketManager` (#216).

Covers:
* Reconnect triggers an RSM.reconcile sweep for every open trade of the
  affected ``(user, exchange)``.
* ``stop_all`` disposes every active client exactly once.
* Feature flag gate — ``start_for_user`` returns ``None`` when disabled.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.ws_manager import WebSocketManager
from src.exchanges.websockets.base import ExchangeWebSocketClient
from src.models.database import Base, TradeRecord, User


# ── Fakes ────────────────────────────────────────────────────────────


class _FakeRSM:
    """Minimal RSM double — records reconcile calls."""

    def __init__(self) -> None:
        self.reconcile_calls: List[int] = []
        self.event_calls: List[tuple] = []

    async def reconcile(self, trade_id: int):
        self.reconcile_calls.append(trade_id)

    async def on_exchange_event(self, **kwargs):
        self.event_calls.append(kwargs)


class _FakeClient(ExchangeWebSocketClient):
    """Minimal WS client double — never opens a real transport."""

    def __init__(self, *, user_id: int, exchange: str, on_event, on_reconnect) -> None:
        super().__init__(
            user_id=user_id,
            exchange=exchange,
            on_event=on_event,
            on_reconnect=on_reconnect,
        )
        self.disconnect_calls = 0

    async def _connect_transport(self):
        return object()

    async def _subscribe(self) -> None:
        return None

    async def _read_once(self):
        await asyncio.sleep(3600)
        return None

    def _parse_message(self, raw):
        return None

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False


# ── Fixtures ─────────────────────────────────────────────────────────


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
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory_cb(engine):
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
async def seeded(engine):
    """Two open bitget trades for user 42 plus one on a different exchange."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user = User(
            username="ws-tester",
            email="ws@example.com",
            password_hash="x",
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        def _trade(symbol: str, exchange: str = "bitget", status: str = "open"):
            return TradeRecord(
                user_id=user.id,
                exchange=exchange,
                symbol=symbol,
                side="long",
                size=0.01,
                entry_price=100.0,
                leverage=10,
                confidence=80,
                reason="ws test",
                order_id=f"o-{symbol}",
                status=status,
                entry_time=datetime.now(timezone.utc),
                demo_mode=True,
            )

        trades = [
            _trade("BTCUSDT"),
            _trade("ETHUSDT"),
            _trade("SOLUSDT", status="closed"),          # should be ignored
            _trade("DOGEUSDT", exchange="hyperliquid"),  # different exchange
        ]
        for t in trades:
            session.add(t)
        await session.commit()
        for t in trades:
            await session.refresh(t)
        return {"user_id": user.id, "trade_ids": [t.id for t in trades]}


def _build_manager(rsm, session_factory, *, client_holder=None):
    async def _creds(user_id, exchange):
        return {"api_key": "k", "api_secret": "s", "passphrase": ""}

    manager = WebSocketManager(
        risk_state_manager=rsm,
        credentials_provider=_creds,
        session_factory=session_factory,
    )

    def _build_client(user_id, exchange, credentials):
        client = _FakeClient(
            user_id=user_id,
            exchange=exchange,
            on_event=manager._on_event,
            on_reconnect=manager._on_reconnect,
        )
        if client_holder is not None:
            client_holder.append(client)
        return client

    manager._build_client = _build_client  # type: ignore[assignment]
    return manager


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_for_user_returns_none_when_flag_disabled(
    monkeypatch, session_factory_cb, seeded,
) -> None:
    """Flag off → start_for_user is a no-op that returns None."""
    monkeypatch.delenv("EXCHANGE_WEBSOCKETS_ENABLED", raising=False)

    rsm = _FakeRSM()
    manager = _build_manager(rsm, session_factory_cb)

    result = await manager.start_for_user(seeded["user_id"], "bitget")
    assert result is None
    await manager.stop_all()


@pytest.mark.asyncio
async def test_on_reconnect_reconciles_every_open_trade_for_user_exchange(
    monkeypatch, session_factory_cb, seeded,
) -> None:
    """Reconnect sweep runs reconcile for every matching open trade only."""
    monkeypatch.setenv("EXCHANGE_WEBSOCKETS_ENABLED", "true")

    rsm = _FakeRSM()
    manager = _build_manager(rsm, session_factory_cb)

    # Invoke the reconnect hook directly — we don't need a live transport
    # to exercise the sweep, and the WS base-class contract guarantees it
    # is called exactly once per successful reconnect.
    await manager._on_reconnect(seeded["user_id"], "bitget")

    # Two open bitget trades were seeded → exactly two reconciles.
    assert len(rsm.reconcile_calls) == 2
    # Closed trade and cross-exchange trade must not be swept.
    bitget_open_ids = set(seeded["trade_ids"][:2])
    assert set(rsm.reconcile_calls) == bitget_open_ids


@pytest.mark.asyncio
async def test_stop_all_disconnects_every_client_exactly_once(
    monkeypatch, session_factory_cb, seeded,
) -> None:
    """stop_all() calls disconnect on each registered client and clears the map."""
    monkeypatch.setenv("EXCHANGE_WEBSOCKETS_ENABLED", "true")

    rsm = _FakeRSM()
    clients: list = []
    manager = _build_manager(rsm, session_factory_cb, client_holder=clients)

    await manager.start_for_user(seeded["user_id"], "bitget")
    await manager.start_for_user(seeded["user_id"], "hyperliquid")
    # Each of the two clients must be a fresh _FakeClient instance.
    assert len(clients) == 2

    await manager.stop_all()

    assert all(c.disconnect_calls == 1 for c in clients)
    # Internal registry is empty — counts are zero, so health reports 0.
    counts = manager.connected_counts()
    assert counts == {"bitget": 0, "hyperliquid": 0}
