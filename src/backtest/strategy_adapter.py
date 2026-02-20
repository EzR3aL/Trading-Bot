"""
Strategy Adapter for Backtesting.

Bridges the gap between the API layer and the existing BacktestEngine.
Wraps BacktestEngine to work with all strategies via a unified interface.

Unified Mode (v3.10.0): Non-LLM strategies use the LIVE strategy code
with a BacktestMarketDataFetcher, ensuring identical signal generation.
"""

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.historical_data import HistoricalDataFetcher
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Candles per day for each supported interval
CANDLES_PER_DAY = {"1m": 1440, "5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6, "1d": 1}

# Strategies that require LLM calls — cannot be unified (non-deterministic)
LLM_STRATEGIES = {"degen", "llm_signal"}


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

    For non-LLM strategies, uses UNIFIED mode: the live strategy code runs
    with a BacktestMarketDataFetcher that returns historical data in API format.
    For LLM strategies, falls back to LEGACY mode with engine-internal signal generators.

    Returns a dict with keys: trades, equity_curve, metrics
    """
    days = (end_date - start_date).days
    if days < 1:
        raise ValueError("Backtest period must be at least 1 day")

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

    # Build config from strategy_params
    config = BacktestConfig(starting_capital=initial_capital)
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
