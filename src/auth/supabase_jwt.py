"""Supabase JWT validation for the auth bridge.

Validates JWTs issued by Supabase Auth so that users who log in on
trading-department.com can seamlessly access the bot dashboard.
"""

import logging
import os
from dataclasses import dataclass

import jwt
from jwt.exceptions import PyJWTError

logger = logging.getLogger(__name__)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_PROJECT_URL = os.getenv("SUPABASE_PROJECT_URL", "")


@dataclass(frozen=True)
class SupabaseClaims:
    """Validated claims extracted from a Supabase JWT."""

    sub: str  # Supabase user UUID
    email: str
    role: str  # "authenticated"


def verify_supabase_token(token: str) -> SupabaseClaims | None:
    """Validate a Supabase JWT and return extracted claims.

    Returns None if the token is invalid, expired, or missing
    required claims.
    """
    if not SUPABASE_JWT_SECRET:
        logger.error("SUPABASE_JWT_SECRET is not configured")
        return None

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except PyJWTError as exc:
        logger.warning("Supabase JWT validation failed: %s", exc)
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

    return SupabaseClaims(sub=sub, email=email, role=role)
