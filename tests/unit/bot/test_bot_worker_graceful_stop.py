"""Characterization tests for ``BotWorker.graceful_stop()``.

Part of ARCH-H1 Phase 0 PR-2 (#270). These tests freeze the current
observable behaviour of ``graceful_stop`` so the upcoming mixin-extraction
refactor (see ``Anleitungen/refactor_plan_bot_worker_composition.md``)
has a safety net before production code is touched.

Scope: ``graceful_stop`` only — no other BotWorker methods, no production
changes. Each test has a single clear behaviour per the refactor plan's
test-discipline gate.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.bot.bot_worker import BotWorker
from src.models.enums import BotStatus


def _make_trade_record(
    symbol="BTCUSDT",
    side="long",
    size=0.01,
    entry_price=95_000.0,
    demo_mode=True,
    take_profit=None,
    stop_loss=None,
):
    """Build a TradeRecord-shaped MagicMock for the DB query result.

    Characterization intent: ``graceful_stop`` only reads the 7 attributes
    below from each row (lines 585-593 in bot_worker.py). If the production
    code starts reading additional attributes, these tests will fail and
    force a review.
    """
    rec = MagicMock()
    rec.symbol = symbol
    rec.side = side
    rec.size = size
    rec.entry_price = entry_price
    rec.demo_mode = demo_mode
    rec.take_profit = take_profit
    rec.stop_loss = stop_loss
    return rec


def _mock_session_with_trades(trades):
    """Build an async-context-manager session whose query returns ``trades``."""
    scalars_result = MagicMock()
    scalars_result.all.return_value = list(trades)

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result

    session = AsyncMock()
    session.execute = AsyncMock(return_value=execute_result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _mock_session_that_raises(exc: Exception):
    """Session whose ``execute`` raises — used for the DB-failure branch."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=exc)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _prime_worker(worker, *, demo=None, live=None):
    """Wire minimal deps so graceful_stop can run without touching the real world.

    - Replaces ``worker.stop`` with an AsyncMock so the final delegation is
      observable and does not cascade into scheduler/strategy cleanup.
    - Leaves ``_operation_in_progress`` in its default SET state (idle).
    """
    worker.stop = AsyncMock()
    worker._demo_client = demo
    worker._live_client = live
    return worker


@pytest.mark.asyncio
class TestGracefulStop:
    """Characterization — freezes current graceful_stop behaviour."""

    async def test_sets_shutting_down_flag_before_awaiting(self):
        """_shutting_down must flip True to block new trades (line 538)."""
        worker = BotWorker(bot_config_id=42)
        _prime_worker(worker)

        session = _mock_session_with_trades([])

        assert worker._shutting_down is False
        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            await worker.graceful_stop(grace_period=0.05)

        assert worker._shutting_down is True

    async def test_delegates_to_stop_at_end(self):
        """self.stop() must always be called, regardless of branch."""
        worker = BotWorker(bot_config_id=1)
        _prime_worker(worker)
        session = _mock_session_with_trades([])

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            await worker.graceful_stop(grace_period=0.05)

        worker.stop.assert_awaited_once()

    async def test_returns_open_positions_with_expected_shape(self):
        """Happy path: DB rows are projected to the documented 7-key dict."""
        worker = BotWorker(bot_config_id=7)
        _prime_worker(worker)
        trades = [
            _make_trade_record(
                symbol="BTCUSDT", side="long", size=0.5,
                entry_price=95_000.0, demo_mode=True,
                take_profit=97_000.0, stop_loss=94_000.0,
            ),
            _make_trade_record(
                symbol="ETHUSDT", side="short", size=1.2,
                entry_price=3_200.0, demo_mode=False,
                take_profit=None, stop_loss=None,
            ),
        ]
        session = _mock_session_with_trades(trades)

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            result = await worker.graceful_stop(grace_period=0.05)

        assert len(result) == 2
        assert result[0] == {
            "symbol": "BTCUSDT",
            "side": "long",
            "size": 0.5,
            "entry_price": 95_000.0,
            "demo_mode": True,
            "has_tp": True,
            "has_sl": True,
        }
        assert result[1] == {
            "symbol": "ETHUSDT",
            "side": "short",
            "size": 1.2,
            "entry_price": 3_200.0,
            "demo_mode": False,
            "has_tp": False,
            "has_sl": False,
        }

    async def test_returns_empty_list_when_no_open_trades(self):
        """No rows in DB → empty list return, stop() still called."""
        worker = BotWorker(bot_config_id=1)
        _prime_worker(worker)
        session = _mock_session_with_trades([])

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            result = await worker.graceful_stop(grace_period=0.05)

        assert result == []
        worker.stop.assert_awaited_once()

    async def test_happy_path_in_flight_wait_completes(self):
        """When _operation_in_progress is already SET, wait returns immediately."""
        worker = BotWorker(bot_config_id=1)
        _prime_worker(worker)
        # Default state: event is set (idle) — wait() completes instantly.
        session = _mock_session_with_trades([])

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            # Even with a short grace period this completes fast.
            await asyncio.wait_for(
                worker.graceful_stop(grace_period=5.0),
                timeout=1.0,
            )

        worker.stop.assert_awaited_once()

    async def test_timeout_path_when_operation_stays_in_progress(self):
        """When _operation_in_progress stays CLEARED, wait times out but
        graceful_stop still continues, queries DB, and calls stop()."""
        worker = BotWorker(bot_config_id=1)
        _prime_worker(worker)
        worker._operation_in_progress.clear()  # Simulate in-flight trade
        session = _mock_session_with_trades([
            _make_trade_record(symbol="SOLUSDT"),
        ])

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            result = await worker.graceful_stop(grace_period=0.05)

        # Despite the timeout, downstream work still happened.
        assert len(result) == 1
        assert result[0]["symbol"] == "SOLUSDT"
        worker.stop.assert_awaited_once()

    async def test_swallows_db_query_exception_and_still_stops(self):
        """DB failure during the open-positions query must not propagate —
        graceful_stop returns [] and still calls stop()."""
        worker = BotWorker(bot_config_id=1)
        _prime_worker(worker)
        session = _mock_session_that_raises(RuntimeError("DB down"))

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            result = await worker.graceful_stop(grace_period=0.05)

        assert result == []
        worker.stop.assert_awaited_once()

    async def test_swallows_client_exception_and_still_returns_db_positions(self):
        """If a client.get_open_positions() raises, graceful_stop logs and
        keeps going — DB-sourced positions are still returned."""
        demo = AsyncMock()
        demo.get_open_positions = AsyncMock(side_effect=RuntimeError("exchange 500"))
        live = AsyncMock()
        live.get_open_positions = AsyncMock(side_effect=RuntimeError("exchange 500"))

        worker = BotWorker(bot_config_id=1)
        _prime_worker(worker, demo=demo, live=live)
        session = _mock_session_with_trades([
            _make_trade_record(symbol="BTCUSDT", demo_mode=True),
        ])

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            result = await worker.graceful_stop(grace_period=0.05)

        demo.get_open_positions.assert_awaited_once()
        live.get_open_positions.assert_awaited_once()
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"
        worker.stop.assert_awaited_once()

    async def test_queries_clients_when_present(self):
        """Both demo and live clients are polled for open positions when set."""
        demo = AsyncMock()
        demo.get_open_positions = AsyncMock(return_value=[])
        live = AsyncMock()
        live.get_open_positions = AsyncMock(return_value=[])

        worker = BotWorker(bot_config_id=1)
        _prime_worker(worker, demo=demo, live=live)
        session = _mock_session_with_trades([])

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            await worker.graceful_stop(grace_period=0.05)

        demo.get_open_positions.assert_awaited_once()
        live.get_open_positions.assert_awaited_once()

    async def test_skips_missing_clients(self):
        """When demo/live clients are None, no exchange calls happen —
        but the DB query and stop() still run."""
        worker = BotWorker(bot_config_id=1)
        _prime_worker(worker, demo=None, live=None)
        session = _mock_session_with_trades([])

        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            result = await worker.graceful_stop(grace_period=0.05)

        assert result == []
        worker.stop.assert_awaited_once()

    async def test_status_transitions_to_stopped_via_stop(self):
        """After graceful_stop, status reflects stop()'s contract.

        ``graceful_stop`` itself does not set STOPPED — it delegates to
        ``stop()``. This test freezes that delegation: if the refactor
        breaks the hand-off, the assertion will fail.
        """
        worker = BotWorker(bot_config_id=1)
        worker.status = BotStatus.RUNNING
        # Real stop() would flip to STOPPED — simulate that as part of the
        # contract we're freezing.
        async def _fake_stop():
            worker.status = BotStatus.STOPPED
        worker.stop = AsyncMock(side_effect=_fake_stop)

        session = _mock_session_with_trades([])
        with patch("src.bot._lifecycle_mixin.get_session", return_value=session):
            await worker.graceful_stop(grace_period=0.05)

        assert worker.status == BotStatus.STOPPED
        worker.stop.assert_awaited_once()
