"""
FastAPI application factory.

Creates the main application with all routers, middleware,
database lifecycle, and static file serving.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from src.api.routers import (
    auth,
    bot_control,
    bots,
    config,
    exchanges,
    funding,
    presets,
    statistics,
    status,
    tax_report,
    trades,
    users,
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
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if os.getenv("ENABLE_HSTS", "false").lower() == "true":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle: startup and shutdown."""
    # Validate JWT configuration before anything else
    from src.auth.jwt_handler import validate_jwt_config
    validate_jwt_config()

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

    # Initialize legacy bot manager (kept for backward compat of /api/bot endpoints)
    from src.bot.bot_manager import BotManager
    bot_manager = BotManager()
    bot_control.set_bot_manager(bot_manager)
    app.state.bot_manager = bot_manager

    # Initialize multibot orchestrator
    from src.bot.orchestrator import BotOrchestrator
    orchestrator = BotOrchestrator()
    bots.set_orchestrator(orchestrator)
    app.state.orchestrator = orchestrator

    # Restore bots that were running before shutdown
    await orchestrator.restore_on_startup()

    logger.info("Application started successfully")
    yield

    # Shutdown
    logger.info("Shutting down...")
    await orchestrator.shutdown_all()
    await bot_manager.shutdown_all()
    await close_db()
    logger.info("Application shut down")


async def _seed_exchanges():
    """Seed the exchanges table with supported exchanges."""
    from sqlalchemy import select

    from src.models.database import Exchange
    from src.models.session import get_session

    async with get_session() as session:
        result = await session.execute(select(Exchange))
        if result.scalars().first():
            return  # Already seeded

        exchanges_data = [
            Exchange(name="bitget", display_name="Bitget", is_enabled=True, supports_demo=True),
            Exchange(name="weex", display_name="Weex", is_enabled=True, supports_demo=True),
            Exchange(name="hyperliquid", display_name="Hyperliquid", is_enabled=True, supports_demo=True),
        ]
        session.add_all(exchanges_data)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Trading Bot API",
        description="Multi-Exchange Trading Bot with Web UI",
        version="3.0.0",
        lifespan=lifespan,
    )

    # Global exception handler — sanitizes error responses in production
    from src.api.middleware.error_handler import global_exception_handler
    app.add_exception_handler(Exception, global_exception_handler)

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

    logger.info("CORS allowed origins: %s", allowed_origins)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    # Rate limit handler
    from src.api.routers.auth import limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Register routers
    app.include_router(status.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(trades.router)
    app.include_router(statistics.router)
    app.include_router(funding.router)
    app.include_router(config.router)
    app.include_router(presets.router)
    app.include_router(exchanges.router)
    app.include_router(bot_control.router)
    app.include_router(bots.router)
    app.include_router(tax_report.router)

    # Serve frontend static files (built React app)
    frontend_dir = Path("static/frontend")
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    else:
        logger.info("Frontend not built yet - API-only mode")

    return app


# Default app instance
app = create_app()
