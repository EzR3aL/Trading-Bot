"""
Extra tests for dashboard/app.py to reach 95%+ coverage.

Covers:
- verify_ws_token with different auth methods
- WebSocket endpoint (accept, send, disconnect)
- Funding tracker exception in health check (lines 200-202)
- Funding tracker exception in detailed health (lines 511-514)
- run_dashboard function (lines 1694-1706)
- Dev mode warning logs (lines 58-61)
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

@dataclass
class MockDailyStats:
    date: str = "2025-01-01"
    starting_balance: float = 10000.0
    current_balance: float = 10150.0
    trades_executed: int = 2
    winning_trades: int = 1
    losing_trades: int = 1
    total_pnl: float = 200.0
    total_fees: float = 20.0
    total_funding: float = 30.0
    max_drawdown: float = 1.5
    is_trading_halted: bool = False
    halt_reason: str = ""

    @property
    def net_pnl(self) -> float:
        return self.total_pnl - self.total_fees - abs(self.total_funding)

    @property
    def win_rate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return (self.winning_trades / total) * 100 if total else 0.0

    @property
    def return_percent(self) -> float:
        if self.starting_balance == 0:
            return 0.0
        return (self.net_pnl / self.starting_balance) * 100

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "starting_balance": self.starting_balance,
            "current_balance": self.current_balance,
            "trades_executed": self.trades_executed,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "total_funding": self.total_funding,
            "net_pnl": self.net_pnl,
            "return_percent": self.return_percent,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "is_trading_halted": self.is_trading_halted,
            "halt_reason": self.halt_reason,
        }


class FailingTracker:
    """Object that raises when accessed via bool()."""
    def __bool__(self):
        raise RuntimeError("Tracker access failed")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.is_demo_mode = True
    s.trading.demo_mode = True
    s.trading.trading_pairs = ["BTCUSDT"]
    s.trading.leverage = 4
    s.trading.max_trades_per_day = 2
    s.trading.daily_loss_limit_percent = 5.0
    s.trading.position_size_percent = 7.5
    s.trading.take_profit_percent = 4.0
    s.trading.stop_loss_percent = 1.5
    s.strategy.fear_greed_extreme_fear = 20
    s.strategy.fear_greed_extreme_greed = 80
    s.strategy.long_short_crowded_longs = 2.5
    s.strategy.long_short_crowded_shorts = 0.4
    s.strategy.high_confidence_min = 85
    s.strategy.low_confidence_min = 60
    return s


@pytest.fixture
def mock_risk_manager():
    rm = MagicMock()
    rm.get_daily_stats.return_value = MockDailyStats()
    rm.can_trade.return_value = (True, "")
    rm.get_remaining_trades.return_value = 1
    rm.get_historical_stats.return_value = []
    return rm


@pytest.fixture
def mock_trade_db():
    db = AsyncMock()
    db.initialize = AsyncMock()
    db.get_statistics = AsyncMock(return_value={
        "total_trades": 10,
        "winning_trades": 6,
        "losing_trades": 4,
        "total_pnl": 150.0,
    })
    db.get_open_trades = AsyncMock(return_value=[])
    db.get_recent_trades = AsyncMock(return_value=[])
    db.get_trade = AsyncMock(return_value=None)
    return db


@pytest.fixture
def mock_funding_tracker():
    ft = AsyncMock()
    ft.get_funding_stats = AsyncMock(return_value=MagicMock(
        total_paid=5.0, total_received=2.0, net_funding=3.0,
        payment_count=10, avg_rate=0.0001, highest_rate=0.0005, lowest_rate=-0.0002
    ))
    ft.get_daily_funding_summary = AsyncMock(return_value=[])
    ft.get_recent_payments = AsyncMock(return_value=[])
    ft.get_funding_rate_history = AsyncMock(return_value=[])
    ft.get_trade_funding = AsyncMock(return_value=[])
    return ft


@pytest.fixture
def mock_tax_generator():
    tg = AsyncMock()
    tg.get_available_years = AsyncMock(return_value=[2025])
    tg.get_year_data = AsyncMock(return_value={"summary": {}, "trades": [], "monthly_breakdown": []})
    tg.generate_csv_content = AsyncMock(return_value="Date,Symbol,PnL\n")
    return tg


@pytest_asyncio.fixture
async def dashboard_app(
    mock_settings, mock_trade_db, mock_risk_manager,
    mock_funding_tracker, mock_tax_generator,
):
    with patch("src.dashboard.app.settings", mock_settings), \
         patch("src.dashboard.app.DASHBOARD_DEV_MODE", True), \
         patch("src.dashboard.app.DASHBOARD_API_KEY", ""), \
         patch("src.dashboard.app.WS_AUTH_ENABLED", False):
        from src.dashboard.app import create_app, limiter
        app = create_app()
        limiter.enabled = False
        app.state.trade_db = mock_trade_db
        app.state.risk_manager = mock_risk_manager
        app.state.funding_tracker = mock_funding_tracker
        app.state.tax_generator = mock_tax_generator
        app.state.websocket_clients = []
        yield app


@pytest_asyncio.fixture
async def client(dashboard_app):
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=dashboard_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helper for creating WebSocket test apps
# ---------------------------------------------------------------------------

def _make_ws_app(dev_mode=True, api_key="", ws_auth_enabled=False):
    """Helper to create a dashboard app with specific auth settings."""
    with patch("src.dashboard.app.settings") as mock_s, \
         patch("src.dashboard.app.DASHBOARD_DEV_MODE", dev_mode), \
         patch("src.dashboard.app.DASHBOARD_API_KEY", api_key), \
         patch("src.dashboard.app.WS_AUTH_ENABLED", ws_auth_enabled):
        mock_s.is_demo_mode = True
        from src.dashboard.app import create_app, limiter
        app = create_app()
        limiter.enabled = False

        mock_rm = MagicMock()
        mock_rm.get_daily_stats.return_value = MockDailyStats()
        mock_rm.can_trade.return_value = (True, "")
        mock_rm.get_remaining_trades.return_value = 1

        app.state.trade_db = None
        app.state.risk_manager = mock_rm
        app.state.funding_tracker = None
        app.state.tax_generator = None
        app.state.websocket_clients = []

        return app


# ---------------------------------------------------------------------------
# Tests: verify_ws_token (lines 541-564) via WebSocket endpoint
# ---------------------------------------------------------------------------

class TestVerifyWsToken:
    """Tests for verify_ws_token through the WebSocket endpoint."""

    def test_ws_dev_mode_bypasses_auth(self):
        """Dev mode allows WebSocket without token."""
        from starlette.testclient import TestClient
        app = _make_ws_app(dev_mode=True, api_key="secret", ws_auth_enabled=True)
        sync_client = TestClient(app)
        with patch("src.dashboard.app.circuit_registry") as mock_cr:
            mock_cr.get_all_statuses.return_value = {}
            with sync_client.websocket_connect("/ws") as ws:
                data = ws.receive_json()
                assert data["type"] == "status"

    def test_ws_no_auth_when_disabled(self):
        """WebSocket connects when auth is disabled."""
        from starlette.testclient import TestClient
        app = _make_ws_app(dev_mode=False, api_key="", ws_auth_enabled=False)
        sync_client = TestClient(app)
        with patch("src.dashboard.app.circuit_registry") as mock_cr:
            mock_cr.get_all_statuses.return_value = {}
            with sync_client.websocket_connect("/ws") as ws:
                data = ws.receive_json()
                assert data["type"] == "status"

    def test_ws_valid_query_token(self):
        """WebSocket connects with valid query parameter token."""
        from starlette.testclient import TestClient
        app = _make_ws_app(dev_mode=False, api_key="my-key", ws_auth_enabled=True)
        sync_client = TestClient(app)
        with patch("src.dashboard.app.circuit_registry") as mock_cr:
            mock_cr.get_all_statuses.return_value = {}
            with sync_client.websocket_connect("/ws?token=my-key") as ws:
                data = ws.receive_json()
                assert data["type"] == "status"

    def test_ws_valid_subprotocol_token(self):
        """WebSocket connects with valid subprotocol token."""
        from starlette.testclient import TestClient
        app = _make_ws_app(dev_mode=False, api_key="my-key", ws_auth_enabled=True)
        sync_client = TestClient(app)
        with patch("src.dashboard.app.circuit_registry") as mock_cr:
            mock_cr.get_all_statuses.return_value = {}
            with sync_client.websocket_connect(
                "/ws", subprotocols=["token.my-key"]
            ) as ws:
                data = ws.receive_json()
                assert data["type"] == "status"

    def test_ws_rejected_invalid_token(self):
        """WebSocket rejected with invalid token - receives close."""
        from starlette.testclient import TestClient
        # Patches must stay active during websocket_connect, not just create_app
        with patch("src.dashboard.app.DASHBOARD_DEV_MODE", False), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", "my-key"), \
             patch("src.dashboard.app.WS_AUTH_ENABLED", True), \
             patch("src.dashboard.app.settings") as mock_s:
            mock_s.is_demo_mode = True
            from src.dashboard.app import create_app, limiter
            app = create_app()
            limiter.enabled = False
            app.state.trade_db = None
            app.state.risk_manager = MagicMock()
            app.state.funding_tracker = None
            app.state.tax_generator = None
            app.state.websocket_clients = []
            sync_client = TestClient(app)
            try:
                with sync_client.websocket_connect("/ws?token=wrong-key") as ws:
                    ws.receive_json()
                    pytest.fail("Should not receive data on rejected WS")
            except Exception:
                pass  # Expected: connection refused or closed

    def test_ws_rejected_no_token(self):
        """WebSocket rejected when no token provided."""
        from starlette.testclient import TestClient
        with patch("src.dashboard.app.DASHBOARD_DEV_MODE", False), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", "my-key"), \
             patch("src.dashboard.app.WS_AUTH_ENABLED", True), \
             patch("src.dashboard.app.settings") as mock_s:
            mock_s.is_demo_mode = True
            from src.dashboard.app import create_app, limiter
            app = create_app()
            limiter.enabled = False
            app.state.trade_db = None
            app.state.risk_manager = MagicMock()
            app.state.funding_tracker = None
            app.state.tax_generator = None
            app.state.websocket_clients = []
            sync_client = TestClient(app)
            try:
                with sync_client.websocket_connect("/ws") as ws:
                    ws.receive_json()
                    pytest.fail("Should not receive data on rejected WS")
            except Exception:
                pass

    def test_ws_rejected_empty_token_prefix(self):
        """WebSocket rejected with empty token after 'token.' prefix."""
        from starlette.testclient import TestClient
        with patch("src.dashboard.app.DASHBOARD_DEV_MODE", False), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", "my-key"), \
             patch("src.dashboard.app.WS_AUTH_ENABLED", True), \
             patch("src.dashboard.app.settings") as mock_s:
            mock_s.is_demo_mode = True
            from src.dashboard.app import create_app, limiter
            app = create_app()
            limiter.enabled = False
            app.state.trade_db = None
            app.state.risk_manager = MagicMock()
            app.state.funding_tracker = None
            app.state.tax_generator = None
            app.state.websocket_clients = []
            sync_client = TestClient(app)
            try:
                with sync_client.websocket_connect("/ws", subprotocols=["token."]) as ws:
                    ws.receive_json()
                    pytest.fail("Should not receive data on rejected WS")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Tests: Funding tracker exception in health check (lines 200-202)
# ---------------------------------------------------------------------------

class TestFundingTrackerException:
    """Tests for funding tracker exception handling in health endpoints."""

    @pytest.mark.asyncio
    async def test_health_check_funding_tracker_exception(self, dashboard_app, client):
        """Health check handles funding tracker exception gracefully."""
        dashboard_app.state.funding_tracker = FailingTracker()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert "unhealthy" in data["components"]["funding_tracker"]

    @pytest.mark.asyncio
    async def test_detailed_health_funding_tracker_exception(self, dashboard_app, client):
        """Detailed health handles funding tracker exception gracefully."""
        dashboard_app.state.funding_tracker = FailingTracker()

        with patch("src.dashboard.app.circuit_registry") as mock_registry:
            mock_registry.get_all_statuses.return_value = {}

            response = await client.get("/api/health/detailed")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert "unhealthy" in data["components"]["funding_tracker"]
            assert any(e["component"] == "funding_tracker" for e in data["errors"])


# ---------------------------------------------------------------------------
# Tests: run_dashboard function (lines 1694-1706)
# ---------------------------------------------------------------------------

class TestRunDashboard:
    """Tests for the run_dashboard function."""

    def test_run_dashboard_default_localhost(self):
        """run_dashboard starts on localhost by default."""
        with patch("src.dashboard.app.settings"), \
             patch("src.dashboard.app.DASHBOARD_DEV_MODE", True), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", ""), \
             patch("src.dashboard.app.create_app") as mock_create, \
             patch("src.dashboard.app.uvicorn") as mock_uvicorn:
            mock_create.return_value = MagicMock()
            from src.dashboard.app import run_dashboard
            run_dashboard()
            mock_uvicorn.run.assert_called_once()
            call_kwargs = mock_uvicorn.run.call_args
            assert call_kwargs[1]["host"] == "127.0.0.1"
            assert call_kwargs[1]["port"] == 8080

    def test_run_dashboard_exposed_without_key_warns(self):
        """run_dashboard warns when exposed on 0.0.0.0 without API key."""
        with patch("src.dashboard.app.settings"), \
             patch("src.dashboard.app.DASHBOARD_DEV_MODE", True), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", ""), \
             patch("src.dashboard.app.create_app") as mock_create, \
             patch("src.dashboard.app.uvicorn") as _mock_uvicorn, \
             patch("src.dashboard.app.logger") as mock_logger:
            mock_create.return_value = MagicMock()
            from src.dashboard.app import run_dashboard
            run_dashboard(host="0.0.0.0")
            # Should log a warning about exposing without API key
            warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
            assert any("without API key" in str(c) for c in warning_calls)

    def test_run_dashboard_exposed_with_key_no_warn(self):
        """run_dashboard does not warn when exposed with API key configured."""
        with patch("src.dashboard.app.settings"), \
             patch("src.dashboard.app.DASHBOARD_DEV_MODE", False), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", "valid-key"), \
             patch("src.dashboard.app.create_app") as mock_create, \
             patch("src.dashboard.app.uvicorn") as _mock_uvicorn, \
             patch("src.dashboard.app.logger") as mock_logger:
            mock_create.return_value = MagicMock()
            from src.dashboard.app import run_dashboard
            run_dashboard(host="0.0.0.0")
            # Should not warn about missing API key
            warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
            assert not any("without API key" in str(c) for c in warning_calls)

    def test_run_dashboard_custom_port(self):
        """run_dashboard uses custom port."""
        with patch("src.dashboard.app.settings"), \
             patch("src.dashboard.app.DASHBOARD_DEV_MODE", True), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", ""), \
             patch("src.dashboard.app.create_app") as mock_create, \
             patch("src.dashboard.app.uvicorn") as mock_uvicorn:
            mock_create.return_value = MagicMock()
            from src.dashboard.app import run_dashboard
            run_dashboard(port=9090)
            call_kwargs = mock_uvicorn.run.call_args
            assert call_kwargs[1]["port"] == 9090
