"""
Prometheus HTTP middleware.

Tracks request count and latency for every endpoint,
normalizing dynamic path segments to avoid cardinality explosion.
"""

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from src.monitoring.metrics import HTTP_REQUESTS_TOTAL, HTTP_REQUEST_DURATION


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record HTTP request metrics for Prometheus."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip the metrics endpoint itself to avoid recursion in metrics
        if path == "/metrics":
            return await call_next(request)

        method = request.method
        normalized = self._normalize_path(path)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        HTTP_REQUESTS_TOTAL.labels(method, normalized, response.status_code).inc()
        HTTP_REQUEST_DURATION.labels(method, normalized).observe(duration)

        return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Replace numeric path segments with {id} to limit cardinality.

        Example: /api/trades/123 -> /api/trades/{id}
        """
        parts = path.split("/")
        return "/".join(p if not p.isdigit() else "{id}" for p in parts)
