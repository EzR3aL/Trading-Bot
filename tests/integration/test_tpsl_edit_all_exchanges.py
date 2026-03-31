"""
E2E tests for TP/SL editing across all 5 exchanges.

Verifies the "cancel first, set after" strategy works correctly for:
- Setting new TP/SL values
- Changing existing TP/SL
- Removing individual TP or SL
- Removing both TP and SL simultaneously

Each exchange has a different TP/SL architecture (order-based vs position-level)
but the router treats them uniformly — the exchange-specific cancel handles differences.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

# Env vars must be set before any src imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, ExchangeConnection, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token


ALL_EXCHANGES = ["bitget", "bingx", "weex", "hyperliquid", "bitunix"]


# ─── Fixtures ────────────────────────────────────────────────────────


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


# ─── Helpers ─────────────────────────────────────────────────────────


async def create_test_data(session_factory, exchange: str):
    """Create user + exchange connection + open trade with TP/SL for a given exchange."""
    async with session_factory() as session:
        user = User(
            username=f"tester_{exchange}",
            email=f"test_{exchange}@test.com",
            password_hash=hash_password("testpass"),
            is_active=True,
        )
        session.add(user)
        await session.flush()

        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type=exchange,
            demo_api_key_encrypted="enc_key",
            demo_api_secret_encrypted="enc_secret",
        )
        session.add(conn)
        await session.flush()

        trade = TradeRecord(
            user_id=user.id,
            exchange=exchange,
            symbol="BTC-USDT",
            side="long",
            size=0.01,
            entry_price=68000.0,
            leverage=10,
            confidence=85,
            reason="Test signal",
            order_id="test_order_001",
            status="open",
            demo_mode=True,
            take_profit=70000.0,
            stop_loss=66000.0,
            entry_time=datetime.now(timezone.utc),
        )
        session.add(trade)
        await session.commit()

        token = create_access_token({"sub": str(user.id)})
        return {"user": user, "trade": trade, "token": token}


def make_mock_client():
    """Create a tracked mock exchange client with call ordering."""
    call_log = []

    client = AsyncMock()

    async def track_set(*args, **kwargs):
        call_log.append(("set_position_tpsl", kwargs))
        return "order123"

    async def track_cancel(*args, **kwargs):
        call_log.append(("cancel_position_tpsl", kwargs))
        return True

    client.set_position_tpsl = AsyncMock(side_effect=track_set)
    client.cancel_position_tpsl = AsyncMock(side_effect=track_cancel)
    client.close = AsyncMock()
    client.exchange_name = "test"

    return client, call_log


def _setup_app_overrides(app, session_factory):
    """Override the DB dependency so the app uses our in-memory test database."""
    from src.models.session import get_db

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db


async def _send_tpsl_request(app, trade_id, token, payload):
    """Send PUT /api/trades/{trade_id}/tp-sl and return the response."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        return await ac.put(
            f"/api/trades/{trade_id}/tp-sl",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )


# ─── Scenario 1: Set new TP (SL unchanged) ──────────────────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_set_new_tp_places_then_cancels(exchange, engine, session_factory):
    """Setting a new TP should: place(tp=71000, sl=66000) -> cancel()."""
    data = await create_test_data(session_factory, exchange)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"take_profit": 71000.0},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        # Verify TP value was sent correctly
        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] == 71000.0, f"{exchange}: TP should be 71000"
        assert set_kwargs["stop_loss"] == 66000.0, f"{exchange}: SL should stay 66000"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 2: Change SL (TP unchanged) ───────────────────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_change_sl_places_then_cancels(exchange, engine, session_factory):
    """Changing SL should: place(tp=70000, sl=65000) -> cancel()."""
    data = await create_test_data(session_factory, exchange)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"stop_loss": 65000.0},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] == 70000.0, f"{exchange}: TP should stay 70000"
        assert set_kwargs["stop_loss"] == 65000.0, f"{exchange}: SL should be 65000"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 3: Remove TP (keep SL) ────────────────────────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_remove_tp_keep_sl(exchange, engine, session_factory):
    """Removing TP should: place(tp=None, sl=66000) -> cancel()."""
    data = await create_test_data(session_factory, exchange)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"remove_tp": True},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] is None, f"{exchange}: TP should be None (removed)"
        assert set_kwargs["stop_loss"] == 66000.0, f"{exchange}: SL should stay 66000"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 4: Remove BOTH TP and SL ──────────────────────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_remove_both_tpsl(exchange, engine, session_factory):
    """Removing both should: only cancel() (no set call)."""
    data = await create_test_data(session_factory, exchange)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"remove_tp": True, "remove_sl": True},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 1, f"{exchange}: expected only cancel call, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: should only cancel"

        # Verify DB was updated (TP and SL should be None)
        from sqlalchemy import select
        async with session_factory() as session:
            result = await session.execute(
                select(TradeRecord).where(TradeRecord.id == data["trade"].id)
            )
            trade = result.scalar_one()
            assert trade.take_profit is None, f"{exchange}: DB TP should be None"
            assert trade.stop_loss is None, f"{exchange}: DB SL should be None"
    finally:
        app.dependency_overrides.clear()


# ─── Custom Helper: Trade with configurable TP/SL ──────────────────


async def create_test_data_custom(session_factory, exchange: str, take_profit=None, stop_loss=None):
    """Create user + exchange connection + open trade with configurable TP/SL."""
    async with session_factory() as session:
        user = User(
            username=f"tester_{exchange}",
            email=f"test_{exchange}@test.com",
            password_hash=hash_password("testpass"),
            is_active=True,
        )
        session.add(user)
        await session.flush()

        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type=exchange,
            demo_api_key_encrypted="enc_key",
            demo_api_secret_encrypted="enc_secret",
        )
        session.add(conn)
        await session.flush()

        trade = TradeRecord(
            user_id=user.id,
            exchange=exchange,
            symbol="BTC-USDT",
            side="long",
            size=0.01,
            entry_price=68000.0,
            leverage=10,
            confidence=85,
            reason="Test signal",
            order_id="test_order_001",
            status="open",
            demo_mode=True,
            take_profit=take_profit,
            stop_loss=stop_loss,
            entry_time=datetime.now(timezone.utc),
        )
        session.add(trade)
        await session.commit()

        token = create_access_token({"sub": str(user.id)})
        return {"user": user, "trade": trade, "token": token}


# ─── Scenario 5: Remove SL, keep TP (trade has both) ──────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_remove_sl_keep_tp(exchange, engine, session_factory):
    """Removing SL should: place(tp=70000, sl=None) -> cancel()."""
    data = await create_test_data(session_factory, exchange)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"remove_sl": True},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] == 70000.0, f"{exchange}: TP should stay 70000"
        assert set_kwargs["stop_loss"] is None, f"{exchange}: SL should be None (removed)"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 6: Change both TP and SL simultaneously ─────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_change_both_tp_and_sl(exchange, engine, session_factory):
    """Changing both should: place(tp=72000, sl=64000) -> cancel()."""
    data = await create_test_data(session_factory, exchange)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"take_profit": 72000.0, "stop_loss": 64000.0},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] == 72000.0, f"{exchange}: TP should be 72000"
        assert set_kwargs["stop_loss"] == 64000.0, f"{exchange}: SL should be 64000"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 7: Set only TP when no TP/SL exists ─────────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_set_tp_only_from_none(exchange, engine, session_factory):
    """Setting TP on empty trade should: place(tp=70000, sl=None) -> cancel()."""
    data = await create_test_data_custom(session_factory, exchange, take_profit=None, stop_loss=None)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"take_profit": 70000.0},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] == 70000.0, f"{exchange}: TP should be 70000"
        assert set_kwargs["stop_loss"] is None, f"{exchange}: SL should stay None"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 8: Set only SL when no TP/SL exists ─────────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_set_sl_only_from_none(exchange, engine, session_factory):
    """Setting SL on empty trade should: place(tp=None, sl=66000) -> cancel()."""
    data = await create_test_data_custom(session_factory, exchange, take_profit=None, stop_loss=None)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"stop_loss": 66000.0},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] is None, f"{exchange}: TP should stay None"
        assert set_kwargs["stop_loss"] == 66000.0, f"{exchange}: SL should be 66000"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 9: Set both TP and SL when none existed ─────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_set_both_from_none(exchange, engine, session_factory):
    """Setting both on empty trade should: place(tp=70000, sl=66000) -> cancel()."""
    data = await create_test_data_custom(session_factory, exchange, take_profit=None, stop_loss=None)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"take_profit": 70000.0, "stop_loss": 66000.0},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] == 70000.0, f"{exchange}: TP should be 70000"
        assert set_kwargs["stop_loss"] == 66000.0, f"{exchange}: SL should be 66000"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 10: Remove TP when only TP exists (no SL) ───────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_remove_tp_when_only_tp(exchange, engine, session_factory):
    """Removing lone TP should: cancel only (both become None)."""
    data = await create_test_data_custom(session_factory, exchange, take_profit=70000.0, stop_loss=None)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"remove_tp": True},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 1, f"{exchange}: expected only cancel call, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: should only cancel"

        # Verify DB: both TP and SL are None
        from sqlalchemy import select
        async with session_factory() as session:
            result = await session.execute(
                select(TradeRecord).where(TradeRecord.id == data["trade"].id)
            )
            trade = result.scalar_one()
            assert trade.take_profit is None, f"{exchange}: DB TP should be None"
            assert trade.stop_loss is None, f"{exchange}: DB SL should be None"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 11: Add TP when only SL exists ──────────────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_add_tp_when_only_sl(exchange, engine, session_factory):
    """Adding TP to SL-only trade should: place(tp=70000, sl=66000) -> cancel()."""
    data = await create_test_data_custom(session_factory, exchange, take_profit=None, stop_loss=66000.0)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"take_profit": 70000.0},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] == 70000.0, f"{exchange}: TP should be 70000"
        assert set_kwargs["stop_loss"] == 66000.0, f"{exchange}: SL should stay 66000"
    finally:
        app.dependency_overrides.clear()


# ─── Scenario 12: Add SL when only TP exists ──────────────────────


@pytest.mark.parametrize("exchange", ALL_EXCHANGES)
async def test_add_sl_when_only_tp(exchange, engine, session_factory):
    """Adding SL to TP-only trade should: place(tp=70000, sl=66000) -> cancel()."""
    data = await create_test_data_custom(session_factory, exchange, take_profit=70000.0, stop_loss=None)
    mock_client, call_log = make_mock_client()

    from src.api.main_app import create_app
    app = create_app()

    from src.api.rate_limit import limiter
    limiter.enabled = False

    _setup_app_overrides(app, session_factory)

    try:
        with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
             patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
            resp = await _send_tpsl_request(
                app, data["trade"].id, data["token"],
                {"stop_loss": 66000.0},
            )

        assert resp.status_code == 200, f"{exchange}: {resp.text}"
        assert len(call_log) == 2, f"{exchange}: expected 2 calls, got {call_log}"
        assert call_log[0][0] == "cancel_position_tpsl", f"{exchange}: first call should be cancel"
        assert call_log[1][0] == "set_position_tpsl", f"{exchange}: second call should be set"

        set_kwargs = call_log[1][1]
        assert set_kwargs["take_profit"] == 70000.0, f"{exchange}: TP should stay 70000"
        assert set_kwargs["stop_loss"] == 66000.0, f"{exchange}: SL should be 66000"
    finally:
        app.dependency_overrides.clear()
