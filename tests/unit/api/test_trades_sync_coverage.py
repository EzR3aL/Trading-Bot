"""
Targeted tests for trades.py sync_trades to cover lines 180, 212, 214,
233-234, 246-247, 270-271, 288-327.

Covers:
- ExchangeConnection with no keys (continue on line 180)
- TAKE_PROFIT exit reason detection (line 212)
- STOP_LOSS exit reason detection (line 214)
- Fee fetching exception (lines 233-234)
- Funding fee exception (lines 246-247)
- Trade close exception (lines 270-271)
- Discord notification on sync close (lines 288-327)
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, ExchangeConnection, TradeRecord, User, UserConfig
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
            username="syncuser",
            email="sync@test.com",
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
async def open_trade_tp(session_factory, user):
    """Open trade whose exit price will be near take_profit."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            take_profit=97000.0,
            stop_loss=93000.0,
            leverage=4,
            confidence=80,
            reason="TP test",
            order_id="order_tp",
            status="open",
            entry_time=datetime.utcnow() - timedelta(hours=6),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def open_trade_sl(session_factory, user):
    """Open trade whose exit price will be near stop_loss."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            take_profit=3200.0,
            stop_loss=3600.0,
            leverage=4,
            confidence=80,
            reason="SL test",
            order_id="order_sl",
            status="open",
            entry_time=datetime.utcnow() - timedelta(hours=4),
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
async def exchange_conn_no_keys(session_factory, user):
    """ExchangeConnection with no keys at all (line 180: continue)."""
    async with session_factory() as session:
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
            # No demo or live keys
        )
        session.add(conn)
        await session.commit()
        await session.refresh(conn)
        return conn


@pytest_asyncio.fixture
async def user_config_with_discord(session_factory, user):
    """UserConfig with Discord webhook URL."""
    async with session_factory() as session:
        cfg = UserConfig(
            user_id=user.id,
            discord_webhook_url=encrypt_value("https://discord.com/api/webhooks/test/test"),
        )
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
        return cfg


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
# Test: ExchangeConnection with no keys (line 180 - continue)
# ---------------------------------------------------------------------------

async def test_sync_skips_connection_without_keys(
    client, auth_headers, open_trade_tp, exchange_conn_no_keys
):
    """Sync skips exchange connections that have no API keys."""
    resp = await client.post("/api/trades/sync", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0


# ---------------------------------------------------------------------------
# Test: TAKE_PROFIT exit reason (line 212)
# ---------------------------------------------------------------------------

async def test_sync_detects_take_profit_exit(
    client, auth_headers, open_trade_tp, exchange_conn
):
    """Sync marks exit_reason as TAKE_PROFIT when price is near TP."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    # Price very close to take_profit (97000), within 0.5% of entry
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96950.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.1)
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted"):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
    assert data["closed_trades"][0]["exit_reason"] == "TAKE_PROFIT"


# ---------------------------------------------------------------------------
# Test: STOP_LOSS exit reason (line 214)
# ---------------------------------------------------------------------------

async def test_sync_detects_stop_loss_exit(
    client, auth_headers, open_trade_sl, exchange_conn
):
    """Sync marks exit_reason as STOP_LOSS when price is near SL."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    # Price very close to stop_loss (3600), within 0.5% of entry
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=3598.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.3)
    mock_client.get_funding_fees = AsyncMock(return_value=0.05)
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted"):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
    assert data["closed_trades"][0]["exit_reason"] == "STOP_LOSS"


# ---------------------------------------------------------------------------
# Test: Fee fetching exception (lines 233-234)
# ---------------------------------------------------------------------------

async def test_sync_handles_fee_fetch_error(
    client, auth_headers, open_trade_tp, exchange_conn
):
    """Sync continues even when fee fetching raises an exception."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
    mock_client.get_trade_total_fees = AsyncMock(side_effect=Exception("Fee API error"))
    mock_client.get_funding_fees = AsyncMock(return_value=0.1)
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted"):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1


# ---------------------------------------------------------------------------
# Test: Funding fee exception (lines 246-247)
# ---------------------------------------------------------------------------

async def test_sync_handles_funding_fee_error(
    client, auth_headers, open_trade_tp, exchange_conn
):
    """Sync continues even when funding fee fetching raises an exception."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(side_effect=Exception("Funding API error"))
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted"):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1


# ---------------------------------------------------------------------------
# Test: Trade close exception (lines 270-271)
# ---------------------------------------------------------------------------

async def test_sync_handles_individual_trade_close_error(
    client, auth_headers, open_trade_tp, exchange_conn
):
    """Sync handles exception when closing individual trade."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    # get_ticker raises for this trade
    mock_client.get_ticker = AsyncMock(side_effect=Exception("Ticker unavailable"))
    mock_client.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted"):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    # Trade should NOT have been closed due to error
    assert data["synced"] == 0


# ---------------------------------------------------------------------------
# Test: Discord notification on sync (lines 288-327)
# ---------------------------------------------------------------------------

async def test_sync_sends_discord_notification(
    client, auth_headers, open_trade_tp, exchange_conn, user_config_with_discord
):
    """Sync sends Discord notification when trades are closed and webhook is configured."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.1)
    mock_client.close = AsyncMock()

    mock_notifier = AsyncMock()
    mock_notifier.send_trade_exit = AsyncMock()
    mock_notifier.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted-url"), \
         patch("src.notifications.discord_notifier.DiscordNotifier", return_value=mock_notifier):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
    # Discord notifier should have been called
    mock_notifier.send_trade_exit.assert_called_once()
    mock_notifier.close.assert_called_once()


async def test_sync_discord_notification_failure_does_not_crash(
    client, auth_headers, open_trade_tp, exchange_conn, user_config_with_discord
):
    """Sync handles Discord notification failure gracefully."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.1)
    mock_client.close = AsyncMock()

    mock_notifier = AsyncMock()
    mock_notifier.send_trade_exit = AsyncMock(side_effect=Exception("Discord down"))
    mock_notifier.close = AsyncMock()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=lambda x: "decrypted-url"), \
         patch("src.notifications.discord_notifier.DiscordNotifier", return_value=mock_notifier):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    # Trade should still be marked as synced despite Discord failure
    assert data["synced"] == 1


async def test_sync_discord_decrypt_error_skips_notification(
    client, auth_headers, open_trade_tp, exchange_conn, user_config_with_discord
):
    """Sync skips Discord notification when webhook URL decryption fails."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_ticker = AsyncMock(return_value=MagicMock(last_price=96000.0))
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.1)
    mock_client.close = AsyncMock()

    call_count = 0

    def decrypt_or_fail(val):
        nonlocal call_count
        call_count += 1
        # First 3 calls are for exchange keys, then webhook URL should fail
        if call_count <= 3:
            return "decrypted"
        raise ValueError("Decryption failed")

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", side_effect=decrypt_or_fail):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
