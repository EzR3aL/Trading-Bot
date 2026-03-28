"""Supabase JWT validation for the auth bridge.

Validates JWTs issued by Supabase Auth so that users who log in on
trading-department.com can seamlessly access the bot dashboard.
Uses JWKS (JSON Web Key Set) for ES256 verification.
"""

import logging
import os
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError

logger = logging.getLogger(__name__)

SUPABASE_PROJECT_URL = os.getenv("SUPABASE_PROJECT_URL", "")

# JWKS client fetches and caches the public key from Supabase
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient | None:
    """Lazy-init the JWKS client."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client
    if not SUPABASE_PROJECT_URL:
        logger.error("SUPABASE_PROJECT_URL is not configured")
        return None
    jwks_url = f"{SUPABASE_PROJECT_URL}/auth/v1/.well-known/jwks.json"
    _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    logger.info("JWKS client initialized: %s", jwks_url)
    return _jwks_client


@dataclass(frozen=True)
class SupabaseClaims:
    """Validated claims extracted from a Supabase JWT."""

    sub: str  # Supabase user UUID
    email: str
    role: str  # "authenticated"
    app_role: str  # "admin" | "user" from app_metadata


def verify_supabase_token(token: str) -> SupabaseClaims | None:
    """Validate a Supabase JWT and return extracted claims.

    Returns None if the token is invalid, expired, or missing
    required claims.
    """
    client = _get_jwks_client()
    if client is None:
        return None

    try:
        signing_key = client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=f"{SUPABASE_PROJECT_URL}/auth/v1",
        )
    except PyJWTError as exc:
        logger.warning("Supabase JWT validation failed: %s", exc)
        return None

    # Reject unverified email addresses (prevents account takeover via email linking)
    if not payload.get("email_confirmed_at"):
        logger.warning("Supabase JWT: email not confirmed")
        return None

    sub = payload.get("sub")
    email = payload.get("email")
    role = payload.get("role", "")

    if not sub or not email:
        logger.warning("Supabase JWT missing sub or email claim")
        return None

    if role != "authenticated":
        logger.warning("Supabase JWT has unexpected role: %s", role)
        return None

    # Extract app_metadata.role for admin sync (defaults to "user")
    app_metadata = payload.get("app_metadata", {})
    app_role = app_metadata.get("role", "user") if isinstance(app_metadata, dict) else "user"
    if app_role not in ("admin", "user"):
        app_role = "user"

    return SupabaseClaims(sub=sub, email=email, role=role, app_role=app_role)
