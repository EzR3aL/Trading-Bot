"""Health check and status endpoints.

ARCH-M6 (#247): ``/api/health`` actively probes critical dependencies
(DB, APScheduler, internal WS manager, exchange WS manager) in parallel
with per-probe timeouts. A failure of the single critical probe (DB)
returns HTTP 503 so Docker/compose/uptime monitors alert instead of
seeing a static 200.

Compatibility: the Docker healthcheck in ``docker-compose.yml`` reads
``d.get('status') == 'healthy'``, so we preserve the literal string
``"healthy"`` for the all-OK case (instead of ``"ok"``). A degraded
state is reported with ``status="degraded"`` and still returns HTTP 200
because non-critical dependencies should not page operators. Only a DB
failure flips to HTTP 503 + ``status="unhealthy"``.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Tuple

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


# ── Probe timeouts ─────────────────────────────────────────────────────
# Per-probe hard deadline. Chosen so a hung dependency can't stall the
# endpoint past Docker's 10 s healthcheck timeout. Total wall-clock is
# additionally capped below so even N stalled probes finish well under
# the outer timeout.
_PROBE_TIMEOUT_S = 2.5
# Outer cap for the asyncio.gather that runs all probes in parallel.
# Probes run concurrently so this is ~per-probe, not sum-of-probes.
_OVERALL_PROBE_TIMEOUT_S = 5.0


async def _probe_database() -> Dict[str, Any]:
    """Probe DB with a trivial ``SELECT 1``."""
    started = time.perf_counter()
    async with get_session() as session:
        await session.execute(text("SELECT 1"))
    return {
        "ok": True,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


async def _probe_scheduler(request: Request) -> Dict[str, Any]:
    """Probe the orchestrator's APScheduler instance."""
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        return {"ok": False, "error": "orchestrator not on app.state"}
    scheduler = getattr(orchestrator, "_scheduler", None)
    if scheduler is None:
        return {"ok": False, "error": "scheduler not initialised"}
    running = bool(getattr(scheduler, "running", False))
    return {"ok": running, "running": running}


async def _probe_ws_broker(request: Request) -> Dict[str, Any]:
    """Probe the internal WebSocket ConnectionManager singleton."""
    ws_manager = getattr(request.app.state, "ws_manager", None)
    if ws_manager is None:
        return {"ok": False, "error": "ws_manager not on app.state"}
    # total_connections is a cheap property; no I/O, no lock.
    try:
        connections = int(ws_manager.total_connections)
    except Exception as exc:  # noqa: BLE001 — health must never itself fail
        return {"ok": False, "error": f"total_connections failed: {exc}"}
    return {"ok": True, "connections": connections}


async def _probe_exchange_ws(request: Request) -> Dict[str, Any]:
    """Probe the exchange WS manager (optional — flag-gated in prod)."""
    manager = getattr(request.app.state, "exchange_ws_manager", None)
    if manager is None:
        return {"ok": False, "error": "exchange_ws_manager not on app.state"}
    counts = manager.connected_counts()
    return {"ok": True, "connections": dict(counts)}


async def _run_probe(
    probe: Callable[[], Awaitable[Dict[str, Any]]],
    timeout: float,
) -> Dict[str, Any]:
    """Run ``probe`` under ``timeout``; never raise.

    Any exception — including :class:`asyncio.TimeoutError` — is captured
    and reported as ``{"ok": False, "error": "..."}`` so a single bad
    probe can't bring down the health endpoint itself.
    """
    try:
        return await asyncio.wait_for(probe(), timeout=timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timeout after {timeout}s"}
    except Exception as exc:  # noqa: BLE001 — health must never raise
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/api/health")
@limiter.limit("30/minute")
async def health_check(request: Request):
    """Active health probe for DB, scheduler, and WS brokers.

    Returns HTTP 503 only when the single *critical* probe (database)
    fails. Non-critical probe failures flip the response to
    ``status="degraded"`` while keeping HTTP 200 so that flaky optional
    components don't cause uptime alerts.

    Redis is intentionally omitted: the project does not use Redis
    anywhere (verified via grep). If a Redis dependency is introduced
    later, add a ``_probe_redis`` branch here guarded on
    ``Settings.redis.url``.

    External services (exchange REST, LLM providers) are deliberately
    NOT probed — they are per-bot, rate-limited, and a health endpoint
    must not DoS them on every uptime poll.
    """

    # Build the set of probes in parallel. Each probe is pre-wrapped so
    # an exception in one probe never cancels the others. We still put
    # an outer ``wait_for`` around ``gather`` as a belt-and-braces cap
    # in case the scheduler loop itself gets starved.
    probe_coros: list[Tuple[str, Awaitable[Dict[str, Any]]]] = [
        ("database", _run_probe(_probe_database, _PROBE_TIMEOUT_S)),
        ("scheduler", _run_probe(lambda: _probe_scheduler(request), _PROBE_TIMEOUT_S)),
        ("ws_broker", _run_probe(lambda: _probe_ws_broker(request), _PROBE_TIMEOUT_S)),
        (
            "exchange_ws",
            _run_probe(lambda: _probe_exchange_ws(request), _PROBE_TIMEOUT_S),
        ),
    ]
    names = [name for name, _ in probe_coros]
    coros = [c for _, c in probe_coros]

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=False),
            timeout=_OVERALL_PROBE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        # Defensive only: individual probes already enforce their own
        # timeout, so the gather should always complete. If we land here
        # the event loop itself is wedged — report everything as failed.
        logger.error("Health check: outer gather timed out")
        results = [
            {"ok": False, "error": "outer-timeout"} for _ in coros
        ]

    checks: Dict[str, Dict[str, Any]] = dict(zip(names, results))

    # ── Assemble audit-log failure counter ────────────────────────────
    # Surfaced alongside probes so monitoring can alert on silent audit
    # gaps without adding a separate endpoint.
    audit_failures = get_audit_failure_count()
    if audit_failures > 0:
        checks["audit_log_failures"] = {
            "ok": False,
            "count": audit_failures,
        }

    # ── Optional: orchestrator bot-error count ────────────────────────
    # Kept for backwards compatibility with the previous shape which
    # exposed ``bots`` under ``checks``. Read-only, no awaits.
    try:
        orchestrator = request.app.state.orchestrator
        workers = getattr(orchestrator, "_workers", {})
        error_count = sum(1 for w in workers.values() if getattr(w, "status", None) == "error")
        total_count = len(workers)
        checks["bots"] = {
            "ok": error_count == 0,
            "errors": error_count,
            "total": total_count,
        }
    except Exception:  # noqa: BLE001
        pass

    # ── Derive HTTP status + top-level status string ──────────────────
    # DB is the only critical probe. Everything else is "nice to know"
    # for the operator but should not page.
    db_ok = bool(checks.get("database", {}).get("ok"))
    non_critical_failures = [
        name
        for name, result in checks.items()
        if name not in ("database", "audit_log_failures", "bots")
        and not result.get("ok")
    ]

    if not db_ok:
        # Literal "unhealthy" preserved for any external tooling that
        # already parses it.
        top_status = "unhealthy"
        http_status = 503
    elif non_critical_failures:
        top_status = "degraded"
        http_status = 200
    else:
        # Literal "healthy" is what the Docker healthcheck in
        # docker-compose.yml greps for — do not change this string.
        top_status = "healthy"
        http_status = 200

    # ── Backwards-compat: keep the old ``ws_connections`` top-level
    # field so existing dashboards/uptime parsers don't break.
    ws_connections = {"bitget": 0, "hyperliquid": 0}
    exchange_ws_result = checks.get("exchange_ws", {})
    if exchange_ws_result.get("ok"):
        ws_connections.update(exchange_ws_result.get("connections", {}))

    result = {
        "status": top_status,
        "checks": checks,
        "ws_connections": ws_connections,
        "version": _GIT_COMMIT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if http_status != 200:
        return JSONResponse(status_code=http_status, content=result)
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
