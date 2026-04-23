"""Authentication schemas."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    # access_token is no longer populated in the body (SEC-012) — it's delivered
    # via the httpOnly access_token cookie. Field kept Optional for API stability.
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int = 14400  # 4 hours


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        """Require at least 1 uppercase, 1 lowercase, 1 digit, 1 special char."""
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[^A-Za-z0-9]", v):
            raise ValueError("Password must contain at least one special character")
        return v


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    role: str
    language: str | None = "en"
    is_active: bool


class LoginResponse(BaseModel):
    """Login response with JWT tokens."""
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    expires_in: int = 14400  # 4 hours


# ── Session Management Schemas ─────────────────────────────────────

class SessionResponse(BaseModel):
    """A single active session."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_name: str | None = None
    ip_address: str | None = None
    last_activity: datetime | None = None
    created_at: datetime | None = None
    is_current: bool = False


class SessionListResponse(BaseModel):
    """List of active sessions for the current user."""
    sessions: list[SessionResponse]
