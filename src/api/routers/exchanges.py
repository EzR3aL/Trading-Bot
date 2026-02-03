"""Exchange information endpoints."""

from fastapi import APIRouter

from src.api.schemas.exchange import ExchangeInfo, ExchangeListResponse
from src.exchanges.factory import get_exchange_info, get_supported_exchanges

router = APIRouter(prefix="/api/exchanges", tags=["exchanges"])


@router.get("", response_model=ExchangeListResponse)
async def list_exchanges():
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
async def get_exchange_detail(exchange_name: str):
    """Get details about a specific exchange."""
    try:
        info = get_exchange_info(exchange_name)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Exchange '{exchange_name}' not found")

    return ExchangeInfo(
        name=info["name"],
        display_name=info["display_name"],
        supports_demo=info["supports_demo"],
        auth_type=info["auth_type"],
        requires_passphrase=info["requires_passphrase"],
    )
