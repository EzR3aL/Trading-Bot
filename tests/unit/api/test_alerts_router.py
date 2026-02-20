"""Tests for the alerts API router."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.models.database import Alert


@pytest_asyncio.fixture
async def sample_alert(test_engine, test_user):
    """Create a sample alert in the DB."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        alert = Alert(
            user_id=test_user.id,
            alert_type="price",
            category="price_above",
            symbol="BTCUSDT",
            threshold=100000.0,
            direction="above",
            cooldown_minutes=15,
            is_enabled=True,
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
        return alert


class TestAlertsCRUD:
    """Test alert CRUD operations."""

    @pytest.mark.asyncio
    async def test_list_alerts_empty(self, client, auth_headers, test_user):
        resp = await client.get("/api/alerts", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_price_alert(self, client, auth_headers, test_user):
        data = {
            "alert_type": "price",
            "category": "price_above",
            "symbol": "BTCUSDT",
            "threshold": 100000.0,
            "direction": "above",
            "cooldown_minutes": 30,
        }
        resp = await client.post("/api/alerts", json=data, headers=auth_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert body["alert_type"] == "price"
        assert body["symbol"] == "BTCUSDT"
        assert body["threshold"] == 100000.0
        assert body["direction"] == "above"
        assert body["is_enabled"] is True
        assert body["trigger_count"] == 0

    @pytest.mark.asyncio
    async def test_create_price_alert_requires_symbol(self, client, auth_headers, test_user):
        data = {
            "alert_type": "price",
            "category": "price_above",
            "threshold": 100000.0,
            "direction": "above",
        }
        resp = await client.post("/api/alerts", json=data, headers=auth_headers)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_portfolio_alert(self, client, auth_headers, test_user):
        data = {
            "alert_type": "portfolio",
            "category": "daily_loss",
            "threshold": 5.0,
        }
        resp = await client.post("/api/alerts", json=data, headers=auth_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert body["alert_type"] == "portfolio"
        assert body["category"] == "daily_loss"

    @pytest.mark.asyncio
    async def test_create_strategy_alert(self, client, auth_headers, test_user):
        data = {
            "alert_type": "strategy",
            "category": "consecutive_losses",
            "threshold": 3.0,
        }
        resp = await client.post("/api/alerts", json=data, headers=auth_headers)
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_get_alert(self, client, auth_headers, sample_alert):
        resp = await client.get(f"/api/alerts/{sample_alert.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == sample_alert.id

    @pytest.mark.asyncio
    async def test_get_alert_not_found(self, client, auth_headers, test_user):
        resp = await client.get("/api/alerts/99999", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_alert(self, client, auth_headers, sample_alert):
        resp = await client.put(
            f"/api/alerts/{sample_alert.id}",
            json={"threshold": 120000.0},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["threshold"] == 120000.0

    @pytest.mark.asyncio
    async def test_delete_alert(self, client, auth_headers, sample_alert):
        resp = await client.delete(f"/api/alerts/{sample_alert.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["detail"] == "deleted"

        # Verify gone
        resp2 = await client.get(f"/api/alerts/{sample_alert.id}", headers=auth_headers)
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_alert(self, client, auth_headers, sample_alert):
        # Initially enabled
        resp = await client.patch(
            f"/api/alerts/{sample_alert.id}/toggle", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is False

        # Toggle back
        resp2 = await client.patch(
            f"/api/alerts/{sample_alert.id}/toggle", headers=auth_headers
        )
        assert resp2.status_code == 200
        assert resp2.json()["is_enabled"] is True

    @pytest.mark.asyncio
    async def test_list_alerts_with_filter(self, client, auth_headers, test_user):
        # Create alerts of different types
        await client.post(
            "/api/alerts",
            json={"alert_type": "price", "category": "price_above", "symbol": "BTCUSDT", "threshold": 100000, "direction": "above"},
            headers=auth_headers,
        )
        await client.post(
            "/api/alerts",
            json={"alert_type": "portfolio", "category": "daily_loss", "threshold": 5.0},
            headers=auth_headers,
        )

        # Filter by type
        resp = await client.get("/api/alerts?alert_type=price", headers=auth_headers)
        assert resp.status_code == 200
        for alert in resp.json():
            assert alert["alert_type"] == "price"

    @pytest.mark.asyncio
    async def test_alert_history_empty(self, client, auth_headers, test_user):
        resp = await client.get("/api/alerts/history", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_unauthenticated_access(self, client):
        resp = await client.get("/api/alerts")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_threshold_must_be_positive(self, client, auth_headers, test_user):
        data = {
            "alert_type": "portfolio",
            "category": "daily_loss",
            "threshold": -1.0,
        }
        resp = await client.post("/api/alerts", json=data, headers=auth_headers)
        assert resp.status_code == 422
