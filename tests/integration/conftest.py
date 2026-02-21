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

import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_db():
    """Create a fresh test database for each test."""
    from src.models.database import Base

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def test_app(test_db, monkeypatch):
    """Create a test FastAPI app with test database.

    Monkeypatches ``src.models.session`` so that all application code
    (routers, dependencies, lifespan) uses the in-memory test engine
    rather than the real database.
    """
    import src.models.session as session_module
    from src.models.database import Base

    # Create a dedicated engine for the app (separate from the fixture session)
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Monkey-patch the session module so every import sees test resources
    monkeypatch.setattr(session_module, "engine", engine)
    monkeypatch.setattr(session_module, "async_session_factory", test_session_factory)
    monkeypatch.setattr(session_module, "DATABASE_URL", TEST_DATABASE_URL)

    from src.api.main_app import create_app
    from src.api.routers.auth import limiter

    app = create_app()

    # Disable rate limiting during integration tests
    limiter.enabled = False

    yield app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


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
        return response.json()["access_token"]
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
        return response.json()["access_token"]
    return None


def auth_header(token: str) -> dict:
    """Convenience helper to build an Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}
