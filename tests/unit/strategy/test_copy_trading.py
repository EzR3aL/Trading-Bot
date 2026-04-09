"""Tests for CopyTradingStrategy."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.strategy.copy_trading import CopyTradingStrategy
from src.exchanges.hyperliquid.wallet_tracker import SourceFill


def _make_ctx(bot_config, exchange_client, executor=None, notifier=None):
    """Build a minimal StrategyTickContext for tests."""
    from src.strategy.base import StrategyTickContext
    return StrategyTickContext(
        bot_config=bot_config,
        user_id=1,
        exchange_client=exchange_client,
        trade_executor=executor or MagicMock(),
        send_notification=notifier or AsyncMock(),
        logger=MagicMock(),
        bot_config_id=99,
    )


def _params(**overrides):
    base = {
        "source_wallet": "0x" + "ab" * 20,
        "budget_usdt": 1000.0,
        "max_slots": 5,
        "leverage": None,
        "symbol_whitelist": "",
        "symbol_blacklist": "",
        "min_position_size_usdt": 10.0,
        "take_profit_pct": None,
        "stop_loss_pct": None,
        "daily_loss_limit_pct": None,
        "max_trades_per_day": None,
    }
    base.update(overrides)
    return base


def _bot_config(strategy_state=None, exchange="bitget"):
    cfg = MagicMock()
    cfg.id = 99
    cfg.exchange_type = exchange
    cfg.user_id = 1
    cfg.strategy_state = json.dumps(strategy_state) if strategy_state else None
    return cfg


def test_is_self_managed_flag():
    s = CopyTradingStrategy(_params())
    assert s.is_self_managed is True


def test_param_schema_keys():
    schema = CopyTradingStrategy.get_param_schema()
    for key in ("source_wallet", "budget_usdt", "max_slots", "leverage",
                "symbol_whitelist", "symbol_blacklist",
                "min_position_size_usdt", "take_profit_pct", "stop_loss_pct",
                "daily_loss_limit_pct", "max_trades_per_day"):
        assert key in schema
    assert "copy_tp_sl" not in schema


@pytest.mark.asyncio
async def test_run_tick_skips_when_no_new_fills(monkeypatch):
    s = CopyTradingStrategy(_params())
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=[])
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr(
        "src.strategy.copy_trading.HyperliquidWalletTracker",
        lambda: tracker,
    )
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    ctx = _make_ctx(cfg, exchange_client=MagicMock())
    await s.run_tick(ctx)
    ctx.trade_executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_dispatches_entry_signal(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)

    monkeypatch.setattr(
        "src.strategy.copy_trading.get_exchange_symbols",
        AsyncMock(return_value=["BTCUSDT"]),
    )
    monkeypatch.setattr(
        "src.strategy.copy_trading.to_exchange_symbol",
        lambda coin, ex: "BTCUSDT" if coin == "BTC" else None,
    )

    s = CopyTradingStrategy(_params(budget_usdt=1000, max_slots=5))
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)

    executor.execute_trade.assert_called_once()
    call = executor.execute_trade.call_args
    assert call.kwargs["symbol"] == "BTCUSDT"
    assert call.kwargs["side"] == "long"
    assert abs(call.kwargs["notional_usdt"] - 200.0) < 0.01


@pytest.mark.asyncio
async def test_run_tick_skips_blacklisted_symbol(monkeypatch):
    fills = [SourceFill(coin="HYPE", side="long", size=10, price=12,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)

    s = CopyTradingStrategy(_params(symbol_blacklist="HYPE,PURR"))
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)
    executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_skips_when_slots_exhausted(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    monkeypatch.setattr("src.strategy.copy_trading.get_exchange_symbols", AsyncMock(return_value=["BTCUSDT"]))
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")

    s = CopyTradingStrategy(_params(max_slots=2))
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=2)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)
    executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_advances_watermark_after_processing(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=5000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    monkeypatch.setattr("src.strategy.copy_trading.get_exchange_symbols", AsyncMock(return_value=["BTCUSDT"]))
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")
    save_state = MagicMock()
    monkeypatch.setattr("src.strategy.copy_trading._save_strategy_state", save_state)

    s = CopyTradingStrategy(_params())
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)

    save_state.assert_called_once()
    saved_state = save_state.call_args.args[1]
    assert saved_state["last_processed_fill_ms"] == 5000


@pytest.mark.asyncio
async def test_cold_start_initializes_watermark_to_now(monkeypatch):
    """First tick after start: strategy_state is None -> set to now, skip all existing fills."""
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=1000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    save_state = MagicMock()
    monkeypatch.setattr("src.strategy.copy_trading._save_strategy_state", save_state)

    s = CopyTradingStrategy(_params())
    cfg = _bot_config(strategy_state=None)  # cold start
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)

    executor.execute_trade.assert_not_called()
    save_state.assert_called()


@pytest.mark.asyncio
async def test_run_tick_exits_when_source_closed_position(monkeypatch):
    """Source no longer holds a position -> close any open copies of it."""
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=[])
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)

    s = CopyTradingStrategy(_params())
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    open_trade = MagicMock()
    open_trade.symbol = "BTCUSDT"
    open_trade.side = "long"
    open_trade.id = 7
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_for_bot = AsyncMock(return_value=[open_trade])
    executor.close_trade_by_strategy = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=1)
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")

    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)
    executor.close_trade_by_strategy.assert_called_once_with(open_trade, reason="COPY_SOURCE_CLOSED")


@pytest.mark.asyncio
async def test_run_tick_skips_when_daily_loss_limit_hit(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    monkeypatch.setattr("src.strategy.copy_trading.get_exchange_symbols", AsyncMock(return_value=["BTCUSDT"]))
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")

    s = CopyTradingStrategy(_params(budget_usdt=1000, daily_loss_limit_pct=5.0))
    # -60 USDT on a 1000 USDT budget = 6% drawdown > 5% limit
    monkeypatch.setattr(
        CopyTradingStrategy, "_get_today_realized_pnl",
        AsyncMock(return_value=-60.0),
    )
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)
    executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_run_tick_skips_when_max_trades_per_day_hit(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    monkeypatch.setattr("src.strategy.copy_trading.get_exchange_symbols", AsyncMock(return_value=["BTCUSDT"]))
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")

    s = CopyTradingStrategy(_params(max_trades_per_day=3))
    monkeypatch.setattr(
        CopyTradingStrategy, "_get_today_entry_count",
        AsyncMock(return_value=3),
    )
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)
    executor.execute_trade.assert_not_called()


@pytest.mark.asyncio
async def test_tp_sl_override_passed_to_executor(monkeypatch):
    fills = [SourceFill(coin="BTC", side="long", size=0.5, price=67000,
                        time_ms=2000, is_entry=True, hash="0xa")]
    tracker = MagicMock()
    tracker.get_fills_since = AsyncMock(return_value=fills)
    tracker.get_open_positions = AsyncMock(return_value=[])
    tracker.close = AsyncMock()
    monkeypatch.setattr("src.strategy.copy_trading.HyperliquidWalletTracker", lambda: tracker)
    monkeypatch.setattr("src.strategy.copy_trading.get_exchange_symbols", AsyncMock(return_value=["BTCUSDT"]))
    monkeypatch.setattr("src.strategy.copy_trading.to_exchange_symbol", lambda c, e: "BTCUSDT")

    s = CopyTradingStrategy(_params(take_profit_pct=2.5, stop_loss_pct=1.5))
    cfg = _bot_config(strategy_state={"last_processed_fill_ms": 1000})
    executor = MagicMock()
    executor.execute_trade = AsyncMock()
    executor.get_open_trades_count = AsyncMock(return_value=0)
    ctx = _make_ctx(cfg, exchange_client=MagicMock(), executor=executor)
    await s.run_tick(ctx)

    executor.execute_trade.assert_called_once()
    kwargs = executor.execute_trade.call_args.kwargs
    assert kwargs["take_profit_pct"] == 2.5
    assert kwargs["stop_loss_pct"] == 1.5
