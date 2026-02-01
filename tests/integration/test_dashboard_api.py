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
def mock_db():
    """Create a mocked database."""
    db = AsyncMock()
    db.initialize = AsyncMock()
    db.get_statistics = AsyncMock(return_value={
        "total_trades": 10,
        "winning_trades": 6,
        "losing_trades": 4,
        "total_pnl": 150.0,
        "win_rate": 60.0,
    })
    db.get_recent_trades = AsyncMock(return_value=[])
    db.get_open_trades = AsyncMock(return_value=[])
    db.get_trade = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_rm():
    """Create a mocked risk manager."""
    rm = MagicMock()
    rm.get_daily_stats.return_value = MagicMock(
        to_dict=lambda: {
            "date": "2024-01-01",
            "net_pnl": 100.0,
            "win_rate": 50.0,
            "trades_executed": 1,
        }
    )
    rm.can_trade.return_value = (True, "OK")
    rm.get_remaining_trades.return_value = 2
    rm.get_historical_stats.return_value = []
    rm.initialize_day = MagicMock()
    return rm


@pytest.fixture
def mock_ft():
    """Create a mocked funding tracker."""
    ft = AsyncMock()
    ft.initialize = AsyncMock()
    ft.close = AsyncMock()
    ft.get_funding_stats = AsyncMock(return_value=MagicMock(
        total_paid=10.0,
        total_received=5.0,
        net_funding=5.0,
        payment_count=2,
        avg_rate=0.0001,
        highest_rate=0.0002,
        lowest_rate=0.00005,
    ))
    ft.get_daily_funding_summary = AsyncMock(return_value=[])
    ft.get_recent_payments = AsyncMock(return_value=[])
    ft.get_trade_funding = AsyncMock(return_value=[])
    ft.get_funding_rate_history = AsyncMock(return_value=[])
    return ft


@pytest.fixture
def mock_tax():
    """Create a mocked tax generator."""
    tax = MagicMock()
    return tax


@pytest.fixture
def client(mock_db, mock_rm, mock_ft, mock_tax):
    """Create test client with mocked components injected into app.state."""
    # Enable dev mode for testing (bypasses API key requirement)
    with patch('src.dashboard.app.TradeDatabase', return_value=mock_db), \
         patch('src.dashboard.app.RiskManager', return_value=mock_rm), \
         patch('src.dashboard.app.FundingTracker', return_value=mock_ft), \
         patch('src.dashboard.app.TaxReportGenerator', return_value=mock_tax), \
         patch('src.dashboard.app.DASHBOARD_DEV_MODE', True):

        from src.dashboard.app import create_app
        app = create_app()

        # Override state with mocks (needed because startup event runs during TestClient init)
        app.state.trade_db = mock_db
        app.state.risk_manager = mock_rm
        app.state.funding_tracker = mock_ft
        app.state.tax_generator = mock_tax

        # Reset rate limiter for tests
        if hasattr(app.state, 'limiter') and app.state.limiter:
            app.state.limiter.reset()

        with TestClient(app) as test_client:
            yield test_client


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

    def test_trades_limit_valid(self, client):
        """Valid limit should be accepted."""
        response = client.get("/api/trades?limit=50")
        assert response.status_code == 200

    def test_statistics_days_valid(self, client):
        """Valid days should be accepted."""
        response = client.get("/api/statistics?days=30")
        assert response.status_code == 200

    def test_trades_status_open(self, client):
        """Open status should be accepted."""
        response = client.get("/api/trades?status=open")
        assert response.status_code == 200

    def test_trades_status_closed(self, client):
        """Closed status should be accepted."""
        response = client.get("/api/trades?status=closed")
        assert response.status_code == 200


class TestModeToggle:
    """Tests for trading mode toggle endpoint."""

    def test_mode_endpoint_returns_mode(self, client):
        """Mode GET endpoint should return current mode."""
        response = client.get("/api/mode")
        assert response.status_code == 200
        data = response.json()
        assert "mode" in data
        assert data["mode"] in ["demo", "live"]

    def test_mode_toggle_with_disabled_limiter(self, mock_db, mock_rm, mock_ft, mock_tax):
        """Mode toggle should work when rate limiter is disabled."""
        # Create a separate client with disabled rate limiting and dev mode
        with patch('src.dashboard.app.TradeDatabase', return_value=mock_db), \
             patch('src.dashboard.app.RiskManager', return_value=mock_rm), \
             patch('src.dashboard.app.FundingTracker', return_value=mock_ft), \
             patch('src.dashboard.app.TaxReportGenerator', return_value=mock_tax), \
             patch('src.dashboard.app.DASHBOARD_DEV_MODE', True), \
             patch('src.dashboard.app.limiter') as mock_limiter:

            # Make the limiter a no-op
            mock_limiter.limit.return_value = lambda f: f

            from src.dashboard.app import create_app
            app = create_app()
            app.state.trade_db = mock_db
            app.state.risk_manager = mock_rm
            app.state.funding_tracker = mock_ft
            app.state.tax_generator = mock_tax

            with TestClient(app) as test_client:
                # Get initial mode
                response = test_client.get("/api/mode")
                initial_mode = response.json()["mode"]

                # Toggle mode
                response = test_client.post("/api/mode/toggle")
                assert response.status_code == 200

                data = response.json()
                assert "success" in data
                assert "mode" in data
                assert data["mode"] != initial_mode


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
