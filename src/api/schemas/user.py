"""User management schemas."""

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_password_strength(password: str) -> str:
    """Ensure password has uppercase, lowercase, digit, and special char."""
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("Password must contain at least one special character")
    return password


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    email: Optional[str] = None
    role: str = Field(default="user", pattern="^(admin|user)$")
    language: str = Field(default="de", pattern="^(de|en)$")

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = Field(default=None, pattern="^(admin|user)$")
    language: Optional[str] = Field(default=None, pattern="^(de|en)$")
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_password_strength(v)
        return v


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    role: str
    language: str
    is_active: bool
