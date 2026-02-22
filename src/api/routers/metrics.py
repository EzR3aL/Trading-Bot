"""
Prometheus metrics endpoint.

In production, access is restricted to localhost, Docker internal
networks, and IPs listed in METRICS_ALLOWED_IPS (comma-separated).
"""

import ipaddress
import os

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["monitoring"])

# Pre-compute allowed networks once at import time
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
]


def _is_allowed(client_ip: str) -> bool:
    """Check if the client IP is in the allow list."""
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    # Always allow private/loopback
    for net in _PRIVATE_NETWORKS:
        if addr in net:
            return True

    # Check explicit allow list
    extra = os.getenv("METRICS_ALLOWED_IPS", "")
    if extra:
        for entry in extra.split(","):
            entry = entry.strip()
            if not entry:
                continue
            try:
                if "/" in entry:
                    if addr in ipaddress.ip_network(entry, strict=False):
                        return True
                elif addr == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                continue

    return False


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(request: Request):
    """Serve Prometheus-formatted metrics (IP-restricted in production)."""
    environment = os.getenv("ENVIRONMENT", "development").lower()

    if environment == "production":
        client_ip = request.client.host if request.client else "0.0.0.0"
        if not _is_allowed(client_ip):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
