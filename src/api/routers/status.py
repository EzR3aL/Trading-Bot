"""Health check and status endpoints."""

import os
import subprocess
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.middleware.audit_log import get_audit_failure_count
from src.api.rate_limit import limiter
from src.models.session import get_session
from src.utils.logger import get_logger

# Resolve build version at import time (once, not per request)
# In Docker: read from BUILD_COMMIT env var (set during build)
# Fallback: try git, then "unknown"
_GIT_COMMIT = os.environ.get("BUILD_COMMIT", "").strip()
if not _GIT_COMMIT:
    try:
        _GIT_COMMIT = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        _GIT_COMMIT = "unknown"

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

    is_healthy = checks["database"] == "ok"
    status = "healthy" if is_healthy else "unhealthy"

    result = {
        "status": status,
        "checks": checks,
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
async def get_version():
    """Return build version for deploy verification."""
    return {"commit": _GIT_COMMIT}
