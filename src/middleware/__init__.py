"""
Middleware components for the trading bot dashboard.
"""

from src.middleware.security_headers import (
    SecurityHeadersMiddleware,
    CORSSecurityMiddleware,
    get_security_headers_middleware,
)
from src.middleware.csrf_protection import (
    CSRFProtectionMiddleware,
    CSRFTokenEndpoint,
    get_csrf_token,
    generate_csrf_token,
)

__all__ = [
    "SecurityHeadersMiddleware",
    "CORSSecurityMiddleware",
    "get_security_headers_middleware",
    "CSRFProtectionMiddleware",
    "CSRFTokenEndpoint",
    "get_csrf_token",
    "generate_csrf_token",
]
