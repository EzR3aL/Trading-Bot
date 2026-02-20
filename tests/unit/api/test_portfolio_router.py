"""Tests for the portfolio API router."""

import pytest
import pytest_asyncio


class TestPortfolioSummary:
    """Test portfolio summary endpoint."""

    @pytest.mark.asyncio
    async def test_summary_empty(self, client, auth_headers, test_user):
        resp = await client.get("/api/portfolio/summary", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_pnl"] == 0
        assert body["total_trades"] == 0
        assert body["exchanges"] == []

    @pytest.mark.asyncio
    async def test_summary_with_trades(self, client, auth_headers, sample_trades):
        resp = await client.get("/api/portfolio/summary?days=30", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_trades"] > 0
        assert len(body["exchanges"]) > 0
        # All sample trades are on bitget
        assert body["exchanges"][0]["exchange"] == "bitget"

    @pytest.mark.asyncio
    async def test_summary_with_demo_filter(self, client, auth_headers, sample_trades):
        resp = await client.get(
            "/api/portfolio/summary?days=30&demo_mode=true", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        # Should only include demo trades
        assert body["total_trades"] >= 0

    @pytest.mark.asyncio
    async def test_summary_period_validation(self, client, auth_headers, test_user):
        resp = await client.get("/api/portfolio/summary?days=0", headers=auth_headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_summary_unauthenticated(self, client):
        resp = await client.get("/api/portfolio/summary")
        assert resp.status_code in (401, 403)


class TestPortfolioDaily:
    """Test portfolio daily breakdown endpoint."""

    @pytest.mark.asyncio
    async def test_daily_empty(self, client, auth_headers, test_user):
        resp = await client.get("/api/portfolio/daily", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_daily_with_trades(self, client, auth_headers, sample_trades):
        resp = await client.get("/api/portfolio/daily?days=30", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) > 0
        # Check structure
        for item in body:
            assert "date" in item
            assert "exchange" in item
            assert "pnl" in item
            assert "trades" in item


class TestPortfolioPositions:
    """Test portfolio positions endpoint."""

    @pytest.mark.asyncio
    async def test_positions_no_connections(self, client, auth_headers, test_user):
        resp = await client.get("/api/portfolio/positions", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []


class TestPortfolioAllocation:
    """Test portfolio allocation endpoint."""

    @pytest.mark.asyncio
    async def test_allocation_no_connections(self, client, auth_headers, test_user):
        resp = await client.get("/api/portfolio/allocation", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []
