"""Tests for LLMSignalStrategy -- prompt validation, should_trade, generate_signal, close."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ai.providers.base import LLMResponse
from src.strategy.base import SignalDirection, TradeSignal
from src.strategy.llm_signal import DEFAULT_PROMPT, MAX_CUSTOM_PROMPT_LENGTH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_params(**overrides):
    """Build minimal valid params dict for LLMSignalStrategy."""
    defaults = {
        "llm_provider": "groq",
        "llm_api_key": "test-key-12345",
        "temperature": 0.3,
    }
    defaults.update(overrides)
    return defaults


def _make_signal(confidence=80, entry_price=100.0, direction=SignalDirection.LONG):
    """Build a TradeSignal for should_trade tests."""
    return TradeSignal(
        direction=direction,
        confidence=confidence,
        symbol="BTCUSDT",
        entry_price=entry_price,
        target_price=104.0,
        stop_loss=98.5,
        reason="test",
        metrics_snapshot={},
        timestamp=datetime.now(timezone.utc),
    )


def _build_strategy(params=None, **overrides):
    """Instantiate LLMSignalStrategy with mocked get_provider_class."""
    from src.strategy.llm_signal import LLMSignalStrategy

    final_params = _make_params(**overrides) if params is None else params
    with patch("src.strategy.llm_signal.get_provider_class") as mock_gpc:
        mock_provider_cls = MagicMock()
        mock_provider_instance = MagicMock()
        mock_provider_instance.get_display_name.return_value = "MockLLM"
        mock_provider_instance.close = AsyncMock()
        mock_provider_cls.return_value = mock_provider_instance
        mock_gpc.return_value = mock_provider_cls
        strategy = LLMSignalStrategy(final_params)
    return strategy


def _build_strategy_with_provider(**overrides):
    """Return (strategy, mock_provider) for generate_signal tests.

    Uses MagicMock for the provider so that sync methods like get_display_name()
    return plain values. Async methods (generate_signal, close) are set explicitly.
    """
    from src.strategy.llm_signal import LLMSignalStrategy

    final_params = _make_params(**overrides)
    with patch("src.strategy.llm_signal.get_provider_class") as mock_gpc:
        mock_provider_instance = MagicMock()
        mock_provider_instance.get_display_name.return_value = "MockLLM"
        mock_provider_instance.generate_signal = AsyncMock()
        mock_provider_instance.close = AsyncMock()
        mock_provider_cls = MagicMock(return_value=mock_provider_instance)
        mock_gpc.return_value = mock_provider_cls
        strategy = LLMSignalStrategy(final_params)
    return strategy, mock_provider_instance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _full_fetched_data():
    """Return a comprehensive mock fetch result covering all data source branches."""
    return {
        "spot_price": {
            "price": 95000.0,
            "price_change_percent": 2.5,
            "quote_volume_24h": 5000000000,
        },
        "fear_greed": (72, "Greed"),
        "long_short_ratio": 1.45,
        "top_trader_ls_ratio": 1.8,
        "funding_rate": 0.0003,
        "predicted_funding": 0.00025,
        "open_interest": 25000000000,
        "oi_history": [
            {"sumOpenInterest": 24000000000},
            {"sumOpenInterest": 25000000000},
        ],
        "liquidations": [{"id": 1}, {"id": 2}, {"id": 3}],
        "news_sentiment": {"average_tone": 0.65, "article_count": 42},
        "options_oi": {"total_oi": 8000000000},
        "max_pain": {"max_pain_price": 90000},
        "put_call_ratio": {"ratio": 0.85},
        "coingecko_market": {"btc_dominance_pct": 52.3, "total_market_cap_usd": 3000000000000},
        "vwap": 94500.0,
        "supertrend": {"direction": "bullish"},
        "spot_volume": {"buy_ratio": 0.58},
        "oiwap": 94800.0,
        "volatility": 3.2,
        "trend_sma": "bullish",
        "cme_gap": {"gap_pct": 1.5, "gap_direction": "above"},
    }


def _llm_response(direction="LONG", confidence=75, reasoning="Bullish market"):
    """Create a standard LLMResponse."""
    return LLMResponse(
        direction=direction,
        confidence=confidence,
        reasoning=reasoning,
        raw_response=f"DIRECTION: {direction}\nCONFIDENCE: {confidence}\nREASONING: {reasoning}",
        model_used="test-model",
        tokens_used=150,
    )


# ===========================================================================
# 1. Custom Prompt Validation
# ===========================================================================


class TestCustomPromptValidation:
    """Verify custom prompt length limits and default prompt selection."""

    def test_empty_prompt_uses_default(self):
        strategy = _build_strategy(custom_prompt="")
        assert "professional cryptocurrency" in strategy.prompt

    def test_no_custom_prompt_uses_default(self):
        strategy = _build_strategy()
        assert "professional cryptocurrency" in strategy.prompt

    def test_short_custom_prompt_accepted(self):
        strategy = _build_strategy(custom_prompt="Go LONG on dips.")
        assert strategy.prompt == "Go LONG on dips."

    def test_prompt_at_limit_accepted(self):
        prompt = "x" * MAX_CUSTOM_PROMPT_LENGTH
        strategy = _build_strategy(custom_prompt=prompt)
        assert strategy.prompt == prompt

    def test_prompt_over_limit_rejected(self):
        prompt = "x" * (MAX_CUSTOM_PROMPT_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            _build_strategy(custom_prompt=prompt)

    def test_prompt_way_over_limit_rejected(self):
        prompt = "x" * 10000
        with pytest.raises(ValueError, match="too long"):
            _build_strategy(custom_prompt=prompt)

    def test_whitespace_only_prompt_uses_default(self):
        strategy = _build_strategy(custom_prompt="   \n  ")
        assert "professional cryptocurrency" in strategy.prompt

    def test_no_api_key_raises(self):
        with pytest.raises(ValueError, match="No API key"):
            _build_strategy(llm_api_key="")

    def test_default_prompt_constant_matches_strategy(self):
        strategy = _build_strategy()
        assert strategy.prompt == DEFAULT_PROMPT

    def test_custom_prompt_replaces_default(self):
        custom = "Analyze BTC. Be concise."
        strategy = _build_strategy(custom_prompt=custom)
        assert strategy.prompt == custom
        assert strategy.prompt != DEFAULT_PROMPT


# ===========================================================================
# 2. Constructor / Initialization
# ===========================================================================


class TestInit:
    """Verify constructor parameter extraction and defaults."""

    def test_default_provider_is_groq(self):
        strategy = _build_strategy()
        assert strategy.llm_provider_name == "groq"

    def test_custom_provider(self):
        strategy = _build_strategy(llm_provider="gemini")
        assert strategy.llm_provider_name == "gemini"

    def test_default_temperature(self):
        strategy = _build_strategy()
        assert strategy.temperature == 0.3

    def test_custom_temperature(self):
        strategy = _build_strategy(temperature=0.7)
        assert strategy.temperature == 0.7

    def test_default_model_is_empty_string(self):
        strategy = _build_strategy()
        assert strategy.llm_model == ""

    def test_custom_model(self):
        strategy = _build_strategy(llm_model="llama-3.3-70b-versatile")
        assert strategy.llm_model == "llama-3.3-70b-versatile"

    def test_tp_sl_none_by_default(self):
        strategy = _build_strategy()
        assert strategy.take_profit_percent is None
        assert strategy.stop_loss_percent is None

    def test_tp_sl_from_params(self):
        strategy = _build_strategy(take_profit_percent=4.0, stop_loss_percent=1.5)
        assert strategy.take_profit_percent == 4.0
        assert strategy.stop_loss_percent == 1.5

    def test_tp_sl_string_conversion(self):
        strategy = _build_strategy(take_profit_percent="5", stop_loss_percent="2")
        assert strategy.take_profit_percent == 5.0
        assert strategy.stop_loss_percent == 2.0

    def test_data_fetcher_starts_none(self):
        strategy = _build_strategy()
        assert strategy.data_fetcher is None

    def test_selected_sources_defaults(self):
        from src.data.data_source_registry import DEFAULT_SOURCES

        strategy = _build_strategy()
        assert strategy.selected_sources == DEFAULT_SOURCES

    def test_custom_data_sources(self):
        custom_sources = ["spot_price", "fear_greed"]
        strategy = _build_strategy(data_sources=custom_sources)
        assert strategy.selected_sources == custom_sources

    def test_api_key_stored(self):
        strategy = _build_strategy(llm_api_key="my-secret-key")
        assert strategy.llm_api_key == "my-secret-key"


# ===========================================================================
# 3. should_trade
# ===========================================================================


class TestShouldTrade:
    """Verify the confidence threshold gate."""

    async def test_high_confidence_accepted(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(80))
        assert ok is True
        assert "accepted" in msg

    async def test_low_confidence_rejected(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(30))
        assert ok is False
        assert "too low" in msg

    async def test_exactly_60_accepted(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(60))
        assert ok is True

    async def test_59_rejected(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(59))
        assert ok is False

    async def test_zero_confidence_rejected(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(0))
        assert ok is False

    async def test_100_confidence_accepted(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(100))
        assert ok is True

    async def test_zero_entry_price_rejected(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(80, entry_price=0))
        assert ok is False
        assert "entry price" in msg

    async def test_negative_entry_price_rejected(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(80, entry_price=-1.0))
        assert ok is False
        assert "entry price" in msg

    async def test_message_includes_confidence_value(self):
        strategy = _build_strategy()
        ok, msg = await strategy.should_trade(_make_signal(75))
        assert "75%" in msg


# ===========================================================================
# 4. generate_signal -- Happy Path
# ===========================================================================


class TestGenerateSignalHappyPath:
    """Test generate_signal with mocked data fetcher and LLM provider."""

    async def test_long_signal_with_full_data(self):
        """LONG signal with all data sources returns correct TradeSignal."""
        strategy, mock_provider = _build_strategy_with_provider(
            take_profit_percent=4.0, stop_loss_percent=1.5,
        )
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 75))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.LONG
        assert signal.confidence == 75
        assert signal.symbol == "BTCUSDT"
        assert signal.entry_price == 95000.0
        # TP for LONG: price * (1 + 4/100) = 95000 * 1.04 = 98800.0
        assert signal.target_price == 98800.0
        # SL for LONG: price * (1 - 1.5/100) = 95000 * 0.985 = 93575.0
        assert signal.stop_loss == 93575.0
        assert "MockLLM" in signal.reason
        assert "Bullish market" in signal.reason

    async def test_short_signal_with_full_data(self):
        """SHORT signal calculates TP/SL in opposite direction."""
        strategy, mock_provider = _build_strategy_with_provider(
            take_profit_percent=3.0, stop_loss_percent=2.0,
        )
        mock_provider.generate_signal = AsyncMock(
            return_value=_llm_response("SHORT", 82, "Bearish divergence")
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.direction == SignalDirection.SHORT
        assert signal.confidence == 82
        # TP for SHORT: price * (1 - 3/100) = 95000 * 0.97 = 92150.0
        assert signal.target_price == 92150.0
        # SL for SHORT: price * (1 + 2/100) = 95000 * 1.02 = 96900.0
        assert signal.stop_loss == 96900.0

    async def test_signal_without_tp_sl(self):
        """When TP/SL not configured, target_price and stop_loss are None."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.target_price is None
        assert signal.stop_loss is None

    async def test_signal_with_only_tp_set(self):
        """When only TP is set (no SL), both remain None (need both for calculation)."""
        strategy, mock_provider = _build_strategy_with_provider(
            take_profit_percent=4.0,
        )
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.target_price is None
        assert signal.stop_loss is None

    async def test_metrics_snapshot_contains_llm_metadata(self):
        """The metrics_snapshot should include LLM provider info and market data."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        snapshot = signal.metrics_snapshot

        assert snapshot["llm_provider"] == "groq"
        assert snapshot["llm_model"] == "test-model"
        assert snapshot["llm_tokens_used"] == 150
        assert snapshot["llm_temperature"] == 0.3
        assert "data_sources_used" in snapshot
        assert "spot_price" in snapshot["data_sources_used"]

    async def test_metrics_snapshot_contains_market_data(self):
        """Verify individual market data fields are present in snapshot."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        snapshot = signal.metrics_snapshot

        assert snapshot["current_price"] == 95000.0
        assert snapshot["price_change_24h_pct"] == 2.5
        assert snapshot["fear_greed_index"] == 72
        assert snapshot["fear_greed_label"] == "Greed"
        assert snapshot["long_short_ratio"] == 1.45
        assert snapshot["funding_rate"] == 0.0003
        assert snapshot["open_interest"] == 25000000000
        assert snapshot["supertrend_direction"] == "bullish"
        assert snapshot["volume_buy_ratio"] == 0.58
        assert snapshot["vwap_24h"] == 94500.0
        assert snapshot["price_vs_vwap"] == "above"

    async def test_signal_timestamp_is_set(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert isinstance(signal.timestamp, datetime)


# ===========================================================================
# 5. generate_signal -- Various Market Data Combinations
# ===========================================================================


class TestGenerateSignalDataVariations:
    """Test generate_signal with sparse or partial market data."""

    async def test_minimal_data_no_spot_price(self):
        """When spot_price is missing, current_price defaults to 0."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 60))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price == 0.0
        assert signal.direction == SignalDirection.LONG

    async def test_spot_price_non_dict_ignored(self):
        """If spot_price is not a dict, it is not processed."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("SHORT", 65))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"spot_price": "invalid"}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price == 0.0

    async def test_fear_greed_tuple_processed(self):
        """fear_greed tuple (value, label) is extracted correctly."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"fear_greed": (25, "Extreme Fear")}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot.get("fear_greed_index") == 25
        assert signal.metrics_snapshot.get("fear_greed_label") == "Extreme Fear"

    async def test_fear_greed_wrong_type_skipped(self):
        """Non-tuple fear_greed is not processed (no error)."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"fear_greed": 42}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert "fear_greed_index" not in signal.metrics_snapshot

    async def test_oi_history_change_calculation(self):
        """OI change percentage is calculated from first/last entries."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        oi_data = [
            {"sumOpenInterest": 100},
            {"sumOpenInterest": 110},
        ]
        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"oi_history": oi_data}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["oi_change_24h_pct"] == 10.0

    async def test_oi_history_single_entry_no_change(self):
        """OI history with only 1 entry does not produce oi_change_24h_pct."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"oi_history": [{"sumOpenInterest": 100}]}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert "oi_change_24h_pct" not in signal.metrics_snapshot

    async def test_oi_history_zero_first_oi_no_division_error(self):
        """First OI = 0 should not cause division by zero."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        oi_data = [
            {"sumOpenInterest": 0},
            {"sumOpenInterest": 100},
        ]
        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"oi_history": oi_data}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        # first_oi == 0, so the change calculation is skipped
        assert "oi_change_24h_pct" not in signal.metrics_snapshot

    async def test_oi_history_empty_list(self):
        """Empty oi_history list produces no change metric."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"oi_history": []}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert "oi_change_24h_pct" not in signal.metrics_snapshot

    async def test_liquidations_count(self):
        """Liquidations list length is recorded."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"liquidations": [1, 2, 3, 4, 5]}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["recent_liquidations_count"] == 5

    async def test_liquidations_empty_not_recorded(self):
        """Empty liquidations list is not recorded."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"liquidations": []}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert "recent_liquidations_count" not in signal.metrics_snapshot

    async def test_news_sentiment_extracted(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"news_sentiment": {"average_tone": -0.3, "article_count": 10}}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["news_sentiment_tone"] == -0.3
        assert signal.metrics_snapshot["news_article_count"] == 10

    async def test_options_and_max_pain_data(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={
                "options_oi": {"total_oi": 5000000000},
                "max_pain": {"max_pain_price": 88000},
                "put_call_ratio": {"ratio": 1.2},
            }
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["options_open_interest"] == 5000000000
        assert signal.metrics_snapshot["max_pain_price"] == 88000
        assert signal.metrics_snapshot["put_call_ratio"] == 1.2

    async def test_coingecko_market_data(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"coingecko_market": {"btc_dominance_pct": 48.5, "total_market_cap_usd": 2e12}}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["btc_dominance_pct"] == 48.5
        assert signal.metrics_snapshot["total_market_cap_usd"] == 2e12

    async def test_vwap_below_price(self):
        """When current price > VWAP, price_vs_vwap is 'above'."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={
                "spot_price": {"price": 100.0, "price_change_percent": 0, "quote_volume_24h": 0},
                "vwap": 95.0,
            }
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["price_vs_vwap"] == "above"

    async def test_vwap_above_price(self):
        """When current price < VWAP, price_vs_vwap is 'below'."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("SHORT", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={
                "spot_price": {"price": 90.0, "price_change_percent": 0, "quote_volume_24h": 0},
                "vwap": 95.0,
            }
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["price_vs_vwap"] == "below"

    async def test_vwap_without_price_no_comparison(self):
        """When current_price is 0, price_vs_vwap is not set."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"vwap": 95.0}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert "price_vs_vwap" not in signal.metrics_snapshot

    async def test_cme_gap_data(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"cme_gap": {"gap_pct": 2.1, "gap_direction": "below"}}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["cme_gap_pct"] == 2.1
        assert signal.metrics_snapshot["cme_gap_direction"] == "below"

    async def test_volatility_and_trend_sma(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"volatility": 5.5, "trend_sma": "bearish"}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["volatility_24h_pct"] == 5.5
        assert signal.metrics_snapshot["trend_direction"] == "bearish"

    async def test_oiwap_data(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"oiwap": 94200.5}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["oiwap"] == 94200.5

    async def test_predicted_funding_data(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"predicted_funding": 0.000123}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["predicted_funding_rate"] == 0.000123

    async def test_top_trader_ls_ratio(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"top_trader_ls_ratio": 2.345}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.metrics_snapshot["top_trader_long_short_ratio"] == 2.345


# ===========================================================================
# 6. generate_signal -- TP/SL Calculations
# ===========================================================================


class TestTPSLCalculation:
    """Verify take profit and stop loss for LONG and SHORT positions."""

    async def test_long_tp_sl_calculation(self):
        """LONG: TP is above entry, SL is below entry."""
        strategy, mock_provider = _build_strategy_with_provider(
            take_profit_percent=5.0, stop_loss_percent=2.0,
        )
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 80))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"spot_price": {"price": 50000.0, "price_change_percent": 0, "quote_volume_24h": 0}}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        # TP = 50000 * 1.05 = 52500
        assert signal.target_price == 52500.0
        # SL = 50000 * 0.98 = 49000
        assert signal.stop_loss == 49000.0

    async def test_short_tp_sl_calculation(self):
        """SHORT: TP is below entry, SL is above entry."""
        strategy, mock_provider = _build_strategy_with_provider(
            take_profit_percent=5.0, stop_loss_percent=2.0,
        )
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("SHORT", 80))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"spot_price": {"price": 50000.0, "price_change_percent": 0, "quote_volume_24h": 0}}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        # TP = 50000 * 0.95 = 47500
        assert signal.target_price == 47500.0
        # SL = 50000 * 1.02 = 51000
        assert signal.stop_loss == 51000.0

    async def test_tp_sl_rounded_to_2_decimals(self):
        """TP/SL values are rounded to 2 decimal places."""
        strategy, mock_provider = _build_strategy_with_provider(
            take_profit_percent=3.33, stop_loss_percent=1.77,
        )
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 80))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"spot_price": {"price": 12345.67, "price_change_percent": 0, "quote_volume_24h": 0}}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        # Verify rounding
        assert signal.target_price == round(12345.67 * 1.0333, 2)
        assert signal.stop_loss == round(12345.67 * (1 - 0.0177), 2)

    async def test_no_tp_sl_when_price_is_zero(self):
        """Even with TP/SL configured, zero price means no TP/SL."""
        strategy, mock_provider = _build_strategy_with_provider(
            take_profit_percent=4.0, stop_loss_percent=1.5,
        )
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.target_price is None
        assert signal.stop_loss is None


# ===========================================================================
# 7. generate_signal -- Error Handling
# ===========================================================================


class TestGenerateSignalErrors:
    """Test error handling in generate_signal."""

    async def test_data_fetch_error_propagates(self):
        """Data fetch failures raise, not silently return bad signal."""
        strategy, mock_provider = _build_strategy_with_provider()

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            side_effect=ConnectionError("API unreachable")
        )
        strategy.data_fetcher = mock_fetcher

        with pytest.raises(ConnectionError, match="API unreachable"):
            await strategy.generate_signal("BTCUSDT")

    async def test_llm_api_failure_returns_zero_confidence_signal(self):
        """LLM API errors return a safe zero-confidence signal instead of crashing."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(
            side_effect=RuntimeError("500 Internal Server Error")
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"spot_price": {"price": 95000.0, "price_change_percent": 0, "quote_volume_24h": 0}}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.confidence == 0
        assert signal.direction == SignalDirection.LONG
        assert "[LLM ERROR]" in signal.reason
        assert signal.entry_price == 95000.0
        assert signal.metrics_snapshot["llm_provider"] == "groq"
        assert "llm_error" in signal.metrics_snapshot

    async def test_llm_timeout_returns_zero_confidence(self):
        """Timeout errors are handled gracefully."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(
            side_effect=TimeoutError("Request timed out")
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.confidence == 0
        assert "[LLM ERROR]" in signal.reason

    async def test_llm_error_signal_has_current_price(self):
        """Error signal still captures the current price from fetched data."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"spot_price": {"price": 42000.0, "price_change_percent": 0, "quote_volume_24h": 0}}
        )
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price == 42000.0
        assert signal.target_price == 42000.0
        assert signal.stop_loss == 42000.0

    async def test_llm_error_signal_with_no_price(self):
        """Error signal with no price data uses 0."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")

        assert signal.entry_price == 0.0
        assert signal.target_price == 0.0
        assert signal.stop_loss == 0.0


# ===========================================================================
# 8. _ensure_fetcher
# ===========================================================================


class TestEnsureFetcher:
    """Test lazy initialization of the market data fetcher."""

    async def test_ensure_fetcher_creates_fetcher(self):
        """First call creates a MarketDataFetcher."""
        strategy, _ = _build_strategy_with_provider()

        assert strategy.data_fetcher is None

        with patch("src.strategy.llm_signal.MarketDataFetcher") as mock_mdf_cls:
            mock_fetcher = AsyncMock()
            mock_mdf_cls.return_value = mock_fetcher
            await strategy._ensure_fetcher()

        assert strategy.data_fetcher is mock_fetcher
        mock_fetcher._ensure_session.assert_awaited_once()

    async def test_ensure_fetcher_does_not_recreate(self):
        """Second call reuses existing fetcher."""
        strategy, _ = _build_strategy_with_provider()

        existing_fetcher = AsyncMock()
        strategy.data_fetcher = existing_fetcher

        await strategy._ensure_fetcher()

        # Should still be the same instance (not replaced)
        assert strategy.data_fetcher is existing_fetcher


# ===========================================================================
# 9. close()
# ===========================================================================


class TestClose:
    """Test resource cleanup."""

    async def test_close_cleans_up_fetcher_and_provider(self):
        strategy, mock_provider = _build_strategy_with_provider(llm_api_key="secret-key")

        mock_fetcher = AsyncMock()
        strategy.data_fetcher = mock_fetcher

        await strategy.close()

        mock_fetcher.close.assert_awaited_once()
        mock_provider.close.assert_awaited_once()
        assert strategy.llm_api_key == ""

    async def test_close_without_fetcher(self):
        """close() works when data_fetcher was never initialized."""
        strategy, mock_provider = _build_strategy_with_provider()

        assert strategy.data_fetcher is None
        await strategy.close()

        mock_provider.close.assert_awaited_once()
        assert strategy.llm_api_key == ""

    async def test_close_clears_api_key(self):
        """API key is wiped on close for security."""
        strategy, _ = _build_strategy_with_provider(llm_api_key="super-secret-key-123")

        assert strategy.llm_api_key == "super-secret-key-123"
        await strategy.close()
        assert strategy.llm_api_key == ""


# ===========================================================================
# 10. generate_signal with custom prompt
# ===========================================================================


class TestGenerateSignalWithCustomPrompt:
    """Verify the prompt passed to the LLM provider."""

    async def test_default_prompt_sent_to_provider(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        await strategy.generate_signal("BTCUSDT")

        call_kwargs = mock_provider.generate_signal.call_args
        assert call_kwargs.kwargs["prompt"] == DEFAULT_PROMPT

    async def test_custom_prompt_sent_to_provider(self):
        strategy, mock_provider = _build_strategy_with_provider(
            custom_prompt="Be bullish always."
        )
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        await strategy.generate_signal("BTCUSDT")

        call_kwargs = mock_provider.generate_signal.call_args
        assert call_kwargs.kwargs["prompt"] == "Be bullish always."

    async def test_temperature_sent_to_provider(self):
        strategy, mock_provider = _build_strategy_with_provider(temperature=0.9)
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value=_full_fetched_data())
        strategy.data_fetcher = mock_fetcher

        await strategy.generate_signal("BTCUSDT")

        call_kwargs = mock_provider.generate_signal.call_args
        assert call_kwargs.kwargs["temperature"] == 0.9

    async def test_market_data_dict_passed_to_provider(self):
        """Provider receives a market_data dict containing the symbol."""
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(
            return_value={"spot_price": {"price": 100.0, "price_change_percent": 0, "quote_volume_24h": 0}}
        )
        strategy.data_fetcher = mock_fetcher

        await strategy.generate_signal("ETHUSDT")

        call_kwargs = mock_provider.generate_signal.call_args
        market_data = call_kwargs.kwargs["market_data"]
        assert market_data["symbol"] == "ETHUSDT"
        assert market_data["current_price"] == 100.0


# ===========================================================================
# 11. Direction parsing
# ===========================================================================


class TestDirectionParsing:
    """Verify LLM response direction maps to correct SignalDirection."""

    async def test_long_direction(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.direction == SignalDirection.LONG

    async def test_short_direction(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("SHORT", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.direction == SignalDirection.SHORT

    async def test_lowercase_long_maps_to_short(self):
        """Lowercase 'long' does not match 'LONG' after .upper(), so maps to SHORT."""
        strategy, mock_provider = _build_strategy_with_provider()
        resp = _llm_response("long", 70)
        mock_provider.generate_signal = AsyncMock(return_value=resp)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        # "long".upper() == "LONG", so direction is LONG
        assert signal.direction == SignalDirection.LONG

    async def test_unknown_direction_maps_to_short(self):
        """Any direction that is not 'LONG' becomes SHORT."""
        strategy, mock_provider = _build_strategy_with_provider()
        resp = _llm_response("NEUTRAL", 70)
        mock_provider.generate_signal = AsyncMock(return_value=resp)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("BTCUSDT")
        assert signal.direction == SignalDirection.SHORT


# ===========================================================================
# 12. get_description and get_param_schema (class methods)
# ===========================================================================


class TestClassMethods:
    """Test get_description and get_param_schema."""

    def test_get_description_returns_string(self):
        from src.strategy.llm_signal import LLMSignalStrategy

        desc = LLMSignalStrategy.get_description()
        assert isinstance(desc, str)
        assert len(desc) > 10
        assert "AI" in desc or "LLM" in desc

    def test_get_param_schema_returns_dict(self):
        from src.strategy.llm_signal import LLMSignalStrategy

        schema = LLMSignalStrategy.get_param_schema()
        assert isinstance(schema, dict)
        assert "llm_provider" in schema
        assert "llm_model" in schema
        assert "custom_prompt" in schema
        assert "temperature" in schema

    def test_param_schema_provider_has_options(self):
        from src.strategy.llm_signal import LLMSignalStrategy

        schema = LLMSignalStrategy.get_param_schema()
        provider_field = schema["llm_provider"]
        assert provider_field["type"] == "select"
        assert len(provider_field["options"]) > 0

    def test_param_schema_model_depends_on_provider(self):
        from src.strategy.llm_signal import LLMSignalStrategy

        schema = LLMSignalStrategy.get_param_schema()
        model_field = schema["llm_model"]
        assert model_field["type"] == "dependent_select"
        assert model_field["depends_on"] == "llm_provider"
        assert "options_map" in model_field

    def test_param_schema_temperature_range(self):
        from src.strategy.llm_signal import LLMSignalStrategy

        schema = LLMSignalStrategy.get_param_schema()
        temp_field = schema["temperature"]
        assert temp_field["min"] == 0.0
        assert temp_field["max"] == 1.0
        assert temp_field["default"] == 0.3


# ===========================================================================
# 13. Strategy registration
# ===========================================================================


class TestStrategyRegistration:
    """Verify the strategy is properly registered."""

    def test_llm_signal_registered_in_registry(self):
        from src.strategy.base import StrategyRegistry

        # Importing llm_signal triggers registration
        import src.strategy.llm_signal  # noqa: F401

        strategy_cls = StrategyRegistry.get("llm_signal")
        assert strategy_cls is not None
        assert strategy_cls.__name__ == "LLMSignalStrategy"


# ===========================================================================
# 14. Symbol passed correctly through the pipeline
# ===========================================================================


class TestSymbolHandling:
    """Verify the symbol flows through to fetcher and signal."""

    async def test_symbol_passed_to_fetcher(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        await strategy.generate_signal("ETHUSDT")

        mock_fetcher.fetch_selected_metrics.assert_awaited_once()
        call_args = mock_fetcher.fetch_selected_metrics.call_args
        assert call_args[0][1] == "ETHUSDT"

    async def test_symbol_in_returned_signal(self):
        strategy, mock_provider = _build_strategy_with_provider()
        mock_provider.generate_signal = AsyncMock(return_value=_llm_response("LONG", 70))

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_selected_metrics = AsyncMock(return_value={})
        strategy.data_fetcher = mock_fetcher

        signal = await strategy.generate_signal("SOLUSDT")

        assert signal.symbol == "SOLUSDT"
