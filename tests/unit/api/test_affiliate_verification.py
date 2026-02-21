"""Tests for the affiliate UID verification endpoint."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.database import AffiliateLink, ExchangeConnection


@pytest_asyncio.fixture
async def sample_affiliate_link(test_engine, test_user):
    """Create an active affiliate link for bitget."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        link = AffiliateLink(
            exchange_type="bitget",
            affiliate_url="https://www.bitget.com/ref/12345",
            label="Bitget Referral",
            is_active=True,
            uid_required=True,
        )
        session.add(link)
        await session.commit()
        await session.refresh(link)
        return link


class TestVerifyUID:
    """Test POST /api/affiliate-links/verify-uid."""

    @pytest.mark.asyncio
    async def test_verify_bitget_uid_numeric(self, client, auth_headers, test_user):
        """Valid numeric Bitget UID should be accepted."""
        resp = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "bitget", "uid": "12345678"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["affiliate_verified"] is True
        assert body["exchange_type"] == "bitget"
        assert body["uid"] == "12345678"

    @pytest.mark.asyncio
    async def test_verify_bitget_uid_non_numeric_rejected(self, client, auth_headers, test_user):
        """Non-numeric Bitget UID should be rejected with 422."""
        resp = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "bitget", "uid": "abc123"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "numeric" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_verify_weex_uid_alphanumeric(self, client, auth_headers, test_user):
        """Valid alphanumeric Weex UID should be accepted."""
        resp = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "weex", "uid": "ABC123xyz"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["affiliate_verified"] is True
        assert body["exchange_type"] == "weex"

    @pytest.mark.asyncio
    async def test_verify_weex_uid_special_chars_rejected(self, client, auth_headers, test_user):
        """Weex UID with special characters should be rejected."""
        resp = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "weex", "uid": "abc!@#"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "alphanumeric" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_verify_empty_uid_rejected(self, client, auth_headers, test_user):
        """Empty UID should be rejected."""
        resp = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "bitget", "uid": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_invalid_exchange_rejected(self, client, auth_headers, test_user):
        """Invalid exchange type should be rejected."""
        resp = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "binance", "uid": "123"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_uid_updates_existing_connection(self, client, auth_headers, test_user, test_engine):
        """Verifying a UID for an existing connection updates it."""
        # First verification
        resp1 = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "bitget", "uid": "111"},
            headers=auth_headers,
        )
        assert resp1.status_code == 200

        # Second verification with new UID
        resp2 = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "bitget", "uid": "222"},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert resp2.json()["uid"] == "222"

    @pytest.mark.asyncio
    async def test_verify_uid_unauthenticated(self, client):
        """Unauthenticated request should fail."""
        resp = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "bitget", "uid": "123"},
        )
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_hyperliquid_uid_no_format_validation(self, client, auth_headers, test_user):
        """Hyperliquid has no UID format validator, any non-empty string passes."""
        resp = await client.post(
            "/api/affiliate-links/verify-uid",
            json={"exchange_type": "hyperliquid", "uid": "0xABCDEF123456"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["affiliate_verified"] is True
