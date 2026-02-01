"""
Backtest Report Generator.

Generates comprehensive reports from backtest results including:
- Performance metrics
- Trade analysis
- Monthly breakdown
- Recommendations
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BacktestResult:
    """Complete backtest result with all metrics."""

    # Period
    start_date: str
    end_date: str

    # Capital
    starting_capital: float
    ending_capital: float
    total_return_percent: float
    max_drawdown_percent: float

    # Trade Statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float

    # Costs
    total_pnl: float
    total_fees: float
    total_funding: float

    # Breakdowns
    monthly_returns: Dict[str, float] = field(default_factory=dict)
    trades: List[Any] = field(default_factory=list)
    daily_stats: List[Any] = field(default_factory=list)
    config: Any = None

    @classmethod
    def empty(cls) -> "BacktestResult":
        """Create empty result."""
        return cls(
            start_date="",
            end_date="",
            starting_capital=0,
            ending_capital=0,
            total_return_percent=0,
            max_drawdown_percent=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0,
            average_win=0,
            average_loss=0,
            profit_factor=0,
            total_pnl=0,
            total_fees=0,
            total_funding=0,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excluding large lists)."""
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "starting_capital": self.starting_capital,
            "ending_capital": self.ending_capital,
            "total_return_percent": self.total_return_percent,
            "max_drawdown_percent": self.max_drawdown_percent,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "average_win": self.average_win,
            "average_loss": self.average_loss,
            "profit_factor": self.profit_factor,
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "total_funding": self.total_funding,
            "monthly_returns": self.monthly_returns,
        }


class BacktestReport:
    """Generates reports from backtest results."""

    def __init__(self, result: BacktestResult):
        """Initialize with backtest result."""
        self.result = result

    def generate_console_report(self) -> str:
        """Generate a text report for console output."""
        r = self.result

        # Header
        lines = [
            "",
            "=" * 70,
            "BACKTEST REPORT - Contrarian Liquidation Hunter",
            "=" * 70,
            "",
            f"Period: {r.start_date} to {r.end_date}",
            f"Duration: {self._calculate_days()} days",
            "",
            "-" * 70,
            "PERFORMANCE SUMMARY",
            "-" * 70,
            "",
            f"Starting Capital:    ${r.starting_capital:>12,.2f}",
            f"Ending Capital:      ${r.ending_capital:>12,.2f}",
            f"Total P&L:           ${r.total_pnl:>12,.2f}",
            f"Total Return:        {r.total_return_percent:>12.2f}%",
            f"Max Drawdown:        {r.max_drawdown_percent:>12.2f}%",
            "",
            "-" * 70,
            "TRADE STATISTICS",
            "-" * 70,
            "",
            f"Total Trades:        {r.total_trades:>12}",
            f"Winning Trades:      {r.winning_trades:>12}",
            f"Losing Trades:       {r.losing_trades:>12}",
            f"Win Rate:            {r.win_rate:>12.2f}%",
            "",
            f"Average Win:         ${r.average_win:>12,.2f}",
            f"Average Loss:        ${r.average_loss:>12,.2f}",
            f"Profit Factor:       {r.profit_factor:>12.2f}",
            "",
            "-" * 70,
            "COSTS",
            "-" * 70,
            "",
            f"Trading Fees:        ${r.total_fees:>12,.2f}",
            f"Funding Paid:        ${r.total_funding:>12,.2f}",
            f"Total Costs:         ${r.total_fees + r.total_funding:>12,.2f}",
            "",
        ]

        # Monthly breakdown
        if r.monthly_returns:
            lines.extend([
                "-" * 70,
                "MONTHLY RETURNS",
                "-" * 70,
                "",
            ])
            for month, pnl in sorted(r.monthly_returns.items()):
                pct = (pnl / r.starting_capital) * 100
                bar = self._generate_bar(pct)
                lines.append(f"{month}:  ${pnl:>10,.2f}  ({pct:>+6.2f}%)  {bar}")
            lines.append("")

        # Trade breakdown by result
        if r.trades:
            tp_trades = [t for t in r.trades if hasattr(t, 'result') and t.result.value == "take_profit"]
            sl_trades = [t for t in r.trades if hasattr(t, 'result') and t.result.value == "stop_loss"]
            te_trades = [t for t in r.trades if hasattr(t, 'result') and t.result.value == "time_exit"]

            lines.extend([
                "-" * 70,
                "TRADE OUTCOMES",
                "-" * 70,
                "",
                f"Take Profit:         {len(tp_trades):>12} ({len(tp_trades)/r.total_trades*100:.1f}%)" if r.total_trades > 0 else "",
                f"Stop Loss:           {len(sl_trades):>12} ({len(sl_trades)/r.total_trades*100:.1f}%)" if r.total_trades > 0 else "",
                f"Time Exit:           {len(te_trades):>12} ({len(te_trades)/r.total_trades*100:.1f}%)" if r.total_trades > 0 else "",
                "",
            ])

        # Recommendations
        lines.extend([
            "-" * 70,
            "RECOMMENDATIONS",
            "-" * 70,
            "",
        ])
        lines.extend(self._generate_recommendations())

        lines.extend([
            "",
            "=" * 70,
        ])

        return "\n".join(lines)

    def _calculate_days(self) -> int:
        """Calculate number of days in backtest period."""
        try:
            start = datetime.strptime(self.result.start_date, "%Y-%m-%d")
            end = datetime.strptime(self.result.end_date, "%Y-%m-%d")
            return (end - start).days
        except:
            return 0

    def _generate_bar(self, value: float, max_width: int = 20) -> str:
        """Generate a simple ASCII bar chart."""
        if value >= 0:
            bar_len = min(int(value / 2), max_width)
            return "[" + "#" * bar_len + " " * (max_width - bar_len) + "]"
        else:
            bar_len = min(int(abs(value) / 2), max_width)
            return "[" + " " * (max_width - bar_len) + "-" * bar_len + "]"

    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on backtest results."""
        r = self.result
        recommendations = []

        # Win Rate Analysis
        if r.win_rate < 50:
            recommendations.extend([
                "! WIN RATE BELOW 50%:",
                "  - Consider stricter entry criteria (higher confidence threshold)",
                "  - Review strategy alignment logic",
                "  - May need to adjust L/S ratio and F&G thresholds",
                "",
            ])
        elif r.win_rate < 55:
            recommendations.extend([
                "* Win rate is marginal (50-55%):",
                "  - Consider adjusting confidence thresholds",
                "  - Review trades during neutral market conditions",
                "",
            ])
        elif r.win_rate < 60:
            recommendations.extend([
                "+ Win rate is acceptable (55-60%):",
                "  - Strategy is performing near target",
                "  - Consider optimizing TP/SL ratios",
                "",
            ])
        else:
            recommendations.extend([
                "++ Excellent win rate (>60%):",
                "  - Strategy is meeting targets",
                "  - Consider slightly increasing position sizes",
                "",
            ])

        # Profit Factor Analysis
        if r.profit_factor < 1.0:
            recommendations.extend([
                "! PROFIT FACTOR < 1.0 (LOSING STRATEGY):",
                "  - Average losses exceed average wins",
                "  - Consider widening take profit targets",
                "  - Review stop loss levels",
                "",
            ])
        elif r.profit_factor < 1.5:
            recommendations.extend([
                "* Profit factor is low (1.0-1.5):",
                "  - Consider adjusting TP/SL ratio",
                "  - Current: TP 3.5%, SL 2.0%",
                "  - Suggestion: Try TP 4.0%, SL 1.5%",
                "",
            ])

        # Drawdown Analysis
        if r.max_drawdown_percent > 15:
            recommendations.extend([
                "! HIGH DRAWDOWN (>15%):",
                "  - Consider reducing position sizes",
                "  - Enable Profit Lock-In feature",
                "  - Reduce daily trade limit",
                "",
            ])
        elif r.max_drawdown_percent > 10:
            recommendations.extend([
                "* Moderate drawdown (10-15%):",
                "  - Monitor risk settings",
                "  - Consider enabling Profit Lock-In",
                "",
            ])

        # Trade Frequency
        days = self._calculate_days()
        if days > 0:
            avg_trades_per_day = r.total_trades / days
            if avg_trades_per_day < 0.5:
                recommendations.extend([
                    "* Low trade frequency (<0.5/day):",
                    "  - Strategy is very selective",
                    "  - Consider relaxing entry criteria for more opportunities",
                    "",
                ])

        # Cost Analysis
        cost_ratio = (r.total_fees + r.total_funding) / r.starting_capital * 100
        if cost_ratio > 5:
            recommendations.extend([
                "! HIGH TRADING COSTS:",
                f"  - Total costs: {cost_ratio:.2f}% of capital",
                "  - Consider fewer but larger trades",
                "  - Review funding rate impact",
                "",
            ])

        # Parameter Suggestions
        if r.win_rate < 55 or r.profit_factor < 1.2:
            recommendations.extend([
                "SUGGESTED PARAMETER CHANGES:",
                "",
                "  | Parameter | Current | Suggested |",
                "  |-----------|---------|-----------|",
            ])

            if r.win_rate < 55:
                recommendations.extend([
                    "  | High Conf Min | 85 | 80 |",
                    "  | Low Conf Min | 55 | 60 |",
                ])

            if r.profit_factor < 1.2:
                recommendations.extend([
                    "  | Take Profit | 3.5% | 4.0% |",
                    "  | Stop Loss | 2.0% | 1.5% |",
                ])

            if r.max_drawdown_percent > 10:
                recommendations.extend([
                    "  | Position Size | 10% | 7.5% |",
                    "  | Leverage | 3x | 2x |",
                ])

            recommendations.append("")

        if not recommendations:
            recommendations.append("Strategy is performing well. No major changes recommended.")

        return recommendations

    def save_json(self, filepath: str = "data/backtest/results.json"):
        """Save detailed results to JSON file."""
        output = {
            "summary": self.result.to_dict(),
            "trades": [t.to_dict() for t in self.result.trades if hasattr(t, 'to_dict')],
            "daily_stats": [
                {
                    "date": s.date,
                    "starting_balance": s.starting_balance,
                    "ending_balance": s.ending_balance,
                    "daily_pnl": s.daily_pnl,
                    "daily_return_percent": s.daily_return_percent,
                    "cumulative_return_percent": s.cumulative_return_percent,
                }
                for s in self.result.daily_stats
            ],
            "generated_at": datetime.now().isoformat(),
        }

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(output, f, indent=2)

        logger.info(f"Saved backtest results to {filepath}")

    def generate_changelog_entry(self) -> str:
        """Generate a changelog entry for the backtest results."""
        r = self.result

        entry = f"""## [1.3.0] - {datetime.now().strftime("%Y-%m-%d")}

### Hinzugefuegt
- **Backtesting-Modul**: Vollstaendige Implementierung fuer historische Strategietests
  - `src/backtest/historical_data.py` - Historische Daten-Fetcher mit Caching
  - `src/backtest/engine.py` - Backtest-Engine mit Trade-Simulation
  - `src/backtest/report.py` - Report-Generator mit Empfehlungen
  - CLI-Integration: `python main.py --backtest`

- **Profit Lock-In Feature**: Dynamisches Verlustlimit
  - Sperrt 75% der Tagesgewinne automatisch
  - Garantiert positive Tage bleiben positiv
  - Konfigurierbar ueber `PROFIT_LOCK_PERCENT`

### Backtest-Ergebnisse (6 Monate, $10.000)

| Metrik | Wert |
|--------|------|
| Zeitraum | {r.start_date} bis {r.end_date} |
| Startkapital | ${r.starting_capital:,.2f} |
| Endkapital | ${r.ending_capital:,.2f} |
| Gesamtrendite | {r.total_return_percent:+.2f}% |
| Max Drawdown | {r.max_drawdown_percent:.2f}% |
| Anzahl Trades | {r.total_trades} |
| Win Rate | {r.win_rate:.2f}% |
| Profit Factor | {r.profit_factor:.2f} |
| Gebühren | ${r.total_fees:,.2f} |
| Funding | ${r.total_funding:,.2f} |

### Monatliche Performance
"""
        for month, pnl in sorted(r.monthly_returns.items()):
            pct = (pnl / r.starting_capital) * 100
            emoji = "+" if pnl >= 0 else "-"
            entry += f"| {month} | ${pnl:+,.2f} ({pct:+.2f}%) |\n"

        return entry
