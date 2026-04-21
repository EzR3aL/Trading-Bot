"""Unit tests for :func:`src.bot.ws_credentials_provider` (#240).

Covers:
* Bitget happy path — decrypted credentials + demo_mode from BotConfig.
* Hyperliquid happy path — decrypted wallet address, mainnet=True.
* Missing ExchangeConnection row → ``None``.
* Missing credential columns → ``None``.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# A valid Fernet key for encrypt/decrypt round-trips in this test file.
# Must be set before importing ``src.utils.encryption``. The top-level
# ``tests/conftest.py`` sets a shorter placeholder — we overwrite it so
# Fernet accepts the key.
os.environ["ENCRYPTION_KEY"] = "Uv11dOPlX4DKMpavq_TfkTGG0IUrgx-0itY4mEmkHXo="

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.models.database import Base, BotConfig, ExchangeConnection, User
from src.utils.encryption import encrypt_value


# ── Fixtures ─────────────────────────────────────────────────────────


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
    await eng.dispose()


@pytest_asyncio.fixture
async def patch_get_session(monkeypatch, engine):
    """Swap ``get_session`` in the provider module with one using our engine."""
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _factory():
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # Patch the symbol the provider module has already bound. Using
    # ``monkeypatch.setattr`` on the module keeps the import-order clean.
    import src.bot.ws_credentials_provider as provider_mod

    monkeypatch.setattr(provider_mod, "get_session", _factory)
    return _factory


async def _make_user(engine) -> int:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        user = User(
            username="ws-creds",
            email="creds@example.com",
            password_hash="x",
            role="user",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _add_exchange_connection(
    engine,
    user_id: int,
    exchange: str,
    *,
    live: bool = True,
    demo: bool = False,
    passphrase: bool = False,
) -> None:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        conn = ExchangeConnection(
            user_id=user_id,
            exchange_type=exchange,
            api_key_encrypted=encrypt_value("live-key") if live else None,
            api_secret_encrypted=encrypt_value("live-secret") if live else None,
            passphrase_encrypted=encrypt_value("live-pass") if passphrase else None,
            demo_api_key_encrypted=encrypt_value("demo-key") if demo else None,
            demo_api_secret_encrypted=encrypt_value("demo-secret") if demo else None,
            demo_passphrase_encrypted=encrypt_value("demo-pass")
            if (demo and passphrase)
            else None,
        )
        session.add(conn)
        await session.commit()


async def _add_bot_config(
    engine, user_id: int, exchange: str, *, mode: str, is_enabled: bool = True,
) -> None:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        bot = BotConfig(
            user_id=user_id,
            name=f"{exchange}-{mode}",
            strategy_type="liquidation_hunter",
            exchange_type=exchange,
            mode=mode,
            is_enabled=is_enabled,
        )
        session.add(bot)
        await session.commit()


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bitget_happy_path_live_mode(engine, patch_get_session):
    """Live bot → live credentials + demo_mode=False."""
    from src.bot.ws_credentials_provider import ws_credentials_provider

    user_id = await _make_user(engine)
    await _add_exchange_connection(
        engine, user_id, "bitget", live=True, demo=True, passphrase=True,
    )
    await _add_bot_config(engine, user_id, "bitget", mode="live")

    creds = await ws_credentials_provider(user_id, "bitget")

    assert creds is not None
    assert creds["api_key"] == "live-key"
    assert creds["api_secret"] == "live-secret"
    assert creds["passphrase"] == "live-pass"
    assert creds["demo_mode"] is False


@pytest.mark.asyncio
async def test_bitget_happy_path_demo_mode(engine, patch_get_session):
    """Demo bot → demo credentials + demo_mode=True."""
    from src.bot.ws_credentials_provider import ws_credentials_provider

    user_id = await _make_user(engine)
    await _add_exchange_connection(
        engine, user_id, "bitget", live=True, demo=True, passphrase=True,
    )
    await _add_bot_config(engine, user_id, "bitget", mode="demo")

    creds = await ws_credentials_provider(user_id, "bitget")

    assert creds is not None
    assert creds["api_key"] == "demo-key"
    assert creds["api_secret"] == "demo-secret"
    assert creds["passphrase"] == "demo-pass"
    assert creds["demo_mode"] is True


@pytest.mark.asyncio
async def test_hyperliquid_happy_path(engine, patch_get_session):
    """HL returns the decrypted wallet + mainnet=True."""
    from src.bot.ws_credentials_provider import ws_credentials_provider

    user_id = await _make_user(engine)
    await _add_exchange_connection(engine, user_id, "hyperliquid", live=True)

    creds = await ws_credentials_provider(user_id, "hyperliquid")

    assert creds is not None
    assert creds["wallet_address"] == "live-key"
    assert creds["mainnet"] is True
    # Must NOT leak bitget-style fields.
    assert "api_secret" not in creds
    assert "passphrase" not in creds


@pytest.mark.asyncio
async def test_missing_connection_returns_none(engine, patch_get_session):
    """No ExchangeConnection row → None."""
    from src.bot.ws_credentials_provider import ws_credentials_provider

    user_id = await _make_user(engine)

    assert await ws_credentials_provider(user_id, "bitget") is None
    assert await ws_credentials_provider(user_id, "hyperliquid") is None


@pytest.mark.asyncio
async def test_missing_credentials_returns_none(engine, patch_get_session):
    """Row exists but live-credential columns are empty → None."""
    from src.bot.ws_credentials_provider import ws_credentials_provider

    user_id = await _make_user(engine)
    # Connection row with NO credentials at all.
    await _add_exchange_connection(
        engine, user_id, "bitget", live=False, demo=False, passphrase=False,
    )
    await _add_exchange_connection(
        engine, user_id, "hyperliquid", live=False, demo=False, passphrase=False,
    )

    assert await ws_credentials_provider(user_id, "bitget") is None
    assert await ws_credentials_provider(user_id, "hyperliquid") is None


@pytest.mark.asyncio
async def test_bitget_defaults_to_live_when_no_bot(engine, patch_get_session):
    """No enabled BotConfig → defaults to live credentials / demo_mode=False."""
    from src.bot.ws_credentials_provider import ws_credentials_provider

    user_id = await _make_user(engine)
    await _add_exchange_connection(
        engine, user_id, "bitget", live=True, demo=True, passphrase=True,
    )
    # Disabled bot must not flip mode to demo.
    await _add_bot_config(
        engine, user_id, "bitget", mode="demo", is_enabled=False,
    )

    creds = await ws_credentials_provider(user_id, "bitget")

    assert creds is not None
    assert creds["demo_mode"] is False
    assert creds["api_key"] == "live-key"


@pytest.mark.asyncio
async def test_unsupported_exchange_returns_none(engine, patch_get_session):
    """Exchange not in the supported set → None (keeps callers safe)."""
    from src.bot.ws_credentials_provider import ws_credentials_provider

    user_id = await _make_user(engine)
    await _add_exchange_connection(engine, user_id, "weex", live=True)

    assert await ws_credentials_provider(user_id, "weex") is None
