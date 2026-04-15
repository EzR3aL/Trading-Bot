"""Verify the coordinator picks admin credentials from the DB (issue #181 follow-up)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
# Fernet key (32 url-safe base64 bytes) required by src.utils.encryption
os.environ["ENCRYPTION_KEY"] = "8P5tm7omM-7rNyRwE0VT2HQjZ08Q5Q-IgOyfTnf8_Ts="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, ExchangeConnection, User
from src.auth.password import hash_password
from src.utils.encryption import encrypt_value


@pytest_asyncio.fixture
async def engine_with_admin():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        admin = User(
            username="admin", email="a@b.c",
            password_hash=hash_password("x"), role="admin",
            is_active=True, language="en",
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)

        session.add_all([
            ExchangeConnection(
                user_id=admin.id, exchange_type="bitget",
                api_key_encrypted=encrypt_value("live-bitget-key"),
                api_secret_encrypted=encrypt_value("live-bitget-sec"),
                passphrase_encrypted=encrypt_value("live-bitget-pass"),
            ),
            ExchangeConnection(
                user_id=admin.id, exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value("0xADM1N1111111111111111111111111111111111"),
                api_secret_encrypted=encrypt_value("0x" + "ab" * 32),
            ),
        ])
        await session.commit()

    yield eng, factory
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.mark.asyncio
async def test_load_admin_credentials_returns_configured_exchanges(engine_with_admin):
    _eng, factory = engine_with_admin

    from src.services import affiliate_revenue_fetcher as fetcher
    with patch.object(fetcher, "get_session", return_value=_factory_context(factory)):
        creds = await fetcher._load_admin_credentials()

    assert set(creds.keys()) == {"bitget", "hyperliquid"}
    assert creds["bitget"].exchange_type == "bitget"


@pytest.mark.asyncio
async def test_build_adapter_injects_decrypted_credentials(engine_with_admin):
    _eng, factory = engine_with_admin
    from src.services import affiliate_revenue_fetcher as fetcher
    from src.services.affiliate.bitget_fetcher import BitgetAffiliateAdapter
    from src.services.affiliate.hyperliquid_fetcher import HyperliquidAffiliateAdapter

    with patch.object(fetcher, "get_session", return_value=_factory_context(factory)):
        creds = await fetcher._load_admin_credentials()

    bitget = fetcher._build_adapter("bitget", creds["bitget"])
    assert isinstance(bitget, BitgetAffiliateAdapter)
    assert bitget.api_key == "live-bitget-key"
    assert bitget.passphrase == "live-bitget-pass"

    hl = fetcher._build_adapter("hyperliquid", creds["hyperliquid"])
    assert isinstance(hl, HyperliquidAffiliateAdapter)
    assert hl.referrer_address.startswith("0xADM1N")


@pytest.mark.asyncio
async def test_build_adapter_returns_unconfigured_when_no_conn():
    from src.services import affiliate_revenue_fetcher as fetcher
    bitget = fetcher._build_adapter("bitget", None)
    assert bitget.api_key == ""

    # Bitunix stub does not require a conn
    bitunix = fetcher._build_adapter("bitunix", None)
    result = await bitunix.fetch(
        __import__("datetime").date.today(), __import__("datetime").date.today()
    )
    assert result.status == "unsupported"


def _factory_context(factory):
    """Wrap an AsyncSession factory into the same async-context shape as get_session()."""
    class _Ctx:
        async def __aenter__(self_inner):
            self_inner._s = factory()
            return await self_inner._s.__aenter__()

        async def __aexit__(self_inner, *args):
            return await self_inner._s.__aexit__(*args)

    return _Ctx()
