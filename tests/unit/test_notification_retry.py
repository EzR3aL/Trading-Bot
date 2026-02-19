"""Tests for notification retry decorator."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from src.notifications.retry import async_retry


@pytest.mark.asyncio
async def test_retry_succeeds_on_first_attempt():
    """Function succeeds immediately, no retries needed."""
    call_count = 0

    @async_retry(max_retries=3, base_delay=0.01)
    async def success_func():
        nonlocal call_count
        call_count += 1
        return True

    result = await success_func()
    assert result is True
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_succeeds_on_third_attempt():
    """Function fails twice then succeeds on third attempt."""
    call_count = 0

    @async_retry(max_retries=3, base_delay=0.01)
    async def flaky_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("Temporary failure")
        return True

    result = await flaky_func()
    assert result is True
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted_returns_false():
    """Function fails all attempts, returns False."""
    call_count = 0

    @async_retry(max_retries=2, base_delay=0.01)
    async def always_fail():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Permanent failure")

    result = await always_fail()
    assert result is False
    assert call_count == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
async def test_retry_exponential_backoff_timing():
    """Verify that retries use exponential backoff."""
    timestamps = []

    @async_retry(max_retries=2, base_delay=0.05)
    async def timed_fail():
        timestamps.append(asyncio.get_event_loop().time())
        raise RuntimeError("fail")

    await timed_fail()

    assert len(timestamps) == 3
    # First retry delay should be ~0.05s, second ~0.1s
    delay1 = timestamps[1] - timestamps[0]
    delay2 = timestamps[2] - timestamps[1]
    assert delay1 >= 0.04  # base_delay with some tolerance
    assert delay2 >= 0.08  # 2x base_delay with tolerance
    assert delay2 > delay1  # exponential growth


@pytest.mark.asyncio
async def test_retry_preserves_function_metadata():
    """Decorated function should preserve original name and docstring."""

    @async_retry(max_retries=1)
    async def my_function():
        """My docstring."""
        return True

    assert my_function.__name__ == "my_function"
    assert my_function.__doc__ == "My docstring."


@pytest.mark.asyncio
async def test_retry_passes_arguments():
    """Retry decorator should pass through args and kwargs."""

    @async_retry(max_retries=1, base_delay=0.01)
    async def add(a, b, extra=0):
        return a + b + extra

    result = await add(1, 2, extra=3)
    assert result == 6
