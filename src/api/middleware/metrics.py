"""HTTP metrics middleware (#327 PR-2).

Emits the three HTTP metrics defined in ``src/observability/metrics.py``
on every request:

* ``http_requests_total{method, path, status}`` — Counter.
* ``http_request_duration_seconds{method, path}`` — Histogram.
* ``http_requests_in_flight{method, path}`` — Gauge (inc / dec).

Cardinality control
-------------------
``path`` is the **template** form of the matched FastAPI route
(``/api/bots/{bot_id}``), never the concrete request path
(``/api/bots/42``). Without this collapse the Prometheus series count
would grow linearly with every bot ID / trade ID / user ID the API
ever sees. Starlette records the matched route on ``scope["route"]``
after the router has resolved the request; we iterate the app's
routes up-front with ``Route.matches(scope)`` to pre-resolve the
template so the in-flight gauge and the counter share the same
label value even in the exception path.

When no route matched (404 → :data:`UNMATCHED_PATH` sentinel) we fall
back to a fixed label so the raw request path never appears as a
label value.

Exception path
--------------
All bookkeeping runs in a ``try/finally`` so a handler exception still
decrements ``HTTP_REQUESTS_IN_FLIGHT`` and records a 500 in
``HTTP_REQUESTS_TOTAL``. The exception is re-raised unchanged so the
FastAPI exception-handler stack still runs.

The ``/metrics`` endpoint itself is **not** instrumented — doing so
would create a self-observing loop every time Prometheus scrapes, and
add noise without telling operators anything useful.

Feature flag
------------
Gated by ``prometheus_enabled`` (read through
``config.feature_flags.feature_flags``). When the flag is off the
middleware is a pass-through — no label allocation, no timing, no
metric observation. The flag is read on every request so runtime
monkeypatching in tests works without reimporting the module.

Implementation notes
--------------------
Written as a pure ASGI middleware (not ``BaseHTTPMiddleware``) so we
can pre-resolve the matched route template with
``Route.matches(scope)`` before the router runs. ``BaseHTTPMiddleware``
wraps ``call_next`` around the router, which means ``scope["route"]``
is only populated *inside* the downstream call — too late for a
consistent IN_FLIGHT label that we need to ``inc`` before and ``dec``
after the downstream app.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Sentinel emitted as the ``path`` label when no FastAPI route matched
# the incoming request (typically 404s). Must not look like a real
# template — angle brackets keep it visually distinct in Grafana.
UNMATCHED_PATH: str = "<unmatched>"


def _resolve_template_path(scope: Scope) -> str:
    """Return the template form of the route that would match ``scope``.

    We iterate over the ASGI app's ``routes`` collection and ask each
    route whether it matches the current scope via
    ``Route.matches(scope)``. The first ``Match.FULL`` wins — that's
    the same lookup rule Starlette's ``Router`` uses internally. If no
    route matches, we return :data:`UNMATCHED_PATH`.

    Iterating over ``routes`` is O(n) in the number of registered
    endpoints, which for this application is bounded (~40). That cost
    is paid once per request and only when the observability flag is
    on, so the overhead is negligible compared with the downstream
    handler (DB queries, exchange calls).
    """
    app = scope.get("app")
    if app is None:
        return UNMATCHED_PATH

    routes = getattr(app, "routes", None)
    if not routes:
        return UNMATCHED_PATH

    for route in routes:
        try:
            match_result, _ = route.matches(scope)
        except Exception:  # noqa: BLE001 — be defensive against custom routes
            continue
        if match_result == Match.FULL:
            template = getattr(route, "path", None)
            if template:
                return template
    return UNMATCHED_PATH


def _prometheus_enabled() -> bool:
    """Read the ``prometheus_enabled`` flag through the registry.

    Imported lazily so tests can monkey-patch
    ``config.settings.settings.monitoring.prometheus_enabled`` at
    runtime and the middleware picks it up on the next request.
    """
    from config.feature_flags import feature_flags

    return feature_flags.get("prometheus_enabled")


class MetricsMiddleware:
    """Record HTTP request metrics for the Prometheus observability registry.

    Registration order: MUST be added last in ``create_app`` so it
    becomes the outermost layer of Starlette's middleware stack. That
    way the histogram / counter cover the wall-clock cost of every
    other middleware (auth, rate limit, security headers) in the
    stack. Other middlewares running after ``call_next`` would
    otherwise be invisible to the histogram.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope.get("type") != "http":
            # WebSocket / lifespan traffic is out of scope for HTTP metrics.
            await self.app(scope, receive, send)
            return

        raw_path = scope.get("path", "")
        # Never instrument the metrics endpoint itself — Prometheus
        # scrapes every 15s and self-observing would produce a constant
        # background of noise without telling operators anything useful.
        if raw_path.startswith("/metrics"):
            await self.app(scope, receive, send)
            return

        # Early-return when the observability gate is off: no label
        # allocation, no timing cost, no downstream overhead.
        if not _prometheus_enabled():
            await self.app(scope, receive, send)
            return

        # Lazily import the metric symbols so importing this module
        # doesn't pull ``prometheus_client`` into tooling contexts that
        # don't need it.
        from src.observability.metrics import (
            HTTP_REQUESTS_IN_FLIGHT,
            HTTP_REQUESTS_TOTAL,
            HTTP_REQUEST_DURATION_SECONDS,
        )

        method: str = scope.get("method", "GET")
        path: str = _resolve_template_path(scope)

        # Capture the response status as it passes through ``send``
        # so exception paths that never set a status still report a 500.
        status_holder: dict = {"code": 500}

        async def _send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = int(message.get("status", 500))
            await send(message)

        HTTP_REQUESTS_IN_FLIGHT.labels(method=method, path=path).inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, _send_wrapper)
        finally:
            duration = time.perf_counter() - start
            HTTP_REQUEST_DURATION_SECONDS.labels(
                method=method, path=path
            ).observe(duration)
            HTTP_REQUESTS_TOTAL.labels(
                method=method,
                path=path,
                status=str(status_holder["code"]),
            ).inc()
            HTTP_REQUESTS_IN_FLIGHT.labels(method=method, path=path).dec()
