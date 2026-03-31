"""User configuration endpoints (per-user settings).

Thin orchestrator that includes focused sub-routers.
All API paths remain under /api/config/* unchanged.
"""

from fastapi import APIRouter

from src.api.routers.config_affiliate import router as affiliate_router
from src.api.routers.config_exchange import router as exchange_router
from src.api.routers.config_hyperliquid import router as hyperliquid_router
from src.api.routers.config_trading import router as trading_router

router = APIRouter(prefix="/api/config", tags=["config"])
router.include_router(trading_router)
router.include_router(exchange_router)
router.include_router(affiliate_router)
router.include_router(hyperliquid_router)
