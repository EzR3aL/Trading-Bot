"""User configuration endpoints (per-user settings)."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.config import (
    ApiKeysUpdate,
    ConfigResponse,
    DiscordConfigUpdate,
    ExchangeConfigUpdate,
    StrategyConfigUpdate,
    TradingConfigUpdate,
)
from src.auth.dependencies import get_current_user
from src.models.database import User, UserConfig
from src.models.session import get_db
from src.utils.encryption import decrypt_value, encrypt_value, mask_value

router = APIRouter(prefix="/api/config", tags=["config"])


async def _get_or_create_config(
    user: User, db: AsyncSession
) -> UserConfig:
    """Get user config or create a default one."""
    result = await db.execute(
        select(UserConfig).where(UserConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        config = UserConfig(user_id=user.id, exchange_type="bitget")
        db.add(config)
        await db.flush()
        await db.refresh(config)
    return config


@router.get("", response_model=ConfigResponse)
async def get_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's configuration."""
    config = await _get_or_create_config(user, db)

    trading = None
    if config.trading_config:
        trading = TradingConfigUpdate(**json.loads(config.trading_config))

    strategy = None
    if config.strategy_config:
        strategy = StrategyConfigUpdate(**json.loads(config.strategy_config))

    discord = None
    if config.discord_webhook_url:
        discord = DiscordConfigUpdate(webhook_url=mask_value(config.discord_webhook_url, 8))

    has_live_keys = bool(config.api_key_encrypted)
    has_demo_keys = bool(config.demo_api_key_encrypted)

    return ConfigResponse(
        trading=trading,
        strategy=strategy,
        discord=discord,
        exchange_type=config.exchange_type,
        api_keys_configured=has_live_keys,
        demo_api_keys_configured=has_demo_keys,
    )


@router.put("/trading")
async def update_trading_config(
    data: TradingConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update trading parameters."""
    config = await _get_or_create_config(user, db)
    config.trading_config = json.dumps(data.model_dump())
    return {"status": "ok", "message": "Trading config updated"}


@router.put("/strategy")
async def update_strategy_config(
    data: StrategyConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update strategy thresholds."""
    config = await _get_or_create_config(user, db)
    config.strategy_config = json.dumps(data.model_dump())
    return {"status": "ok", "message": "Strategy config updated"}


@router.put("/discord")
async def update_discord_config(
    data: DiscordConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update Discord webhook URL."""
    config = await _get_or_create_config(user, db)
    config.discord_webhook_url = data.webhook_url
    return {"status": "ok", "message": "Discord config updated"}


@router.post("/discord/test")
async def test_discord_webhook(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a test message to the configured Discord webhook."""
    config = await _get_or_create_config(user, db)
    if not config.discord_webhook_url:
        raise HTTPException(status_code=400, detail="No Discord webhook configured")

    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "content": None,
                "embeds": [{
                    "title": "Test Notification",
                    "description": "Trading Bot webhook is working!",
                    "color": 3447003,
                }],
            }
            async with session.post(config.discord_webhook_url, json=payload) as resp:
                if resp.status in (200, 204):
                    return {"status": "ok", "message": "Test message sent"}
                return {"status": "error", "message": f"Discord returned {resp.status}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to send: {str(e)}")


@router.put("/api-keys")
async def update_api_keys(
    data: ApiKeysUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update exchange API keys (encrypted at rest)."""
    config = await _get_or_create_config(user, db)
    config.exchange_type = data.exchange_type

    if data.api_key:
        config.api_key_encrypted = encrypt_value(data.api_key)
    if data.api_secret:
        config.api_secret_encrypted = encrypt_value(data.api_secret)
    if data.passphrase:
        config.passphrase_encrypted = encrypt_value(data.passphrase)
    if data.demo_api_key:
        config.demo_api_key_encrypted = encrypt_value(data.demo_api_key)
    if data.demo_api_secret:
        config.demo_api_secret_encrypted = encrypt_value(data.demo_api_secret)
    if data.demo_passphrase:
        config.demo_passphrase_encrypted = encrypt_value(data.demo_passphrase)

    return {"status": "ok", "message": "API keys updated"}


@router.post("/api-keys/test")
async def test_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test exchange connection with stored API keys."""
    config = await _get_or_create_config(user, db)

    if not config.api_key_encrypted and not config.demo_api_key_encrypted:
        raise HTTPException(status_code=400, detail="No API keys configured")

    try:
        from src.exchanges.factory import create_exchange_client

        # Try demo keys first, then live
        if config.demo_api_key_encrypted:
            client = create_exchange_client(
                exchange_type=config.exchange_type,
                api_key=decrypt_value(config.demo_api_key_encrypted),
                api_secret=decrypt_value(config.demo_api_secret_encrypted),
                passphrase=decrypt_value(config.demo_passphrase_encrypted) if config.demo_passphrase_encrypted else "",
                demo_mode=True,
            )
        else:
            client = create_exchange_client(
                exchange_type=config.exchange_type,
                api_key=decrypt_value(config.api_key_encrypted),
                api_secret=decrypt_value(config.api_secret_encrypted),
                passphrase=decrypt_value(config.passphrase_encrypted) if config.passphrase_encrypted else "",
                demo_mode=False,
            )

        balance = await client.get_account_balance()
        await client.close()

        return {
            "status": "ok",
            "exchange": config.exchange_type,
            "balance": balance.total,
            "currency": balance.currency,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {str(e)}")


@router.put("/exchange")
async def update_exchange(
    data: ExchangeConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update active exchange type."""
    config = await _get_or_create_config(user, db)
    config.exchange_type = data.exchange_type
    return {"status": "ok", "message": f"Exchange set to {data.exchange_type}"}
