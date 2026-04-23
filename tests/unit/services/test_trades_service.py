"""Unit tests for ``TradesService`` (ARCH-C1 Phase 2a PR-3).

These tests exercise the service directly — no FastAPI stack, no HTTP
client. A fresh in-memory SQLite engine is built per test via the module
fixtures below, following the same pattern used by
``tests/unit/services/test_affiliate_creds_from_db.py``.

What's covered
--------------
* ``list_trades`` — empty user, populated user, filter-by-symbol ilike match
* ``get_filter_options`` — empty user, populated user with distinct values

What's intentionally *not* covered here
---------------------------------------
* HTTP shape / status codes — owned by the characterization tests in
  ``tests/integration/test_trades_router_characterization.py``.
* Trailing-stop enrichment — the fixture trades have no bot / no
  override, so the ``trailing`` dict stays empty (same as the current
  handler behavior for open-only-no-strategy trades).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from src.models.database import (  # noqa: E402
    Base,
    BotConfig,
    TradeRecord,
    User,
)
from src.services.trades_service import (  # noqa: E402
    FilterOptionsResult,
    Pagination,
    TradeFilters,
    TradeListResult,
    TradesService,
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
            username="svc_user",
            email="svc@example.com",
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
    """Seed three trades (two symbols, two statuses, one exchange)."""
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
            confidence=70,
            reason="t1",
            order_id="svc_t1",
            status="closed",
            entry_time=now - timedelta(days=5),
            exit_time=now - timedelta(days=4),
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=user.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            leverage=3,
            confidence=65,
            reason="t2",
            order_id="svc_t2",
            status="closed",
            entry_time=now - timedelta(days=3),
            exit_time=now - timedelta(days=2),
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.02,
            entry_price=94000.0,
            leverage=4,
            confidence=60,
            reason="t3 open",
            order_id="svc_t3",
            status="open",
            entry_time=now - timedelta(hours=2),
            exchange="bitget",
            demo_mode=True,
        ),
    ]
    async with session_factory() as s:
        s.add_all(trades)
        await s.commit()
    return user


# ---------------------------------------------------------------------------
# list_trades
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_trades_empty_user_returns_zero(session_factory, user):
    """User with no trades → empty result, total=0, echoed pagination."""
    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.list_trades(TradeFilters(), Pagination(page=1, per_page=50))

    assert isinstance(result, TradeListResult)
    assert result.items == []
    assert result.total == 0
    assert result.page == 1
    assert result.per_page == 50


@pytest.mark.asyncio
async def test_list_trades_populated_user_returns_all_ordered_desc(
    session_factory, populated_user,
):
    """Three trades → total=3, ordered newest-first by entry_time."""
    async with session_factory() as s:
        svc = TradesService(db=s, user=populated_user)
        result = await svc.list_trades(TradeFilters(), Pagination(page=1, per_page=50))

    assert result.total == 3
    assert len(result.items) == 3
    # Newest first — the "open" row (entry_time = now - 2h) comes first.
    symbols_in_order = [item.symbol for item in result.items]
    assert symbols_in_order[0] == "BTCUSDT"
    assert result.items[0].status == "open"
    # Trailing enrichment dict is empty for a bot-less open trade.
    assert result.items[0].trailing == {}


@pytest.mark.asyncio
async def test_list_trades_filter_by_symbol_returns_matching_only(
    session_factory, populated_user,
):
    """``symbol=ETH`` (ilike contains) filters to the single ETH trade."""
    async with session_factory() as s:
        svc = TradesService(db=s, user=populated_user)
        result = await svc.list_trades(
            TradeFilters(symbol="ETH"), Pagination(page=1, per_page=50),
        )

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].symbol == "ETHUSDT"


# ---------------------------------------------------------------------------
# get_filter_options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_filter_options_empty_user_returns_empty_collections(
    session_factory, user,
):
    """No trades + no bots → all four collections are empty lists."""
    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.get_filter_options()

    assert isinstance(result, FilterOptionsResult)
    assert result.symbols == []
    assert result.bots == []
    assert result.exchanges == []
    assert result.statuses == []


@pytest.mark.asyncio
async def test_get_filter_options_populated_user_returns_distinct_sorted(
    session_factory, populated_user,
):
    """Populated user → distinct sorted symbols, exchanges, statuses.

    A bot owned by the user but with no trades still contributes its
    ``exchange_type`` to the exchanges set (union of TradeRecord.exchange +
    BotConfig.exchange_type) — this test pins that behavior.
    """
    # Add a bot on a different exchange to exercise the exchange union.
    async with session_factory() as s:
        s.add(BotConfig(
            user_id=populated_user.id,
            name="Alpha Bot",
            description="unit-test bot",
            strategy_type="edge_indicator",
            exchange_type="hyperliquid",
            mode="demo",
            trading_pairs='["BTCUSDT"]',
            leverage=3,
            position_size_percent=5.0,
            max_trades_per_day=1,
            take_profit_percent=2.0,
            stop_loss_percent=1.0,
            daily_loss_limit_percent=3.0,
            is_enabled=False,
        ))
        await s.commit()

    async with session_factory() as s:
        svc = TradesService(db=s, user=populated_user)
        result = await svc.get_filter_options()

    assert result.symbols == ["BTCUSDT", "ETHUSDT"]
    # bitget (from trades) + hyperliquid (from the bot) — sorted.
    assert result.exchanges == ["bitget", "hyperliquid"]
    assert set(result.statuses) == {"open", "closed"}
    # Bots present: the one "Alpha Bot" we added above.
    assert [b.name for b in result.bots] == ["Alpha Bot"]
    assert result.bots[0].id > 0
