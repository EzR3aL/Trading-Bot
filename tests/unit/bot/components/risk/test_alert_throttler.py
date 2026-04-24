"""Unit tests for ``AlertThrottler`` (ARCH-H2 Phase 1 PR-4, issue #326).

Focused tests on the component in isolation. The BotWorker-level
integration contracts (dedupe across the emission branches, midnight
reset, daily-summary reset) are locked by the Phase 0 characterization
suite in ``tests/unit/bot/test_risk_state_manager_characterization.py``
and re-verified there against the extracted component.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.bot.components.risk import AlertThrottler, AlertThrottlerProtocol


# ── Helpers ─────────────────────────────────────────────────────────


def _make_throttler(*, notifier: AsyncMock | None = None) -> AlertThrottler:
    """Build a throttler with a stubbed notifier callable."""
    sender = notifier or AsyncMock()
    return AlertThrottler(bot_config_id=1, notification_sender=sender)


# ── Protocol conformance ────────────────────────────────────────────


class TestProtocolConformance:
    """The component must satisfy ``AlertThrottlerProtocol`` structurally."""

    def test_is_alert_throttler_protocol(self):
        assert isinstance(_make_throttler(), AlertThrottlerProtocol)


# ── should_emit + dedupe ────────────────────────────────────────────


class TestShouldEmitDedupe:
    def test_first_call_returns_true_and_records_key(self):
        t = _make_throttler()
        assert t.should_emit("global_foo") is True
        assert "global_foo" in t.sent

    def test_second_call_same_key_returns_false(self):
        t = _make_throttler()
        assert t.should_emit("global_foo") is True
        assert t.should_emit("global_foo") is False

    def test_different_keys_do_not_dedupe_each_other(self):
        t = _make_throttler()
        assert t.should_emit("global_a") is True
        assert t.should_emit("global_b") is True


# ── maybe_reset + reset ─────────────────────────────────────────────


class TestResetBehaviour:
    def test_maybe_reset_no_op_inside_window(self):
        t = _make_throttler()
        t.sent.add("stale")
        t.maybe_reset()
        assert "stale" in t.sent

    def test_maybe_reset_clears_after_24h_and_bumps_timestamp(self):
        t = _make_throttler()
        t.sent.add("stale")
        old = datetime.now(timezone.utc) - timedelta(hours=25)
        t.last_reset = old

        t.maybe_reset()

        assert "stale" not in t.sent
        assert t.last_reset > old

    def test_reset_unconditional_clears_set(self):
        t = _make_throttler()
        t.sent.update({"a", "b", "c"})
        t.reset()
        assert t.sent == set()

    def test_reset_preserves_last_reset_timestamp(self):
        """Unconditional ``reset()`` only clears the set — it does NOT
        bump the timestamp. Midnight reset cadence is driven by
        ``maybe_reset``; ``reset()`` is for the daily-summary path."""
        t = _make_throttler()
        original = t.last_reset
        t.reset()
        assert t.last_reset == original


# ── emit_global_if_needed ───────────────────────────────────────────


@pytest.mark.asyncio
class TestEmitGlobalIfNeeded:
    async def test_emits_for_halted_reason(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)
        result = await t.emit_global_if_needed("Trading halted due to loss limit")
        assert result is True
        send.assert_awaited_once()

    async def test_emits_for_trade_limit_as_trade_limit_type(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)

        await t.emit_global_if_needed("Global trade limit reached (3/3)")

        send.assert_awaited_once()
        _, kwargs = send.call_args
        assert kwargs["event_type"] == "risk_alert"
        assert "TRADE_LIMIT" in kwargs["summary"]

    async def test_emits_for_daily_loss_limit_as_daily_loss_type(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)

        await t.emit_global_if_needed("Daily loss limit exceeded (5% >= 5%)")

        send.assert_awaited_once()
        _, kwargs = send.call_args
        assert "DAILY_LOSS_LIMIT" in kwargs["summary"]

    async def test_skips_non_matching_reason(self):
        """Reasons without 'halted' or 'limit' are NEVER queued."""
        send = AsyncMock()
        t = _make_throttler(notifier=send)
        result = await t.emit_global_if_needed("not initialized yet")
        assert result is False
        send.assert_not_awaited()
        assert not any("not initialized" in k for k in t.sent)

    async def test_dedupes_second_call_same_reason(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)

        first = await t.emit_global_if_needed("Global trade limit reached (3/3)")
        second = await t.emit_global_if_needed("Global trade limit reached (3/3)")

        assert first is True
        assert second is False
        send.assert_awaited_once()

    async def test_different_reason_emits_independently(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)
        await t.emit_global_if_needed("Global trade limit reached (3/3)")
        await t.emit_global_if_needed("Daily loss limit exceeded (5% >= 5%)")
        assert send.await_count == 2

    async def test_key_format_is_global_prefix(self):
        t = _make_throttler()
        await t.emit_global_if_needed("Global trade limit reached (3/3)")
        assert any(k.startswith("global_") for k in t.sent)


# ── emit_per_symbol_if_needed ───────────────────────────────────────


@pytest.mark.asyncio
class TestEmitPerSymbolIfNeeded:
    async def test_emits_for_halted_symbol(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)
        result = await t.emit_per_symbol_if_needed(
            "BTCUSDT", "BTCUSDT: trade limit reached (3/3)"
        )
        assert result is True
        send.assert_awaited_once()

    async def test_key_prefixed_by_symbol(self):
        t = _make_throttler()
        await t.emit_per_symbol_if_needed(
            "BTCUSDT", "BTCUSDT: trade limit reached (3/3)"
        )
        assert any(k.startswith("BTCUSDT_") for k in t.sent)

    async def test_different_symbols_emit_independently(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)
        await t.emit_per_symbol_if_needed("BTCUSDT", "trade limit reached")
        await t.emit_per_symbol_if_needed("ETHUSDT", "trade limit reached")
        assert send.await_count == 2

    async def test_same_symbol_same_reason_is_deduped(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)
        await t.emit_per_symbol_if_needed("BTCUSDT", "trade limit reached")
        await t.emit_per_symbol_if_needed("BTCUSDT", "trade limit reached")
        assert send.await_count == 1

    async def test_skips_non_matching_reason(self):
        send = AsyncMock()
        t = _make_throttler(notifier=send)
        result = await t.emit_per_symbol_if_needed("BTCUSDT", "no signal today")
        assert result is False
        send.assert_not_awaited()


# ── Notifier exception swallow ──────────────────────────────────────


@pytest.mark.asyncio
class TestNotifierSwallow:
    """PR-4 contract change: notifier exceptions NEVER propagate out of
    the throttler. Previously the inlined call in BotWorker let them
    bubble into ``_analyze_and_trade`` and kill the per-symbol loop."""

    async def test_global_notifier_exception_is_swallowed(self):
        send = AsyncMock(side_effect=RuntimeError("discord 500"))
        t = _make_throttler(notifier=send)

        # Must not raise
        await t.emit_global_if_needed("Global trade limit reached (3/3)")

        send.assert_awaited_once()

    async def test_per_symbol_notifier_exception_is_swallowed(self):
        send = AsyncMock(side_effect=RuntimeError("telegram 500"))
        t = _make_throttler(notifier=send)

        await t.emit_per_symbol_if_needed(
            "BTCUSDT", "BTCUSDT: trade limit reached"
        )

        send.assert_awaited_once()

    async def test_swallowed_exception_still_records_key(self):
        """The alert_key is recorded in ``sent`` even though the notifier
        raised. Rationale: if delivery is broken, we still don't want to
        spam the notifier with duplicate dispatches on every tick."""
        send = AsyncMock(side_effect=RuntimeError("discord 500"))
        t = _make_throttler(notifier=send)
        await t.emit_global_if_needed("Global trade limit reached (3/3)")
        assert any(k.startswith("global_") for k in t.sent)


# ── Sent + last_reset backward-compat accessors ─────────────────────


class TestSentAndLastResetAccessors:
    """The BotWorker-level ``_risk_alerts_sent`` / ``_risk_alerts_last_reset``
    attrs delegate to ``AlertThrottler.sent`` / ``.last_reset``. The
    accessors must therefore support mutation + replacement."""

    def test_sent_exposes_live_set(self):
        t = _make_throttler()
        t.sent.add("direct")
        assert "direct" in t.sent

    def test_sent_setter_replaces_set(self):
        t = _make_throttler()
        t.sent = {"a", "b"}
        assert t.sent == {"a", "b"}

    def test_last_reset_getter_and_setter(self):
        t = _make_throttler()
        now = datetime.now(timezone.utc)
        t.last_reset = now
        assert t.last_reset == now
