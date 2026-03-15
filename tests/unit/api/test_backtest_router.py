"""
Unit tests for the backtest API router.

Covers list_strategies, start_backtest, list_history, get_run,
delete_run, concurrent limit, validation, and auth requirements.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, BacktestRun, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token
from src.errors import ERR_END_BEFORE_START, ERR_INVALID_DATE_FORMAT


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
            username="backtester",
            email="bt@test.com",
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
            username="other_bt",
            email="other_bt@test.com",
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


def _register_test_strategy():
    """Register a minimal test strategy for backtest tests."""
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
            return "Test strategy"

    StrategyRegistry.register("test_strategy", TestStrategy)


@pytest_asyncio.fixture
async def sample_metrics():
    return json.dumps({
        "total_return_percent": 15.5,
        "win_rate": 60.0,
        "max_drawdown_percent": 5.2,
        "sharpe_ratio": 1.5,
        "profit_factor": 2.0,
        "total_trades": 10,
        "winning_trades": 6,
        "losing_trades": 4,
        "average_win": 50.0,
        "average_loss": -25.0,
        "total_pnl": 150.0,
        "total_fees": 10.0,
        "starting_capital": 10000.0,
        "ending_capital": 11550.0,
    })


@pytest_asyncio.fixture
async def completed_run(session_factory, user, sample_metrics):
    """Insert a completed backtest run."""
    async with session_factory() as session:
        run = BacktestRun(
            user_id=user.id,
            strategy_type="test_strategy",
            symbol="BTCUSDT",
            timeframe="1d",
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 6, 1),
            initial_capital=10000.0,
            strategy_params=json.dumps({"test_param": 42}),
            status="completed",
            result_metrics=sample_metrics,
            equity_curve=json.dumps([{"timestamp": "2025-01-01", "equity": 10000.0}]),
            trades=json.dumps([{
                "entry_date": "2025-01-15",
                "exit_date": "2025-01-20",
                "direction": "long",
                "entry_price": 42000.0,
                "exit_price": 45000.0,
                "position_value": 1000.0,
                "pnl": 71.43,
                "pnl_percent": 7.14,
                "fees": 2.0,
                "net_pnl": 69.43,
                "result": "win",
                "reason": "Signal detected",
                "confidence": 80,
            }]),
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


@pytest_asyncio.fixture
async def other_user_run(session_factory, other_user):
    """A backtest run belonging to another user."""
    async with session_factory() as session:
        run = BacktestRun(
            user_id=other_user.id,
            strategy_type="test_strategy",
            symbol="ETHUSDT",
            timeframe="1h",
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 3, 1),
            initial_capital=5000.0,
            status="completed",
            created_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


@pytest_asyncio.fixture
async def pending_runs(session_factory, user):
    """Insert 3 pending/running backtest runs to test concurrent limit."""
    runs = []
    async with session_factory() as session:
        for i in range(3):
            run = BacktestRun(
                user_id=user.id,
                strategy_type="test_strategy",
                symbol="BTCUSDT",
                timeframe="1d",
                start_date=datetime(2025, 1, 1),
                end_date=datetime(2025, 6, 1),
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
async def app(session_factory):
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import backtest
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
    test_app.include_router(backtest.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# GET /api/backtest/strategies
# ---------------------------------------------------------------------------


async def test_list_strategies(client, auth_headers):
    """Lists available strategies including test_strategy."""
    resp = await client.get("/api/backtest/strategies", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "strategies" in data
    names = [s["name"] for s in data["strategies"]]
    assert "test_strategy" in names


async def test_list_strategies_requires_auth(client):
    """Listing strategies without auth returns 401."""
    resp = await client.get("/api/backtest/strategies")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/backtest/run
# ---------------------------------------------------------------------------


async def test_start_backtest_success(client, auth_headers, user):
    """Starting a backtest returns run_id and pending status."""
    with patch("src.api.routers.backtest._execute_backtest"):
        resp = await client.post(
            "/api/backtest/run",
            headers=auth_headers,
            json={
                "strategy_type": "test_strategy",
                "symbol": "BTCUSDT",
                "timeframe": "1d",
                "start_date": "2025-01-01",
                "end_date": "2025-06-01",
                "initial_capital": 10000.0,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "pending"


async def test_start_backtest_invalid_strategy(client, auth_headers, user):
    """Starting a backtest with an unknown strategy returns 400."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "nonexistent_strategy",
            "start_date": "2025-01-01",
            "end_date": "2025-06-01",
        },
    )
    assert resp.status_code == 400


async def test_start_backtest_invalid_dates(client, auth_headers, user):
    """Start date after end date returns 400."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "test_strategy",
            "start_date": "2025-06-01",
            "end_date": "2025-01-01",
        },
    )
    assert resp.status_code == 400
    assert ERR_END_BEFORE_START in resp.json()["detail"]


async def test_start_backtest_invalid_date_format(client, auth_headers, user):
    """Invalid date format returns 400."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "test_strategy",
            "start_date": "not-a-date",
            "end_date": "2025-06-01",
        },
    )
    assert resp.status_code == 400
    assert ERR_INVALID_DATE_FORMAT in resp.json()["detail"]


async def test_start_backtest_concurrent_limit(client, auth_headers, pending_runs):
    """Exceeding concurrent backtest limit returns 429."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "test_strategy",
            "start_date": "2025-01-01",
            "end_date": "2025-06-01",
        },
    )
    assert resp.status_code == 429
    assert "backtest" in resp.json()["detail"].lower() or "gleichzeitig" in resp.json()["detail"].lower()


async def test_start_backtest_requires_auth(client):
    """Starting a backtest without auth returns 401."""
    resp = await client.post(
        "/api/backtest/run",
        json={
            "strategy_type": "test_strategy",
            "start_date": "2025-01-01",
            "end_date": "2025-06-01",
        },
    )
    assert resp.status_code == 401


async def test_start_backtest_with_strategy_params(client, auth_headers, user):
    """Starting a backtest with strategy_params succeeds."""
    with patch("src.api.routers.backtest._execute_backtest"):
        resp = await client.post(
            "/api/backtest/run",
            headers=auth_headers,
            json={
                "strategy_type": "test_strategy",
                "start_date": "2025-01-01",
                "end_date": "2025-06-01",
                "strategy_params": {"test_param": 99},
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


async def test_start_backtest_same_start_end_date(client, auth_headers, user):
    """Same start and end date returns 400 (end must be after start)."""
    resp = await client.post(
        "/api/backtest/run",
        headers=auth_headers,
        json={
            "strategy_type": "test_strategy",
            "start_date": "2025-01-01",
            "end_date": "2025-01-01",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/backtest/history
# ---------------------------------------------------------------------------


async def test_list_history(client, auth_headers, completed_run):
    """History returns user's backtest runs."""
    resp = await client.get("/api/backtest/history", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["runs"]) >= 1
    assert data["page"] == 1


async def test_list_history_pagination(client, auth_headers, completed_run):
    """History supports pagination."""
    resp = await client.get(
        "/api/backtest/history",
        headers=auth_headers,
        params={"page": 1, "per_page": 1},
    )
    data = resp.json()
    assert data["per_page"] == 1
    assert len(data["runs"]) <= 1


async def test_list_history_empty(client, auth_headers, user):
    """History returns empty when no backtests exist."""
    resp = await client.get("/api/backtest/history", headers=auth_headers)
    data = resp.json()
    assert data["total"] == 0
    assert data["runs"] == []


async def test_list_history_user_isolation(client, auth_headers, completed_run, other_user_run):
    """User can only see their own backtest history."""
    resp = await client.get("/api/backtest/history", headers=auth_headers)
    data = resp.json()
    run_ids = [r["id"] for r in data["runs"]]
    assert completed_run.id in run_ids
    assert other_user_run.id not in run_ids


async def test_list_history_includes_metrics(client, auth_headers, completed_run):
    """Completed runs include metrics summary."""
    resp = await client.get("/api/backtest/history", headers=auth_headers)
    data = resp.json()
    run = data["runs"][0]
    assert run["total_return_percent"] is not None
    assert run["win_rate"] is not None
    assert run["total_trades"] is not None


async def test_list_history_requires_auth(client):
    """History without auth returns 401."""
    resp = await client.get("/api/backtest/history")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/backtest/{run_id}
# ---------------------------------------------------------------------------


async def test_get_run_completed(client, auth_headers, completed_run):
    """Get a completed backtest run with all details."""
    resp = await client.get(f"/api/backtest/{completed_run.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == completed_run.id
    assert data["status"] == "completed"
    assert data["metrics"] is not None
    assert data["equity_curve"] is not None
    assert data["trades"] is not None
    assert data["strategy_params"] == {"test_param": 42}


async def test_get_run_fields(client, auth_headers, completed_run):
    """Response includes all expected fields."""
    resp = await client.get(f"/api/backtest/{completed_run.id}", headers=auth_headers)
    data = resp.json()
    expected_fields = {
        "id", "strategy_type", "symbol", "timeframe", "start_date", "end_date",
        "initial_capital", "strategy_params", "status", "error_message",
        "metrics", "equity_curve", "trades", "created_at", "completed_at",
    }
    assert expected_fields.issubset(set(data.keys()))


async def test_get_run_not_found(client, auth_headers, user):
    """Getting a non-existent run returns 404."""
    resp = await client.get("/api/backtest/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_get_run_other_user_not_visible(client, auth_headers, other_user_run):
    """Cannot access another user's backtest run."""
    resp = await client.get(f"/api/backtest/{other_user_run.id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_get_run_requires_auth(client, completed_run):
    """Getting a run without auth returns 401."""
    resp = await client.get(f"/api/backtest/{completed_run.id}")
    assert resp.status_code == 401


async def test_get_run_pending_has_no_results(client, auth_headers, pending_runs):
    """Pending run has null metrics, equity_curve, and trades."""
    run = pending_runs[0]
    resp = await client.get(f"/api/backtest/{run.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["metrics"] is None
    assert data["equity_curve"] is None
    assert data["trades"] is None


# ---------------------------------------------------------------------------
# DELETE /api/backtest/{run_id}
# ---------------------------------------------------------------------------


async def test_delete_run_success(client, auth_headers, completed_run):
    """Delete a backtest run succeeds."""
    resp = await client.delete(f"/api/backtest/{completed_run.id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    # Verify it is actually deleted
    resp2 = await client.get(f"/api/backtest/{completed_run.id}", headers=auth_headers)
    assert resp2.status_code == 404


async def test_delete_run_not_found(client, auth_headers, user):
    """Deleting a non-existent run returns 404."""
    resp = await client.delete("/api/backtest/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_delete_run_other_user(client, auth_headers, other_user_run):
    """Cannot delete another user's backtest run."""
    resp = await client.delete(f"/api/backtest/{other_user_run.id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_delete_run_requires_auth(client, completed_run):
    """Deleting without auth returns 401."""
    resp = await client.delete(f"/api/backtest/{completed_run.id}")
    assert resp.status_code == 401
