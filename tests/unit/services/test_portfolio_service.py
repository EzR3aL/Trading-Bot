"""Unit tests for ``PortfolioService`` (ARCH-C1 Phase 2a PR-5).

Tests exercise the service directly — no FastAPI stack, no HTTP client.
A fresh in-memory SQLite engine is built per test, matching the pattern
used by ``tests/unit/services/test_trades_service.py``.

What's covered
--------------
* ``get_summary`` — empty user + populated user (per-exchange aggregation)
* ``list_positions`` — no clients + one mocked exchange with a live position
* ``get_daily`` — empty user + populated user (grouped per-date/exchange)
* ``get_allocation`` — no clients + two mocked exchanges with balances

What's intentionally *not* covered here
---------------------------------------
* HTTP shape / response-model mapping — owned by
  ``tests/integration/test_portfolio_router_characterization.py``.
* TTL caching — owned by the router (the service always computes).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Env bootstrapping must happen before any src imports.
os.environ.setdefault(
    "JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production",
)
os.environ.setdefault(
    "ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==",
)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.auth.password import hash_password  # noqa: E402
from src.exchanges.types import Balance, Position  # noqa: E402
from src.models.database import (  # noqa: E402
    Base,
    TradeRecord,
    User,
)
from src.services.portfolio_service import (  # noqa: E402
    PortfolioAllocationItem,
    PortfolioDailyItem,
    PortfolioPositionItem,
    PortfolioService,
    PortfolioSummaryResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    """Fresh in-memory SQLite engine per test (no cross-test contamination)."""
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
    """An ``async_sessionmaker`` bound to the test engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def user(session_factory) -> User:
    """A realistic user row; used as the owner of all seeded trades."""
    async with session_factory() as s:
        u = User(
            username="portfolio_user",
            email="portfolio@example.com",
            password_hash=hash_password("pw"),
            role="user",
            is_active=True,
            language="en",
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


@pytest_asyncio.fixture
async def populated_user(session_factory, user) -> User:
    """Seed three closed trades across two exchanges (bitget + hyperliquid)."""
    now = datetime.now(timezone.utc)
    trades = [
        TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            leverage=4,
            confidence=75,
            reason="winner bitget",
            order_id="port_t1",
            status="closed",
            pnl=10.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            entry_time=now - timedelta(days=5),
            exit_time=now - timedelta(days=4),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=user.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            exit_price=3400.0,
            leverage=4,
            confidence=80,
            reason="winner bitget",
            order_id="port_t2",
            status="closed",
            pnl=10.0,
            pnl_percent=2.86,
            fees=0.3,
            funding_paid=0.05,
            entry_time=now - timedelta(days=3),
            exit_time=now - timedelta(days=2),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.02,
            entry_price=94000.0,
            exit_price=93000.0,
            leverage=4,
            confidence=60,
            reason="loser hyperliquid",
            order_id="port_t3",
            status="closed",
            pnl=-20.0,
            pnl_percent=-1.06,
            fees=0.4,
            funding_paid=0.08,
            entry_time=now - timedelta(days=2),
            exit_time=now - timedelta(days=1),
            exit_reason="STOP_LOSS",
            exchange="hyperliquid",
            demo_mode=False,
        ),
    ]
    async with session_factory() as s:
        s.add_all(trades)
        await s.commit()
    return user


def _make_client(
    positions: list[Position] | None = None,
    balance: Balance | None = None,
) -> MagicMock:
    """Build a mock exchange client matching the ExchangeClient interface."""
    client = MagicMock()
    client.get_open_positions = AsyncMock(return_value=positions or [])
    client.get_account_balance = AsyncMock(
        return_value=balance
        or Balance(total=0.0, available=0.0, unrealized_pnl=0.0, currency="USDT")
    )
    return client


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_summary_empty_user_returns_zeroed_shape(
    session_factory, user,
):
    """User with no trades → grand totals all 0 and exchanges list is empty."""
    async with session_factory() as s:
        svc = PortfolioService(db=s, user=user)
        result = await svc.get_summary(days=30, demo_mode=None)

    assert isinstance(result, PortfolioSummaryResult)
    assert result.total_pnl == 0
    assert result.total_trades == 0
    assert result.overall_win_rate == 0
    assert result.total_fees == 0
    assert result.total_funding == 0
    assert result.exchanges == []


@pytest.mark.asyncio
async def test_get_summary_populated_user_aggregates_per_exchange(
    session_factory, populated_user,
):
    """Three closed trades across two exchanges produce the expected totals."""
    async with session_factory() as s:
        svc = PortfolioService(db=s, user=populated_user)
        result = await svc.get_summary(days=30, demo_mode=None)

    assert result.total_trades == 3
    assert result.total_pnl == pytest.approx(0.0, abs=0.01)
    assert result.total_fees == pytest.approx(1.2, abs=0.01)
    assert result.total_funding == pytest.approx(0.23, abs=0.01)
    assert result.overall_win_rate == pytest.approx(2 / 3 * 100, abs=0.1)

    by_exchange = {e.exchange: e for e in result.exchanges}
    assert set(by_exchange.keys()) == {"bitget", "hyperliquid"}
    assert by_exchange["bitget"].total_trades == 2
    assert by_exchange["bitget"].winning_trades == 2
    assert by_exchange["bitget"].win_rate == pytest.approx(100.0, abs=0.1)
    assert by_exchange["hyperliquid"].total_trades == 1
    assert by_exchange["hyperliquid"].winning_trades == 0
    assert by_exchange["hyperliquid"].win_rate == 0
    assert by_exchange["hyperliquid"].total_pnl == pytest.approx(-20.0, abs=0.01)


# ---------------------------------------------------------------------------
# list_positions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_positions_no_clients_returns_empty_list(
    session_factory, user,
):
    """No clients loader configured → short-circuit to []."""
    async with session_factory() as s:
        svc = PortfolioService(db=s, user=user)
        result = await svc.list_positions()

    assert result == []


@pytest.mark.asyncio
async def test_list_positions_single_exchange_builds_enriched_item(
    session_factory, user,
):
    """One mocked bitget client with one live position → one enriched item."""
    fake_position = Position(
        symbol="BTCUSDT",
        side="long",
        size=0.01,
        entry_price=95000.0,
        current_price=96000.0,
        unrealized_pnl=10.0,
        leverage=4,
        exchange="bitget",
        margin=237.5,
    )
    fake_client = _make_client(positions=[fake_position])

    async def loader(user_id, db):  # noqa: ARG001
        return [("bitget", False, fake_client)]

    async with session_factory() as s:
        svc = PortfolioService(db=s, user=user, clients_loader=loader)
        result = await svc.list_positions()

    assert len(result) == 1
    item = result[0]
    assert isinstance(item, PortfolioPositionItem)
    assert item.exchange == "bitget"
    assert item.symbol == "BTCUSDT"
    assert item.side == "long"
    assert item.size == pytest.approx(0.01)
    assert item.unrealized_pnl == pytest.approx(10.0)
    assert item.leverage == 4
    # No DB trade matches this exchange-position → bot_name/trade-derived
    # fields stay None and demo_mode falls through to the client's flag.
    assert item.trade_id is None
    assert item.bot_name is None
    assert item.demo_mode is False
    assert item.trailing_stop_active is False


# ---------------------------------------------------------------------------
# get_daily
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_daily_empty_user_returns_empty_list(
    session_factory, user,
):
    """No trades → empty timeseries."""
    async with session_factory() as s:
        svc = PortfolioService(db=s, user=user)
        result = await svc.get_daily(days=30, demo_mode=None)

    assert result == []


@pytest.mark.asyncio
async def test_get_daily_populated_user_groups_by_date_and_exchange(
    session_factory, populated_user,
):
    """Daily timeseries groups each (date, exchange) into its own bucket."""
    async with session_factory() as s:
        svc = PortfolioService(db=s, user=populated_user)
        result = await svc.get_daily(days=30, demo_mode=None)

    assert len(result) >= 1
    assert all(isinstance(item, PortfolioDailyItem) for item in result)

    # Total trade count and summed PnL match the seeded closed trades.
    assert sum(item.trades for item in result) == 3
    assert sum(item.pnl for item in result) == pytest.approx(0.0, abs=0.01)
    assert {item.exchange for item in result} == {"bitget", "hyperliquid"}


# ---------------------------------------------------------------------------
# get_allocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_allocation_no_clients_returns_empty_list(
    session_factory, user,
):
    """No clients loader configured → short-circuit to []."""
    async with session_factory() as s:
        svc = PortfolioService(db=s, user=user)
        result = await svc.get_allocation()

    assert result == []


@pytest.mark.asyncio
async def test_get_allocation_two_exchanges_returns_balance_buckets(
    session_factory, user,
):
    """Two mocked exchanges → two allocation buckets with the right totals."""
    bitget_client = _make_client(
        balance=Balance(
            total=1000.0, available=800.0, unrealized_pnl=0.0, currency="USDT"
        )
    )
    hl_client = _make_client(
        balance=Balance(
            total=500.0, available=500.0, unrealized_pnl=0.0, currency="USDT"
        )
    )

    async def loader(user_id, db):  # noqa: ARG001
        return [
            ("bitget", False, bitget_client),
            ("hyperliquid", False, hl_client),
        ]

    async with session_factory() as s:
        svc = PortfolioService(db=s, user=user, clients_loader=loader)
        result = await svc.get_allocation()

    assert len(result) == 2
    assert all(isinstance(item, PortfolioAllocationItem) for item in result)

    by_exchange = {item.exchange: item for item in result}
    assert by_exchange["bitget"].balance == pytest.approx(1000.0)
    assert by_exchange["bitget"].currency == "USDT"
    assert by_exchange["hyperliquid"].balance == pytest.approx(500.0)
