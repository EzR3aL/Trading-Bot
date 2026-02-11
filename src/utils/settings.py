"""
DB-first, ENV-fallback settings helper.

Reads from the system_settings table first; falls back to os.environ.
"""

import os

from sqlalchemy import select

from src.models.database import SystemSetting
from src.models.session import get_session


async def get_setting(key: str, default: str = "") -> str:
    """Read a single setting: DB first, then os.environ fallback."""
    async with get_session() as session:
        result = await session.execute(
            select(SystemSetting.value).where(SystemSetting.key == key)
        )
        row = result.scalar_one_or_none()
        if row is not None and row != "":
            return row
    return os.environ.get(key, default).strip()


async def get_hl_config() -> dict:
    """Get all Hyperliquid builder settings at once."""
    return {
        "builder_address": await get_setting("HL_BUILDER_ADDRESS"),
        "builder_fee": int(await get_setting("HL_BUILDER_FEE", "0")),
        "referral_code": await get_setting("HL_REFERRAL_CODE"),
    }
