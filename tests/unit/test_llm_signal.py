"""Tests for LLMSignalStrategy — prompt validation and should_trade logic."""

import pytest

from src.strategy.llm_signal import MAX_CUSTOM_PROMPT_LENGTH


class TestCustomPromptValidation:
    """Verify custom prompt length limits."""

    def _make_strategy(self, custom_prompt: str = "", **overrides):
        """Helper to build strategy params dict (does NOT call external APIs)."""
        from src.strategy.llm_signal import LLMSignalStrategy

        params = {
            "llm_provider": "groq",
            "llm_api_key": "test-key-12345",
            "custom_prompt": custom_prompt,
            "temperature": 0.3,
            **overrides,
        }
        return LLMSignalStrategy(params)

    def test_empty_prompt_uses_default(self):
        strategy = self._make_strategy("")
        assert "professional cryptocurrency" in strategy.prompt

    def test_no_custom_prompt_uses_default(self):
        strategy = self._make_strategy()
        assert "professional cryptocurrency" in strategy.prompt

    def test_short_custom_prompt_accepted(self):
        strategy = self._make_strategy("Go LONG on dips.")
        assert strategy.prompt == "Go LONG on dips."

    def test_prompt_at_limit_accepted(self):
        prompt = "x" * MAX_CUSTOM_PROMPT_LENGTH
        strategy = self._make_strategy(prompt)
        assert strategy.prompt == prompt

    def test_prompt_over_limit_rejected(self):
        prompt = "x" * (MAX_CUSTOM_PROMPT_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            self._make_strategy(prompt)

    def test_prompt_way_over_limit_rejected(self):
        prompt = "x" * 10000
        with pytest.raises(ValueError, match="too long"):
            self._make_strategy(prompt)

    def test_whitespace_only_prompt_uses_default(self):
        strategy = self._make_strategy("   \n  ")
        assert "professional cryptocurrency" in strategy.prompt

    def test_no_api_key_raises(self):
        with pytest.raises(ValueError, match="No API key"):
            self._make_strategy("", llm_api_key="")


class TestShouldTrade:
    """Verify the confidence threshold gate."""

    def _make_strategy(self):
        from src.strategy.llm_signal import LLMSignalStrategy

        return LLMSignalStrategy({
            "llm_provider": "groq",
            "llm_api_key": "test-key-12345",
        })

    def _make_signal(self, confidence: int, entry_price: float = 100.0):
        from src.strategy.base import SignalDirection, TradeSignal
        from datetime import datetime

        return TradeSignal(
            direction=SignalDirection.LONG,
            confidence=confidence,
            symbol="BTCUSDT",
            entry_price=entry_price,
            target_price=104.0,
            stop_loss=98.5,
            reason="test",
            metrics_snapshot={},
            timestamp=datetime.utcnow(),
        )

    @pytest.mark.asyncio
    async def test_high_confidence_accepted(self):
        strategy = self._make_strategy()
        ok, msg = await strategy.should_trade(self._make_signal(80))
        assert ok is True

    @pytest.mark.asyncio
    async def test_low_confidence_rejected(self):
        strategy = self._make_strategy()
        ok, msg = await strategy.should_trade(self._make_signal(30))
        assert ok is False
        assert "too low" in msg

    @pytest.mark.asyncio
    async def test_exactly_60_accepted(self):
        strategy = self._make_strategy()
        ok, msg = await strategy.should_trade(self._make_signal(60))
        assert ok is True

    @pytest.mark.asyncio
    async def test_59_rejected(self):
        strategy = self._make_strategy()
        ok, msg = await strategy.should_trade(self._make_signal(59))
        assert ok is False

    @pytest.mark.asyncio
    async def test_zero_entry_price_rejected(self):
        strategy = self._make_strategy()
        ok, msg = await strategy.should_trade(self._make_signal(80, entry_price=0))
        assert ok is False
        assert "entry price" in msg
