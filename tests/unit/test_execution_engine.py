"""
Tests for the Smart Execution Engine.
"""

import pytest
from datetime import datetime, timedelta

from src.execution.engine import (
    ExecutionEngine,
    ExecutionStrategy,
    ExecutionResult,
    SlippageRecord,
)
from src.execution.twap import TWAPExecutor, TWAPConfig, TWAPSlice
from src.execution.orderbook import OrderbookAnalyzer, OrderbookSnapshot


class TestExecutionEngine:
    """Tests for ExecutionEngine class."""

    @pytest.fixture
    def engine(self):
        return ExecutionEngine()

    def test_initialization(self, engine):
        assert engine.default_strategy == ExecutionStrategy.LIMIT_WITH_FALLBACK
        assert engine.limit_timeout_seconds == 5.0
        assert engine.max_slippage_pct == 0.5

    def test_calculate_limit_price_buy(self, engine):
        price = engine.calculate_limit_price("buy", 50000.0, tick_size=0.1)
        assert price == pytest.approx(50000.1)

    def test_calculate_limit_price_sell(self, engine):
        price = engine.calculate_limit_price("sell", 50000.0, tick_size=0.1)
        assert price == pytest.approx(49999.9)

    def test_calculate_limit_price_custom_ticks(self):
        engine = ExecutionEngine(price_improvement_ticks=3)
        price = engine.calculate_limit_price("buy", 50000.0, tick_size=0.5)
        assert price == pytest.approx(50001.5)

    def test_calculate_slippage_buy_positive(self, engine):
        record = engine.calculate_slippage("buy", 50000.0, 50050.0, 1.0, ExecutionStrategy.MARKET)
        assert record.slippage_pct == pytest.approx(0.1)
        assert record.slippage_usd == pytest.approx(50.0)

    def test_calculate_slippage_buy_negative(self, engine):
        """Negative slippage = price improvement."""
        record = engine.calculate_slippage("buy", 50000.0, 49950.0, 1.0, ExecutionStrategy.MARKET)
        assert record.slippage_pct == pytest.approx(-0.1)

    def test_calculate_slippage_sell(self, engine):
        record = engine.calculate_slippage("sell", 50000.0, 49950.0, 1.0, ExecutionStrategy.MARKET)
        assert record.slippage_pct == pytest.approx(0.1)

    def test_calculate_slippage_zero_price(self, engine):
        record = engine.calculate_slippage("buy", 0, 100, 1.0, ExecutionStrategy.MARKET)
        assert record.slippage_pct == 0.0

    def test_iceberg_chunks_default(self, engine):
        chunks = engine.calculate_iceberg_chunks(100.0)
        assert len(chunks) == 4  # 25% each
        assert sum(chunks) == pytest.approx(100.0)

    def test_iceberg_chunks_custom(self, engine):
        chunks = engine.calculate_iceberg_chunks(100.0, chunk_pct=50.0)
        assert len(chunks) == 2
        assert sum(chunks) == pytest.approx(100.0)

    def test_iceberg_chunks_small_order(self, engine):
        chunks = engine.calculate_iceberg_chunks(10.0, chunk_pct=100.0)
        assert len(chunks) == 1
        assert chunks[0] == pytest.approx(10.0)

    def test_should_use_limit_wide_spread(self, engine):
        use_limit, reason = engine.should_use_limit(0.15)
        assert use_limit is True
        assert "Wide spread" in reason

    def test_should_use_limit_tight_spread(self, engine):
        use_limit, reason = engine.should_use_limit(0.02)
        assert use_limit is False
        assert "Tight spread" in reason

    def test_should_use_limit_high_volatility(self, engine):
        use_limit, reason = engine.should_use_limit(0.05, volatility_pct=3.0)
        assert use_limit is False
        assert "volatility" in reason.lower()

    def test_is_slippage_acceptable_within(self, engine):
        ok, reason = engine.is_slippage_acceptable(0.3)
        assert ok is True

    def test_is_slippage_acceptable_exceeded(self, engine):
        ok, reason = engine.is_slippage_acceptable(0.8)
        assert ok is False
        assert "exceeds" in reason

    def test_slippage_stats_empty(self, engine):
        stats = engine.get_slippage_stats()
        assert stats["count"] == 0

    def test_slippage_stats_with_data(self, engine):
        engine.calculate_slippage("buy", 100.0, 100.1, 10.0, ExecutionStrategy.MARKET)
        engine.calculate_slippage("buy", 100.0, 100.2, 10.0, ExecutionStrategy.MARKET)

        stats = engine.get_slippage_stats()
        assert stats["count"] == 2
        assert stats["avg_slippage_pct"] > 0

    def test_execution_stats_empty(self, engine):
        stats = engine.get_execution_stats()
        assert stats["total_executions"] == 0

    def test_execution_stats_with_data(self, engine):
        engine.record_execution(ExecutionResult(
            success=True, symbol="BTCUSDT", side="buy",
            strategy=ExecutionStrategy.MARKET,
            requested_size=1.0, filled_size=1.0, average_price=50000,
            execution_time_ms=150.0,
        ))
        engine.record_execution(ExecutionResult(
            success=True, symbol="BTCUSDT", side="sell",
            strategy=ExecutionStrategy.LIMIT_WITH_FALLBACK,
            requested_size=1.0, filled_size=0.9, average_price=50100,
            execution_time_ms=200.0,
        ))

        stats = engine.get_execution_stats()
        assert stats["total_executions"] == 2
        assert stats["success_rate"] == 100.0
        assert stats["avg_fill_ratio"] == pytest.approx(0.95)

    def test_get_summary(self, engine):
        summary = engine.get_summary()
        assert "config" in summary
        assert "slippage" in summary
        assert "execution" in summary


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_fill_ratio_full(self):
        r = ExecutionResult(
            success=True, symbol="BTC", side="buy",
            strategy=ExecutionStrategy.MARKET,
            requested_size=1.0, filled_size=1.0, average_price=50000,
        )
        assert r.fill_ratio == pytest.approx(1.0)

    def test_fill_ratio_partial(self):
        r = ExecutionResult(
            success=True, symbol="BTC", side="buy",
            strategy=ExecutionStrategy.MARKET,
            requested_size=2.0, filled_size=1.5, average_price=50000,
        )
        assert r.fill_ratio == pytest.approx(0.75)

    def test_fill_ratio_zero_request(self):
        r = ExecutionResult(
            success=False, symbol="BTC", side="buy",
            strategy=ExecutionStrategy.MARKET,
            requested_size=0.0, filled_size=0.0, average_price=0,
        )
        assert r.fill_ratio == 0.0

    def test_to_dict(self):
        r = ExecutionResult(
            success=True, symbol="BTCUSDT", side="buy",
            strategy=ExecutionStrategy.LIMIT_WITH_FALLBACK,
            requested_size=1.0, filled_size=1.0, average_price=50000,
        )
        d = r.to_dict()
        assert d["strategy"] == "limit_with_fallback"
        assert d["fill_ratio"] == 1.0


class TestTWAPExecutor:
    """Tests for TWAPExecutor class."""

    @pytest.fixture
    def twap(self):
        config = TWAPConfig(total_duration_seconds=300, num_slices=5)
        return TWAPExecutor(config=config)

    def test_create_plan(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)
        assert len(slices) == 5
        total = sum(s.target_size for s in slices)
        assert total == pytest.approx(1.0)

    def test_plan_slice_timing(self, twap):
        start = datetime.utcnow()
        slices = twap.create_plan("BTCUSDT", "buy", 1.0, start_time=start)

        for i, s in enumerate(slices):
            expected = start + timedelta(seconds=60 * i)  # 300/5 = 60s intervals
            assert s.scheduled_time == expected

    def test_mark_slice_executed(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)

        result = twap.mark_slice_executed(slices, 1, 0.2, 50000.0)
        assert result is True
        assert slices[0].executed is True
        assert slices[0].fill_price == 50000.0

    def test_mark_slice_invalid(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)
        result = twap.mark_slice_executed(slices, 99, 0.2, 50000.0)
        assert result is False

    def test_plan_progress_initial(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)
        progress = twap.get_plan_progress(slices)

        assert progress["total_slices"] == 5
        assert progress["executed_slices"] == 0
        assert progress["complete"] is False

    def test_plan_progress_partial(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)
        twap.mark_slice_executed(slices, 1, 0.2, 50000.0)
        twap.mark_slice_executed(slices, 2, 0.2, 50100.0)

        progress = twap.get_plan_progress(slices)
        assert progress["executed_slices"] == 2
        assert progress["fill_ratio"] == pytest.approx(0.4)
        assert progress["complete"] is False

    def test_plan_progress_complete(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)
        for i, s in enumerate(slices):
            twap.mark_slice_executed(slices, i + 1, 0.2, 50000.0)

        progress = twap.get_plan_progress(slices)
        assert progress["complete"] is True
        assert progress["fill_ratio"] == pytest.approx(1.0)

    def test_get_next_slice(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)
        next_s = twap.get_next_slice(slices)
        assert next_s.slice_number == 1

        twap.mark_slice_executed(slices, 1, 0.2, 50000.0)
        next_s = twap.get_next_slice(slices)
        assert next_s.slice_number == 2

    def test_get_next_slice_all_done(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)
        for i in range(5):
            twap.mark_slice_executed(slices, i + 1, 0.2, 50000.0)

        assert twap.get_next_slice(slices) is None

    def test_vwap_calculation(self, twap):
        slices = twap.create_plan("BTCUSDT", "buy", 1.0)
        twap.mark_slice_executed(slices, 1, 0.2, 50000.0)
        twap.mark_slice_executed(slices, 2, 0.2, 50100.0)

        progress = twap.get_plan_progress(slices)
        expected_vwap = (50000 * 0.2 + 50100 * 0.2) / 0.4
        assert progress["vwap"] == pytest.approx(expected_vwap, rel=0.001)


class TestTWAPConfig:
    """Tests for TWAPConfig."""

    def test_interval_calculation(self):
        config = TWAPConfig(total_duration_seconds=300, num_slices=5)
        assert config.interval_seconds == pytest.approx(60.0)

    def test_interval_single_slice(self):
        config = TWAPConfig(total_duration_seconds=300, num_slices=1)
        assert config.interval_seconds == pytest.approx(300.0)

    def test_to_dict(self):
        config = TWAPConfig()
        d = config.to_dict()
        assert "total_duration_seconds" in d
        assert "num_slices" in d
        assert "interval_seconds" in d


class TestOrderbookAnalyzer:
    """Tests for OrderbookAnalyzer class."""

    @pytest.fixture
    def analyzer(self):
        return OrderbookAnalyzer()

    @pytest.fixture
    def snapshot(self, analyzer):
        """Create a sample orderbook snapshot."""
        bids = [
            (50000.0, 1.0),
            (49990.0, 2.0),
            (49980.0, 3.0),
            (49970.0, 5.0),
        ]
        asks = [
            (50010.0, 1.0),
            (50020.0, 2.0),
            (50030.0, 3.0),
            (50040.0, 5.0),
        ]
        return analyzer.create_snapshot("BTCUSDT", bids, asks)

    def test_snapshot_best_bid(self, snapshot):
        assert snapshot.best_bid == 50000.0

    def test_snapshot_best_ask(self, snapshot):
        assert snapshot.best_ask == 50010.0

    def test_snapshot_mid_price(self, snapshot):
        assert snapshot.mid_price == pytest.approx(50005.0)

    def test_snapshot_spread(self, snapshot):
        assert snapshot.spread == pytest.approx(10.0)

    def test_snapshot_spread_pct(self, snapshot):
        expected = (10.0 / 50005.0) * 100
        assert snapshot.spread_pct == pytest.approx(expected, rel=0.01)

    def test_estimate_slippage_small_buy(self, analyzer, snapshot):
        result = analyzer.estimate_slippage(snapshot, "buy", 0.5)
        assert result["estimatable"] is True
        assert result["estimated_slippage_pct"] == pytest.approx(0.0, abs=0.01)

    def test_estimate_slippage_large_buy(self, analyzer, snapshot):
        result = analyzer.estimate_slippage(snapshot, "buy", 5.0)
        assert result["estimatable"] is True
        assert result["estimated_slippage_pct"] > 0

    def test_estimate_slippage_too_large(self, analyzer, snapshot):
        result = analyzer.estimate_slippage(snapshot, "buy", 100.0)
        assert result["estimatable"] is False
        assert "Insufficient depth" in result["reason"]

    def test_estimate_slippage_sell(self, analyzer, snapshot):
        result = analyzer.estimate_slippage(snapshot, "sell", 0.5)
        assert result["estimatable"] is True

    def test_depth_at_price(self, analyzer, snapshot):
        depth = analyzer.get_depth_at_price(snapshot, "buy", 0.1)
        assert depth["total_size"] > 0
        assert depth["side"] == "buy"

    def test_imbalance_balanced(self, analyzer):
        bids = [(100, 5.0), (99, 5.0)]
        asks = [(101, 5.0), (102, 5.0)]
        snap = analyzer.create_snapshot("TEST", bids, asks)

        result = analyzer.get_imbalance(snap, levels=2)
        assert abs(result["imbalance"]) < 0.1
        assert result["interpretation"] == "Balanced"

    def test_imbalance_buy_heavy(self, analyzer):
        bids = [(100, 10.0), (99, 10.0)]
        asks = [(101, 2.0), (102, 2.0)]
        snap = analyzer.create_snapshot("TEST", bids, asks)

        result = analyzer.get_imbalance(snap, levels=2)
        assert result["imbalance"] > 0.3
        assert "buy pressure" in result["interpretation"].lower()

    def test_imbalance_sell_heavy(self, analyzer):
        bids = [(100, 2.0), (99, 2.0)]
        asks = [(101, 10.0), (102, 10.0)]
        snap = analyzer.create_snapshot("TEST", bids, asks)

        result = analyzer.get_imbalance(snap, levels=2)
        assert result["imbalance"] < -0.3
        assert "sell pressure" in result["interpretation"].lower()

    def test_snapshot_to_dict(self, snapshot):
        d = snapshot.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert d["best_bid"] == 50000.0
        assert d["best_ask"] == 50010.0
        assert "spread_pct" in d

    def test_get_snapshot_cached(self, analyzer, snapshot):
        cached = analyzer.get_snapshot("BTCUSDT")
        assert cached is not None
        assert cached.symbol == "BTCUSDT"

    def test_empty_orderbook(self, analyzer):
        snap = analyzer.create_snapshot("EMPTY", [], [])
        assert snap.best_bid == 0.0
        assert snap.best_ask == 0.0
        assert snap.spread == 0.0
        assert snap.mid_price == 0.0
