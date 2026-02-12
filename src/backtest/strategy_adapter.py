"""
Strategy Adapter for Backtesting.

Bridges the gap between the API layer and the existing BacktestEngine.
Wraps BacktestEngine to work with all strategies via a unified interface.
"""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.historical_data import HistoricalDataFetcher
from src.utils.logger import get_logger

logger = get_logger(__name__)


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

    Returns a dict with keys: trades, equity_curve, metrics
    """
    days = (end_date - start_date).days
    if days < 1:
        raise ValueError("Backtest period must be at least 1 day")

    # Fetch historical data
    fetcher = HistoricalDataFetcher()
    data_sources = []
    try:
        data_points = await fetcher.fetch_all_historical_data(days=days)
        data_sources = fetcher.data_sources
    except Exception as e:
        logger.warning(f"Failed to fetch live data, using mock: {e}")
        from src.backtest.mock_data import generate_mock_historical_data
        data_points = generate_mock_historical_data(days=days)
        data_sources = ["Mock Data Generator"]
    finally:
        await fetcher.close()

    # Filter to date range
    filtered = [
        dp for dp in data_points
        if start_date <= dp.timestamp <= end_date
    ]

    if not filtered:
        # If filtering emptied the list, use mock data
        from src.backtest.mock_data import generate_mock_historical_data
        filtered = generate_mock_historical_data(days=days)

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

    # Run engine
    engine = BacktestEngine(config)
    result = engine.run(filtered)

    # Convert trades to serializable dicts
    trades_list = []
    for t in result.trades:
        trades_list.append(t.to_dict())

    # Build equity curve from daily stats
    equity_curve = []
    for stats in result.daily_stats:
        equity_curve.append({
            "timestamp": stats.date,
            "equity": round(stats.ending_balance, 2),
        })

    # Calculate Sharpe ratio from daily returns
    daily_returns = []
    for s in result.daily_stats:
        if s.starting_balance > 0:
            daily_returns.append(s.daily_return_percent / 100)
    sharpe_ratio = _calculate_sharpe(daily_returns)

    metrics = {
        "total_return_percent": round(result.total_return_percent, 2),
        "win_rate": round(result.win_rate, 2),
        "max_drawdown_percent": round(result.max_drawdown_percent, 2),
        "sharpe_ratio": sharpe_ratio,
        "profit_factor": round(result.profit_factor, 2) if result.profit_factor != float('inf') else 999.99,
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

    return {
        "trades": trades_list,
        "equity_curve": equity_curve,
        "metrics": metrics,
    }


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
