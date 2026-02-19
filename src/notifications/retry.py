"""Shared retry decorator for notification systems."""

import asyncio
import logging
from functools import wraps

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0  # seconds
MAX_DELAY = 10.0


def async_retry(max_retries=MAX_RETRIES, base_delay=BASE_DELAY):
    """Decorator for async functions with exponential backoff retry."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), MAX_DELAY)
                        logger.warning(
                            "%s attempt %d/%d failed: %s. Retrying in %.1fs",
                            func.__name__, attempt + 1, max_retries + 1, e, delay
                        )
                        await asyncio.sleep(delay)
            logger.error(
                "%s failed after %d attempts: %s",
                func.__name__, max_retries + 1, last_exception
            )
            return False
        return wrapper
    return decorator
