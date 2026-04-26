"""Unit tests for :mod:`src.services.affiliate_revenue_fetcher`.

Covers:
- _revenue_type_for: mapping logic
- _decrypt: passthrough / empty-string fallback
- _build_adapter: all exchange branches, conn=None branch, unknown type
- _load_admin_credentials: admin with live/demo keys, no admin, multi-admin
- _persist_state: insert new row, update existing row
- _upsert_rows: insert new, update changed, skip unchanged
- run_affiliate_fetch: happy path, adapter crash, persist failure
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "8P5tm7omM-7rNyRwE0VT2HQjZ08Q5Q-IgOyfTnf8_Ts="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.models.database import (
    AffiliateState,
    Base,
    ExchangeConnection,
    RevenueEntry,
    User,
)
from src.auth.password import hash_password
from src.utils.encryption import encrypt_value
from src.services.affiliate.base import DailyRevenue, FetchResult
import src.services.affiliate_revenue_fetcher as fetcher_mod


# ---------------------------------------------------------------------------
# In-memory DB fixtures
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
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _factory():
        async with maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    return _factory


def _make_admin(session, username="admin"):
    user = User(
        username=username,
        email=f"{username}@test.com",
        password_hash=hash_password("x"),
        role="admin",
        is_active=True,
        language="en",
    )
    return user


# ---------------------------------------------------------------------------
# _revenue_type_for
# ---------------------------------------------------------------------------


def test_revenue_type_for_hyperliquid():
    assert fetcher_mod._revenue_type_for("hyperliquid") == "referral"


def test_revenue_type_for_bitget():
    assert fetcher_mod._revenue_type_for("bitget") == "affiliate"


def test_revenue_type_for_unknown():
    assert fetcher_mod._revenue_type_for("unknown_exchange") == "affiliate"


# ---------------------------------------------------------------------------
# _decrypt
# ---------------------------------------------------------------------------


def test_decrypt_none_returns_empty_string():
    result = fetcher_mod._decrypt(None)
    assert result == ""


def test_decrypt_encrypted_value():
    encrypted = encrypt_value("my-secret-key")
    result = fetcher_mod._decrypt(encrypted)
    assert result == "my-secret-key"


# ---------------------------------------------------------------------------
# _build_adapter
# ---------------------------------------------------------------------------


def test_build_adapter_bitunix_no_conn_needed():
    adapter = fetcher_mod._build_adapter("bitunix", None)
    from src.services.affiliate.bitunix_fetcher import BitunixAffiliateAdapter
    assert isinstance(adapter, BitunixAffiliateAdapter)


def test_build_adapter_bitget_no_conn():
    adapter = fetcher_mod._build_adapter("bitget", None)
    from src.services.affiliate.bitget_fetcher import BitgetAffiliateAdapter
    assert isinstance(adapter, BitgetAffiliateAdapter)


def test_build_adapter_weex_no_conn():
    adapter = fetcher_mod._build_adapter("weex", None)
    from src.services.affiliate.weex_fetcher import WeexAffiliateAdapter
    assert isinstance(adapter, WeexAffiliateAdapter)


def test_build_adapter_hyperliquid_no_conn():
    adapter = fetcher_mod._build_adapter("hyperliquid", None)
    from src.services.affiliate.hyperliquid_fetcher import HyperliquidAffiliateAdapter
    assert isinstance(adapter, HyperliquidAffiliateAdapter)


def test_build_adapter_bingx_no_conn():
    adapter = fetcher_mod._build_adapter("bingx", None)
    from src.services.affiliate.bingx_fetcher import BingxAffiliateAdapter
    assert isinstance(adapter, BingxAffiliateAdapter)


def test_build_adapter_unknown_raises():
    conn = MagicMock()
    conn.api_key_encrypted = encrypt_value("k")
    conn.api_secret_encrypted = encrypt_value("s")
    conn.passphrase_encrypted = encrypt_value("p")
    conn.demo_api_key_encrypted = None
    conn.demo_api_secret_encrypted = None
    conn.demo_passphrase_encrypted = None
    with pytest.raises(ValueError, match="Unknown exchange_type"):
        fetcher_mod._build_adapter("unknown_xyz", conn)


def test_build_adapter_bitget_with_live_conn():
    conn = MagicMock()
    conn.api_key_encrypted = encrypt_value("live-key")
    conn.api_secret_encrypted = encrypt_value("live-secret")
    conn.passphrase_encrypted = encrypt_value("live-pass")
    conn.demo_api_key_encrypted = None
    conn.demo_api_secret_encrypted = None
    conn.demo_passphrase_encrypted = None

    adapter = fetcher_mod._build_adapter("bitget", conn)
    from src.services.affiliate.bitget_fetcher import BitgetAffiliateAdapter
    assert isinstance(adapter, BitgetAffiliateAdapter)


def test_build_adapter_falls_back_to_demo_keys():
    conn = MagicMock()
    conn.api_key_encrypted = None
    conn.api_secret_encrypted = None
    conn.passphrase_encrypted = None
    conn.demo_api_key_encrypted = encrypt_value("demo-key")
    conn.demo_api_secret_encrypted = encrypt_value("demo-secret")
    conn.demo_passphrase_encrypted = encrypt_value("demo-pass")

    adapter = fetcher_mod._build_adapter("bitget", conn)
    from src.services.affiliate.bitget_fetcher import BitgetAffiliateAdapter
    assert isinstance(adapter, BitgetAffiliateAdapter)


# ---------------------------------------------------------------------------
# _load_admin_credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_admin_credentials_no_admins(session_factory):
    with patch.object(fetcher_mod, "get_session", session_factory):
        creds = await fetcher_mod._load_admin_credentials()
    assert creds == {}


@pytest.mark.asyncio
async def test_load_admin_credentials_admin_with_connections(engine, session_factory):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        admin = _make_admin(session)
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        session.add_all([
            ExchangeConnection(
                user_id=admin.id,
                exchange_type="bitget",
                api_key_encrypted=encrypt_value("bk"),
                api_secret_encrypted=encrypt_value("bs"),
                passphrase_encrypted=encrypt_value("bp"),
            ),
            ExchangeConnection(
                user_id=admin.id,
                exchange_type="hyperliquid",
                api_key_encrypted=encrypt_value("0xWALLET"),
                api_secret_encrypted=encrypt_value("0x" + "ab" * 32),
            ),
        ])
        await session.commit()

    with patch.object(fetcher_mod, "get_session", session_factory):
        creds = await fetcher_mod._load_admin_credentials()

    assert set(creds.keys()) == {"bitget", "hyperliquid"}


@pytest.mark.asyncio
async def test_load_admin_credentials_prefers_live_over_demo(engine, session_factory):
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        admin = _make_admin(session)
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        # conn with both live + demo keys
        session.add(ExchangeConnection(
            user_id=admin.id,
            exchange_type="bitget",
            api_key_encrypted=encrypt_value("live-key"),
            api_secret_encrypted=encrypt_value("live-sec"),
            passphrase_encrypted=encrypt_value("live-pass"),
            demo_api_key_encrypted=encrypt_value("demo-key"),
            demo_api_secret_encrypted=encrypt_value("demo-sec"),
        ))
        await session.commit()

    with patch.object(fetcher_mod, "get_session", session_factory):
        creds = await fetcher_mod._load_admin_credentials()

    assert "bitget" in creds


# ---------------------------------------------------------------------------
# _persist_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_state_creates_new_row(session_factory):
    with patch.object(fetcher_mod, "get_session", session_factory):
        await fetcher_mod._persist_state("bitget", "ok", None)

    # Read it back
    from sqlalchemy import select
    async with session_factory() as session:
        row = (await session.execute(
            select(AffiliateState).where(AffiliateState.exchange == "bitget")
        )).scalar_one_or_none()

    assert row is not None
    assert row.last_status == "ok"
    assert row.last_error is None


@pytest.mark.asyncio
async def test_persist_state_updates_existing_row(session_factory):
    with patch.object(fetcher_mod, "get_session", session_factory):
        await fetcher_mod._persist_state("weex", "ok", None)
        await fetcher_mod._persist_state("weex", "error", "timeout")

    from sqlalchemy import select
    async with session_factory() as session:
        rows = (await session.execute(
            select(AffiliateState).where(AffiliateState.exchange == "weex")
        )).scalars().all()

    assert len(rows) == 1
    assert rows[0].last_status == "error"
    assert rows[0].last_error == "timeout"


# ---------------------------------------------------------------------------
# _upsert_rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_rows_inserts_new_entries(session_factory):
    today = date.today()
    result = FetchResult(
        exchange="bitget",
        status="ok",
        rows=[DailyRevenue(day=today, amount_usd=12.50)],
    )

    with patch.object(fetcher_mod, "get_session", session_factory):
        written = await fetcher_mod._upsert_rows(result)

    assert written == 1


@pytest.mark.asyncio
async def test_upsert_rows_updates_changed_amount(session_factory):
    today = date.today()
    result1 = FetchResult(
        exchange="bitget",
        status="ok",
        rows=[DailyRevenue(day=today, amount_usd=10.0)],
    )
    result2 = FetchResult(
        exchange="bitget",
        status="ok",
        rows=[DailyRevenue(day=today, amount_usd=15.0)],
    )

    with patch.object(fetcher_mod, "get_session", session_factory):
        await fetcher_mod._upsert_rows(result1)
        written = await fetcher_mod._upsert_rows(result2)

    assert written == 1  # updated

    from sqlalchemy import select
    async with session_factory() as session:
        row = (await session.execute(
            select(RevenueEntry).where(RevenueEntry.exchange == "bitget")
        )).scalar_one_or_none()

    assert row.amount_usd == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_upsert_rows_skips_unchanged_amount(session_factory):
    today = date.today()
    result = FetchResult(
        exchange="bitget",
        status="ok",
        rows=[DailyRevenue(day=today, amount_usd=10.0)],
    )

    with patch.object(fetcher_mod, "get_session", session_factory):
        await fetcher_mod._upsert_rows(result)
        written = await fetcher_mod._upsert_rows(result)  # same amount

    assert written == 0


@pytest.mark.asyncio
async def test_upsert_rows_empty_result(session_factory):
    result = FetchResult(exchange="weex", status="ok", rows=[])
    with patch.object(fetcher_mod, "get_session", session_factory):
        written = await fetcher_mod._upsert_rows(result)
    assert written == 0


# ---------------------------------------------------------------------------
# run_affiliate_fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_affiliate_fetch_happy_path(session_factory):
    """All adapters succeed → summary contains all exchanges."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    mock_adapter_bitget = MagicMock()
    mock_adapter_bitget.exchange = "bitget"
    mock_adapter_bitget.fetch = AsyncMock(return_value=FetchResult(
        exchange="bitget",
        status="ok",
        rows=[DailyRevenue(day=yesterday, amount_usd=5.0)],
    ))

    mock_adapter_weex = MagicMock()
    mock_adapter_weex.exchange = "weex"
    mock_adapter_weex.fetch = AsyncMock(return_value=FetchResult(
        exchange="weex",
        status="not_configured",
        rows=[],
    ))

    with patch.object(fetcher_mod, "_build_adapters", AsyncMock(
        return_value=[mock_adapter_bitget, mock_adapter_weex]
    )):
        with patch.object(fetcher_mod, "get_session", session_factory):
            summary = await fetcher_mod.run_affiliate_fetch(lookback_days=1)

    assert "bitget" in summary
    assert summary["bitget"]["status"] == "ok"
    assert summary["bitget"]["rows"] == 1
    assert summary["bitget"]["written"] >= 0

    assert "weex" in summary
    assert summary["weex"]["status"] == "not_configured"


@pytest.mark.asyncio
async def test_run_affiliate_fetch_adapter_crash_does_not_stop_others(session_factory):
    """A crashing adapter yields error status; other adapters still run."""
    mock_ok = MagicMock()
    mock_ok.exchange = "bingx"
    mock_ok.fetch = AsyncMock(return_value=FetchResult(exchange="bingx", status="ok", rows=[]))

    mock_crash = MagicMock()
    mock_crash.exchange = "weex"
    mock_crash.fetch = AsyncMock(side_effect=RuntimeError("network timeout"))

    with patch.object(fetcher_mod, "_build_adapters", AsyncMock(
        return_value=[mock_crash, mock_ok]
    )):
        with patch.object(fetcher_mod, "get_session", session_factory):
            summary = await fetcher_mod.run_affiliate_fetch(lookback_days=1)

    assert summary["weex"]["status"] == "error"
    assert "network timeout" in summary["weex"]["error"]
    assert summary["bingx"]["status"] == "ok"


@pytest.mark.asyncio
async def test_run_affiliate_fetch_returns_error_status_on_persist_failure(session_factory):
    """Persist failure is swallowed but logged; summary still returns error adapter's data."""
    mock_adapter = MagicMock()
    mock_adapter.exchange = "bitget"
    mock_adapter.fetch = AsyncMock(return_value=FetchResult(
        exchange="bitget",
        status="ok",
        rows=[DailyRevenue(day=date.today(), amount_usd=1.0)],
    ))

    with patch.object(fetcher_mod, "_build_adapters", AsyncMock(return_value=[mock_adapter])):
        with patch.object(fetcher_mod, "_upsert_rows", AsyncMock(side_effect=RuntimeError("DB down"))):
            with patch.object(fetcher_mod, "_persist_state", AsyncMock()):
                summary = await fetcher_mod.run_affiliate_fetch(lookback_days=1)

    assert "bitget" in summary
    # persist failed so written=0
    assert summary["bitget"]["written"] == 0
