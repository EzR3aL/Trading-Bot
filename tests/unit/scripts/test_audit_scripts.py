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
from datetime import datetime, timedelta, timezone
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


def test_audit_classify_method_json_parser_yields_tz_aware_timestamp():
    """Trading-bot JSON logs emit ``YYYY-MM-DD HH:MM:SS,fff`` without tz (#238).

    Python 3.11+ ``fromisoformat`` parses that to a *naive* datetime; the
    scheduler later compares it against a tz-aware ``since`` and raises
    ``TypeError``. The parser must normalize to UTC.
    """
    from scripts import audit_classify_method

    line = (
        '{"timestamp": "2026-04-21 16:45:00,123", "level": "INFO", '
        '"logger": "src.bot.risk_state_manager", '
        '"message": "risk_state.classify_close trade=540 '
        'reason=EXTERNAL_CLOSE_UNKNOWN method=heuristic_fallback"}'
    )

    event = audit_classify_method.parse_event_line(line)
    assert event is not None
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset() == timedelta(0)
    assert event.trade_id == 540
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


# ── default_admin_notifier: DB-first with env fallback (#242) ──────────


def _admin_user(user_id: int = 1) -> SimpleNamespace:
    """Duck-typed admin row with the fields audit_scheduler reads."""
    return SimpleNamespace(id=user_id, role="admin", is_active=True)


def _bot_config_stub(
    *,
    discord_webhook_url=None,
    telegram_bot_token=None,
    telegram_chat_id=None,
    bot_id: int = 1,
) -> SimpleNamespace:
    """Duck-typed BotConfig row with encrypted-style fields."""
    return SimpleNamespace(
        id=bot_id,
        discord_webhook_url=discord_webhook_url,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )


class _FakeScalarResult:
    def __init__(self, items):
        self._items = list(items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalars(self):
        class _Scalars:
            def __init__(self, items):
                self._items = items

            def all(self):
                return list(self._items)

            def first(self):
                return self._items[0] if self._items else None

        return _Scalars(self._items)


class _FakeSession:
    """Minimal AsyncSession stand-in for audit_scheduler DB lookups.

    ``results`` is a FIFO list of iterables — one per ``session.execute``
    call, in the order audit_scheduler invokes them (admin row first,
    then bot configs).
    """

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def execute(self, _query):
        self.calls += 1
        batch = self._results.pop(0) if self._results else []
        return _FakeScalarResult(batch)


def _session_ctx(session):
    """Wrap a _FakeSession as the async contextmanager ``get_session`` yields."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield session

    return _ctx()


@pytest.mark.asyncio
async def test_default_admin_notifier_uses_admin_user_db_config(monkeypatch):
    """DB-configured Discord + Telegram credentials drive notifier dispatch."""
    from src.bot import audit_scheduler as scheduler_module

    session = _FakeSession([
        [_admin_user()],
        [_bot_config_stub(
            discord_webhook_url="enc_webhook",
            telegram_bot_token="enc_token",
            telegram_chat_id="enc_chat",
        )],
    ])

    def fake_get_session():
        return _session_ctx(session)

    def fake_decrypt(ciphertext: str) -> str:
        return {
            "enc_webhook": "https://discord.test/webhook",
            "enc_token": "tg-token-value",
            "enc_chat": "tg-chat-value",
        }[ciphertext]

    monkeypatch.setattr("src.models.session.get_session", fake_get_session)
    monkeypatch.setattr("src.utils.encryption.decrypt_value", fake_decrypt)
    # Env values must NOT leak in when DB wins.
    monkeypatch.setenv("ADMIN_DISCORD_WEBHOOK_URL", "https://env.example/hook")
    monkeypatch.setenv("ADMIN_TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("ADMIN_TELEGRAM_CHAT_ID", "env-chat")

    calls: dict[str, dict] = {}

    class _FakeDiscord:
        def __init__(self, webhook_url: str):
            calls["discord_init"] = {"webhook_url": webhook_url}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_alert(self, **kwargs):
            calls["discord_send"] = kwargs

    class _FakeTelegram:
        def __init__(self, bot_token: str, chat_id: str):
            calls["telegram_init"] = {"bot_token": bot_token, "chat_id": chat_id}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_alert(self, **kwargs):
            calls["telegram_send"] = kwargs

    monkeypatch.setattr(
        "src.notifications.discord_notifier.DiscordNotifier", _FakeDiscord,
    )
    monkeypatch.setattr(
        "src.notifications.telegram_notifier.TelegramNotifier", _FakeTelegram,
    )

    await scheduler_module.default_admin_notifier(
        "synthetic summary", {"findings": [1, 2]},
    )

    assert calls["discord_init"]["webhook_url"] == "https://discord.test/webhook"
    assert calls["telegram_init"] == {
        "bot_token": "tg-token-value",
        "chat_id": "tg-chat-value",
    }
    assert calls["discord_send"]["message"] == "synthetic summary"
    assert calls["telegram_send"]["message"] == "synthetic summary"


@pytest.mark.asyncio
async def test_default_admin_notifier_falls_back_to_env_when_db_empty(monkeypatch):
    """Missing DB admin/bot-config makes the notifier use ADMIN_* env vars."""
    from src.bot import audit_scheduler as scheduler_module

    # No admin row returned → fully empty DB path.
    session = _FakeSession([[]])

    def fake_get_session():
        return _session_ctx(session)

    monkeypatch.setattr("src.models.session.get_session", fake_get_session)
    monkeypatch.setenv("ADMIN_DISCORD_WEBHOOK_URL", "https://env.example/hook")
    monkeypatch.setenv("ADMIN_TELEGRAM_BOT_TOKEN", "env-token")
    monkeypatch.setenv("ADMIN_TELEGRAM_CHAT_ID", "env-chat")

    init_args: dict[str, dict] = {}

    class _FakeDiscord:
        def __init__(self, webhook_url: str):
            init_args["discord"] = {"webhook_url": webhook_url}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_alert(self, **kwargs):
            init_args["discord_sent"] = True

    class _FakeTelegram:
        def __init__(self, bot_token: str, chat_id: str):
            init_args["telegram"] = {"bot_token": bot_token, "chat_id": chat_id}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_alert(self, **kwargs):
            init_args["telegram_sent"] = True

    monkeypatch.setattr(
        "src.notifications.discord_notifier.DiscordNotifier", _FakeDiscord,
    )
    monkeypatch.setattr(
        "src.notifications.telegram_notifier.TelegramNotifier", _FakeTelegram,
    )

    await scheduler_module.default_admin_notifier(
        "env summary", {"findings": []},
    )

    assert init_args["discord"] == {"webhook_url": "https://env.example/hook"}
    assert init_args["telegram"] == {"bot_token": "env-token", "chat_id": "env-chat"}
    assert init_args.get("discord_sent") is True
    assert init_args.get("telegram_sent") is True


@pytest.mark.asyncio
async def test_default_admin_notifier_noop_when_nothing_configured(monkeypatch, caplog):
    """Empty DB and empty env → no notifier constructed, WARN logged."""
    from src.bot import audit_scheduler as scheduler_module

    session = _FakeSession([[]])

    def fake_get_session():
        return _session_ctx(session)

    monkeypatch.setattr("src.models.session.get_session", fake_get_session)
    monkeypatch.delenv("ADMIN_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("ADMIN_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_TELEGRAM_CHAT_ID", raising=False)

    built = {"discord": 0, "telegram": 0}

    class _ExplodingDiscord:
        def __init__(self, *a, **kw):
            built["discord"] += 1
            raise AssertionError("Discord notifier must not be constructed")

    class _ExplodingTelegram:
        def __init__(self, *a, **kw):
            built["telegram"] += 1
            raise AssertionError("Telegram notifier must not be constructed")

    monkeypatch.setattr(
        "src.notifications.discord_notifier.DiscordNotifier", _ExplodingDiscord,
    )
    monkeypatch.setattr(
        "src.notifications.telegram_notifier.TelegramNotifier", _ExplodingTelegram,
    )

    with caplog.at_level("WARNING"):
        await scheduler_module.default_admin_notifier(
            "noop summary", {"findings": [1]},
        )

    assert built == {"discord": 0, "telegram": 0}
    assert any(
        "no admin channels configured" in rec.getMessage()
        for rec in caplog.records
    )
