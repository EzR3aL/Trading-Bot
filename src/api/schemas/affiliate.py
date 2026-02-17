"""Pydantic schemas for affiliate links."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, HttpUrl


class AffiliateLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exchange_type: str
    affiliate_url: str
    label: Optional[str] = None
    is_active: bool = True
    uid_required: bool = False


class AffiliateLinkUpdate(BaseModel):
    affiliate_url: HttpUrl
    label: Optional[str] = None
    is_active: bool = True
    uid_required: bool = False
