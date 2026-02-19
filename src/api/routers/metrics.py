"""
Prometheus metrics endpoint.

Unauthenticated by design — in production, restrict access
via firewall rules (e.g. allow only Prometheus IP or localhost).
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["monitoring"])


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    """Serve Prometheus-formatted metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
