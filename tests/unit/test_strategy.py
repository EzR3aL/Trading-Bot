"""
Unit tests for the strategy system (base, registry).

Tests cover:
- TradeSignal dataclass creation and to_dict serialization
- SignalDirection enum values
- BaseStrategy initialization and abstract method enforcement
- StrategyRegistry register, get, create, list_available
"""

import json
import pytest
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.base import (
    BaseStrategy,
    SignalDirection,
    StrategyRegistry,
    TradeSignal,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_signal(
    direction=SignalDirection.LONG,
    confidence=75,
    symbol="BTCUSDT",
    entry_price=95000.0,
    target_price=97000.0,
    stop_loss=93000.0,
    reason="test signal",
):
    """Create a TradeSignal with sensible defaults."""
    return TradeSignal(
        direction=direction,
        confidence=confidence,
        symbol=symbol,
        entry_price=entry_price,
        target_price=target_price,
        stop_loss=stop_loss,
        reason=reason,
        metrics_snapshot={"test": True},
        timestamp=datetime(2026, 1, 15, 12, 0, 0),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TradeSignal
# ═══════════════════════════════════════════════════════════════════════════════

class TestTradeSignal:
    """Tests for the TradeSignal dataclass."""

    def test_create_long_signal(self):
        """TradeSignal stores all fields for a LONG signal."""
        signal = _make_signal(direction=SignalDirection.LONG)

        assert signal.direction == SignalDirection.LONG
        assert signal.confidence == 75
        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price == 95000.0

    def test_create_short_signal(self):
        """TradeSignal stores all fields for a SHORT signal."""
        signal = _make_signal(direction=SignalDirection.SHORT)

        assert signal.direction == SignalDirection.SHORT

    def test_to_dict_serialization(self):
        """to_dict produces a JSON-serializable dictionary."""
        signal = _make_signal()
        result = signal.to_dict()

        assert result["direction"] == "long"
        assert result["confidence"] == 75
        assert result["symbol"] == "BTCUSDT"
        assert result["entry_price"] == 95000.0
        assert result["target_price"] == 97000.0
        assert result["stop_loss"] == 93000.0
        assert result["reason"] == "test signal"
        assert "timestamp" in result
        # Ensure it is JSON serializable
        json.dumps(result)

    def test_to_dict_short_direction_value(self):
        """SHORT direction serializes as 'short'."""
        signal = _make_signal(direction=SignalDirection.SHORT)
        assert signal.to_dict()["direction"] == "short"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SignalDirection
# ═══════════════════════════════════════════════════════════════════════════════

class TestSignalDirection:
    """Tests for the SignalDirection enum."""

    def test_long_value(self):
        assert SignalDirection.LONG.value == "long"

    def test_short_value(self):
        assert SignalDirection.SHORT.value == "short"

    def test_enum_members_count(self):
        assert len(SignalDirection) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 3. BaseStrategy
# ═══════════════════════════════════════════════════════════════════════════════

class TestBaseStrategy:
    """Tests for the abstract BaseStrategy class."""

    def test_cannot_instantiate_directly(self):
        """BaseStrategy is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseStrategy()

    def test_params_default_to_empty_dict(self):
        """When no params given, self.params should be {}."""
        # Create a minimal concrete subclass
        class MinimalStrategy(BaseStrategy):
            async def generate_signal(self, symbol):
                ...

            async def should_trade(self, signal):
                ...

            @classmethod
            def get_param_schema(cls):
                return {}

            @classmethod
            def get_description(cls):
                return "minimal"

        strategy = MinimalStrategy()
        assert strategy.params == {}

    def test_params_stored_correctly(self):
        """Explicit params should be stored."""
        class MinimalStrategy(BaseStrategy):
            async def generate_signal(self, symbol):
                ...

            async def should_trade(self, signal):
                ...

            @classmethod
            def get_param_schema(cls):
                return {}

            @classmethod
            def get_description(cls):
                return "minimal"

        strategy = MinimalStrategy(params={"foo": "bar"})
        assert strategy.params == {"foo": "bar"}

    def test_subclass_must_implement_generate_signal(self):
        """Omitting generate_signal raises TypeError."""
        with pytest.raises(TypeError):
            class Incomplete(BaseStrategy):
                async def should_trade(self, signal):
                    ...

                @classmethod
                def get_param_schema(cls):
                    return {}

                @classmethod
                def get_description(cls):
                    return "incomplete"

            Incomplete()

    def test_subclass_must_implement_should_trade(self):
        """Omitting should_trade raises TypeError."""
        with pytest.raises(TypeError):
            class Incomplete(BaseStrategy):
                async def generate_signal(self, symbol):
                    ...

                @classmethod
                def get_param_schema(cls):
                    return {}

                @classmethod
                def get_description(cls):
                    return "incomplete"

            Incomplete()

    def test_subclass_must_implement_get_param_schema(self):
        """Omitting get_param_schema raises TypeError."""
        with pytest.raises(TypeError):
            class Incomplete(BaseStrategy):
                async def generate_signal(self, symbol):
                    ...

                async def should_trade(self, signal):
                    ...

                @classmethod
                def get_description(cls):
                    return "incomplete"

            Incomplete()

    def test_subclass_must_implement_get_description(self):
        """Omitting get_description raises TypeError."""
        with pytest.raises(TypeError):
            class Incomplete(BaseStrategy):
                async def generate_signal(self, symbol):
                    ...

                async def should_trade(self, signal):
                    ...

                @classmethod
                def get_param_schema(cls):
                    return {}

            Incomplete()

    @pytest.mark.asyncio
    async def test_close_is_noop_by_default(self):
        """Base close() should be a no-op (does not raise)."""
        class MinimalStrategy(BaseStrategy):
            async def generate_signal(self, symbol):
                ...

            async def should_trade(self, signal):
                ...

            @classmethod
            def get_param_schema(cls):
                return {}

            @classmethod
            def get_description(cls):
                return "minimal"

        strategy = MinimalStrategy()
        await strategy.close()  # Should not raise


# ═══════════════════════════════════════════════════════════════════════════════
# 4. StrategyRegistry
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyRegistry:
    """Tests for the StrategyRegistry."""

    def setup_method(self):
        """Save original registry state and restore after each test."""
        self._original = dict(StrategyRegistry._strategies)

    def teardown_method(self):
        """Restore original registry to avoid polluting other tests."""
        StrategyRegistry._strategies = self._original

    def _make_concrete_strategy(self, name="Concrete"):
        """Build a concrete BaseStrategy subclass dynamically."""
        _attrs = {
            "generate_signal": lambda self, symbol: None,
            "should_trade": lambda self, signal: (True, "ok"),
            "get_param_schema": classmethod(lambda cls: {}),
            "get_description": classmethod(lambda cls: f"{name} strategy"),
        }
        # We need async methods — use proper async defs

        class _Strat(BaseStrategy):
            async def generate_signal(self, symbol):
                ...

            async def should_trade(self, signal):
                return True, "ok"

            @classmethod
            def get_param_schema(cls):
                return {"p": {"type": "int", "label": "P", "default": 1, "description": "test"}}

            @classmethod
            def get_description(cls):
                return f"{name} strategy"

        _Strat.__name__ = name
        return _Strat

    def test_register_and_get(self):
        """Registered strategy can be retrieved by name."""
        strat_cls = self._make_concrete_strategy("Alpha")
        StrategyRegistry.register("alpha", strat_cls)

        assert StrategyRegistry.get("alpha") is strat_cls

    def test_get_unknown_raises_key_error(self):
        """Getting an unregistered strategy raises KeyError."""
        with pytest.raises(KeyError, match="not found"):
            StrategyRegistry.get("nonexistent_strategy_xyz")

    def test_register_non_subclass_raises_type_error(self):
        """Registering a non-BaseStrategy class raises TypeError."""
        with pytest.raises(TypeError, match="must be a subclass"):
            StrategyRegistry.register("bad", dict)

    def test_create_returns_instance(self):
        """create() returns an instance of the registered class."""
        strat_cls = self._make_concrete_strategy("Beta")
        StrategyRegistry.register("beta", strat_cls)

        instance = StrategyRegistry.create("beta", params={"x": 1})

        assert isinstance(instance, strat_cls)
        assert isinstance(instance, BaseStrategy)
        assert instance.params == {"x": 1}

    def test_create_with_no_params(self):
        """create() with no params gives empty dict."""
        strat_cls = self._make_concrete_strategy("Gamma")
        StrategyRegistry.register("gamma", strat_cls)

        instance = StrategyRegistry.create("gamma")
        assert instance.params == {}

    def test_list_available_includes_registered(self):
        """list_available returns metadata for registered strategies."""
        strat_cls = self._make_concrete_strategy("Delta")
        StrategyRegistry.register("delta", strat_cls)

        available = StrategyRegistry.list_available()
        names = [entry["name"] for entry in available]

        assert "delta" in names

        delta_entry = next(e for e in available if e["name"] == "delta")
        assert delta_entry["description"] == "Delta strategy"
        assert isinstance(delta_entry["param_schema"], dict)

    def test_register_overwrites_existing(self):
        """Registering with the same name overwrites the previous class."""
        cls_a = self._make_concrete_strategy("A")
        cls_b = self._make_concrete_strategy("B")

        StrategyRegistry.register("overwrite_test", cls_a)
        StrategyRegistry.register("overwrite_test", cls_b)

        assert StrategyRegistry.get("overwrite_test") is cls_b
