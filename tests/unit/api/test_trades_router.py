"""
Unit tests for the trades API router.

Covers list_trades (with all filters), get_trade, sync_trades,
pagination, error paths, and authentication requirements.
Uses httpx.AsyncClient with ASGITransport against a real FastAPI app
backed by an in-memory SQLite database.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, BotConfig, ExchangeConnection, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token


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
            username="trader",
            email="trader@test.com",
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
async def other_user(session_factory):
    async with session_factory() as session:
        u = User(
            username="other_user",
            email="other@test.com",
            password_hash=hash_password("password456"),
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
            description="Test bot",
            strategy_type="test_strategy",
            exchange_type="bitget",
            mode="demo",
            trading_pairs='["BTCUSDT"]',
            leverage=4,
            is_enabled=False,
        )
        session.add(bc)
        await session.commit()
        await session.refresh(bc)
        return bc


@pytest_asyncio.fixture
async def trades(session_factory, user, bot_config):
    """Insert diverse trades for thorough filter testing."""
    now = datetime.now(timezone.utc)
    items = [
        TradeRecord(
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
            reason="BTC long",
            order_id="order_001",
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
            bot_config_id=bot_config.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            exit_price=3400.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=4,
            confidence=80,
            reason="ETH short",
            order_id="order_002",
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
            take_profit=96000.0,
            stop_loss=93000.0,
            leverage=4,
            confidence=60,
            reason="BTC long losing",
            order_id="order_003",
            status="closed",
            pnl=-20.0,
            pnl_percent=-1.06,
            fees=0.4,
            funding_paid=0.08,
            entry_time=now - timedelta(days=2),
            exit_time=now - timedelta(days=1),
            exit_reason="STOP_LOSS",
            exchange="bitget",
            demo_mode=False,
        ),
        TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95500.0,
            take_profit=97000.0,
            stop_loss=94500.0,
            leverage=4,
            confidence=70,
            reason="BTC long open",
            order_id="order_004",
            status="open",
            entry_time=now - timedelta(hours=2),
            exchange="bitget",
            demo_mode=True,
        ),
    ]
    async with session_factory() as session:
        session.add_all(items)
        await session.commit()
        for t in items:
            await session.refresh(t)
    return items


@pytest_asyncio.fixture
async def other_user_trade(session_factory, other_user):
    """Trade belonging to a different user (should never be visible)."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        t = TradeRecord(
            user_id=other_user.id,
            symbol="XRPUSDT",
            side="long",
            size=100,
            entry_price=0.5,
            take_profit=0.7,
            stop_loss=0.4,
            leverage=2,
            confidence=50,
            reason="XRP long",
            order_id="other_order_001",
            status="open",
            entry_time=now,
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


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
# list_trades: basic
# ---------------------------------------------------------------------------


async def test_list_trades_returns_all(client, auth_headers, trades):
    """GET /api/trades returns all trades for the authenticated user."""
    resp = await client.get("/api/trades", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert len(data["trades"]) == 4
    assert data["page"] == 1
    assert data["per_page"] == 50


async def test_list_trades_empty_when_no_trades(client, auth_headers, user):
    """GET /api/trades with no trade records returns empty list."""
    resp = await client.get("/api/trades", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["trades"] == []


async def test_list_trades_requires_auth(client, trades):
    """GET /api/trades without auth returns 401."""
    resp = await client.get("/api/trades")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# list_trades: pagination
# ---------------------------------------------------------------------------


async def test_list_trades_pagination_page_1(client, auth_headers, trades):
    """Pagination: page 1 with per_page=2."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"per_page": 2, "page": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["trades"]) == 2
    assert data["total"] == 4
    assert data["page"] == 1
    assert data["per_page"] == 2


async def test_list_trades_pagination_page_2(client, auth_headers, trades):
    """Pagination: page 2 with per_page=2."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"per_page": 2, "page": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["trades"]) == 2
    assert data["total"] == 4
    assert data["page"] == 2


async def test_list_trades_pagination_page_3_empty(client, auth_headers, trades):
    """Pagination: page 3 with per_page=2 returns empty (only 4 trades)."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"per_page": 2, "page": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["trades"]) == 0
    assert data["total"] == 4


async def test_list_trades_per_page_default(client, auth_headers, trades):
    """Default per_page is 50."""
    resp = await client.get("/api/trades", headers=auth_headers)
    data = resp.json()
    assert data["per_page"] == 50


# ---------------------------------------------------------------------------
# list_trades: filter by status
# ---------------------------------------------------------------------------


async def test_list_trades_filter_status_open(client, auth_headers, trades):
    """Filter status=open returns only open trades."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"status": "open"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert all(t["status"] == "open" for t in data["trades"])


async def test_list_trades_filter_status_closed(client, auth_headers, trades):
    """Filter status=closed returns only closed trades."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"status": "closed"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert all(t["status"] == "closed" for t in data["trades"])


# ---------------------------------------------------------------------------
# list_trades: filter by symbol
# ---------------------------------------------------------------------------


async def test_list_trades_filter_symbol_eth(client, auth_headers, trades):
    """Filter symbol=ETHUSDT returns only ETH trades."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"symbol": "ETHUSDT"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["trades"][0]["symbol"] == "ETHUSDT"


async def test_list_trades_filter_symbol_btc(client, auth_headers, trades):
    """Filter symbol=BTCUSDT returns only BTC trades."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"symbol": "BTCUSDT"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3


async def test_list_trades_filter_symbol_nonexistent(client, auth_headers, trades):
    """Filter by a symbol that does not exist returns empty."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"symbol": "NONEXIST"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["trades"] == []


# ---------------------------------------------------------------------------
# list_trades: filter by demo_mode
# ---------------------------------------------------------------------------


async def test_list_trades_filter_demo_true(client, auth_headers, trades):
    """Filter demo_mode=true returns only demo trades."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"demo_mode": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert all(t["demo_mode"] is True for t in data["trades"])


async def test_list_trades_filter_demo_false(client, auth_headers, trades):
    """Filter demo_mode=false returns only live trades."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"demo_mode": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert all(t["demo_mode"] is False for t in data["trades"])


# ---------------------------------------------------------------------------
# list_trades: filter by exchange (via bot_config)
# ---------------------------------------------------------------------------


async def test_list_trades_filter_by_exchange(client, auth_headers, trades, bot_config):
    """Filter by exchange returns trades linked to that exchange's bot config."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"exchange": "bitget"})
    assert resp.status_code == 200
    data = resp.json()
    # Only the 2 trades that have bot_config_id set (exchange_type=bitget)
    assert data["total"] == 2


async def test_list_trades_filter_exchange_nonexistent(client, auth_headers, trades):
    """Filter by a non-existent exchange returns no results."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"exchange": "kraken"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# list_trades: filter by bot_name
# ---------------------------------------------------------------------------


async def test_list_trades_filter_by_bot_name(client, auth_headers, trades, bot_config):
    """Filter by bot_name returns only trades from that bot."""
    resp = await client.get("/api/trades", headers=auth_headers, params={"bot_name": "TestBot"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for t in data["trades"]:
        assert t["bot_name"] == "TestBot"


# ---------------------------------------------------------------------------
# list_trades: combined filters
# ---------------------------------------------------------------------------


async def test_list_trades_combined_status_and_symbol(client, auth_headers, trades):
    """Combined status + symbol filter."""
    resp = await client.get(
        "/api/trades",
        headers=auth_headers,
        params={"status": "closed", "symbol": "BTCUSDT"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for t in data["trades"]:
        assert t["status"] == "closed"
        assert t["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# list_trades: date filters
# ---------------------------------------------------------------------------


async def test_list_trades_filter_date_from(client, auth_headers, trades):
    """Filter by date_from returns only trades after that date."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    resp = await client.get("/api/trades", headers=auth_headers, params={"date_from": yesterday})
    assert resp.status_code == 200
    data = resp.json()
    # Only the open trade entered 2 hours ago should be after yesterday start
    assert data["total"] >= 1


async def test_list_trades_filter_date_to(client, auth_headers, trades):
    """Filter by date_to returns only trades before that date."""
    four_days_ago = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%d")
    resp = await client.get("/api/trades", headers=auth_headers, params={"date_to": four_days_ago})
    assert resp.status_code == 200
    data = resp.json()
    # Only the first trade has entry_time 5 days ago
    assert data["total"] >= 1


# ---------------------------------------------------------------------------
# list_trades: ordering
# ---------------------------------------------------------------------------


async def test_list_trades_ordered_by_entry_time_desc(client, auth_headers, trades):
    """Trades are returned in descending entry_time order."""
    resp = await client.get("/api/trades", headers=auth_headers)
    data = resp.json()
    times = [t["entry_time"] for t in data["trades"]]
    assert times == sorted(times, reverse=True)


# ---------------------------------------------------------------------------
# list_trades: user isolation
# ---------------------------------------------------------------------------


async def test_list_trades_user_isolation(client, auth_headers, trades, other_user_trade):
    """User cannot see trades belonging to another user."""
    resp = await client.get("/api/trades", headers=auth_headers)
    data = resp.json()
    trade_ids = [t["id"] for t in data["trades"]]
    assert other_user_trade.id not in trade_ids
    assert data["total"] == 4


# ---------------------------------------------------------------------------
# get_trade: success
# ---------------------------------------------------------------------------


async def test_get_trade_by_id(client, auth_headers, trades):
    """GET /api/trades/{id} returns the correct trade."""
    trade_id = trades[0].id
    resp = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == trade_id
    assert data["symbol"] == "BTCUSDT"
    assert data["side"] == "long"
    assert data["pnl"] == 10.0


async def test_get_trade_includes_bot_name(client, auth_headers, trades, bot_config):
    """GET /api/trades/{id} includes bot_name and bot_exchange when linked."""
    trade_id = trades[0].id
    resp = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["bot_name"] == "TestBot"
    assert data["bot_exchange"] == "bitget"


# ---------------------------------------------------------------------------
# get_trade: errors
# ---------------------------------------------------------------------------


async def test_get_trade_not_found(client, auth_headers, trades):
    """GET /api/trades/99999 returns 404."""
    resp = await client.get("/api/trades/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_get_trade_requires_auth(client, trades):
    """GET /api/trades/{id} without auth returns 401."""
    resp = await client.get(f"/api/trades/{trades[0].id}")
    assert resp.status_code == 401


async def test_get_trade_other_user_not_visible(client, auth_headers, other_user_trade):
    """Cannot access another user's trade via GET /api/trades/{id}."""
    resp = await client.get(f"/api/trades/{other_user_trade.id}", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# get_trade: response fields
# ---------------------------------------------------------------------------


async def test_get_trade_all_fields_present(client, auth_headers, trades):
    """TradeResponse includes all expected fields."""
    trade_id = trades[0].id
    resp = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)
    data = resp.json()
    expected_fields = {
        "id", "symbol", "side", "size", "entry_price", "exit_price",
        "take_profit", "stop_loss", "leverage", "confidence", "reason",
        "status", "pnl", "pnl_percent", "fees", "funding_paid",
        "entry_time", "exit_time", "exit_reason", "exchange", "demo_mode",
        "bot_name", "bot_exchange",
    }
    assert expected_fields.issubset(set(data.keys()))


async def test_get_trade_open_trade_has_null_exit_fields(client, auth_headers, trades):
    """Open trade has null exit_price, exit_time, exit_reason."""
    open_trade = next(t for t in trades if t.status == "open")
    resp = await client.get(f"/api/trades/{open_trade.id}", headers=auth_headers)
    data = resp.json()
    assert data["exit_price"] is None
    assert data["exit_time"] is None
    assert data["exit_reason"] is None


# ---------------------------------------------------------------------------
# sync_trades: no open trades
# ---------------------------------------------------------------------------


async def test_sync_trades_no_open_trades(client, auth_headers, user):
    """POST /api/trades/sync with no open trades returns synced=0."""
    resp = await client.post("/api/trades/sync", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0
    assert data["closed_trades"] == []


async def test_sync_trades_requires_auth(client):
    """POST /api/trades/sync without auth returns 401."""
    resp = await client.post("/api/trades/sync")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# sync_trades: with open trades but no exchange connection
# ---------------------------------------------------------------------------


async def test_sync_trades_skips_when_no_exchange_connection(client, auth_headers, trades):
    """Sync with open trades but no exchange connection returns synced=0."""
    resp = await client.post("/api/trades/sync", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    # No exchange connection found, so no trades can be synced
    assert data["synced"] == 0
    assert data["closed_trades"] == []


# ---------------------------------------------------------------------------
# sync_trades: with exchange connection (mocked exchange client)
# ---------------------------------------------------------------------------


async def test_sync_trades_closes_position_not_on_exchange(
    client, auth_headers, trades, session_factory, user
):
    """Sync closes trades whose positions no longer exist on the exchange."""
    # Insert an exchange connection with demo keys
    async with session_factory() as session:
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
            demo_api_key_encrypted="encrypted_key",
            demo_api_secret_encrypted="encrypted_secret",
            demo_passphrase_encrypted="encrypted_pass",
        )
        session.add(conn)
        await session.commit()

    # Mock exchange client that returns no open positions
    mock_client = AsyncMock()
    mock_client.get_close_fill_price = AsyncMock(return_value=None)
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.1)
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.decrypt_value", return_value="decrypted"), \
         patch("src.api.routers.trades.create_exchange_client", return_value=mock_client):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    # The open trade (order_004) should have been closed
    assert data["synced"] == 1
    assert len(data["closed_trades"]) == 1
    assert data["closed_trades"][0]["symbol"] == "BTCUSDT"


async def test_sync_trades_does_not_close_if_still_on_exchange(
    client, auth_headers, trades, session_factory, user
):
    """Sync keeps trades open if they still exist on the exchange."""
    async with session_factory() as session:
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
            demo_api_key_encrypted="encrypted_key",
            demo_api_secret_encrypted="encrypted_secret",
        )
        session.add(conn)
        await session.commit()

    # Mock exchange returns a position matching the open trade
    open_trade = next(t for t in trades if t.status == "open")
    mock_position = MagicMock(symbol=open_trade.symbol, side=open_trade.side)
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[mock_position])
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.decrypt_value", return_value="decrypted"), \
         patch("src.api.routers.trades.create_exchange_client", return_value=mock_client):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0
    assert data["closed_trades"] == []


async def test_sync_trades_uses_live_keys_when_no_demo_keys(
    client, auth_headers, trades, session_factory, user
):
    """Sync falls back to live API keys when no demo keys are present."""
    async with session_factory() as session:
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
            api_key_encrypted="live_key",
            api_secret_encrypted="live_secret",
            passphrase_encrypted="live_pass",
        )
        session.add(conn)
        await session.commit()

    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.1)
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.decrypt_value", return_value="decrypted") as _mock_decrypt, \
         patch("src.api.routers.trades.create_exchange_client", return_value=mock_client) as mock_create:
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    # Verify it was called with demo_mode=False since no demo keys
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args
    assert call_kwargs.kwargs.get("demo_mode") is False or call_kwargs[1].get("demo_mode") is False


async def test_sync_trades_handles_exchange_error_gracefully(
    client, auth_headers, trades, session_factory, user
):
    """Sync handles exchange API errors without crashing."""
    async with session_factory() as session:
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
            demo_api_key_encrypted="encrypted_key",
            demo_api_secret_encrypted="encrypted_secret",
        )
        session.add(conn)
        await session.commit()

    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(side_effect=Exception("API timeout"))
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.decrypt_value", return_value="decrypted"), \
         patch("src.api.routers.trades.create_exchange_client", return_value=mock_client):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0
