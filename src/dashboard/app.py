"""
Web Dashboard Application using FastAPI.

Provides REST API endpoints and serves the web interface.

Security Features (v1.7.0):
- API key authentication on sensitive endpoints
- CORS restricted to localhost
- Rate limiting on mode toggle
- Health check endpoint
"""

import asyncio
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

from src.utils.logger import get_logger
from src.models.trade_database import TradeDatabase
from src.risk.risk_manager import RiskManager
from src.data.funding_tracker import FundingTracker
from src.dashboard.tax_report import TaxReportGenerator
from config import settings

logger = get_logger(__name__)

# Dashboard directory
DASHBOARD_DIR = Path(__file__).parent

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# API Key for dashboard authentication
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")


async def verify_api_key(x_api_key: str = Header(None, alias="X-API-Key")):
    """
    Verify API key for protected endpoints.

    If DASHBOARD_API_KEY is not set, authentication is disabled (development mode).
    """
    if not DASHBOARD_API_KEY:
        # No API key configured - allow access (development mode)
        return True

    if not x_api_key or not secrets.compare_digest(x_api_key, DASHBOARD_API_KEY):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "API key required in X-API-Key header"}
        )
    return True


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Bitget Trading Bot Dashboard",
        description="Real-time monitoring dashboard for the Contrarian Liquidation Hunter",
        version="1.7.0"
    )

    # Rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS middleware - restricted to localhost only
    allowed_origins = [
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Shared state
    app.state.trade_db = None
    app.state.risk_manager = None
    app.state.funding_tracker = None
    app.state.tax_generator = None
    app.state.websocket_clients = []

    @app.on_event("startup")
    async def startup():
        """Initialize database connections on startup."""
        app.state.trade_db = TradeDatabase()
        await app.state.trade_db.initialize()

        app.state.risk_manager = RiskManager()

        app.state.funding_tracker = FundingTracker()
        await app.state.funding_tracker.initialize()

        app.state.tax_generator = TaxReportGenerator(
            app.state.trade_db,
            app.state.funding_tracker
        )

        logger.info("Dashboard started")

    @app.on_event("shutdown")
    async def shutdown():
        """Clean up on shutdown."""
        if app.state.funding_tracker:
            await app.state.funding_tracker.close()
        logger.info("Dashboard stopped")

    # ==================== API ENDPOINTS ====================

    @app.get("/api/health")
    async def health_check():
        """
        Health check endpoint for monitoring and container orchestration.

        Returns service health status and component connectivity.
        No authentication required.
        """
        health = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.7.0",
            "components": {
                "database": "unknown",
                "risk_manager": "unknown",
                "funding_tracker": "unknown",
            }
        }

        # Check database
        try:
            if app.state.trade_db:
                # Simple query to verify DB is responsive
                await app.state.trade_db.get_statistics(1)
                health["components"]["database"] = "healthy"
        except Exception as e:
            health["components"]["database"] = f"unhealthy: {str(e)}"
            health["status"] = "degraded"

        # Check risk manager
        try:
            if app.state.risk_manager:
                app.state.risk_manager.get_daily_stats()
                health["components"]["risk_manager"] = "healthy"
        except Exception as e:
            health["components"]["risk_manager"] = f"unhealthy: {str(e)}"
            health["status"] = "degraded"

        # Check funding tracker
        try:
            if app.state.funding_tracker:
                health["components"]["funding_tracker"] = "healthy"
        except Exception as e:
            health["components"]["funding_tracker"] = f"unhealthy: {str(e)}"
            health["status"] = "degraded"

        # Return appropriate HTTP status
        status_code = 200 if health["status"] == "healthy" else 503
        return JSONResponse(content=health, status_code=status_code)

    @app.get("/api/status")
    async def get_status():
        """Get current bot status."""
        daily_stats = app.state.risk_manager.get_daily_stats()

        return {
            "status": "running",
            "timestamp": datetime.now().isoformat(),
            "demo_mode": settings.is_demo_mode,
            "config": {
                "trading_pairs": settings.trading.trading_pairs,
                "leverage": settings.trading.leverage,
                "max_trades_per_day": settings.trading.max_trades_per_day,
                "daily_loss_limit": settings.trading.daily_loss_limit_percent,
                "take_profit": settings.trading.take_profit_percent,
                "stop_loss": settings.trading.stop_loss_percent,
            },
            "daily_stats": daily_stats.to_dict() if daily_stats else None,
            "can_trade": app.state.risk_manager.can_trade()[0],
            "remaining_trades": app.state.risk_manager.get_remaining_trades(),
        }

    @app.post("/api/mode/toggle")
    @limiter.limit("5/minute")
    async def toggle_trading_mode(request: Request, auth: bool = Depends(verify_api_key)):
        """
        Toggle between demo and live trading mode.

        Security:
        - Requires API key authentication (if DASHBOARD_API_KEY is set)
        - Rate limited to 5 requests per minute
        """
        current_mode = settings.trading.demo_mode
        settings.trading.demo_mode = not current_mode
        new_mode = "demo" if settings.trading.demo_mode else "live"

        logger.warning(f"Trading mode changed to: {new_mode.upper()} (by API request)")

        return {
            "success": True,
            "mode": new_mode,
            "demo_mode": settings.trading.demo_mode,
            "message": f"Switched to {new_mode.upper()} mode"
        }

    @app.get("/api/mode")
    async def get_trading_mode():
        """Get current trading mode."""
        return {
            "demo_mode": settings.is_demo_mode,
            "mode": "demo" if settings.is_demo_mode else "live"
        }

    @app.get("/api/trades")
    async def get_trades(
        limit: int = 50,
        status: Optional[str] = None,
        symbol: Optional[str] = None
    ):
        """Get trade history."""
        if status == "open":
            trades = await app.state.trade_db.get_open_trades(symbol)
        else:
            trades = await app.state.trade_db.get_recent_trades(limit)

        return {
            "trades": [trade_to_dict(t) for t in trades],
            "count": len(trades)
        }

    @app.get("/api/trades/{trade_id}")
    async def get_trade(trade_id: int):
        """Get single trade details."""
        trade = await app.state.trade_db.get_trade(trade_id)
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")

        # Get funding payments for this trade
        funding = await app.state.funding_tracker.get_trade_funding(trade_id)

        return {
            "trade": trade_to_dict(trade),
            "funding_payments": [f.to_dict() for f in funding],
            "total_funding": sum(f.payment_amount for f in funding)
        }

    @app.get("/api/statistics")
    async def get_statistics(days: int = 30):
        """Get performance statistics."""
        stats = await app.state.trade_db.get_statistics(days)
        funding_stats = await app.state.funding_tracker.get_funding_stats(days=days)

        return {
            "period_days": days,
            "trade_stats": stats,
            "funding_stats": {
                "total_paid": funding_stats.total_paid,
                "total_received": funding_stats.total_received,
                "net_funding": funding_stats.net_funding,
                "payment_count": funding_stats.payment_count,
                "avg_rate": funding_stats.avg_rate,
            }
        }

    @app.get("/api/funding")
    async def get_funding(days: int = 30, symbol: Optional[str] = None):
        """Get funding rate data."""
        stats = await app.state.funding_tracker.get_funding_stats(symbol, days)
        daily_summary = await app.state.funding_tracker.get_daily_funding_summary(days)
        recent = await app.state.funding_tracker.get_recent_payments(50)

        return {
            "stats": {
                "total_paid": stats.total_paid,
                "total_received": stats.total_received,
                "net_funding": stats.net_funding,
                "payment_count": stats.payment_count,
                "avg_rate": stats.avg_rate,
                "highest_rate": stats.highest_rate,
                "lowest_rate": stats.lowest_rate,
            },
            "daily_summary": daily_summary,
            "recent_payments": [p.to_dict() for p in recent]
        }

    @app.get("/api/funding/history/{symbol}")
    async def get_funding_history(symbol: str, days: int = 7):
        """Get funding rate history for a symbol."""
        history = await app.state.funding_tracker.get_funding_rate_history(symbol, days)
        return {"symbol": symbol, "history": history}

    @app.get("/api/performance/daily")
    async def get_daily_performance(days: int = 30):
        """Get daily performance breakdown."""
        stats = app.state.risk_manager.get_historical_stats(days)
        return {"daily_stats": stats}

    @app.get("/api/config")
    async def get_config():
        """Get current configuration."""
        return {
            "trading": {
                "trading_pairs": settings.trading.trading_pairs,
                "max_trades_per_day": settings.trading.max_trades_per_day,
                "daily_loss_limit_percent": settings.trading.daily_loss_limit_percent,
                "position_size_percent": settings.trading.position_size_percent,
                "leverage": settings.trading.leverage,
                "take_profit_percent": settings.trading.take_profit_percent,
                "stop_loss_percent": settings.trading.stop_loss_percent,
            },
            "strategy": {
                "fear_greed_extreme_fear": settings.strategy.fear_greed_extreme_fear,
                "fear_greed_extreme_greed": settings.strategy.fear_greed_extreme_greed,
                "long_short_crowded_longs": settings.strategy.long_short_crowded_longs,
                "long_short_crowded_shorts": settings.strategy.long_short_crowded_shorts,
                "high_confidence_min": settings.strategy.high_confidence_min,
                "low_confidence_min": settings.strategy.low_confidence_min,
            }
        }

    # ==================== TAX REPORT ====================

    @app.get("/api/tax-report/years")
    async def get_tax_report_years():
        """Get list of years with trade data for tax reporting."""
        years = await app.state.tax_generator.get_available_years()
        return {"years": years}

    @app.get("/api/tax-report/{year}")
    async def get_tax_report_data(year: int, language: str = "de"):
        """
        Get tax report data for a specific year.

        Args:
            year: Calendar year (e.g., 2025)
            language: Language code ('de' or 'en')

        Returns:
            JSON with summary, trades, monthly breakdown, and funding payments
        """
        if language not in ['de', 'en']:
            language = 'de'

        data = await app.state.tax_generator.get_year_data(year, language)
        return data

    @app.get("/api/tax-report/{year}/download")
    async def download_tax_report_csv(year: int, language: str = "de"):
        """
        Download tax report as CSV file.

        Args:
            year: Calendar year (e.g., 2025)
            language: Language code ('de' or 'en')

        Returns:
            CSV file download
        """
        from fastapi.responses import StreamingResponse
        from io import BytesIO

        if language not in ['de', 'en']:
            language = 'de'

        # Generate CSV content
        csv_content = await app.state.tax_generator.generate_csv_content(year, language)

        # Convert to bytes
        csv_bytes = csv_content.encode('utf-8')
        stream = BytesIO(csv_bytes)

        # Determine filename
        if language == 'de':
            filename = f"Steuerreport_{year}_DE.csv"
        else:
            filename = f"TaxReport_{year}_EN.csv"

        # Return as streaming response
        return StreamingResponse(
            stream,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8"
            }
        )

    # ==================== WEBSOCKET ====================

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket for real-time updates."""
        await websocket.accept()
        app.state.websocket_clients.append(websocket)

        try:
            while True:
                # Send status update every 5 seconds
                status = await get_status()
                await websocket.send_json({"type": "status", "data": status})
                await asyncio.sleep(5)
        except WebSocketDisconnect:
            app.state.websocket_clients.remove(websocket)

    # ==================== WEB INTERFACE ====================

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the main dashboard page."""
        html_path = DASHBOARD_DIR / "templates" / "index.html"
        if html_path.exists():
            return HTMLResponse(content=html_path.read_text())
        return HTMLResponse(content=get_default_html())

    return app


def trade_to_dict(trade) -> Dict[str, Any]:
    """Convert trade object to dictionary."""
    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "side": trade.side,
        "size": trade.size,
        "entry_price": trade.entry_price,
        "exit_price": getattr(trade, 'exit_price', None),
        "take_profit": trade.take_profit,
        "stop_loss": trade.stop_loss,
        "leverage": trade.leverage,
        "confidence": trade.confidence,
        "reason": trade.reason,
        "status": trade.status.value if hasattr(trade.status, 'value') else trade.status,
        "pnl": getattr(trade, 'pnl', None),
        "pnl_percent": getattr(trade, 'pnl_percent', None),
        "fees": getattr(trade, 'fees', None),
        "funding_paid": getattr(trade, 'funding_paid', None),
        "entry_time": trade.entry_time.isoformat() if trade.entry_time else None,
        "exit_time": getattr(trade, 'exit_time', None),
    }


def get_default_html() -> str:
    """Return default HTML if template not found."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bitget Trading Bot Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .card { @apply bg-white rounded-lg shadow-md p-6 mb-4; }
        .stat-value { @apply text-3xl font-bold; }
        .stat-label { @apply text-gray-500 text-sm; }
        .positive { @apply text-green-600; }
        .negative { @apply text-red-600; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <nav class="bg-indigo-600 text-white p-4 shadow-lg">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-xl font-bold">Bitget Trading Bot</h1>
            <div class="flex items-center gap-4">
                <div class="flex items-center gap-2">
                    <span class="text-sm">Mode:</span>
                    <button id="mode-toggle" onclick="toggleMode()" class="px-3 py-1 rounded-full text-sm font-semibold transition-all duration-200 cursor-pointer hover:opacity-80">
                        DEMO
                    </button>
                </div>
                <span id="status-indicator" class="px-3 py-1 rounded-full bg-green-500 text-sm">Running</span>
            </div>
        </div>
    </nav>

    <div class="container mx-auto p-6">
        <!-- Stats Overview -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div class="card">
                <div class="stat-label">Daily P&L</div>
                <div id="daily-pnl" class="stat-value">$0.00</div>
            </div>
            <div class="card">
                <div class="stat-label">Win Rate</div>
                <div id="win-rate" class="stat-value">0%</div>
            </div>
            <div class="card">
                <div class="stat-label">Trades Today</div>
                <div id="trades-today" class="stat-value">0/2</div>
            </div>
            <div class="card">
                <div class="stat-label">Net Funding</div>
                <div id="net-funding" class="stat-value">$0.00</div>
            </div>
        </div>

        <!-- Charts Row -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            <div class="card">
                <h2 class="text-lg font-semibold mb-4">Equity Curve (30 Days)</h2>
                <canvas id="equity-chart"></canvas>
            </div>
            <div class="card">
                <h2 class="text-lg font-semibold mb-4">Funding Rate History</h2>
                <canvas id="funding-chart"></canvas>
            </div>
        </div>

        <!-- Open Positions -->
        <div class="card">
            <h2 class="text-lg font-semibold mb-4">Open Positions</h2>
            <div id="positions-container" class="overflow-x-auto">
                <table class="min-w-full">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-4 py-2 text-left">Symbol</th>
                            <th class="px-4 py-2 text-left">Side</th>
                            <th class="px-4 py-2 text-right">Size</th>
                            <th class="px-4 py-2 text-right">Entry</th>
                            <th class="px-4 py-2 text-right">TP/SL</th>
                            <th class="px-4 py-2 text-right">Unrealized P&L</th>
                        </tr>
                    </thead>
                    <tbody id="positions-body">
                        <tr><td colspan="6" class="text-center py-4 text-gray-500">No open positions</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Recent Trades -->
        <div class="card">
            <h2 class="text-lg font-semibold mb-4">Recent Trades</h2>
            <div class="overflow-x-auto">
                <table class="min-w-full">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-4 py-2 text-left">Time</th>
                            <th class="px-4 py-2 text-left">Symbol</th>
                            <th class="px-4 py-2 text-left">Side</th>
                            <th class="px-4 py-2 text-right">Entry</th>
                            <th class="px-4 py-2 text-right">Exit</th>
                            <th class="px-4 py-2 text-right">P&L</th>
                            <th class="px-4 py-2 text-right">Fees</th>
                        </tr>
                    </thead>
                    <tbody id="trades-body">
                        <tr><td colspan="7" class="text-center py-4 text-gray-500">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Configuration -->
        <div class="card">
            <h2 class="text-lg font-semibold mb-4">Configuration</h2>
            <div id="config-container" class="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div><span class="text-gray-500">Leverage:</span> <span id="cfg-leverage">-</span></div>
                <div><span class="text-gray-500">Take Profit:</span> <span id="cfg-tp">-</span></div>
                <div><span class="text-gray-500">Stop Loss:</span> <span id="cfg-sl">-</span></div>
                <div><span class="text-gray-500">Max Trades:</span> <span id="cfg-max-trades">-</span></div>
            </div>
        </div>

        <!-- Tax Report -->
        <div class="card">
            <h2 class="text-lg font-semibold mb-4">📊 <span id="tax-report-title">Steuerreport / Tax Report</span></h2>

            <!-- Controls Row -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                <!-- Year Selector -->
                <div>
                    <label class="text-gray-500 text-sm block mb-1"><span id="tax-year-label">Jahr / Year</span></label>
                    <select id="tax-year-select" class="w-full px-3 py-2 border rounded-md bg-white">
                        <option value="">Loading...</option>
                    </select>
                </div>

                <!-- Language Toggle -->
                <div>
                    <label class="text-gray-500 text-sm block mb-1"><span id="tax-lang-label">Sprache / Language</span></label>
                    <div class="flex gap-2">
                        <button id="lang-de" onclick="toggleTaxLanguage('de')" class="flex-1 px-4 py-2 rounded-md bg-indigo-600 text-white font-semibold transition-colors">
                            Deutsch
                        </button>
                        <button id="lang-en" onclick="toggleTaxLanguage('en')" class="flex-1 px-4 py-2 rounded-md bg-gray-300 text-gray-700 font-semibold transition-colors">
                            English
                        </button>
                    </div>
                </div>

                <!-- Download Button -->
                <div>
                    <label class="text-gray-500 text-sm block mb-1">&nbsp;</label>
                    <button id="download-tax-csv" onclick="downloadTaxCSV()" class="w-full px-4 py-2 rounded-md bg-green-600 text-white font-semibold hover:bg-green-700 transition-colors">
                        📥 <span id="download-btn-text">CSV Herunterladen</span>
                    </button>
                </div>
            </div>

            <!-- Tax Summary Preview -->
            <div id="tax-summary" class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 p-4 bg-gray-50 rounded-lg">
                <div class="text-center">
                    <div class="text-gray-500 text-sm" id="tax-label-trades">Trades</div>
                    <div class="text-2xl font-bold" id="tax-value-trades">-</div>
                </div>
                <div class="text-center">
                    <div class="text-gray-500 text-sm" id="tax-label-gains">Gewinne / Gains</div>
                    <div class="text-2xl font-bold text-green-600" id="tax-value-gains">€0.00</div>
                </div>
                <div class="text-center">
                    <div class="text-gray-500 text-sm" id="tax-label-losses">Verluste / Losses</div>
                    <div class="text-2xl font-bold text-red-600" id="tax-value-losses">€0.00</div>
                </div>
                <div class="text-center">
                    <div class="text-gray-500 text-sm" id="tax-label-net">Netto / Net</div>
                    <div class="text-2xl font-bold" id="tax-value-net">€0.00</div>
                </div>
            </div>

            <!-- Monthly Breakdown Chart -->
            <div class="mt-4">
                <h3 class="text-md font-semibold mb-2" id="tax-monthly-title">Monatliche Aufschlüsselung / Monthly Breakdown</h3>
                <canvas id="tax-monthly-chart"></canvas>
            </div>

            <!-- No Data Message -->
            <div id="tax-no-data" class="text-center py-8 text-gray-500" style="display: none;">
                <span id="tax-no-data-text">Keine Daten für dieses Jahr / No data for this year</span>
            </div>
        </div>
    </div>

    <script>
        // Charts
        let equityChart, fundingChart;
        let currentMode = 'demo';

        // Update mode indicator UI
        function updateModeUI(mode) {
            currentMode = mode;
            const btn = document.getElementById('mode-toggle');
            if (mode === 'demo') {
                btn.textContent = 'DEMO';
                btn.className = 'px-3 py-1 rounded-full text-sm font-semibold transition-all duration-200 cursor-pointer hover:opacity-80 bg-orange-500 text-white';
            } else {
                btn.textContent = 'LIVE';
                btn.className = 'px-3 py-1 rounded-full text-sm font-semibold transition-all duration-200 cursor-pointer hover:opacity-80 bg-red-600 text-white animate-pulse';
            }
        }

        // Toggle trading mode
        async function toggleMode() {
            const newMode = currentMode === 'demo' ? 'live' : 'demo';
            if (newMode === 'live') {
                if (!confirm('WARNING: Switching to LIVE mode will execute REAL trades with REAL money. Are you sure?')) {
                    return;
                }
            }
            try {
                const response = await fetch('/api/mode/toggle', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    updateModeUI(data.mode);
                }
            } catch (error) {
                console.error('Error toggling mode:', error);
                alert('Failed to toggle mode');
            }
        }

        // Fetch current mode
        async function fetchMode() {
            try {
                const response = await fetch('/api/mode');
                const data = await response.json();
                updateModeUI(data.mode);
            } catch (error) {
                console.error('Error fetching mode:', error);
            }
        }

        // Initialize charts
        function initCharts() {
            const equityCtx = document.getElementById('equity-chart').getContext('2d');
            equityChart = new Chart(equityCtx, {
                type: 'line',
                data: { labels: [], datasets: [{ label: 'Equity', data: [], borderColor: '#4F46E5', fill: false }] },
                options: { responsive: true, scales: { y: { beginAtZero: false } } }
            });

            const fundingCtx = document.getElementById('funding-chart').getContext('2d');
            fundingChart = new Chart(fundingCtx, {
                type: 'bar',
                data: { labels: [], datasets: [{ label: 'Funding Paid', data: [], backgroundColor: '#EF4444' }] },
                options: { responsive: true }
            });
        }

        // Fetch and update data
        async function updateDashboard() {
            try {
                // Status
                const status = await fetch('/api/status').then(r => r.json());
                if (status.daily_stats) {
                    document.getElementById('daily-pnl').textContent = '$' + (status.daily_stats.net_pnl || 0).toFixed(2);
                    document.getElementById('daily-pnl').className = 'stat-value ' + (status.daily_stats.net_pnl >= 0 ? 'positive' : 'negative');
                    document.getElementById('win-rate').textContent = (status.daily_stats.win_rate || 0).toFixed(1) + '%';
                    document.getElementById('trades-today').textContent = status.daily_stats.trades_executed + '/' + status.config.max_trades_per_day;
                }

                // Config
                document.getElementById('cfg-leverage').textContent = status.config.leverage + 'x';
                document.getElementById('cfg-tp').textContent = status.config.take_profit + '%';
                document.getElementById('cfg-sl').textContent = status.config.stop_loss + '%';
                document.getElementById('cfg-max-trades').textContent = status.config.max_trades_per_day;

                // Funding
                const funding = await fetch('/api/funding?days=30').then(r => r.json());
                document.getElementById('net-funding').textContent = '$' + (funding.stats.net_funding || 0).toFixed(2);
                document.getElementById('net-funding').className = 'stat-value ' + (funding.stats.net_funding <= 0 ? 'positive' : 'negative');

                // Update funding chart
                if (funding.daily_summary && funding.daily_summary.length > 0) {
                    fundingChart.data.labels = funding.daily_summary.map(d => d.date).reverse();
                    fundingChart.data.datasets[0].data = funding.daily_summary.map(d => d.total).reverse();
                    fundingChart.update();
                }

                // Trades
                const trades = await fetch('/api/trades?limit=20').then(r => r.json());
                const tbody = document.getElementById('trades-body');
                if (trades.trades.length > 0) {
                    tbody.innerHTML = trades.trades.map(t => `
                        <tr class="border-t">
                            <td class="px-4 py-2">${t.entry_time ? new Date(t.entry_time).toLocaleString() : '-'}</td>
                            <td class="px-4 py-2">${t.symbol}</td>
                            <td class="px-4 py-2 ${t.side === 'long' ? 'text-green-600' : 'text-red-600'}">${t.side.toUpperCase()}</td>
                            <td class="px-4 py-2 text-right">$${t.entry_price?.toFixed(2) || '-'}</td>
                            <td class="px-4 py-2 text-right">$${t.exit_price?.toFixed(2) || '-'}</td>
                            <td class="px-4 py-2 text-right ${(t.pnl || 0) >= 0 ? 'positive' : 'negative'}">$${(t.pnl || 0).toFixed(2)}</td>
                            <td class="px-4 py-2 text-right">$${(t.fees || 0).toFixed(2)}</td>
                        </tr>
                    `).join('');
                }

                // Open positions
                const openTrades = await fetch('/api/trades?status=open').then(r => r.json());
                const posBody = document.getElementById('positions-body');
                if (openTrades.trades.length > 0) {
                    posBody.innerHTML = openTrades.trades.map(t => `
                        <tr class="border-t">
                            <td class="px-4 py-2 font-medium">${t.symbol}</td>
                            <td class="px-4 py-2 ${t.side === 'long' ? 'text-green-600' : 'text-red-600'}">${t.side.toUpperCase()}</td>
                            <td class="px-4 py-2 text-right">${t.size?.toFixed(6) || '-'}</td>
                            <td class="px-4 py-2 text-right">$${t.entry_price?.toFixed(2) || '-'}</td>
                            <td class="px-4 py-2 text-right">$${t.take_profit?.toFixed(2)} / $${t.stop_loss?.toFixed(2)}</td>
                            <td class="px-4 py-2 text-right">-</td>
                        </tr>
                    `).join('');
                } else {
                    posBody.innerHTML = '<tr><td colspan="6" class="text-center py-4 text-gray-500">No open positions</td></tr>';
                }

                // Performance for equity chart
                const perf = await fetch('/api/performance/daily?days=30').then(r => r.json());
                if (perf.daily_stats && perf.daily_stats.length > 0) {
                    let equity = 10000;
                    const equityData = perf.daily_stats.reverse().map(d => {
                        equity += d.net_pnl || 0;
                        return equity;
                    });
                    equityChart.data.labels = perf.daily_stats.map(d => d.date);
                    equityChart.data.datasets[0].data = equityData;
                    equityChart.update();
                }

            } catch (error) {
                console.error('Error updating dashboard:', error);
            }
        }

        // ==================== TAX REPORT ====================

        // Tax report state
        let currentTaxYear = new Date().getFullYear();
        let currentTaxLanguage = 'de';
        let taxMonthlyChart = null;
        let taxData = null;

        // Tax report translations
        const taxTranslations = {
            de: {
                trades: 'Trades',
                gains: 'Gewinne',
                losses: 'Verluste',
                net: 'Netto',
                downloadBtn: 'CSV Herunterladen',
                noData: 'Keine Daten für dieses Jahr',
                yearLabel: 'Jahr',
                langLabel: 'Sprache'
            },
            en: {
                trades: 'Trades',
                gains: 'Gains',
                losses: 'Losses',
                net: 'Net',
                downloadBtn: 'Download CSV',
                noData: 'No data for this year',
                yearLabel: 'Year',
                langLabel: 'Language'
            }
        };

        // Load available years
        async function loadAvailableYears() {
            try {
                const response = await fetch('/api/tax-report/years');
                const data = await response.json();

                const select = document.getElementById('tax-year-select');
                select.innerHTML = '';

                if (data.years && data.years.length > 0) {
                    data.years.forEach(year => {
                        const option = document.createElement('option');
                        option.value = year;
                        option.textContent = year;
                        if (year === currentTaxYear) {
                            option.selected = true;
                        }
                        select.appendChild(option);
                    });

                    // Set to first available year if current year not available
                    if (!data.years.includes(currentTaxYear)) {
                        currentTaxYear = data.years[0];
                    }
                } else {
                    const option = document.createElement('option');
                    option.value = '';
                    option.textContent = 'No data available';
                    select.appendChild(option);
                }

                // Add change listener
                select.addEventListener('change', (e) => {
                    currentTaxYear = parseInt(e.target.value);
                    loadTaxReportData();
                });
            } catch (error) {
                console.error('Error loading available years:', error);
            }
        }

        // Load tax report data
        async function loadTaxReportData() {
            try {
                const response = await fetch(`/api/tax-report/${currentTaxYear}?language=${currentTaxLanguage}`);
                taxData = await response.json();

                updateTaxSummaryUI();
                updateTaxMonthlyChart();
            } catch (error) {
                console.error('Error loading tax report data:', error);
                showTaxNoData();
            }
        }

        // Update tax summary UI
        function updateTaxSummaryUI() {
            const summary = taxData.summary;

            if (!summary || summary.trade_count === 0) {
                showTaxNoData();
                return;
            }

            // Hide no-data message
            document.getElementById('tax-no-data').style.display = 'none';
            document.getElementById('tax-summary').style.display = 'grid';
            document.getElementById('tax-monthly-chart').parentElement.style.display = 'block';

            // Update values
            document.getElementById('tax-value-trades').textContent = summary.trade_count || 0;
            document.getElementById('tax-value-gains').textContent = '€' + (summary.total_gains || 0).toFixed(2);
            document.getElementById('tax-value-losses').textContent = '€' + (summary.total_losses || 0).toFixed(2);
            document.getElementById('tax-value-net').textContent = '€' + (summary.net_pnl || 0).toFixed(2);

            // Update net color
            const netElement = document.getElementById('tax-value-net');
            if (summary.net_pnl >= 0) {
                netElement.className = 'text-2xl font-bold text-green-600';
            } else {
                netElement.className = 'text-2xl font-bold text-red-600';
            }
        }

        // Show no data message
        function showTaxNoData() {
            document.getElementById('tax-no-data').style.display = 'block';
            document.getElementById('tax-summary').style.display = 'none';
            document.getElementById('tax-monthly-chart').parentElement.style.display = 'none';
        }

        // Initialize tax monthly chart
        function initTaxMonthlyChart() {
            const ctx = document.getElementById('tax-monthly-chart').getContext('2d');
            taxMonthlyChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Net PnL (€)',
                        data: [],
                        backgroundColor: 'rgba(99, 102, 241, 0.8)',
                        borderColor: 'rgba(99, 102, 241, 1)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function(value) {
                                    return '€' + value.toFixed(2);
                                }
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return 'Net: €' + context.parsed.y.toFixed(2);
                                }
                            }
                        }
                    }
                }
            });
        }

        // Update tax monthly chart
        function updateTaxMonthlyChart() {
            if (!taxData || !taxData.monthly_breakdown) return;

            const monthly = taxData.monthly_breakdown.filter(m => m.trades > 0);

            if (monthly.length === 0) {
                return;
            }

            taxMonthlyChart.data.labels = monthly.map(m => m.month);
            taxMonthlyChart.data.datasets[0].data = monthly.map(m => m.net);

            // Update colors based on positive/negative
            taxMonthlyChart.data.datasets[0].backgroundColor = monthly.map(m =>
                m.net >= 0 ? 'rgba(34, 197, 94, 0.8)' : 'rgba(239, 68, 68, 0.8)'
            );

            taxMonthlyChart.update();
        }

        // Toggle tax language
        function toggleTaxLanguage(lang) {
            if (lang !== 'de' && lang !== 'en') return;

            currentTaxLanguage = lang;

            // Update button styles
            document.getElementById('lang-de').className = lang === 'de'
                ? 'flex-1 px-4 py-2 rounded-md bg-indigo-600 text-white font-semibold transition-colors'
                : 'flex-1 px-4 py-2 rounded-md bg-gray-300 text-gray-700 font-semibold transition-colors';

            document.getElementById('lang-en').className = lang === 'en'
                ? 'flex-1 px-4 py-2 rounded-md bg-indigo-600 text-white font-semibold transition-colors'
                : 'flex-1 px-4 py-2 rounded-md bg-gray-300 text-gray-700 font-semibold transition-colors';

            // Update UI labels
            const t = taxTranslations[lang];
            document.getElementById('tax-label-trades').textContent = t.trades;
            document.getElementById('tax-label-gains').textContent = t.gains;
            document.getElementById('tax-label-losses').textContent = t.losses;
            document.getElementById('tax-label-net').textContent = t.net;
            document.getElementById('download-btn-text').textContent = t.downloadBtn;
            document.getElementById('tax-no-data-text').textContent = t.noData;

            // Reload data in new language
            loadTaxReportData();
        }

        // Download tax CSV
        function downloadTaxCSV() {
            const filename = currentTaxLanguage === 'de'
                ? `Steuerreport_${currentTaxYear}_DE.csv`
                : `TaxReport_${currentTaxYear}_EN.csv`;

            window.location.href = `/api/tax-report/${currentTaxYear}/download?language=${currentTaxLanguage}`;
        }

        // ==================== END TAX REPORT ====================

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            initCharts();
            initTaxMonthlyChart();
            fetchMode();
            updateDashboard();
            loadAvailableYears();
            loadTaxReportData();
            setInterval(updateDashboard, 10000); // Update every 10 seconds
        });
    </script>
</body>
</html>
"""


def run_dashboard(host: str = "127.0.0.1", port: int = 8080):
    """
    Run the dashboard server.

    Args:
        host: Host to bind to. Default is 127.0.0.1 (localhost only) for security.
              Use 0.0.0.0 only if you need external access and have proper auth.
        port: Port to listen on. Default is 8080.
    """
    app = create_app()

    # Security warning if binding to all interfaces
    if host == "0.0.0.0":
        if not DASHBOARD_API_KEY:
            logger.warning(
                "WARNING: Dashboard exposed on all interfaces without API key! "
                "Set DASHBOARD_API_KEY environment variable for production use."
            )

    logger.info(f"Starting dashboard at http://{host}:{port}")
    logger.info(f"API authentication: {'ENABLED' if DASHBOARD_API_KEY else 'DISABLED (development mode)'}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_dashboard()
