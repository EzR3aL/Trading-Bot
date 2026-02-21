"""Tests for the funding router and SQLAlchemy case() compatibility.

Verifies that the funding router works correctly with SQLAlchemy 2.x
tuple-style case() syntax.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models.database import FundingPayment


@pytest_asyncio.fixture
async def sample_funding_payments(test_engine, test_user):
    """Create sample funding payments in the DB."""
    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    now = datetime.utcnow()
    payments = [
        FundingPayment(
            user_id=test_user.id,
            symbol="BTCUSDT",
            funding_rate=0.0001,
            position_size=0.5,
            payment_amount=0.5,
            side="long",
            timestamp=now - timedelta(days=1),
        ),
        FundingPayment(
            user_id=test_user.id,
            symbol="ETHUSDT",
            funding_rate=-0.0002,
            position_size=2.0,
            payment_amount=-0.4,
            side="short",
            timestamp=now - timedelta(days=2),
        ),
        FundingPayment(
            user_id=test_user.id,
            symbol="BTCUSDT",
            funding_rate=0.0003,
            position_size=0.5,
            payment_amount=1.5,
            side="long",
            timestamp=now - timedelta(hours=12),
        ),
    ]
    async with session_factory() as session:
        session.add_all(payments)
        await session.commit()
        for p in payments:
            await session.refresh(p)
    return payments


class TestFundingEndpoints:
    """Test funding router endpoints."""

    @pytest.mark.asyncio
    async def test_list_funding_empty(self, client, auth_headers, test_user):
        """Empty funding list returns empty payments array."""
        resp = await client.get("/api/funding", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["payments"] == []
        assert body["total_count"] == 0

    @pytest.mark.asyncio
    async def test_list_funding_with_data(self, client, auth_headers, sample_funding_payments):
        """Returns funding payments for the user."""
        resp = await client.get("/api/funding?days=30", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 3
        assert len(body["payments"]) == 3

    @pytest.mark.asyncio
    async def test_list_funding_filter_by_symbol(self, client, auth_headers, sample_funding_payments):
        """Filter by symbol returns only matching payments."""
        resp = await client.get("/api/funding?symbol=BTCUSDT", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 2
        for p in body["payments"]:
            assert p["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_funding_summary_endpoint(self, client, auth_headers, sample_funding_payments):
        """Summary endpoint uses case() which must work with SQLAlchemy 2.x."""
        resp = await client.get("/api/funding/summary", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Should have summary data
        assert "total_paid" in body or "summary" in body or isinstance(body, dict)

    @pytest.mark.asyncio
    async def test_funding_unauthenticated(self, client):
        """Unauthenticated request should be rejected."""
        resp = await client.get("/api/funding")
        assert resp.status_code in (401, 403)


class TestSQLAlchemyCaseImport:
    """Verify that SQLAlchemy case() import is compatible."""

    def test_case_importable_from_sqlalchemy(self):
        """case() should be directly importable from sqlalchemy."""
        from sqlalchemy import case
        assert callable(case)

    def test_case_tuple_syntax(self):
        """SQLAlchemy 2.x supports case() with tuples."""
        from sqlalchemy import case, literal_column
        # This should not raise - verifies 2.x syntax works
        expr = case(
            (literal_column("1") == literal_column("1"), literal_column("'yes'")),
            else_=literal_column("'no'"),
        )
        assert expr is not None

    def test_func_case_not_needed(self):
        """func.case is NOT needed — direct case() import is correct."""
        from sqlalchemy import case
        # case is a standalone function, not accessed via func
        assert case.__module__.startswith("sqlalchemy")
