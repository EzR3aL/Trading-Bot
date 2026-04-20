"""Unit tests for the #216 audit scripts and ``AuditScheduler``.

One smoke test per audit script verifies the comparison/parsing logic
reports a mismatch when one is present. A second scheduler-level test
asserts the four audits register with the expected hourly cadence.

The scripts themselves are imported normally (namespace package
``scripts/``) — both ``scripts/_audit_common.py`` and ``src/`` need to
be on ``sys.path``, which the project's ``conftest.py`` already arranges.
Where a script would hit the DB, we call its pure comparator function
directly or pass an in-memory SQLite session factory via ``patch``.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


# ── audit_tp_sl_flags ──────────────────────────────────────────────────


def _fake_trade(
    trade_id: int = 101,
    exchange: str = "bitget",
    symbol: str = "BTCUSDT",
    side: str = "long",
    *,
    size: float = 0.01,
    take_profit=None,
    stop_loss=None,
    tp_order_id=None,
    sl_order_id=None,
    entry_price: float = 68_000.0,
    exit_price=None,
    entry_time=None,
    exit_time=None,
    status: str = "open",
) -> SimpleNamespace:
    """Build a duck-typed stand-in for a TradeRecord row."""
    return SimpleNamespace(
        id=trade_id,
        user_id=1,
        bot_config_id=None,
        exchange=exchange,
        symbol=symbol,
        side=side,
        size=size,
        entry_price=entry_price,
        exit_price=exit_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        tp_order_id=tp_order_id,
        sl_order_id=sl_order_id,
        demo_mode=True,
        entry_time=entry_time,
        exit_time=exit_time,
        status=status,
    )


def test_audit_tp_sl_flags_reports_db_only_tp_mismatch():
    """DB has TP, exchange doesn't → one ``db_only_tp`` mismatch is reported."""
    from scripts import audit_tp_sl_flags

    trade = _fake_trade(
        take_profit=71_000.0,
        tp_order_id="db-tp-1",
        stop_loss=None,
        sl_order_id=None,
    )
    exchange_snap = SimpleNamespace(
        symbol="BTCUSDT",
        side="long",
        tp_price=None,
        tp_order_id=None,
        tp_trigger_type=None,
        sl_price=None,
        sl_order_id=None,
        sl_trigger_type=None,
    )

    mismatches = audit_tp_sl_flags.compare_tp_sl(trade, exchange_snap)

    assert [m.kind for m in mismatches] == ["db_only_tp"]
    assert mismatches[0].trade_id == trade.id
    assert mismatches[0].db_value == 71_000.0
    assert mismatches[0].exchange_value is None


def test_audit_tp_sl_flags_outcome_dict_shape():
    """AuditReport.as_outcome() carries the mismatch into the scheduler."""
    from scripts import audit_tp_sl_flags

    report = audit_tp_sl_flags.AuditReport(
        started_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        apply_mode=False,
        user_id_filter=None,
        exchange_filter=None,
        checked=1,
    )
    report.mismatches.append(audit_tp_sl_flags.FlagMismatch(
        trade_id=1, user_id=1, exchange="bitget", symbol="BTCUSDT",
        side="long", demo_mode=True,
        kind="db_only_sl", db_value=67_500.0, exchange_value=None,
    ))

    outcome = report.as_outcome()
    assert outcome["mismatches"][0]["kind"] == "db_only_sl"


# ── audit_position_size ────────────────────────────────────────────────


def test_audit_position_size_flags_desync_above_tolerance():
    """An exchange size 5 % smaller than DB is flagged as ``desync``."""
    from scripts import audit_position_size

    trade = _fake_trade(size=0.100)
    finding = audit_position_size.classify_size_drift(trade, exchange_size=0.095)

    assert finding.severity == "desync"
    assert finding.delta_pct is not None
    assert finding.delta_pct < -audit_position_size.SIZE_TOLERANCE_PCT


def test_audit_position_size_tolerance_boundary_is_rounded():
    """A tiny 0.1 % delta falls inside tolerance and is ``rounded``."""
    from scripts import audit_position_size

    trade = _fake_trade(size=0.100)
    finding = audit_position_size.classify_size_drift(trade, exchange_size=0.0999)
    assert finding.severity == "rounded"


def test_audit_position_size_missing_position_is_flagged():
    """``None`` from the exchange means the position disappeared — ``missing``."""
    from scripts import audit_position_size

    trade = _fake_trade(size=0.25)
    finding = audit_position_size.classify_size_drift(trade, exchange_size=None)
    assert finding.severity == "missing"
    assert finding.exchange_size is None


# ── audit_price_sanity ─────────────────────────────────────────────────


def _make_kline(open_time_ms: int, open_price: float, close_price: float) -> list:
    """Build a Binance-shaped kline row."""
    return [
        open_time_ms,
        str(open_price),
        str(open_price * 1.001),  # high
        str(open_price * 0.999),  # low
        str(close_price),
        "0",                       # volume
        open_time_ms + 59_000,
    ]


def test_audit_price_sanity_flags_exit_above_threshold():
    """A 5 % gap between DB exit_price and kline close triggers a finding."""
    from scripts import audit_price_sanity

    exit_time = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    trade = _fake_trade(
        status="closed",
        entry_price=68_000.0,
        exit_price=70_000.0,  # DB exit
        exit_time=exit_time,
    )
    exit_kline = _make_kline(
        open_time_ms=int(exit_time.timestamp() * 1000),
        open_price=66_500.0,
        close_price=66_500.0,  # kline says the real price was much lower
    )

    findings = audit_price_sanity.compare_prices(
        trade, entry_kline=None, exit_kline=exit_kline,
    )

    assert len(findings) == 1
    assert findings[0].kind == "exit"
    assert findings[0].db_price == 70_000.0
    assert findings[0].kline_price == 66_500.0
    assert abs(findings[0].deviation_pct) > audit_price_sanity.PRICE_DEVIATION_THRESHOLD_PCT


def test_audit_price_sanity_tight_match_produces_no_finding():
    """A 0.1 % deviation stays under the 2 % threshold → no finding."""
    from scripts import audit_price_sanity

    exit_time = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    trade = _fake_trade(
        status="closed", exit_price=68_068.0, exit_time=exit_time,
    )
    kline = _make_kline(
        open_time_ms=int(exit_time.timestamp() * 1000),
        open_price=68_000.0, close_price=68_000.0,
    )
    findings = audit_price_sanity.compare_prices(trade, None, kline)
    assert findings == []


# ── audit_classify_method ──────────────────────────────────────────────


def test_audit_classify_method_text_parser_recognises_line():
    """The plain-text parser picks up ``method=heuristic_fallback`` emissions."""
    from scripts import audit_classify_method

    line = (
        "2026-04-20 12:34:56 | INFO | src.bot.risk_state_manager | "
        "classify_close:540 | risk_state.classify_close trade=286 "
        "reason=EXTERNAL_CLOSE_UNKNOWN method=heuristic_fallback"
    )

    event = audit_classify_method.parse_event_line(line)
    assert event is not None
    assert event.trade_id == 286
    assert event.reason == "EXTERNAL_CLOSE_UNKNOWN"
    assert event.method == "heuristic_fallback"


def test_audit_classify_method_aggregates_and_alerts_on_high_fallback_rate():
    """>30 % fallback share on a single exchange yields an alert."""
    from scripts import audit_classify_method

    ts = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    events = [
        audit_classify_method.ClassifyEvent(
            timestamp=ts, trade_id=1, reason="r", method="history_match",
            exchange="bitget",
        ),
        audit_classify_method.ClassifyEvent(
            timestamp=ts, trade_id=2, reason="r", method="heuristic_fallback",
            exchange="bitget",
        ),
        audit_classify_method.ClassifyEvent(
            timestamp=ts, trade_id=3, reason="r", method="heuristic_fallback",
            exchange="bitget",
        ),
    ]
    stats = audit_classify_method.aggregate_stats(events)
    alerts = audit_classify_method.compute_alerts(stats)

    assert stats["bitget"].total == 3
    assert stats["bitget"].fallback_rate == pytest.approx(2 / 3)
    assert len(alerts) == 1
    assert "bitget" in alerts[0]


def test_audit_classify_method_clean_logs_produce_no_alert():
    """All history_match → no alert, no noise."""
    from scripts import audit_classify_method

    ts = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    events = [
        audit_classify_method.ClassifyEvent(
            timestamp=ts, trade_id=i, reason="r",
            method="history_match", exchange="bitget",
        )
        for i in range(10)
    ]
    stats = audit_classify_method.aggregate_stats(events)
    alerts = audit_classify_method.compute_alerts(stats)
    assert alerts == []


# ── AuditScheduler ─────────────────────────────────────────────────────


def test_audit_scheduler_registers_four_jobs_with_expected_cadence():
    """AuditScheduler registers exactly 4 cron jobs, 15-minute offsets."""
    from src.bot.audit_scheduler import AUDIT_JOBS, AuditScheduler

    scheduler = AuditScheduler()
    scheduler.register_jobs()

    job_ids = scheduler.get_job_ids()
    assert set(job_ids) == {j.job_id for j in AUDIT_JOBS}
    assert len(job_ids) == 4

    minutes = scheduler.get_job_minutes()
    assert minutes == {
        "audit_tp_sl_flags": 0,
        "audit_position_size": 15,
        "audit_price_sanity": 30,
        "audit_classify_method": 45,
    }


def test_audit_scheduler_summary_is_none_on_clean_outcome():
    """Clean runs MUST NOT generate a notification summary."""
    from scripts import audit_tp_sl_flags as tp_sl
    from src.bot.audit_scheduler import AUDIT_JOBS, summarize_outcome

    clean_outcome = {
        "audit": tp_sl.AUDIT_NAME,
        "checked": 5,
        "mismatches": [],
        "skipped": [],
        "errors": [],
    }
    tp_sl_job = next(j for j in AUDIT_JOBS if j.job_id == "audit_tp_sl_flags")
    assert summarize_outcome(tp_sl_job, clean_outcome) is None


def test_audit_scheduler_summary_mentions_mismatch_on_findings():
    """A non-empty mismatches list surfaces in the notification text."""
    from scripts import audit_tp_sl_flags as tp_sl
    from src.bot.audit_scheduler import AUDIT_JOBS, summarize_outcome

    outcome = {
        "audit": tp_sl.AUDIT_NAME,
        "checked": 3,
        "mismatches": [
            {"trade_id": 42, "kind": "db_only_tp",
             "exchange": "bitget", "symbol": "BTCUSDT",
             "db_value": 71_000.0, "exchange_value": None},
        ],
        "skipped": [],
        "errors": [],
    }
    tp_sl_job = next(j for j in AUDIT_JOBS if j.job_id == "audit_tp_sl_flags")
    summary = summarize_outcome(tp_sl_job, outcome)
    assert summary is not None
    assert "TP/SL" in summary
    assert "42" in summary


@pytest.mark.asyncio
async def test_audit_scheduler_notifier_receives_summary_on_findings(monkeypatch):
    """Wrapped runner calls ``notifier(summary, outcome)`` for a finding."""
    from src.bot import audit_scheduler as scheduler_module

    captured: list[tuple[str, dict]] = []

    async def fake_notifier(summary: str, outcome: dict) -> None:
        captured.append((summary, outcome))

    finding_outcome = {
        "audit": scheduler_module.audit_tp_sl_flags.AUDIT_NAME,
        "checked": 1,
        "mismatches": [{
            "trade_id": 7, "kind": "exchange_only_sl",
            "exchange": "bingx", "symbol": "ETHUSDT",
            "db_value": None, "exchange_value": 3400.0,
        }],
        "skipped": [],
        "errors": [],
    }

    async def fake_runner() -> dict:
        return finding_outcome

    fake_job = scheduler_module.AuditJob(
        job_id="fake_job",
        name="Fake Audit",
        minute=0,
        runner=fake_runner,
    )

    with patch.object(scheduler_module, "summarize_outcome",
                      return_value="synthetic summary"):
        scheduler = scheduler_module.AuditScheduler(
            notifier=fake_notifier, jobs=(fake_job,),
        )
        runner = scheduler._wrap_runner(fake_job)
        await runner()

    assert captured == [("synthetic summary", finding_outcome)]


@pytest.mark.asyncio
async def test_audit_scheduler_notifier_skipped_on_clean_run():
    """Clean runs MUST NOT invoke the notifier."""
    from src.bot import audit_scheduler as scheduler_module

    call_count = {"n": 0}

    async def fake_notifier(summary: str, outcome: dict) -> None:
        call_count["n"] += 1

    async def clean_runner() -> dict:
        # Use a real audit name so summarize_outcome recognises "no findings"
        # rather than falling through to the unknown-audit catch-all.
        return {
            "audit": scheduler_module.audit_tp_sl_flags.AUDIT_NAME,
            "checked": 1,
            "mismatches": [],
            "skipped": [],
            "errors": [],
        }

    fake_job = scheduler_module.AuditJob(
        job_id="clean_job", name="Clean", minute=0, runner=clean_runner,
    )
    scheduler = scheduler_module.AuditScheduler(
        notifier=fake_notifier, jobs=(fake_job,),
    )
    runner = scheduler._wrap_runner(fake_job)
    await runner()

    assert call_count["n"] == 0
