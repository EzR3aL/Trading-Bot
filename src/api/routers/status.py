"""Health check and status endpoints."""

from datetime import datetime

from fastapi import APIRouter

router = APIRouter(tags=["status"])


@router.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
    }


@router.get("/api/status")
async def get_status():
    """Get overall system status."""
    return {
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
        "features": {
            "multi_exchange": True,
            "multi_user": True,
            "config_presets": True,
        },
    }
