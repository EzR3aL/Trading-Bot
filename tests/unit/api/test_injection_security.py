"""
Input injection security tests.

Verifies that malicious inputs (SQL injection, XSS, SSRF attempts)
are safely handled by the API schemas and database layer.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from src.models.database import Base, User
from src.auth.password import hash_password
from src.api.schemas.bots import BotConfigCreate, BotConfigUpdate
from src.api.schemas.user import UserCreate
from src.api.schemas.config import ApiKeysUpdate

# Disable rate limiter
from src.api.routers.auth import limiter
limiter.enabled = False

from src.api.routers.bots import (  # noqa: E402
    create_bot,
    update_bot,
)


# ---------------------------------------------------------------------------
# Fixtures (same pattern as bots_router_extra)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def factory(engine):
    from contextlib import asynccontextmanager
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _factory():
        async with sm() as session:
            yield session
    return _factory


@pytest_asyncio.fixture
async def admin_user(engine):
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as session:
        user = User(
            username="secadmin", password_hash=hash_password("testpass123"),
            role="admin", language="en", is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
def mock_request():
    scope = {"type": "http", "method": "POST", "path": "/api/bots", "headers": []}
    return Request(scope)


@pytest.fixture
def mock_orchestrator():
    mock_orch = MagicMock()
    mock_orch.is_running.return_value = False
    mock_orch.get_bot_count_for_user.return_value = 0
    mock_orch.stop_all_for_user = AsyncMock(return_value=0)
    return mock_orch


# SQL injection payloads
SQL_INJECTIONS = [
    "'; DROP TABLE users; --",
    "1 OR 1=1",
    "' UNION SELECT * FROM users --",
    "'; UPDATE users SET role='admin' WHERE '1'='1",
    "Robert'); DROP TABLE bots;--",
    "1; EXEC xp_cmdshell('dir')",
]

# XSS payloads
XSS_PAYLOADS = [
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",
    '<a href="javascript:void(0)" onclick="alert(1)">click</a>',
    "{{7*7}}",
    "${7*7}",
]

# Path traversal payloads
PATH_TRAVERSALS = [
    "../../../etc/passwd",
    "..\\..\\..\\windows\\system32\\config\\sam",
    "/etc/shadow",
    "....//....//etc/passwd",
]


# ---------------------------------------------------------------------------
# SQL Injection Tests
# ---------------------------------------------------------------------------


class TestSQLInjection:

    async def test_bot_name_sql_injection(self, factory, admin_user, mock_request):
        """SQL injection in bot name is safely stored as literal string."""
        for payload in SQL_INJECTIONS:
            async with factory() as session:
                body = BotConfigCreate(
                    name=payload[:100],
                    strategy_type="edge_indicator",
                    exchange_type="bitget",
                )
                result = await create_bot(
                    request=mock_request, body=body, user=admin_user, db=session,
                )
                await session.commit()
            assert result.name == payload[:100]

    async def test_bot_description_sql_injection(self, factory, admin_user, mock_request, mock_orchestrator):
        """SQL injection in description is safely stored."""
        async with factory() as session:
            body = BotConfigCreate(
                name="SafeBot",
                strategy_type="edge_indicator",
                exchange_type="bitget",
            )
            result = await create_bot(
                request=mock_request, body=body, user=admin_user, db=session,
            )
            await session.commit()

        async with factory() as session:
            update = BotConfigUpdate(description="'; DROP TABLE bots; --")
            result = await update_bot(
                request=mock_request, bot_id=result.id, body=update,
                user=admin_user, db=session, orchestrator=mock_orchestrator,
            )
            await session.commit()
        assert "DROP TABLE" in result.description

    async def test_sql_injection_does_not_corrupt_db(self, factory, admin_user, mock_request):
        """Create bots with injection payloads and verify DB integrity."""
        # Create a couple of injection-named bots
        for payload in SQL_INJECTIONS[:3]:
            async with factory() as session:
                body = BotConfigCreate(
                    name=payload[:100],
                    strategy_type="edge_indicator",
                    exchange_type="bitget",
                )
                await create_bot(
                    request=mock_request, body=body, user=admin_user, db=session,
                )
                await session.commit()

        # Verify tables are intact
        async with factory() as session:
            result = await session.execute(
                select(User).where(User.username == "secadmin")
            )
            assert result.scalar_one_or_none() is not None

            result = await session.execute(text("SELECT count(*) FROM bot_configs"))
            count = result.scalar()
            assert count >= 3


# ---------------------------------------------------------------------------
# XSS Tests
# ---------------------------------------------------------------------------


class TestXSSPrevention:

    async def test_bot_name_xss_stored_literally(self, factory, admin_user, mock_request):
        """XSS payloads in bot name are stored as literal text (not executed)."""
        for payload in XSS_PAYLOADS:
            async with factory() as session:
                body = BotConfigCreate(
                    name=payload[:100],
                    strategy_type="edge_indicator",
                    exchange_type="bitget",
                )
                result = await create_bot(
                    request=mock_request, body=body, user=admin_user, db=session,
                )
                await session.commit()
            # Stored as literal string, not interpreted
            assert result.name == payload[:100]

    async def test_strategy_params_xss(self, factory, admin_user, mock_request):
        """XSS in strategy_params dict values stored as data."""
        async with factory() as session:
            body = BotConfigCreate(
                name="XSS Params Bot",
                strategy_type="edge_indicator",
                exchange_type="bitget",
                strategy_params={"key": "<script>alert(1)</script>"},
            )
            result = await create_bot(
                request=mock_request, body=body, user=admin_user, db=session,
            )
            await session.commit()
        assert result.strategy_params["key"] == "<script>alert(1)</script>"


# ---------------------------------------------------------------------------
# Schema Validation as Defense
# ---------------------------------------------------------------------------


class TestSchemaDefense:

    def test_exchange_type_rejects_injection(self):
        """exchange_type regex blocks arbitrary strings."""
        with pytest.raises(ValidationError):
            BotConfigCreate(
                name="Bot", strategy_type="d",
                exchange_type="'; DROP TABLE users;--",
            )

    def test_mode_rejects_injection(self):
        """mode regex blocks arbitrary strings."""
        with pytest.raises(ValidationError):
            BotConfigCreate(
                name="Bot", strategy_type="d", exchange_type="bitget",
                mode="'; DROP TABLE users;--",
            )

    def test_api_keys_exchange_rejects_injection(self):
        """ApiKeysUpdate exchange_type pattern blocks injection."""
        with pytest.raises(ValidationError):
            ApiKeysUpdate(exchange_type="' OR 1=1 --")

    def test_user_role_rejects_injection(self):
        """UserCreate role pattern blocks arbitrary strings."""
        with pytest.raises(ValidationError):
            UserCreate(username="user", password="Test@1234", role="admin' OR '1'='1")

    def test_schedule_type_rejects_injection(self):
        """schedule_type pattern blocks injection."""
        with pytest.raises(ValidationError):
            BotConfigCreate(
                name="Bot", strategy_type="d", exchange_type="bitget",
                schedule_type="'; DROP TABLE;--",
            )


# ---------------------------------------------------------------------------
# Oversized Input Tests
# ---------------------------------------------------------------------------


class TestOversizedInputs:

    def test_extremely_long_bot_name(self):
        """Names beyond max_length are rejected."""
        with pytest.raises(ValidationError):
            BotConfigCreate(name="A" * 10000, strategy_type="d", exchange_type="bitget")

    def test_extremely_long_username(self):
        with pytest.raises(ValidationError):
            UserCreate(username="A" * 10000, password="Test@1234")

    def test_extremely_long_password(self):
        with pytest.raises(ValidationError):
            UserCreate(username="user", password="A" * 10000)

    def test_large_trading_pairs_list_rejected(self):
        """Trading pairs list exceeding max_length=20 is rejected."""
        pairs = [f"TOKEN{i}USDT" for i in range(100)]
        with pytest.raises(ValidationError):
            BotConfigCreate(
                name="Many Pairs Bot",
                strategy_type="edge_indicator",
                exchange_type="bitget",
                trading_pairs=pairs,
            )

    async def test_max_trading_pairs_list_accepted(self, factory, admin_user, mock_request, monkeypatch):
        """Trading pairs list within max_length=20 is accepted."""
        from unittest.mock import AsyncMock
        pairs = [f"TOKEN{i}USDT" for i in range(20)]
        monkeypatch.setattr(
            "src.services.bots_service.get_exchange_symbols",
            AsyncMock(return_value=pairs),
        )
        async with factory() as session:
            body = BotConfigCreate(
                name="Many Pairs Bot",
                strategy_type="edge_indicator",
                exchange_type="bitget",
                trading_pairs=pairs,
            )
            result = await create_bot(
                request=mock_request, body=body, user=admin_user, db=session,
            )
            await session.commit()
        assert len(result.trading_pairs) == 20

    async def test_large_strategy_params(self, factory, admin_user, mock_request):
        """Large strategy params dict doesn't crash."""
        params = {f"param_{i}": i * 0.1 for i in range(200)}
        async with factory() as session:
            body = BotConfigCreate(
                name="Large Params Bot",
                strategy_type="edge_indicator",
                exchange_type="bitget",
                strategy_params=params,
            )
            result = await create_bot(
                request=mock_request, body=body, user=admin_user, db=session,
            )
            await session.commit()
        assert len(result.strategy_params) == 200


# ---------------------------------------------------------------------------
# Unicode / Special Characters
# ---------------------------------------------------------------------------


class TestUnicodeInputs:

    async def test_unicode_bot_name(self, factory, admin_user, mock_request):
        """Unicode characters in bot name are handled correctly."""
        names = [
            "BTC Bot",
            "Bot mit Umlauten: äöüß",
            "日本語ボット",
            "Бот на русском",
            "🚀 Rocket Bot",
        ]
        for name in names:
            async with factory() as session:
                body = BotConfigCreate(
                    name=name[:100],
                    strategy_type="edge_indicator",
                    exchange_type="bitget",
                )
                result = await create_bot(
                    request=mock_request, body=body, user=admin_user, db=session,
                )
                await session.commit()
            assert result.name == name[:100]

    def test_null_bytes_in_name(self):
        """Null bytes are handled (Pydantic may accept, DB layer handles)."""
        # Pydantic accepts null bytes in strings; this is a defense-in-depth check
        bot = BotConfigCreate(
            name="Bot\x00Injected",
            strategy_type="test",
            exchange_type="bitget",
        )
        assert "Bot" in bot.name
