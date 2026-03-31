"""Tests for the TP/SL router cancel flow — place first, cancel old, handle both-removed."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, ExchangeConnection, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token
from src.api.routers.auth import limiter
from src.api.routers import trades
from src.models.session import get_db


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
async def setup_data(session_factory):
    """Create user, exchange connection, and open trade with existing TP/SL."""
    async with session_factory() as session:
        user = User(
            username="tester",
            email="test@test.com",
            password_hash=hash_password("testpass"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(user)
        await session.flush()

        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bingx",
            demo_api_key_encrypted="enc_key",
            demo_api_secret_encrypted="enc_secret",
        )
        session.add(conn)
        await session.flush()

        trade = TradeRecord(
            user_id=user.id,
            exchange="bingx",
            symbol="BTC-USDT",
            side="long",
            size=0.01,
            entry_price=68000.0,
            leverage=10,
            confidence=80,
            reason="Test trade",
            order_id="test_order_001",
            entry_time=datetime.now(timezone.utc),
            status="open",
            demo_mode=True,
            take_profit=70000.0,
            stop_loss=66000.0,
        )
        session.add(trade)
        await session.commit()

        token = create_access_token({"sub": str(user.id)})
        return {"user": user, "trade": trade, "token": token}


@pytest_asyncio.fixture
async def app(session_factory):
    """Create a minimal FastAPI app with just the trades router."""
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


def make_mock_client():
    """Create a mock exchange client that tracks call order."""
    client = AsyncMock()
    client.set_position_tpsl = AsyncMock(return_value="order123")
    client.cancel_position_tpsl = AsyncMock(return_value=True)
    client.close = AsyncMock()
    client.exchange_name = "bingx"
    return client


@pytest.mark.asyncio
async def test_update_tpsl_places_first_then_cancels(app, setup_data):
    """When setting new TP, should place new orders THEN cancel old ones."""
    data = setup_data
    call_order = []

    mock_client = make_mock_client()

    async def track_set(*args, **kwargs):
        call_order.append("set_position_tpsl")
        return "order123"

    async def track_cancel(*args, **kwargs):
        call_order.append("cancel_position_tpsl")
        return True

    mock_client.set_position_tpsl.side_effect = track_set
    mock_client.cancel_position_tpsl.side_effect = track_cancel

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                f"/api/trades/{data['trade'].id}/tp-sl",
                json={"take_profit": 71000.0},
                headers={"Authorization": f"Bearer {data['token']}"},
            )

    assert resp.status_code == 200
    # Core invariant: place BEFORE cancel
    assert call_order == ["set_position_tpsl", "cancel_position_tpsl"]


@pytest.mark.asyncio
async def test_remove_both_tpsl_calls_cancel_only(app, setup_data):
    """When removing both TP and SL, should call cancel_position_tpsl only (no set)."""
    data = setup_data
    mock_client = make_mock_client()

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                f"/api/trades/{data['trade'].id}/tp-sl",
                json={"remove_tp": True, "remove_sl": True},
                headers={"Authorization": f"Bearer {data['token']}"},
            )

    assert resp.status_code == 200
    mock_client.set_position_tpsl.assert_not_called()
    mock_client.cancel_position_tpsl.assert_called_once()


@pytest.mark.asyncio
async def test_remove_tp_keep_sl_places_then_cancels(app, setup_data):
    """When removing TP but keeping SL, should set SL on exchange then cancel old."""
    data = setup_data
    call_order = []
    mock_client = make_mock_client()

    async def track_set(*args, **kwargs):
        call_order.append("set_position_tpsl")
        return "order123"

    async def track_cancel(*args, **kwargs):
        call_order.append("cancel_position_tpsl")
        return True

    mock_client.set_position_tpsl.side_effect = track_set
    mock_client.cancel_position_tpsl.side_effect = track_cancel

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                f"/api/trades/{data['trade'].id}/tp-sl",
                json={"remove_tp": True},
                headers={"Authorization": f"Bearer {data['token']}"},
            )

    assert resp.status_code == 200
    # SL remains (66000.0 from trade), TP removed -> set with only SL, then cancel old
    assert call_order == ["set_position_tpsl", "cancel_position_tpsl"]
