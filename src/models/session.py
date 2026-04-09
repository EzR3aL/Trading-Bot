"""
Async SQLAlchemy Engine and Session Factory.

Supports SQLite (default) and PostgreSQL (via DATABASE_URL env var).
PostgreSQL uses connection pooling optimized for 10k+ concurrent users.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.exceptions import DatabaseUnavailableError
from src.models.database import Base
from src.utils.circuit_breaker import CircuitBreaker, CircuitBreakerError

# Database URL - easily switch to PostgreSQL:
# DATABASE_URL = "postgresql+asyncpg://user:pass@host/db"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")


def _build_engine_kwargs() -> dict:
    """Build engine kwargs based on the database backend."""
    kwargs = {
        "echo": os.getenv("SQL_ECHO", "false").lower() == "true",
    }
    if _is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL connection pool settings
        kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "20"))
        kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "30"))
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "1800"))
        kwargs["pool_timeout"] = int(os.getenv("DB_POOL_TIMEOUT", "10"))
    return kwargs


engine = create_async_engine(DATABASE_URL, **_build_engine_kwargs())

# Set WAL mode and busy_timeout on EVERY new SQLite connection
if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=1000")
        cursor.close()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Create/migrate all tables. Call once at application startup.

    Strategy:
    - Fresh database: run ``alembic upgrade head`` to create schema
    - Existing database (pre-Alembic): stamp as ``head`` so future migrations apply
    - Existing database (with Alembic): run ``alembic upgrade head`` for pending migrations
    """
    from alembic import command as alembic_cmd
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig("alembic.ini")

    async with engine.begin() as conn:
        # Check whether the database already has tables (pre-Alembic legacy)
        has_tables = await conn.run_sync(
            lambda sync_conn: engine.dialect.has_table(sync_conn, "users")
        )

        # Check whether Alembic version table exists
        has_alembic = await conn.run_sync(
            lambda sync_conn: engine.dialect.has_table(sync_conn, "alembic_version")
        )

    if has_tables and not has_alembic:
        # Legacy database: ensure schema is up to date, then stamp
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        alembic_cmd.stamp(alembic_cfg, "head")
    else:
        # Fresh or already-migrated database — Alembic is the single migration system
        alembic_cmd.upgrade(alembic_cfg, "head")


async def close_db() -> None:
    """Dispose engine. Call at application shutdown."""
    await engine.dispose()


SESSION_ACQUIRE_TIMEOUT = int(os.getenv("DB_SESSION_TIMEOUT", "10"))
_SESSION_MAX_RETRIES = int(os.getenv("DB_SESSION_RETRIES", "3"))
_SESSION_RETRY_DELAY = float(os.getenv("DB_SESSION_RETRY_DELAY", "1.0"))

_db_breaker = CircuitBreaker(
    name="database",
    fail_threshold=3,
    reset_timeout=30.0,
)


async def _acquire_session() -> AsyncSession:
    """Acquire a database session with retry logic.

    Retries up to ``_SESSION_MAX_RETRIES`` times on pool-exhaustion
    (TimeoutError) with exponential backoff so that transient spikes
    don't cascade into unrecoverable failures.
    """
    from src.utils.logger import get_logger
    _log = get_logger(__name__)

    last_err: Exception | None = None
    for attempt in range(1, _SESSION_MAX_RETRIES + 1):
        try:
            session = await asyncio.wait_for(
                async_session_factory().__aenter__(),
                timeout=SESSION_ACQUIRE_TIMEOUT,
            )
            return session
        except asyncio.TimeoutError:
            last_err = TimeoutError(
                f"Could not acquire database session within {SESSION_ACQUIRE_TIMEOUT}s "
                "(connection pool may be exhausted)"
            )
            if attempt < _SESSION_MAX_RETRIES:
                delay = _SESSION_RETRY_DELAY * (2 ** (attempt - 1))
                _log.warning(
                    "DB session acquire timeout (attempt %d/%d), retrying in %.1fs",
                    attempt, _SESSION_MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            else:
                raise last_err
    # Unreachable but satisfies type checkers
    raise last_err  # type: ignore[misc]


@asynccontextmanager
async def get_session():
    """Provide an async session with automatic commit/rollback.

    Wraps session acquisition in a circuit breaker so that repeated
    database failures cause fast rejection instead of cascading timeouts.
    """
    try:
        session = await _db_breaker.call(_acquire_session)
    except CircuitBreakerError:
        raise DatabaseUnavailableError(
            "Database circuit breaker open \u2014 too many recent failures"
        )

    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.__aexit__(None, None, None)


async def get_db() -> AsyncSession:
    """FastAPI dependency that provides a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
