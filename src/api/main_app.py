"""
FastAPI application factory.

Creates the main application with all routers, middleware,
database lifecycle, and static file serving.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.routers import (
    admin_logs,
    affiliate,
    auth,
    backtest,
    bots,
    config,
    exchanges,
    funding,
    metrics,
    portfolio,
    presets,
    statistics,
    status,
    tax_report,
    trades,
    users,
    websocket,
)
from src.models.session import close_db, init_db
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-API-Version"] = "1"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' wss: https:; "
            "font-src 'self'"
        )
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment == "production" or os.getenv("ENABLE_HSTS", "false").lower() == "true":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    # Validate JWT configuration before anything else
    from src.auth.jwt_handler import validate_jwt_config
    validate_jwt_config()

    # Validate general configuration
    from src.utils.config_validator import validate_startup_config, ConfigValidationError
    try:
        validate_startup_config()
    except ConfigValidationError as e:
        logger.error("Startup aborted: %s", e)
        raise

    # Startup check: warn if running in production without explicit encryption key
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment == "production" and not os.getenv("ENCRYPTION_KEY"):
        logger.warning(
            "SECURITY WARNING: Running in production without explicit ENCRYPTION_KEY. "
            "Set ENCRYPTION_KEY env var to prevent auto-generation."
        )

    # Startup
    logger.info("Initializing database...")
    await init_db()

    # Seed exchanges table
    await _seed_exchanges()

    # Clean up stale backtest runs left in "pending"/"running" from previous crash
    await _recover_stale_backtests()

    # Initialize multibot orchestrator
    from src.bot.orchestrator import BotOrchestrator
    orchestrator = BotOrchestrator()
    app.state.orchestrator = orchestrator

    # Restore bots that were running before shutdown
    await orchestrator.restore_on_startup()

    # Start Prometheus bot-metrics collector
    from src.monitoring.collectors import collect_bot_metrics
    from src.monitoring.metrics import APP_INFO

    APP_INFO.info({"version": "3.0.0", "environment": environment})
    collector_task = asyncio.create_task(collect_bot_metrics(app))

    logger.info("Application started successfully")
    yield

    # Shutdown
    logger.info("Shutting down...")
    collector_task.cancel()
    await orchestrator.shutdown_all()

    # Drain pending audit + event writes before closing DB
    from src.api.middleware.audit_log import drain_pending_audit_tasks
    from src.utils.event_logger import drain_pending_event_tasks
    await drain_pending_audit_tasks(timeout=5.0)
    await drain_pending_event_tasks(timeout=5.0)

    await close_db()
    logger.info("Application shut down")


async def _recover_stale_backtests():
    """Mark backtest runs stuck in 'pending'/'running' as failed after restart."""
    from sqlalchemy import update

    from src.models.database import BacktestRun
    from src.models.session import get_session

    try:
        async with get_session() as session:
            result = await session.execute(
                update(BacktestRun)
                .where(BacktestRun.status.in_(["pending", "running"]))
                .values(status="failed", error_message="Server restarted during execution")
            )
            if result.rowcount:
                logger.info("Recovered %d stale backtest run(s)", result.rowcount)
    except Exception as e:
        logger.warning("Failed to recover stale backtests: %s", e)


async def _seed_exchanges():
    """Seed the exchanges table with supported exchanges."""
    from sqlalchemy import select

    from src.models.database import Exchange
    from src.models.session import get_session

    async with get_session() as session:
        exchanges_data = [
            {"name": "bitget", "display_name": "Bitget", "is_enabled": True, "supports_demo": True},
            {"name": "weex", "display_name": "Weex", "is_enabled": True, "supports_demo": True},
            {"name": "hyperliquid", "display_name": "Hyperliquid", "is_enabled": True, "supports_demo": True},
        ]
        for ex in exchanges_data:
            existing = await session.execute(
                select(Exchange).where(Exchange.name == ex["name"])
            )
            if not existing.scalar_one_or_none():
                session.add(Exchange(**ex))


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    environment = os.getenv("ENVIRONMENT", "development").lower()
    is_prod = environment == "production"

    app = FastAPI(
        title="Trading Bot API",
        description="Multi-Exchange Trading Bot with Web UI",
        version="3.0.0",
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    # Global exception handler — sanitizes error responses in production
    from src.api.middleware.error_handler import global_exception_handler
    app.add_exception_handler(Exception, global_exception_handler)

    # Log 422 validation errors for debugging (without request body to avoid leaking secrets)
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(
            "[422] %s %s | errors=%s",
            request.method, request.url.path, exc.errors(),
        )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    # Prometheus metrics middleware
    from src.monitoring.middleware import PrometheusMiddleware
    app.add_middleware(PrometheusMiddleware)

    # Audit logging middleware
    from src.api.middleware.audit_log import AuditLogMiddleware
    app.add_middleware(AuditLogMiddleware)

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS — same-origin (localhost:8000) does not need CORS so it is excluded.
    environment = os.getenv("ENVIRONMENT", "development").lower()
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    extra_origins = os.getenv("CORS_ORIGINS", "")
    if extra_origins:
        for origin in extra_origins.split(","):
            origin = origin.strip()
            if not origin:
                continue
            # In production, only allow HTTPS origins
            if environment == "production" and not origin.startswith("https://"):
                logger.warning(
                    "Rejecting non-HTTPS CORS origin in production: %s", origin
                )
                continue
            allowed_origins.append(origin)

    # In production, remove default HTTP dev origins — only CORS_ORIGINS apply
    if environment == "production":
        allowed_origins = [o for o in allowed_origins if o.startswith("https://")]
        if not allowed_origins:
            logger.warning("No CORS origins configured for production. Set CORS_ORIGINS env var.")

    logger.debug("CORS allowed origins: %s", allowed_origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    # Rate limit handler
    from src.api.rate_limit import limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Register routers
    app.include_router(metrics.router)
    app.include_router(status.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(trades.router)
    app.include_router(statistics.router)
    app.include_router(funding.router)
    app.include_router(config.router)
    app.include_router(presets.router)
    app.include_router(exchanges.router)
    app.include_router(bots.router)
    app.include_router(tax_report.router)
    app.include_router(affiliate.router)
    app.include_router(backtest.router)
    app.include_router(portfolio.router)
    app.include_router(websocket.router)
    app.include_router(admin_logs.router)

    # Store WebSocket manager on app state for access
    from src.api.websocket.manager import ws_manager
    app.state.ws_manager = ws_manager

    # Serve frontend static files (built React app)
    frontend_dir = Path("static/frontend")
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    else:
        logger.info("Frontend not built yet - API-only mode")

    return app


# Default app instance
app = create_app()
