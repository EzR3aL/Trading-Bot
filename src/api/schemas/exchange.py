"""Exchange-related schemas."""

from pydantic import BaseModel


class ExchangeInfo(BaseModel):
    name: str
    display_name: str
    supports_demo: bool
    auth_type: str
    requires_passphrase: bool


class ExchangeListResponse(BaseModel):
    exchanges: list[ExchangeInfo]
