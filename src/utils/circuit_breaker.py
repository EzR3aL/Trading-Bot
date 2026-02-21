"""
Circuit Breaker implementation for external API resilience.

Provides fault tolerance for external API calls by:
- Tracking failure counts per service
- Opening circuit after threshold failures
- Auto-recovery after timeout period
- Retry with exponential backoff

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Circuit tripped, requests fail immediately
- HALF_OPEN: Testing if service recovered
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Dict, Any, TypeVar
from functools import wraps

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryError,
)

from src.exceptions import TradingBotError
from src.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "success_rate": (
                self.successful_calls / self.total_calls * 100
                if self.total_calls > 0 else 0
            ),
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
        }


class CircuitBreakerError(TradingBotError):
    """Raised when circuit is open and request is rejected."""

    def __init__(self, service_name: str, state: CircuitState, retry_after: float = 0):
        self.service_name = service_name
        self.state = state
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker open for {service_name} (state={state.value})")
        super().__init__(
            f"Circuit breaker for '{service_name}' is {state.value}. "
            f"Retry after {retry_after:.1f}s"
        )


class CircuitBreaker:
    """
    Async-compatible circuit breaker for external API calls.

    Usage:
        breaker = CircuitBreaker("binance_api", fail_threshold=5, reset_timeout=60)

        @breaker
        async def fetch_data():
            return await api.get_data()

        # Or use directly:
        result = await breaker.call(api.get_data)
    """

    def __init__(
        self,
        name: str,
        fail_threshold: int = 5,
        reset_timeout: float = 60.0,
        half_open_max_calls: int = 3,
        excluded_exceptions: tuple = (),
    ):
        """
        Initialize the circuit breaker.

        Args:
            name: Identifier for this circuit (e.g., "binance_api")
            fail_threshold: Number of failures before opening circuit
            reset_timeout: Seconds to wait before trying again (half-open)
            half_open_max_calls: Max calls allowed in half-open state
            excluded_exceptions: Exceptions that don't count as failures
        """
        self.name = name
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self.half_open_max_calls = half_open_max_calls
        self.excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._last_state_change = time.time()
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def stats(self) -> CircuitStats:
        """Get circuit statistics."""
        return self._stats

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self._state == CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        return time.time() - self._last_state_change >= self.reset_timeout

    async def _transition_to(self, new_state: CircuitState):
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._last_state_change = time.time()

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0

        logger.info(
            f"Circuit '{self.name}' state change: {old_state.value} -> {new_state.value}"
        )

    async def _record_success(self):
        """Record a successful call."""
        async with self._lock:
            self._stats.total_calls += 1
            self._stats.successful_calls += 1
            self._stats.consecutive_successes += 1
            self._stats.consecutive_failures = 0
            self._stats.last_success_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                if self._half_open_calls >= self.half_open_max_calls:
                    await self._transition_to(CircuitState.CLOSED)
                    logger.info(f"Circuit '{self.name}' recovered after {self.half_open_max_calls} successful calls")

    async def _record_failure(self, error: Exception):
        """Record a failed call."""
        async with self._lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._stats.last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Single failure in half-open goes back to open
                await self._transition_to(CircuitState.OPEN)
                logger.warning(f"Circuit '{self.name}' re-opened after failure in half-open state")

            elif self._state == CircuitState.CLOSED:
                if self._stats.consecutive_failures >= self.fail_threshold:
                    await self._transition_to(CircuitState.OPEN)
                    logger.error(
                        f"Circuit '{self.name}' OPENED after {self.fail_threshold} consecutive failures. "
                        f"Last error: {error}"
                    )

    async def _can_execute(self) -> bool:
        """Check if a call can be executed."""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    await self._transition_to(CircuitState.HALF_OPEN)
                    return True
                else:
                    self._stats.rejected_calls += 1
                    return False

            if self._state == CircuitState.HALF_OPEN:
                return True

            return False  # pragma: no cover — all enum states handled above

    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute a function through the circuit breaker.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result of the function

        Raises:
            CircuitBreakerError: If circuit is open
            Exception: If the underlying function fails
        """
        if not await self._can_execute():
            retry_after = self.reset_timeout - (time.time() - self._last_state_change)
            raise CircuitBreakerError(self.name, self._state, max(0, retry_after))

        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result

        except Exception as e:
            if isinstance(e, self.excluded_exceptions):
                # Don't count excluded exceptions as failures
                await self._record_success()
                raise

            await self._record_failure(e)
            raise

    def __call__(self, func: Callable) -> Callable:
        """Decorator to wrap a function with circuit breaker."""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)
        return wrapper

    def get_status(self) -> Dict[str, Any]:
        """Get circuit breaker status for monitoring."""
        return {
            "name": self.name,
            "state": self._state.value,
            "stats": self._stats.to_dict(),
            "config": {
                "fail_threshold": self.fail_threshold,
                "reset_timeout": self.reset_timeout,
                "half_open_max_calls": self.half_open_max_calls,
            },
            "time_since_state_change": time.time() - self._last_state_change,
        }


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    Usage:
        registry = CircuitBreakerRegistry()

        # Get or create a circuit breaker
        breaker = registry.get("binance_api")

        # Get all statuses
        statuses = registry.get_all_statuses()
    """

    _instance: Optional['CircuitBreakerRegistry'] = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._breakers: Dict[str, CircuitBreaker] = {}
        return cls._instance

    def get(
        self,
        name: str,
        fail_threshold: int = 5,
        reset_timeout: float = 60.0,
        **kwargs
    ) -> CircuitBreaker:
        """
        Get or create a circuit breaker by name.

        Args:
            name: Unique identifier
            fail_threshold: Failures before opening
            reset_timeout: Recovery timeout in seconds
            **kwargs: Additional CircuitBreaker arguments

        Returns:
            CircuitBreaker instance
        """
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                fail_threshold=fail_threshold,
                reset_timeout=reset_timeout,
                **kwargs
            )
            logger.debug(f"Created circuit breaker: {name}")

        return self._breakers[name]

    def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all circuit breakers."""
        return {
            name: breaker.get_status()
            for name, breaker in self._breakers.items()
        }

    def reset_all(self):
        """Reset all circuit breakers to closed state."""
        for breaker in self._breakers.values():
            breaker._state = CircuitState.CLOSED
            breaker._stats = CircuitStats()
            breaker._last_state_change = time.time()
        logger.info("All circuit breakers reset")


# Global registry instance
circuit_registry = CircuitBreakerRegistry()


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 10.0,
    retry_on: tuple = (Exception,),
):
    """
    Decorator for retry with exponential backoff.

    Args:
        max_attempts: Maximum retry attempts
        min_wait: Minimum wait between retries (seconds)
        max_wait: Maximum wait between retries (seconds)
        retry_on: Tuple of exceptions to retry on

    Usage:
        @with_retry(max_attempts=3, min_wait=1.0, max_wait=10.0)
        async def fetch_data():
            return await api.get_data()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            @retry(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
                retry=retry_if_exception_type(retry_on),
                before_sleep=before_sleep_log(logger, log_level=20),  # INFO level
                reraise=True,
            )
            async def _retry_wrapper():
                return await func(*args, **kwargs)

            try:
                return await _retry_wrapper()
            except RetryError as e:  # pragma: no cover — reraise=True raises original exception
                logger.error(f"All {max_attempts} retry attempts failed for {func.__name__}")
                raise e.last_attempt.exception()

        return wrapper
    return decorator


def with_circuit_breaker(
    name: str,
    fail_threshold: int = 5,
    reset_timeout: float = 60.0,
    with_retry_config: Optional[Dict[str, Any]] = None,
):
    """
    Combined decorator for circuit breaker with optional retry.

    Args:
        name: Circuit breaker name
        fail_threshold: Failures before opening circuit
        reset_timeout: Recovery timeout
        with_retry_config: Optional retry configuration dict
                          {"max_attempts": 3, "min_wait": 1.0, "max_wait": 10.0}

    Usage:
        @with_circuit_breaker("binance_api", fail_threshold=5, reset_timeout=60)
        async def fetch_data():
            return await api.get_data()

        # With retry:
        @with_circuit_breaker(
            "binance_api",
            fail_threshold=5,
            with_retry_config={"max_attempts": 3, "min_wait": 1.0}
        )
        async def fetch_data():
            return await api.get_data()
    """
    breaker = circuit_registry.get(name, fail_threshold, reset_timeout)

    def decorator(func: Callable) -> Callable:
        # Apply retry if configured
        if with_retry_config:
            func = with_retry(**with_retry_config)(func)

        # Apply circuit breaker
        return breaker(func)

    return decorator
