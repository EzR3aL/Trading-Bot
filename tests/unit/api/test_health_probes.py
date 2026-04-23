"""Tests for the /api/health dependency-probe logic (ARCH-M6, #247).

These complement ``tests/unit/test_status_endpoints.py`` which covers the
happy-path HTTP contract. Here we exercise the individual probe branches
using a monkeypatched app.state so we don't depend on a live DB, a real
APScheduler, or a real WS manager at unit-test time.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.routers import status as status_module
from src.api.routers.status import router


# ── Test helpers ───────────────────────────────────────────────────────


class _FakeWsManager:
    """Stand-in for :class:`ConnectionManager`."""

    def __init__(self, total: int = 3):
        self._total = total

    @property
    def total_connections(self) -> int:
        return self._total


class _FakeExchangeWsManager:
    """Stand-in for :class:`src.bot.ws_manager.WebSocketManager`."""

    def __init__(self, counts: Dict[str, int] | None = None):
        self._counts = counts or {"bitget": 0, "hyperliquid": 0}

    def connected_counts(self) -> Dict[str, int]:
        return dict(self._counts)


class _FakeScheduler:
    def __init__(self, running: bool = True):
        self.running = running


class _FakeWorker:
    def __init__(self, status: str = "running"):
        self.status = status


class _FakeOrchestrator:
    def __init__(self, running: bool = True, workers: Dict[int, Any] | None = None):
        self._scheduler = _FakeScheduler(running=running)
        self._workers = workers or {}


def _build_app(
    *,
    orchestrator: Any = None,
    ws_manager: Any = None,
    exchange_ws_manager: Any = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.orchestrator = orchestrator or _FakeOrchestrator()
    app.state.ws_manager = ws_manager or _FakeWsManager()
    if exchange_ws_manager is not None:
        app.state.exchange_ws_manager = exchange_ws_manager
    return app


@pytest.fixture(autouse=True)
def _reset_breaker():
    """Reset DB circuit breaker before each test."""
    from src.models.session import _db_breaker
    from src.utils.circuit_breaker import CircuitState, CircuitStats

    _db_breaker._state = CircuitState.CLOSED
    _db_breaker._stats = CircuitStats()


# ── Probe-level unit tests (no HTTP) ───────────────────────────────────


@pytest.mark.asyncio
async def test_scheduler_probe_reports_running():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestrator=_FakeOrchestrator(running=True)
    )))
    result = await status_module._probe_scheduler(request)
    assert result == {"ok": True, "running": True}


@pytest.mark.asyncio
async def test_scheduler_probe_reports_stopped():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        orchestrator=_FakeOrchestrator(running=False)
    )))
    result = await status_module._probe_scheduler(request)
    assert result["ok"] is False
    assert result["running"] is False


@pytest.mark.asyncio
async def test_scheduler_probe_missing_orchestrator():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    result = await status_module._probe_scheduler(request)
    assert result["ok"] is False
    assert "orchestrator" in result["error"]


@pytest.mark.asyncio
async def test_ws_broker_probe_reports_count():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        ws_manager=_FakeWsManager(total=7)
    )))
    result = await status_module._probe_ws_broker(request)
    assert result == {"ok": True, "connections": 7}


@pytest.mark.asyncio
async def test_ws_broker_probe_missing_manager():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    result = await status_module._probe_ws_broker(request)
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_run_probe_catches_timeout():
    async def slow_probe() -> Dict[str, Any]:
        await asyncio.sleep(5)
        return {"ok": True}

    result = await status_module._run_probe(slow_probe, timeout=0.05)
    assert result["ok"] is False
    assert "timeout" in result["error"]


@pytest.mark.asyncio
async def test_run_probe_catches_exception():
    async def boom_probe() -> Dict[str, Any]:
        raise RuntimeError("kaboom")

    result = await status_module._run_probe(boom_probe, timeout=1.0)
    assert result["ok"] is False
    assert "RuntimeError" in result["error"]
    assert "kaboom" in result["error"]


# ── Endpoint-level HTTP tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_all_ok_returns_200(monkeypatch):
    async def ok_db() -> Dict[str, Any]:
        return {"ok": True, "latency_ms": 2}

    monkeypatch.setattr(status_module, "_probe_database", ok_db)

    app = _build_app(exchange_ws_manager=_FakeExchangeWsManager())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    # Literal string preserved for docker-compose healthcheck parsing.
    assert data["status"] == "healthy"
    assert data["checks"]["database"]["ok"] is True
    assert data["checks"]["scheduler"]["ok"] is True
    assert data["checks"]["ws_broker"]["ok"] is True
    assert data["checks"]["exchange_ws"]["ok"] is True
    # Legacy top-level fields still present.
    assert "ws_connections" in data
    assert "timestamp" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_health_db_failure_returns_503(monkeypatch):
    async def broken_db() -> Dict[str, Any]:
        raise RuntimeError("db down")

    monkeypatch.setattr(status_module, "_probe_database", broken_db)

    app = _build_app(exchange_ws_manager=_FakeExchangeWsManager())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["database"]["ok"] is False
    # Other probes are still reported.
    assert "scheduler" in data["checks"]
    assert "ws_broker" in data["checks"]


@pytest.mark.asyncio
async def test_health_optional_probe_failure_is_degraded(monkeypatch):
    async def ok_db() -> Dict[str, Any]:
        return {"ok": True, "latency_ms": 1}

    monkeypatch.setattr(status_module, "_probe_database", ok_db)

    # Scheduler is stopped but DB is fine — should be degraded, HTTP 200.
    app = _build_app(
        orchestrator=_FakeOrchestrator(running=False),
        exchange_ws_manager=_FakeExchangeWsManager(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["checks"]["scheduler"]["ok"] is False
    assert data["checks"]["database"]["ok"] is True


@pytest.mark.asyncio
async def test_health_exchange_ws_missing_is_absent_from_dict(monkeypatch):
    """When exchange_ws_manager is not registered, the probe reports a
    clean ``ok=false`` rather than hanging or raising. The key exists but
    carries an explicit error so monitoring can distinguish
    'not configured' from 'configured but down'."""
    async def ok_db() -> Dict[str, Any]:
        return {"ok": True, "latency_ms": 1}

    monkeypatch.setattr(status_module, "_probe_database", ok_db)

    app = _build_app()  # no exchange_ws_manager
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")

    data = resp.json()
    assert data["checks"]["exchange_ws"]["ok"] is False
    assert "not on app.state" in data["checks"]["exchange_ws"]["error"]
    # DB is still ok, so top status should be degraded (exchange_ws is
    # non-critical) rather than unhealthy.
    assert resp.status_code == 200
    assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_probe_timeout_does_not_hang_endpoint(monkeypatch):
    """A hung probe must resolve to ok=false within the per-probe
    timeout and not stall the endpoint."""
    async def ok_db() -> Dict[str, Any]:
        return {"ok": True, "latency_ms": 1}

    async def hung_ws(request: Any) -> Dict[str, Any]:
        await asyncio.sleep(10)
        return {"ok": True}

    monkeypatch.setattr(status_module, "_probe_database", ok_db)
    monkeypatch.setattr(status_module, "_probe_ws_broker", hung_ws)
    # Shorten the per-probe timeout for the test so we don't actually
    # wait 2.5 s. 0.15 s is plenty to prove the wait_for kicks in.
    monkeypatch.setattr(status_module, "_PROBE_TIMEOUT_S", 0.15)
    monkeypatch.setattr(status_module, "_OVERALL_PROBE_TIMEOUT_S", 1.0)

    app = _build_app(exchange_ws_manager=_FakeExchangeWsManager())

    loop_start = asyncio.get_event_loop().time()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")
    elapsed = asyncio.get_event_loop().time() - loop_start

    # Endpoint must return in well under the 10 s sleep.
    assert elapsed < 2.0, f"Endpoint took {elapsed}s, probe timeout didn't fire"
    data = resp.json()
    assert data["checks"]["ws_broker"]["ok"] is False
    assert "timeout" in data["checks"]["ws_broker"]["error"]
    # DB ok + ws_broker failure => degraded, 200.
    assert resp.status_code == 200
    assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_preserves_docker_healthcheck_contract(monkeypatch):
    """docker-compose.yml greps ``d.get('status') == 'healthy'``. Make
    sure the happy-path literal is exactly that string."""
    async def ok_db() -> Dict[str, Any]:
        return {"ok": True, "latency_ms": 1}

    monkeypatch.setattr(status_module, "_probe_database", ok_db)

    app = _build_app(exchange_ws_manager=_FakeExchangeWsManager())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")

    assert resp.json()["status"] == "healthy"
