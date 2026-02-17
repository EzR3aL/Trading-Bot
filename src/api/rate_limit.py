"""Shared rate limiter for all API routers."""

import os

from fastapi import Request
from slowapi import Limiter

# Only trust X-Forwarded-For when deployed behind a reverse proxy
_TRUST_PROXY = os.getenv("BEHIND_PROXY", "").lower() in ("1", "true", "yes")


def _get_real_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For only behind a trusted proxy."""
    if _TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_client_ip)
