"""Health check and status endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.api.rate_limit import limiter
from src.models.session import get_session
from src.utils.logger import get_logger

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
    """Get overall system status (no version info for security)."""
    return {
        "status": "running",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
