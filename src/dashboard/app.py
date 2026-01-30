"""
Web Dashboard Application using FastAPI.

Provides REST API endpoints and serves the web interface.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from src.utils.logger import get_logger
from src.models.trade_database import TradeDatabase
from src.risk.risk_manager import RiskManager
from src.data.funding_tracker import FundingTracker
from config import settings

logger = get_logger(__name__)

# Dashboard directory
DASHBOARD_DIR = Path(__file__).parent


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Bitget Trading Bot Dashboard",
        description="Real-time monitoring dashboard for the Contrarian Liquidation Hunter",
        version="1.5.0"
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Shared state
    app.state.trade_db = None
    app.state.risk_manager = None
    app.state.funding_tracker = None
    app.state.websocket_clients = []

    @app.on_event("startup")
    async def startup():
        """Initialize database connections on startup."""
        app.state.trade_db = TradeDatabase()
        await app.state.trade_db.initialize()

        app.state.risk_manager = RiskManager()

        app.state.funding_tracker = FundingTracker()
        await app.state.funding_tracker.initialize()

        logger.info("Dashboard started")

    @app.on_event("shutdown")
    async def shutdown():
        """Clean up on shutdown."""
        if app.state.funding_tracker:
            await app.state.funding_tracker.close()
        logger.info("Dashboard stopped")

    # ==================== API ENDPOINTS ====================

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
    async def toggle_trading_mode():
        """Toggle between demo and live trading mode."""
        current_mode = settings.trading.demo_mode
        settings.trading.demo_mode = not current_mode
        new_mode = "demo" if settings.trading.demo_mode else "live"

        logger.info(f"Trading mode changed to: {new_mode.upper()}")

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

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            initCharts();
            fetchMode();
            updateDashboard();
            setInterval(updateDashboard, 10000); // Update every 10 seconds
        });
    </script>
</body>
</html>
"""


def run_dashboard(host: str = "0.0.0.0", port: int = 8080):
    """Run the dashboard server."""
    app = create_app()
    logger.info(f"Starting dashboard at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_dashboard()
