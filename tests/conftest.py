"""
Pytest configuration and shared fixtures for API integration tests.

Sets up an in-memory SQLite database, test client, authenticated user,
and sample data fixtures for comprehensive API testing.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from dataclasses import dataclass
from typing import Optional

# Ensure JWT_SECRET_KEY is set BEFORE any src imports (jwt_handler exits without it)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, BotConfig, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token, create_refresh_token


# ---------------------------------------------------------------------------
# Event loop (session-scoped for async fixtures)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database engine / session fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async session bound to the test engine."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Mock orchestrator & bot_manager
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_orchestrator():
    """Create a mock BotOrchestrator."""
    orch = MagicMock()
    orch.get_bot_status = MagicMock(return_value=None)
    orch.is_running = MagicMock(return_value=False)
    orch.start_bot = AsyncMock(return_value=True)
    orch.stop_bot = AsyncMock(return_value=True)
    orch.restart_bot = AsyncMock(return_value=True)
    orch.stop_all_for_user = AsyncMock(return_value=0)
    orch.restore_on_startup = AsyncMock()
    orch.shutdown_all = AsyncMock()
    return orch




# ---------------------------------------------------------------------------
# FastAPI app + test client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def app(test_engine, mock_orchestrator):
    """Create a FastAPI application with test database and mocked services."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Override the get_db dependency
    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Import routers AFTER setting env vars
    from src.api.routers import bots as bots_router

    # Inject mocks into router globals
    bots_router.set_orchestrator(mock_orchestrator)

    # We must register a test strategy so bot creation works
    _register_test_strategy()

    # Build the app without lifespan (we handle DB init ourselves)
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from src.api.routers.auth import limiter
    from src.api.routers import (
        auth,
        bots,
        config,
        exchanges,
        funding,
        presets,
        statistics,
        status,
        tax_report,
        trades,
        users,
    )
    from src.models.session import get_db

    # Disable rate limiting for tests so login tests do not interfere
    limiter.enabled = False

    test_app = FastAPI(title="Test Trading Bot API")
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Include all routers
    test_app.include_router(status.router)
    test_app.include_router(auth.router)
    test_app.include_router(users.router)
    test_app.include_router(trades.router)
    test_app.include_router(statistics.router)
    test_app.include_router(funding.router)
    test_app.include_router(config.router)
    test_app.include_router(presets.router)
    test_app.include_router(exchanges.router)
    test_app.include_router(bots.router)
    test_app.include_router(tax_report.router)

    # Override dependency
    test_app.dependency_overrides[get_db] = override_get_db

    yield test_app

    # Cleanup
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test user & authentication
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_user(test_engine) -> User:
    """Create a test user in the database and return it."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        user = User(
            username="testuser",
            email="test@example.com",
            password_hash=hash_password("testpassword123"),
            role="admin",
            is_active=True,
            language="en",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def auth_headers(test_user) -> dict:
    """Return authorization headers with a valid JWT access token."""
    token_data = {"sub": str(test_user.id), "role": test_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def refresh_token_str(test_user) -> str:
    """Return a valid refresh token string."""
    token_data = {"sub": str(test_user.id), "role": test_user.role}
    return create_refresh_token(token_data)


# ---------------------------------------------------------------------------
# Sample trade data
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def sample_trades(test_engine, test_user) -> list:
    """Insert sample trade records and return them."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    now = datetime.utcnow()
    trades_data = [
        TradeRecord(
            user_id=test_user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Test trade 1",
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
            user_id=test_user.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            exit_price=3400.0,
            take_profit=3300.0,
            stop_loss=3600.0,
            leverage=4,
            confidence=80,
            reason="Test trade 2",
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
            user_id=test_user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.02,
            entry_price=94000.0,
            exit_price=93000.0,
            take_profit=96000.0,
            stop_loss=93000.0,
            leverage=4,
            confidence=60,
            reason="Test trade 3 - losing",
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
            user_id=test_user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95500.0,
            take_profit=97000.0,
            stop_loss=94500.0,
            leverage=4,
            confidence=70,
            reason="Test trade 4 - open",
            order_id="order_004",
            status="open",
            entry_time=now - timedelta(hours=2),
            exchange="bitget",
            demo_mode=True,
        ),
    ]

    async with session_factory() as session:
        session.add_all(trades_data)
        await session.commit()
        for t in trades_data:
            await session.refresh(t)

    return trades_data


# ---------------------------------------------------------------------------
# Sample bot configs
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def sample_bot_config(test_engine, test_user) -> BotConfig:
    """Insert a sample bot configuration and return it."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        config = BotConfig(
            user_id=test_user.id,
            name="Test Bot Alpha",
            description="A test bot for unit testing",
            strategy_type="test_strategy",
            exchange_type="bitget",
            mode="demo",
            trading_pairs=json.dumps(["BTCUSDT", "ETHUSDT"]),
            leverage=4,
            position_size_percent=7.5,
            max_trades_per_day=2,
            take_profit_percent=4.0,
            stop_loss_percent=1.5,
            daily_loss_limit_percent=5.0,
            is_enabled=False,
        )
        session.add(config)
        await session.commit()
        await session.refresh(config)
        return config


@pytest_asyncio.fixture
async def sample_bot_with_trades(test_engine, test_user, sample_bot_config) -> BotConfig:
    """Create trades linked to the sample bot config."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    now = datetime.utcnow()
    trades = [
        TradeRecord(
            user_id=test_user.id,
            bot_config_id=sample_bot_config.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Bot trade 1",
            order_id="bot_order_001",
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
            user_id=test_user.id,
            bot_config_id=sample_bot_config.id,
            symbol="BTCUSDT",
            side="short",
            size=0.01,
            entry_price=96000.0,
            exit_price=96500.0,
            take_profit=95000.0,
            stop_loss=97000.0,
            leverage=4,
            confidence=65,
            reason="Bot trade 2",
            order_id="bot_order_002",
            status="closed",
            pnl=-5.0,
            pnl_percent=-0.52,
            fees=0.3,
            funding_paid=0.05,
            entry_time=now - timedelta(days=3),
            exit_time=now - timedelta(days=2),
            exit_reason="STOP_LOSS",
            exchange="bitget",
            demo_mode=True,
        ),
    ]
    async with session_factory() as session:
        session.add_all(trades)
        await session.commit()
    return sample_bot_config


# ---------------------------------------------------------------------------
# Test strategy registration helper
# ---------------------------------------------------------------------------

def _register_test_strategy():
    """Register a minimal test strategy for bot CRUD tests."""
    from src.strategy.base import BaseStrategy, StrategyRegistry, TradeSignal

    # Only register once
    if "test_strategy" in StrategyRegistry._strategies:
        return

    class TestStrategy(BaseStrategy):
        async def generate_signal(self, symbol: str) -> TradeSignal:
            raise NotImplementedError("Test strategy does not generate signals")

        async def should_trade(self, signal) -> tuple:
            return False, "Test strategy never trades"

        @classmethod
        def get_param_schema(cls) -> dict:
            return {
                "test_param": {
                    "type": "int",
                    "label": "Test Parameter",
                    "description": "A test parameter",
                    "default": 42,
                }
            }

        @classmethod
        def get_description(cls) -> str:
            return "Test strategy for unit testing"

    StrategyRegistry.register("test_strategy", TestStrategy)


# ---------------------------------------------------------------------------
# Mock market metrics (kept from existing conftest for unit tests)
# ---------------------------------------------------------------------------

@dataclass
class MockMarketMetrics:
    """Mock MarketMetrics for testing."""
    fear_greed_index: int = 50
    fear_greed_classification: str = "Neutral"
    long_short_ratio: float = 1.0
    funding_rate_btc: float = 0.0001
    funding_rate_eth: float = 0.0001
    btc_24h_change_percent: float = 0.0
    eth_24h_change_percent: float = 0.0
    btc_price: float = 95000.0
    eth_price: float = 3500.0
    btc_open_interest: float = 100000.0
    eth_open_interest: float = 50000.0
    timestamp: datetime = None
    data_quality: Optional[dict] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self):
        return {
            "fear_greed_index": self.fear_greed_index,
            "fear_greed_classification": self.fear_greed_classification,
            "long_short_ratio": self.long_short_ratio,
            "funding_rate_btc": self.funding_rate_btc,
            "funding_rate_eth": self.funding_rate_eth,
            "btc_24h_change_percent": self.btc_24h_change_percent,
            "eth_24h_change_percent": self.eth_24h_change_percent,
            "btc_price": self.btc_price,
            "eth_price": self.eth_price,
            "btc_open_interest": self.btc_open_interest,
            "eth_open_interest": self.eth_open_interest,
            "timestamp": self.timestamp.isoformat(),
        }


@pytest.fixture
def mock_market_metrics():
    """Factory for creating mock market metrics."""
    def _create(**kwargs):
        return MockMarketMetrics(**kwargs)
    return _create


@pytest.fixture
def mock_data_fetcher(mock_market_metrics):
    """Create a mock data fetcher."""
    fetcher = AsyncMock()
    fetcher.fetch_all_metrics = AsyncMock(return_value=mock_market_metrics())
    fetcher._ensure_session = AsyncMock()
    fetcher.close = AsyncMock()
    return fetcher


@pytest.fixture
def neutral_metrics(mock_market_metrics):
    """Neutral market conditions."""
    return mock_market_metrics(
        fear_greed_index=50,
        long_short_ratio=1.0,
        funding_rate_btc=0.0001,
        btc_price=95000.0,
        btc_24h_change_percent=0.5,
    )


@pytest.fixture
def crowded_longs_extreme_greed(mock_market_metrics):
    """Crowded longs + extreme greed = Strong SHORT signal."""
    return mock_market_metrics(
        fear_greed_index=85,
        long_short_ratio=2.6,
        funding_rate_btc=0.001,
        btc_price=95000.0,
        btc_24h_change_percent=5.0,
    )


@pytest.fixture
def crowded_shorts_extreme_fear(mock_market_metrics):
    """Crowded shorts + extreme fear = Strong LONG signal."""
    return mock_market_metrics(
        fear_greed_index=15,
        long_short_ratio=0.3,
        funding_rate_btc=-0.0005,
        btc_price=85000.0,
        btc_24h_change_percent=-8.0,
    )


@pytest.fixture
def conflicting_signals(mock_market_metrics):
    """Leverage says SHORT, sentiment says LONG = Follow leverage."""
    return mock_market_metrics(
        fear_greed_index=15,
        long_short_ratio=2.7,
        funding_rate_btc=0.0001,
        btc_price=90000.0,
        btc_24h_change_percent=-2.0,
    )
