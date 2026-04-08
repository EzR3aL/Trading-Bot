"""Test the self-managed strategy interface added for copy trading."""
import pytest
from src.strategy.base import BaseStrategy


class _NormalStrategy(BaseStrategy):
    async def generate_signal(self, symbol):  # type: ignore[override]
        return None
    async def should_trade(self, signal):  # type: ignore[override]
        return False, ""
    @classmethod
    def get_param_schema(cls):
        return {}
    @classmethod
    def get_description(cls):
        return ""


def test_base_strategy_default_is_not_self_managed():
    s = _NormalStrategy()
    assert s.is_self_managed is False


@pytest.mark.asyncio
async def test_base_strategy_run_tick_default_is_noop():
    s = _NormalStrategy()
    # Default run_tick should be a safe no-op for non-self-managed strategies
    await s.run_tick(ctx=None)
