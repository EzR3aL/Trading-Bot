"""
Strategy Adapter for Backtesting.

Bridges the gap between the API layer and the backtest engines.
Routes kline-based strategies (Edge Indicator, Claude-Edge) to
KlineBacktestEngine, and data-based strategies to BacktestEngine.

Unified Mode (v3.10.0): Non-LLM data strategies use the LIVE strategy code
with a BacktestMarketDataFetcher, ensuring identical signal generation.
LLM strategies fall back to LEGACY mode with engine-internal signal generators.
"""

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.historical_data import HistoricalDataFetcher
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Strategies that use OHLCV kline data with technical indicators
KLINE_STRATEGIES = {"edge_indicator", "claude_edge_indicator"}

# Strategies that require LLM calls — cannot be unified (non-deterministic)
LLM_STRATEGIES = {"degen", "llm_signal"}

# Interval -> approximate number of bars/candles per day
BARS_PER_DAY = {
    "1m": 1440,
    "5m": 288,
    "15m": 96,
    "30m": 48,
    "1h": 24,
    "4h": 6,
    "1d": 1,
}
CANDLES_PER_DAY = BARS_PER_DAY


async def run_backtest_for_strategy(
    strategy_type: str,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    strategy_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run a backtest for any registered strategy.

    Kline strategies (Edge Indicator, Claude-Edge) use KlineBacktestEngine.
    Non-LLM data strategies use UNIFIED mode with live strategy code.
    LLM strategies fall back to LEGACY mode with engine-internal signal generators.

    Returns a dict with keys: trades, equity_curve, metrics
    """
    days = (end_date - start_date).days
    if days < 1:
        raise ValueError("Backtest period must be at least 1 day")

    if strategy_type in KLINE_STRATEGIES:
        return await _run_kline_backtest(
            strategy_type, symbol, timeframe, start_date, end_date,
            initial_capital, days, strategy_params,
        )

    return await _run_data_backtest(
        strategy_type, symbol, timeframe, start_date, end_date,
        initial_capital, days, strategy_params,
    )


# ------------------------------------------------------------------ #
#  KLINE-BASED BACKTEST (Edge Indicator, Claude-Edge)                 #
# ------------------------------------------------------------------ #

async def _run_kline_backtest(
    strategy_type: str,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    days: int,
    strategy_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run backtest using KlineBacktestEngine with actual strategy indicators."""
    from src.backtest.kline_backtest_engine import KlineBacktestEngine, KlineBacktestConfig
    from src.data.market_data import MarketDataFetcher
    from src.strategy import StrategyRegistry

    strategy_cls = StrategyRegistry.get(strategy_type)
    interval = timeframe if timeframe in BARS_PER_DAY else "1h"

    # Calculate how many klines we need (data period + lookback buffer)
    lookback = 200
    bars_per_day = BARS_PER_DAY.get(interval, 24)
    data_bars = days * bars_per_day
    total_bars_needed = data_bars + lookback

    # Binance allows max 1000 per request; paginate if needed
    fetcher = MarketDataFetcher()
    pair = symbol if symbol.endswith("USDT") else symbol + "USDT"
    data_sources = []

    try:
        klines = await _fetch_klines_paginated(fetcher, pair, interval, total_bars_needed, end_date)
        if klines:
            data_sources.append(f"Binance Futures ({interval} klines)")
    except Exception as e:
        logger.warning(f"Failed to fetch klines: {e}")
        klines = []

    if not klines or len(klines) < lookback + 10:
        # Fallback: fetch from HistoricalDataFetcher
        hist_fetcher = HistoricalDataFetcher()
        try:
            klines = await hist_fetcher.fetch_klines_history(pair, interval, days + 30)
            if klines:
                # Convert dict format to list format [ts, open, high, low, close, volume]
                klines = [
                    [k["timestamp"] * 1000, k["open"], k["high"], k["low"], k["close"], k.get("volume", 0)]
                    for k in klines
                ]
                data_sources = [f"Binance Futures ({interval} klines, fallback)"]
        except Exception as e:
            logger.warning(f"Fallback kline fetch also failed: {e}")
            klines = []
        finally:
            await hist_fetcher.close()

    if not klines or len(klines) < lookback + 10:
        raise ValueError(
            f"Not enough kline data for backtest. Got {len(klines)} bars, "
            f"need at least {lookback + 10}. Try a shorter period or 1d interval."
        )

    # Build config
    config = KlineBacktestConfig(starting_capital=initial_capital)
    if strategy_params:
        for key in ("leverage", "position_size_percent", "trading_fee_percent",
                     "max_bars_in_trade", "cooldown_bars", "min_confidence"):
            if key in strategy_params:
                setattr(config, key, strategy_params[key])

    # Run engine with the actual strategy class
    engine = KlineBacktestEngine(config)
    result = engine.run(klines, strategy_cls, strategy_params, interval, lookback)

    # Convert KlineTrade list to the common API format
    trades_list = []
    for t in result.trades:
        entry_ts = _bar_to_date(klines, t.entry_bar)
        exit_ts = _bar_to_date(klines, t.exit_bar) if t.exit_bar is not None else None
        trades_list.append({
            "entry_date": entry_ts,
            "exit_date": exit_ts or entry_ts,
            "direction": t.direction,
            "entry_price": round(t.entry_price, 2),
            "exit_price": round(t.exit_price, 2) if t.exit_price else t.entry_price,
            "position_value": round(t.position_value, 2),
            "pnl": round(t.pnl, 2),
            "pnl_percent": round(t.pnl_percent, 2),
            "fees": round(t.fees, 2),
            "net_pnl": round(t.net_pnl, 2),
            "result": t.result.value if t.result else "open",
            "reason": t.reason,
            "confidence": t.confidence,
        })

    # Build equity curve
    equity_curve = []
    if result.equity_curve:
        # Sample equity curve at regular intervals for readability
        step = max(1, len(result.equity_curve) // days) if days > 0 else 1
        for idx in range(0, len(result.equity_curve), step):
            ts = _bar_to_date(klines, lookback + idx) if (lookback + idx) < len(klines) else ""
            equity_curve.append({
                "timestamp": ts,
                "equity": round(result.equity_curve[idx], 2),
            })

    # Build metrics
    pf = result.profit_factor
    if pf == float("inf") or pf > 999:
        pf = 999.99

    metrics = {
        "total_return_percent": round(result.total_return_percent, 2),
        "win_rate": round(result.win_rate, 2),
        "max_drawdown_percent": round(result.max_drawdown_percent, 2),
        "sharpe_ratio": round(result.sharpe_ratio, 2) if result.sharpe_ratio else None,
        "profit_factor": round(pf, 2),
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "average_win": round(result.average_win, 2),
        "average_loss": round(result.average_loss, 2),
        "total_pnl": round(result.total_pnl, 2),
        "total_fees": round(result.total_fees, 2),
        "starting_capital": result.starting_capital,
        "ending_capital": round(result.ending_capital, 2),
        "data_sources": data_sources,
    }

    return {"trades": trades_list, "equity_curve": equity_curve, "metrics": metrics}


def _bar_to_date(klines: List[List], bar_idx: int) -> str:
    """Convert a bar index to a date string."""
    if 0 <= bar_idx < len(klines):
        try:
            ts = int(klines[bar_idx][0])
            # Binance timestamps are in ms
            if ts > 1e12:
                ts = ts // 1000
            return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except (IndexError, ValueError, TypeError):
            pass
    return ""


async def _fetch_klines_paginated(
    fetcher, symbol: str, interval: str, total_needed: int, end_date: datetime
) -> List[List]:
    """Fetch klines from Binance with pagination for large requests."""
    all_klines: List[List] = []
    batch_size = 1000
    end_ms = int(end_date.timestamp() * 1000)

    remaining = total_needed
    current_end = end_ms

    while remaining > 0:
        limit = min(remaining, batch_size)
        try:
            url = "https://fapi.binance.com/fapi/v1/klines"
            import aiohttp
            params = {
                "symbol": symbol,
                "interval": interval,
                "endTime": current_end,
                "limit": limit,
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning(f"Binance klines returned {resp.status}")
                        break
                    data = await resp.json()

            if not data or not isinstance(data, list):
                break

            all_klines = data + all_klines  # prepend older data
            remaining -= len(data)

            if len(data) < limit:
                break  # no more data available

            # Move end time before the earliest fetched candle
            current_end = int(data[0][0]) - 1

        except Exception as e:
            logger.warning(f"Kline pagination error: {e}")
            break

    return all_klines


# ------------------------------------------------------------------ #
#  DATA-BASED BACKTEST (Liquidation Hunter, Sentiment, LLM, Degen)   #
# ------------------------------------------------------------------ #

async def _run_data_backtest(
    strategy_type: str,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    days: int,
    strategy_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run backtest using BacktestEngine with multi-source indicator data."""
    # Warmup buffer: extra days so indicators have enough candles to initialize
    cpd = CANDLES_PER_DAY.get(timeframe, 1)
    min_warmup_candles = 50
    warmup_days = math.ceil(min_warmup_candles / cpd) + 1
    fetch_days = days + warmup_days

    # Compute adjusted date range including warmup buffer
    fetch_start = start_date - timedelta(days=warmup_days)
    fetch_end = end_date

    # Fetch historical data with correct interval and date range
    fetcher = HistoricalDataFetcher()
    data_sources = []
    try:
        data_points = await fetcher.fetch_all_historical_data(
            days=fetch_days,
            interval=timeframe,
            start_date=fetch_start,
            end_date=fetch_end,
        )
        data_sources = fetcher.data_sources
    except Exception as e:
        logger.warning(f"Failed to fetch live data, using mock: {e}")
        from src.backtest.mock_data import generate_mock_historical_data
        data_points = generate_mock_historical_data(days=fetch_days, interval=timeframe)
        data_sources = ["Mock Data Generator"]
    finally:
        await fetcher.close()

    if not data_points:
        from src.backtest.mock_data import generate_mock_historical_data
        data_points = generate_mock_historical_data(days=fetch_days, interval=timeframe)

    # Build config with strategy-specific defaults
    config = _build_strategy_config(strategy_type, initial_capital)
    if strategy_params:
        config_keys = [
            "leverage", "take_profit_percent", "stop_loss_percent",
            "max_trades_per_day", "position_size_percent",
            "daily_loss_limit_percent", "fear_greed_extreme_fear",
            "fear_greed_extreme_greed", "long_short_crowded_longs",
            "long_short_crowded_shorts", "funding_rate_high",
            "funding_rate_low", "high_confidence_min", "low_confidence_min",
        ]
        for key in config_keys:
            if key in strategy_params:
                setattr(config, key, strategy_params[key])

    # Map symbol (e.g. "BTCUSDT" → "BTC") for the engine
    engine_symbol = symbol.replace("USDT", "").replace("USDC", "")

    engine = BacktestEngine(config, strategy_type=strategy_type, symbol=engine_symbol)

    if strategy_type in LLM_STRATEGIES:
        # LEGACY MODE: Engine-internal signal generators (rule-based proxy)
        logger.info(f"Running LEGACY backtest for {strategy_type}")
        result = engine.run(data_points)
    else:
        # UNIFIED MODE: Live strategy code + BacktestMarketDataFetcher
        logger.info(f"Running UNIFIED backtest for {strategy_type} on {timeframe}")
        result = await _run_unified_backtest(
            engine, data_points, strategy_type, engine_symbol,
            timeframe, strategy_params,
        )

    # Filter trades to user-requested date range (exclude warmup trades)
    start_str = start_date.strftime("%Y-%m-%d")
    filtered_trades = [t for t in result.trades if t.entry_date >= start_str]
    trades_list = [t.to_dict() for t in filtered_trades]

    # Recalculate ALL metrics from filtered trades only
    total_trades = len(filtered_trades)
    wins = [t for t in filtered_trades if t.pnl > 0]
    losses = [t for t in filtered_trades if t.pnl <= 0 and t.exit_date is not None]
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    total_pnl = sum(t.net_pnl for t in filtered_trades)
    total_fees = sum(t.fees for t in filtered_trades)
    ending_capital = initial_capital + total_pnl
    total_return_pct = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0

    total_win_pnl = sum(t.pnl for t in wins)
    total_loss_pnl = abs(sum(t.pnl for t in losses))
    if total_loss_pnl > 0:
        profit_factor = round(total_win_pnl / total_loss_pnl, 2)
    elif total_win_pnl > 0:
        profit_factor = 999.99
    else:
        profit_factor = 0.0

    average_win = round(total_win_pnl / winning_trades, 2) if winning_trades > 0 else 0
    average_loss = round(sum(t.pnl for t in losses) / losing_trades, 2) if losing_trades > 0 else 0

    # Max drawdown and equity curve from filtered trades
    peak = initial_capital
    max_dd = 0.0
    balance = initial_capital
    daily_pnl: Dict[str, float] = {}
    for t in filtered_trades:
        balance += t.net_pnl
        peak = max(peak, balance)
        dd = (peak - balance) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
        # Aggregate PnL by date for equity curve
        trade_date = t.exit_date or t.entry_date
        daily_pnl[trade_date] = daily_pnl.get(trade_date, 0) + t.net_pnl

    # Build equity curve: one point per day with cumulative balance
    equity_curve = [{"timestamp": start_str, "equity": round(initial_capital, 2)}]
    cumulative = initial_capital
    for date_key in sorted(daily_pnl.keys()):
        cumulative += daily_pnl[date_key]
        equity_curve.append({"timestamp": date_key, "equity": round(cumulative, 2)})

    # Sharpe ratio from daily PnL within user period
    daily_returns = []
    for pnl_val in daily_pnl.values():
        if initial_capital > 0:
            daily_returns.append(pnl_val / initial_capital)
    sharpe_ratio = _calculate_sharpe(daily_returns)

    metrics = {
        "total_return_percent": round(total_return_pct, 2),
        "win_rate": round(win_rate, 2),
        "max_drawdown_percent": round(max_dd, 2),
        "sharpe_ratio": sharpe_ratio,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "average_win": average_win,
        "average_loss": average_loss,
        "total_pnl": round(total_pnl, 2),
        "total_fees": round(total_fees, 2),
        "starting_capital": initial_capital,
        "ending_capital": round(ending_capital, 2),
        "data_sources": data_sources,
    }

    return {
        "trades": trades_list,
        "equity_curve": equity_curve,
        "metrics": metrics,
    }


def _build_strategy_config(strategy_type: str, initial_capital: float) -> BacktestConfig:
    """Build a BacktestConfig with strategy-specific defaults."""
    base = dict(starting_capital=initial_capital, strategy_type=strategy_type)

    if strategy_type == "liquidation_hunter":
        return BacktestConfig(
            **base,
            take_profit_percent=4.0,
            stop_loss_percent=1.5,
            max_trades_per_day=2,
            fear_greed_extreme_fear=20,
            fear_greed_extreme_greed=80,
            long_short_crowded_longs=2.5,
            long_short_crowded_shorts=0.4,
            high_confidence_min=85,
            low_confidence_min=60,
        )

    if strategy_type == "sentiment_surfer":
        return BacktestConfig(
            **base,
            take_profit_percent=3.5,
            stop_loss_percent=1.5,
            max_trades_per_day=2,
            fear_greed_extreme_fear=25,
            fear_greed_extreme_greed=75,
            low_confidence_min=40,
        )

    if strategy_type == "llm_signal":
        return BacktestConfig(
            **base,
            take_profit_percent=4.0,
            stop_loss_percent=2.0,
            max_trades_per_day=1,
            low_confidence_min=55,
            position_size_percent=8.0,
        )

    if strategy_type == "degen":
        return BacktestConfig(
            **base,
            take_profit_percent=5.0,
            stop_loss_percent=3.0,
            max_trades_per_day=3,
            leverage=5,
            position_size_percent=15.0,
            low_confidence_min=50,
        )

    # Fallback: generic config
    return BacktestConfig(**base)


async def _run_unified_backtest(
    engine: BacktestEngine,
    data_points,
    strategy_type: str,
    engine_symbol: str,
    timeframe: str,
    strategy_params: Optional[Dict[str, Any]],
) -> "BacktestResult":
    """Create a live strategy instance with BacktestMarketDataFetcher and run unified backtest."""
    from src.backtest.backtest_data_provider import BacktestMarketDataFetcher
    from src.backtest.execution_simulator import ExecutionSimulator
    from src.strategy.base import StrategyRegistry

    mock_fetcher = BacktestMarketDataFetcher()

    # Build strategy params: sync kline_interval to backtest timeframe
    params = dict(strategy_params or {})
    params["kline_interval"] = timeframe
    params["kline_count"] = 200

    # Create ExecutionSimulator with exchange-specific cost model
    exchange = (strategy_params or {}).get("exchange", "bitget")
    fee_tier = (strategy_params or {}).get("fee_tier", "standard")
    engine.execution_simulator = ExecutionSimulator(
        exchange=exchange,
        fee_tier=fee_tier,
    )

    # Create live strategy instance with mock data fetcher
    strategy_class = StrategyRegistry.get(strategy_type)

    # ClaudeEdgeIndicator accepts backtest_mode for sync HTF alignment
    kwargs = {"params": params, "data_fetcher": mock_fetcher}
    if strategy_type == "claude_edge_indicator":
        kwargs["backtest_mode"] = True

    strategy = strategy_class(**kwargs)

    try:
        result = await engine.run_unified(data_points, strategy, mock_fetcher, interval=timeframe)
    finally:
        await strategy.close()

    return result


def _calculate_sharpe(daily_returns: List[float], risk_free_rate: float = 0.0) -> Optional[float]:
    """Calculate annualized Sharpe ratio from daily returns."""
    if len(daily_returns) < 2:
        return None
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std = math.sqrt(variance) if variance > 0 else 0
    if std == 0:
        return None
    sharpe = (mean - risk_free_rate / 365) / std * math.sqrt(365)
    return round(sharpe, 2)
