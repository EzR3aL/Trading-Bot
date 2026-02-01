"""
Pytest configuration and shared fixtures.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass
from typing import Optional

# Ensure src is importable
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@dataclass
class MockMarketMetrics:
    """Mock MarketMetrics for testing."""
    fear_greed_index: int = 50
    fear_greed_classification: str = "Neutral"
    long_short_ratio: float = 1.0
    funding_rate_btc: float = 0.0001
    funding_rate_eth: float = 0.0001
    btc_24h_change_percent: float = 0.0
    eth_24h_change_percent: float = 0.0
    btc_price: float = 95000.0
    eth_price: float = 3500.0
    btc_open_interest: float = 100000.0
    eth_open_interest: float = 50000.0
    timestamp: datetime = None
    data_quality: Optional[dict] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def to_dict(self):
        return {
            "fear_greed_index": self.fear_greed_index,
            "fear_greed_classification": self.fear_greed_classification,
            "long_short_ratio": self.long_short_ratio,
            "funding_rate_btc": self.funding_rate_btc,
            "funding_rate_eth": self.funding_rate_eth,
            "btc_24h_change_percent": self.btc_24h_change_percent,
            "eth_24h_change_percent": self.eth_24h_change_percent,
            "btc_price": self.btc_price,
            "eth_price": self.eth_price,
            "btc_open_interest": self.btc_open_interest,
            "eth_open_interest": self.eth_open_interest,
            "timestamp": self.timestamp.isoformat(),
        }


@pytest.fixture
def mock_market_metrics():
    """Factory for creating mock market metrics."""
    def _create(**kwargs):
        return MockMarketMetrics(**kwargs)
    return _create


@pytest.fixture
def mock_data_fetcher(mock_market_metrics):
    """Create a mock data fetcher."""
    fetcher = AsyncMock()
    fetcher.fetch_all_metrics = AsyncMock(return_value=mock_market_metrics())
    fetcher._ensure_session = AsyncMock()
    fetcher.close = AsyncMock()
    return fetcher


@pytest.fixture
def neutral_metrics(mock_market_metrics):
    """Neutral market conditions."""
    return mock_market_metrics(
        fear_greed_index=50,
        long_short_ratio=1.0,
        funding_rate_btc=0.0001,
        btc_price=95000.0,
        btc_24h_change_percent=0.5,
    )


@pytest.fixture
def crowded_longs_extreme_greed(mock_market_metrics):
    """Crowded longs + extreme greed = Strong SHORT signal."""
    return mock_market_metrics(
        fear_greed_index=85,  # Extreme greed (>75)
        long_short_ratio=2.5,  # Crowded longs (>2.0)
        funding_rate_btc=0.001,  # High funding (expensive to long)
        btc_price=95000.0,
        btc_24h_change_percent=5.0,
    )


@pytest.fixture
def crowded_shorts_extreme_fear(mock_market_metrics):
    """Crowded shorts + extreme fear = Strong LONG signal."""
    return mock_market_metrics(
        fear_greed_index=15,  # Extreme fear (<25)
        long_short_ratio=0.3,  # Crowded shorts (<0.5)
        funding_rate_btc=-0.0005,  # Negative funding (expensive to short)
        btc_price=85000.0,
        btc_24h_change_percent=-8.0,
    )


@pytest.fixture
def conflicting_signals(mock_market_metrics):
    """Leverage says SHORT, sentiment says LONG = Follow leverage."""
    return mock_market_metrics(
        fear_greed_index=20,  # Extreme fear (suggests LONG)
        long_short_ratio=2.5,  # Crowded longs (suggests SHORT)
        funding_rate_btc=0.0001,
        btc_price=90000.0,
        btc_24h_change_percent=-2.0,
    )
