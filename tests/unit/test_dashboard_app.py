"""
Unit tests for the Dashboard FastAPI application (src/dashboard/app.py).

Tests cover:
- trade_to_dict helper function
- get_default_html helper function
- verify_api_key dependency (dev mode, valid key, invalid key, missing config)
- Health check endpoint (healthy, degraded)
- Status endpoint
- Mode toggle and get endpoints
- Trades endpoints (list, open filter, single trade, not found)
- Statistics endpoint
- Funding endpoint and funding history
- Daily performance endpoint
- Config endpoint
- Tax report endpoints (years, year data, CSV download)
- Detailed health endpoint (including circuit breaker states)
- WebSocket token verification
- Index page (template exists / fallback)
- Error handling paths
"""

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Mock helpers and dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MockDailyStats:
    """Minimal DailyStats stand-in for testing."""
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


class MockTradeStatus:
    """Minimal enum-like status."""
    def __init__(self, value):
        self.value = value


@dataclass
class MockTrade:
    """Minimal Trade stand-in for testing."""
    id: int = 1
    symbol: str = "BTCUSDT"
    side: str = "long"
    size: float = 0.01
    entry_price: float = 95000.0
    exit_price: Optional[float] = 96000.0
    take_profit: float = 97000.0
    stop_loss: float = 94000.0
    leverage: int = 4
    confidence: int = 75
    reason: str = "Test trade"
    status: object = None
    pnl: Optional[float] = 10.0
    pnl_percent: Optional[float] = 1.05
    fees: Optional[float] = 0.5
    funding_paid: Optional[float] = 0.1
    entry_time: datetime = None
    exit_time: Optional[str] = None

    def __post_init__(self):
        if self.status is None:
            self.status = MockTradeStatus("open")
        if self.entry_time is None:
            self.entry_time = datetime(2025, 6, 1, 12, 0, 0)


@dataclass
class MockFundingPayment:
    """Minimal FundingPayment stand-in."""
    id: int = 1
    symbol: str = "BTCUSDT"
    timestamp: datetime = None
    funding_rate: float = 0.0001
    position_size: float = 0.01
    position_value: float = 950.0
    payment_amount: float = 0.095
    side: str = "long"
    trade_id: Optional[int] = 1

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime(2025, 6, 1, 8, 0, 0)

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "funding_rate": self.funding_rate,
            "position_size": self.position_size,
            "position_value": self.position_value,
            "payment_amount": self.payment_amount,
            "side": self.side,
            "trade_id": self.trade_id,
        }


@dataclass
class MockFundingStats:
    """Minimal FundingStats stand-in."""
    total_paid: float = 5.0
    total_received: float = 2.0
    net_funding: float = 3.0
    payment_count: int = 10
    avg_rate: float = 0.0001
    highest_rate: float = 0.0005
    lowest_rate: float = -0.0002


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_settings():
    """Create a mock settings object matching the real Settings dataclass."""
    s = MagicMock()
    s.is_demo_mode = True
    s.trading.demo_mode = True
    s.trading.trading_pairs = ["BTCUSDT", "ETHUSDT"]
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
def mock_trade_db():
    """Create a mock TradeDatabase."""
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
def mock_risk_manager():
    """Create a mock RiskManager."""
    rm = MagicMock()
    rm.get_daily_stats.return_value = MockDailyStats()
    rm.can_trade.return_value = (True, "")
    rm.get_remaining_trades.return_value = 1
    rm.get_historical_stats.return_value = [
        {"date": "2025-01-01", "net_pnl": 50.0},
        {"date": "2025-01-02", "net_pnl": -20.0},
    ]
    return rm


@pytest.fixture
def mock_funding_tracker():
    """Create a mock FundingTracker."""
    ft = AsyncMock()
    ft.initialize = AsyncMock()
    ft.close = AsyncMock()
    ft.get_funding_stats = AsyncMock(return_value=MockFundingStats())
    ft.get_daily_funding_summary = AsyncMock(return_value=[
        {"date": "2025-01-01", "total": -1.5},
        {"date": "2025-01-02", "total": 0.5},
    ])
    ft.get_recent_payments = AsyncMock(return_value=[MockFundingPayment()])
    ft.get_funding_rate_history = AsyncMock(return_value=[
        {"timestamp": "2025-01-01T08:00:00", "rate": 0.0001},
    ])
    ft.get_trade_funding = AsyncMock(return_value=[MockFundingPayment()])
    return ft


@pytest.fixture
def mock_tax_generator():
    """Create a mock TaxReportGenerator."""
    tg = AsyncMock()
    tg.get_available_years = AsyncMock(return_value=[2025, 2024])
    tg.get_year_data = AsyncMock(return_value={
        "summary": {
            "trade_count": 10,
            "total_gains": 500.0,
            "total_losses": -200.0,
            "net_pnl": 300.0,
        },
        "trades": [],
        "monthly_breakdown": [],
    })
    tg.generate_csv_content = AsyncMock(
        return_value="Date,Symbol,PnL\n2025-01-01,BTCUSDT,50.0\n"
    )
    return tg


@pytest_asyncio.fixture
async def dashboard_app(
    mock_settings,
    mock_trade_db,
    mock_risk_manager,
    mock_funding_tracker,
    mock_tax_generator,
):
    """Create a dashboard FastAPI app with all dependencies mocked."""
    with patch("src.dashboard.app.settings", mock_settings), \
         patch("src.dashboard.app.DASHBOARD_DEV_MODE", True), \
         patch("src.dashboard.app.DASHBOARD_API_KEY", ""), \
         patch("src.dashboard.app.WS_AUTH_ENABLED", False):

        from src.dashboard.app import create_app, limiter
        app = create_app()

        # Disable rate limiting for tests
        limiter.enabled = False

        # Inject mocked state
        app.state.trade_db = mock_trade_db
        app.state.risk_manager = mock_risk_manager
        app.state.funding_tracker = mock_funding_tracker
        app.state.tax_generator = mock_tax_generator
        app.state.websocket_clients = []

        yield app


@pytest_asyncio.fixture
async def client(dashboard_app):
    """Provide an async HTTP test client for the dashboard."""
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=dashboard_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests: trade_to_dict helper
# ---------------------------------------------------------------------------

class TestTradeToDict:
    """Tests for the trade_to_dict utility function."""

    def test_trade_to_dict_returns_complete_dictionary(self):
        """trade_to_dict should map all Trade attributes correctly."""
        from src.dashboard.app import trade_to_dict

        trade = MockTrade()
        result = trade_to_dict(trade)

        assert result["id"] == 1
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "long"
        assert result["size"] == 0.01
        assert result["entry_price"] == 95000.0
        assert result["exit_price"] == 96000.0
        assert result["take_profit"] == 97000.0
        assert result["stop_loss"] == 94000.0
        assert result["leverage"] == 4
        assert result["confidence"] == 75
        assert result["reason"] == "Test trade"
        assert result["status"] == "open"
        assert result["pnl"] == 10.0
        assert result["pnl_percent"] == 1.05
        assert result["fees"] == 0.5
        assert result["funding_paid"] == 0.1
        assert result["entry_time"] == "2025-06-01T12:00:00"
        assert result["exit_time"] is None

    def test_trade_to_dict_handles_none_optional_fields(self):
        """trade_to_dict should handle None optional fields gracefully."""
        from src.dashboard.app import trade_to_dict

        trade = MockTrade(
            exit_price=None,
            pnl=None,
            pnl_percent=None,
            fees=None,
            funding_paid=None,
        )

        result = trade_to_dict(trade)

        assert result["exit_price"] is None
        assert result["pnl"] is None
        assert result["pnl_percent"] is None
        assert result["fees"] is None
        assert result["funding_paid"] is None
        assert result["exit_time"] is None

    def test_trade_to_dict_handles_status_without_value_attr(self):
        """trade_to_dict should handle status as plain string."""
        from src.dashboard.app import trade_to_dict

        trade = MockTrade()
        trade.status = "closed"  # Plain string, no .value
        result = trade_to_dict(trade)

        assert result["status"] == "closed"

    def test_trade_to_dict_handles_none_entry_time(self):
        """trade_to_dict should handle None entry_time."""
        from src.dashboard.app import trade_to_dict

        trade = MockTrade()
        trade.entry_time = None
        result = trade_to_dict(trade)

        assert result["entry_time"] is None


# ---------------------------------------------------------------------------
# Tests: get_default_html helper
# ---------------------------------------------------------------------------

class TestGetDefaultHtml:
    """Tests for the get_default_html function."""

    def test_get_default_html_returns_valid_html(self):
        """Default HTML should contain key dashboard elements."""
        from src.dashboard.app import get_default_html
        html = get_default_html()

        assert "<!DOCTYPE html>" in html
        assert "Bitget Trading Bot Dashboard" in html
        assert "Daily P&L" in html
        assert "Win Rate" in html
        assert "websocket" in html.lower() or "WebSocket" in html

    def test_get_default_html_contains_api_endpoints(self):
        """Default HTML should reference API endpoints."""
        from src.dashboard.app import get_default_html
        html = get_default_html()

        assert "/api/status" in html
        assert "/api/trades" in html
        assert "/api/funding" in html
        assert "/api/health/detailed" in html

    def test_get_default_html_contains_tax_report_section(self):
        """Default HTML should contain tax report UI elements."""
        from src.dashboard.app import get_default_html
        html = get_default_html()

        assert "tax-report" in html or "Steuerreport" in html
        assert "tax-year-select" in html


# ---------------------------------------------------------------------------
# Tests: verify_api_key dependency
# ---------------------------------------------------------------------------

class TestVerifyApiKey:
    """Tests for the verify_api_key authentication dependency."""

    @pytest.mark.asyncio
    async def test_verify_api_key_dev_mode_allows_access(self):
        """When DASHBOARD_DEV_MODE is True, access should be granted."""
        with patch("src.dashboard.app.DASHBOARD_DEV_MODE", True):
            from src.dashboard.app import verify_api_key
            result = await verify_api_key(x_api_key=None)
            assert result is True

    @pytest.mark.asyncio
    async def test_verify_api_key_no_key_no_dev_mode_raises_503(self):
        """When no API key is configured and dev mode is off, raise 503."""
        with patch("src.dashboard.app.DASHBOARD_DEV_MODE", False), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", ""):
            from src.dashboard.app import verify_api_key
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key=None)
            assert exc_info.value.status_code == 503
            assert "not configured" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_api_key_valid_key_allows_access(self):
        """When a valid API key is provided, access should be granted."""
        with patch("src.dashboard.app.DASHBOARD_DEV_MODE", False), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", "my-secret-key"):
            from src.dashboard.app import verify_api_key
            result = await verify_api_key(x_api_key="my-secret-key")
            assert result is True

    @pytest.mark.asyncio
    async def test_verify_api_key_invalid_key_raises_401(self):
        """When an invalid API key is provided, raise 401."""
        with patch("src.dashboard.app.DASHBOARD_DEV_MODE", False), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", "correct-key"):
            from src.dashboard.app import verify_api_key
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key="wrong-key")
            assert exc_info.value.status_code == 401
            assert "Invalid" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_api_key_missing_header_raises_401(self):
        """When API key header is missing, raise 401."""
        with patch("src.dashboard.app.DASHBOARD_DEV_MODE", False), \
             patch("src.dashboard.app.DASHBOARD_API_KEY", "correct-key"):
            from src.dashboard.app import verify_api_key
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(x_api_key=None)
            assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Health check endpoint
# ---------------------------------------------------------------------------

class TestHealthCheck:
    """Tests for GET /api/health."""

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self, client, mock_trade_db, mock_risk_manager):
        """Health check returns 200 when all components are healthy."""
        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.10.0"
        assert data["components"]["database"] == "healthy"
        assert data["components"]["risk_manager"] == "healthy"
        assert data["components"]["funding_tracker"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_database_unhealthy(self, client, mock_trade_db):
        """Health check returns 503 when database is unhealthy."""
        mock_trade_db.get_statistics.side_effect = Exception("DB connection failed")

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert "unhealthy" in data["components"]["database"]

    @pytest.mark.asyncio
    async def test_health_check_risk_manager_unhealthy(self, client, mock_risk_manager):
        """Health check returns 503 when risk manager is unhealthy."""
        mock_risk_manager.get_daily_stats.side_effect = Exception("RM error")

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert "unhealthy" in data["components"]["risk_manager"]

    @pytest.mark.asyncio
    async def test_health_check_components_none(self, dashboard_app, client):
        """Health check handles None components gracefully."""
        dashboard_app.state.trade_db = None
        dashboard_app.state.risk_manager = None
        dashboard_app.state.funding_tracker = None

        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        # When components are None, they stay "unknown"
        assert data["components"]["database"] == "unknown"
        assert data["components"]["risk_manager"] == "unknown"
        assert data["components"]["funding_tracker"] == "unknown"


# ---------------------------------------------------------------------------
# Tests: Status endpoint
# ---------------------------------------------------------------------------

class TestGetStatus:
    """Tests for GET /api/status."""

    @pytest.mark.asyncio
    async def test_get_status_returns_running(self, client, mock_settings):
        """Status endpoint returns running state with config."""
        response = await client.get("/api/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "timestamp" in data
        assert data["demo_mode"] is True
        assert data["config"]["trading_pairs"] == ["BTCUSDT", "ETHUSDT"]
        assert data["config"]["leverage"] == 4
        assert data["can_trade"] is True
        assert data["remaining_trades"] == 1

    @pytest.mark.asyncio
    async def test_get_status_includes_daily_stats(self, client):
        """Status endpoint includes daily stats when available."""
        response = await client.get("/api/status")
        if response.status_code == 429:
            pytest.skip("Rate limited")

        data = response.json()
        assert data["daily_stats"] is not None
        assert "net_pnl" in data["daily_stats"]
        assert "win_rate" in data["daily_stats"]

    @pytest.mark.asyncio
    async def test_get_status_none_daily_stats(self, client, mock_risk_manager):
        """Status endpoint handles None daily stats."""
        mock_risk_manager.get_daily_stats.return_value = None

        response = await client.get("/api/status")
        if response.status_code == 429:
            pytest.skip("Rate limited")

        data = response.json()
        assert data["daily_stats"] is None


# ---------------------------------------------------------------------------
# Tests: Mode toggle
# ---------------------------------------------------------------------------

class TestModeToggle:
    """Tests for POST /api/mode/toggle and GET /api/mode."""

    @pytest.mark.asyncio
    async def test_toggle_mode_from_demo_to_live(self, client, mock_settings):
        """Toggle mode should switch from demo to live."""
        mock_settings.trading.demo_mode = True

        response = await client.post("/api/mode/toggle")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["mode"] == "live"
        assert data["demo_mode"] is False

    @pytest.mark.asyncio
    async def test_toggle_mode_from_live_to_demo(self, client, mock_settings):
        """Toggle mode should switch from live to demo."""
        mock_settings.trading.demo_mode = False

        response = await client.post("/api/mode/toggle")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["mode"] == "demo"
        assert data["demo_mode"] is True

    @pytest.mark.asyncio
    async def test_get_mode_returns_current_mode(self, client, mock_settings):
        """GET /api/mode returns current mode."""
        response = await client.get("/api/mode")

        assert response.status_code == 200
        data = response.json()
        assert "demo_mode" in data
        assert "mode" in data


# ---------------------------------------------------------------------------
# Tests: Trades endpoints
# ---------------------------------------------------------------------------

class TestTradesEndpoints:
    """Tests for GET /api/trades and GET /api/trades/{trade_id}."""

    @pytest.mark.asyncio
    async def test_get_trades_default(self, client, mock_trade_db):
        """GET /api/trades returns recent trades by default."""
        mock_trade_db.get_recent_trades.return_value = [MockTrade()]

        response = await client.get("/api/trades")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert len(data["trades"]) == 1
        assert data["trades"][0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_get_trades_with_limit(self, client, mock_trade_db):
        """GET /api/trades respects the limit parameter."""
        mock_trade_db.get_recent_trades.return_value = []

        response = await client.get("/api/trades?limit=10")

        assert response.status_code == 200
        mock_trade_db.get_recent_trades.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_get_trades_open_filter(self, client, mock_trade_db):
        """GET /api/trades?status=open returns open trades."""
        open_trade = MockTrade(status=MockTradeStatus("open"))
        mock_trade_db.get_open_trades.return_value = [open_trade]

        response = await client.get("/api/trades?status=open")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        mock_trade_db.get_open_trades.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_trades_open_with_symbol_filter(self, client, mock_trade_db):
        """GET /api/trades?status=open&symbol=BTCUSDT passes symbol to db."""
        mock_trade_db.get_open_trades.return_value = []

        response = await client.get("/api/trades?status=open&symbol=BTCUSDT")

        assert response.status_code == 200
        mock_trade_db.get_open_trades.assert_called_once_with("BTCUSDT")

    @pytest.mark.asyncio
    async def test_get_single_trade_found(self, client, mock_trade_db, mock_funding_tracker):
        """GET /api/trades/{id} returns trade details and funding."""
        trade = MockTrade(id=42)
        mock_trade_db.get_trade.return_value = trade
        payment = MockFundingPayment(payment_amount=0.095)
        mock_funding_tracker.get_trade_funding.return_value = [payment]

        response = await client.get("/api/trades/42")

        assert response.status_code == 200
        data = response.json()
        assert data["trade"]["id"] == 42
        assert len(data["funding_payments"]) == 1
        assert data["total_funding"] == pytest.approx(0.095)

    @pytest.mark.asyncio
    async def test_get_single_trade_not_found(self, client, mock_trade_db):
        """GET /api/trades/{id} returns 404 when trade not found."""
        mock_trade_db.get_trade.return_value = None

        response = await client.get("/api/trades/999")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    @pytest.mark.asyncio
    async def test_get_trades_empty_list(self, client, mock_trade_db):
        """GET /api/trades returns empty list when no trades exist."""
        mock_trade_db.get_recent_trades.return_value = []

        response = await client.get("/api/trades")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["trades"] == []


# ---------------------------------------------------------------------------
# Tests: Statistics endpoint
# ---------------------------------------------------------------------------

class TestStatisticsEndpoint:
    """Tests for GET /api/statistics."""

    @pytest.mark.asyncio
    async def test_get_statistics_default_period(self, client, mock_trade_db, mock_funding_tracker):
        """GET /api/statistics returns stats for default 30-day period."""
        response = await client.get("/api/statistics")

        assert response.status_code == 200
        data = response.json()
        assert data["period_days"] == 30
        assert "trade_stats" in data
        assert "funding_stats" in data
        assert data["funding_stats"]["total_paid"] == 5.0
        assert data["funding_stats"]["net_funding"] == 3.0

    @pytest.mark.asyncio
    async def test_get_statistics_custom_period(self, client, mock_trade_db):
        """GET /api/statistics?days=7 uses the provided period."""
        response = await client.get("/api/statistics?days=7")

        assert response.status_code == 200
        data = response.json()
        assert data["period_days"] == 7
        mock_trade_db.get_statistics.assert_called_with(7)


# ---------------------------------------------------------------------------
# Tests: Funding endpoints
# ---------------------------------------------------------------------------

class TestFundingEndpoints:
    """Tests for GET /api/funding and GET /api/funding/history/{symbol}."""

    @pytest.mark.asyncio
    async def test_get_funding_default(self, client, mock_funding_tracker):
        """GET /api/funding returns funding stats, daily summary, and recent."""
        response = await client.get("/api/funding")

        assert response.status_code == 200
        data = response.json()
        assert data["stats"]["total_paid"] == 5.0
        assert data["stats"]["net_funding"] == 3.0
        assert data["stats"]["highest_rate"] == 0.0005
        assert data["stats"]["lowest_rate"] == -0.0002
        assert len(data["daily_summary"]) == 2
        assert len(data["recent_payments"]) == 1

    @pytest.mark.asyncio
    async def test_get_funding_with_symbol_filter(self, client, mock_funding_tracker):
        """GET /api/funding?symbol=BTCUSDT passes symbol to funding tracker."""
        response = await client.get("/api/funding?symbol=BTCUSDT&days=7")

        assert response.status_code == 200
        mock_funding_tracker.get_funding_stats.assert_called_once_with("BTCUSDT", 7)

    @pytest.mark.asyncio
    async def test_get_funding_history(self, client, mock_funding_tracker):
        """GET /api/funding/history/{symbol} returns rate history."""
        response = await client.get("/api/funding/history/BTCUSDT?days=14")

        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "BTCUSDT"
        assert "history" in data
        mock_funding_tracker.get_funding_rate_history.assert_called_once_with("BTCUSDT", 14)

    @pytest.mark.asyncio
    async def test_get_funding_history_default_days(self, client, mock_funding_tracker):
        """GET /api/funding/history/{symbol} defaults to 7 days."""
        response = await client.get("/api/funding/history/ETHUSDT")

        assert response.status_code == 200
        mock_funding_tracker.get_funding_rate_history.assert_called_once_with("ETHUSDT", 7)


# ---------------------------------------------------------------------------
# Tests: Daily performance endpoint
# ---------------------------------------------------------------------------

class TestDailyPerformance:
    """Tests for GET /api/performance/daily."""

    @pytest.mark.asyncio
    async def test_get_daily_performance_default(self, client, mock_risk_manager):
        """GET /api/performance/daily returns daily stats."""
        response = await client.get("/api/performance/daily")

        assert response.status_code == 200
        data = response.json()
        assert "daily_stats" in data
        assert len(data["daily_stats"]) == 2
        mock_risk_manager.get_historical_stats.assert_called_once_with(30)

    @pytest.mark.asyncio
    async def test_get_daily_performance_custom_days(self, client, mock_risk_manager):
        """GET /api/performance/daily?days=7 uses custom period."""
        response = await client.get("/api/performance/daily?days=7")

        assert response.status_code == 200
        mock_risk_manager.get_historical_stats.assert_called_once_with(7)


# ---------------------------------------------------------------------------
# Tests: Config endpoint
# ---------------------------------------------------------------------------

class TestConfigEndpoint:
    """Tests for GET /api/config."""

    @pytest.mark.asyncio
    async def test_get_config_returns_full_configuration(self, client, mock_settings):
        """GET /api/config returns trading and strategy configuration."""
        response = await client.get("/api/config")

        assert response.status_code == 200
        data = response.json()
        assert data["trading"]["trading_pairs"] == ["BTCUSDT", "ETHUSDT"]
        assert data["trading"]["leverage"] == 4
        assert data["trading"]["max_trades_per_day"] == 2
        assert data["trading"]["take_profit_percent"] == 4.0
        assert data["trading"]["stop_loss_percent"] == 1.5
        assert data["strategy"]["fear_greed_extreme_fear"] == 20
        assert data["strategy"]["fear_greed_extreme_greed"] == 80
        assert data["strategy"]["high_confidence_min"] == 85
        assert data["strategy"]["low_confidence_min"] == 60


# ---------------------------------------------------------------------------
# Tests: Tax report endpoints
# ---------------------------------------------------------------------------

class TestTaxReportEndpoints:
    """Tests for tax report API endpoints."""

    @pytest.mark.asyncio
    async def test_get_tax_report_years(self, client, mock_tax_generator):
        """GET /api/tax-report/years returns available years."""
        response = await client.get("/api/tax-report/years")

        assert response.status_code == 200
        data = response.json()
        assert data["years"] == [2025, 2024]

    @pytest.mark.asyncio
    async def test_get_tax_report_data_default_language(self, client, mock_tax_generator):
        """GET /api/tax-report/{year} returns data in default language."""
        response = await client.get("/api/tax-report/2025")

        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["trade_count"] == 10
        assert data["summary"]["net_pnl"] == 300.0
        mock_tax_generator.get_year_data.assert_called_once_with(2025, "de")

    @pytest.mark.asyncio
    async def test_get_tax_report_data_english(self, client, mock_tax_generator):
        """GET /api/tax-report/{year}?language=en returns English data."""
        response = await client.get("/api/tax-report/2024?language=en")

        assert response.status_code == 200
        mock_tax_generator.get_year_data.assert_called_once_with(2024, "en")

    @pytest.mark.asyncio
    async def test_get_tax_report_data_invalid_language_defaults_to_de(self, client, mock_tax_generator):
        """Invalid language parameter defaults to 'de'."""
        response = await client.get("/api/tax-report/2025?language=fr")

        assert response.status_code == 200
        mock_tax_generator.get_year_data.assert_called_once_with(2025, "de")

    @pytest.mark.asyncio
    async def test_download_tax_report_csv_german(self, client, mock_tax_generator):
        """GET /api/tax-report/{year}/download returns CSV file."""
        response = await client.get("/api/tax-report/2025/download?language=de")

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "Steuerreport_2025_DE.csv" in response.headers["content-disposition"]
        content = response.text
        assert "Date,Symbol,PnL" in content

    @pytest.mark.asyncio
    async def test_download_tax_report_csv_english(self, client, mock_tax_generator):
        """GET /api/tax-report/{year}/download?language=en uses English filename."""
        response = await client.get("/api/tax-report/2024/download?language=en")

        assert response.status_code == 200
        assert "TaxReport_2024_EN.csv" in response.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_download_tax_report_csv_invalid_language_defaults(self, client, mock_tax_generator):
        """Invalid language for CSV download defaults to 'de'."""
        response = await client.get("/api/tax-report/2025/download?language=xx")

        assert response.status_code == 200
        assert "Steuerreport_2025_DE.csv" in response.headers["content-disposition"]
        mock_tax_generator.generate_csv_content.assert_called_once_with(2025, "de")


# ---------------------------------------------------------------------------
# Tests: Detailed health endpoint
# ---------------------------------------------------------------------------

class TestDetailedHealth:
    """Tests for GET /api/health/detailed."""

    @pytest.mark.asyncio
    async def test_detailed_health_all_healthy(self, client):
        """Detailed health returns all healthy when no issues."""
        with patch("src.dashboard.app.circuit_registry") as mock_registry:
            mock_registry.get_all_statuses.return_value = {}

            response = await client.get("/api/health/detailed")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["components"]["database"] == "healthy"
            assert data["components"]["risk_manager"] == "healthy"
            assert data["components"]["funding_tracker"] == "healthy"
            assert data["circuit_breakers"] == {}
            assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_detailed_health_with_open_circuit_breaker(self, client):
        """Detailed health shows degraded when a circuit breaker is open."""
        with patch("src.dashboard.app.circuit_registry") as mock_registry:
            mock_registry.get_all_statuses.return_value = {
                "bitget_api": {"state": "open", "stats": {"success_rate": 0.0}},
            }

            response = await client.get("/api/health/detailed")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert len(data["errors"]) >= 1
            cb_errors = [e for e in data["errors"] if "circuit_breaker" in e["component"]]
            assert len(cb_errors) == 1
            assert "bitget_api" in cb_errors[0]["error"]

    @pytest.mark.asyncio
    async def test_detailed_health_database_error(self, client, mock_trade_db):
        """Detailed health reports database errors."""
        mock_trade_db.get_statistics.side_effect = Exception("DB timeout")

        with patch("src.dashboard.app.circuit_registry") as mock_registry:
            mock_registry.get_all_statuses.return_value = {}

            response = await client.get("/api/health/detailed")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert any(e["component"] == "database" for e in data["errors"])

    @pytest.mark.asyncio
    async def test_detailed_health_risk_manager_error(self, client, mock_risk_manager):
        """Detailed health reports risk manager errors."""
        mock_risk_manager.get_daily_stats.side_effect = Exception("RM crash")

        with patch("src.dashboard.app.circuit_registry") as mock_registry:
            mock_registry.get_all_statuses.return_value = {}

            response = await client.get("/api/health/detailed")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert any(e["component"] == "risk_manager" for e in data["errors"])

    @pytest.mark.asyncio
    async def test_detailed_health_components_none(self, dashboard_app, client):
        """Detailed health handles None components."""
        dashboard_app.state.trade_db = None
        dashboard_app.state.risk_manager = None
        dashboard_app.state.funding_tracker = None

        with patch("src.dashboard.app.circuit_registry") as mock_registry:
            mock_registry.get_all_statuses.return_value = {}

            response = await client.get("/api/health/detailed")

            assert response.status_code == 200
            data = response.json()
            assert data["components"]["database"] == "unknown"
            assert data["components"]["risk_manager"] == "unknown"
            assert data["components"]["funding_tracker"] == "unknown"

    @pytest.mark.asyncio
    async def test_detailed_health_multiple_open_circuit_breakers(self, client):
        """Detailed health reports multiple open circuit breakers."""
        with patch("src.dashboard.app.circuit_registry") as mock_registry:
            mock_registry.get_all_statuses.return_value = {
                "bitget_api": {"state": "open", "stats": {"success_rate": 0.0}},
                "binance_api": {"state": "open", "stats": {"success_rate": 10.0}},
                "alternative_me_api": {"state": "closed", "stats": {"success_rate": 99.0}},
            }

            response = await client.get("/api/health/detailed")

            data = response.json()
            assert data["status"] == "degraded"
            cb_errors = [e for e in data["errors"] if "circuit_breaker" in e["component"]]
            assert len(cb_errors) == 2


# ---------------------------------------------------------------------------
# Tests: Index page
# ---------------------------------------------------------------------------

class TestIndexPage:
    """Tests for GET / (main dashboard page)."""

    @pytest.mark.asyncio
    async def test_index_returns_html(self, client):
        """GET / returns HTML content."""
        response = await client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.asyncio
    async def test_index_fallback_to_default_html(self, client):
        """GET / returns default HTML when template does not exist."""
        with patch("src.dashboard.app.DASHBOARD_DIR", Path("/nonexistent/path")):
            response = await client.get("/")

            assert response.status_code == 200
            assert "Bitget Trading Bot Dashboard" in response.text

    @pytest.mark.asyncio
    async def test_index_serves_template_when_exists(self, client, tmp_path):
        """GET / serves the template file when it exists."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        html_file = templates_dir / "index.html"
        html_file.write_text("<html><body>Custom Dashboard</body></html>")

        with patch("src.dashboard.app.DASHBOARD_DIR", tmp_path):
            response = await client.get("/")

            assert response.status_code == 200
            assert "Custom Dashboard" in response.text


# ---------------------------------------------------------------------------
# Tests: create_app function
# ---------------------------------------------------------------------------

class TestCreateApp:
    """Tests for the create_app factory function."""

    def test_create_app_returns_fastapi_instance(self):
        """create_app should return a configured FastAPI app."""
        with patch("src.dashboard.app.settings") as _mock_s, \
             patch("src.dashboard.app.DASHBOARD_DEV_MODE", True):
            from src.dashboard.app import create_app
            app = create_app()

            from fastapi import FastAPI
            assert isinstance(app, FastAPI)
            assert app.title == "Bitget Trading Bot Dashboard"

    def test_create_app_initializes_state(self):
        """create_app should initialize shared state to None/empty."""
        with patch("src.dashboard.app.settings") as _mock_s, \
             patch("src.dashboard.app.DASHBOARD_DEV_MODE", True):
            from src.dashboard.app import create_app
            app = create_app()

            assert app.state.trade_db is None
            assert app.state.risk_manager is None
            assert app.state.funding_tracker is None
            assert app.state.tax_generator is None
            assert app.state.websocket_clients == []


# ---------------------------------------------------------------------------
# Tests: Multiple trades in response
# ---------------------------------------------------------------------------

class TestMultipleTradesResponse:
    """Tests verifying correct handling of multiple trade items."""

    @pytest.mark.asyncio
    async def test_get_trades_multiple_items(self, client, mock_trade_db):
        """GET /api/trades returns multiple trades correctly."""
        trades = [
            MockTrade(id=1, symbol="BTCUSDT", side="long"),
            MockTrade(id=2, symbol="ETHUSDT", side="short"),
            MockTrade(id=3, symbol="BTCUSDT", side="long"),
        ]
        mock_trade_db.get_recent_trades.return_value = trades

        response = await client.get("/api/trades")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        assert data["trades"][0]["id"] == 1
        assert data["trades"][1]["symbol"] == "ETHUSDT"
        assert data["trades"][2]["side"] == "long"

    @pytest.mark.asyncio
    async def test_get_single_trade_with_multiple_funding_payments(
        self, client, mock_trade_db, mock_funding_tracker
    ):
        """Single trade endpoint correctly sums multiple funding payments."""
        trade = MockTrade(id=10)
        mock_trade_db.get_trade.return_value = trade

        payments = [
            MockFundingPayment(payment_amount=0.05),
            MockFundingPayment(payment_amount=0.10),
            MockFundingPayment(payment_amount=-0.02),
        ]
        mock_funding_tracker.get_trade_funding.return_value = payments

        response = await client.get("/api/trades/10")

        assert response.status_code == 200
        data = response.json()
        assert data["total_funding"] == pytest.approx(0.13)
        assert len(data["funding_payments"]) == 3


# ---------------------------------------------------------------------------
# Tests: Edge cases and error handling
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases and error handling paths."""

    @pytest.mark.asyncio
    async def test_health_check_has_timestamp(self, client):
        """Health check response includes a valid timestamp."""
        response = await client.get("/api/health")
        data = response.json()
        assert "timestamp" in data
        # Should be parseable as ISO format
        datetime.fromisoformat(data["timestamp"])

    @pytest.mark.asyncio
    async def test_status_has_timestamp(self, client):
        """Status response includes a valid timestamp."""
        response = await client.get("/api/status")
        data = response.json()
        assert "timestamp" in data
        datetime.fromisoformat(data["timestamp"])

    @pytest.mark.asyncio
    async def test_get_trades_closed_status_uses_recent(self, client, mock_trade_db):
        """GET /api/trades?status=closed falls through to recent trades."""
        mock_trade_db.get_recent_trades.return_value = []

        response = await client.get("/api/trades?status=closed")

        assert response.status_code == 200
        mock_trade_db.get_recent_trades.assert_called_once()

    @pytest.mark.asyncio
    async def test_statistics_includes_funding_stats_fields(self, client):
        """Statistics response includes all required funding stats fields."""
        response = await client.get("/api/statistics")

        data = response.json()
        funding = data["funding_stats"]
        assert "total_paid" in funding
        assert "total_received" in funding
        assert "net_funding" in funding
        assert "payment_count" in funding
        assert "avg_rate" in funding

    @pytest.mark.asyncio
    async def test_funding_includes_all_stat_fields(self, client):
        """Funding response includes all required stat fields."""
        response = await client.get("/api/funding")

        data = response.json()
        stats = data["stats"]
        assert "highest_rate" in stats
        assert "lowest_rate" in stats
        assert "avg_rate" in stats
        assert "payment_count" in stats
