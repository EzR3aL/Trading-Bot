"""Characterization tests for the risk-state surface (ARCH-H2, issue #326).

These tests freeze the *observable* behaviour of the four risk-state
responsibilities that Phase 1 (PR-4..PR-7) will extract into separate
components under ``src/bot/components/risk/``:

1. **DailyStatsAggregator** — PnL/trade-count aggregation exposed via
   ``RiskManager.get_daily_stats()``.
2. **TradeGate** — global + per-symbol branches in
   ``RiskManager.can_trade(symbol=None)``.
3. **AlertThrottler** — ``BotWorker._risk_alerts_sent`` dedupe +
   midnight reset (inlined in ``_analyze_and_trade``).
4. **RiskStatePersistence** — ``load_stats_from_db`` /
   ``_save_stats_to_db`` (#188 truth-source) and their swallow-on-error
   contract.

Covered in Part A (sub-PR-2): 1, 2, 3.
Covered in Part B (sub-PR-3): midnight reset for 3, and all of 4 +
exception-swallow behaviour.

Why it matters
--------------
The Phase 1 PRs extract each component while keeping the RiskManager
façade unchanged. These tests are the safety net: any refactor that
moves logic between components MUST leave the public observables
frozen here untouched. If a test changes, it's either a bug in the
refactor or an intentional change that needs issue-level sign-off.

See ``Anleitungen/refactor_plan_bot_worker_composition.md`` (Phase 0
characterization pattern, inherited here for ARCH-H2).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.bot_worker import BotWorker
from src.risk.risk_manager import DailyStats, RiskManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rm(
    *,
    max_trades_per_day: int | None = None,
    daily_loss_limit_percent: float | None = None,
    position_size_percent: float | None = None,
    per_symbol_limits: dict | None = None,
    enable_profit_lock: bool = False,
) -> RiskManager:
    """Build an in-memory RiskManager (no DB, no bot_config_id)."""
    return RiskManager(
        max_trades_per_day=max_trades_per_day,
        daily_loss_limit_percent=daily_loss_limit_percent,
        position_size_percent=position_size_percent,
        per_symbol_limits=per_symbol_limits,
        enable_profit_lock=enable_profit_lock,
        bot_config_id=None,
    )


# ---------------------------------------------------------------------------
# PART A.1 — DailyStatsAggregator: get_daily_stats + record_trade_*
# ---------------------------------------------------------------------------


class TestGetDailyStats:
    """Freezes the observable shape of ``get_daily_stats()``.

    Contract (Phase 1 must preserve):
    * Returns ``None`` before ``initialize_day``.
    * Returns the in-memory ``DailyStats`` dataclass afterwards.
    * All 17 dataclass fields remain accessible (``to_dict`` keys).
    * Derived properties (``net_pnl``, ``return_percent``, ``win_rate``)
      stay consistent with the raw counters.
    """

    def test_returns_none_before_initialize(self):
        rm = _make_rm()
        assert rm.get_daily_stats() is None

    def test_returns_empty_dailystats_shape_after_init(self):
        """Fresh bot after initialize_day → 17-field DailyStats with zero counters."""
        rm = _make_rm()
        rm.initialize_day(starting_balance=10_000.0)

        stats = rm.get_daily_stats()
        assert stats is not None
        assert isinstance(stats, DailyStats)

        # Exactly the 17 fields the to_dict contract guarantees.
        assert stats.date == datetime.now().strftime("%Y-%m-%d")
        assert stats.starting_balance == 10_000.0
        assert stats.current_balance == 10_000.0
        assert stats.trades_executed == 0
        assert stats.winning_trades == 0
        assert stats.losing_trades == 0
        assert stats.total_pnl == 0.0
        assert stats.total_fees == 0.0
        assert stats.total_funding == 0.0
        assert stats.max_drawdown == 0.0
        assert stats.is_trading_halted is False
        assert stats.halt_reason == ""
        assert stats.symbol_trades == {}
        assert stats.symbol_pnl == {}
        assert stats.halted_symbols == {}
        # Derived
        assert stats.net_pnl == 0.0
        assert stats.return_percent == 0.0
        assert stats.win_rate == 0.0

    def test_aggregates_mixed_win_loss_trades(self):
        """record_trade_entry + record_trade_exit with mixed outcomes →
        counters aggregate correctly, per-symbol PnL tracked, win_rate +
        net_pnl reflect the series."""
        rm = _make_rm()
        rm.initialize_day(starting_balance=10_000.0)

        # Two entries
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, leverage=1, confidence=70,
            reason="signal", order_id="e1",
        )
        rm.record_trade_entry(
            symbol="ETHUSDT", side="long", size=1.0,
            entry_price=3_000, leverage=1, confidence=70,
            reason="signal", order_id="e2",
        )

        # Win on BTC, loss on ETH
        rm.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, exit_price=51_000, fees=2.0,
            funding_paid=0.0, reason="tp", order_id="x1",
        )
        rm.record_trade_exit(
            symbol="ETHUSDT", side="long", size=1.0,
            entry_price=3_000, exit_price=2_900, fees=2.0,
            funding_paid=0.0, reason="sl", order_id="x2",
        )

        stats = rm.get_daily_stats()
        assert stats is not None
        assert stats.trades_executed == 2
        assert stats.winning_trades == 1
        assert stats.losing_trades == 1
        assert stats.total_pnl == pytest.approx(100.0 + (-100.0))
        assert stats.total_fees == pytest.approx(4.0)
        # Per-symbol split
        assert stats.symbol_trades == {"BTCUSDT": 1, "ETHUSDT": 1}
        assert stats.symbol_pnl == pytest.approx({"BTCUSDT": 100.0, "ETHUSDT": -100.0})
        # Derived
        assert stats.win_rate == pytest.approx(50.0)
        # total_pnl = 0, fees = 4, funding = 0 → net_pnl = -4
        assert stats.net_pnl == pytest.approx(-4.0)

    def test_net_pnl_funding_subtraction(self):
        """Funding paid reduces net_pnl; funding received (negative) adds back.
        Contract locked: ``net_pnl = total_pnl - total_fees - total_funding``."""
        rm = _make_rm()
        rm.initialize_day(10_000.0)
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, leverage=1, confidence=70,
            reason="s", order_id="e",
        )
        rm.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, exit_price=51_000, fees=5.0,
            funding_paid=-20.0, reason="tp", order_id="x",
        )
        stats = rm.get_daily_stats()
        assert stats.total_pnl == pytest.approx(100.0)
        assert stats.total_fees == pytest.approx(5.0)
        assert stats.total_funding == pytest.approx(-20.0)
        # 100 - 5 - (-20) = 115
        assert stats.net_pnl == pytest.approx(115.0)

    def test_initialize_day_is_idempotent_same_day(self):
        """Calling initialize_day twice on the same UTC day preserves counters
        (does not re-zero). Extracted aggregator MUST preserve this to avoid
        resetting state on bot restarts within a day."""
        rm = _make_rm()
        rm.initialize_day(10_000.0)
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, leverage=1, confidence=70,
            reason="s", order_id="e1",
        )
        rm.initialize_day(20_000.0)  # would reset if not idempotent
        stats = rm.get_daily_stats()
        assert stats.trades_executed == 1
        # starting_balance is NOT overwritten on same-day re-init.
        assert stats.starting_balance == 10_000.0


# ---------------------------------------------------------------------------
# PART A.2 — TradeGate: can_trade branches
# ---------------------------------------------------------------------------


class TestCanTradeBranches:
    """Freezes each branch of ``can_trade(symbol=None)``.

    Return shape (locked): ``tuple[bool, str]`` — ``(allowed, reason)``.
    Phase 1 MUST preserve this tuple contract even if it internally
    migrates to an Enum/dataclass — the façade adapts back.
    """

    def test_rejects_when_stats_not_initialized(self):
        rm = _make_rm()
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert "not initialized" in reason.lower()

    def test_allows_when_within_all_limits(self):
        rm = _make_rm(max_trades_per_day=3, daily_loss_limit_percent=5.0)
        rm.initialize_day(10_000.0)
        allowed, reason = rm.can_trade()
        assert allowed is True
        assert reason == "Trading allowed"

    def test_allows_when_no_limits_configured(self):
        """NULL limits in BotConfig → no gating (documented in #326 premise)."""
        rm = _make_rm()
        rm.initialize_day(10_000.0)
        allowed, reason = rm.can_trade()
        assert allowed is True
        assert reason == "Trading allowed"

    def test_blocks_global_max_trades(self):
        """Global trade-count branch: trades_executed >= max → block."""
        rm = _make_rm(max_trades_per_day=2)
        rm.initialize_day(10_000.0)
        # Simulate 2 trades without exits
        for i in range(2):
            rm.record_trade_entry(
                symbol=f"SYM{i}", side="long", size=1, entry_price=100,
                leverage=1, confidence=70, reason="s", order_id=f"e{i}",
            )
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert "Global trade limit reached" in reason
        assert "2/2" in reason

    def test_blocks_global_daily_loss_limit_and_halts(self):
        """Global loss-limit branch: hitting the cap sets
        is_trading_halted=True (side effect locked)."""
        rm = _make_rm(daily_loss_limit_percent=5.0)
        rm.initialize_day(10_000.0)
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        # Force a 6% loss → crosses 5% cap.
        rm.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, exit_price=44_000, fees=0, funding_paid=0,
            reason="sl", order_id="x",
        )
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert "Daily loss limit exceeded" in reason
        # Halt side effect locked
        stats = rm.get_daily_stats()
        assert stats.is_trading_halted is True
        assert "Daily loss limit exceeded" in stats.halt_reason

    def test_blocks_once_halted_globally_independent_of_symbol(self):
        """Once is_trading_halted=True, every can_trade call returns blocked
        before per-symbol branches even run."""
        rm = _make_rm()
        rm.initialize_day(10_000.0)
        stats = rm.get_daily_stats()
        stats.is_trading_halted = True
        stats.halt_reason = "manual halt"
        allowed, reason = rm.can_trade()
        assert allowed is False
        assert "manual halt" in reason
        allowed_sym, reason_sym = rm.can_trade(symbol="BTCUSDT")
        assert allowed_sym is False
        assert "manual halt" in reason_sym

    def test_blocks_per_symbol_max_trades_without_affecting_others(self):
        """per_symbol_limits override caps one symbol; other symbols stay
        tradable. Covers the per-symbol branch explicitly."""
        rm = _make_rm(per_symbol_limits={"BTCUSDT": {"max_trades": 1}})
        rm.initialize_day(10_000.0)
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        allowed_btc, reason_btc = rm.can_trade(symbol="BTCUSDT")
        assert allowed_btc is False
        assert "trade limit reached" in reason_btc
        # Other symbol unaffected
        allowed_eth, reason_eth = rm.can_trade(symbol="ETHUSDT")
        assert allowed_eth is True

    def test_blocks_per_symbol_loss_limit_adds_to_halted_symbols(self):
        """Per-symbol loss-limit branch: symbol gets added to
        halted_symbols dict; subsequent can_trade for that symbol reads
        from halted_symbols, not from recomputation."""
        rm = _make_rm(per_symbol_limits={"BTCUSDT": {"loss_limit": 2.0}})
        rm.initialize_day(10_000.0)
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        # Force a 3% loss on 10k → 300 USD loss
        rm.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, exit_price=47_000, fees=0, funding_paid=0,
            reason="sl", order_id="x",
        )
        allowed, reason = rm.can_trade(symbol="BTCUSDT")
        assert allowed is False
        assert "halted" in reason.lower() or "limit" in reason.lower()
        # Halted-symbols side effect locked.
        stats = rm.get_daily_stats()
        assert "BTCUSDT" in stats.halted_symbols

    def test_per_symbol_override_takes_precedence_over_global(self):
        """per_symbol_limits.max_trades=5 beats global max_trades_per_day=1 for that symbol."""
        rm = _make_rm(
            max_trades_per_day=1,
            per_symbol_limits={"BTCUSDT": {"max_trades": 5}},
        )
        rm.initialize_day(10_000.0)
        # Record one BTC trade — global would block at 1, but per-symbol override = 5
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        allowed, _ = rm.can_trade(symbol="BTCUSDT")
        # Per-symbol branch only checks symbol count (1 < 5) → allowed.
        assert allowed is True


# ---------------------------------------------------------------------------
# PART A.3 — AlertThrottler: dedupe behaviour on BotWorker._risk_alerts_sent
# ---------------------------------------------------------------------------


class _FakeRiskManager:
    """Tiny stand-in so we don't need to wire a real RiskManager for
    alert-throttling tests. ``can_trade`` returns a scripted sequence."""

    def __init__(self, global_reason: str | None = None, per_symbol_reason: str | None = None):
        self._global_reason = global_reason
        self._per_symbol_reason = per_symbol_reason

    def can_trade(self, symbol=None):
        if symbol is None:
            if self._global_reason is None:
                return True, "Trading allowed"
            return False, self._global_reason
        if self._per_symbol_reason is None:
            return True, "Trading allowed"
        return False, self._per_symbol_reason


async def _run_alert_pass(worker: BotWorker, *, global_reason=None, per_symbol_reason=None):
    """Drive one pass through the alert-emission branches in _analyze_and_trade.

    Bypasses the strategy + per-symbol analysis loop — we only want to
    exercise the two alert-emission blocks (lines ~1037-1086 in
    bot_worker.py) which is where ``_risk_alerts_sent`` is mutated.
    """
    worker._risk_manager = _FakeRiskManager(global_reason, per_symbol_reason)
    worker._strategy = None  # non-self-managed path
    worker._config = MagicMock()
    worker._config.trading_pairs = '["BTCUSDT"]'
    worker._send_notification = AsyncMock()
    # Provide a client so _calculate_asset_budgets does not blow up.
    fake_balance = MagicMock()
    fake_balance.available = 1_000.0
    fake_client = MagicMock()
    fake_client.get_account_balance = AsyncMock(return_value=fake_balance)
    worker._client = fake_client
    worker._calculate_asset_budgets = MagicMock(return_value={"BTCUSDT": 1_000.0})
    worker._analyze_symbol = AsyncMock()
    await worker._analyze_and_trade()
    return worker._send_notification


@pytest.mark.asyncio
class TestAlertThrottlerDedupe:
    """Freezes the ``_risk_alerts_sent`` dedupe semantics currently inlined
    in ``BotWorker._analyze_and_trade``.

    Contract (Phase 1 must preserve):
    * First emission for a key: notification dispatched, key recorded.
    * Second emission with same key (same window): NO dispatch.
    * Different key (different symbol or different reason): dispatched.
    * Non-"halted"/"limit" reasons: never queued as alerts (filter).
    """

    async def test_first_global_alert_emits_and_records_key(self):
        worker = BotWorker(bot_config_id=1)
        send_mock = await _run_alert_pass(
            worker, global_reason="Global trade limit reached (3/3)",
        )
        send_mock.assert_awaited_once()
        # Key recorded
        assert any(
            k.startswith("global_") for k in worker._risk_alerts_sent
        ), "global alert key must be recorded in _risk_alerts_sent"

    async def test_duplicate_global_alert_is_deduped(self):
        worker = BotWorker(bot_config_id=1)
        await _run_alert_pass(
            worker, global_reason="Global trade limit reached (3/3)",
        )
        # Second pass with the SAME reason: no new notification
        worker._send_notification = AsyncMock()
        worker._risk_manager = _FakeRiskManager(
            global_reason="Global trade limit reached (3/3)",
        )
        await worker._analyze_and_trade()
        worker._send_notification.assert_not_awaited()

    async def test_different_global_reason_emits_new_alert(self):
        """Different reason string → different key → emitted."""
        worker = BotWorker(bot_config_id=1)
        send1 = await _run_alert_pass(
            worker, global_reason="Global trade limit reached (3/3)",
        )
        send1.assert_awaited_once()

        # New reason — still triggers emission
        worker._send_notification = AsyncMock()
        worker._risk_manager = _FakeRiskManager(
            global_reason="Daily loss limit exceeded (5% >= 5%)",
        )
        await worker._analyze_and_trade()
        worker._send_notification.assert_awaited_once()

    async def test_non_matching_reason_is_not_queued(self):
        """Reasons without 'halted' or 'limit' keywords are NOT queued as
        alerts — the filter on line 1042 / 1073 is locked behaviour."""
        worker = BotWorker(bot_config_id=1)
        await _run_alert_pass(
            worker, global_reason="not initialized yet",
        )
        # No key recorded because "not initialized" doesn't match the filter.
        assert not any(
            "not initialized" in k for k in worker._risk_alerts_sent
        )

    async def test_per_symbol_alert_key_includes_symbol(self):
        """Per-symbol alert uses ``f\"{symbol}_{reason}\"`` as key — different
        symbols yield different keys so both emit independently."""
        worker = BotWorker(bot_config_id=1)
        worker._risk_manager = _FakeRiskManager(
            per_symbol_reason="BTCUSDT: trade limit reached (3/3)",
        )
        worker._strategy = None
        worker._config = MagicMock()
        worker._config.trading_pairs = '["BTCUSDT"]'
        worker._send_notification = AsyncMock()
        worker._client = MagicMock()
        bal = MagicMock(); bal.available = 1_000
        worker._client.get_account_balance = AsyncMock(return_value=bal)
        worker._calculate_asset_budgets = MagicMock(return_value={"BTCUSDT": 1_000})
        worker._analyze_symbol = AsyncMock()

        await worker._analyze_and_trade()
        assert any(
            k.startswith("BTCUSDT_") for k in worker._risk_alerts_sent
        ), "per-symbol alert key must include the symbol prefix"


# ---------------------------------------------------------------------------
# PART B.1 — AlertThrottler midnight reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAlertThrottlerMidnightReset:
    """Freezes the 24h reset cadence on ``_risk_alerts_sent``.

    Contract (Phase 1 must preserve):
    * If ``now - _risk_alerts_last_reset > 86400s``, the set is cleared
      and ``_risk_alerts_last_reset`` is updated to ``now``.
    * Otherwise the set is preserved as-is.
    * The clear happens BEFORE the alert-emission branches run, so a
      stale key from yesterday does not block today's first alert.
    """

    async def test_no_reset_when_within_24h_window(self):
        """Last reset < 24h ago → set is NOT cleared."""
        worker = BotWorker(bot_config_id=1)
        worker._risk_alerts_last_reset = datetime.now(timezone.utc) - timedelta(hours=1)
        stale_key = "global_some_old_reason"
        worker._risk_alerts_sent.add(stale_key)

        send_mock = await _run_alert_pass(worker, global_reason=None)
        # No alert because no reason triggered, and the stale key is preserved.
        send_mock.assert_not_awaited()
        assert stale_key in worker._risk_alerts_sent

    async def test_resets_after_24h_window_and_stamps_new_timestamp(self):
        """Last reset > 24h ago → set cleared, timestamp bumped."""
        worker = BotWorker(bot_config_id=1)
        old_reset = datetime.now(timezone.utc) - timedelta(hours=25)
        worker._risk_alerts_last_reset = old_reset
        worker._risk_alerts_sent.add("stale_from_yesterday")

        await _run_alert_pass(worker, global_reason=None)

        assert "stale_from_yesterday" not in worker._risk_alerts_sent
        # Timestamp was bumped forward (monotonically > old_reset).
        assert worker._risk_alerts_last_reset > old_reset

    async def test_reset_unblocks_same_key_emission_next_day(self):
        """After midnight reset, the same alert key that was deduped
        yesterday should fire again — this is the whole point of the reset."""
        worker = BotWorker(bot_config_id=1)
        # Day 1 — first alert fires + is recorded
        await _run_alert_pass(
            worker, global_reason="Global trade limit reached (3/3)",
        )
        assert any(k.startswith("global_") for k in worker._risk_alerts_sent)

        # Simulate 25h elapsed
        worker._risk_alerts_last_reset = datetime.now(timezone.utc) - timedelta(hours=25)

        # Day 2 — SAME reason should re-emit
        worker._send_notification = AsyncMock()
        worker._risk_manager = _FakeRiskManager(
            global_reason="Global trade limit reached (3/3)",
        )
        await worker._analyze_and_trade()
        worker._send_notification.assert_awaited_once()

    async def test_daily_summary_unconditionally_resets_alerts(self):
        """``_send_daily_summary`` clears ``_risk_alerts_sent`` on every
        code path (happy/skip/exception). Regression guard: if a future
        refactor moves the clear into a conditional branch, this test
        fires. Already covered in ``test_bot_worker_daily_summary.py``
        but locked here too so the risk-component refactor sees it."""
        worker = BotWorker(bot_config_id=1)
        worker._config = MagicMock()
        worker._config.name = "Bot"
        worker._config.user_id = 1
        worker._config.id = 1
        worker._risk_alerts_sent.add("stale")
        rm = MagicMock()
        rm.get_daily_stats.return_value = None
        worker._risk_manager = rm
        worker._send_notification = AsyncMock()

        await worker._send_daily_summary()
        assert worker._risk_alerts_sent == set()


# ---------------------------------------------------------------------------
# PART B.2 — RiskStatePersistence: DB load path (#188 truth-source)
# ---------------------------------------------------------------------------


class _FakeQueryResult:
    """Minimal stand-in for a SQLAlchemy result object."""

    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Minimal async-session stand-in used as a context manager."""

    def __init__(self, row=None, raises: Exception | None = None):
        self._row = row
        self._raises = raises
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, _stmt):
        if self._raises is not None:
            raise self._raises
        return _FakeQueryResult(self._row)

    def add(self, row):
        self.added.append(row)


def _session_cm_factory(session: _FakeSession):
    """Return a callable that mimics ``get_session()`` returning an async CM."""
    def _factory():
        return session
    return _factory


@pytest.mark.asyncio
class TestRiskStatePersistenceLoad:
    """Freezes the #188 truth-source read path.

    Contract (Phase 1 must preserve):
    * ``_use_db=False`` (no bot_config_id / no DB imports) → ``load_stats_from_db``
      is a no-op.
    * ``_use_db=True`` + DB row exists → hydrates ``_daily_stats`` from the
      JSON blob and drops computed fields (``net_pnl`` / ``return_percent`` /
      ``win_rate``) before DailyStats construction (they are @property).
    * ``_use_db=True`` + DB row missing → ``_daily_stats`` stays ``None``
      (no default state is materialised on miss).
    * ``_use_db=True`` + read raises → exception swallowed, logger.warning,
      ``_daily_stats`` remains unchanged.
    """

    async def test_noop_when_db_disabled(self):
        rm = _make_rm()  # bot_config_id=None → _use_db=False
        await rm.load_stats_from_db()
        assert rm.get_daily_stats() is None

    async def test_loads_daily_stats_from_db_row(self):
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True  # force DB path even if sqlalchemy import-guard flipped it

        today = datetime.now().strftime("%Y-%m-%d")
        row = MagicMock()
        row.stats_json = (
            '{"date": "' + today + '", '
            '"starting_balance": 10000.0, "current_balance": 10100.0, '
            '"trades_executed": 2, "winning_trades": 1, "losing_trades": 1, '
            '"total_pnl": 150.0, "total_fees": 10.0, "total_funding": 5.0, '
            '"max_drawdown": 2.5, "is_trading_halted": false, '
            '"halt_reason": "", "symbol_trades": {"BTCUSDT": 2}, '
            '"symbol_pnl": {"BTCUSDT": 150.0}, "halted_symbols": {}, '
            # Computed fields must be stripped out before DailyStats(**data)
            '"net_pnl": 135.0, "return_percent": 1.35, "win_rate": 50.0}'
        )
        fake_session = _FakeSession(row=row)

        with patch("src.risk.risk_manager.get_session", _session_cm_factory(fake_session)):
            await rm.load_stats_from_db()

        stats = rm.get_daily_stats()
        assert stats is not None
        assert stats.trades_executed == 2
        assert stats.starting_balance == 10000.0
        assert stats.symbol_trades == {"BTCUSDT": 2}

    async def test_leaves_stats_none_when_db_row_missing(self):
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        fake_session = _FakeSession(row=None)
        with patch("src.risk.risk_manager.get_session", _session_cm_factory(fake_session)):
            await rm.load_stats_from_db()
        # No default materialised on miss.
        assert rm.get_daily_stats() is None

    async def test_swallows_db_read_exception(self):
        """Contract locked: any Exception during load is swallowed + logged.
        ``_daily_stats`` stays unchanged, no propagation — the bot must
        continue without DB history rather than crash on boot."""
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        fake_session = _FakeSession(raises=RuntimeError("DB down"))
        with patch("src.risk.risk_manager.get_session", _session_cm_factory(fake_session)):
            # Must NOT raise
            await rm.load_stats_from_db()
        assert rm.get_daily_stats() is None


# ---------------------------------------------------------------------------
# PART B.3 — Exception-swallow behaviour on DB write + notification paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExceptionSwallowContracts:
    """Freezes the exception-handling contracts that the Phase 1 refactor
    MUST preserve.

    Contract locked:
    * ``_save_stats_to_db`` failure → warning log, no propagation, caller
      (e.g. ``record_trade_entry``) still returns ``True``.
    * Notifier failure during alert emission → does not break the
      trade-gate logic for subsequent symbols. (Already verified in
      ``test_bot_worker_daily_summary.py::test_swallows_notification_exception_and_still_clears_alerts``;
      re-locked here for the extraction safety-net.)
    """

    async def test_save_stats_swallows_db_exception(self):
        """DB write failure must not propagate out of ``_save_stats_to_db``
        — the in-memory ``_daily_stats`` remains source-of-truth for the
        running session, DB resyncs on next successful write."""
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        rm.initialize_day(10_000.0)
        fake_session = _FakeSession(raises=RuntimeError("write rejected"))
        with patch("src.risk.risk_manager.get_session", _session_cm_factory(fake_session)):
            # Must NOT raise
            await rm._save_stats_to_db()
        # State unchanged.
        stats = rm.get_daily_stats()
        assert stats is not None
        assert stats.starting_balance == 10_000.0

    async def test_save_stats_noop_when_db_disabled(self):
        rm = _make_rm()  # _use_db = False
        rm.initialize_day(10_000.0)
        # Must NOT raise, must NOT hit DB (no patching needed).
        await rm._save_stats_to_db()

    async def test_notifier_exception_does_not_break_analysis_loop(self):
        """A Discord/Telegram failure during ``_send_notification`` must not
        prevent the per-symbol analysis loop from continuing to the next
        symbol. Locks the AlertThrottler swallow-on-error contract
        introduced in ARCH-H2 Phase 1 PR-4 (#326).

        Before PR-4, notifier exceptions propagated out of
        ``_analyze_and_trade``; this test was skipped with a FIXME. PR-4
        wraps the dispatch in ``AlertThrottler._dispatch`` so a flaky
        webhook never aborts the analysis loop.
        """
        worker = BotWorker(bot_config_id=1)
        worker._risk_manager = _FakeRiskManager(
            per_symbol_reason="BTCUSDT: trade limit reached (1/1)",
        )
        worker._strategy = None
        worker._config = MagicMock()
        worker._config.trading_pairs = '["BTCUSDT", "ETHUSDT"]'
        # ETHUSDT-path risk manager override: allowed
        worker._send_notification = AsyncMock(
            side_effect=[RuntimeError("discord 500"), None],
        )
        worker._client = MagicMock()
        bal = MagicMock(); bal.available = 1_000
        worker._client.get_account_balance = AsyncMock(return_value=bal)
        worker._calculate_asset_budgets = MagicMock(
            return_value={"BTCUSDT": 500, "ETHUSDT": 500},
        )
        worker._analyze_symbol = AsyncMock()

        # Must not raise — throttler swallows the notifier exception.
        await worker._analyze_and_trade()

        # Loop survived: both BTCUSDT + ETHUSDT alert branches ran. The
        # first notifier call raised + was swallowed; the second ran.
        assert worker._send_notification.await_count == 2

    async def test_save_stats_inserts_new_row_when_none_exists(self):
        """Happy-path write: no existing row → INSERT a new RiskStats row."""
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        rm.initialize_day(10_000.0)
        fake_session = _FakeSession(row=None)
        with patch("src.risk.risk_manager.get_session", _session_cm_factory(fake_session)):
            await rm._save_stats_to_db()
        # An upsert-new path must call session.add exactly once.
        assert len(fake_session.added) == 1
        added = fake_session.added[0]
        assert added.bot_config_id == 42
        assert added.trades_count == 0
        assert added.is_halted is False

    async def test_save_stats_updates_existing_row(self):
        """Happy-path update: existing row → mutate fields, no INSERT."""
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        rm.initialize_day(10_000.0)
        # Give the stats some non-default state.
        stats = rm.get_daily_stats()
        stats.trades_executed = 5
        stats.total_pnl = 42.0
        stats.is_trading_halted = True
        existing = MagicMock()
        fake_session = _FakeSession(row=existing)
        with patch("src.risk.risk_manager.get_session", _session_cm_factory(fake_session)):
            await rm._save_stats_to_db()
        # No INSERT
        assert fake_session.added == []
        # Fields mutated on the existing row
        assert existing.trades_count == 5
        assert existing.is_halted is True

    async def test_get_historical_stats_from_db_returns_parsed_rows(self):
        """Happy-path historical read: returns list of parsed dicts."""
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        # Two fake rows
        row1 = MagicMock()
        row1.stats_json = '{"date": "2026-04-20", "trades_executed": 3}'
        row2 = MagicMock()
        row2.stats_json = '{"date": "2026-04-19", "trades_executed": 5}'

        class _MultiResult:
            def scalars(self):
                class _S:
                    def all(self_inner):
                        return [row1, row2]
                return _S()

        class _HistSession(_FakeSession):
            async def execute(self_inner, _stmt):
                return _MultiResult()

        with patch(
            "src.risk.risk_manager.get_session",
            _session_cm_factory(_HistSession()),
        ):
            rows = await rm.get_historical_stats_from_db(days=30)
        assert len(rows) == 2
        assert rows[0]["trades_executed"] == 3
        assert rows[1]["trades_executed"] == 5

    async def test_get_historical_stats_from_db_swallows_exception(self):
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        with patch(
            "src.risk.risk_manager.get_session",
            _session_cm_factory(_FakeSession(raises=RuntimeError("db down"))),
        ):
            rows = await rm.get_historical_stats_from_db(days=30)
        assert rows == []

    async def test_get_historical_stats_noop_when_db_disabled(self):
        rm = _make_rm()  # _use_db = False
        rows = await rm.get_historical_stats_from_db(days=30)
        assert rows == []

    async def test_record_trade_entry_returns_true_even_when_save_fails(self):
        """``record_trade_entry`` returns ``True`` regardless of persistence
        outcome — the sync wrapper ``_save_daily_stats`` schedules the DB
        write as a fire-and-forget task, so entry recording cannot fail
        on a DB error."""
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        rm.initialize_day(10_000.0)
        # Patch get_session to raise on any write attempt.
        fake_session = _FakeSession(raises=RuntimeError("db gone"))
        with patch("src.risk.risk_manager.get_session", _session_cm_factory(fake_session)):
            ok = rm.record_trade_entry(
                symbol="BTCUSDT", side="long", size=0.1,
                entry_price=50_000, leverage=1, confidence=70,
                reason="s", order_id="e",
            )
        assert ok is True
        stats = rm.get_daily_stats()
        assert stats.trades_executed == 1


# ---------------------------------------------------------------------------
# PART B.4 — TradeGate auxiliary observables (remaining trades / budget /
# dynamic loss limit). These also belong to the TradeGate component.
# ---------------------------------------------------------------------------


class TestTradeGateAuxiliaryObservables:
    """Freezes ``get_remaining_trades`` / ``get_remaining_risk_budget`` /
    ``get_dynamic_loss_limit``. These sit on the TradeGate component in
    Phase 1 — lock their shape now."""

    def test_remaining_trades_returns_999_when_no_limit(self):
        """``None`` max_trades → sentinel 999 (locked: callers treat as "unlimited")."""
        rm = _make_rm()
        rm.initialize_day(10_000.0)
        assert rm.get_remaining_trades() == 999

    def test_remaining_trades_global_decrements(self):
        rm = _make_rm(max_trades_per_day=5)
        rm.initialize_day(10_000.0)
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        assert rm.get_remaining_trades() == 4

    def test_remaining_trades_per_symbol(self):
        """Per-symbol override: remaining decrements only for that symbol."""
        rm = _make_rm(per_symbol_limits={"BTCUSDT": {"max_trades": 3}})
        rm.initialize_day(10_000.0)
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        assert rm.get_remaining_trades(symbol="BTCUSDT") == 2
        # ETHUSDT has no per-symbol override, falls back to global (None) → 999
        assert rm.get_remaining_trades(symbol="ETHUSDT") == 999

    def test_remaining_trades_before_initialize(self):
        """Edge: no stats yet → returns effective cap (not zero)."""
        rm = _make_rm(max_trades_per_day=3)
        assert rm.get_remaining_trades() == 3

    def test_remaining_risk_budget_none_when_no_limit(self):
        rm = _make_rm()
        rm.initialize_day(10_000.0)
        assert rm.get_remaining_risk_budget() is None

    def test_remaining_risk_budget_full_when_no_loss(self):
        rm = _make_rm(daily_loss_limit_percent=5.0)
        rm.initialize_day(10_000.0)
        assert rm.get_remaining_risk_budget() == 5.0

    def test_remaining_risk_budget_decreases_with_loss(self):
        rm = _make_rm(daily_loss_limit_percent=5.0)
        rm.initialize_day(10_000.0)
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        rm.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, exit_price=49_500, fees=0, funding_paid=0,
            reason="sl", order_id="x",
        )
        # 0.5% loss → 4.5% remaining (approx; return_percent is net of fees/funding=0)
        remaining = rm.get_remaining_risk_budget()
        assert remaining is not None
        assert 4.3 < remaining < 4.6

    def test_dynamic_loss_limit_none_when_no_global_limit(self):
        rm = _make_rm()
        rm.initialize_day(10_000.0)
        assert rm.get_dynamic_loss_limit() is None

    def test_dynamic_loss_limit_returns_base_when_profit_lock_disabled(self):
        rm = _make_rm(daily_loss_limit_percent=5.0, enable_profit_lock=False)
        rm.initialize_day(10_000.0)
        # Even with positive return, profit_lock disabled → base limit unchanged.
        assert rm.get_dynamic_loss_limit() == 5.0

    def test_dynamic_loss_limit_tightens_after_profit(self):
        """Profit Lock-In: after booking profit, the loss limit shrinks
        toward the min_profit_floor so a drawdown can't erase gains."""
        rm = RiskManager(
            max_trades_per_day=10,
            daily_loss_limit_percent=5.0,
            enable_profit_lock=True,
            profit_lock_percent=75.0,
            min_profit_floor=0.5,
            bot_config_id=None,
        )
        rm.initialize_day(10_000.0)
        # Book a 3% profit
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        rm.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, exit_price=53_000, fees=0, funding_paid=0,
            reason="tp", order_id="x",
        )
        # return ≈ +3%, max_allowed_loss = 3 - 0.5 = 2.5
        # new_limit = min(5.0, 2.5) = 2.5
        dyn = rm.get_dynamic_loss_limit()
        assert dyn == pytest.approx(2.5)


class TestAggregatorErrorPaths:
    """Edge cases on DailyStats aggregator that Phase 1 must preserve."""

    def test_record_entry_before_init_returns_false(self):
        """Safety path: entry without init → logs error, returns False (does NOT raise)."""
        rm = _make_rm()
        ok = rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        assert ok is False

    def test_record_exit_before_init_returns_false(self):
        rm = _make_rm()
        ok = rm.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            exit_price=51_000, fees=0, funding_paid=0, reason="tp", order_id="x",
        )
        assert ok is False

    def test_save_daily_stats_noop_when_no_stats(self):
        """Sync wrapper `_save_daily_stats` is a no-op if stats is None."""
        rm = RiskManager(bot_config_id=42)
        rm._use_db = True
        # Should NOT raise even though no event loop is running and no stats.
        rm._save_daily_stats()
        assert rm.get_daily_stats() is None

    def test_dynamic_loss_limit_returns_base_when_return_is_negative(self):
        """Profit Lock-In early-return: if return <= 0, no tightening."""
        rm = RiskManager(
            max_trades_per_day=10,
            daily_loss_limit_percent=5.0,
            enable_profit_lock=True,
            bot_config_id=None,
        )
        rm.initialize_day(10_000.0)
        # Book a small loss — return_percent < 0
        rm.record_trade_entry(
            symbol="BTCUSDT", side="long", size=0.1, entry_price=50_000,
            leverage=1, confidence=70, reason="s", order_id="e",
        )
        rm.record_trade_exit(
            symbol="BTCUSDT", side="long", size=0.1,
            entry_price=50_000, exit_price=49_500, fees=0, funding_paid=0,
            reason="sl", order_id="x",
        )
        # Negative return → base limit returned unchanged (line 311).
        assert rm.get_dynamic_loss_limit() == 5.0


class TestCanTradePerSymbolLossLimitInGate:
    """Freezes the per-symbol loss-limit branch INSIDE ``can_trade`` (lines
    357-367). The record-trade-exit path halts symbols eagerly; this test
    covers the gate-side branch where a symbol with accumulated loss has
    NOT yet been halted via halted_symbols — ``can_trade`` recomputes the
    percentage and halts on-the-fly."""

    def test_can_trade_halts_on_pending_symbol_loss(self):
        rm = _make_rm(per_symbol_limits={"BTCUSDT": {"loss_limit": 2.0}})
        rm.initialize_day(10_000.0)
        # Manually inject per-symbol PnL without triggering halted_symbols
        # via record_trade_exit (which would short-circuit line 342).
        stats = rm.get_daily_stats()
        stats.symbol_pnl["BTCUSDT"] = -300.0  # 3% loss vs 2% cap
        assert "BTCUSDT" not in stats.halted_symbols  # precondition

        allowed, reason = rm.can_trade(symbol="BTCUSDT")
        assert allowed is False
        assert "Loss limit exceeded" in reason
        # Side effect: now added to halted_symbols
        assert "BTCUSDT" in stats.halted_symbols
