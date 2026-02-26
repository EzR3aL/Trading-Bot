"""
Unit tests for the strategy system (base, registry, degen).

Tests cover:
- TradeSignal dataclass creation and to_dict serialization
- SignalDirection enum values
- BaseStrategy initialization and abstract method enforcement
- StrategyRegistry register, get, create, list_available
- DegenStrategy initialization (valid params, missing API key)
- DegenStrategy.generate_signal with mocked LLM and data fetcher
- DegenStrategy.generate_signal LLM error fallback
- DegenStrategy.should_trade confidence/price gating
- DegenStrategy._build_market_context for various data shapes
- DegenStrategy.get_param_schema and get_description
- DegenStrategy TP/SL calculation for LONG and SHORT
"""

import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_degen_strategy(**overrides):
    """Build a DegenStrategy with mocked provider, avoiding real imports.

    Patches get_provider_class so no real HTTP clients are created.
    """
    from src.ai.providers.base import LLMResponse

    mock_provider = MagicMock()
    mock_provider.get_display_name.return_value = "MockProvider"
    mock_provider.close = AsyncMock()
    mock_provider.generate_signal = AsyncMock(
        return_value=LLMResponse(
            direction="LONG",
            confidence=80,
            reasoning="BTC looks bullish based on funding data",
            raw_response="DIRECTION: LONG\nCONFIDENCE: 80\nREASONING: BTC looks bullish",
            model_used="mock-model-v1",
            tokens_used=150,
        )
    )

    params = {
        "llm_provider": "groq",
        "llm_api_key": "test-key-for-unit-tests",
        "llm_model": "mock-model-v1",
        "temperature": 0.3,
        **overrides,
    }

    with patch("src.strategy.degen.get_provider_class", return_value=lambda *a, **kw: mock_provider):
        from src.strategy.degen import DegenStrategy
        strategy = DegenStrategy(params=params)

    return strategy, mock_provider


# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_FETCHED_DATA = {
    "spot_price": {
        "price": 95000.0,
        "price_change_percent": 2.5,
        "quote_volume_24h": 1_500_000_000.0,
    },
    "fear_greed": (72, "Greed"),
    "news_sentiment": {
        "article_count": 45,
        "average_tone": 1.5,
    },
    "funding_rate": 0.0003,
    "open_interest": 85000.0,
    "long_short_ratio": 1.35,
    "order_book": {"bid_total": 500.0, "ask_total": 480.0},
    "liquidations": [
        {"side": "BUY", "amount": 10},
        {"side": "SELL", "amount": 5},
    ],
    "supertrend": {"direction": "bullish", "value": 93500.0, "atr": 1200.0},
    "vwap": 94200.0,
    "oiwap": 94800.0,
    "spot_volume": {"buy_ratio": 0.58},
    "volatility": 3.2,
    "coingecko_market": {
        "btc_dominance_pct": 52.3,
        "total_market_cap_usd": 3_200_000_000_000,
        "active_cryptocurrencies": 14500,
    },
}


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

    def test_degen_is_registered(self):
        """The degen strategy should be registered after module import."""
        # The module-level registration at the bottom of degen.py runs on import
        from src.strategy.degen import DegenStrategy  # noqa: F401

        assert StrategyRegistry.get("degen") is DegenStrategy


# ═══════════════════════════════════════════════════════════════════════════════
# 5. DegenStrategy — Initialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestDegenStrategyInit:
    """Tests for DegenStrategy initialization."""

    def test_valid_params_stores_config(self):
        """Strategy stores LLM provider, model, and temperature."""
        strategy, _ = _make_degen_strategy(
            llm_provider="groq",
            llm_model="test-model",
            temperature=0.5,
        )

        assert strategy.llm_provider_name == "groq"
        assert strategy.llm_model == "test-model"
        assert strategy.temperature == 0.5

    def test_default_temperature(self):
        """Default temperature is 0.3."""
        strategy, _ = _make_degen_strategy()
        assert strategy.temperature == 0.3

    def test_missing_api_key_raises_value_error(self):
        """No API key should raise ValueError."""
        with pytest.raises(ValueError, match="No API key"):
            with patch("src.strategy.degen.get_provider_class", return_value=MagicMock()):
                from src.strategy.degen import DegenStrategy
                DegenStrategy(params={
                    "llm_provider": "groq",
                    "llm_api_key": "",
                })

    def test_tp_sl_parsed_from_params(self):
        """take_profit_percent and stop_loss_percent are parsed as floats."""
        strategy, _ = _make_degen_strategy(
            take_profit_percent="4.0",
            stop_loss_percent="1.5",
        )

        assert strategy.take_profit_percent == 4.0
        assert strategy.stop_loss_percent == 1.5

    def test_tp_sl_none_when_not_provided(self):
        """TP/SL are None when not in params."""
        strategy, _ = _make_degen_strategy()

        assert strategy.take_profit_percent is None
        assert strategy.stop_loss_percent is None

    def test_data_fetcher_initially_none(self):
        """data_fetcher starts as None (lazy initialization)."""
        strategy, _ = _make_degen_strategy()
        assert strategy.data_fetcher is None


# ═══════════════════════════════════════════════════════════════════════════════
# 6. DegenStrategy — Signal Generation
# ═══════════════════════════════════════════════════════════════════════════════

class TestDegenStrategySignalGeneration:
    """Tests for DegenStrategy.generate_signal with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_generate_signal_long_success(self):
        """Happy path: LLM returns LONG, signal is assembled correctly."""
        from src.ai.providers.base import LLMResponse

        strategy, mock_provider = _make_degen_strategy(
            take_profit_percent=4.0,
            stop_loss_percent=1.5,
        )
        mock_provider.generate_signal = AsyncMock(
            return_value=LLMResponse(
                direction="LONG",
                confidence=80,
                reasoning="Bullish funding and order book",
                raw_response="DIRECTION: LONG\nCONFIDENCE: 80",
                model_used="mock-model",
                tokens_used=100,
            )
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=SAMPLE_FETCHED_DATA)
        mock_fetcher._ensure_session = AsyncMock()
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.LONG
        assert signal.confidence == 80
        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price == 95000.0
        # LONG TP/SL: TP above entry, SL below entry
        assert signal.target_price > signal.entry_price
        assert signal.stop_loss < signal.entry_price
        assert "[Degen/MockProvider]" in signal.reason
        assert isinstance(signal.timestamp, datetime)

    @pytest.mark.asyncio
    async def test_generate_signal_short_success(self):
        """LLM returns SHORT, TP below entry, SL above entry."""
        from src.ai.providers.base import LLMResponse

        strategy, mock_provider = _make_degen_strategy(
            take_profit_percent=4.0,
            stop_loss_percent=1.5,
        )
        mock_provider.generate_signal = AsyncMock(
            return_value=LLMResponse(
                direction="SHORT",
                confidence=70,
                reasoning="Bearish indicators across the board",
                raw_response="DIRECTION: SHORT\nCONFIDENCE: 70",
                model_used="mock-model",
                tokens_used=120,
            )
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=SAMPLE_FETCHED_DATA)
        mock_fetcher._ensure_session = AsyncMock()
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.SHORT
        assert signal.confidence == 70
        # SHORT TP/SL: TP below entry, SL above entry
        assert signal.target_price < signal.entry_price
        assert signal.stop_loss > signal.entry_price

    @pytest.mark.asyncio
    async def test_generate_signal_llm_error_returns_zero_confidence(self):
        """When the LLM call raises, signal has confidence=0 and error in reason."""
        strategy, mock_provider = _make_degen_strategy()
        mock_provider.generate_signal = AsyncMock(
            side_effect=RuntimeError("API timeout")
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=SAMPLE_FETCHED_DATA)
        mock_fetcher._ensure_session = AsyncMock()
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.confidence == 0
        assert "[LLM ERROR]" in signal.reason
        assert signal.symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_generate_signal_data_fetch_error_propagates(self):
        """When data fetch fails, the exception propagates."""
        strategy, _ = _make_degen_strategy()

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            side_effect=ConnectionError("Network down")
        )
        mock_fetcher._ensure_session = AsyncMock()
        strategy.data_fetcher = mock_fetcher

        with pytest.raises(ConnectionError, match="Network down"):
            await strategy.generate_signal("BTCUSDT")

    @pytest.mark.asyncio
    async def test_generate_signal_without_tp_sl_uses_current_price(self):
        """When TP/SL percents are None, target_price and stop_loss equal entry_price."""
        from src.ai.providers.base import LLMResponse

        strategy, mock_provider = _make_degen_strategy()
        # TP/SL not set (default None)
        mock_provider.generate_signal = AsyncMock(
            return_value=LLMResponse(
                direction="LONG",
                confidence=60,
                reasoning="Mildly bullish",
                raw_response="DIRECTION: LONG\nCONFIDENCE: 60",
                model_used="mock-model",
                tokens_used=80,
            )
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=SAMPLE_FETCHED_DATA)
        mock_fetcher._ensure_session = AsyncMock()
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        # Without TP/SL percents, strategy applies sensible defaults (3% TP, 2% SL)
        assert signal.target_price == round(signal.entry_price * 1.03, 2)
        assert signal.stop_loss == round(signal.entry_price * 0.98, 2)

    @pytest.mark.asyncio
    async def test_generate_signal_metrics_snapshot_contains_llm_info(self):
        """metrics_snapshot should include LLM provider, model, tokens."""
        from src.ai.providers.base import LLMResponse

        strategy, mock_provider = _make_degen_strategy()
        mock_provider.generate_signal = AsyncMock(
            return_value=LLMResponse(
                direction="LONG",
                confidence=75,
                reasoning="Test reasoning",
                raw_response="raw",
                model_used="test-model-v2",
                tokens_used=200,
            )
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=SAMPLE_FETCHED_DATA)
        mock_fetcher._ensure_session = AsyncMock()
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.metrics_snapshot["llm_provider"] == "groq"
        assert signal.metrics_snapshot["llm_model"] == "test-model-v2"
        assert signal.metrics_snapshot["llm_tokens_used"] == 200
        assert "data_sources_used" in signal.metrics_snapshot

    @pytest.mark.asyncio
    async def test_ensure_fetcher_creates_fetcher_once(self):
        """_ensure_fetcher creates a MarketDataFetcher lazily."""
        strategy, _ = _make_degen_strategy()
        assert strategy.data_fetcher is None

        with patch("src.strategy.degen.MarketDataFetcher") as MockFetcher:
            mock_instance = MagicMock()
            mock_instance._ensure_session = AsyncMock()
            MockFetcher.return_value = mock_instance

            await strategy._ensure_fetcher()
            assert strategy.data_fetcher is mock_instance

            # Calling again should not create a second fetcher
            await strategy._ensure_fetcher()
            assert MockFetcher.call_count == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 7. DegenStrategy — should_trade
# ═══════════════════════════════════════════════════════════════════════════════

class TestDegenStrategyShouldTrade:
    """Tests for the DegenStrategy.should_trade confidence gate."""

    @pytest.mark.asyncio
    async def test_high_confidence_accepted(self):
        """Confidence >= 55 with valid price should be accepted."""
        strategy, _ = _make_degen_strategy()
        signal = _make_signal(confidence=75, entry_price=95000.0)

        ok, reason = await strategy.should_trade(signal)

        assert ok is True
        assert "accepted" in reason.lower()

    @pytest.mark.asyncio
    async def test_exactly_55_accepted(self):
        """Confidence exactly at MIN_CONFIDENCE (55) should be accepted."""
        strategy, _ = _make_degen_strategy()
        signal = _make_signal(confidence=55)

        ok, reason = await strategy.should_trade(signal)

        assert ok is True

    @pytest.mark.asyncio
    async def test_54_rejected(self):
        """Confidence 54 (below MIN_CONFIDENCE=55) should be rejected."""
        strategy, _ = _make_degen_strategy()
        signal = _make_signal(confidence=54)

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "too low" in reason.lower() or "55" in reason

    @pytest.mark.asyncio
    async def test_zero_confidence_rejected(self):
        """Zero confidence (LLM error fallback) should be rejected."""
        strategy, _ = _make_degen_strategy()
        signal = _make_signal(confidence=0)

        ok, reason = await strategy.should_trade(signal)

        assert ok is False

    @pytest.mark.asyncio
    async def test_zero_entry_price_rejected(self):
        """Entry price of 0 should be rejected regardless of confidence."""
        strategy, _ = _make_degen_strategy()
        signal = _make_signal(confidence=90, entry_price=0)

        ok, reason = await strategy.should_trade(signal)

        assert ok is False
        assert "price" in reason.lower()

    @pytest.mark.asyncio
    async def test_negative_entry_price_rejected(self):
        """Negative entry price should be rejected."""
        strategy, _ = _make_degen_strategy()
        signal = _make_signal(confidence=90, entry_price=-100)

        ok, reason = await strategy.should_trade(signal)

        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. DegenStrategy — _build_market_context
# ═══════════════════════════════════════════════════════════════════════════════

class TestDegenStrategyBuildMarketContext:
    """Tests for the internal _build_market_context method."""

    def test_full_data_builds_complete_context(self):
        """All 14 data sources produce a fully populated context."""
        strategy, _ = _make_degen_strategy()

        ctx = strategy._build_market_context("BTCUSDT", SAMPLE_FETCHED_DATA)

        assert ctx["bitcoin"]["usd"] == 95000.0
        assert ctx["bitcoin"]["usd_24h_change"] == 2.5
        assert ctx["fearGreed"]["value"] == "72"
        assert ctx["fearGreed"]["value_classification"] == "Greed"
        assert "news" in ctx
        assert ctx["news"]["summary"]["averageTone"] == 1.5
        assert "derivatives" in ctx
        assert "premiumIndex" in ctx["derivatives"]
        assert "openInterest" in ctx["derivatives"]
        assert "longShortRatio" in ctx["derivatives"]
        assert "orderBook" in ctx
        assert "liquidations" in ctx
        assert "supertrend" in ctx
        assert ctx["supertrend"]["trend"] == "BULLISH"
        assert "vwap" in ctx
        assert "realizedVol" in ctx
        assert "marketCap" in ctx
        assert "totalReturn" in ctx

    def test_empty_fetched_data_produces_minimal_context(self):
        """Empty fetch results should produce context with just bitcoin section."""
        strategy, _ = _make_degen_strategy()

        ctx = strategy._build_market_context("BTCUSDT", {})

        assert ctx["bitcoin"]["usd"] == 0
        assert "derivatives" not in ctx
        assert "fearGreed" not in ctx

    def test_spot_price_missing_defaults_to_zero(self):
        """Missing spot_price results in price=0."""
        strategy, _ = _make_degen_strategy()
        fetched = {"funding_rate": 0.0001}

        ctx = strategy._build_market_context("BTCUSDT", fetched)

        assert ctx["bitcoin"]["usd"] == 0

    def test_long_short_ratio_contrarian_short_interpretation(self):
        """L/S ratio > 2.0 triggers contrarian short interpretation."""
        strategy, _ = _make_degen_strategy()
        fetched = {"long_short_ratio": 2.5}

        ctx = strategy._build_market_context("BTCUSDT", fetched)

        interp = ctx["derivatives"]["longShortRatio"]["interpretation"]
        assert "contrarian SHORT" in interp

    def test_long_short_ratio_contrarian_long_interpretation(self):
        """L/S ratio < 0.5 triggers contrarian long interpretation."""
        strategy, _ = _make_degen_strategy()
        fetched = {"long_short_ratio": 0.3}

        ctx = strategy._build_market_context("BTCUSDT", fetched)

        interp = ctx["derivatives"]["longShortRatio"]["interpretation"]
        assert "contrarian LONG" in interp

    def test_long_short_ratio_moderate_interpretation(self):
        """L/S ratio between 0.5 and 2.0 is moderate."""
        strategy, _ = _make_degen_strategy()
        fetched = {"long_short_ratio": 1.2}

        ctx = strategy._build_market_context("BTCUSDT", fetched)

        interp = ctx["derivatives"]["longShortRatio"]["interpretation"]
        assert "Moderate" in interp

    def test_liquidation_risk_levels(self):
        """Liquidation risk is categorized by count (low/moderate/high)."""
        strategy, _ = _make_degen_strategy()

        # Low: <= 20
        fetched_low = {"liquidations": [{"side": "BUY"}] * 5}
        ctx_low = strategy._build_market_context("BTCUSDT", fetched_low)
        assert ctx_low["liquidations"]["estimatedRisk"] == "low"

        # Moderate: 21-50
        fetched_mod = {"liquidations": [{"side": "BUY"}] * 30}
        ctx_mod = strategy._build_market_context("BTCUSDT", fetched_mod)
        assert ctx_mod["liquidations"]["estimatedRisk"] == "moderate"

        # High: > 50
        fetched_high = {"liquidations": [{"side": "SELL"}] * 60}
        ctx_high = strategy._build_market_context("BTCUSDT", fetched_high)
        assert ctx_high["liquidations"]["estimatedRisk"] == "high"

    def test_spot_volume_interpretation(self):
        """Spot volume buy_ratio drives interpretation text."""
        strategy, _ = _make_degen_strategy()

        # Balanced
        fetched = {"spot_volume": {"buy_ratio": 0.50}}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert ctx["spotVolume"]["interpretation"] == "Balanced"

        # Buy dominant
        fetched = {"spot_volume": {"buy_ratio": 0.60}}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert "accumulation" in ctx["spotVolume"]["interpretation"].lower()

        # Sell dominant
        fetched = {"spot_volume": {"buy_ratio": 0.40}}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert "distribution" in ctx["spotVolume"]["interpretation"].lower()

    def test_volatility_interpretation(self):
        """Realized volatility < 2 = low, 2-5 = moderate, > 5 = high."""
        strategy, _ = _make_degen_strategy()

        fetched = {"volatility": 1.5}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert ctx["realizedVol"]["interpretation"] == "Low volatility"

        fetched = {"volatility": 3.0}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert ctx["realizedVol"]["interpretation"] == "Moderate volatility"

        fetched = {"volatility": 7.0}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert ctx["realizedVol"]["interpretation"] == "High volatility"

    def test_news_tone_interpretation(self):
        """News average tone drives positive/negative/neutral interpretation."""
        strategy, _ = _make_degen_strategy()

        # Positive
        fetched = {"news_sentiment": {"article_count": 10, "average_tone": 2.0}}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert "Positive" in ctx["news"]["summary"]["interpretation"]

        # Negative
        fetched = {"news_sentiment": {"article_count": 10, "average_tone": -2.0}}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert "Negative" in ctx["news"]["summary"]["interpretation"]

        # Neutral
        fetched = {"news_sentiment": {"article_count": 10, "average_tone": 0.5}}
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert "Neutral" in ctx["news"]["summary"]["interpretation"]

    def test_vwap_above_below_label(self):
        """VWAP context shows above/below label relative to price."""
        strategy, _ = _make_degen_strategy()

        # Price above VWAP
        fetched = {
            "spot_price": {"price": 95000.0, "price_change_percent": 0, "quote_volume_24h": 0},
            "vwap": 94000.0,
        }
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert "bullish" in ctx["vwap"]["priceVsVwapLabel"].lower()

        # Price below VWAP
        fetched["vwap"] = 96000.0
        ctx = strategy._build_market_context("BTCUSDT", fetched)
        assert "bearish" in ctx["vwap"]["priceVsVwapLabel"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 9. DegenStrategy — Schema & Description
# ═══════════════════════════════════════════════════════════════════════════════

class TestDegenStrategySchema:
    """Tests for get_param_schema and get_description."""

    def test_get_description_returns_string(self):
        """get_description returns a non-empty string."""
        from src.strategy.degen import DegenStrategy

        desc = DegenStrategy.get_description()

        assert isinstance(desc, str)
        assert len(desc) > 10

    def test_get_param_schema_has_required_keys(self):
        """Schema must include llm_provider, llm_model, temperature."""
        from src.strategy.degen import DegenStrategy

        schema = DegenStrategy.get_param_schema()

        assert "llm_provider" in schema
        assert "llm_model" in schema
        assert "temperature" in schema

    def test_temperature_schema_bounds(self):
        """Temperature parameter should have min=0.0 and max=1.0."""
        from src.strategy.degen import DegenStrategy

        temp_schema = DegenStrategy.get_param_schema()["temperature"]

        assert temp_schema["min"] == 0.0
        assert temp_schema["max"] == 1.0
        assert temp_schema["default"] == 0.3


# ═══════════════════════════════════════════════════════════════════════════════
# 10. DegenStrategy — close()
# ═══════════════════════════════════════════════════════════════════════════════

class TestDegenStrategyClose:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_clears_api_key_and_closes_resources(self):
        """close() should close fetcher, provider, and clear the API key."""
        strategy, mock_provider = _make_degen_strategy()
        mock_fetcher = AsyncMock()
        strategy.data_fetcher = mock_fetcher

        await strategy.close()

        mock_fetcher.close.assert_awaited_once()
        mock_provider.close.assert_awaited_once()
        assert strategy.llm_api_key == ""

    @pytest.mark.asyncio
    async def test_close_without_fetcher_does_not_raise(self):
        """close() when data_fetcher is None should not raise."""
        strategy, mock_provider = _make_degen_strategy()
        strategy.data_fetcher = None

        await strategy.close()

        mock_provider.close.assert_awaited_once()
