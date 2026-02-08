"""
Global exception handler middleware.

In production, returns generic error messages without stack traces.
In development, includes full error details for debugging.
"""

import os
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

from src.utils.logger import get_logger

logger = get_logger(__name__)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle unhandled exceptions globally.

    In production (ENVIRONMENT=production), returns a generic error message
    without exposing internal details or stack traces.
    In development, includes the full error detail for debugging.
    """
    environment = os.getenv("ENVIRONMENT", "development").lower()

    # Always log the full error server-side
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )

    if environment == "production":
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Internal server error: {str(exc)}",
                "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
            },
        )
