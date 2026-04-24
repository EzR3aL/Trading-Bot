"""Tests for resolve_strategy_params and dashboard/strategy parity.

These tests guard against the bug described in #133: the dashboard API used
its own merge logic that ignored RISK_PROFILES, causing the dashboard to
display trailing stop state based on different parameters than the live
strategy actually used.

The parity tests instantiate the real strategy classes and compare their
effective ``_p`` dict against ``resolve_strategy_params``. If they diverge,
these tests fail loudly.
"""

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.strategy.base import resolve_strategy_params
from src.strategy.edge_indicator import (
    DEFAULTS as EDGE_DEFAULTS,
    EdgeIndicatorStrategy,
)
from src.strategy.liquidation_hunter import (
    LiquidationHunterStrategy,
)


# ═══════════════════════════════════════════════════════════════════════════
# Basic helper behavior
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveStrategyParams:
    """Unit tests for resolve_strategy_params."""

    def test_unknown_strategy_returns_user_params(self):
        """Unknown strategy_type passes user params through unchanged."""
        result = resolve_strategy_params("nonexistent", '{"foo": "bar"}')
        assert result == {"foo": "bar"}

    def test_none_strategy_returns_user_params(self):
        """None strategy_type returns parsed user params."""
        result = resolve_strategy_params(None, '{"x": 1}')
        assert result == {"x": 1}

    def test_invalid_json_returns_empty(self):
        """Malformed JSON yields an empty dict, never raises."""
        result = resolve_strategy_params("edge_indicator", "{not valid json")
        # For a known strategy, invalid user JSON falls back to DEFAULTS + profile
        assert result["kline_interval"] == EDGE_DEFAULTS["kline_interval"]
        assert result["trailing_breakeven_atr"] == EDGE_DEFAULTS["trailing_breakeven_atr"]

    def test_none_json_returns_defaults_with_profile(self):
        """Empty/None params_json still applies the standard profile."""
        result = resolve_strategy_params("edge_indicator", None)
        # Standard profile has no overrides, so result matches DEFAULTS
        assert result["trailing_breakeven_atr"] == EDGE_DEFAULTS["trailing_breakeven_atr"]
        assert result["trailing_trail_atr"] == EDGE_DEFAULTS["trailing_trail_atr"]
        assert result["kline_interval"] == EDGE_DEFAULTS["kline_interval"]

    def test_edge_indicator_conservative_profile(self):
        """Conservative profile overrides trailing and kline_interval."""
        result = resolve_strategy_params(
            "edge_indicator",
            '{"risk_profile": "conservative"}',
        )
        # These come from the conservative profile, NOT DEFAULTS
        assert result["trailing_breakeven_atr"] == 2.0
        assert result["trailing_trail_atr"] == 3.0
        assert result["kline_interval"] == "4h"
        assert result["adx_chop_threshold"] == 22.0

    def test_user_params_override_profile(self):
        """Explicit user params beat profile overrides."""
        result = resolve_strategy_params(
            "edge_indicator",
            '{"risk_profile": "conservative", "kline_interval": "1h", "trailing_trail_atr": 4.0}',
        )
        # User explicitly overrode these — profile values should lose
        assert result["kline_interval"] == "1h"
        assert result["trailing_trail_atr"] == 4.0
        # But profile still sets the ones the user didn't touch
        assert result["trailing_breakeven_atr"] == 2.0
        assert result["adx_chop_threshold"] == 22.0

    def test_liquidation_hunter_aggressive_profile(self):
        """LiquidationHunter also has profiles — confirm aggressive applies."""
        result = resolve_strategy_params(
            "liquidation_hunter",
            '{"risk_profile": "aggressive"}',
        )
        assert result["trailing_breakeven_atr"] == 0.5
        assert result["trailing_trail_atr"] == 1.0
        assert result["max_hold_hours"] == 12

    def test_non_dict_user_json_falls_back(self):
        """JSON that parses to a non-dict (e.g. a list) is ignored safely."""
        result = resolve_strategy_params("edge_indicator", "[1, 2, 3]")
        # Should still produce a valid merged dict
        assert result["kline_interval"] == EDGE_DEFAULTS["kline_interval"]


# ═══════════════════════════════════════════════════════════════════════════
# Parity: dashboard resolve === live strategy._p
# ═══════════════════════════════════════════════════════════════════════════


class TestParityWithLiveStrategy:
    """Regression tests for #133: dashboard and strategy must agree on params.

    The bug was that ``_compute_trailing_stop`` merged only DEFAULTS + user
    params, ignoring the RISK_PROFILE. The strategy instance applied the
    profile correctly in ``__init__``. These tests instantiate the real
    strategy and compare every key that affects the trailing stop calculation.
    """

    TRAILING_KEYS = (
        "trailing_stop_enabled",
        "trailing_breakeven_atr",
        "trailing_trail_atr",
        "kline_interval",
        "atr_period",
    )

    @pytest.mark.parametrize(
        "user_params",
        [
            {},
            {"risk_profile": "standard"},
            {"risk_profile": "conservative"},
            {"risk_profile": "conservative", "kline_interval": "1h"},
            {"risk_profile": "conservative", "trailing_trail_atr": 5.0},
            {"kline_interval": "15m", "trailing_breakeven_atr": 0.8},
        ],
    )
    def test_edge_indicator_parity(self, user_params):
        """resolve_strategy_params matches EdgeIndicatorStrategy._p for edge cases."""
        strategy = EdgeIndicatorStrategy(params=user_params)
        resolved = resolve_strategy_params("edge_indicator", json.dumps(user_params))
        for key in self.TRAILING_KEYS:
            assert resolved[key] == strategy._p[key], (
                f"Parameter '{key}' mismatch for user_params={user_params}: "
                f"resolved={resolved[key]!r} vs strategy._p={strategy._p[key]!r}"
            )

    @pytest.mark.parametrize(
        "user_params",
        [
            {},
            {"risk_profile": "standard"},
            {"risk_profile": "conservative"},
            {"risk_profile": "aggressive"},
            {"risk_profile": "aggressive", "max_hold_hours": 6},
        ],
    )
    def test_liquidation_hunter_parity(self, user_params):
        """resolve_strategy_params matches LiquidationHunterStrategy._p."""
        strategy = LiquidationHunterStrategy(params=user_params)
        resolved = resolve_strategy_params("liquidation_hunter", json.dumps(user_params))
        for key in self.TRAILING_KEYS:
            assert resolved[key] == strategy._p[key], (
                f"Parameter '{key}' mismatch for user_params={user_params}: "
                f"resolved={resolved[key]!r} vs strategy._p={strategy._p[key]!r}"
            )

    def test_edge_conservative_not_using_defaults(self):
        """Regression: conservative profile must NOT inherit 1.5/2.5 from DEFAULTS.

        Before #133, the dashboard used DEFAULTS verbatim. For a conservative
        bot this caused the displayed trailing stop to activate at ~1.5× ATR
        while the live strategy required ~2.0× ATR — a 33% discrepancy that
        showed "trailing protecting" when the strategy had not armed it.
        """
        resolved = resolve_strategy_params("edge_indicator", '{"risk_profile": "conservative"}')
        assert resolved["trailing_breakeven_atr"] == 2.0, (
            "Conservative profile must set breakeven_atr=2.0, not the default 1.5"
        )
        assert resolved["trailing_trail_atr"] == 3.0, (
            "Conservative profile must set trail_atr=3.0, not the default 2.5"
        )
        assert resolved["kline_interval"] == "4h", (
            "Conservative profile must set kline_interval=4h, not the default 1h"
        )


# ═══════════════════════════════════════════════════════════════════════════
# End-to-end: _compute_trailing_stop respects profile + interval
# ═══════════════════════════════════════════════════════════════════════════


class _FakeTrade:
    """Minimal stand-in for TradeRecord — only the fields _compute_trailing_stop reads."""

    def __init__(
        self,
        side="long",
        entry_price=69097.2,
        highest_price=70179.3,
        symbol="BTCUSDT",
        trailing_atr_override=None,
        status="open",
    ):
        self.side = side
        self.entry_price = entry_price
        self.highest_price = highest_price
        self.symbol = symbol
        self.trailing_atr_override = trailing_atr_override
        self.status = status


def _kline(close, high, low):
    """Build a minimal kline row [open_time, o, h, l, c, ...]."""
    return [0, close, high, low, close, 0, 0, 0, 0, 0, 0, 0]


@pytest.mark.asyncio
class TestComputeTrailingStopParity:
    """Verify _compute_trailing_stop honors the resolved strategy params."""

    async def test_conservative_edge_dormant_when_gain_below_threshold(self):
        """For a conservative edge_indicator trade with the live-Bitget numbers,
        the dashboard trailing must remain dormant — matching the strategy.

        Trade 71 on 2026-04-07: entry 69097.2, highest 70179.3 (+1082),
        4h ATR ≈ 905. Conservative breakeven_atr=2.0 → threshold 1810 > 1082,
        so trailing must NOT activate. The pre-fix dashboard calc (1h ATR ≈
        406, DEFAULTS 1.5) produced threshold 609 < 1082 → falsely active.
        """
        from src.services.trades_service import _compute_trailing_stop

        trade = _FakeTrade()
        # 4h klines with ATR ≈ 905 (simplified constant range)
        atr_target = 905
        klines = [
            _kline(close=69000 + i * 10, high=69000 + i * 10 + atr_target, low=69000 + i * 10)
            for i in range(29)
        ]
        klines_cache = {("BTCUSDT", "4h"): klines}

        result = await _compute_trailing_stop(
            trade,
            strategy_type="edge_indicator",
            strategy_params_json='{"risk_profile": "conservative", "kline_interval": "4h"}',
            klines_cache=klines_cache,
        )

        assert result.get("trailing_stop_active") is False, (
            f"Conservative trailing must be dormant when gain < 2×ATR; got {result}"
        )
        assert result.get("can_close_at_loss") is True

    async def test_conservative_edge_uses_4h_cache_not_1h(self):
        """A conservative bot must read the 4h cache entry, not a 1h entry.

        Guards against regression where portfolio.py / trades.py would
        prefetch with "1h" hardcoded and _compute_trailing_stop would miss
        the cache, falling back to a live fetch with the wrong interval.
        """
        from src.services.trades_service import _compute_trailing_stop

        trade = _FakeTrade(highest_price=75000)  # clearly profitable at any ATR
        # Same fake data for both cache keys, but only 4h should be read
        atr_target = 500
        klines = [
            _kline(close=69000 + i * 10, high=69000 + i * 10 + atr_target, low=69000 + i * 10)
            for i in range(29)
        ]
        # Only 4h populated — if code mistakenly looks up 1h, cache miss → fetch
        klines_cache = {("BTCUSDT", "4h"): klines}

        result = await _compute_trailing_stop(
            trade,
            strategy_type="edge_indicator",
            strategy_params_json='{"risk_profile": "conservative"}',
            klines_cache=klines_cache,
        )
        # With a 75000 highest and ATR 500, gain 5903 >> 1000 (2.0 × 500)
        assert result.get("trailing_stop_active") is True

    async def test_liquidation_hunter_supported(self):
        """Regression: liquidation_hunter trades now get trailing info too."""
        from src.services.trades_service import _compute_trailing_stop

        trade = _FakeTrade(highest_price=70500)
        klines = [
            _kline(close=69000 + i * 10, high=69000 + i * 10 + 400, low=69000 + i * 10)
            for i in range(29)
        ]
        klines_cache = {("BTCUSDT", "1h"): klines}

        result = await _compute_trailing_stop(
            trade,
            strategy_type="liquidation_hunter",
            strategy_params_json='{"risk_profile": "standard"}',
            klines_cache=klines_cache,
        )
        # LiquidationHunter standard: breakeven_atr=1.0, trail_atr=1.5
        # ATR≈400, threshold=400, gain=1403 >> threshold → active
        assert result.get("trailing_stop_active") is True
        assert result.get("trailing_stop_price") is not None


# ═══════════════════════════════════════════════════════════════════════════
# Exchange-agnostic dashboard rendering (#133 follow-up)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestDashboardExchangeAgnostic:
    """The dashboard _compute_trailing_stop must produce identical output for
    the same trade data regardless of which exchange the trade lives on.

    For Bitget/BingX bots, the computed trailing represents where the NATIVE
    trailing on the exchange will fire. For Weex/Bitunix/Hyperliquid bots,
    it represents where the SOFTWARE trailing in strategy.should_exit will
    fire. In both cases the underlying calculation is identical (same ATR,
    same profile multipliers, same highest_price) — the dashboard should
    show matching numbers so users see consistent behavior regardless of
    which exchange they picked.
    """

    async def test_trailing_computation_independent_of_exchange(self):
        """The trailing stop calculation must NOT depend on exchange field.

        _compute_trailing_stop does not receive the exchange — it only uses
        strategy_type + strategy_params + trade. This test asserts that
        contract by calling the function many times with different symbols
        (one per exchange convention) but identical strategy settings, and
        verifying the output shape is the same.
        """
        from src.services.trades_service import _compute_trailing_stop

        # Each exchange uses a slightly different symbol format, but the
        # dashboard computation only cares about the strategy + highest_price.
        symbols_per_exchange = {
            "bitget": "ETHUSDT",
            "bingx": "ETH-USDT",
            "weex": "ETH/USDT:USDT",
            "bitunix": "ETHUSDT",
            "hyperliquid": "ETH",
        }
        # Shared klines with ATR large enough to activate conservative threshold
        klines = [
            _kline(close=2100 + i * 2, high=2100 + i * 2 + 30, low=2100 + i * 2)
            for i in range(29)
        ]

        results = {}
        for exchange, symbol in symbols_per_exchange.items():
            trade = _FakeTrade(
                side="long",
                entry_price=2100.0,
                highest_price=2200.0,
                symbol=symbol,
            )
            klines_cache = {(symbol, "4h"): klines}
            result = await _compute_trailing_stop(
                trade,
                strategy_type="edge_indicator",
                strategy_params_json='{"risk_profile": "conservative"}',
                klines_cache=klines_cache,
            )
            results[exchange] = result

        # All exchanges must yield a fully populated, active trailing
        for exchange, result in results.items():
            assert result.get("trailing_stop_active") is True, (
                f"{exchange}: trailing must be active for +100/2100 gain; got {result}"
            )
            assert result.get("can_close_at_loss") is False
            assert result.get("trailing_stop_price") is not None
            assert result.get("trailing_stop_distance_pct") is not None

        # And the trailing_stop_price must be IDENTICAL across all five —
        # the calculation only depends on highest_price + ATR + profile.
        stop_prices = {ex: r["trailing_stop_price"] for ex, r in results.items()}
        unique_stops = set(stop_prices.values())
        assert len(unique_stops) == 1, (
            f"Dashboard trailing stop diverges between exchanges: {stop_prices}. "
            "The calculation must be exchange-agnostic."
        )

    async def test_software_trailing_calc_matches_check_atr_trailing_stop(self):
        """The dashboard's _compute_trailing_stop must return the same stop
        price that check_atr_trailing_stop (used by strategy.should_exit for
        software trailing on all exchanges) would trigger on.

        This is the critical invariant that protects Weex/Bitunix/Hyperliquid
        users: they rely exclusively on software trailing, and the dashboard
        is the only place they see the stop level. If the two calculations
        diverge, the displayed stop is misleading.
        """
        from src.services.trades_service import _compute_trailing_stop
        from src.strategy.base import check_atr_trailing_stop

        # Shared inputs
        entry = 2100.0
        highest = 2200.0
        current_at_stop = 2109.99  # just below the trailing stop
        atr_target = 30
        klines = [
            _kline(close=2100 + i * 2, high=2100 + i * 2 + atr_target, low=2100 + i * 2)
            for i in range(29)
        ]

        # Dashboard side: compute displayed trailing stop
        trade = _FakeTrade(side="long", entry_price=entry, highest_price=highest, symbol="ETHUSDT")
        klines_cache = {("ETHUSDT", "4h"): klines}
        dash_result = await _compute_trailing_stop(
            trade,
            strategy_type="edge_indicator",
            strategy_params_json='{"risk_profile": "conservative"}',
            klines_cache=klines_cache,
        )

        # Software trailing side: what check_atr_trailing_stop returns at the
        # same current price — with the same conservative profile multipliers
        should_exit, reason = check_atr_trailing_stop(
            side="long",
            entry_price=entry,
            current_price=current_at_stop,
            highest_price=highest,
            klines=klines,
            atr_period=14,
            breakeven_atr=2.0,  # conservative
            trail_atr=3.0,      # conservative
        )

        # Both must see the trailing as active/protecting the same zone.
        assert dash_result.get("trailing_stop_active") is True
        displayed_stop = dash_result["trailing_stop_price"]

        # If current drops below displayed_stop, software trailing MUST fire.
        # Test at exactly the displayed stop price to ensure they agree.
        should_exit_at_stop, _ = check_atr_trailing_stop(
            side="long",
            entry_price=entry,
            current_price=displayed_stop - 0.01,  # 1 cent below
            highest_price=highest,
            klines=klines,
            atr_period=14,
            breakeven_atr=2.0,
            trail_atr=3.0,
        )
        assert should_exit_at_stop is True, (
            f"Dashboard says stop at {displayed_stop}, but software trailing "
            f"did not fire at {displayed_stop - 0.01}. The two calculations "
            f"diverge — the dashboard display is misleading."
        )

        # And ABOVE the displayed stop, software trailing must NOT fire
        should_exit_above, _ = check_atr_trailing_stop(
            side="long",
            entry_price=entry,
            current_price=displayed_stop + 1.0,
            highest_price=highest,
            klines=klines,
            atr_period=14,
            breakeven_atr=2.0,
            trail_atr=3.0,
        )
        assert should_exit_above is False, (
            f"Software trailing fired ABOVE the displayed stop {displayed_stop}. "
            f"The dashboard would show the position as safe while it is not."
        )

    async def test_short_trailing_exchange_agnostic(self):
        """Same parity check for SHORT positions.

        highest_price for shorts actually tracks the LOWEST price since entry
        (see position_monitor.py:108 and check_atr_trailing_stop).
        """
        from src.services.trades_service import _compute_trailing_stop

        trade = _FakeTrade(
            side="short",
            entry_price=2100.0,
            highest_price=2000.0,  # "highest" = lowest for shorts, +100 gain
            symbol="ETHUSDT",
        )
        klines = [
            _kline(close=2100 + i * 2, high=2100 + i * 2 + 30, low=2100 + i * 2)
            for i in range(29)
        ]
        klines_cache = {("ETHUSDT", "4h"): klines}

        result = await _compute_trailing_stop(
            trade,
            strategy_type="edge_indicator",
            strategy_params_json='{"risk_profile": "conservative"}',
            klines_cache=klines_cache,
        )

        # Conservative: breakeven_atr=2.0, trail_atr=3.0, ATR≈32 from the
        # synthetic klines (True Range includes close-to-close gaps).
        # entry - highest_price (lowest) = 100 > 2×32 → active.
        assert result.get("trailing_stop_active") is True
        # For short: trailing_stop = min(highest_price + trail_distance, entry)
        # Must be strictly above the current "lowest price" (2000) so it can
        # act as a ceiling, and strictly below/equal to entry (2100) to
        # represent a protective breakeven floor.
        stop = result["trailing_stop_price"]
        assert 2000.0 < stop <= 2100.0, (
            f"Short trailing stop must sit between lowest ({2000.0}) and "
            f"entry ({2100.0}); got {stop}"
        )
