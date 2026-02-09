"""Pydantic schemas for affiliate links."""

from typing import Optional

from pydantic import BaseModel, HttpUrl


class AffiliateLinkResponse(BaseModel):
    exchange_type: str
    affiliate_url: str
    label: Optional[str] = None
    is_active: bool = True

    class Config:
        from_attributes = True


class AffiliateLinkUpdate(BaseModel):
    affiliate_url: str
    label: Optional[str] = None
    is_active: bool = True
