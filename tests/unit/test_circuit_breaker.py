"""
Unit tests for the Circuit Breaker.

Tests cover:
- State transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Failure counting and threshold
- Timeout-based recovery
- Excluded exceptions
- Statistics tracking
- CircuitBreakerRegistry singleton
- CircuitBreakerError properties
"""

import asyncio
import time
import pytest
from unittest.mock import patch, AsyncMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitBreakerRegistry,
    CircuitState,
    CircuitStats,
    with_circuit_breaker,
    with_retry,
)


# ---------------------------------------------------------------------------
# CircuitStats tests
# ---------------------------------------------------------------------------

class TestCircuitStats:
    """Tests for CircuitStats dataclass."""

    def test_default_values(self):
        stats = CircuitStats()
        assert stats.total_calls == 0
        assert stats.successful_calls == 0
        assert stats.failed_calls == 0
        assert stats.rejected_calls == 0
        assert stats.consecutive_failures == 0
        assert stats.consecutive_successes == 0

    def test_to_dict_success_rate_zero_calls(self):
        stats = CircuitStats()
        result = stats.to_dict()
        assert result["success_rate"] == 0

    def test_to_dict_success_rate_with_calls(self):
        stats = CircuitStats(total_calls=10, successful_calls=7)
        result = stats.to_dict()
        assert result["success_rate"] == 70.0

    def test_to_dict_contains_all_fields(self):
        stats = CircuitStats(
            total_calls=5, successful_calls=3, failed_calls=2,
            rejected_calls=1, consecutive_failures=2, consecutive_successes=0,
        )
        result = stats.to_dict()
        assert "total_calls" in result
        assert "successful_calls" in result
        assert "failed_calls" in result
        assert "rejected_calls" in result
        assert "success_rate" in result
        assert "consecutive_failures" in result
        assert "consecutive_successes" in result


# ---------------------------------------------------------------------------
# CircuitBreakerError tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerError:
    """Tests for CircuitBreakerError."""

    def test_error_attributes(self):
        err = CircuitBreakerError("test_api", CircuitState.OPEN, retry_after=30.0)
        assert err.service_name == "test_api"
        assert err.state == CircuitState.OPEN
        assert err.retry_after == 30.0

    def test_error_message(self):
        err = CircuitBreakerError("test_api", CircuitState.OPEN, retry_after=30.0)
        assert "test_api" in str(err)
        assert "open" in str(err)

    def test_error_is_exception(self):
        err = CircuitBreakerError("test_api", CircuitState.OPEN)
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerInitialState:
    """Tests for initial circuit breaker state."""

    def test_starts_closed(self):
        breaker = CircuitBreaker("test", fail_threshold=3)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed is True
        assert breaker.is_open is False

    def test_initial_stats_empty(self):
        breaker = CircuitBreaker("test")
        assert breaker.stats.total_calls == 0

    def test_custom_parameters(self):
        breaker = CircuitBreaker(
            "test", fail_threshold=10, reset_timeout=120.0,
            half_open_max_calls=5,
        )
        assert breaker.fail_threshold == 10
        assert breaker.reset_timeout == 120.0
        assert breaker.half_open_max_calls == 5


@pytest.mark.asyncio
class TestCircuitBreakerSuccessPath:
    """Tests for successful calls through the circuit breaker."""

    async def test_successful_call_passes_through(self):
        breaker = CircuitBreaker("test", fail_threshold=3)
        mock_fn = AsyncMock(return_value="result")

        result = await breaker.call(mock_fn)

        assert result == "result"
        mock_fn.assert_awaited_once()

    async def test_successful_call_updates_stats(self):
        breaker = CircuitBreaker("test", fail_threshold=3)
        mock_fn = AsyncMock(return_value="ok")

        await breaker.call(mock_fn)

        assert breaker.stats.total_calls == 1
        assert breaker.stats.successful_calls == 1
        assert breaker.stats.consecutive_successes == 1

    async def test_multiple_successes_track_consecutive(self):
        breaker = CircuitBreaker("test", fail_threshold=3)
        mock_fn = AsyncMock(return_value="ok")

        for _ in range(5):
            await breaker.call(mock_fn)

        assert breaker.stats.consecutive_successes == 5
        assert breaker.stats.total_calls == 5


@pytest.mark.asyncio
class TestCircuitBreakerFailurePath:
    """Tests for failures and circuit opening."""

    async def test_failure_raises_original_exception(self):
        breaker = CircuitBreaker("test", fail_threshold=3)
        mock_fn = AsyncMock(side_effect=ValueError("bad value"))

        with pytest.raises(ValueError, match="bad value"):
            await breaker.call(mock_fn)

    async def test_failure_updates_stats(self):
        breaker = CircuitBreaker("test", fail_threshold=3)
        mock_fn = AsyncMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError):
            await breaker.call(mock_fn)

        assert breaker.stats.failed_calls == 1
        assert breaker.stats.consecutive_failures == 1

    async def test_circuit_opens_after_threshold(self):
        breaker = CircuitBreaker("test", fail_threshold=3, reset_timeout=60)
        mock_fn = AsyncMock(side_effect=RuntimeError("fail"))

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await breaker.call(mock_fn)

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open is True

    async def test_open_circuit_rejects_calls(self):
        breaker = CircuitBreaker("test", fail_threshold=2, reset_timeout=60)
        failing_fn = AsyncMock(side_effect=RuntimeError("fail"))

        # Trip the breaker
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(failing_fn)

        assert breaker.state == CircuitState.OPEN

        # Next call should raise CircuitBreakerError
        with pytest.raises(CircuitBreakerError) as exc_info:
            await breaker.call(AsyncMock())

        assert exc_info.value.service_name == "test"
        assert exc_info.value.state == CircuitState.OPEN

    async def test_open_circuit_increments_rejected_count(self):
        breaker = CircuitBreaker("test", fail_threshold=2, reset_timeout=60)
        failing_fn = AsyncMock(side_effect=RuntimeError("fail"))

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(failing_fn)

        with pytest.raises(CircuitBreakerError):
            await breaker.call(AsyncMock())

        assert breaker.stats.rejected_calls == 1


@pytest.mark.asyncio
class TestCircuitBreakerRecovery:
    """Tests for half-open state and recovery."""

    async def test_transitions_to_half_open_after_timeout(self):
        breaker = CircuitBreaker("test", fail_threshold=2, reset_timeout=0.1)
        failing_fn = AsyncMock(side_effect=RuntimeError("fail"))

        # Trip the breaker
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(failing_fn)

        assert breaker.state == CircuitState.OPEN

        # Wait for reset timeout
        await asyncio.sleep(0.15)

        # Next call should transition to HALF_OPEN
        success_fn = AsyncMock(return_value="recovered")
        result = await breaker.call(success_fn)

        assert result == "recovered"
        assert breaker.state in (CircuitState.HALF_OPEN, CircuitState.CLOSED)

    async def test_half_open_closes_after_enough_successes(self):
        breaker = CircuitBreaker(
            "test", fail_threshold=2, reset_timeout=0.1,
            half_open_max_calls=2,
        )
        failing_fn = AsyncMock(side_effect=RuntimeError("fail"))

        # Trip the breaker
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(failing_fn)

        await asyncio.sleep(0.15)

        # Succeed enough times to close
        success_fn = AsyncMock(return_value="ok")
        for _ in range(2):
            await breaker.call(success_fn)

        assert breaker.state == CircuitState.CLOSED

    async def test_half_open_reopens_on_failure(self):
        breaker = CircuitBreaker("test", fail_threshold=2, reset_timeout=0.1)
        failing_fn = AsyncMock(side_effect=RuntimeError("fail"))

        # Trip the breaker
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call(failing_fn)

        await asyncio.sleep(0.15)

        # Fail again in half-open -> should go back to OPEN
        with pytest.raises(RuntimeError):
            await breaker.call(failing_fn)

        assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
class TestCircuitBreakerExcludedExceptions:
    """Tests for excluded exceptions behavior."""

    async def test_excluded_exception_does_not_count_as_failure(self):
        breaker = CircuitBreaker(
            "test", fail_threshold=2,
            excluded_exceptions=(ValueError,),
        )
        mock_fn = AsyncMock(side_effect=ValueError("expected"))

        for _ in range(5):
            with pytest.raises(ValueError):
                await breaker.call(mock_fn)

        # Should still be closed because ValueError is excluded
        assert breaker.state == CircuitState.CLOSED
        assert breaker.stats.consecutive_failures == 0

    async def test_non_excluded_exception_counts_as_failure(self):
        breaker = CircuitBreaker(
            "test", fail_threshold=2,
            excluded_exceptions=(ValueError,),
        )
        mock_fn = AsyncMock(side_effect=TypeError("unexpected"))

        for _ in range(2):
            with pytest.raises(TypeError):
                await breaker.call(mock_fn)

        assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
class TestCircuitBreakerDecorator:
    """Tests for using circuit breaker as a decorator."""

    async def test_decorator_wraps_function(self):
        breaker = CircuitBreaker("test")

        @breaker
        async def my_func():
            return 42

        result = await my_func()
        assert result == 42
        assert breaker.stats.total_calls == 1


class TestCircuitBreakerGetStatus:
    """Tests for get_status method."""

    def test_get_status_returns_complete_dict(self):
        breaker = CircuitBreaker("test", fail_threshold=5, reset_timeout=60)
        status = breaker.get_status()

        assert status["name"] == "test"
        assert status["state"] == "closed"
        assert "stats" in status
        assert status["config"]["fail_threshold"] == 5
        assert status["config"]["reset_timeout"] == 60
        assert "time_since_state_change" in status


# ---------------------------------------------------------------------------
# CircuitBreakerRegistry tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerRegistry:
    """Tests for the circuit breaker registry."""

    def test_get_creates_new_breaker(self):
        # Use a fresh registry
        registry = CircuitBreakerRegistry.__new__(CircuitBreakerRegistry)
        registry._breakers = {}

        breaker = registry.get("new_service", fail_threshold=3)
        assert isinstance(breaker, CircuitBreaker)
        assert breaker.name == "new_service"

    def test_get_returns_existing_breaker(self):
        registry = CircuitBreakerRegistry.__new__(CircuitBreakerRegistry)
        registry._breakers = {}

        b1 = registry.get("same_service")
        b2 = registry.get("same_service")
        assert b1 is b2

    def test_get_all_statuses(self):
        registry = CircuitBreakerRegistry.__new__(CircuitBreakerRegistry)
        registry._breakers = {}

        registry.get("service_a")
        registry.get("service_b")

        statuses = registry.get_all_statuses()
        assert "service_a" in statuses
        assert "service_b" in statuses

    def test_reset_all(self):
        registry = CircuitBreakerRegistry.__new__(CircuitBreakerRegistry)
        registry._breakers = {}

        breaker = registry.get("test_reset", fail_threshold=1)
        # Manually set to open
        breaker._state = CircuitState.OPEN
        breaker._stats.failed_calls = 5

        registry.reset_all()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.stats.failed_calls == 0


# ---------------------------------------------------------------------------
# with_retry decorator tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWithRetryDecorator:
    """Tests for the with_retry decorator function."""

    async def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        result = await flaky_func()
        assert result == "ok"
        assert call_count == 3

    async def test_raises_after_max_attempts_exhausted(self):
        @with_retry(max_attempts=2, min_wait=0.01, max_wait=0.02)
        async def always_fail():
            raise ConnectionError("permanent")

        with pytest.raises(ConnectionError, match="permanent"):
            await always_fail()

    async def test_succeeds_on_first_try(self):
        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
        async def ok_func():
            return 42

        result = await ok_func()
        assert result == 42


# ---------------------------------------------------------------------------
# with_circuit_breaker decorator tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWithCircuitBreakerDecorator:
    """Tests for the with_circuit_breaker combined decorator."""

    async def test_basic_circuit_breaker_decorator(self):
        CircuitBreakerRegistry._instance = None
        reg = CircuitBreakerRegistry()
        reg._breakers = {}

        @with_circuit_breaker("test_wcb", fail_threshold=3)
        async def my_api_call():
            return "data"

        result = await my_api_call()
        assert result == "data"

    async def test_circuit_breaker_with_retry_config(self):
        CircuitBreakerRegistry._instance = None
        reg = CircuitBreakerRegistry()
        reg._breakers = {}

        call_count = 0

        @with_circuit_breaker(
            "test_wcb_retry",
            fail_threshold=10,
            with_retry_config={"max_attempts": 3, "min_wait": 0.01, "max_wait": 0.02},
        )
        async def flaky_api():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "recovered"

        result = await flaky_api()
        assert result == "recovered"
        assert call_count == 3

    async def test_circuit_opens_through_decorator(self):
        CircuitBreakerRegistry._instance = None
        reg = CircuitBreakerRegistry()
        reg._breakers = {}

        @with_circuit_breaker("test_wcb_open", fail_threshold=2, reset_timeout=60)
        async def bad_api():
            raise RuntimeError("always fails")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                await bad_api()

        with pytest.raises(CircuitBreakerError):
            await bad_api()
