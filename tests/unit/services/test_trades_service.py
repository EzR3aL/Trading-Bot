"""Unit tests for ``TradesService`` (ARCH-C1 Phase 2a PR-3 + #325 PR-1).

These tests exercise the service directly — no FastAPI stack, no HTTP
client. A fresh in-memory SQLite engine is built per test via the module
fixtures below, following the same pattern used by
``tests/unit/services/test_affiliate_creds_from_db.py``.

What's covered
--------------
* ``list_trades`` — empty user, populated user, filter-by-symbol ilike match
* ``get_filter_options`` — empty user, populated user with distinct values
* ``get_trade`` — not found, other user's trade (still not found),
  happy path for closed + open rows, bot-linkage projection
* ``get_risk_state_snapshot`` — not found, other user (same 404 shape),
  happy path with confirmed legs, reconcile ValueError → TradeNotFound

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
from src.bot.risk_state_manager import RiskLeg, RiskOpResult, RiskOpStatus  # noqa: E402
from src.models.database import (  # noqa: E402
    Base,
    BotConfig,
    ExchangeConnection,
    TradeRecord,
    User,
)
from src.services.exceptions import (  # noqa: E402
    ExchangeConnectionMissing,
    InvalidTpSlIntent,
    TpSlExchangeNotSupported,
    TpSlUpdateFailed,
    TradeNotFound,
    TradeNotOpen,
)
from src.services.trades_service import (  # noqa: E402
    FilterOptionsResult,
    Pagination,
    RiskLegSnapshot,
    RiskStateSnapshotResult,
    SyncResult,
    TpSlIntent,
    TpSlLegacyResult,
    TpSlManagerResult,
    TradeDetail,
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


# ---------------------------------------------------------------------------
# get_trade — #325 PR-1
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def other_user(session_factory) -> User:
    """A second user used to seed trades owned by somebody else."""
    async with session_factory() as s:
        u = User(
            username="other_user",
            email="other@example.com",
            password_hash=hash_password("pw"),
            role="user",
            is_active=True,
            language="en",
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


@pytest.mark.asyncio
async def test_get_trade_unknown_id_raises_trade_not_found(
    session_factory, user,
):
    """Unknown ``trade_id`` -> ``TradeNotFound``. No 403 branch exists."""
    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TradeNotFound):
            await svc.get_trade(999999)


@pytest.mark.asyncio
async def test_get_trade_other_users_trade_raises_trade_not_found(
    session_factory, user, other_user,
):
    """Another user's trade is indistinguishable from a missing one.

    Ownership is fused into the WHERE clause — this is intentional
    security hardening that prevents existence-leak via status codes.
    """
    async with session_factory() as s:
        t = TradeRecord(
            user_id=other_user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=70,
            reason="not yours",
            order_id="svc_other",
            status="closed",
            entry_time=datetime.now(timezone.utc) - timedelta(days=1),
            exchange="bitget",
            demo_mode=True,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        trade_id = t.id

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TradeNotFound):
            await svc.get_trade(trade_id)


@pytest.mark.asyncio
async def test_get_trade_happy_path_closed_trade_maps_all_fields(
    session_factory, user,
):
    """Closed trade with bot linkage returns every documented field."""
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        bc = BotConfig(
            user_id=user.id,
            name="DetailBot",
            description="detail test bot",
            strategy_type="edge_indicator",
            exchange_type="bitget",
            mode="demo",
            trading_pairs='["BTCUSDT"]',
            leverage=4,
            is_enabled=False,
        )
        s.add(bc)
        await s.flush()
        t = TradeRecord(
            user_id=user.id,
            bot_config_id=bc.id,
            symbol="BTCUSDT",
            side="long",
            size=0.02,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=80,
            reason="closed detail",
            order_id="svc_detail_closed",
            status="closed",
            pnl=20.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            entry_time=now - timedelta(days=2),
            exit_time=now - timedelta(days=1),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        trade_id = t.id

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        detail = await svc.get_trade(trade_id)

    assert isinstance(detail, TradeDetail)
    assert detail.id == trade_id
    assert detail.symbol == "BTCUSDT"
    assert detail.side == "long"
    assert detail.status == "closed"
    assert detail.pnl == 20.0
    assert detail.pnl_percent == 1.05
    assert detail.exit_price == 96000.0
    assert detail.exit_reason == "TAKE_PROFIT"
    assert detail.bot_name == "DetailBot"
    assert detail.bot_exchange == "bitget"
    # Closed trade: no trailing enrichment.
    assert detail.trailing == {}


@pytest.mark.asyncio
async def test_get_trade_open_without_bot_has_empty_trailing(
    session_factory, user,
):
    """Open trade without a bot link -> empty trailing dict, null exit fields."""
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        t = TradeRecord(
            user_id=user.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            leverage=3,
            confidence=60,
            reason="open orphan",
            order_id="svc_detail_open",
            status="open",
            entry_time=now - timedelta(hours=1),
            exchange="bitget",
            demo_mode=True,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        trade_id = t.id

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        detail = await svc.get_trade(trade_id)

    assert detail.status == "open"
    assert detail.exit_price is None
    assert detail.exit_time is None
    assert detail.exit_reason is None
    assert detail.bot_name is None
    assert detail.bot_exchange is None
    # No strategy + no manual override -> trailing enrichment short-circuits.
    assert detail.trailing == {}


# ---------------------------------------------------------------------------
# get_risk_state_snapshot — #325 PR-1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_risk_state_snapshot_unknown_trade_raises(
    session_factory, user,
):
    """Unknown trade -> ``TradeNotFound`` before the manager is touched."""
    manager = MagicMock()
    manager.reconcile = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TradeNotFound):
            await svc.get_risk_state_snapshot(999999, manager)

    manager.reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_risk_state_snapshot_other_user_trade_raises(
    session_factory, user, other_user,
):
    """Another user's trade never reaches the manager."""
    async with session_factory() as s:
        t = TradeRecord(
            user_id=other_user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=70,
            reason="not yours",
            order_id="svc_other_risk",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        trade_id = t.id

    manager = MagicMock()
    manager.reconcile = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TradeNotFound):
            await svc.get_risk_state_snapshot(trade_id, manager)

    manager.reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_risk_state_snapshot_happy_path_confirms_legs(
    session_factory, user,
):
    """Confirmed TP+SL with no trailing -> overall_status='all_confirmed'."""
    async with session_factory() as s:
        t = TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=70,
            reason="open risk",
            order_id="svc_risk_open",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        trade_id = t.id

    applied_at = datetime.now(timezone.utc)
    snapshot = MagicMock()
    snapshot.tp = {
        "value": 97000.0,
        "status": RiskOpStatus.CONFIRMED.value,
        "order_id": "tp_1",
        "error": None,
        "latency_ms": 12,
    }
    snapshot.sl = {
        "value": 94000.0,
        "status": RiskOpStatus.CONFIRMED.value,
        "order_id": "sl_1",
        "error": None,
        "latency_ms": 8,
    }
    snapshot.trailing = None
    snapshot.last_synced_at = applied_at

    manager = MagicMock()
    manager.reconcile = AsyncMock(return_value=snapshot)

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.get_risk_state_snapshot(trade_id, manager)

    assert isinstance(result, RiskStateSnapshotResult)
    assert result.trade_id == trade_id
    assert isinstance(result.tp, RiskLegSnapshot)
    assert result.tp.status == RiskOpStatus.CONFIRMED.value
    assert result.tp.value == 97000.0
    assert result.tp.order_id == "tp_1"
    assert result.sl.status == RiskOpStatus.CONFIRMED.value
    assert result.trailing is None
    assert result.applied_at == applied_at
    assert result.overall_status == "all_confirmed"


@pytest.mark.asyncio
async def test_get_risk_state_snapshot_no_legs_returns_no_change(
    session_factory, user,
):
    """All legs None/cleared -> overall_status='no_change'."""
    async with session_factory() as s:
        t = TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=70,
            reason="open risk-none",
            order_id="svc_risk_none",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        trade_id = t.id

    snapshot = MagicMock()
    snapshot.tp = None
    snapshot.sl = None
    snapshot.trailing = None
    snapshot.last_synced_at = datetime.now(timezone.utc)

    manager = MagicMock()
    manager.reconcile = AsyncMock(return_value=snapshot)

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.get_risk_state_snapshot(trade_id, manager)

    assert result.tp is None
    assert result.sl is None
    assert result.trailing is None
    assert result.overall_status == "no_change"


@pytest.mark.asyncio
async def test_get_risk_state_snapshot_reconcile_value_error_maps_to_not_found(
    session_factory, user,
):
    """``manager.reconcile`` ValueError -> ``TradeNotFound`` with message."""
    async with session_factory() as s:
        t = TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            leverage=4,
            confidence=70,
            reason="open risk-vanish",
            order_id="svc_risk_vanish",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
        trade_id = t.id

    manager = MagicMock()
    manager.reconcile = AsyncMock(side_effect=ValueError("row vanished"))

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TradeNotFound) as exc_info:
            await svc.get_risk_state_snapshot(trade_id, manager)

    assert "row vanished" in str(exc_info.value)


# ---------------------------------------------------------------------------
# sync_exchange_positions — #325 PR-2
# ---------------------------------------------------------------------------


async def _seed_open_trade(
    session_factory, user_id: int, *, symbol: str = "BTCUSDT",
    side: str = "long", exchange: str = "bitget",
) -> int:
    """Insert a single ``open`` trade and return its id (test helper)."""
    t = TradeRecord(
        user_id=user_id,
        symbol=symbol,
        side=side,
        size=0.01,
        entry_price=95000.0,
        leverage=4,
        confidence=70,
        reason="svc-write-test",
        order_id=f"svc_{symbol}_{side}",
        status="open",
        entry_time=datetime.now(timezone.utc),
        exchange=exchange,
        demo_mode=True,
    )
    async with session_factory() as s:
        s.add(t)
        await s.commit()
        await s.refresh(t)
        return t.id


async def _seed_exchange_connection(
    session_factory, user_id: int, *, exchange_type: str = "bitget",
) -> None:
    """Insert a demo-mode ``ExchangeConnection`` for ``user_id``."""
    conn = ExchangeConnection(
        user_id=user_id,
        exchange_type=exchange_type,
        demo_api_key_encrypted="demo_key_enc",
        demo_api_secret_encrypted="demo_secret_enc",
        demo_passphrase_encrypted="demo_passphrase_enc",
    )
    async with session_factory() as s:
        s.add(conn)
        await s.commit()


@pytest.mark.asyncio
async def test_sync_exchange_positions_no_open_trades_returns_empty_result(
    session_factory, user,
):
    """No open trades → SyncResult(synced=0, closed_trades=[]) — no DB I/O, no exchange calls."""
    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.sync_exchange_positions(
            rsm_enabled=False,
            decrypt_value=lambda v: v,
            create_exchange_client=MagicMock(),  # must not be invoked
            get_risk_state_manager=MagicMock(),
            discord_notifier_cls=MagicMock(),
        )

    assert isinstance(result, SyncResult)
    assert result.synced == 0
    assert result.closed_trades == []


@pytest.mark.asyncio
async def test_sync_exchange_positions_closes_vanished_trade(
    session_factory, user,
):
    """Open trade no longer on exchange → closed with exit_price, pnl, reason."""
    trade_id = await _seed_open_trade(session_factory, user.id)
    await _seed_exchange_connection(session_factory, user.id)

    mock_client = AsyncMock()
    # Exchange returns no open positions => our trade is "closed remotely".
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_close_fill_price = AsyncMock(return_value=None)
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.1)
    mock_client.get_funding_fees = AsyncMock(return_value=0.0)
    mock_client.close = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.sync_exchange_positions(
            rsm_enabled=False,
            decrypt_value=lambda v: v,
            create_exchange_client=MagicMock(return_value=mock_client),
            get_risk_state_manager=MagicMock(),
            discord_notifier_cls=MagicMock(),
        )
        await s.commit()

    assert result.synced == 1
    assert len(result.closed_trades) == 1
    ct = result.closed_trades[0]
    assert ct.id == trade_id
    assert ct.symbol == "BTCUSDT"
    assert ct.side == "long"
    assert ct.exit_price == 96000.0
    # Long 0.01 BTC from 95000 → 96000 ≈ +10 (pre-fees).
    assert ct.pnl > 0


@pytest.mark.asyncio
async def test_sync_exchange_positions_swallows_exchange_errors(
    session_factory, user,
):
    """Exchange throws → no close, SyncResult stays empty (not re-raised)."""
    await _seed_open_trade(session_factory, user.id)
    await _seed_exchange_connection(session_factory, user.id)

    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(
        side_effect=Exception("exchange blew up"),
    )
    mock_client.close = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.sync_exchange_positions(
            rsm_enabled=False,
            decrypt_value=lambda v: v,
            create_exchange_client=MagicMock(return_value=mock_client),
            get_risk_state_manager=MagicMock(),
            discord_notifier_cls=MagicMock(),
        )

    assert result.synced == 0
    assert result.closed_trades == []


# ---------------------------------------------------------------------------
# update_tp_sl_via_manager — #325 PR-2
# ---------------------------------------------------------------------------


def _make_manager_with_confirmed_tp(trade_id: int, tp_value: float) -> MagicMock:
    """A fake RiskStateManager that returns a CONFIRMED RiskOpResult.

    Used by the manager-path happy-path test and the idempotency test.
    """
    mgr = MagicMock()
    mgr.apply_intent = AsyncMock(return_value=RiskOpResult(
        trade_id=trade_id,
        leg=RiskLeg.TP,
        status=RiskOpStatus.CONFIRMED,
        value=tp_value,
        order_id="tp_order_1",
        error=None,
        latency_ms=42,
    ))
    return mgr


@pytest.mark.asyncio
async def test_update_tp_sl_via_manager_tp_only_confirmed(session_factory, user):
    """Setting only TP → CONFIRMED outcome, overall_status='all_confirmed'."""
    trade_id = await _seed_open_trade(session_factory, user.id)

    idem_cache = MagicMock()
    idem_cache.get = AsyncMock(return_value=None)
    idem_cache.set = AsyncMock()
    manager = _make_manager_with_confirmed_tp(trade_id, 100000.0)

    intent = TpSlIntent(take_profit=100000.0)
    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.update_tp_sl_via_manager(
            trade_id,
            intent,
            idempotency_key=None,
            get_risk_state_manager=lambda: manager,
            get_idempotency_cache=lambda: idem_cache,
            market_data_fetcher_cls=MagicMock(),
        )

    assert isinstance(result, TpSlManagerResult)
    assert result.tp is not None
    assert result.tp.status == RiskOpStatus.CONFIRMED.value
    assert result.sl is None
    assert result.trailing is None
    assert result.overall_status == "all_confirmed"
    # Only the TP leg was applied — not SL, not trailing.
    manager.apply_intent.assert_awaited_once()
    args, _ = manager.apply_intent.await_args
    assert args[1] == RiskLeg.TP


@pytest.mark.asyncio
async def test_update_tp_sl_via_manager_idempotency_cache_hit_short_circuits(
    session_factory, user,
):
    """Idempotency-Key hit → return cached response; manager is NOT invoked."""
    trade_id = await _seed_open_trade(session_factory, user.id)

    cached_result = TpSlManagerResult(
        trade_id=trade_id,
        tp=None, sl=None, trailing=None,
        applied_at=datetime.now(timezone.utc),
        overall_status="no_change",
    )

    idem_cache = MagicMock()
    idem_cache.get = AsyncMock(return_value=cached_result)
    idem_cache.set = AsyncMock()
    manager = MagicMock()
    manager.apply_intent = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.update_tp_sl_via_manager(
            trade_id,
            TpSlIntent(take_profit=100000.0),
            idempotency_key="req-123",
            get_risk_state_manager=lambda: manager,
            get_idempotency_cache=lambda: idem_cache,
            market_data_fetcher_cls=MagicMock(),
        )

    assert result is cached_result
    idem_cache.get.assert_awaited_once_with(f"tp_sl:{trade_id}:req-123")
    manager.apply_intent.assert_not_awaited()
    idem_cache.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_tp_sl_via_manager_leg_exception_yields_rejected_outcome(
    session_factory, user,
):
    """Per-leg exception → REJECTED outcome with error, other legs proceed."""
    trade_id = await _seed_open_trade(session_factory, user.id)

    # TP crashes; SL is CONFIRMED — mustn't short-circuit on the TP failure.
    async def _apply(trade_id_arg, leg, value):
        if leg == RiskLeg.TP:
            raise RuntimeError("boom")
        return RiskOpResult(
            trade_id=trade_id_arg,
            leg=leg,
            status=RiskOpStatus.CONFIRMED,
            value=value,
            order_id="sl_order",
            error=None,
            latency_ms=5,
        )

    manager = MagicMock()
    manager.apply_intent = AsyncMock(side_effect=_apply)
    idem_cache = MagicMock()
    idem_cache.get = AsyncMock(return_value=None)
    idem_cache.set = AsyncMock()

    intent = TpSlIntent(take_profit=100000.0, stop_loss=90000.0)
    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.update_tp_sl_via_manager(
            trade_id,
            intent,
            idempotency_key=None,
            get_risk_state_manager=lambda: manager,
            get_idempotency_cache=lambda: idem_cache,
            market_data_fetcher_cls=MagicMock(),
        )

    assert result.tp is not None
    assert result.tp.status == RiskOpStatus.REJECTED.value
    assert result.tp.error == "boom"
    assert result.sl is not None
    assert result.sl.status == RiskOpStatus.CONFIRMED.value
    assert result.overall_status == "partial_success"


@pytest.mark.asyncio
async def test_update_tp_sl_via_manager_tp_conflict_raises_invalid(
    session_factory, user,
):
    """Mutex TP: remove_tp + take_profit set → InvalidTpSlIntent('tp_conflict')."""
    trade_id = await _seed_open_trade(session_factory, user.id)
    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(InvalidTpSlIntent) as exc_info:
            await svc.update_tp_sl_via_manager(
                trade_id,
                TpSlIntent(take_profit=100000.0, remove_tp=True),
                idempotency_key=None,
                get_risk_state_manager=MagicMock(),
                get_idempotency_cache=MagicMock(),
                market_data_fetcher_cls=MagicMock(),
            )
    assert str(exc_info.value) == "tp_conflict"


@pytest.mark.asyncio
async def test_update_tp_sl_via_manager_not_open_raises_not_open(
    session_factory, user,
):
    """Closed trade → TradeNotOpen carrying the trade id."""
    t = TradeRecord(
        user_id=user.id,
        symbol="BTCUSDT",
        side="long",
        size=0.01,
        entry_price=95000.0,
        exit_price=96000.0,
        leverage=4,
        confidence=70,
        reason="closed-test",
        order_id="svc_closed",
        status="closed",
        entry_time=datetime.now(timezone.utc) - timedelta(days=1),
        exit_time=datetime.now(timezone.utc),
        exchange="bitget",
        demo_mode=True,
    )
    async with session_factory() as s:
        s.add(t)
        await s.commit()
        await s.refresh(t)
        trade_id = t.id

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TradeNotOpen) as exc_info:
            await svc.update_tp_sl_via_manager(
                trade_id,
                TpSlIntent(take_profit=100000.0),
                idempotency_key=None,
                get_risk_state_manager=MagicMock(),
                get_idempotency_cache=MagicMock(),
                market_data_fetcher_cls=MagicMock(),
            )
    assert exc_info.value.trade_id == trade_id


@pytest.mark.asyncio
async def test_update_tp_sl_via_manager_unknown_id_raises_not_found(
    session_factory, user,
):
    """Unknown trade id → TradeNotFound (before any manager call)."""
    manager = MagicMock()
    manager.apply_intent = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TradeNotFound):
            await svc.update_tp_sl_via_manager(
                999999,
                TpSlIntent(take_profit=100000.0),
                idempotency_key=None,
                get_risk_state_manager=lambda: manager,
                get_idempotency_cache=MagicMock(),
                market_data_fetcher_cls=MagicMock(),
            )
    manager.apply_intent.assert_not_awaited()


# ---------------------------------------------------------------------------
# update_tp_sl_legacy — #325 PR-2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_tp_sl_legacy_happy_path_updates_exchange_and_db(
    session_factory, user,
):
    """Setting TP on open long → exchange called, DB row updated, legacy shape."""
    trade_id = await _seed_open_trade(session_factory, user.id)
    await _seed_exchange_connection(session_factory, user.id)

    mock_client = AsyncMock()
    mock_client.cancel_position_tpsl = AsyncMock()
    mock_client.set_position_tpsl = AsyncMock()
    mock_client.close = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        result = await svc.update_tp_sl_legacy(
            trade_id,
            TpSlIntent(take_profit=100000.0),
            decrypt_value=lambda v: v,
            create_exchange_client=MagicMock(return_value=mock_client),
            market_data_fetcher_cls=MagicMock(),
        )

    assert isinstance(result, TpSlLegacyResult)
    assert result.take_profit == 100000.0
    assert result.stop_loss is None
    assert result.trailing_stop_placed is False
    assert result.trailing_stop_software is False
    # Cancel-then-set ordering on the exchange client.
    mock_client.cancel_position_tpsl.assert_awaited_once()
    mock_client.set_position_tpsl.assert_awaited_once()
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_tp_sl_legacy_missing_connection_raises(
    session_factory, user,
):
    """No ExchangeConnection row → ExchangeConnectionMissing."""
    trade_id = await _seed_open_trade(session_factory, user.id)
    # no exchange connection seeded

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(ExchangeConnectionMissing):
            await svc.update_tp_sl_legacy(
                trade_id,
                TpSlIntent(take_profit=100000.0),
                decrypt_value=lambda v: v,
                create_exchange_client=MagicMock(),
                market_data_fetcher_cls=MagicMock(),
            )


@pytest.mark.asyncio
async def test_update_tp_sl_legacy_exchange_not_implemented_raises_not_supported(
    session_factory, user,
):
    """Client raises NotImplementedError → TpSlExchangeNotSupported(exchange)."""
    trade_id = await _seed_open_trade(session_factory, user.id)
    await _seed_exchange_connection(session_factory, user.id)

    mock_client = AsyncMock()
    mock_client.cancel_position_tpsl = AsyncMock(side_effect=NotImplementedError)
    mock_client.close = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TpSlExchangeNotSupported) as exc_info:
            await svc.update_tp_sl_legacy(
                trade_id,
                TpSlIntent(take_profit=100000.0),
                decrypt_value=lambda v: v,
                create_exchange_client=MagicMock(return_value=mock_client),
                market_data_fetcher_cls=MagicMock(),
            )
    assert exc_info.value.exchange == "bitget"


@pytest.mark.asyncio
async def test_update_tp_sl_legacy_exchange_error_raises_update_failed(
    session_factory, user,
):
    """Generic exchange exception → TpSlUpdateFailed carrying the raw msg."""
    trade_id = await _seed_open_trade(session_factory, user.id)
    await _seed_exchange_connection(session_factory, user.id)

    mock_client = AsyncMock()
    mock_client.cancel_position_tpsl = AsyncMock(
        side_effect=Exception("TP price less than mark"),
    )
    mock_client.close = AsyncMock()

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TpSlUpdateFailed) as exc_info:
            await svc.update_tp_sl_legacy(
                trade_id,
                TpSlIntent(take_profit=100000.0),
                decrypt_value=lambda v: v,
                create_exchange_client=MagicMock(return_value=mock_client),
                market_data_fetcher_cls=MagicMock(),
            )
    assert "less than" in exc_info.value.raw_error


@pytest.mark.asyncio
async def test_update_tp_sl_legacy_tp_below_entry_long_raises_invalid(
    session_factory, user,
):
    """Long trade + TP below entry → InvalidTpSlIntent('tp_below_entry_long')."""
    trade_id = await _seed_open_trade(session_factory, user.id)  # entry=95000 long

    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(InvalidTpSlIntent) as exc_info:
            await svc.update_tp_sl_legacy(
                trade_id,
                TpSlIntent(take_profit=60000.0),
                decrypt_value=lambda v: v,
                create_exchange_client=MagicMock(),
                market_data_fetcher_cls=MagicMock(),
            )
    assert str(exc_info.value) == "tp_below_entry_long"


@pytest.mark.asyncio
async def test_update_tp_sl_legacy_unknown_id_raises_not_found(
    session_factory, user,
):
    """Unknown trade id → TradeNotFound before any exchange call."""
    fake_factory = MagicMock()
    async with session_factory() as s:
        svc = TradesService(db=s, user=user)
        with pytest.raises(TradeNotFound):
            await svc.update_tp_sl_legacy(
                999999,
                TpSlIntent(take_profit=100000.0),
                decrypt_value=lambda v: v,
                create_exchange_client=fake_factory,
                market_data_fetcher_cls=MagicMock(),
            )
    fake_factory.assert_not_called()
