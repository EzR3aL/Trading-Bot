"""Tests for the default ExchangeClient.pre_start_checks behavior (#ARCH-H2).

The base implementation runs the exchange-agnostic affiliate-UID gate:
 - returns an empty list when no active ``AffiliateLink`` with
   ``uid_required=True`` exists for this exchange_name,
 - returns a failing ``GateCheckResult`` when a UID is required but the
   user's ``ExchangeConnection.affiliate_verified`` flag is not set,
 - fails open on unexpected errors (returns empty list).

Exchange-specific overrides (e.g. Hyperliquid) must call ``super()`` to
inherit this gate.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw=="
)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.base import ExchangeClient, GateCheckResult


class _StubExchangeClient(ExchangeClient):
    """Minimal concrete ExchangeClient for testing the default gate logic."""

    EXCHANGE_NAME = "stub"

    async def get_account_balance(self):  # pragma: no cover - unused
        raise NotImplementedError

    async def place_market_order(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def cancel_order(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def close_position(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def get_position(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def get_open_positions(self):  # pragma: no cover
        raise NotImplementedError

    async def set_leverage(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def get_ticker(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def get_funding_rate(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    async def close(self):  # pragma: no cover
        return None

    @property
    def exchange_name(self) -> str:
        return type(self).EXCHANGE_NAME

    @property
    def supports_demo(self) -> bool:
        return True


@pytest.fixture
def stub_client():
    return _StubExchangeClient(api_key="k", api_secret="s", demo_mode=True)


@pytest.mark.asyncio
async def test_default_pre_start_checks_without_db_returns_empty(stub_client):
    """No DB session -> nothing to check, returns empty list."""
    result = await stub_client.pre_start_checks(user_id=1, db=None)
    assert result == []


@pytest.mark.asyncio
async def test_default_pre_start_checks_no_uid_required_returns_empty(stub_client):
    """When no uid_required AffiliateLink exists, returns empty list."""
    db = AsyncMock()

    no_link_result = MagicMock()
    no_link_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=no_link_result)

    result = await stub_client.pre_start_checks(user_id=1, db=db)
    assert result == []


@pytest.mark.asyncio
async def test_default_pre_start_checks_unverified_blocks(stub_client):
    """Active uid_required link + unverified connection -> failing gate."""
    affiliate_link = MagicMock(uid_required=True, is_active=True)
    connection = MagicMock(affiliate_verified=False)

    link_row = MagicMock()
    link_row.scalar_one_or_none = MagicMock(return_value=affiliate_link)
    conn_row = MagicMock()
    conn_row.scalar_one_or_none = MagicMock(return_value=connection)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[link_row, conn_row])

    result = await stub_client.pre_start_checks(user_id=1, db=db)
    assert len(result) == 1
    gate = result[0]
    assert isinstance(gate, GateCheckResult)
    assert gate.ok is False
    assert gate.key == "affiliate_uid"
    assert "Affiliate UID" in gate.message


@pytest.mark.asyncio
async def test_default_pre_start_checks_verified_passes(stub_client):
    """Active uid_required link + verified connection -> empty list."""
    affiliate_link = MagicMock(uid_required=True, is_active=True)
    connection = MagicMock(affiliate_verified=True)

    link_row = MagicMock()
    link_row.scalar_one_or_none = MagicMock(return_value=affiliate_link)
    conn_row = MagicMock()
    conn_row.scalar_one_or_none = MagicMock(return_value=connection)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[link_row, conn_row])

    result = await stub_client.pre_start_checks(user_id=1, db=db)
    assert result == []


@pytest.mark.asyncio
async def test_default_pre_start_checks_fails_open_on_error(stub_client):
    """Unexpected DB/import errors must not block bot start."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=Exception("boom"))

    result = await stub_client.pre_start_checks(user_id=1, db=db)
    # Fails open: returns empty list, does not raise.
    assert result == []
