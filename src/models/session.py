"""
Async SQLAlchemy Engine and Session Factory.

Supports SQLite (default) and PostgreSQL (via DATABASE_URL env var).
"""

import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base

# Database URL - easily switch to PostgreSQL:
# DATABASE_URL = "postgresql+asyncpg://user:pass@host/db"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db")

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    # SQLite-specific: enable WAL mode for concurrency
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Create all tables. Call once at application startup."""
    async with engine.begin() as conn:
        # Enable WAL mode for SQLite
        if "sqlite" in DATABASE_URL:
            await conn.execute(
                __import__("sqlalchemy").text("PRAGMA journal_mode=WAL")
            )
            await conn.execute(
                __import__("sqlalchemy").text("PRAGMA busy_timeout=5000")
            )
        await conn.run_sync(Base.metadata.create_all)

        # Migration: add demo_mode column to existing tables
        if "sqlite" in DATABASE_URL:
            from sqlalchemy import text
            try:
                await conn.execute(
                    text("ALTER TABLE trade_records ADD COLUMN demo_mode BOOLEAN NOT NULL DEFAULT 0")
                )
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    from src.utils.logger import get_logger
                    get_logger(__name__).warning(f"Migration check: {e}")


async def close_db() -> None:
    """Dispose engine. Call at application shutdown."""
    await engine.dispose()


@asynccontextmanager
async def get_session():
    """Provide an async session with automatic commit/rollback."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncSession:
    """FastAPI dependency that provides a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
