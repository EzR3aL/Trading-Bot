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


async def get_settings_batch(keys: list[str], defaults: dict[str, str] | None = None) -> dict[str, str]:
    """Read multiple settings in a single DB round-trip."""
    defaults = defaults or {}
    result_map: dict[str, str] = {}
    async with get_session() as session:
        result = await session.execute(
            select(SystemSetting.key, SystemSetting.value).where(SystemSetting.key.in_(keys))
        )
        for key, value in result.all():
            if value is not None and value != "":
                result_map[key] = value
    # Fill missing keys from env / defaults
    for key in keys:
        if key not in result_map:
            result_map[key] = os.environ.get(key, defaults.get(key, "")).strip()
    return result_map


async def get_hl_config() -> dict:
    """Get all Hyperliquid builder settings in a single DB query."""
    settings = await get_settings_batch(
        ["HL_BUILDER_ADDRESS", "HL_BUILDER_FEE", "HL_REFERRAL_CODE"],
        defaults={"HL_BUILDER_FEE": "0"},
    )
    return {
        "builder_address": settings["HL_BUILDER_ADDRESS"],
        "builder_fee": int(settings["HL_BUILDER_FEE"] or "0"),
        "referral_code": settings["HL_REFERRAL_CODE"],
    }
