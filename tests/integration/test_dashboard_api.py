"""
Integration tests for Dashboard API endpoints.

Tests cover:
- Authentication requirements
- Input validation
- Rate limiting
- Response formats
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture
def mock_components():
    """Create mocked database and risk manager components."""
    with patch('src.dashboard.app.TradeDatabase') as mock_db, \
         patch('src.dashboard.app.RiskManager') as mock_rm, \
         patch('src.dashboard.app.FundingTracker') as mock_ft:

        # Mock database
        db_instance = AsyncMock()
        db_instance.initialize = AsyncMock()
        db_instance.get_statistics = AsyncMock(return_value={})
        db_instance.get_recent_trades = AsyncMock(return_value=[])
        db_instance.get_open_trades = AsyncMock(return_value=[])
        db_instance.get_trade = AsyncMock(return_value=None)
        mock_db.return_value = db_instance

        # Mock risk manager
        rm_instance = MagicMock()
        rm_instance.get_daily_stats.return_value = MagicMock(
            to_dict=lambda: {
                "date": "2024-01-01",
                "net_pnl": 100.0,
                "win_rate": 50.0,
                "trades_executed": 1,
            }
        )
        rm_instance.can_trade.return_value = (True, "OK")
        rm_instance.get_remaining_trades.return_value = 2
        rm_instance.get_historical_stats.return_value = []
        mock_rm.return_value = rm_instance

        # Mock funding tracker
        ft_instance = AsyncMock()
        ft_instance.initialize = AsyncMock()
        ft_instance.close = AsyncMock()
        ft_instance.get_funding_stats = AsyncMock(return_value=MagicMock(
            total_paid=10.0,
            total_received=5.0,
            net_funding=5.0,
            payment_count=2,
            avg_rate=0.0001,
            highest_rate=0.0002,
            lowest_rate=0.00005,
        ))
        ft_instance.get_daily_funding_summary = AsyncMock(return_value=[])
        ft_instance.get_recent_payments = AsyncMock(return_value=[])
        ft_instance.get_trade_funding = AsyncMock(return_value=[])
        ft_instance.get_funding_rate_history = AsyncMock(return_value=[])
        mock_ft.return_value = ft_instance

        yield {
            "db": db_instance,
            "rm": rm_instance,
            "ft": ft_instance,
        }


@pytest.fixture
def client(mock_components):
    """Create test client with mocked components."""
    from src.dashboard.app import create_app

    app = create_app()
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Return headers with API key."""
    return {"X-API-Key": "test-api-key"}


class TestHealthEndpoint:
    """Tests for /api/health endpoint (no auth required)."""

    def test_health_check_returns_200(self, client):
        """Health check should return 200 and health status."""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "components" in data
        assert "version" in data


class TestAuthenticatedEndpoints:
    """Tests for endpoints requiring authentication."""

    def test_status_without_auth_in_dev_mode(self, client):
        """Status should work without auth in dev mode (no API key set)."""
        # In dev mode (no DASHBOARD_API_KEY), auth is disabled
        response = client.get("/api/status")

        # Should work because no API key is configured
        assert response.status_code == 200

    def test_trades_endpoint_returns_trades(self, client):
        """Trades endpoint should return trade list."""
        response = client.get("/api/trades")

        assert response.status_code == 200
        data = response.json()
        assert "trades" in data
        assert "count" in data

    def test_statistics_endpoint(self, client):
        """Statistics endpoint should return stats."""
        response = client.get("/api/statistics")

        assert response.status_code == 200
        data = response.json()
        assert "period_days" in data
        assert "trade_stats" in data

    def test_funding_endpoint(self, client):
        """Funding endpoint should return funding data."""
        response = client.get("/api/funding")

        assert response.status_code == 200
        data = response.json()
        assert "stats" in data
        assert "daily_summary" in data

    def test_config_endpoint(self, client):
        """Config endpoint should return configuration."""
        response = client.get("/api/config")

        assert response.status_code == 200
        data = response.json()
        assert "trading" in data
        assert "strategy" in data


class TestInputValidation:
    """Tests for input validation on query parameters."""

    def test_trades_limit_validation(self, client):
        """Limit parameter should be validated."""
        # Valid limit
        response = client.get("/api/trades?limit=50")
        assert response.status_code == 200

        # Too high limit should fail
        response = client.get("/api/trades?limit=1000")
        assert response.status_code == 422  # Validation error

        # Negative limit should fail
        response = client.get("/api/trades?limit=-1")
        assert response.status_code == 422

    def test_statistics_days_validation(self, client):
        """Days parameter should be validated."""
        # Valid days
        response = client.get("/api/statistics?days=30")
        assert response.status_code == 200

        # Too many days should fail
        response = client.get("/api/statistics?days=500")
        assert response.status_code == 422

        # Zero days should fail
        response = client.get("/api/statistics?days=0")
        assert response.status_code == 422

    def test_trades_status_validation(self, client):
        """Status parameter should only accept valid values."""
        # Valid status
        response = client.get("/api/trades?status=open")
        assert response.status_code == 200

        response = client.get("/api/trades?status=closed")
        assert response.status_code == 200

        # Invalid status should fail
        response = client.get("/api/trades?status=invalid")
        assert response.status_code == 422


class TestModeToggle:
    """Tests for trading mode toggle endpoint."""

    def test_mode_toggle_changes_mode(self, client):
        """Toggle should change trading mode."""
        # Get initial mode
        response = client.get("/api/mode")
        initial_mode = response.json()["mode"]

        # Toggle
        response = client.post("/api/mode/toggle")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["mode"] != initial_mode

    def test_mode_toggle_returns_new_mode(self, client):
        """Toggle should return the new mode in response."""
        response = client.post("/api/mode/toggle")

        data = response.json()
        assert "mode" in data
        assert data["mode"] in ["demo", "live"]


class TestTradeNotFound:
    """Tests for trade not found scenarios."""

    def test_get_nonexistent_trade(self, client):
        """Getting non-existent trade should return 404."""
        response = client.get("/api/trades/99999")

        assert response.status_code == 404


class TestResponseFormats:
    """Tests for response format consistency."""

    def test_status_response_format(self, client):
        """Status response should have expected structure."""
        response = client.get("/api/status")
        data = response.json()

        assert "status" in data
        assert "timestamp" in data
        assert "demo_mode" in data
        assert "config" in data
        assert "daily_stats" in data
        assert "can_trade" in data
        assert "remaining_trades" in data

    def test_funding_response_format(self, client):
        """Funding response should have expected structure."""
        response = client.get("/api/funding")
        data = response.json()

        assert "stats" in data
        stats = data["stats"]
        assert "total_paid" in stats
        assert "total_received" in stats
        assert "net_funding" in stats
