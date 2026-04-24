"""Tests for the HTTP metrics middleware (#327 PR-2).

Contract coverage
-----------------

1. Flag OFF — no observation happens, request still flows through.
2. Flag ON, happy path — counter/histogram/gauge are updated with the
   matched route template and the real status code.
3. Flag ON, parametrised route — a request against ``/api/bots/42``
   reports ``path="/api/bots/{bot_id}"`` (template form), NEVER the
   concrete path — otherwise Prometheus cardinality would explode.
4. Flag ON, unmatched path — a request against ``/does-not-exist``
   reports ``path="<unmatched>"`` (sentinel from
   :data:`src.api.middleware.metrics.UNMATCHED_PATH`), not the raw
   request path.
5. Flag ON, handler raises — counter increments with ``status="500"``
   and ``http_requests_in_flight`` returns to zero (no leak).
6. ``/metrics`` endpoint itself is not instrumented — a request
   against ``/metrics`` must leave the HTTP counters untouched to
   prevent self-observation noise.

Registry isolation
------------------
The observability registry is a single process-global
``CollectorRegistry`` (PR-1). Counters / gauges cannot be reset
in-place, so these tests diff the label-specific ``_value.get()``
before and after each request instead of asserting absolute values.
This keeps the tests robust against other tests in the same process
that may have touched the same labels previously.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

# Ensure repo root on sys.path before importing src.* — mirrors the
# pattern used by tests/unit/observability/test_metrics_endpoint.py.
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo=")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _counter_value(counter, **labels) -> float:
    """Read the current value of a ``prometheus_client`` Counter / Gauge.

    prometheus_client exposes the current value via the private
    ``_value.get()`` attribute on the per-label child. We rely on this
    rather than parsing the exposition body to keep tests precise and
    independent of formatting.
    """
    return counter.labels(**labels)._value.get()


def _histogram_sum(histogram, **labels) -> float:
    """Return the ``_sum`` of a labelled ``prometheus_client`` Histogram.

    A non-zero sum proves at least one observation landed on the
    histogram without having to inspect individual bucket counters.
    """
    return histogram.labels(**labels)._sum.get()


def _build_app() -> FastAPI:
    """Build a tiny FastAPI app wrapping :class:`MetricsMiddleware`.

    The surface is intentionally minimal — a static healthz, a
    parametrised route, and an exception-raising route — so that the
    tests do not pull in the full application's DB / orchestrator
    startup.
    """
    from fastapi.responses import JSONResponse

    from src.api.middleware.metrics import MetricsMiddleware

    app = FastAPI()

    @app.exception_handler(RuntimeError)
    async def _runtime_error_handler(request, exc):
        # Translate unhandled RuntimeError into a 500 response the way
        # the production app does via its global exception handler —
        # otherwise httpx's ASGITransport propagates the exception out
        # of the middleware and the test can't assert on status code.
        return JSONResponse(status_code=500, content={"detail": "internal"})

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/api/bots/{bot_id}")
    async def get_bot(bot_id: int):
        return {"id": bot_id}

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("kaboom")

    @app.get("/api/not-found")
    async def emit_not_found():
        raise HTTPException(status_code=404, detail="nope")

    app.add_middleware(MetricsMiddleware)
    return app


@pytest.fixture
def app_with_middleware() -> FastAPI:
    return _build_app()


@pytest.fixture
def enable_prometheus(monkeypatch):
    """Turn ``prometheus_enabled`` on for the duration of a single test."""
    from config.settings import settings

    monkeypatch.setattr(settings.monitoring, "prometheus_enabled", True)
    yield


@pytest.fixture
def disable_prometheus(monkeypatch):
    """Force ``prometheus_enabled`` off for the duration of a single test."""
    from config.settings import settings

    monkeypatch.setattr(settings.monitoring, "prometheus_enabled", False)
    yield


# ---------------------------------------------------------------------------
# 1. Flag OFF → no metric observation
# ---------------------------------------------------------------------------

async def test_flag_off_does_not_touch_metrics(
    app_with_middleware, disable_prometheus
):
    """Flag off: request still flows through, counter is not touched."""
    from src.observability.metrics import HTTP_REQUESTS_TOTAL

    before = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", path="/healthz", status="200"
    )

    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")

    assert resp.status_code == 200
    after = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", path="/healthz", status="200"
    )
    assert after == before, "flag off must not increment the counter"


# ---------------------------------------------------------------------------
# 2. Flag ON, happy path
# ---------------------------------------------------------------------------

async def test_flag_on_static_route_increments_counter_and_histogram(
    app_with_middleware, enable_prometheus
):
    from src.observability.metrics import (
        HTTP_REQUESTS_IN_FLIGHT,
        HTTP_REQUESTS_TOTAL,
        HTTP_REQUEST_DURATION_SECONDS,
    )

    before_total = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", path="/healthz", status="200"
    )
    before_sum = _histogram_sum(
        HTTP_REQUEST_DURATION_SECONDS, method="GET", path="/healthz"
    )

    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")

    assert resp.status_code == 200

    assert (
        _counter_value(
            HTTP_REQUESTS_TOTAL, method="GET", path="/healthz", status="200"
        )
        == before_total + 1
    )
    # Histogram sum must advance by the observed duration; any strictly
    # positive delta proves ``.observe`` was called.
    assert (
        _histogram_sum(
            HTTP_REQUEST_DURATION_SECONDS, method="GET", path="/healthz"
        )
        > before_sum
    )
    # In-flight must end at zero for this label (no leak).
    assert (
        _counter_value(HTTP_REQUESTS_IN_FLIGHT, method="GET", path="/healthz")
        == 0
    )


# ---------------------------------------------------------------------------
# 3. Flag ON, parametrised route → template path collapsing
# ---------------------------------------------------------------------------

async def test_flag_on_parametrised_path_is_collapsed_to_template(
    app_with_middleware, enable_prometheus
):
    """``/api/bots/42`` MUST be recorded as ``/api/bots/{bot_id}``."""
    from src.observability.metrics import HTTP_REQUESTS_TOTAL

    template = "/api/bots/{bot_id}"
    before = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", path=template, status="200"
    )

    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/bots/42")
        assert resp.status_code == 200
        resp = await client.get("/api/bots/99")
        assert resp.status_code == 200

    after = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", path=template, status="200"
    )
    assert after == before + 2, (
        "two requests against two different bot IDs must both collapse "
        "onto the single template label — Prometheus cardinality guard"
    )

    # And the raw path MUST NOT appear as a label value — otherwise
    # Prometheus series would explode by bot ID.
    raw_value = _counter_value(
        HTTP_REQUESTS_TOTAL, method="GET", path="/api/bots/42", status="200"
    )
    assert raw_value == 0, "raw request path must never appear as a label"


# ---------------------------------------------------------------------------
# 4. Flag ON, unmatched path → <unmatched> sentinel
# ---------------------------------------------------------------------------

async def test_flag_on_unmatched_path_uses_sentinel_label(
    app_with_middleware, enable_prometheus
):
    from src.api.middleware.metrics import UNMATCHED_PATH
    from src.observability.metrics import HTTP_REQUESTS_TOTAL

    before = _counter_value(
        HTTP_REQUESTS_TOTAL,
        method="GET",
        path=UNMATCHED_PATH,
        status="404",
    )

    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/this-route-does-not-exist")

    assert resp.status_code == 404

    after = _counter_value(
        HTTP_REQUESTS_TOTAL,
        method="GET",
        path=UNMATCHED_PATH,
        status="404",
    )
    assert after == before + 1

    # The raw path MUST NOT be recorded as a label value.
    assert (
        _counter_value(
            HTTP_REQUESTS_TOTAL,
            method="GET",
            path="/this-route-does-not-exist",
            status="404",
        )
        == 0
    )


# ---------------------------------------------------------------------------
# 5. Flag ON, handler raises → status=500 and IN_FLIGHT returns to zero
# ---------------------------------------------------------------------------

async def test_flag_on_handler_exception_records_500_and_drains_in_flight(
    app_with_middleware, enable_prometheus
):
    from src.observability.metrics import (
        HTTP_REQUESTS_IN_FLIGHT,
        HTTP_REQUESTS_TOTAL,
    )

    before = _counter_value(
        HTTP_REQUESTS_TOTAL,
        method="GET",
        path="/api/boom",
        status="500",
    )

    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/boom")

    # FastAPI's default exception handler maps RuntimeError to a 500.
    assert resp.status_code == 500

    assert (
        _counter_value(
            HTTP_REQUESTS_TOTAL,
            method="GET",
            path="/api/boom",
            status="500",
        )
        == before + 1
    )
    assert (
        _counter_value(HTTP_REQUESTS_IN_FLIGHT, method="GET", path="/api/boom")
        == 0
    ), "in-flight gauge must return to 0 after an exception (no leak)"


# ---------------------------------------------------------------------------
# 6. /metrics endpoint itself is not instrumented
# ---------------------------------------------------------------------------

async def test_metrics_endpoint_is_not_self_instrumented(
    enable_prometheus, monkeypatch
):
    """Probing ``/metrics`` MUST NOT increment any HTTP counter.

    Otherwise every Prometheus scrape (default: every 15 s) would show
    up in the HTTP panels as perpetual traffic without telling anyone
    anything useful.
    """
    from src.api.middleware.metrics import MetricsMiddleware, UNMATCHED_PATH
    from src.api.routers import metrics as metrics_router
    from src.observability.metrics import HTTP_REQUESTS_TOTAL

    monkeypatch.setenv("METRICS_BASIC_AUTH_USER", "prom")
    monkeypatch.setenv("METRICS_BASIC_AUTH_PASSWORD", "s3cret-long-enough")

    app = FastAPI()
    app.include_router(metrics_router.router)
    app.add_middleware(MetricsMiddleware)

    # Snapshot every plausible label combo the middleware could touch
    # for this path.
    baselines = {
        (path, status): _counter_value(
            HTTP_REQUESTS_TOTAL, method="GET", path=path, status=status
        )
        for path in ("/metrics", UNMATCHED_PATH)
        for status in ("200", "401", "404")
    }

    import base64

    token = base64.b64encode(b"prom:s3cret-long-enough").decode("ascii")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/metrics", headers={"Authorization": f"Basic {token}"}
        )

    assert resp.status_code == 200

    for (path, status), baseline in baselines.items():
        current = _counter_value(
            HTTP_REQUESTS_TOTAL, method="GET", path=path, status=status
        )
        assert current == baseline, (
            f"/metrics must not be self-instrumented, but label "
            f"(path={path!r}, status={status!r}) changed {baseline} → {current}"
        )
