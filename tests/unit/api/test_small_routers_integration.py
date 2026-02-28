"""
Integration tests for four small API routers: users, backtest, statistics, affiliate.

All four routers are mounted in a single FastAPI app and tested together using
an in-memory SQLite database. This file targets uncovered lines to increase
coverage across all four routers.

Coverage targets:
  - users.py:      46% -> 90%+ (lines 16-99)
  - backtest.py:   38% -> 90%+ (lines 33-257)
  - statistics.py: 71% -> 90%+ (lines 16-198)
  - affiliate.py:  58% -> 90%+ (lines 17-79)
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import AffiliateLink, BacktestRun, Base, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token
from src.errors import (
    ERR_BACKTEST_NOT_FOUND,
    ERR_CANNOT_DELETE_SELF,
    ERR_END_BEFORE_START,
    ERR_INVALID_DATE_FORMAT,
    ERR_INVALID_EXCHANGE,
    ERR_USERNAME_EXISTS,
    ERR_USER_NOT_FOUND,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _register_test_strategy():
    """Register a minimal test strategy so backtest endpoints work."""
    from src.strategy.base import BaseStrategy, StrategyRegistry, TradeSignal

    if "test_strategy" in StrategyRegistry._strategies:
        return

    class TestStrategy(BaseStrategy):
        async def generate_signal(self, symbol: str) -> TradeSignal:
            raise NotImplementedError

        async def should_trade(self, signal) -> tuple:
            return False, "Test"

        @classmethod
        def get_param_schema(cls) -> dict:
            return {"test_param": {"type": "int", "label": "Test", "default": 42}}

        @classmethod
        def get_description(cls) -> str:
            return "Test strategy for integration tests"

    StrategyRegistry.register("test_strategy", TestStrategy)


# ===========================================================================
# Shared fixtures
# ===========================================================================


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
    """Create a regular (non-admin) user."""
    async with session_factory() as session:
        u = User(
            username="regular",
            email="regular@test.com",
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
async def admin_user(session_factory):
    """Create an admin user."""
    async with session_factory() as session:
        u = User(
            username="admin",
            email="admin@test.com",
            password_hash=hash_password("adminpass123"),
            role="admin",
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
async def admin_headers(admin_user):
    token_data = {"sub": str(admin_user.id), "role": admin_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def app(session_factory):
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import users, backtest, statistics, affiliate
    from src.models.session import get_db

    limiter.enabled = False
    _register_test_strategy()

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
    test_app.include_router(users.router)
    test_app.include_router(backtest.router)
    test_app.include_router(statistics.router)
    test_app.include_router(affiliate.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ===========================================================================
# Test data fixtures
# ===========================================================================


@pytest_asyncio.fixture
async def backtest_run(session_factory, user):
    """A completed backtest run belonging to the regular user."""
    async with session_factory() as session:
        run = BacktestRun(
            user_id=user.id,
            strategy_type="test_strategy",
            symbol="BTCUSDT",
            timeframe="1h",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 3, 1),
            initial_capital=10000.0,
            status="completed",
            result_metrics=json.dumps({
                "total_return_percent": 15.2,
                "win_rate": 55.0,
                "max_drawdown_percent": 8.1,
                "sharpe_ratio": 1.2,
                "profit_factor": 1.6,
                "total_trades": 20,
                "winning_trades": 11,
                "losing_trades": 9,
                "average_win": 45.0,
                "average_loss": -30.0,
                "total_pnl": 1520.0,
                "total_fees": 50.0,
                "starting_capital": 10000.0,
                "ending_capital": 11520.0,
            }),
            equity_curve=json.dumps([
                {"timestamp": "2024-01-01", "equity": 10000},
                {"timestamp": "2024-03-01", "equity": 11520},
            ]),
            trades=json.dumps([{
                "entry_date": "2024-01-15",
                "exit_date": "2024-01-16",
                "direction": "long",
                "entry_price": 42000,
                "exit_price": 43000,
                "position_value": 1000,
                "pnl": 100,
                "pnl_percent": 2.38,
                "fees": 2.0,
                "net_pnl": 98.0,
                "result": "win",
                "reason": "Signal detected",
                "confidence": 80,
            }]),
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            completed_at=datetime(2024, 3, 1, 12, 0),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


@pytest_asyncio.fixture
async def pending_backtest_run(session_factory, user):
    """A pending backtest run belonging to the regular user."""
    async with session_factory() as session:
        run = BacktestRun(
            user_id=user.id,
            strategy_type="test_strategy",
            symbol="ETHUSDT",
            timeframe="4h",
            start_date=datetime(2024, 6, 1),
            end_date=datetime(2024, 9, 1),
            initial_capital=5000.0,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


@pytest_asyncio.fixture
async def three_pending_runs(session_factory, user):
    """Insert 3 pending/running runs to trigger concurrent limit."""
    runs = []
    async with session_factory() as session:
        for i in range(3):
            run = BacktestRun(
                user_id=user.id,
                strategy_type="test_strategy",
                symbol="BTCUSDT",
                timeframe="1d",
                start_date=datetime(2024, 1, 1),
                end_date=datetime(2024, 6, 1),
                initial_capital=10000.0,
                status="pending" if i < 2 else "running",
                created_at=datetime.now(timezone.utc),
            )
            session.add(run)
            runs.append(run)
        await session.commit()
        for r in runs:
            await session.refresh(r)
    return runs


@pytest_asyncio.fixture
async def trade_data(session_factory, user):
    """Insert closed trades for statistics testing."""
    now = datetime.now(timezone.utc)
    trades = [
        TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000,
            exit_price=96000,
            take_profit=97000,
            stop_loss=94000,
            leverage=4,
            confidence=80,
            reason="Signal detected",
            order_id="int_ord_001",
            status="closed",
            pnl=10.0,
            pnl_percent=1.0,
            fees=0.5,
            funding_paid=0.1,
            builder_fee=0.2,
            entry_time=now - timedelta(days=5),
            exit_time=now - timedelta(days=4),
            exchange="hyperliquid",
            demo_mode=False,
        ),
        TradeRecord(
            user_id=user.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500,
            exit_price=3600,
            take_profit=3300,
            stop_loss=3700,
            leverage=3,
            confidence=60,
            reason="Reversal expected",
            order_id="int_ord_002",
            status="closed",
            pnl=-10.0,
            pnl_percent=-2.8,
            fees=0.3,
            funding_paid=0.05,
            builder_fee=0.0,
            entry_time=now - timedelta(days=3),
            exit_time=now - timedelta(days=2),
            exchange="bitget",
            demo_mode=True,
        ),
    ]
    async with session_factory() as session:
        session.add_all(trades)
        await session.commit()
    return trades


@pytest_asyncio.fixture
async def affiliate_links(session_factory):
    """Insert sample affiliate links."""
    async with session_factory() as session:
        links = [
            AffiliateLink(
                exchange_type="bitget",
                affiliate_url="https://bitget.com/ref/test",
                label="Bitget referral",
                is_active=True,
                uid_required=True,
            ),
            AffiliateLink(
                exchange_type="weex",
                affiliate_url="https://weex.com/ref/test",
                label="Weex referral",
                is_active=True,
                uid_required=False,
            ),
            AffiliateLink(
                exchange_type="hyperliquid",
                affiliate_url="https://hyperliquid.xyz/ref/test",
                label="HL referral",
                is_active=False,
                uid_required=False,
            ),
        ]
        session.add_all(links)
        await session.commit()
        for link in links:
            await session.refresh(link)
        return links


# ===========================================================================
# USERS ROUTER TESTS
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /api/users - list_users (admin only)
# ---------------------------------------------------------------------------


async def test_users_list_admin_returns_all(client, admin_headers, admin_user, user):
    """Admin can list all users and sees both admin and regular user."""
    resp = await client.get("/api/users", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    usernames = [u["username"] for u in data]
    assert "admin" in usernames
    assert "regular" in usernames


async def test_users_list_admin_response_fields(client, admin_headers, admin_user):
    """User response contains expected fields and no password_hash."""
    resp = await client.get("/api/users", headers=admin_headers)
    data = resp.json()
    for u in data:
        assert "id" in u
        assert "username" in u
        assert "email" in u
        assert "role" in u
        assert "language" in u
        assert "is_active" in u
        assert "password_hash" not in u


async def test_users_list_forbidden_for_regular_user(client, auth_headers, user):
    """Regular user gets 403 when listing users."""
    resp = await client.get("/api/users", headers=auth_headers)
    assert resp.status_code == 403


async def test_users_list_requires_auth(client):
    """Listing users without auth returns 401."""
    resp = await client.get("/api/users")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/users - create_user (admin only)
# ---------------------------------------------------------------------------


async def test_users_create_success(client, admin_headers, admin_user):
    """Admin can create a new user with all fields."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "newuser",
            "password": "New@pass123",
            "email": "new@test.com",
            "role": "user",
            "language": "de",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newuser"
    assert data["email"] == "new@test.com"
    assert data["role"] == "user"
    assert data["language"] == "de"
    assert data["is_active"] is True


async def test_users_create_duplicate_username_returns_409(
    client, admin_headers, admin_user
):
    """Creating a user with an existing username returns 409."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "admin", "password": "Test@1234"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == ERR_USERNAME_EXISTS


async def test_users_create_defaults(client, admin_headers, admin_user):
    """Creating user without optional fields uses defaults (role=user, language=de)."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "defaultuser", "password": "Test@1234"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["role"] == "user"
    assert data["language"] == "de"


async def test_users_create_forbidden_for_regular_user(client, auth_headers, user):
    """Regular user cannot create users (403)."""
    resp = await client.post(
        "/api/users",
        headers=auth_headers,
        json={"username": "blocked", "password": "Test@1234"},
    )
    assert resp.status_code == 403


async def test_users_create_requires_auth(client):
    """Create user without auth returns 401."""
    resp = await client.post(
        "/api/users",
        json={"username": "noauth", "password": "Test@1234"},
    )
    assert resp.status_code == 401


async def test_users_create_short_username_rejected(client, admin_headers, admin_user):
    """Username shorter than 3 chars is rejected (422)."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "ab", "password": "Test@1234"},
    )
    assert resp.status_code == 422


async def test_users_create_short_password_rejected(client, admin_headers, admin_user):
    """Password shorter than 8 chars is rejected (422)."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "validname", "password": "short"},
    )
    assert resp.status_code == 422


async def test_users_create_invalid_role_rejected(client, admin_headers, admin_user):
    """Invalid role value is rejected (422)."""
    resp = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"username": "badrole", "password": "Test@1234", "role": "superadmin"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/users/{user_id} - update_user (admin only)
# ---------------------------------------------------------------------------


async def test_users_update_email(client, admin_headers, admin_user, user):
    """Admin can update a user's email."""
    resp = await client.put(
        f"/api/users/{user.id}",
        headers=admin_headers,
        json={"email": "updated@test.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "updated@test.com"


async def test_users_update_role(client, admin_headers, admin_user, user):
    """Admin can change a user's role."""
    resp = await client.put(
        f"/api/users/{user.id}",
        headers=admin_headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_users_update_language(client, admin_headers, admin_user, user):
    """Admin can change a user's language."""
    resp = await client.put(
        f"/api/users/{user.id}",
        headers=admin_headers,
        json={"language": "de"},
    )
    assert resp.status_code == 200
    assert resp.json()["language"] == "de"


async def test_users_update_is_active(client, admin_headers, admin_user, user):
    """Admin can deactivate a user."""
    resp = await client.put(
        f"/api/users/{user.id}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


async def test_users_update_password(client, admin_headers, admin_user, user):
    """Admin can change a user's password (not visible in response)."""
    resp = await client.put(
        f"/api/users/{user.id}",
        headers=admin_headers,
        json={"password": "New@pass789"},
    )
    assert resp.status_code == 200
    assert "password" not in resp.json()
    assert "password_hash" not in resp.json()


async def test_users_update_multiple_fields(client, admin_headers, admin_user, user):
    """Admin can update multiple fields at once."""
    resp = await client.put(
        f"/api/users/{user.id}",
        headers=admin_headers,
        json={
            "email": "multi@test.com",
            "role": "admin",
            "language": "de",
            "is_active": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "multi@test.com"
    assert data["role"] == "admin"
    assert data["language"] == "de"
    assert data["is_active"] is False


async def test_users_update_not_found(client, admin_headers, admin_user):
    """Updating a non-existent user returns 404."""
    resp = await client.put(
        "/api/users/99999",
        headers=admin_headers,
        json={"email": "gone@test.com"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == ERR_USER_NOT_FOUND


async def test_users_update_forbidden_for_regular_user(client, auth_headers, user):
    """Regular user cannot update users (403)."""
    resp = await client.put(
        f"/api/users/{user.id}",
        headers=auth_headers,
        json={"email": "nope@test.com"},
    )
    assert resp.status_code == 403


async def test_users_update_requires_auth(client, user):
    """Update without auth returns 401."""
    resp = await client.put(
        f"/api/users/{user.id}",
        json={"email": "no@auth.com"},
    )
    assert resp.status_code == 401


async def test_users_update_empty_body(client, admin_headers, admin_user, user):
    """Sending empty body returns current data."""
    resp = await client.put(
        f"/api/users/{user.id}",
        headers=admin_headers,
        json={},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "regular"


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_id} - delete_user (admin only)
# ---------------------------------------------------------------------------


async def test_users_delete_success(client, admin_headers, admin_user, user):
    """Admin can delete another user (204)."""
    resp = await client.delete(f"/api/users/{user.id}", headers=admin_headers)
    assert resp.status_code == 204


async def test_users_delete_cannot_delete_self(client, admin_headers, admin_user):
    """Admin cannot delete themselves (400)."""
    resp = await client.delete(f"/api/users/{admin_user.id}", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == ERR_CANNOT_DELETE_SELF


async def test_users_delete_not_found(client, admin_headers, admin_user):
    """Deleting a non-existent user returns 404."""
    resp = await client.delete("/api/users/99999", headers=admin_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == ERR_USER_NOT_FOUND


async def test_users_delete_forbidden_for_regular_user(
    client, auth_headers, user, admin_user
):
    """Regular user cannot delete users (403)."""
    resp = await client.delete(f"/api/users/{admin_user.id}", headers=auth_headers)
    assert resp.status_code == 403


async def test_users_delete_requires_auth(client, user):
    """Delete without auth returns 401."""
    resp = await client.delete(f"/api/users/{user.id}")
    assert resp.status_code == 401


async def test_users_delete_then_list_excludes(
    client, admin_headers, admin_user, user
):
    """After deleting a user, they no longer appear in the list."""
    await client.delete(f"/api/users/{user.id}", headers=admin_headers)
    resp = await client.get("/api/users", headers=admin_headers)
    data = resp.json()
    usernames = [u["username"] for u in data]
    assert "regular" not in usernames


# ===========================================================================
# BACKTEST ROUTER TESTS
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /api/backtest/strategies
# ---------------------------------------------------------------------------


async def test_backtest_list_strategies(client, auth_headers, user):
    """Lists available strategies including the registered test_strategy."""
    resp = await client.get("/api/backtest/strategies", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "strategies" in data
    names = [s["name"] for s in data["strategies"]]
    assert "test_strategy" in names


async def test_backtest_list_strategies_requires_auth(client):
    """Listing strategies without auth returns 401."""
    resp = await client.get("/api/backtest/strategies")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/backtest/run
# ---------------------------------------------------------------------------


async def test_backtest_start_success(client, auth_headers, user):
    """Starting a backtest returns run_id and pending status."""
    with patch("src.api.routers.backtest._execute_backtest"):
        resp = await client.post(
            "/api/backtest/run",
            headers=auth_headers,
            json={
                "strategy_type": "test_strategy",
                "symbol": "BTCUSDT",
                "timeframe": "1d",
                "start_date": "2024-01-01",
                "end_date": "2024-06-01",
                "initial_capital": 10000.0,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "pending"


async def test_backtest_start_with_strategy_params(client, auth_headers, user):
    """Starting a backtest with strategy_params succeeds."""
    with patch("src.api.routers.backtest._execute_backtest"):
        resp = await client.post(
            "/api/backtest/run",
            headers=auth_headers,
            json={
                "strategy_type": "test_strategy",
                "start_date": "2024-01-01",
                "end_date": "2024-06-01",
                "strategy_params": {"test_param": 99},
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


async def test_backtest_start_invalid_strategy(client, auth_headers, user):
    """Unknown strategy returns 400."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "nonexistent_strategy",
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
        },
    )
    assert resp.status_code == 400


async def test_backtest_start_invalid_date_format(client, auth_headers, user):
    """Invalid date format returns 400."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "test_strategy",
            "start_date": "not-a-date",
            "end_date": "2024-06-01",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == ERR_INVALID_DATE_FORMAT


async def test_backtest_start_end_before_start(client, auth_headers, user):
    """end_date before start_date returns 400."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "test_strategy",
            "start_date": "2024-06-01",
            "end_date": "2024-01-01",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == ERR_END_BEFORE_START


async def test_backtest_start_same_dates(client, auth_headers, user):
    """Same start and end date returns 400 (end must be after start)."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "test_strategy",
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
        },
    )
    assert resp.status_code == 400


async def test_backtest_start_concurrent_limit(
    client, auth_headers, three_pending_runs
):
    """Exceeding concurrent backtest limit returns 429."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "test_strategy",
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
        },
    )
    assert resp.status_code == 429
    assert "concurrent" in resp.json()["detail"].lower()


async def test_backtest_start_requires_auth(client):
    """Starting a backtest without auth returns 401."""
    resp = await client.post(
        "/api/backtest/run",
        json={
            "strategy_type": "test_strategy",
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
        },
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/backtest/history
# ---------------------------------------------------------------------------


async def test_backtest_history(client, auth_headers, backtest_run):
    """History returns user's backtest runs with metrics."""
    resp = await client.get("/api/backtest/history", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["runs"]) >= 1
    assert data["page"] == 1

    run = data["runs"][0]
    assert run["strategy_type"] == "test_strategy"
    assert run["total_return_percent"] is not None
    assert run["win_rate"] is not None
    assert run["total_trades"] is not None


async def test_backtest_history_pagination(client, auth_headers, backtest_run):
    """History supports page and per_page params."""
    resp = await client.get(
        "/api/backtest/history",
        headers=auth_headers,
        params={"page": 1, "per_page": 1},
    )
    data = resp.json()
    assert data["per_page"] == 1
    assert len(data["runs"]) <= 1


async def test_backtest_history_empty(client, auth_headers, user):
    """History returns empty when no backtests exist."""
    resp = await client.get("/api/backtest/history", headers=auth_headers)
    data = resp.json()
    assert data["total"] == 0
    assert data["runs"] == []


async def test_backtest_history_requires_auth(client):
    """History without auth returns 401."""
    resp = await client.get("/api/backtest/history")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/backtest/{run_id}
# ---------------------------------------------------------------------------


async def test_backtest_get_run_completed(client, auth_headers, backtest_run):
    """Get a completed backtest run with metrics, equity_curve, trades."""
    resp = await client.get(
        f"/api/backtest/{backtest_run.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == backtest_run.id
    assert data["status"] == "completed"
    assert data["metrics"] is not None
    assert data["metrics"]["total_return_percent"] == 15.2
    assert data["equity_curve"] is not None
    assert len(data["equity_curve"]) == 2
    assert data["trades"] is not None
    assert len(data["trades"]) == 1
    assert data["completed_at"] is not None


async def test_backtest_get_run_pending(client, auth_headers, pending_backtest_run):
    """Pending run has null metrics, equity_curve, and trades."""
    resp = await client.get(
        f"/api/backtest/{pending_backtest_run.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["metrics"] is None
    assert data["equity_curve"] is None
    assert data["trades"] is None


async def test_backtest_get_run_not_found(client, auth_headers, user):
    """Getting a non-existent run returns 404."""
    resp = await client.get("/api/backtest/99999", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == ERR_BACKTEST_NOT_FOUND


async def test_backtest_get_run_requires_auth(client, backtest_run):
    """Getting a run without auth returns 401."""
    resp = await client.get(f"/api/backtest/{backtest_run.id}")
    assert resp.status_code == 401


async def test_backtest_get_run_response_fields(client, auth_headers, backtest_run):
    """Response includes all expected fields."""
    resp = await client.get(
        f"/api/backtest/{backtest_run.id}", headers=auth_headers
    )
    data = resp.json()
    expected_fields = {
        "id", "strategy_type", "symbol", "timeframe", "start_date", "end_date",
        "initial_capital", "strategy_params", "status", "error_message",
        "metrics", "equity_curve", "trades", "created_at", "completed_at",
    }
    assert expected_fields.issubset(set(data.keys()))


# ---------------------------------------------------------------------------
# DELETE /api/backtest/{run_id}
# ---------------------------------------------------------------------------


async def test_backtest_delete_success(client, auth_headers, backtest_run):
    """Delete a backtest run succeeds and is confirmed gone."""
    resp = await client.delete(
        f"/api/backtest/{backtest_run.id}", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    # Verify it is actually deleted
    resp2 = await client.get(
        f"/api/backtest/{backtest_run.id}", headers=auth_headers
    )
    assert resp2.status_code == 404


async def test_backtest_delete_not_found(client, auth_headers, user):
    """Deleting a non-existent run returns 404."""
    resp = await client.delete("/api/backtest/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_backtest_delete_requires_auth(client, backtest_run):
    """Deleting without auth returns 401."""
    resp = await client.delete(f"/api/backtest/{backtest_run.id}")
    assert resp.status_code == 401


# ===========================================================================
# STATISTICS ROUTER TESTS
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /api/statistics
# ---------------------------------------------------------------------------


async def test_statistics_with_trades(client, auth_headers, user, trade_data):
    """Statistics endpoint returns correct aggregated values."""
    resp = await client.get("/api/statistics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["period_days"] == 30
    assert data["total_trades"] == 2
    assert data["winning_trades"] == 1
    assert data["losing_trades"] == 1
    assert data["total_pnl"] == pytest.approx(0.0, abs=0.01)
    assert data["total_fees"] == pytest.approx(0.8, abs=0.01)
    assert data["win_rate"] == pytest.approx(50.0, abs=1.0)
    assert data["best_trade"] == pytest.approx(10.0, abs=0.01)
    assert data["worst_trade"] == pytest.approx(-10.0, abs=0.01)
    assert "net_pnl" in data
    assert "avg_pnl_percent" in data
    assert "total_funding" in data
    assert "total_builder_fees" in data


async def test_statistics_no_trades(client, auth_headers, user):
    """Statistics with no trades returns zeroed values."""
    resp = await client.get("/api/statistics", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_trades"] == 0
    assert data["winning_trades"] == 0
    assert data["losing_trades"] == 0
    assert data["total_pnl"] == 0
    assert data["total_fees"] == 0
    assert data["win_rate"] == 0
    assert data["net_pnl"] == 0


async def test_statistics_demo_mode_filter_true(
    client, auth_headers, user, trade_data
):
    """Statistics filters by demo_mode=true (only demo trades)."""
    resp = await client.get(
        "/api/statistics",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only the ETHUSDT trade is demo_mode=True
    assert data["total_trades"] == 1
    assert data["total_pnl"] == pytest.approx(-10.0, abs=0.01)


async def test_statistics_demo_mode_filter_false(
    client, auth_headers, user, trade_data
):
    """Statistics filters by demo_mode=false (only live trades)."""
    resp = await client.get(
        "/api/statistics",
        headers=auth_headers,
        params={"demo_mode": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only the BTCUSDT trade is demo_mode=False
    assert data["total_trades"] == 1
    assert data["total_pnl"] == pytest.approx(10.0, abs=0.01)


async def test_statistics_custom_days(client, auth_headers, user, trade_data):
    """Statistics respects custom days parameter."""
    resp = await client.get(
        "/api/statistics", headers=auth_headers, params={"days": 4}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_days"] == 4
    # Only the ETHUSDT trade (3 days ago) should be in range
    assert data["total_trades"] >= 1


async def test_statistics_requires_auth(client):
    """Statistics endpoint requires auth."""
    resp = await client.get("/api/statistics")
    assert resp.status_code == 401


async def test_statistics_net_pnl_formula(client, auth_headers, user, trade_data):
    """Net PnL = total_pnl - total_fees - abs(total_funding)."""
    resp = await client.get("/api/statistics", headers=auth_headers)
    data = resp.json()
    expected_net = data["total_pnl"] - data["total_fees"] - abs(data["total_funding"])
    assert data["net_pnl"] == pytest.approx(expected_net, abs=0.01)


async def test_statistics_days_validation_low(client, auth_headers, user):
    """Days parameter below 1 is rejected (422)."""
    resp = await client.get(
        "/api/statistics", headers=auth_headers, params={"days": 0}
    )
    assert resp.status_code == 422


async def test_statistics_days_validation_high(client, auth_headers, user):
    """Days parameter above 365 is rejected (422)."""
    resp = await client.get(
        "/api/statistics", headers=auth_headers, params={"days": 366}
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/statistics/daily
# ---------------------------------------------------------------------------


async def test_daily_stats_with_trades(client, auth_headers, user, trade_data):
    """Daily stats returns day-level aggregates."""
    resp = await client.get("/api/statistics/daily", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "days" in data
    assert isinstance(data["days"], list)
    assert len(data["days"]) >= 1

    for day in data["days"]:
        expected = {"date", "trades", "pnl", "fees", "funding", "builder_fees", "wins", "losses"}
        assert expected.issubset(set(day.keys()))


async def test_daily_stats_no_trades(client, auth_headers, user):
    """Daily stats returns empty days list when no trades exist."""
    resp = await client.get("/api/statistics/daily", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["days"] == []


async def test_daily_stats_demo_mode_filter(client, auth_headers, user, trade_data):
    """Daily stats filters by demo_mode."""
    resp = await client.get(
        "/api/statistics/daily",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only the ETHUSDT demo trade
    assert len(data["days"]) == 1


async def test_daily_stats_custom_days(client, auth_headers, user, trade_data):
    """Daily stats respects custom days parameter."""
    resp = await client.get(
        "/api/statistics/daily",
        headers=auth_headers,
        params={"days": 4},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["days"]) >= 1


async def test_daily_stats_requires_auth(client):
    """Daily stats requires auth."""
    resp = await client.get("/api/statistics/daily")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/statistics/revenue
# ---------------------------------------------------------------------------


async def test_revenue_with_hl_trades(client, auth_headers, user, trade_data):
    """Revenue analytics returns builder fees from hyperliquid trades."""
    resp = await client.get("/api/statistics/revenue", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["period_days"] == 30
    # Only BTCUSDT trade is hyperliquid
    assert data["total_trades"] == 1
    assert data["total_builder_fees"] == pytest.approx(0.2, abs=0.01)
    assert data["total_exchange_fees"] == pytest.approx(0.5, abs=0.01)
    assert "monthly_estimate" in data
    assert "daily" in data
    assert isinstance(data["daily"], list)


async def test_revenue_no_trades(client, auth_headers, user):
    """Revenue analytics with no trades returns zeroed values."""
    resp = await client.get("/api/statistics/revenue", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_trades"] == 0
    assert data["total_builder_fees"] == 0
    assert data["total_exchange_fees"] == 0
    assert data["monthly_estimate"] == 0
    assert data["daily"] == []


async def test_revenue_demo_mode_filter(client, auth_headers, user, trade_data):
    """Revenue analytics filters by demo_mode."""
    # The BTCUSDT HL trade is demo_mode=False
    resp_demo = await client.get(
        "/api/statistics/revenue",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert resp_demo.status_code == 200
    assert resp_demo.json()["total_trades"] == 0

    resp_live = await client.get(
        "/api/statistics/revenue",
        headers=auth_headers,
        params={"demo_mode": False},
    )
    assert resp_live.status_code == 200
    assert resp_live.json()["total_trades"] == 1


async def test_revenue_custom_days(client, auth_headers, user, trade_data):
    """Revenue analytics with custom days parameter."""
    resp = await client.get(
        "/api/statistics/revenue",
        headers=auth_headers,
        params={"days": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_days"] == 3
    # HL trade entry was 5 days ago, so outside 3-day window
    assert data["total_trades"] == 0


async def test_revenue_requires_auth(client):
    """Revenue analytics requires auth."""
    resp = await client.get("/api/statistics/revenue")
    assert resp.status_code == 401


async def test_revenue_daily_breakdown_fields(
    client, auth_headers, user, trade_data
):
    """Revenue daily breakdown has expected fields."""
    resp = await client.get("/api/statistics/revenue", headers=auth_headers)
    data = resp.json()
    for day in data["daily"]:
        expected = {"date", "trades", "builder_fees", "exchange_fees", "pnl"}
        assert expected.issubset(set(day.keys()))


async def test_revenue_monthly_estimate_calculation(
    client, auth_headers, user, trade_data
):
    """Monthly estimate = (total_builder_fees / days) * 30."""
    resp = await client.get("/api/statistics/revenue", headers=auth_headers)
    data = resp.json()
    if data["total_trades"] > 0:
        daily_avg = data["total_builder_fees"] / data["period_days"]
        expected_monthly = daily_avg * 30
        assert data["monthly_estimate"] == pytest.approx(expected_monthly, abs=0.01)


# ===========================================================================
# AFFILIATE ROUTER TESTS
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /api/affiliate-links
# ---------------------------------------------------------------------------


async def test_affiliate_list_active_only(
    client, auth_headers, user, affiliate_links
):
    """List affiliate links returns only active links."""
    resp = await client.get("/api/affiliate-links", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    exchanges = [link["exchange_type"] for link in data]
    assert "bitget" in exchanges
    assert "weex" in exchanges
    assert "hyperliquid" not in exchanges


async def test_affiliate_list_empty(client, auth_headers, user):
    """List affiliate links returns empty when none exist."""
    resp = await client.get("/api/affiliate-links", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_affiliate_list_response_fields(
    client, auth_headers, user, affiliate_links
):
    """Affiliate link response has expected fields."""
    resp = await client.get("/api/affiliate-links", headers=auth_headers)
    data = resp.json()
    for link in data:
        expected = {"exchange_type", "affiliate_url", "label", "is_active", "uid_required"}
        assert expected.issubset(set(link.keys()))


async def test_affiliate_list_any_user_allowed(
    client, auth_headers, user, affiliate_links
):
    """Regular (non-admin) user can list affiliate links."""
    resp = await client.get("/api/affiliate-links", headers=auth_headers)
    assert resp.status_code == 200


async def test_affiliate_list_admin_allowed(
    client, admin_headers, admin_user, affiliate_links
):
    """Admin can also list affiliate links (admins see all including inactive)."""
    resp = await client.get("/api/affiliate-links", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 3


async def test_affiliate_list_requires_auth(client):
    """List affiliate links without auth returns 401."""
    resp = await client.get("/api/affiliate-links")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/affiliate-links/{exchange} - upsert
# ---------------------------------------------------------------------------


async def test_affiliate_upsert_create_new(client, admin_headers, admin_user):
    """Admin can create a new affiliate link via PUT."""
    resp = await client.put(
        "/api/affiliate-links/bitget",
        headers=admin_headers,
        json={
            "affiliate_url": "https://bitget.com/ref/new",
            "label": "New Bitget link",
            "is_active": True,
            "uid_required": True,
        },
    )
    assert resp.status_code == 200


async def test_affiliate_upsert_update_existing(
    client, admin_headers, admin_user, affiliate_links
):
    """Admin can update an existing affiliate link."""
    resp = await client.put(
        "/api/affiliate-links/bitget",
        headers=admin_headers,
        json={
            "affiliate_url": "https://bitget.com/ref/updated",
            "label": "Updated label",
            "is_active": False,
            "uid_required": False,
        },
    )
    assert resp.status_code == 200


async def test_affiliate_upsert_invalid_exchange(client, admin_headers, admin_user):
    """Invalid exchange name returns 400."""
    resp = await client.put(
        "/api/affiliate-links/kraken",
        headers=admin_headers,
        json={
            "affiliate_url": "https://kraken.com/ref",
            "label": "Kraken",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == ERR_INVALID_EXCHANGE


async def test_affiliate_upsert_forbidden_for_regular_user(
    client, auth_headers, user
):
    """Regular user cannot upsert affiliate links (403)."""
    resp = await client.put(
        "/api/affiliate-links/bitget",
        headers=auth_headers,
        json={"affiliate_url": "https://bitget.com/ref/nope"},
    )
    assert resp.status_code == 403


async def test_affiliate_upsert_requires_auth(client):
    """Upsert without auth returns 401."""
    resp = await client.put(
        "/api/affiliate-links/bitget",
        json={"affiliate_url": "https://bitget.com/ref/nope"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/affiliate-links/{exchange}
# ---------------------------------------------------------------------------


async def test_affiliate_delete_success(
    client, admin_headers, admin_user, affiliate_links
):
    """Admin can delete an affiliate link."""
    resp = await client.delete(
        "/api/affiliate-links/bitget", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.json()["detail"] == "deleted"


async def test_affiliate_delete_not_found(client, admin_headers, admin_user):
    """Deleting a non-existent link returns 404."""
    resp = await client.delete(
        "/api/affiliate-links/bitget", headers=admin_headers
    )
    assert resp.status_code == 404
    assert "nicht gefunden" in resp.json()["detail"].lower()


async def test_affiliate_delete_forbidden_for_regular_user(
    client, auth_headers, user, affiliate_links
):
    """Regular user cannot delete affiliate links (403)."""
    resp = await client.delete("/api/affiliate-links/bitget", headers=auth_headers)
    assert resp.status_code == 403


async def test_affiliate_delete_requires_auth(client, affiliate_links):
    """Delete without auth returns 401."""
    resp = await client.delete("/api/affiliate-links/bitget")
    assert resp.status_code == 401


async def test_affiliate_delete_then_list_excludes(
    client, admin_headers, admin_user, affiliate_links
):
    """After deleting a link, it no longer appears in the list."""
    await client.delete("/api/affiliate-links/bitget", headers=admin_headers)
    resp = await client.get("/api/affiliate-links", headers=admin_headers)
    data = resp.json()
    exchanges = [item["exchange_type"] for item in data]
    assert "bitget" not in exchanges


# ===========================================================================
# CROSS-ROUTER INTEGRATION TESTS
# ===========================================================================


async def test_all_routers_reject_unauthenticated_requests(client):
    """All protected endpoints return 401 without authentication."""
    endpoints = [
        ("GET", "/api/users"),
        ("POST", "/api/users"),
        ("PUT", "/api/users/1"),
        ("DELETE", "/api/users/1"),
        ("GET", "/api/backtest/strategies"),
        ("POST", "/api/backtest/run"),
        ("GET", "/api/backtest/history"),
        ("GET", "/api/backtest/1"),
        ("DELETE", "/api/backtest/1"),
        ("GET", "/api/statistics"),
        ("GET", "/api/statistics/daily"),
        ("GET", "/api/statistics/revenue"),
        ("GET", "/api/affiliate-links"),
        ("PUT", "/api/affiliate-links/bitget"),
        ("DELETE", "/api/affiliate-links/bitget"),
    ]
    for method, path in endpoints:
        if method == "GET":
            resp = await client.get(path)
        elif method == "POST":
            resp = await client.post(path, json={})
        elif method == "PUT":
            resp = await client.put(path, json={})
        elif method == "DELETE":
            resp = await client.delete(path)
        assert resp.status_code in (401, 422), (
            f"{method} {path} returned {resp.status_code}, expected 401 or 422"
        )


async def test_admin_only_endpoints_reject_regular_user(
    client, auth_headers, user, admin_user
):
    """Admin-only endpoints return 403 for regular users."""
    admin_endpoints = [
        ("GET", "/api/users"),
        ("POST", "/api/users"),
        ("PUT", f"/api/users/{admin_user.id}"),
        ("DELETE", f"/api/users/{admin_user.id}"),
        ("PUT", "/api/affiliate-links/bitget"),
        ("DELETE", "/api/affiliate-links/bitget"),
    ]
    for method, path in admin_endpoints:
        if method == "GET":
            resp = await client.get(path, headers=auth_headers)
        elif method == "POST":
            resp = await client.post(
                path,
                headers=auth_headers,
                json={"username": "test_cross", "password": "Test@1234"},
            )
        elif method == "PUT":
            resp = await client.put(
                path,
                headers=auth_headers,
                json={"email": "x@test.com", "affiliate_url": "https://test.com"},
            )
        elif method == "DELETE":
            resp = await client.delete(path, headers=auth_headers)
        assert resp.status_code == 403, (
            f"{method} {path} returned {resp.status_code}, expected 403"
        )


async def test_user_endpoints_accessible_by_regular_user(
    client, auth_headers, user
):
    """Regular user can access non-admin endpoints (backtest, statistics)."""
    user_endpoints = [
        ("GET", "/api/backtest/strategies"),
        ("GET", "/api/backtest/history"),
        ("GET", "/api/statistics"),
        ("GET", "/api/statistics/daily"),
        ("GET", "/api/statistics/revenue"),
        ("GET", "/api/affiliate-links"),
    ]
    for method, path in user_endpoints:
        resp = await client.get(path, headers=auth_headers)
        assert resp.status_code == 200, (
            f"GET {path} returned {resp.status_code}, expected 200"
        )
