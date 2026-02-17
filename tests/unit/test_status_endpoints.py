"""Tests for the health check and status endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.routers.status import router


@pytest.fixture
def app():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return app


class TestHealthCheck:
    """Tests for /api/health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_response_fields(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/health")
        data = resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "version" in data


class TestGetStatus:
    """Tests for /api/status endpoint."""

    @pytest.mark.asyncio
    async def test_status_returns_200(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/status")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_status_response_fields(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/status")
        data = resp.json()
        assert data["status"] == "running"
        assert data["features"]["multi_exchange"] is True
        assert data["features"]["multi_user"] is True
        assert data["features"]["config_presets"] is True
