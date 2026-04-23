"""Health check and status endpoints."""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.middleware.audit_log import get_audit_failure_count
from src.api.rate_limit import limiter
from src.auth.dependencies import get_current_user
from src.models.database import User
from src.models.session import get_session
from src.utils.logger import get_logger

# SEC-L1: resolve build version from BUILD_COMMIT / GIT_COMMIT env vars
# populated at Docker build time (see Dockerfile's ARG BUILD_COMMIT).
# The previous implementation called `git rev-parse --short HEAD` via
# subprocess at import time, which requires a .git/ tree inside the
# container (not present in the production image) and adds a needless
# process spawn on every cold start.
_GIT_COMMIT = (
    os.environ.get("BUILD_COMMIT", "").strip()
    or os.environ.get("GIT_COMMIT", "").strip()
    or "unknown"
)

logger = get_logger(__name__)

router = APIRouter(tags=["status"])


@router.get("/api/health")
@limiter.limit("30/minute")
async def health_check(request: Request):
    """Health check endpoint with DB and orchestrator verification."""
    checks = {"database": "ok", "bots": "ok"}

    # Database connectivity
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("Health check: DB unreachable: %s", e)
        checks["database"] = "unreachable"

    # Orchestrator: count bots in error state
    try:
        orchestrator = request.app.state.orchestrator
        workers = orchestrator._workers
        error_count = sum(1 for w in workers.values() if w.status == "error")
        total_count = len(workers)
        if error_count > 0:
            checks["bots"] = f"{error_count}/{total_count} in error state"
    except Exception:
        pass

    # Expose audit write failure count so monitoring can detect silent gaps
    audit_failures = get_audit_failure_count()
    if audit_failures > 0:
        checks["audit_log_failures"] = audit_failures

    # Exchange WS listener health (#216). Always emitted — zero counts
    # are the expected default when the feature flag is off, and make
    # it easy for monitoring to alert if a listener drops mid-session.
    ws_connections = {"bitget": 0, "hyperliquid": 0}
    try:
        exchange_ws_manager = getattr(
            request.app.state, "exchange_ws_manager", None
        )
        if exchange_ws_manager is not None:
            ws_connections.update(exchange_ws_manager.connected_counts())
    except Exception as e:  # noqa: BLE001 — health must never itself fail
        logger.debug("Health check: exchange_ws_manager read failed: %s", e)

    is_healthy = checks["database"] == "ok"
    status = "healthy" if is_healthy else "unhealthy"

    result = {
        "status": status,
        "checks": checks,
        "ws_connections": ws_connections,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if not is_healthy:
        return JSONResponse(status_code=503, content=result)

    return result


@router.get("/api/status")
async def get_status():
    """Get overall system status."""
    return {
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/version")
async def get_version(_user: User = Depends(get_current_user)):
    """Return build version for deploy verification.

    SEC-L1: auth-required. Not consumed by any unauth monitor in this
    codebase (verified via grep: no ``/api/version`` callers in frontend
    or monitoring config), so hiding the commit SHA behind ``get_current_user``
    is safe and prevents leaking internal build metadata to the public.
    """
    return {"commit": _GIT_COMMIT}
