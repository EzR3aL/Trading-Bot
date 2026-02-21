"""
Targeted tests for backtest.py _execute_backtest background worker (lines 103-142).

Covers:
- Successful backtest execution
- Backtest run not found (line 113-114)
- Backtest failure with exception (lines 138-142)
- Strategy params None vs JSON (line 120)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, BacktestRun, User
from src.auth.password import hash_password


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
            username="btuser",
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
async def pending_run(session_factory, user):
    """A backtest run in pending state with no strategy_params."""
    async with session_factory() as session:
        run = BacktestRun(
            user_id=user.id,
            strategy_type="sentiment_surfer",
            symbol="BTCUSDT",
            timeframe="1d",
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 6, 1),
            initial_capital=10000.0,
            strategy_params=None,
            status="pending",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


@pytest_asyncio.fixture
async def pending_run_with_params(session_factory, user):
    """A backtest run in pending state with strategy_params."""
    async with session_factory() as session:
        run = BacktestRun(
            user_id=user.id,
            strategy_type="degen",
            symbol="ETHUSDT",
            timeframe="4h",
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 3, 1),
            initial_capital=5000.0,
            strategy_params=json.dumps({"custom_prompt": "Be aggressive"}),
            status="pending",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_backtest_success(session_factory, pending_run):
    """_execute_backtest completes successfully and stores results."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    mock_result = {
        "metrics": {"total_return_percent": 15.5, "win_rate": 60.0, "total_trades": 10},
        "equity_curve": [{"timestamp": "2025-01-01", "equity": 10000}],
        "trades": [{"entry_date": "2025-01-05", "exit_date": "2025-01-10", "pnl": 100}],
    }

    with patch("src.api.routers.backtest.get_session", mock_get_session), \
         patch("src.backtest.strategy_adapter.run_backtest_for_strategy", new_callable=AsyncMock, return_value=mock_result):
        from src.api.routers.backtest import _execute_backtest
        await _execute_backtest(pending_run.id)

    # Verify the run was updated
    async with session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(select(BacktestRun).where(BacktestRun.id == pending_run.id))
        run = result.scalar_one()
        assert run.status == "completed"
        assert run.completed_at is not None
        assert json.loads(run.result_metrics)["total_return_percent"] == 15.5
        assert len(json.loads(run.equity_curve)) == 1
        assert len(json.loads(run.trades)) == 1


@pytest.mark.asyncio
async def test_execute_backtest_with_strategy_params(session_factory, pending_run_with_params):
    """_execute_backtest correctly parses strategy_params JSON."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    captured_params = {}

    async def mock_run_backtest(**kwargs):
        captured_params.update(kwargs)
        return {
            "metrics": {"total_return_percent": 10.0},
            "equity_curve": [],
            "trades": [],
        }

    with patch("src.api.routers.backtest.get_session", mock_get_session), \
         patch("src.backtest.strategy_adapter.run_backtest_for_strategy", side_effect=mock_run_backtest):
        from src.api.routers.backtest import _execute_backtest
        await _execute_backtest(pending_run_with_params.id)

    assert captured_params["strategy_params"] == {"custom_prompt": "Be aggressive"}


@pytest.mark.asyncio
async def test_execute_backtest_run_not_found(session_factory):
    """_execute_backtest returns early when run_id does not exist."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    with patch("src.api.routers.backtest.get_session", mock_get_session):
        from src.api.routers.backtest import _execute_backtest
        # Should not raise - just logs and returns
        await _execute_backtest(99999)


@pytest.mark.asyncio
async def test_execute_backtest_failure(session_factory, pending_run):
    """_execute_backtest handles backtest failure and marks run as failed."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_get_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    with patch("src.api.routers.backtest.get_session", mock_get_session), \
         patch("src.backtest.strategy_adapter.run_backtest_for_strategy",
               new_callable=AsyncMock, side_effect=RuntimeError("Data fetch failed")):
        from src.api.routers.backtest import _execute_backtest
        await _execute_backtest(pending_run.id)

    # Verify the run was marked as failed
    async with session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(select(BacktestRun).where(BacktestRun.id == pending_run.id))
        run = result.scalar_one()
        assert run.status == "failed"
        assert "Data fetch failed" in run.error_message
        assert run.completed_at is not None
