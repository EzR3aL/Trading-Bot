"""
Security Headers Middleware.

Adds comprehensive security headers to all responses following OWASP guidelines.
Provides defense-in-depth protection against XSS, clickjacking, MIME sniffing, and more.
"""

from typing import Callable, Optional, List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.utils.logger import get_logger

logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all HTTP responses.

    Headers added:
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking
    - X-XSS-Protection: Legacy XSS protection (for older browsers)
    - Strict-Transport-Security: Forces HTTPS
    - Content-Security-Policy: Controls resource loading
    - Referrer-Policy: Controls referrer information
    - Permissions-Policy: Controls browser features
    - Cache-Control: Prevents caching of sensitive data

    Usage:
        app.add_middleware(SecurityHeadersMiddleware)
    """

    def __init__(
        self,
        app,
        enable_hsts: bool = True,
        hsts_max_age: int = 31536000,  # 1 year
        csp_policy: Optional[str] = None,
        allowed_frame_ancestors: Optional[List[str]] = None,
    ):
        """
        Initialize security headers middleware.

        Args:
            app: The ASGI application
            enable_hsts: Enable Strict-Transport-Security header
            hsts_max_age: HSTS max age in seconds (default 1 year)
            csp_policy: Custom Content-Security-Policy (optional)
            allowed_frame_ancestors: List of allowed frame ancestors (default: 'none')
        """
        super().__init__(app)
        self.enable_hsts = enable_hsts
        self.hsts_max_age = hsts_max_age
        self.allowed_frame_ancestors = allowed_frame_ancestors or []

        # Build CSP policy
        if csp_policy:
            self.csp_policy = csp_policy
        else:
            self.csp_policy = self._build_default_csp()

    def _build_default_csp(self) -> str:
        """Build a secure default Content-Security-Policy."""
        # Strict CSP that allows:
        # - Scripts/styles from same origin
        # - Images from same origin and data URIs (for inline icons)
        # - Connections to same origin and localhost (for API)
        # - Fonts from same origin
        # - No frames, objects, or base URI manipulation
        directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  # React needs this
            "style-src 'self' 'unsafe-inline'",  # Tailwind needs inline styles
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self' ws://localhost:* wss://localhost:* http://localhost:* https://localhost:*",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "upgrade-insecure-requests",
        ]
        return "; ".join(directives)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to the response."""
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        if self.allowed_frame_ancestors:
            ancestors = " ".join(self.allowed_frame_ancestors)
            response.headers["X-Frame-Options"] = "ALLOW-FROM " + self.allowed_frame_ancestors[0]
        else:
            response.headers["X-Frame-Options"] = "DENY"

        # Legacy XSS protection (still useful for older browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Force HTTPS (only in production with HTTPS)
        if self.enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={self.hsts_max_age}; includeSubDomains; preload"
            )

        # Content Security Policy
        response.headers["Content-Security-Policy"] = self.csp_policy

        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Disable dangerous browser features
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), "
            "camera=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "microphone=(), "
            "payment=(), "
            "usb=()"
        )

        # Prevent caching of sensitive responses
        # Only apply to API endpoints, not static files
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"

        # Remove server identification headers (defense in depth)
        if "server" in response.headers:
            del response.headers["server"]
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]

        return response


class CORSSecurityMiddleware(BaseHTTPMiddleware):
    """
    Additional CORS security checks beyond FastAPI's CORSMiddleware.

    Validates Origin header against allowlist and adds security logging.
    """

    def __init__(
        self,
        app,
        allowed_origins: List[str],
        log_violations: bool = True,
    ):
        """
        Initialize CORS security middleware.

        Args:
            app: The ASGI application
            allowed_origins: List of allowed origins
            log_violations: Whether to log CORS violations
        """
        super().__init__(app)
        self.allowed_origins = set(origin.lower() for origin in allowed_origins)
        self.log_violations = log_violations

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Validate CORS requests."""
        origin = request.headers.get("origin", "").lower()

        # Check for CORS violations on API endpoints
        if origin and request.url.path.startswith("/api/"):
            if origin not in self.allowed_origins:
                if self.log_violations:
                    logger.warning(
                        f"CORS violation: Origin '{origin}' not in allowlist. "
                        f"Path: {request.url.path}, Method: {request.method}"
                    )
                # Still let the request through - CORSMiddleware will handle the response
                # This middleware is for logging and monitoring

        return await call_next(request)


def get_security_headers_middleware(
    enable_hsts: bool = True,
    hsts_max_age: int = 31536000,
) -> type:
    """
    Factory function to create configured SecurityHeadersMiddleware.

    Usage:
        middleware_class = get_security_headers_middleware(enable_hsts=True)
        app.add_middleware(middleware_class)
    """
    class ConfiguredSecurityHeadersMiddleware(SecurityHeadersMiddleware):
        def __init__(self, app):
            super().__init__(
                app,
                enable_hsts=enable_hsts,
                hsts_max_age=hsts_max_age,
            )

    return ConfiguredSecurityHeadersMiddleware
