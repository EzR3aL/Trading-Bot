"""Exchange information endpoints."""

import re

from fastapi import APIRouter, HTTPException, Request

from src.api.rate_limit import limiter
from src.api.schemas.exchange import ExchangeInfo, ExchangeListResponse
from src.exchanges.factory import get_exchange_info, get_supported_exchanges

router = APIRouter(prefix="/api/exchanges", tags=["exchanges"])

_EXCHANGE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,29}$")


@router.get("", response_model=ExchangeListResponse)
@limiter.limit("30/minute")
async def list_exchanges(request: Request):
    """List all supported exchanges."""
    exchanges = []
    for name in get_supported_exchanges():
        info = get_exchange_info(name)
        exchanges.append(ExchangeInfo(
            name=info["name"],
            display_name=info["display_name"],
            supports_demo=info["supports_demo"],
            auth_type=info["auth_type"],
            requires_passphrase=info["requires_passphrase"],
        ))
    return ExchangeListResponse(exchanges=exchanges)


@router.get("/{exchange_name}/info", response_model=ExchangeInfo)
@limiter.limit("30/minute")
async def get_exchange_detail(request: Request, exchange_name: str):
    """Get details about a specific exchange."""
    if not _EXCHANGE_NAME_RE.match(exchange_name):
        raise HTTPException(status_code=400, detail="Ungueltiger Exchange-Name")

    try:
        info = get_exchange_info(exchange_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Exchange '{exchange_name}' not found")

    return ExchangeInfo(
        name=info["name"],
        display_name=info["display_name"],
        supports_demo=info["supports_demo"],
        auth_type=info["auth_type"],
        requires_passphrase=info["requires_passphrase"],
    )
