"""
FastAPI application factory.

Creates the main application with all routers, middleware,
database lifecycle, and static file serving.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, Response  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402

from src.api.routers import (  # noqa: E402
    admin_logs,
    affiliate,
    auth,
    auth_bridge,
    bots,
    config,
    config_audit,
    exchanges,
    funding,
    metrics,
    notifications,
    portfolio,
    statistics,
    status,
    tax_report,
    trades,
    trades_stream,
    users,
    websocket,
)
from src.models.session import close_db, init_db  # noqa: E402
from src.utils.logger import get_logger, request_id_var, setup_logging  # noqa: E402

setup_logging(log_level=os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request for log correlation.

    ARCH-H6: the ID is also stored in a ``contextvars.ContextVar`` so every
    ``logger.*`` call emitted during this request has ``request_id`` set on
    the LogRecord (via ``RequestIDLogFilter``). The token is reset in the
    finally block so we never leak a stale ID across requests.
    """

    async def dispatch(self, request: Request, call_next):
        import uuid
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)


class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    """Redirect HTTP to HTTPS in production when behind a reverse proxy.

    Checks the X-Forwarded-Proto header set by Nginx/Caddy/Traefik.
    Only active when ENVIRONMENT=production.
    """

    async def dispatch(self, request: Request, call_next):
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment == "production":
            proto = request.headers.get("x-forwarded-proto", "https")
            if proto == "http":
                url = str(request.url).replace("http://", "https://", 1)
                return Response(status_code=301, headers={"Location": url})
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-API-Version"] = "1"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # SEC-P3: Prevent caching of authenticated API responses in
        # shared proxies/browser caches. Static assets served from "/"
        # (via StaticFiles) keep their own Cache-Control; we only patch
        # /api/* responses so the SPA build can still be cached.
        if request.url.path.startswith("/api/") and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        # SEC-H1: script-src must NOT include 'unsafe-inline' — Vite's
        # production build does not emit inline <script> blocks, so 'self'
        # is sufficient. style-src still allows 'unsafe-inline' because
        # Vite/Tailwind ship small per-chunk <style> tags in the built
        # index.html; that is a meaningfully smaller risk surface than
        # inline scripts and removing it would require hash-tracking every
        # build output.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' wss: https:; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), "
            "payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment == "production" or os.getenv("ENABLE_HSTS", "false").lower() == "true":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
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

    # Initialize multibot orchestrator
    from src.bot.orchestrator import BotOrchestrator
    orchestrator = BotOrchestrator()
    app.state.orchestrator = orchestrator

    # Restore bots that were running before shutdown
    await orchestrator.restore_on_startup()

    # Periodic background job: retry pending affiliate UID verifications.
    # Runs every 30 minutes against the orchestrator's shared scheduler so
    # users whose UID couldn't be verified at submission time (e.g. admin
    # had no live keys yet, or the API hiccupped) get auto-verified later.
    from src.services.affiliate_retry import retry_pending_verifications
    if not orchestrator._scheduler.running:
        orchestrator._scheduler.start()
    orchestrator._scheduler.add_job(
        retry_pending_verifications,
        "interval",
        minutes=30,
        id="affiliate_retry_pending",
        replace_existing=True,
    )

    # Affiliate revenue fetcher: pull commission data from each exchange every 6h.
    # Bitget/Weex/BingX use signed REST calls; Hyperliquid uses the public
    # /info referral endpoint with cumulative-delta tracking. Bitunix has no
    # public API and reports "unsupported".
    from src.services.affiliate_revenue_fetcher import run_affiliate_fetch
    orchestrator._scheduler.add_job(
        run_affiliate_fetch,
        "interval",
        hours=6,
        id="affiliate_revenue_fetch",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
    )

    # Recover interrupted broadcasts on startup
    await _recover_broadcasts(orchestrator)

    # Start auth bridge code cleanup
    from src.auth.auth_code import auth_code_store
    auth_code_store.start_cleanup()

    # Start Prometheus bot-metrics collector
    from src.monitoring.collectors import collect_bot_metrics
    from src.monitoring.metrics import APP_INFO, publish_feature_flag_gauge

    APP_INFO.info({"version": "3.0.0", "environment": environment})

    # Observability registry (#327 PR-3): stamp the deployed commit as an
    # info-gauge with value 1 so Grafana can use it for build-over-build
    # diffs. Falls back to "unknown" so the label is never empty.
    try:
        from src.observability.metrics import APP_BUILD_COMMIT

        APP_BUILD_COMMIT.labels(
            commit=os.getenv("BUILD_COMMIT", "unknown"),
        ).set(1)
    except Exception:  # pragma: no cover — observability must never block boot
        logger.debug("APP_BUILD_COMMIT gauge init failed", exc_info=True)

    # #338: publish runtime feature-flag state as a Prometheus gauge so
    # ops can see at a glance which flags are live on the current pod.
    # One label per entry in config.feature_flags.FEATURE_FLAGS; values
    # are strictly 0 or 1 — follows up #327 PR-3.
    publish_feature_flag_gauge()

    collector_task = asyncio.create_task(collect_bot_metrics(app))

    # Start Telegram interactive bot (long-polling for /status, /trades, /pnl)
    from src.telegram.poller import TelegramPoller
    telegram_poller = TelegramPoller()
    await telegram_poller.start()
    app.state.telegram_poller = telegram_poller

    # Optional: automatic bug-detection audit scheduler (#216 Section 2.4).
    # Opt-in via AUTO_AUDIT_ENABLED=true so the default deployment is
    # unchanged until the ops team explicitly turns it on.
    from src.bot.audit_scheduler import build_and_start_if_enabled
    app.state.audit_scheduler = await build_and_start_if_enabled()

    # Exchange WebSocket listeners (#240). Gated process-wide by
    # EXCHANGE_WEBSOCKETS_ENABLED — start_for_user is a no-op when the
    # flag is off, so these calls are safe to always run. Reuses the
    # RiskStateManager singleton so WS events share the per-(trade, leg)
    # lock map with the REST/bot-worker code paths.
    from sqlalchemy import select as _ws_select
    from src.api.dependencies.risk_state import get_risk_state_manager
    from src.bot.ws_credentials_provider import ws_credentials_provider
    from src.bot.ws_manager import WebSocketManager
    from src.models.database import BotConfig as _BotConfig
    from src.models.session import get_session as _ws_get_session

    exchange_ws_manager = WebSocketManager(
        risk_state_manager=get_risk_state_manager(),
        credentials_provider=ws_credentials_provider,
        session_factory=_ws_get_session,
    )
    app.state.exchange_ws_manager = exchange_ws_manager

    try:
        async with _ws_get_session() as ws_session:
            active_pairs_result = await ws_session.execute(
                _ws_select(_BotConfig.user_id, _BotConfig.exchange_type)
                .where(_BotConfig.is_enabled.is_(True))
                .distinct()
            )
            active_pairs = list(active_pairs_result.all())
        for user_id, exchange in active_pairs:
            await exchange_ws_manager.start_for_user(user_id, exchange)
    except Exception as e:  # noqa: BLE001 — WS startup must not block app boot
        logger.warning("Exchange WS startup skipped: %s", e)

    logger.info("Application started successfully")
    yield

    # Shutdown
    logger.info("Shutting down — graceful shutdown initiated...")
    await telegram_poller.stop()
    auth_code_store.stop_cleanup()
    collector_task.cancel()

    # Stop the audit scheduler before the DB closes so in-flight
    # audit reports can still finish their writes.
    audit_scheduler = getattr(app.state, "audit_scheduler", None)
    if audit_scheduler is not None:
        await audit_scheduler.shutdown()

    # Tear down every exchange WS listener (#240). stop_all is
    # best-effort — errors are logged inside the manager.
    exchange_ws_manager = getattr(app.state, "exchange_ws_manager", None)
    if exchange_ws_manager is not None:
        await exchange_ws_manager.stop_all()

    # Graceful bot shutdown: wait for in-flight trades, log open positions.
    # Total timeout of 25s leaves margin within Docker's 30s stop_grace_period.
    try:
        await asyncio.wait_for(
            orchestrator.shutdown_gracefully(grace_period=20.0),
            timeout=25.0,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Graceful shutdown timed out after 25s — force stopping remaining bots"
        )
        # Fall back to hard stop for any stragglers
        try:
            await orchestrator.shutdown_all()
        except Exception as e:
            logger.error("Force shutdown error: %s", e)

    # Drain pending audit + event writes after bots are stopped
    from src.api.middleware.audit_log import drain_pending_audit_tasks
    from src.utils.event_logger import drain_pending_event_tasks
    await drain_pending_audit_tasks(timeout=5.0)
    await drain_pending_event_tasks(timeout=5.0)

    await close_db()
    logger.info("Application shut down")


async def _recover_broadcasts(orchestrator) -> None:
    """Recover broadcasts that were interrupted by a shutdown.

    - status='sending': restart send_broadcast() for each
    - status='scheduled' with scheduled_at <= now: start immediately
    - status='scheduled' with scheduled_at > now: re-register APScheduler jobs
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    try:
        from src.models.broadcast import Broadcast
        from src.models.session import get_session
    except ImportError:
        return

    try:
        async with get_session() as session:
            # Restart interrupted sends
            sending_result = await session.execute(
                select(Broadcast).where(Broadcast.status == "sending")
            )
            for broadcast in sending_result.scalars().all():
                logger.info("Recovering interrupted broadcast #%d", broadcast.id)
                from src.services.broadcast_sender import send_broadcast
                asyncio.create_task(send_broadcast(broadcast.id))

            # Handle scheduled broadcasts
            scheduled_result = await session.execute(
                select(Broadcast).where(Broadcast.status == "scheduled")
            )
            now = datetime.now(timezone.utc)
            scheduler = orchestrator._scheduler

            for broadcast in scheduled_result.scalars().all():
                if broadcast.scheduled_at and broadcast.scheduled_at <= now:
                    logger.info(
                        "Starting overdue scheduled broadcast #%d", broadcast.id
                    )
                    broadcast.status = "sending"
                    broadcast.started_at = now
                    from src.services.broadcast_sender import send_broadcast
                    asyncio.create_task(send_broadcast(broadcast.id))
                elif broadcast.scheduled_at and broadcast.scheduled_at > now:
                    job_id = broadcast.scheduler_job_id or f"broadcast_scheduled_{broadcast.id}"
                    logger.info(
                        "Re-registering scheduled broadcast #%d at %s",
                        broadcast.id, broadcast.scheduled_at,
                    )
                    from src.services.broadcast_sender import send_broadcast
                    scheduler.add_job(
                        send_broadcast,
                        "date",
                        run_date=broadcast.scheduled_at,
                        id=job_id,
                        args=[broadcast.id],
                        replace_existing=True,
                    )
    except Exception as e:
        logger.warning("Broadcast recovery skipped: %s", e)


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
            {"name": "bitunix", "display_name": "Bitunix", "is_enabled": True, "supports_demo": True},
            {"name": "bingx", "display_name": "BingX", "is_enabled": True, "supports_demo": True},
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

        def _coerce(value):
            # Drop raw bytes (may leak secrets), stringify non-JSON-serializable objects
            # like Exception instances that Pydantic v2 attaches to ctx.error when a
            # @field_validator raises ValueError.
            if isinstance(value, bytes):
                return value.decode(errors="replace")
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            if isinstance(value, dict):
                return {k: _coerce(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_coerce(v) for v in value]
            return str(value)

        sanitized = []
        for err in exc.errors():
            clean = {k: _coerce(v) for k, v in err.items() if k != "input"}
            sanitized.append(clean)
        return JSONResponse(status_code=422, content={"detail": sanitized})

    # Audit logging middleware
    # (HTTP metrics are emitted by src.api.middleware.metrics.MetricsMiddleware
    # registered later in this function — #337 removed the legacy
    # src/monitoring/middleware.py which wrote to the default registry.)
    from src.api.middleware.audit_log import AuditLogMiddleware
    app.add_middleware(AuditLogMiddleware)

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # Request ID for log correlation
    app.add_middleware(RequestIDMiddleware)

    # HTTPS redirect (outermost of the runtime middlewares below — CORS
    # and MetricsMiddleware wrap it later so they observe the redirect).
    app.add_middleware(HTTPSRedirectMiddleware)

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
            # Validate that origin is a well-formed URL with scheme and host
            parsed = urlparse(origin)
            if not parsed.scheme or not parsed.netloc:
                logger.warning(
                    "Skipping invalid CORS origin (missing scheme or host): %s", origin
                )
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

    # Hard fail at startup if wildcard + credentials combine: browsers treat
    # that pairing as a CSRF vector and most reject it at runtime, but we
    # refuse to start rather than rely on that. (SEC-004)
    _allow_credentials = True
    if _allow_credentials and any(o.strip() == "*" for o in allowed_origins):
        raise RuntimeError(
            "CORS misconfiguration: allow_origins contains '*' while "
            "allow_credentials=True. This combination is insecure — refusing "
            "to start. Set CORS_ORIGINS to an explicit origin list."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    # HTTP metrics middleware (#327 PR-2) — registered LAST so it is the
    # outermost layer of the middleware stack. Starlette wraps middlewares
    # in reverse registration order, so the last ``add_middleware`` call
    # produces the outermost ASGI wrapper. Outermost placement means the
    # histogram / counter capture the wall-clock cost of every other
    # middleware (CORS, HTTPS redirect, auth, rate limit, security headers)
    # and even CORS preflights show up in ``http_requests_total``.
    # Gated internally by the ``prometheus_enabled`` flag; when the flag
    # is off the middleware is a pure pass-through.
    from src.api.middleware.metrics import MetricsMiddleware
    app.add_middleware(MetricsMiddleware)

    # Rate limit handler
    from src.api.rate_limit import limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Register routers
    app.include_router(metrics.router)
    app.include_router(status.router)
    app.include_router(auth.router)
    app.include_router(auth_bridge.router)
    app.include_router(users.router)
    app.include_router(trades.router)
    app.include_router(trades_stream.router)
    app.include_router(statistics.router)
    app.include_router(funding.router)
    app.include_router(config.router)
    app.include_router(exchanges.router)
    app.include_router(bots.router)
    app.include_router(tax_report.router)
    app.include_router(affiliate.router)
    app.include_router(portfolio.router)
    app.include_router(websocket.router)
    app.include_router(notifications.router)
    app.include_router(config_audit.router)
    app.include_router(admin_logs.router)
    from src.api.routers.copy_trading import router as copy_trading_router
    app.include_router(copy_trading_router)
    from src.api.routers.reconciliation import reconciliation_router
    app.include_router(reconciliation_router)
    from src.api.routers.admin_broadcasts import router as broadcast_router
    app.include_router(broadcast_router)
    from src.api.routers.revenue import router as revenue_router
    app.include_router(revenue_router)

    # Store WebSocket manager on app state for access
    from src.api.websocket.manager import ws_manager
    app.state.ws_manager = ws_manager

    # ARCH-M4: SPA fallback via StaticFiles(html=True). Starlette's StaticFiles
    # already performs path-traversal protection (see starlette.staticfiles.
    # StaticFiles.get_path / get_response); mounting it at "/" with html=True
    # transparently serves index.html for unknown paths so deep React Router
    # routes reload cleanly. Must be registered LAST so it does not shadow
    # /api/* routes.
    frontend_dir = Path("static/frontend")

    if frontend_dir.exists() and not os.getenv("TESTING"):
        app.mount(
            "/",
            StaticFiles(directory=str(frontend_dir), html=True, check_dir=True),
            name="spa",
        )
    else:
        logger.info("Frontend not built yet - API-only mode")

    return app


# Default app instance
app = create_app()
