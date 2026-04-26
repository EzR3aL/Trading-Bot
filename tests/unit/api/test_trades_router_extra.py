"""
Extra tests for the trades API router — sync_trades and get_trade endpoints.

Covers lines 86-329 and 346-352 (sync_trades with exchange interaction,
PnL calculations, Discord notifications, and get_trade single-trade view).
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, BotConfig, ExchangeConnection, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token
from src.utils.encryption import encrypt_value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
async def user(session_factory):
    async with session_factory() as session:
        u = User(
            username="tradeuser",
            email="trade@test.com",
            password_hash=hash_password("password123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def auth_headers(user):
    token_data = {"sub": str(user.id), "role": user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def bot_config(session_factory, user):
    async with session_factory() as session:
        bc = BotConfig(
            user_id=user.id,
            name="TestBot",
            exchange_type="bitget",
            strategy_type="edge_indicator",
        )
        session.add(bc)
        await session.commit()
        await session.refresh(bc)
        return bc


@pytest_asyncio.fixture
async def closed_trade(session_factory, user, bot_config):
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            bot_config_id=bot_config.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Test trade",
            order_id="order_001",
            status="closed",
            pnl=10.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            entry_time=datetime.now(timezone.utc) - timedelta(hours=24),
            exit_time=datetime.now(timezone.utc) - timedelta(hours=12),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def open_trade(session_factory, user, bot_config):
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            bot_config_id=bot_config.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=4,
            confidence=80,
            reason="ETH short",
            order_id="order_002",
            status="open",
            entry_time=datetime.now(timezone.utc) - timedelta(hours=6),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def exchange_conn(session_factory, user):
    async with session_factory() as session:
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
            demo_api_key_encrypted=encrypt_value("test-demo-key"),
            demo_api_secret_encrypted=encrypt_value("test-demo-secret"),
            demo_passphrase_encrypted=encrypt_value("test-demo-pass"),
        )
        session.add(conn)
        await session.commit()
        await session.refresh(conn)
        return conn


@pytest_asyncio.fixture
async def app(session_factory):
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import trades
    from src.models.session import get_db

    limiter.enabled = False

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app = FastAPI()
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    test_app.include_router(trades.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /api/trades/{trade_id}
# ---------------------------------------------------------------------------


async def test_get_single_trade(client, auth_headers, closed_trade):
    """Get a specific trade by ID."""
    resp = await client.get(f"/api/trades/{closed_trade.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == closed_trade.id
    assert data["symbol"] == "BTCUSDT"
    assert data["side"] == "long"
    assert data["pnl"] == 10.0
    assert data["bot_name"] == "TestBot"
    assert data["bot_exchange"] == "bitget"


async def test_get_trade_not_found(client, auth_headers):
    """Get non-existent trade returns 404."""
    resp = await client.get("/api/trades/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_get_trade_requires_auth(client, closed_trade):
    """Get trade without auth returns 401."""
    resp = await client.get(f"/api/trades/{closed_trade.id}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/trades/sync
# ---------------------------------------------------------------------------


async def test_sync_trades_no_open_trades(client, auth_headers, closed_trade):
    """Sync with no open trades returns empty."""
    resp = await client.post("/api/trades/sync", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0
    assert data["closed_trades"] == []


async def test_sync_trades_no_exchange_connection(client, auth_headers, open_trade):
    """Sync when no exchange connection exists skips trades."""
    resp = await client.post("/api/trades/sync", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0


async def test_sync_trades_closes_missing_position(
    client, auth_headers, open_trade, exchange_conn
):
    """Sync detects position no longer on exchange and closes it."""
    mock_client = AsyncMock()
    mock_client.get_close_fill_price = AsyncMock(return_value=None)
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_ticker = MagicMock()
    mock_ticker.last_price = 3400.0
    mock_client.get_ticker = AsyncMock(return_value=mock_ticker)
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.1)
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted"):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
    assert len(data["closed_trades"]) == 1
    ct = data["closed_trades"][0]
    assert ct["symbol"] == "ETHUSDT"
    assert ct["side"] == "short"


async def test_sync_trades_position_still_open(
    client, auth_headers, open_trade, exchange_conn
):
    """Sync keeps trade open if position still exists on exchange."""
    mock_pos = MagicMock()
    mock_pos.symbol = "ETHUSDT"
    mock_pos.side = "short"

    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[mock_pos])
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted"):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0


async def test_sync_trades_exchange_error(
    client, auth_headers, open_trade, exchange_conn
):
    """Sync handles exchange query error gracefully."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(side_effect=Exception("Network error"))
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted"):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0


async def test_sync_trades_requires_auth(client):
    """Sync without auth returns 401."""
    resp = await client.post("/api/trades/sync")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List trades with filters
# ---------------------------------------------------------------------------


async def test_list_trades_filter_by_symbol(client, auth_headers, closed_trade):
    """Filter trades by symbol partial match."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"symbol": "BTC"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


async def test_list_trades_filter_by_exchange(client, auth_headers, closed_trade):
    """Filter trades by exchange."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"exchange": "bitget"})
    assert resp.status_code == 200


async def test_list_trades_filter_by_bot_name(client, auth_headers, closed_trade):
    """Filter trades by bot name."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"bot_name": "TestBot"})
    assert resp.status_code == 200


async def test_list_trades_filter_by_date_range(client, auth_headers, closed_trade):
    """Filter trades by date range."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    resp = await client.get(
        "/api/trades",
        headers=auth_headers,
        params={"date_from": yesterday, "date_to": today},
    )
    assert resp.status_code == 200


async def test_list_trades_filter_by_demo_mode(client, auth_headers, closed_trade):
    """Filter trades by demo_mode."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"demo_mode": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


async def test_list_trades_pagination(client, auth_headers, closed_trade):
    """Pagination params work correctly."""
    resp = await client.get(
        "/api/trades",
        headers=auth_headers,
        params={"page": 1, "per_page": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 10


async def test_list_trades_response_has_all_fields(client, auth_headers, closed_trade):
    """Trade response includes all expected fields."""
    resp = await client.get("/api/trades", headers=auth_headers)
    data = resp.json()
    assert "trades" in data
    assert "total" in data
    if data["trades"]:
        t = data["trades"][0]
        expected = {"id", "symbol", "side", "size", "entry_price", "status", "pnl", "fees", "demo_mode"}
        assert expected.issubset(set(t.keys()))


# ---------------------------------------------------------------------------
# Trailing stop enrichment
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def edge_bot(session_factory, user):
    """Bot using edge_indicator strategy with trailing stop enabled."""
    import json as _json
    async with session_factory() as session:
        bc = BotConfig(
            user_id=user.id,
            name="EdgeBot",
            exchange_type="bitget",
            strategy_type="edge_indicator",
            strategy_params=_json.dumps({
                "trailing_stop_enabled": True,
                "trailing_breakeven_atr": 1.5,
                "trailing_trail_atr": 2.5,
                "atr_period": 14,
                "kline_interval": "1h",
            }),
        )
        session.add(bc)
        await session.commit()
        await session.refresh(bc)
        return bc


@pytest_asyncio.fixture
async def open_long_trailing(session_factory, user, edge_bot):
    """Open LONG trade with highest_price high enough for trailing stop to activate."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            bot_config_id=edge_bot.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=60000.0,
            leverage=3,
            confidence=75,
            reason="Edge long",
            order_id="edge_001",
            status="open",
            highest_price=62000.0,  # +$2000 above entry
            entry_time=datetime.now(timezone.utc) - timedelta(hours=4),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def open_short_trailing(session_factory, user, edge_bot):
    """Open SHORT trade with highest_price (lowest) enough for trailing stop."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            bot_config_id=edge_bot.id,
            symbol="BTCUSDT",
            side="short",
            size=0.01,
            entry_price=65000.0,
            leverage=3,
            confidence=75,
            reason="Edge short",
            order_id="edge_002",
            status="open",
            highest_price=63000.0,  # $2000 below entry (good for short)
            entry_time=datetime.now(timezone.utc) - timedelta(hours=4),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


def _mock_klines(atr_value=600.0, count=30):
    """Create fake klines that produce a predictable ATR."""
    klines = []
    base = 62000.0
    for i in range(count):
        o = base
        h = base + atr_value
        lo = base - atr_value * 0.1
        c = base + atr_value * 0.5
        klines.append([i * 3600000, str(o), str(h), str(lo), str(c), "100", (i + 1) * 3600000])
    return klines


def _make_mdf_mock(klines):
    """Create a MarketDataFetcher mock class that preserves calculate_atr."""
    from src.data.market_data import MarketDataFetcher as RealMDF
    mock_fetcher = MagicMock()
    mock_fetcher.get_binance_klines = AsyncMock(return_value=klines)
    mock_fetcher.close = AsyncMock()
    mock_cls = MagicMock(return_value=mock_fetcher)
    mock_cls.calculate_atr = RealMDF.calculate_atr
    return mock_cls


async def test_trailing_stop_long_active(client, auth_headers, open_long_trailing):
    """Open LONG trade with sufficient profit shows active trailing stop."""
    mock_cls = _make_mdf_mock(_mock_klines(600.0))

    # After #363 split, _compute_trailing_stop lives in _trades_helpers
    # which holds the top-level MarketDataFetcher binding.
    with (
        patch("src.api.routers.trades.MarketDataFetcher", mock_cls),
        patch("src.services._trades_helpers.MarketDataFetcher", mock_cls),
    ):
        resp = await client.get(
            f"/api/trades/{open_long_trailing.id}", headers=auth_headers
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_stop_active"] is True
    assert data["trailing_stop_price"] is not None
    assert data["trailing_stop_price"] >= 60000.0  # at least entry
    assert data["trailing_stop_distance"] is not None
    assert data["trailing_stop_distance_pct"] is not None
    assert data["can_close_at_loss"] is False


async def test_trailing_stop_short_active(client, auth_headers, open_short_trailing):
    """Open SHORT trade with sufficient profit shows active trailing stop."""
    mock_cls = _make_mdf_mock(_mock_klines(600.0))

    # After #363 split, _compute_trailing_stop lives in _trades_helpers
    # which holds the top-level MarketDataFetcher binding.
    with (
        patch("src.api.routers.trades.MarketDataFetcher", mock_cls),
        patch("src.services._trades_helpers.MarketDataFetcher", mock_cls),
    ):
        resp = await client.get(
            f"/api/trades/{open_short_trailing.id}", headers=auth_headers
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_stop_active"] is True
    assert data["trailing_stop_price"] is not None
    assert data["trailing_stop_price"] <= 65000.0  # at most entry
    assert data["can_close_at_loss"] is False


async def test_trailing_stop_not_active_when_not_profitable(
    client, auth_headers, session_factory, user, edge_bot
):
    """Trade that hasn't moved enough shows trailing_stop_active=False."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            bot_config_id=edge_bot.id,
            symbol="ETHUSDT",
            side="long",
            size=0.1,
            entry_price=3500.0,
            leverage=3,
            confidence=70,
            reason="Edge long ETH",
            order_id="edge_003",
            status="open",
            highest_price=3510.0,  # barely moved — not enough for breakeven
            entry_time=datetime.now(timezone.utc) - timedelta(hours=1),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        trade_id = t.id

    mock_cls = _make_mdf_mock(_mock_klines(600.0))

    # After #363 split, _compute_trailing_stop lives in _trades_helpers
    # which holds the top-level MarketDataFetcher binding.
    with (
        patch("src.api.routers.trades.MarketDataFetcher", mock_cls),
        patch("src.services._trades_helpers.MarketDataFetcher", mock_cls),
    ):
        resp = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_stop_active"] is False
    assert data["can_close_at_loss"] is True


async def test_trailing_stop_null_for_closed_trade(client, auth_headers, closed_trade):
    """Closed trades have null trailing stop fields (no computation)."""
    resp = await client.get(f"/api/trades/{closed_trade.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_stop_active"] is None
    assert data["trailing_stop_price"] is None
    assert data["can_close_at_loss"] is None


async def test_trailing_stop_null_for_non_edge_strategy(client, auth_headers, session_factory, user):
    """Trades without a trailing-capable strategy have null trailing stop fields.

    Covers the case where the LEFT JOIN on BotConfig yields NULL for
    strategy_type (trade has no bot_config or the bot was deleted). The
    _compute_trailing_stop function should short-circuit and return {},
    leaving the response fields as None.
    """
    async with session_factory() as session:
        orphan = TradeRecord(
            user_id=user.id,
            bot_config_id=None,  # no bot → strategy_type is None after outer join
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=4,
            confidence=80,
            reason="Orphan trade",
            order_id="order_orphan",
            status="open",
            entry_time=datetime.now(timezone.utc) - timedelta(hours=6),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(orphan)
        await session.commit()
        await session.refresh(orphan)
        orphan_id = orphan.id

    resp = await client.get(f"/api/trades/{orphan_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_stop_active"] is None


async def test_trailing_stop_in_list_trades(client, auth_headers, open_long_trailing):
    """list_trades endpoint also enriches open trades with trailing stop info."""
    mock_cls = _make_mdf_mock(_mock_klines(600.0))

    # After #363 split, list_trades lives in _trades_list_mixin and does a
    # function-local ``from src.data.market_data import MarketDataFetcher``
    # for its kline pre-fetch — patch the source module to intercept it.
    # The trailing-stop enrichment then runs through _compute_trailing_stop
    # in _trades_helpers, which uses its own top-level binding.
    with (
        patch("src.api.routers.trades.MarketDataFetcher", mock_cls),
        patch("src.data.market_data.MarketDataFetcher", mock_cls),
        patch("src.services._trades_helpers.MarketDataFetcher", mock_cls),
    ):
        resp = await client.get(
            "/api/trades", headers=auth_headers, params={"status": "open"}
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    open_t = data["trades"][0]
    assert open_t["trailing_stop_active"] is True
    assert open_t["can_close_at_loss"] is False


async def test_trailing_stop_kline_fetch_failure(
    client, auth_headers, open_long_trailing
):
    """When kline fetch fails, trailing_stop_active defaults to False."""
    mock_fetcher = MagicMock()
    mock_fetcher.get_binance_klines = AsyncMock(side_effect=Exception("Network error"))
    mock_fetcher.close = AsyncMock()
    mock_cls = MagicMock(return_value=mock_fetcher)

    # After #363 split, _compute_trailing_stop lives in _trades_helpers
    # which holds the top-level MarketDataFetcher binding.
    with (
        patch("src.api.routers.trades.MarketDataFetcher", mock_cls),
        patch("src.services._trades_helpers.MarketDataFetcher", mock_cls),
    ):
        resp = await client.get(
            f"/api/trades/{open_long_trailing.id}", headers=auth_headers
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_stop_active"] is False


async def test_trailing_stop_no_highest_price(
    client, auth_headers, session_factory, user, edge_bot
):
    """Trade without highest_price returns trailing_stop_active=False, can_close_at_loss=True."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            bot_config_id=edge_bot.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=60000.0,
            leverage=3,
            confidence=75,
            reason="Edge long no HP",
            order_id="edge_004",
            status="open",
            highest_price=None,
            entry_time=datetime.now(timezone.utc) - timedelta(minutes=5),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        trade_id = t.id

    resp = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_stop_active"] is False
    assert data["can_close_at_loss"] is True
