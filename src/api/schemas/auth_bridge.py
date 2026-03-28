"""Schemas for the auth bridge endpoints."""

from pydantic import BaseModel, Field


class GenerateCodeResponse(BaseModel):
    code: str
    expires_in: int = 60


class ExchangeCodeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class ExchangeCodeResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 14400  # 4 hours
    user: "BridgeUserProfile"


class BridgeUserProfile(BaseModel):
    id: int
    username: str
    email: str | None = None
    role: str
    language: str | None = "en"
    is_new: bool = False  # True if the account was just created
