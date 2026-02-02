"""
Correlation Tracker for Portfolio Assets.

Tracks and calculates correlation between portfolio assets
for diversification analysis and risk management.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)


class CorrelationTracker:
    """
    Tracks price correlations between portfolio assets.

    Used for:
    - Diversification analysis
    - Risk assessment (correlated assets amplify risk)
    - Rebalancing decisions
    """

    def __init__(self, window: int = 30, update_interval_hours: int = 24):
        """
        Initialize the correlation tracker.

        Args:
            window: Number of days for rolling correlation
            update_interval_hours: How often to recalculate
        """
        self.window = window
        self.update_interval_hours = update_interval_hours
        self._price_history: Dict[str, List[Tuple[datetime, float]]] = {}
        self._correlation_matrix: Optional[pd.DataFrame] = None
        self._last_update: Optional[datetime] = None

    def record_price(self, symbol: str, price: float, timestamp: Optional[datetime] = None):
        """
        Record a price observation for an asset.

        Args:
            symbol: Trading pair
            price: Current price
            timestamp: Observation time (defaults to now)
        """
        ts = timestamp or datetime.now()

        if symbol not in self._price_history:
            self._price_history[symbol] = []

        self._price_history[symbol].append((ts, price))

        # Keep only recent data (2x window for safety)
        cutoff = ts - timedelta(days=self.window * 2)
        self._price_history[symbol] = [
            (t, p) for t, p in self._price_history[symbol] if t >= cutoff
        ]

    def calculate_correlation_matrix(self) -> pd.DataFrame:
        """
        Calculate the correlation matrix for all tracked assets.

        Returns:
            DataFrame with pairwise correlations
        """
        if len(self._price_history) < 2:
            return pd.DataFrame()

        # Build price DataFrame
        price_data = {}
        for symbol, history in self._price_history.items():
            if len(history) < 2:
                continue
            df = pd.DataFrame(history, columns=["timestamp", symbol])
            df["date"] = df["timestamp"].dt.date
            # Use daily close (last price of the day)
            daily = df.groupby("date")[symbol].last()
            price_data[symbol] = daily

        if len(price_data) < 2:
            return pd.DataFrame()

        # Combine into single DataFrame
        prices_df = pd.DataFrame(price_data)
        prices_df = prices_df.dropna()

        if len(prices_df) < 3:
            return pd.DataFrame()

        # Calculate returns
        returns = prices_df.pct_change().dropna()

        if len(returns) < 2:
            return pd.DataFrame()

        # Calculate correlation
        self._correlation_matrix = returns.corr()
        self._last_update = datetime.now()

        return self._correlation_matrix

    def get_correlation(self, symbol_a: str, symbol_b: str) -> Optional[float]:
        """
        Get the correlation between two assets.

        Args:
            symbol_a: First trading pair
            symbol_b: Second trading pair

        Returns:
            Correlation coefficient (-1 to 1) or None if not available
        """
        if self._needs_update():
            self.calculate_correlation_matrix()

        if self._correlation_matrix is None or self._correlation_matrix.empty:
            return None

        if symbol_a not in self._correlation_matrix.columns or symbol_b not in self._correlation_matrix.columns:
            return None

        return float(self._correlation_matrix.loc[symbol_a, symbol_b])

    def get_matrix(self) -> Dict[str, Dict[str, float]]:
        """
        Get the full correlation matrix as a nested dict.

        Returns:
            Nested dict of correlations for API responses
        """
        if self._needs_update():
            self.calculate_correlation_matrix()

        if self._correlation_matrix is None or self._correlation_matrix.empty:
            return {}

        result = {}
        for symbol in self._correlation_matrix.columns:
            result[symbol] = {}
            for other in self._correlation_matrix.columns:
                result[symbol][other] = round(
                    float(self._correlation_matrix.loc[symbol, other]), 4
                )

        return result

    def get_portfolio_diversification_score(self) -> float:
        """
        Calculate a diversification score for the portfolio.

        Score ranges from 0 (perfectly correlated) to 1 (perfectly diversified).
        Based on average off-diagonal correlation.

        Returns:
            Diversification score (0-1)
        """
        if self._needs_update():
            self.calculate_correlation_matrix()

        if self._correlation_matrix is None or self._correlation_matrix.empty:
            return 0.5  # Neutral if no data

        n = len(self._correlation_matrix)
        if n < 2:
            return 0.5

        # Get off-diagonal correlations
        mask = np.ones((n, n), dtype=bool)
        np.fill_diagonal(mask, False)
        off_diagonal = self._correlation_matrix.values[mask]

        if len(off_diagonal) == 0:
            return 0.5

        # Average absolute correlation
        avg_corr = np.mean(np.abs(off_diagonal))

        # Convert to diversification score (1 - avg_correlation)
        return round(float(1.0 - avg_corr), 4)

    def get_high_correlation_pairs(self, threshold: float = 0.8) -> List[Dict]:
        """
        Find asset pairs with high correlation (potential concentration risk).

        Args:
            threshold: Correlation threshold for flagging

        Returns:
            List of highly correlated pairs
        """
        if self._needs_update():
            self.calculate_correlation_matrix()

        if self._correlation_matrix is None or self._correlation_matrix.empty:
            return []

        pairs = []
        symbols = list(self._correlation_matrix.columns)

        for i, sym_a in enumerate(symbols):
            for j, sym_b in enumerate(symbols):
                if j <= i:
                    continue
                corr = float(self._correlation_matrix.loc[sym_a, sym_b])
                if abs(corr) >= threshold:
                    pairs.append({
                        "symbol_a": sym_a,
                        "symbol_b": sym_b,
                        "correlation": round(corr, 4),
                        "risk": "high" if abs(corr) >= 0.9 else "moderate",
                    })

        return pairs

    def load_from_parquet(self, symbols: List[str], days: int = 30):
        """
        Load price history from parquet storage for correlation calculation.

        Args:
            symbols: List of trading pairs
            days: Number of days to load
        """
        try:
            from src.backtest.data_storage import ParquetDataStorage

            storage = ParquetDataStorage()
            start_date = datetime.now() - timedelta(days=days)

            for symbol in symbols:
                df = storage.load_ohlcv(symbol, "1D", start_date=start_date)
                if not df.empty:
                    for _, row in df.iterrows():
                        self.record_price(
                            symbol,
                            float(row["close"]),
                            row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"]
                        )
                    logger.info(f"Loaded {len(df)} price points for {symbol}")
        except Exception as e:
            logger.warning(f"Could not load parquet data for correlations: {e}")

    def _needs_update(self) -> bool:
        """Check if correlation matrix needs recalculation."""
        if self._last_update is None:
            return True
        elapsed = (datetime.now() - self._last_update).total_seconds() / 3600
        return elapsed >= self.update_interval_hours
