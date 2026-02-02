"""
CSRF Protection Middleware.

Implements double-submit cookie pattern for CSRF protection.
Works alongside JWT authentication for defense in depth.
"""

import secrets
import hashlib
from typing import Callable, Optional, Set
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from src.utils.logger import get_logger

logger = get_logger(__name__)

# CSRF token settings
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_LENGTH = 32
CSRF_COOKIE_MAX_AGE = 3600  # 1 hour

# Methods that require CSRF validation
CSRF_PROTECTED_METHODS: Set[str] = {"POST", "PUT", "DELETE", "PATCH"}

# Paths exempt from CSRF (e.g., login, public APIs)
CSRF_EXEMPT_PATHS: Set[str] = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
    "/api/health",
}


class CSRFError(Exception):
    """Raised when CSRF validation fails."""
    pass


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token."""
    return secrets.token_urlsafe(CSRF_TOKEN_LENGTH)


def hash_token(token: str) -> str:
    """Hash a token for comparison."""
    return hashlib.sha256(token.encode()).hexdigest()


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """
    CSRF protection using double-submit cookie pattern.

    How it works:
    1. On first request, generates a CSRF token and sets it as a cookie
    2. Client must include the token in X-CSRF-Token header for state-changing requests
    3. Server validates that cookie value matches header value

    This is effective because:
    - Attacker cannot read cookies from another domain (same-origin policy)
    - Attacker cannot set custom headers in cross-origin requests
    - Combined with SameSite cookies, provides strong CSRF protection

    Usage:
        app.add_middleware(CSRFProtectionMiddleware)

    Client usage:
        1. Read csrf_token from cookies
        2. Include in header: X-CSRF-Token: <token>
    """

    def __init__(
        self,
        app,
        cookie_name: str = CSRF_COOKIE_NAME,
        header_name: str = CSRF_HEADER_NAME,
        exempt_paths: Optional[Set[str]] = None,
        cookie_secure: bool = True,
        cookie_samesite: str = "strict",
    ):
        """
        Initialize CSRF protection middleware.

        Args:
            app: The ASGI application
            cookie_name: Name of the CSRF cookie
            header_name: Name of the CSRF header
            exempt_paths: Paths exempt from CSRF validation
            cookie_secure: Set Secure flag on cookie (requires HTTPS)
            cookie_samesite: SameSite cookie attribute (strict, lax, none)
        """
        super().__init__(app)
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.exempt_paths = exempt_paths or CSRF_EXEMPT_PATHS
        self.cookie_secure = cookie_secure
        self.cookie_samesite = cookie_samesite

    def _is_exempt(self, request: Request) -> bool:
        """Check if the request path is exempt from CSRF validation."""
        path = request.url.path.rstrip("/")
        return path in self.exempt_paths or any(
            path.startswith(exempt.rstrip("/"))
            for exempt in self.exempt_paths
            if exempt.endswith("*")
        )

    def _needs_validation(self, request: Request) -> bool:
        """Check if the request needs CSRF validation."""
        return (
            request.method in CSRF_PROTECTED_METHODS
            and not self._is_exempt(request)
        )

    def _validate_csrf(self, request: Request) -> bool:
        """
        Validate CSRF token.

        Returns True if valid, False otherwise.
        """
        # Get token from cookie
        cookie_token = request.cookies.get(self.cookie_name)
        if not cookie_token:
            logger.warning("CSRF validation failed: No cookie token")
            return False

        # Get token from header
        header_token = request.headers.get(self.header_name)
        if not header_token:
            logger.warning("CSRF validation failed: No header token")
            return False

        # Compare tokens (timing-safe comparison)
        if not secrets.compare_digest(cookie_token, header_token):
            logger.warning("CSRF validation failed: Token mismatch")
            return False

        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process the request with CSRF protection."""

        # Check if validation is needed
        if self._needs_validation(request):
            if not self._validate_csrf(request):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "CSRF validation failed",
                        "error": "csrf_error",
                    }
                )

        # Process the request
        response = await call_next(request)

        # Set CSRF cookie if not present
        if self.cookie_name not in request.cookies:
            csrf_token = generate_csrf_token()
            response.set_cookie(
                key=self.cookie_name,
                value=csrf_token,
                max_age=CSRF_COOKIE_MAX_AGE,
                httponly=False,  # Must be readable by JavaScript
                secure=self.cookie_secure,
                samesite=self.cookie_samesite,
                path="/",
            )

        return response


class CSRFTokenEndpoint:
    """
    Endpoint to get a fresh CSRF token.

    Useful for SPAs that need to initialize CSRF protection.

    Usage:
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/api/csrf-token")
        async def get_csrf_token(request: Request):
            return CSRFTokenEndpoint.get_token_response(request)
    """

    @staticmethod
    def get_token_response(request: Request) -> dict:
        """Generate a CSRF token response."""
        # Get existing token from cookie or generate new one
        existing_token = request.cookies.get(CSRF_COOKIE_NAME)
        token = existing_token or generate_csrf_token()

        return {
            "csrf_token": token,
            "header_name": CSRF_HEADER_NAME,
            "cookie_name": CSRF_COOKIE_NAME,
        }


def get_csrf_token(request: Request) -> str:
    """
    Dependency to get CSRF token from request.

    Usage:
        @app.post("/api/sensitive-action")
        async def sensitive_action(csrf_token: str = Depends(get_csrf_token)):
            # Token is validated by middleware
            pass
    """
    return request.cookies.get(CSRF_COOKIE_NAME, "")
