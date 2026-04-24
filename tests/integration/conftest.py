"""
Integration test fixtures.

Requirements:
    - pytest-asyncio (for async test support with asyncio_mode=auto)
    - httpx (for AsyncClient / ASGITransport)
    - aiosqlite (for async SQLite in-memory test database)

NOTE: The create_app() lifespan also calls init_db() and seeds exchanges,
which will run against the monkeypatched session module. This is intentional
so that the test database is fully initialised just as production would be.
If the lifespan introduces side effects that interfere with tests (e.g.
BotManager), those may need additional mocking in the future.
"""

import os

# Prevent SPA catch-all from swallowing API requests during tests
os.environ["TESTING"] = "1"

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

# Use TEST_DATABASE_URL env var if set (e.g. PostgreSQL in CI), otherwise SQLite
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _engine_kwargs(is_sqlite: bool) -> dict:
    """Build engine kwargs that avoid keeping pooled connections between tests.

    * SQLite :memory: -> ``StaticPool`` so every session shares one connection
      (otherwise each new connection sees a fresh empty DB).
    * Postgres -> ``NullPool`` so each session opens + closes its own connection.
      Without this, every function-scoped test engine retains ``pool_size``
      connections until dispose, exhausting the postgres ``max_connections``
      limit when hundreds of tests run back-to-back in CI.
    """
    kwargs: dict = {}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        kwargs["poolclass"] = NullPool
    return kwargs


@pytest_asyncio.fixture
async def _integration_engine():
    """Shared engine for ``test_db`` and ``test_app`` in a single test.

    Previously each of those fixtures built its own engine, meaning tests
    that used both held two PG connection pools simultaneously. Under CI
    with the default ``max_connections=100`` that doubled the pressure
    and contributed to the #354 pool exhaustion. Sharing a single engine
    halves connection churn per integration test.
    """
    from src.models.database import Base

    is_sqlite = TEST_DATABASE_URL.startswith("sqlite")
    engine = create_async_engine(TEST_DATABASE_URL, **_engine_kwargs(is_sqlite))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        except Exception:
            # Loop may be tearing down — swallow so dispose still runs.
            pass
        await engine.dispose()


@pytest_asyncio.fixture
async def test_db(_integration_engine):
    """Provide an async session bound to the shared integration engine."""
    session_factory = async_sessionmaker(
        _integration_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_app(_integration_engine, monkeypatch):
    """Create a test FastAPI app that reuses the integration engine.

    Monkeypatches ``src.models.session`` so that all application code
    (routers, dependencies, lifespan) uses the test engine rather than
    the real database.
    """
    import src.models.session as session_module

    test_session_factory = async_sessionmaker(
        _integration_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Monkey-patch the session module so every import sees test resources
    monkeypatch.setattr(session_module, "engine", _integration_engine)
    monkeypatch.setattr(session_module, "async_session_factory", test_session_factory)
    monkeypatch.setattr(session_module, "DATABASE_URL", TEST_DATABASE_URL)

    from src.api.main_app import create_app
    from src.api.routers.auth import limiter

    app = create_app()

    # Disable rate limiting during integration tests
    limiter.enabled = False

    # Provide a mock orchestrator so endpoints that depend on it
    # do not return 503 "orchestrator not initialized".
    from unittest.mock import AsyncMock, MagicMock
    mock_orch = MagicMock()
    mock_orch.get_bot_status = MagicMock(return_value=None)
    mock_orch.is_running = MagicMock(return_value=False)
    mock_orch.start_bot = AsyncMock(return_value=True)
    mock_orch.stop_bot = AsyncMock(return_value=True)
    mock_orch.restart_bot = AsyncMock(return_value=True)
    mock_orch.stop_all_for_user = AsyncMock(return_value=0)
    app.state.orchestrator = mock_orch

    yield app


@pytest_asyncio.fixture
async def client(test_app):
    """HTTP client for testing API endpoints."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_token(client, test_db):
    """Create an admin user and return an auth token.

    Inserts the user directly via the session module (so it lands in the
    monkeypatched test database) then authenticates via the login endpoint.
    """
    from src.auth.password import hash_password
    from src.models.database import User
    from src.models.session import get_session

    async with get_session() as session:
        admin = User(
            username="admin",
            password_hash=hash_password("admin123456"),
            role="admin",
            is_active=True,
            language="en",
        )
        session.add(admin)

    response = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123456"},
    )
    if response.status_code == 200:
        # SEC-012: access_token is only in the httpOnly cookie, not the body.
        return response.cookies.get("access_token")
    return None


@pytest_asyncio.fixture
async def user_token(client, test_db):
    """Create a regular user and return an auth token."""
    from src.auth.password import hash_password
    from src.models.database import User
    from src.models.session import get_session

    async with get_session() as session:
        user = User(
            username="testuser",
            password_hash=hash_password("testpass123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(user)

    response = await client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "testpass123"},
    )
    if response.status_code == 200:
        # SEC-012: access_token is only in the httpOnly cookie, not the body.
        return response.cookies.get("access_token")
    return None


def auth_header(token: str) -> dict:
    """Convenience helper to build an Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}
