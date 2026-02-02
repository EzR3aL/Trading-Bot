"""
Authentication module for multi-tenant user management.

Provides:
- JWT token generation and validation
- Password hashing with bcrypt
- FastAPI authentication dependencies
- Rate limiting for auth endpoints
"""

from src.auth.jwt_handler import JWTHandler, TokenPair
from src.auth.password import PasswordHandler
from src.auth.dependencies import get_current_user, get_current_admin_user

__all__ = [
    "JWTHandler",
    "TokenPair",
    "PasswordHandler",
    "get_current_user",
    "get_current_admin_user",
]
