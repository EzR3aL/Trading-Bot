"""Unit tests for the periodic affiliate-UID retry job."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.services import affiliate_retry  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pending_row(user_id: int, exchange_type: str, uid: str):
    """Create a fake ExchangeConnection row (just an attr-bag)."""
    row = MagicMock()
    row.user_id = user_id
    row.exchange_type = exchange_type
    row.affiliate_uid = uid
    row.affiliate_verified = False
    row.affiliate_verified_at = None
    return row


def _patch_session_with_rows(rows):
    """Patch get_session and ``session.execute`` to yield ``rows``."""
    session = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    exec_result = MagicMock()
    exec_result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=exec_result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    @asynccontextmanager
    async def fake_get_session():
        yield session

    return patch.object(affiliate_retry, "get_session", fake_get_session), session


def _patch_admin_client(check_results):
    """Patch ``_build_admin_client`` to return a stub client.

    ``check_results`` is either a single value/Exception or a list applied
    in order via ``side_effect``.
    """
    client = MagicMock()
    if isinstance(check_results, list):
        client.check_affiliate_uid = AsyncMock(side_effect=check_results)
    else:
        client.check_affiliate_uid = AsyncMock(return_value=check_results)
    client.close = AsyncMock()
    return patch.object(
        affiliate_retry, "_build_admin_client", AsyncMock(return_value=client)
    ), client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_skips_when_no_admin_conn():
    row = _make_pending_row(1, "bitget", "uid-1")
    session_patch, _ = _patch_session_with_rows([row])

    with session_patch, patch.object(
        affiliate_retry, "get_admin_exchange_conn", AsyncMock(return_value=None)
    ):
        result = await affiliate_retry.retry_pending_verifications()

    assert row.affiliate_verified is False
    assert row.affiliate_verified_at is None
    assert "bitget" in result["skipped_no_admin_conn"]
    assert result["newly_verified"] == 0
    assert result["still_pending"] == 1
    assert result["checked"] == 0


@pytest.mark.asyncio
async def test_retry_promotes_pending_to_verified_when_api_says_yes():
    row = _make_pending_row(2, "bitget", "uid-yes")
    session_patch, _ = _patch_session_with_rows([row])
    admin_conn = MagicMock()
    client_patch, client = _patch_admin_client(True)

    before = datetime.now(timezone.utc)
    with session_patch, patch.object(
        affiliate_retry,
        "get_admin_exchange_conn",
        AsyncMock(return_value=admin_conn),
    ), client_patch:
        result = await affiliate_retry.retry_pending_verifications()

    assert row.affiliate_verified is True
    assert row.affiliate_verified_at is not None
    assert row.affiliate_verified_at >= before
    assert result["newly_verified"] == 1
    assert result["checked"] == 1
    assert result["still_pending"] == 0
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_leaves_row_pending_when_api_says_no():
    row = _make_pending_row(3, "bitget", "uid-no")
    session_patch, _ = _patch_session_with_rows([row])
    admin_conn = MagicMock()
    client_patch, _ = _patch_admin_client(False)

    with session_patch, patch.object(
        affiliate_retry,
        "get_admin_exchange_conn",
        AsyncMock(return_value=admin_conn),
    ), client_patch:
        result = await affiliate_retry.retry_pending_verifications()

    assert row.affiliate_verified is False
    assert row.affiliate_verified_at is None
    assert result["newly_verified"] == 0
    assert result["checked"] == 1
    assert result["still_pending"] == 1


@pytest.mark.asyncio
async def test_retry_handles_per_row_exception_and_continues():
    row_bad = _make_pending_row(4, "bitget", "uid-boom")
    row_good = _make_pending_row(5, "bitget", "uid-ok")
    session_patch, _ = _patch_session_with_rows([row_bad, row_good])
    admin_conn = MagicMock()
    client_patch, _ = _patch_admin_client([RuntimeError("api blew up"), True])

    with session_patch, patch.object(
        affiliate_retry,
        "get_admin_exchange_conn",
        AsyncMock(return_value=admin_conn),
    ), client_patch:
        result = await affiliate_retry.retry_pending_verifications()

    assert row_bad.affiliate_verified is False
    assert row_good.affiliate_verified is True
    assert row_good.affiliate_verified_at is not None
    assert result["checked"] == 2
    assert result["newly_verified"] == 1
    assert result["still_pending"] == 1
