"""Shared rate limiter for all API routers."""

import ipaddress
import os

from fastapi import Request
from slowapi import Limiter

# Only trust X-Forwarded-For when deployed behind a reverse proxy
_TRUST_PROXY = os.getenv("BEHIND_PROXY", "").lower() in ("1", "true", "yes")


def _is_valid_ip(value: str) -> bool:
    """Validate an IP address string (IPv4 or IPv6)."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _get_real_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For only behind a trusted proxy."""
    if _TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
            if _is_valid_ip(ip):
                return ip
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_client_ip)
