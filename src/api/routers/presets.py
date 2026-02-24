"""Config preset CRUD endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import limiter
from src.api.schemas.preset import PresetCreate, PresetResponse, PresetUpdate
from src.auth.dependencies import get_current_user
from src.models.database import ConfigPreset, User
from src.models.session import get_db

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _preset_to_response(preset: ConfigPreset) -> PresetResponse:
    return PresetResponse(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        exchange_type=preset.exchange_type,
        is_active=preset.is_active,
        trading_config=json.loads(preset.trading_config) if preset.trading_config else None,
        strategy_config=json.loads(preset.strategy_config) if preset.strategy_config else None,
        trading_pairs=json.loads(preset.trading_pairs) if preset.trading_pairs else None,
    )


@router.get("", response_model=list[PresetResponse])
async def list_presets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all presets for the current user."""
    result = await db.execute(
        select(ConfigPreset)
        .where(ConfigPreset.user_id == user.id)
        .order_by(ConfigPreset.created_at)
    )
    presets = result.scalars().all()
    return [_preset_to_response(p) for p in presets]


@router.post("", response_model=PresetResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_preset(
    request: Request,
    data: PresetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new config preset."""
    preset = ConfigPreset(
        user_id=user.id,
        name=data.name,
        description=data.description,
        exchange_type=data.exchange_type,
        trading_config=json.dumps(data.trading_config) if data.trading_config else None,
        strategy_config=json.dumps(data.strategy_config) if data.strategy_config else None,
        trading_pairs=json.dumps(data.trading_pairs),
    )
    db.add(preset)
    await db.flush()
    await db.refresh(preset)
    return _preset_to_response(preset)


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(
    preset_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific preset."""
    result = await db.execute(
        select(ConfigPreset).where(
            ConfigPreset.id == preset_id, ConfigPreset.user_id == user.id
        )
    )
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset nicht gefunden")
    return _preset_to_response(preset)


@router.put("/{preset_id}", response_model=PresetResponse)
@limiter.limit("10/minute")
async def update_preset(
    request: Request,
    preset_id: int,
    data: PresetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a preset."""
    result = await db.execute(
        select(ConfigPreset).where(
            ConfigPreset.id == preset_id, ConfigPreset.user_id == user.id
        )
    )
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset nicht gefunden")

    if data.name is not None:
        preset.name = data.name
    if data.description is not None:
        preset.description = data.description
    if data.trading_config is not None:
        preset.trading_config = json.dumps(data.trading_config)
    if data.strategy_config is not None:
        preset.strategy_config = json.dumps(data.strategy_config)
    if data.trading_pairs is not None:
        preset.trading_pairs = json.dumps(data.trading_pairs)

    await db.flush()
    await db.refresh(preset)
    return _preset_to_response(preset)


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_preset(
    request: Request,
    preset_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a preset."""
    result = await db.execute(
        select(ConfigPreset).where(
            ConfigPreset.id == preset_id, ConfigPreset.user_id == user.id
        )
    )
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset nicht gefunden")
    if preset.is_active:
        raise HTTPException(status_code=400, detail="Aktives Preset kann nicht geloescht werden. Zuerst deaktivieren.")
    await db.delete(preset)


@router.post("/{preset_id}/activate")
@limiter.limit("10/minute")
async def activate_preset(
    request: Request,
    preset_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Activate a preset (deactivates all others for this user)."""
    # Deactivate all user presets
    result = await db.execute(
        select(ConfigPreset).where(ConfigPreset.user_id == user.id)
    )
    for p in result.scalars().all():
        p.is_active = False

    # Activate the requested one
    result = await db.execute(
        select(ConfigPreset).where(
            ConfigPreset.id == preset_id, ConfigPreset.user_id == user.id
        )
    )
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Preset nicht gefunden")

    preset.is_active = True
    return {"status": "ok", "message": f"Preset '{preset.name}' activated"}


@router.post("/{preset_id}/duplicate", response_model=PresetResponse)
@limiter.limit("10/minute")
async def duplicate_preset(
    request: Request,
    preset_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Duplicate a preset."""
    result = await db.execute(
        select(ConfigPreset).where(
            ConfigPreset.id == preset_id, ConfigPreset.user_id == user.id
        )
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Preset nicht gefunden")

    copy = ConfigPreset(
        user_id=user.id,
        name=f"{original.name} (Copy)",
        description=original.description,
        exchange_type=original.exchange_type,
        trading_config=original.trading_config,
        strategy_config=original.strategy_config,
        trading_pairs=original.trading_pairs,
        is_active=False,
    )
    db.add(copy)
    await db.flush()
    await db.refresh(copy)
    return _preset_to_response(copy)
