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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uvicorn

from src.middleware.security_headers import SecurityHeadersMiddleware, CORSSecurityMiddleware
from src.middleware.csrf_protection import CSRFProtectionMiddleware, CSRFTokenEndpoint

from src.utils.logger import get_logger
from src.models.trade_database import TradeDatabase
from src.risk.risk_manager import RiskManager
from src.data.funding_tracker import FundingTracker
from src.dashboard.tax_report import TaxReportGenerator
from src.utils.circuit_breaker import circuit_registry
from config import settings

# Multi-tenant routes
from src.dashboard.auth_routes import router as auth_router
from src.dashboard.credential_routes import router as credential_router
from src.dashboard.bot_routes import router as bot_router
from src.dashboard.admin_routes import router as admin_router
from src.dashboard.websocket_manager import get_connection_manager

logger = get_logger(__name__)

# WebSocket authentication token (optional, uses same key as API)
WS_AUTH_ENABLED = bool(os.getenv("DASHBOARD_API_KEY", ""))

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
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )

    # Security headers middleware (adds CSP, HSTS, X-Frame-Options, etc.)
    # Disable HSTS in development (localhost), enable in production
    enable_hsts = os.getenv("ENABLE_HSTS", "false").lower() == "true"
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=enable_hsts,
        hsts_max_age=31536000,  # 1 year
    )

    # CORS violation logging
    app.add_middleware(
        CORSSecurityMiddleware,
        allowed_origins=allowed_origins,
        log_violations=True,
    )

    # CSRF protection middleware (double-submit cookie pattern)
    # Disable secure cookie in development (localhost without HTTPS)
    csrf_secure = os.getenv("CSRF_COOKIE_SECURE", "false").lower() == "true"
    app.add_middleware(
        CSRFProtectionMiddleware,
        cookie_secure=csrf_secure,
        cookie_samesite="lax",  # Allow same-site navigation
    )

    # Register multi-tenant API routers
    app.include_router(auth_router)
    app.include_router(credential_router)
    app.include_router(bot_router)
    app.include_router(admin_router)

    # Shared state
    app.state.trade_db = None
    app.state.risk_manager = None
    app.state.funding_tracker = None
    app.state.tax_generator = None
    app.state.websocket_clients = []

    @app.on_event("startup")
    async def startup():
        """Initialize database connections on startup."""
        # Run database migrations first
        from src.models.migrations.multi_tenant_schema import run_migrations
        await run_migrations()

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

    @app.get("/api/csrf-token")
    async def get_csrf_token_endpoint(request: Request):
        """
        Get a CSRF token for use in subsequent requests.

        Returns:
            csrf_token: The token to include in X-CSRF-Token header
            header_name: Name of the header to use
            cookie_name: Name of the cookie that contains the token
        """
        return CSRFTokenEndpoint.get_token_response(request)

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
    @limiter.limit("30/minute")
    async def get_status(request: Request, auth: bool = Depends(verify_api_key)):
        """Get current bot status. Requires API key authentication."""
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
    @limiter.limit("30/minute")
    async def get_trading_mode(request: Request, auth: bool = Depends(verify_api_key)):
        """Get current trading mode. Requires API key authentication."""
        return {
            "demo_mode": settings.is_demo_mode,
            "mode": "demo" if settings.is_demo_mode else "live"
        }

    @app.get("/api/trades")
    @limiter.limit("30/minute")
    async def get_trades(
        request: Request,
        auth: bool = Depends(verify_api_key),
        limit: int = Query(50, ge=1, le=500, description="Number of trades to return"),
        status: Optional[str] = Query(None, pattern="^(open|closed)?$", description="Filter by status"),
        symbol: Optional[str] = Query(None, max_length=20, description="Filter by symbol")
    ):
        """Get trade history. Requires API key authentication."""
        if status == "open":
            trades = await app.state.trade_db.get_open_trades(symbol)
        else:
            trades = await app.state.trade_db.get_recent_trades(limit)

        return {
            "trades": [trade_to_dict(t) for t in trades],
            "count": len(trades)
        }

    @app.get("/api/trades/{trade_id}")
    @limiter.limit("30/minute")
    async def get_trade(request: Request, trade_id: int, auth: bool = Depends(verify_api_key)):
        """Get single trade details. Requires API key authentication."""
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
    @limiter.limit("30/minute")
    async def get_statistics(
        request: Request,
        auth: bool = Depends(verify_api_key),
        days: int = Query(30, ge=1, le=365, description="Number of days to analyze")
    ):
        """Get performance statistics. Requires API key authentication."""
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
    @limiter.limit("30/minute")
    async def get_funding(
        request: Request,
        auth: bool = Depends(verify_api_key),
        days: int = Query(30, ge=1, le=365, description="Number of days"),
        symbol: Optional[str] = Query(None, max_length=20, description="Filter by symbol")
    ):
        """Get funding rate data. Requires API key authentication."""
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
    @limiter.limit("30/minute")
    async def get_funding_history(
        request: Request,
        symbol: str,
        auth: bool = Depends(verify_api_key),
        days: int = Query(7, ge=1, le=90, description="Number of days")
    ):
        """Get funding rate history for a symbol. Requires API key authentication."""
        history = await app.state.funding_tracker.get_funding_rate_history(symbol, days)
        return {"symbol": symbol, "history": history}

    @app.get("/api/performance/daily")
    @limiter.limit("30/minute")
    async def get_daily_performance(
        request: Request,
        auth: bool = Depends(verify_api_key),
        days: int = Query(30, ge=1, le=365, description="Number of days")
    ):
        """Get daily performance breakdown. Requires API key authentication."""
        stats = app.state.risk_manager.get_historical_stats(days)
        return {"daily_stats": stats}

    @app.get("/api/config")
    @limiter.limit("30/minute")
    async def get_config(request: Request, auth: bool = Depends(verify_api_key)):
        """Get current configuration. Requires API key authentication."""
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

    # ==================== OHLC / CANDLESTICK DATA ====================

    @app.get("/api/ohlc/{symbol}")
    @limiter.limit("30/minute")
    async def get_ohlc_data(
        request: Request,
        symbol: str,
        auth: bool = Depends(verify_api_key),
        granularity: str = Query("1H", description="Timeframe: 1m, 5m, 15m, 30m, 1H, 4H, 1D"),
        limit: int = Query(100, ge=10, le=500, description="Number of candles")
    ):
        """
        Get OHLC candlestick data for a symbol.

        Returns candlestick data with open, high, low, close, volume.
        Requires API key authentication.
        """
        try:
            from src.api.bitget_client import BitgetClient

            # Create client (uses environment credentials)
            client = BitgetClient()

            # Fetch candlestick data
            candles = await client.get_candlesticks(
                symbol=symbol,
                granularity=granularity,
                limit=limit
            )

            # Format response
            ohlc_data = []
            for candle in candles:
                # Bitget returns: [timestamp, open, high, low, close, volume, quoteVolume]
                if len(candle) >= 6:
                    ohlc_data.append({
                        "time": int(candle[0]),
                        "open": float(candle[1]),
                        "high": float(candle[2]),
                        "low": float(candle[3]),
                        "close": float(candle[4]),
                        "volume": float(candle[5]),
                    })

            # Sort by time ascending (oldest first)
            ohlc_data.sort(key=lambda x: x["time"])

            return {
                "symbol": symbol,
                "granularity": granularity,
                "count": len(ohlc_data),
                "data": ohlc_data
            }

        except Exception as e:
            logger.error(f"Failed to fetch OHLC data for {symbol}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch candlestick data: {str(e)}"
            )

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

    # ==================== HEALTH & CIRCUIT BREAKER STATUS ====================

    @app.get("/api/health/detailed")
    @limiter.limit("30/minute")
    async def get_detailed_health(request: Request, auth: bool = Depends(verify_api_key)):
        """
        Get detailed health status including circuit breaker states.
        Requires API key authentication.
        """
        # Get basic health
        health = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.8.0",
            "components": {
                "database": "unknown",
                "risk_manager": "unknown",
                "funding_tracker": "unknown",
            },
            "circuit_breakers": {},
            "errors": []
        }

        # Check database
        try:
            if app.state.trade_db:
                await app.state.trade_db.get_statistics(1)
                health["components"]["database"] = "healthy"
        except Exception as e:
            health["components"]["database"] = f"unhealthy: {str(e)}"
            health["status"] = "degraded"
            health["errors"].append({"component": "database", "error": str(e)})

        # Check risk manager
        try:
            if app.state.risk_manager:
                app.state.risk_manager.get_daily_stats()
                health["components"]["risk_manager"] = "healthy"
        except Exception as e:
            health["components"]["risk_manager"] = f"unhealthy: {str(e)}"
            health["status"] = "degraded"
            health["errors"].append({"component": "risk_manager", "error": str(e)})

        # Check funding tracker
        try:
            if app.state.funding_tracker:
                health["components"]["funding_tracker"] = "healthy"
        except Exception as e:
            health["components"]["funding_tracker"] = f"unhealthy: {str(e)}"
            health["status"] = "degraded"
            health["errors"].append({"component": "funding_tracker", "error": str(e)})

        # Get circuit breaker statuses
        health["circuit_breakers"] = circuit_registry.get_all_statuses()

        # Check if any circuit breakers are open
        for name, breaker_status in health["circuit_breakers"].items():
            if breaker_status.get("state") == "open":
                health["status"] = "degraded"
                health["errors"].append({
                    "component": f"circuit_breaker:{name}",
                    "error": f"Circuit breaker {name} is OPEN - API temporarily unavailable"
                })

        return health

    # ==================== BACKTESTING API ====================

    @app.get("/api/backtest/data")
    @limiter.limit("30/minute")
    async def list_backtest_data(request: Request, auth: bool = Depends(verify_api_key)):
        """
        List available historical data for backtesting.

        Returns list of data files with metadata.
        """
        from src.backtest.data_storage import ParquetDataStorage

        storage = ParquetDataStorage()
        data_list = storage.list_available_data()

        return {
            "data_files": data_list,
            "supported_timeframes": ["1m", "5m", "15m", "30m", "1H", "4H", "1D"],
            "supported_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
        }

    @app.post("/api/backtest/download")
    @limiter.limit("5/minute")
    async def download_backtest_data(
        request: Request,
        symbol: str = Query("BTCUSDT", description="Trading pair"),
        timeframe: str = Query("1H", description="Candle timeframe"),
        days: int = Query(365, ge=1, le=1000, description="Days to download"),
        auth: bool = Depends(verify_api_key)
    ):
        """
        Download historical data from Binance.

        This is a long-running operation that downloads data month by month.
        """
        from src.backtest.data_storage import ParquetDataStorage, BinanceDataDownloader
        from datetime import datetime, timedelta

        storage = ParquetDataStorage()
        downloader = BinanceDataDownloader(storage)

        start_date = datetime.now() - timedelta(days=days)

        try:
            total_rows = await downloader.download_klines(
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date
            )

            return {
                "success": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "days": days,
                "rows_downloaded": total_rows,
                "message": f"Downloaded {total_rows} rows for {symbol} {timeframe}"
            }
        except Exception as e:
            logger.error(f"Error downloading backtest data: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/backtest/run")
    @limiter.limit("5/minute")
    async def run_backtest(
        request: Request,
        symbol: str = Query("BTCUSDT", description="Trading pair"),
        days: int = Query(180, ge=30, le=365, description="Days to backtest"),
        capital: float = Query(10000.0, ge=100, le=1000000, description="Starting capital"),
        leverage: int = Query(3, ge=1, le=20, description="Leverage"),
        take_profit: float = Query(3.5, ge=0.5, le=20, description="Take profit %"),
        stop_loss: float = Query(2.0, ge=0.5, le=10, description="Stop loss %"),
        auth: bool = Depends(verify_api_key)
    ):
        """
        Run a backtest with custom parameters.

        Returns detailed backtest results including performance metrics.
        """
        from src.backtest.historical_data import HistoricalDataFetcher
        from src.backtest.engine import BacktestEngine, BacktestConfig
        from src.backtest.report import BacktestReport
        from src.backtest.mock_data import generate_mock_historical_data

        try:
            # Fetch data
            fetcher = HistoricalDataFetcher()
            data_points = await fetcher.fetch_all_historical_data(days)
            await fetcher.close()

            if not data_points:
                logger.info("No live data available, using mock data")
                data_points = generate_mock_historical_data(days)

            if not data_points:
                raise HTTPException(status_code=500, detail="No data available for backtest")

            # Configure backtest
            config = BacktestConfig(
                starting_capital=capital,
                leverage=leverage,
                take_profit_percent=take_profit,
                stop_loss_percent=stop_loss,
                max_trades_per_day=settings.trading.max_trades_per_day,
                daily_loss_limit_percent=settings.trading.daily_loss_limit_percent,
                position_size_percent=settings.trading.position_size_percent,
            )

            # Run backtest
            engine = BacktestEngine(config)
            result = engine.run(data_points)

            # Save results
            report = BacktestReport(result)
            report.save_json()

            return {
                "success": True,
                "results": result.to_dict(),
                "trades_count": len([t for t in result.trades if hasattr(t, 'to_dict')]),
                "daily_stats_count": len(result.daily_stats),
            }

        except Exception as e:
            logger.error(f"Backtest error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/backtest/results")
    @limiter.limit("30/minute")
    async def get_backtest_results(request: Request, auth: bool = Depends(verify_api_key)):
        """
        Get the most recent backtest results.

        Returns saved backtest results from the last run.
        """
        import json
        from pathlib import Path

        results_file = Path("data/backtest/results.json")

        if not results_file.exists():
            return {"results": None, "message": "No backtest results found. Run a backtest first."}

        try:
            with open(results_file, "r") as f:
                results = json.load(f)
            return {"results": results}
        except Exception as e:
            logger.error(f"Error reading backtest results: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ==================== WEBSOCKET ====================

    async def verify_ws_token(websocket: WebSocket) -> bool:
        """Verify WebSocket authentication token."""
        if not WS_AUTH_ENABLED:
            return True

        # Check query parameter
        token = websocket.query_params.get("token")
        if token and secrets.compare_digest(token, DASHBOARD_API_KEY):
            return True

        # Reject unauthenticated connection
        return False

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """
        WebSocket for real-time updates.

        Authentication:
        - If DASHBOARD_API_KEY is set, requires ?token=<api_key> query parameter
        - If not set, authentication is disabled (development mode)
        """
        # Verify authentication
        if not await verify_ws_token(websocket):
            await websocket.close(code=4001, reason="Authentication required")
            logger.warning("WebSocket connection rejected: Invalid or missing token")
            return

        await websocket.accept()
        app.state.websocket_clients.append(websocket)
        logger.info(f"WebSocket client connected (total: {len(app.state.websocket_clients)})")

        try:
            while True:
                # Build status update with health info
                daily_stats = app.state.risk_manager.get_daily_stats()

                # Get circuit breaker status
                circuit_status = circuit_registry.get_all_statuses()
                has_api_issues = any(
                    s.get("state") == "open" for s in circuit_status.values()
                )

                status_data = {
                    "status": "running",
                    "timestamp": datetime.now().isoformat(),
                    "demo_mode": settings.is_demo_mode,
                    "daily_stats": daily_stats.to_dict() if daily_stats else None,
                    "can_trade": app.state.risk_manager.can_trade()[0],
                    "remaining_trades": app.state.risk_manager.get_remaining_trades(),
                    "health": {
                        "has_api_issues": has_api_issues,
                        "circuit_breakers": circuit_status
                    }
                }

                await websocket.send_json({"type": "status", "data": status_data})
                await asyncio.sleep(5)
        except WebSocketDisconnect:
            if websocket in app.state.websocket_clients:
                app.state.websocket_clients.remove(websocket)
            logger.info(f"WebSocket client disconnected (remaining: {len(app.state.websocket_clients)})")

    # ==================== AUTHENTICATED WEBSOCKET ====================

    @app.websocket("/ws/user")
    async def user_websocket_endpoint(websocket: WebSocket):
        """
        Per-user WebSocket for real-time updates.

        Authentication:
        - Requires JWT token as ?token=<jwt> query parameter
        - Each connection is isolated to the authenticated user
        - Receives only data for that user's bots and trades
        """
        # Get token from query parameter
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4001, reason="JWT token required")
            logger.warning("User WebSocket rejected: Missing token")
            return

        # Authenticate with JWT
        manager = get_connection_manager()
        payload = await manager.authenticate(websocket, token)

        if not payload:
            await websocket.close(code=4001, reason="Invalid or expired token")
            logger.warning("User WebSocket rejected: Invalid token")
            return

        # Register connection
        await manager.connect(websocket, payload)

        try:
            while True:
                # Send periodic status updates for this user
                user_id = payload.user_id

                # Get user-specific bot status
                try:
                    from src.bot.orchestrator import get_orchestrator
                    orchestrator = get_orchestrator()
                    user_bots = await orchestrator.get_user_bots(user_id)
                    bot_statuses = [
                        {
                            "id": bot.bot_instance.id,
                            "name": bot.bot_instance.name,
                            "status": bot.status.value,
                            "symbol": bot.bot_instance.symbol,
                        }
                        for bot in user_bots
                    ]
                except Exception:
                    bot_statuses = []

                # Send user-specific status
                status_data = {
                    "type": "status",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "user_id": user_id,
                        "bots": bot_statuses,
                        "bot_count": len(bot_statuses),
                        "active_bots": sum(1 for b in bot_statuses if b["status"] == "running"),
                    }
                }

                await websocket.send_json(status_data)

                # Wait for next update or client message
                try:
                    # Non-blocking receive with timeout
                    data = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=5.0
                    )
                    # Handle client commands if needed
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    # No message received, continue loop
                    pass

        except WebSocketDisconnect:
            await manager.disconnect(websocket)
            logger.info(f"User WebSocket disconnected: user={payload.user_id}")
        except Exception as e:
            logger.error(f"User WebSocket error: {e}")
            await manager.disconnect(websocket)

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
    <!-- Error Banner (hidden by default) -->
    <div id="error-banner" class="hidden bg-red-600 text-white p-3 shadow-lg">
        <div class="container mx-auto flex justify-between items-center">
            <div class="flex items-center gap-3">
                <span class="text-xl">⚠️</span>
                <div>
                    <strong id="error-title">API Connection Issue</strong>
                    <p id="error-message" class="text-sm opacity-90">Some external APIs are temporarily unavailable.</p>
                </div>
            </div>
            <button onclick="dismissError()" class="px-3 py-1 bg-red-700 hover:bg-red-800 rounded text-sm">Dismiss</button>
        </div>
    </div>

    <!-- Warning Banner (hidden by default) -->
    <div id="warning-banner" class="hidden bg-yellow-500 text-yellow-900 p-3 shadow-lg">
        <div class="container mx-auto flex justify-between items-center">
            <div class="flex items-center gap-3">
                <span class="text-xl">⚡</span>
                <div>
                    <strong id="warning-title">Degraded Performance</strong>
                    <p id="warning-message" class="text-sm">Some features may be temporarily limited.</p>
                </div>
            </div>
            <button onclick="dismissWarning()" class="px-3 py-1 bg-yellow-600 hover:bg-yellow-700 rounded text-sm text-white">Dismiss</button>
        </div>
    </div>

    <nav class="bg-indigo-600 text-white p-4 shadow-lg">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-xl font-bold">Bitget Trading Bot</h1>
            <div class="flex items-center gap-4">
                <!-- Health Status Indicator -->
                <div id="health-status" class="flex items-center gap-2 cursor-pointer" onclick="showHealthDetails()" title="Click for details">
                    <span id="health-icon" class="text-lg">🟢</span>
                    <span id="health-text" class="text-sm hidden md:inline">Healthy</span>
                </div>
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

    <!-- Health Details Modal (hidden by default) -->
    <div id="health-modal" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div class="bg-white rounded-lg p-6 max-w-lg w-full mx-4 max-h-96 overflow-y-auto">
            <div class="flex justify-between items-center mb-4">
                <h2 class="text-lg font-bold">System Health Status</h2>
                <button onclick="closeHealthModal()" class="text-gray-500 hover:text-gray-700 text-xl">&times;</button>
            </div>
            <div id="health-details" class="space-y-4">
                <p class="text-gray-500">Loading...</p>
            </div>
        </div>
    </div>

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
        let wsConnection = null;
        let wsReconnectAttempts = 0;
        let healthStatus = { status: 'unknown', errors: [] };

        // Error/Warning banner management
        function showErrorBanner(title, message) {
            document.getElementById('error-title').textContent = title;
            document.getElementById('error-message').textContent = message;
            document.getElementById('error-banner').classList.remove('hidden');
        }

        function dismissError() {
            document.getElementById('error-banner').classList.add('hidden');
        }

        function showWarningBanner(title, message) {
            document.getElementById('warning-title').textContent = title;
            document.getElementById('warning-message').textContent = message;
            document.getElementById('warning-banner').classList.remove('hidden');
        }

        function dismissWarning() {
            document.getElementById('warning-banner').classList.add('hidden');
        }

        // Health status management
        function updateHealthIndicator(status) {
            const icon = document.getElementById('health-icon');
            const text = document.getElementById('health-text');

            if (status.status === 'healthy') {
                icon.textContent = '🟢';
                text.textContent = 'Healthy';
                text.className = 'text-sm hidden md:inline text-green-200';
                dismissError();
                dismissWarning();
            } else if (status.status === 'degraded') {
                icon.textContent = '🟡';
                text.textContent = 'Degraded';
                text.className = 'text-sm hidden md:inline text-yellow-200';

                // Show warning if circuit breakers are open
                if (status.errors && status.errors.length > 0) {
                    const cbErrors = status.errors.filter(e => e.component.startsWith('circuit_breaker:'));
                    if (cbErrors.length > 0) {
                        showWarningBanner(
                            'External API Issues',
                            cbErrors.map(e => e.error).join('; ')
                        );
                    }
                }
            } else if (status.status === 'unhealthy') {
                icon.textContent = '🔴';
                text.textContent = 'Unhealthy';
                text.className = 'text-sm hidden md:inline text-red-200';
                showErrorBanner('System Error', 'Critical components are unavailable. Trading may be affected.');
            }

            healthStatus = status;
        }

        // Show health details modal
        async function showHealthDetails() {
            document.getElementById('health-modal').classList.remove('hidden');

            try {
                const response = await fetch('/api/health/detailed');
                const data = await response.json();

                let html = '';

                // Components
                html += '<div class="border-b pb-3 mb-3">';
                html += '<h3 class="font-semibold mb-2">Components</h3>';
                for (const [name, status] of Object.entries(data.components)) {
                    const isHealthy = status === 'healthy';
                    html += `<div class="flex justify-between items-center py-1">
                        <span class="text-gray-700">${name}</span>
                        <span class="${isHealthy ? 'text-green-600' : 'text-red-600'}">${status}</span>
                    </div>`;
                }
                html += '</div>';

                // Circuit Breakers
                if (Object.keys(data.circuit_breakers).length > 0) {
                    html += '<div class="border-b pb-3 mb-3">';
                    html += '<h3 class="font-semibold mb-2">External APIs (Circuit Breakers)</h3>';
                    for (const [name, breaker] of Object.entries(data.circuit_breakers)) {
                        const state = breaker.state;
                        let stateColor = 'text-green-600';
                        let stateIcon = '✓';
                        if (state === 'open') {
                            stateColor = 'text-red-600';
                            stateIcon = '✗';
                        } else if (state === 'half_open') {
                            stateColor = 'text-yellow-600';
                            stateIcon = '~';
                        }
                        html += `<div class="flex justify-between items-center py-1">
                            <span class="text-gray-700">${name}</span>
                            <span class="${stateColor}">${stateIcon} ${state} (${breaker.stats.success_rate.toFixed(0)}% success)</span>
                        </div>`;
                    }
                    html += '</div>';
                }

                // Errors
                if (data.errors && data.errors.length > 0) {
                    html += '<div>';
                    html += '<h3 class="font-semibold mb-2 text-red-600">Active Issues</h3>';
                    for (const error of data.errors) {
                        html += `<div class="bg-red-50 p-2 rounded mb-2">
                            <strong class="text-red-700">${error.component}</strong>
                            <p class="text-sm text-red-600">${error.error}</p>
                        </div>`;
                    }
                    html += '</div>';
                }

                document.getElementById('health-details').innerHTML = html;
            } catch (error) {
                document.getElementById('health-details').innerHTML =
                    '<p class="text-red-500">Failed to load health details: ' + error.message + '</p>';
            }
        }

        function closeHealthModal() {
            document.getElementById('health-modal').classList.add('hidden');
        }

        // WebSocket connection with authentication
        function connectWebSocket() {
            const apiKey = ''; // Will be empty in dev mode
            const wsUrl = apiKey
                ? `ws://${window.location.host}/ws?token=${apiKey}`
                : `ws://${window.location.host}/ws`;

            wsConnection = new WebSocket(wsUrl);

            wsConnection.onopen = function() {
                console.log('WebSocket connected');
                wsReconnectAttempts = 0;
                document.getElementById('status-indicator').textContent = 'Connected';
                document.getElementById('status-indicator').className = 'px-3 py-1 rounded-full bg-green-500 text-sm';
            };

            wsConnection.onmessage = function(event) {
                const message = JSON.parse(event.data);
                if (message.type === 'status') {
                    handleStatusUpdate(message.data);
                }
            };

            wsConnection.onclose = function(event) {
                console.log('WebSocket closed:', event.code, event.reason);
                document.getElementById('status-indicator').textContent = 'Disconnected';
                document.getElementById('status-indicator').className = 'px-3 py-1 rounded-full bg-yellow-500 text-sm';

                // Reconnect with exponential backoff
                if (wsReconnectAttempts < 5) {
                    const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts), 30000);
                    wsReconnectAttempts++;
                    console.log(`Reconnecting in ${delay}ms (attempt ${wsReconnectAttempts})`);
                    setTimeout(connectWebSocket, delay);
                } else {
                    showErrorBanner('Connection Lost', 'Unable to connect to the server. Please refresh the page.');
                }
            };

            wsConnection.onerror = function(error) {
                console.error('WebSocket error:', error);
            };
        }

        // Handle status updates from WebSocket
        function handleStatusUpdate(status) {
            // Update mode
            updateModeUI(status.demo_mode ? 'demo' : 'live');

            // Update health
            if (status.health) {
                const healthInfo = {
                    status: status.health.has_api_issues ? 'degraded' : 'healthy',
                    errors: [],
                    circuit_breakers: status.health.circuit_breakers
                };

                // Check for open circuit breakers
                for (const [name, cb] of Object.entries(status.health.circuit_breakers || {})) {
                    if (cb.state === 'open') {
                        healthInfo.errors.push({
                            component: `circuit_breaker:${name}`,
                            error: `${name} is temporarily unavailable`
                        });
                    }
                }

                updateHealthIndicator(healthInfo);
            }

            // Update stats
            if (status.daily_stats) {
                document.getElementById('daily-pnl').textContent = '$' + (status.daily_stats.net_pnl || 0).toFixed(2);
                document.getElementById('daily-pnl').className = 'stat-value ' + ((status.daily_stats.net_pnl || 0) >= 0 ? 'positive' : 'negative');
                document.getElementById('win-rate').textContent = (status.daily_stats.win_rate || 0).toFixed(1) + '%';
            }
        }

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

        // Toggle trading mode with enhanced security
        async function toggleMode() {
            const newMode = currentMode === 'demo' ? 'live' : 'demo';

            if (newMode === 'live') {
                // First confirmation
                if (!confirm('WARNING: You are about to switch to LIVE mode.\\n\\nThis will execute REAL trades with REAL money!\\n\\nAre you absolutely sure?')) {
                    return;
                }

                // Second confirmation: User must type "Live"
                const userInput = prompt(
                    'SECURITY CHECK\\n\\n' +
                    'To confirm switching to LIVE mode, please type the word "Live" exactly:\\n\\n' +
                    '(This prevents accidental mode switches)'
                );

                if (userInput !== 'Live') {
                    alert('Mode switch cancelled.\\n\\nYou must type "Live" exactly (case-sensitive) to confirm.');
                    return;
                }

                // Final confirmation with countdown
                let countdown = 5;
                const countdownConfirm = confirm(
                    'FINAL CONFIRMATION\\n\\n' +
                    'You typed "Live" - switching to LIVE TRADING MODE.\\n\\n' +
                    'This is your LAST CHANCE to cancel.\\n\\n' +
                    'Click OK to proceed or Cancel to abort.'
                );

                if (!countdownConfirm) {
                    alert('Mode switch cancelled.');
                    return;
                }
            }

            try {
                const response = await fetch('/api/mode/toggle', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    updateModeUI(data.mode);
                    if (data.mode === 'live') {
                        alert('⚠️ LIVE MODE ACTIVATED\\n\\nThe bot will now execute REAL trades!');
                    } else {
                        alert('✅ DEMO MODE ACTIVATED\\n\\nNo real trades will be executed.');
                    }
                } else {
                    alert('Failed to toggle mode: ' + (data.detail || 'Unknown error'));
                }
            } catch (error) {
                console.error('Error toggling mode:', error);
                alert('Failed to toggle mode: ' + error.message);
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
                document.getElementById('net-funding').className = 'stat-value ' + (funding.stats.net_funding >= 0 ? 'positive' : 'negative');

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
            connectWebSocket(); // Start WebSocket connection
            setInterval(updateDashboard, 10000); // Update every 10 seconds

            // Initial health check
            fetch('/api/health/detailed')
                .then(r => r.json())
                .then(data => updateHealthIndicator(data))
                .catch(err => console.error('Health check failed:', err));
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
