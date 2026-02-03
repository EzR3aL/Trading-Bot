"""User management schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    email: Optional[str] = None
    role: str = Field(default="user", pattern="^(admin|user)$")
    language: str = Field(default="de", pattern="^(de|en)$")


class UserUpdate(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = Field(default=None, pattern="^(admin|user)$")
    language: Optional[str] = Field(default=None, pattern="^(de|en)$")
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    language: str
    is_active: bool

    class Config:
        from_attributes = True
