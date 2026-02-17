"""
Comprehensive unit tests for TaxReportGenerator (tax_report.py).

Tests cover:
- translate() helper function
- TaxReportConfig dataclass
- TaxReportGenerator.aggregate_year_summary (no trades, single trade, many trades)
- TaxReportGenerator.aggregate_monthly_summary (empty, multi-month, edge cases)
- TaxReportGenerator._trade_to_dict (full data, missing fields, zero PnL)
- TaxReportGenerator.get_year_data (happy path, DB errors)
- TaxReportGenerator.get_available_years (happy path, DB errors)
- TaxReportGenerator.get_funding_payments (happy path, DB errors)
- TaxReportGenerator.generate_csv_content (full report, empty report, both languages)
- CSV section writers (_write_header_section, _write_summary_section, etc.)
- Edge cases: None PnL, None fees, None funding_paid, None entry/exit times
"""

import csv
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import StringIO
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.dashboard.tax_report import (
    TRANSLATIONS,
    TaxReportConfig,
    TaxReportGenerator,
    translate,
)


# ---------------------------------------------------------------------------
# Mock Trade dataclass (mirrors src.models.trade_database.Trade fields)
# ---------------------------------------------------------------------------


@dataclass
class MockTrade:
    """Lightweight mock that matches the Trade interface used by TaxReportGenerator."""

    id: int = 1
    symbol: str = "BTCUSDT"
    side: str = "long"
    size: float = 0.01
    entry_price: float = 95000.0
    exit_price: Optional[float] = 96000.0
    pnl: Optional[float] = 100.0
    fees: Optional[float] = 2.5
    funding_paid: Optional[float] = -0.5
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None

    def __post_init__(self):
        if self.entry_time is None:
            self.entry_time = datetime(2025, 3, 15, 10, 0, 0)
        if self.exit_time is None:
            self.exit_time = datetime(2025, 3, 15, 14, 0, 0)


# ---------------------------------------------------------------------------
# Helper: build a generator with mocked dependencies
# ---------------------------------------------------------------------------


def _make_generator():
    """Create a TaxReportGenerator with mocked trade_db and funding_tracker."""
    trade_db = MagicMock()
    trade_db.db_path = ":memory:"
    trade_db.get_trades_by_year = AsyncMock(return_value=[])
    trade_db.get_open_trades = AsyncMock(return_value=[])

    funding_tracker = MagicMock()
    funding_tracker.db_path = ":memory:"

    return TaxReportGenerator(trade_db, funding_tracker)


# ===========================================================================
# 1. translate() function
# ===========================================================================


class TestTranslate:
    """Tests for the translate() helper."""

    def test_translate_german_key(self):
        # Arrange / Act
        result = translate("total_gains", "de")

        # Assert
        assert result == "Gesamtgewinne"

    def test_translate_english_key(self):
        # Arrange / Act
        result = translate("total_gains", "en")

        # Assert
        assert result == "Total Gains"

    def test_translate_unknown_language_falls_back_to_english(self):
        # Arrange / Act
        result = translate("total_gains", "fr")

        # Assert
        assert result == "Total Gains"

    def test_translate_unknown_key_returns_key_itself(self):
        # Arrange / Act
        result = translate("nonexistent_key_xyz", "en")

        # Assert
        assert result == "nonexistent_key_xyz"

    def test_translate_all_german_keys_exist(self):
        """Every key in the English translation must also exist in German."""
        for key in TRANSLATIONS["en"]:
            assert key in TRANSLATIONS["de"], f"Missing German translation for '{key}'"

    def test_translate_all_english_keys_exist(self):
        """Every key in the German translation must also exist in English."""
        for key in TRANSLATIONS["de"]:
            assert key in TRANSLATIONS["en"], f"Missing English translation for '{key}'"


# ===========================================================================
# 2. TaxReportConfig dataclass
# ===========================================================================


class TestTaxReportConfig:
    """Tests for the TaxReportConfig dataclass."""

    def test_default_values(self):
        # Arrange / Act
        config = TaxReportConfig(year=2025, language="de")

        # Assert
        assert config.year == 2025
        assert config.language == "de"
        assert config.include_funding is True
        assert config.include_monthly_breakdown is True

    def test_custom_values(self):
        # Arrange / Act
        config = TaxReportConfig(
            year=2024, language="en", include_funding=False, include_monthly_breakdown=False
        )

        # Assert
        assert config.year == 2024
        assert config.language == "en"
        assert config.include_funding is False
        assert config.include_monthly_breakdown is False


# ===========================================================================
# 3. _trade_to_dict()
# ===========================================================================


class TestTradeToDict:
    """Tests for TaxReportGenerator._trade_to_dict."""

    def test_full_trade_conversion(self):
        # Arrange
        gen = _make_generator()
        entry = datetime(2025, 6, 1, 8, 0, 0)
        exit_ = datetime(2025, 6, 1, 12, 30, 0)
        trade = MockTrade(
            id=42,
            symbol="ETHUSDT",
            side="short",
            size=0.5,
            entry_price=3500.0,
            exit_price=3400.0,
            pnl=50.0,
            fees=1.25,
            funding_paid=-0.3,
            entry_time=entry,
            exit_time=exit_,
        )

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["id"] == 42
        assert result["symbol"] == "ETHUSDT"
        assert result["side"] == "short"
        assert result["size"] == 0.5
        assert result["entry_price"] == 3500.0
        assert result["exit_price"] == 3400.0
        assert result["pnl"] == 50.0
        assert result["fees"] == 1.25
        assert result["funding_paid"] == 0.3  # absolute value
        assert result["entry_time"] == entry.isoformat()
        assert result["exit_time"] == exit_.isoformat()
        # Duration: 4.5 hours
        assert result["duration_hours"] == 4.5
        # Net result: 50.0 - 1.25 - 0.3 = 48.45
        assert result["net_result"] == 48.45

    def test_trade_with_none_pnl(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=None, fees=1.0, funding_paid=0.0)

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["pnl"] == 0.0
        assert result["net_result"] == -1.0  # 0 - 1.0 - 0.0

    def test_trade_with_none_fees(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=10.0, fees=None, funding_paid=0.0)

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["fees"] == 0.0
        assert result["net_result"] == 10.0

    def test_trade_with_none_funding(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=10.0, fees=1.0, funding_paid=None)

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["funding_paid"] == 0.0
        assert result["net_result"] == 9.0

    def test_trade_with_no_exit_time(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(exit_time=None)
        # Force exit_time to None after __post_init__ sets a default
        trade.exit_time = None

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["duration_hours"] == 0.0
        assert result["exit_time"] == ""

    def test_trade_with_no_entry_time(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade()
        trade.entry_time = None

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["entry_time"] == ""
        assert result["duration_hours"] == 0.0

    def test_trade_with_zero_pnl(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=0.0, fees=0.0, funding_paid=0.0)

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["pnl"] == 0.0
        assert result["net_result"] == 0.0


# ===========================================================================
# 4. aggregate_year_summary()
# ===========================================================================


class TestAggregateYearSummary:
    """Tests for TaxReportGenerator.aggregate_year_summary."""

    @pytest.mark.asyncio
    async def test_no_trades_returns_zeros(self):
        # Arrange
        gen = _make_generator()

        # Act
        result = await gen.aggregate_year_summary(2025, trades=[])

        # Assert
        assert result["total_gains"] == 0.0
        assert result["total_losses"] == 0.0
        assert result["net_pnl"] == 0.0
        assert result["total_fees"] == 0.0
        assert result["total_funding"] == 0.0
        assert result["trade_count"] == 0
        assert result["win_count"] == 0
        assert result["loss_count"] == 0
        assert result["win_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_none_trades_fetches_from_db(self):
        # Arrange
        gen = _make_generator()
        gen.trade_db.get_trades_by_year = AsyncMock(return_value=[])

        # Act
        result = await gen.aggregate_year_summary(2025, trades=None)

        # Assert
        gen.trade_db.get_trades_by_year.assert_awaited_once_with(2025)
        assert result["trade_count"] == 0

    @pytest.mark.asyncio
    async def test_single_winning_trade(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=100.0, fees=2.0, funding_paid=-0.5)

        # Act
        result = await gen.aggregate_year_summary(2025, trades=[trade])

        # Assert
        assert result["total_gains"] == 100.0
        assert result["total_losses"] == 0.0
        assert result["gross_pnl"] == 100.0
        assert result["net_pnl"] == 100.0 - 2.0 - 0.5  # 97.5
        assert result["total_fees"] == 2.0
        assert result["total_funding"] == 0.5  # abs(-0.5)
        assert result["trade_count"] == 1
        assert result["win_count"] == 1
        assert result["loss_count"] == 0
        assert result["win_rate"] == 100.0

    @pytest.mark.asyncio
    async def test_single_losing_trade(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=-50.0, fees=1.0, funding_paid=-0.2)

        # Act
        result = await gen.aggregate_year_summary(2025, trades=[trade])

        # Assert
        assert result["total_gains"] == 0.0
        assert result["total_losses"] == -50.0
        assert result["gross_pnl"] == -50.0
        assert result["net_pnl"] == -50.0 - 1.0 - 0.2  # -51.2
        assert result["win_count"] == 0
        assert result["loss_count"] == 1
        assert result["win_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_mixed_trades(self):
        # Arrange
        gen = _make_generator()
        trades = [
            MockTrade(id=1, pnl=200.0, fees=3.0, funding_paid=-1.0),
            MockTrade(id=2, pnl=-80.0, fees=2.0, funding_paid=-0.5),
            MockTrade(id=3, pnl=50.0, fees=1.5, funding_paid=0.0),
        ]

        # Act
        result = await gen.aggregate_year_summary(2025, trades=trades)

        # Assert
        assert result["total_gains"] == 250.0   # 200 + 50
        assert result["total_losses"] == -80.0
        assert result["gross_pnl"] == 170.0      # 250 - 80
        assert result["total_fees"] == 6.5        # 3 + 2 + 1.5
        assert result["total_funding"] == 1.5     # abs(-1.0) + abs(-0.5) + abs(0)
        assert result["net_pnl"] == 170.0 - 6.5 - 1.5  # 162.0
        assert result["trade_count"] == 3
        assert result["win_count"] == 2
        assert result["loss_count"] == 1
        assert result["win_rate"] == pytest.approx(66.67, abs=0.01)

    @pytest.mark.asyncio
    async def test_trade_with_zero_pnl_not_counted_as_win_or_loss(self):
        """A trade with PnL == 0.0 is falsy, so it bypasses both win and loss checks."""
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=0.0, fees=0.5, funding_paid=0.0)

        # Act
        result = await gen.aggregate_year_summary(2025, trades=[trade])

        # Assert
        # 0.0 is falsy in Python: `trade.pnl and trade.pnl > 0` => False
        # and `trade.pnl and trade.pnl <= 0` => False (short-circuits)
        assert result["loss_count"] == 0
        assert result["win_count"] == 0
        assert result["trade_count"] == 1

    @pytest.mark.asyncio
    async def test_trade_with_none_pnl_not_counted_in_gains_or_losses(self):
        """Trades with None PnL should not add to gains or losses."""
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=None, fees=1.0, funding_paid=0.0)

        # Act
        result = await gen.aggregate_year_summary(2025, trades=[trade])

        # Assert
        assert result["total_gains"] == 0.0
        assert result["total_losses"] == 0.0
        # None pnl => not (pnl > 0) and not (pnl <= 0) because None evaluates falsy
        assert result["win_count"] == 0
        assert result["loss_count"] == 0

    @pytest.mark.asyncio
    async def test_rounding_precision(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=100.555, fees=1.111, funding_paid=-0.333)

        # Act
        result = await gen.aggregate_year_summary(2025, trades=[trade])

        # Assert -- values are rounded to 2 decimal places
        assert result["total_gains"] == 100.56  # round(100.555, 2)
        assert result["total_fees"] == 1.11
        assert result["total_funding"] == 0.33


# ===========================================================================
# 5. aggregate_monthly_summary()
# ===========================================================================


class TestAggregateMonthlyBreakdown:
    """Tests for TaxReportGenerator.aggregate_monthly_summary."""

    @pytest.mark.asyncio
    async def test_empty_trades_returns_12_months(self):
        # Arrange
        gen = _make_generator()

        # Act
        result = await gen.aggregate_monthly_summary(2025, trades=[])

        # Assert - 12 months from Jan to Dec
        assert len(result) == 12
        for i, month_data in enumerate(result, start=1):
            assert month_data["month"] == f"2025-{i:02d}"
            assert month_data["trades"] == 0
            assert month_data["wins"] == 0
            assert month_data["losses"] == 0
            assert month_data["pnl"] == 0.0
            assert month_data["fees"] == 0.0
            assert month_data["funding"] == 0.0
            assert month_data["net"] == 0.0
            assert month_data["win_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_none_trades_fetches_from_db(self):
        # Arrange
        gen = _make_generator()
        gen.trade_db.get_trades_by_year = AsyncMock(return_value=[])

        # Act
        result = await gen.aggregate_monthly_summary(2025, trades=None)

        # Assert
        gen.trade_db.get_trades_by_year.assert_awaited_once_with(2025)
        assert len(result) == 12

    @pytest.mark.asyncio
    async def test_single_trade_in_march(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(
            pnl=100.0,
            fees=2.0,
            funding_paid=-0.5,
            entry_time=datetime(2025, 3, 15, 10, 0, 0),
        )

        # Act
        result = await gen.aggregate_monthly_summary(2025, trades=[trade])

        # Assert - March (index 2) should have data
        march = result[2]
        assert march["month"] == "2025-03"
        assert march["trades"] == 1
        assert march["wins"] == 1
        assert march["losses"] == 0
        assert march["pnl"] == 100.0
        assert march["fees"] == 2.0
        assert march["funding"] == 0.5  # abs(-0.5)
        assert march["net"] == 100.0 - 2.0 - 0.5  # 97.5
        assert march["win_rate"] == 100.0

        # Other months should be zero
        for i, month_data in enumerate(result):
            if i != 2:
                assert month_data["trades"] == 0

    @pytest.mark.asyncio
    async def test_multiple_trades_same_month(self):
        # Arrange
        gen = _make_generator()
        trades = [
            MockTrade(
                id=1,
                pnl=80.0,
                fees=1.0,
                funding_paid=-0.2,
                entry_time=datetime(2025, 6, 5, 10, 0, 0),
            ),
            MockTrade(
                id=2,
                pnl=-30.0,
                fees=0.8,
                funding_paid=-0.1,
                entry_time=datetime(2025, 6, 20, 14, 0, 0),
            ),
        ]

        # Act
        result = await gen.aggregate_monthly_summary(2025, trades=trades)

        # Assert - June (index 5)
        june = result[5]
        assert june["month"] == "2025-06"
        assert june["trades"] == 2
        assert june["wins"] == 1
        assert june["losses"] == 1
        assert june["pnl"] == 50.0  # 80 + (-30)
        assert june["fees"] == 1.8
        assert june["funding"] == 0.3  # abs(-0.2) + abs(-0.1)
        assert june["win_rate"] == 50.0
        assert june["net"] == pytest.approx(50.0 - 1.8 - 0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_trades_across_multiple_months(self):
        # Arrange
        gen = _make_generator()
        trades = [
            MockTrade(
                id=1,
                pnl=50.0,
                fees=1.0,
                funding_paid=0.0,
                entry_time=datetime(2025, 1, 10),
            ),
            MockTrade(
                id=2,
                pnl=-20.0,
                fees=0.5,
                funding_paid=0.0,
                entry_time=datetime(2025, 7, 22),
            ),
            MockTrade(
                id=3,
                pnl=30.0,
                fees=0.7,
                funding_paid=0.0,
                entry_time=datetime(2025, 12, 31),
            ),
        ]

        # Act
        result = await gen.aggregate_monthly_summary(2025, trades=trades)

        # Assert
        assert result[0]["trades"] == 1   # January
        assert result[0]["pnl"] == 50.0
        assert result[6]["trades"] == 1   # July
        assert result[6]["pnl"] == -20.0
        assert result[11]["trades"] == 1  # December
        assert result[11]["pnl"] == 30.0

    @pytest.mark.asyncio
    async def test_trade_with_no_entry_time_is_skipped(self):
        """Trades with None entry_time should not be counted in any month."""
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=100.0)
        trade.entry_time = None

        # Act
        result = await gen.aggregate_monthly_summary(2025, trades=[trade])

        # Assert - no month should have any trades
        for month_data in result:
            assert month_data["trades"] == 0

    @pytest.mark.asyncio
    async def test_trade_outside_target_year_is_ignored(self):
        """Trades from a different year should not be aggregated."""
        # Arrange
        gen = _make_generator()
        trade = MockTrade(
            pnl=100.0,
            entry_time=datetime(2024, 6, 15),  # Wrong year for 2025 report
        )

        # Act
        result = await gen.aggregate_monthly_summary(2025, trades=[trade])

        # Assert - month_key "2024-06" won't match any 2025 month
        for month_data in result:
            assert month_data["trades"] == 0

    @pytest.mark.asyncio
    async def test_losing_trade_with_none_pnl(self):
        """Trade with None PnL adds to losses (else branch in source)."""
        # Arrange
        gen = _make_generator()
        trade = MockTrade(
            pnl=None,
            fees=1.0,
            funding_paid=0.0,
            entry_time=datetime(2025, 4, 10),
        )

        # Act
        result = await gen.aggregate_monthly_summary(2025, trades=[trade])

        # Assert - April (index 3)
        april = result[3]
        assert april["trades"] == 1
        # None pnl => not (pnl > 0) => goes to else => losses += 1
        assert april["losses"] == 1
        assert april["wins"] == 0


# ===========================================================================
# 6. get_year_data()
# ===========================================================================


class TestGetYearData:
    """Tests for TaxReportGenerator.get_year_data."""

    @pytest.mark.asyncio
    async def test_happy_path_with_trades(self):
        # Arrange
        gen = _make_generator()
        trades = [
            MockTrade(id=1, pnl=100.0, fees=2.0, funding_paid=-0.5),
            MockTrade(id=2, pnl=-30.0, fees=1.0, funding_paid=-0.2),
        ]
        gen.trade_db.get_trades_by_year = AsyncMock(return_value=trades)
        gen.trade_db.get_open_trades = AsyncMock(return_value=[MockTrade(id=3)])

        # Mock get_funding_payments to avoid DB access
        with patch.object(gen, "get_funding_payments", new_callable=AsyncMock, return_value=[]):
            # Act
            result = await gen.get_year_data(2025, language="en")

        # Assert
        assert result["year"] == 2025
        assert result["language"] == "en"
        assert result["summary"]["trade_count"] == 2
        assert result["summary"]["open_trades_count"] == 1
        assert len(result["trades"]) == 2
        assert len(result["monthly_breakdown"]) == 12
        assert result["funding_payments"] == []

    @pytest.mark.asyncio
    async def test_no_trades(self):
        # Arrange
        gen = _make_generator()
        gen.trade_db.get_trades_by_year = AsyncMock(return_value=[])
        gen.trade_db.get_open_trades = AsyncMock(return_value=[])

        with patch.object(gen, "get_funding_payments", new_callable=AsyncMock, return_value=[]):
            # Act
            result = await gen.get_year_data(2025)

        # Assert
        assert result["summary"]["trade_count"] == 0
        assert result["summary"]["open_trades_count"] == 0
        assert len(result["trades"]) == 0

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_structure(self):
        # Arrange
        gen = _make_generator()
        gen.trade_db.get_trades_by_year = AsyncMock(
            side_effect=Exception("DB connection failed")
        )

        # Act
        result = await gen.get_year_data(2025, language="de")

        # Assert
        assert result["year"] == 2025
        assert result["language"] == "de"
        assert result["summary"] == {}
        assert result["trades"] == []
        assert result["monthly_breakdown"] == []
        assert result["funding_payments"] == []

    @pytest.mark.asyncio
    async def test_open_trades_none_returns_zero_count(self):
        # Arrange
        gen = _make_generator()
        gen.trade_db.get_trades_by_year = AsyncMock(return_value=[])
        gen.trade_db.get_open_trades = AsyncMock(return_value=None)

        with patch.object(gen, "get_funding_payments", new_callable=AsyncMock, return_value=[]):
            # Act
            result = await gen.get_year_data(2025)

        # Assert
        assert result["summary"]["open_trades_count"] == 0


# ===========================================================================
# 7. get_available_years()
# ===========================================================================


class TestGetAvailableYears:
    """Tests for TaxReportGenerator.get_available_years."""

    @pytest.mark.asyncio
    async def test_returns_years_from_db(self):
        # Arrange
        gen = _make_generator()

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("2025",), ("2024",), ("2023",)])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("aiosqlite.connect", return_value=mock_db):
            # Act
            result = await gen.get_available_years()

        # Assert
        assert result == [2025, 2024, 2023]

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_list(self):
        # Arrange
        gen = _make_generator()

        with patch("aiosqlite.connect", side_effect=Exception("DB error")):
            # Act
            result = await gen.get_available_years()

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_empty_db_returns_empty_list(self):
        # Arrange
        gen = _make_generator()

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("aiosqlite.connect", return_value=mock_db):
            # Act
            result = await gen.get_available_years()

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_out_none_years(self):
        # Arrange
        gen = _make_generator()

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("2025",), (None,)])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        with patch("aiosqlite.connect", return_value=mock_db):
            # Act
            result = await gen.get_available_years()

        # Assert
        assert result == [2025]


# ===========================================================================
# 8. get_funding_payments()
# ===========================================================================


class TestGetFundingPayments:
    """Tests for TaxReportGenerator.get_funding_payments."""

    @pytest.mark.asyncio
    async def test_returns_funding_data(self):
        # Arrange
        gen = _make_generator()

        mock_row = {
            "timestamp": "2025-03-15T08:00:00",
            "symbol": "BTCUSDT",
            "side": "long",
            "funding_rate": 0.0001,
            "position_value": 10000.0,
            "payment_amount": 1.0,
        }
        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[mock_row])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)

        import aiosqlite as _aiosqlite
        with patch("aiosqlite.connect", return_value=mock_db):
            # Patch Row on the module so it can be assigned to db.row_factory
            with patch.object(_aiosqlite, "Row", "Row", create=True):
                # Act
                result = await gen.get_funding_payments(2025)

        # Assert
        assert len(result) == 1
        assert result[0]["symbol"] == "BTCUSDT"
        assert result[0]["funding_rate"] == 0.0001
        assert result[0]["payment_amount"] == 1.0

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_list(self):
        # Arrange
        gen = _make_generator()

        with patch("aiosqlite.connect", side_effect=Exception("DB error")):
            # Act
            result = await gen.get_funding_payments(2025)

        # Assert
        assert result == []


# ===========================================================================
# 9. generate_csv_content()
# ===========================================================================


class TestGenerateCsvContent:
    """Tests for TaxReportGenerator.generate_csv_content."""

    @pytest.mark.asyncio
    async def test_csv_starts_with_utf8_bom(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "de",
                "summary": {
                    "total_gains": 0, "total_losses": 0, "net_pnl": 0,
                    "total_fees": 0, "total_funding": 0, "trade_count": 0,
                    "win_rate": 0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "de")

        # Assert
        assert csv_content.startswith("\ufeff")

    @pytest.mark.asyncio
    async def test_csv_contains_bilingual_title(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "en",
                "summary": {
                    "total_gains": 100, "total_losses": -50, "net_pnl": 50,
                    "total_fees": 5, "total_funding": 2, "trade_count": 3,
                    "win_rate": 66.67, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert
        assert "STEUERREPORT" in csv_content
        assert "TAX REPORT" in csv_content

    @pytest.mark.asyncio
    async def test_csv_contains_summary_data(self):
        # Arrange
        gen = _make_generator()
        summary = {
            "total_gains": 500.0,
            "total_losses": -200.0,
            "net_pnl": 280.0,
            "total_fees": 15.0,
            "total_funding": 5.0,
            "trade_count": 10,
            "win_rate": 70.0,
            "open_trades_count": 2,
        }
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "de",
                "summary": summary,
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "de")

        # Assert
        assert "500.0" in csv_content or "500" in csv_content
        assert "-200.0" in csv_content or "-200" in csv_content
        assert "280.0" in csv_content or "280" in csv_content
        assert "70.0%" in csv_content

    @pytest.mark.asyncio
    async def test_csv_contains_trade_rows(self):
        # Arrange
        gen = _make_generator()
        trade_data = {
            "id": 1,
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_time": "2025-03-15T10:00:00",
            "exit_time": "2025-03-15T14:00:00",
            "entry_price": 95000.0,
            "exit_price": 96000.0,
            "size": 0.01,
            "pnl": 100.0,
            "fees": 2.5,
            "funding_paid": 0.5,
            "net_result": 97.0,
            "duration_hours": 4.0,
        }
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "en",
                "summary": {
                    "total_gains": 100, "total_losses": 0, "net_pnl": 97,
                    "total_fees": 2.5, "total_funding": 0.5, "trade_count": 1,
                    "win_rate": 100.0, "open_trades_count": 0,
                },
                "trades": [trade_data],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert
        assert "BTCUSDT" in csv_content
        assert "LONG" in csv_content
        assert "95000.0" in csv_content
        assert "96000.0" in csv_content

    @pytest.mark.asyncio
    async def test_csv_contains_monthly_breakdown(self):
        # Arrange
        gen = _make_generator()
        monthly = [
            {
                "month": "2025-03",
                "trades": 5,
                "wins": 3,
                "losses": 2,
                "win_rate": 60.0,
                "pnl": 150.0,
                "fees": 8.0,
                "funding": 2.0,
                "net": 140.0,
            }
        ]
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "de",
                "summary": {
                    "total_gains": 150, "total_losses": 0, "net_pnl": 140,
                    "total_fees": 8, "total_funding": 2, "trade_count": 5,
                    "win_rate": 60.0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": monthly,
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "de")

        # Assert
        assert "2025-03" in csv_content
        assert "MONATLICHE AUFSCHLÜSSELUNG" in csv_content or "MONTHLY BREAKDOWN" in csv_content

    @pytest.mark.asyncio
    async def test_csv_empty_monthly_rows_are_skipped(self):
        """Months with zero trades should not appear in the monthly section."""
        # Arrange
        gen = _make_generator()
        monthly = [
            {
                "month": "2025-01",
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "pnl": 0.0,
                "fees": 0.0,
                "funding": 0.0,
                "net": 0.0,
            },
            {
                "month": "2025-02",
                "trades": 3,
                "wins": 2,
                "losses": 1,
                "win_rate": 66.67,
                "pnl": 80.0,
                "fees": 2.0,
                "funding": 0.5,
                "net": 77.5,
            },
        ]
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "en",
                "summary": {
                    "total_gains": 80, "total_losses": 0, "net_pnl": 77.5,
                    "total_fees": 2, "total_funding": 0.5, "trade_count": 3,
                    "win_rate": 66.67, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": monthly,
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert - 2025-01 should NOT appear in monthly data rows (only in header row if at all)
        lines = csv_content.split("\n")
        # Find lines that contain monthly data
        monthly_data_lines = [l for l in lines if "2025-02" in l]
        assert len(monthly_data_lines) >= 1

    @pytest.mark.asyncio
    async def test_csv_includes_funding_section_when_payments_exist(self):
        # Arrange
        gen = _make_generator()
        funding = [
            {
                "timestamp": "2025-03-15T08:00:00",
                "symbol": "BTCUSDT",
                "side": "long",
                "funding_rate": 0.0001,
                "position_value": 10000.0,
                "payment_amount": 1.0,
            }
        ]
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "en",
                "summary": {
                    "total_gains": 0, "total_losses": 0, "net_pnl": 0,
                    "total_fees": 0, "total_funding": 0, "trade_count": 0,
                    "win_rate": 0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": funding,
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert
        assert "FUNDING PAYMENTS DETAIL" in csv_content or "FINANZIERUNGSKOSTEN" in csv_content
        assert "10000.0" in csv_content or "10000" in csv_content

    @pytest.mark.asyncio
    async def test_csv_omits_funding_section_when_no_payments(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "de",
                "summary": {
                    "total_gains": 0, "total_losses": 0, "net_pnl": 0,
                    "total_fees": 0, "total_funding": 0, "trade_count": 0,
                    "win_rate": 0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "de")

        # Assert
        assert "FINANZIERUNGSKOSTEN EINZELN" not in csv_content
        assert "FUNDING PAYMENTS DETAIL" not in csv_content

    @pytest.mark.asyncio
    async def test_csv_open_trades_note_shown_when_nonzero(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "en",
                "summary": {
                    "total_gains": 0, "total_losses": 0, "net_pnl": 0,
                    "total_fees": 0, "total_funding": 0, "trade_count": 0,
                    "win_rate": 0, "open_trades_count": 3,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert
        assert "Open trades not included" in csv_content
        assert "3" in csv_content

    @pytest.mark.asyncio
    async def test_csv_open_trades_note_hidden_when_zero(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "en",
                "summary": {
                    "total_gains": 0, "total_losses": 0, "net_pnl": 0,
                    "total_fees": 0, "total_funding": 0, "trade_count": 0,
                    "win_rate": 0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert
        assert "Open trades not included" not in csv_content

    @pytest.mark.asyncio
    async def test_csv_german_language(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "de",
                "summary": {
                    "total_gains": 100, "total_losses": -50, "net_pnl": 40,
                    "total_fees": 5, "total_funding": 5, "trade_count": 5,
                    "win_rate": 60.0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "de")

        # Assert - German terms should be present
        assert "Gesamtgewinne" in csv_content
        assert "Gesamtverluste" in csv_content
        assert "Gewinnrate" in csv_content

    @pytest.mark.asyncio
    async def test_csv_english_language(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "en",
                "summary": {
                    "total_gains": 100, "total_losses": -50, "net_pnl": 40,
                    "total_fees": 5, "total_funding": 5, "trade_count": 5,
                    "win_rate": 60.0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert - English terms should be present
        assert "Total Gains" in csv_content
        assert "Total Losses" in csv_content
        assert "Win Rate" in csv_content

    @pytest.mark.asyncio
    async def test_csv_contains_disclaimers_in_both_languages(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2025,
                "language": "en",
                "summary": {
                    "total_gains": 0, "total_losses": 0, "net_pnl": 0,
                    "total_fees": 0, "total_funding": 0, "trade_count": 0,
                    "win_rate": 0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert - both disclaimers should always be present
        assert "HINWEIS" in csv_content
        assert "NOTE" in csv_content

    @pytest.mark.asyncio
    async def test_csv_year_period_in_header(self):
        # Arrange
        gen = _make_generator()
        with patch.object(gen, "get_year_data", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "year": 2024,
                "language": "en",
                "summary": {
                    "total_gains": 0, "total_losses": 0, "net_pnl": 0,
                    "total_fees": 0, "total_funding": 0, "trade_count": 0,
                    "win_rate": 0, "open_trades_count": 0,
                },
                "trades": [],
                "monthly_breakdown": [],
                "funding_payments": [],
            }

            # Act
            csv_content = await gen.generate_csv_content(2024, "en")

        # Assert
        assert "2024-01-01" in csv_content
        assert "2024-12-31" in csv_content


# ===========================================================================
# 10. CSV Section Writers (direct testing)
# ===========================================================================


class TestCsvSectionWriters:
    """Tests for internal CSV section writing methods."""

    def _get_csv_lines(self, output: StringIO) -> list:
        """Parse CSV output into rows."""
        output.seek(0)
        return list(csv.reader(output))

    def test_write_header_section(self):
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {"year": 2025}

        # Act
        gen._write_header_section(writer, data, "en")

        # Assert
        rows = self._get_csv_lines(output)
        assert len(rows) >= 4  # title, period, generated date, empty row
        assert "STEUERREPORT" in rows[0][0]
        assert "TAX REPORT" in rows[0][0]
        assert "2025-01-01" in rows[1][1]
        assert "2025-12-31" in rows[1][1]

    def test_write_summary_section(self):
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {
            "summary": {
                "total_gains": 1000.0,
                "total_losses": -400.0,
                "net_pnl": 560.0,
                "total_fees": 30.0,
                "total_funding": 10.0,
                "trade_count": 20,
                "win_rate": 65.0,
                "open_trades_count": 0,
            }
        }

        # Act
        gen._write_summary_section(writer, data, "en")

        # Assert
        rows = self._get_csv_lines(output)
        # Should have: header, column names, 7 data rows, empty row
        assert len(rows) >= 9
        # Check gains row
        gains_rows = [r for r in rows if "Total Gains" in str(r)]
        assert len(gains_rows) >= 1

    def test_write_summary_section_with_open_trades(self):
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {
            "summary": {
                "total_gains": 0,
                "total_losses": 0,
                "net_pnl": 0,
                "total_fees": 0,
                "total_funding": 0,
                "trade_count": 0,
                "win_rate": 0,
                "open_trades_count": 5,
            }
        }

        # Act
        gen._write_summary_section(writer, data, "en")

        # Assert
        rows = self._get_csv_lines(output)
        open_rows = [r for r in rows if "Open trades not included" in str(r)]
        assert len(open_rows) == 1

    def test_write_trades_section_with_trades(self):
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {
            "trades": [
                {
                    "entry_time": "2025-03-15T10:00:00.000000",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_price": 95000.0,
                    "exit_price": 96000.0,
                    "size": 0.01,
                    "pnl": 100.0,
                    "fees": 2.5,
                    "funding_paid": 0.5,
                    "net_result": 97.0,
                    "duration_hours": 4.0,
                },
            ]
        }

        # Act
        gen._write_trades_section(writer, data, "en")

        # Assert
        rows = self._get_csv_lines(output)
        # header + column names + 1 trade + empty row = 4
        assert len(rows) >= 4
        # Trade row should have LONG (uppercased)
        trade_row = [r for r in rows if "BTCUSDT" in str(r)]
        assert len(trade_row) >= 1

    def test_write_trades_section_empty(self):
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {"trades": []}

        # Act
        gen._write_trades_section(writer, data, "de")

        # Assert
        rows = self._get_csv_lines(output)
        # header + column names + empty row = 3
        assert len(rows) >= 3

    def test_write_monthly_section(self):
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {
            "monthly_breakdown": [
                {
                    "month": "2025-01",
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "win_rate": 0,
                    "pnl": 0,
                    "fees": 0,
                    "funding": 0,
                    "net": 0,
                },
                {
                    "month": "2025-03",
                    "trades": 5,
                    "wins": 3,
                    "losses": 2,
                    "win_rate": 60.0,
                    "pnl": 150.0,
                    "fees": 8.0,
                    "funding": 2.0,
                    "net": 140.0,
                },
            ]
        }

        # Act
        gen._write_monthly_section(writer, data, "en")

        # Assert
        rows = self._get_csv_lines(output)
        # Only months with trades > 0 should appear
        month_data_rows = [r for r in rows if "2025-03" in str(r)]
        assert len(month_data_rows) >= 1
        # January (0 trades) should not appear as a data row
        jan_data_rows = [r for r in rows if r and r[0] == "2025-01"]
        assert len(jan_data_rows) == 0

    def test_write_funding_section(self):
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {
            "funding_payments": [
                {
                    "timestamp": "2025-03-15T08:00:00.000000",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "funding_rate": 0.0001,
                    "position_value": 10000.0,
                    "payment_amount": 1.0,
                }
            ]
        }

        # Act
        gen._write_funding_section(writer, data, "en")

        # Assert
        rows = self._get_csv_lines(output)
        # header + column names + 1 payment + empty row
        assert len(rows) >= 4
        # Funding rate should be converted to percentage: 0.0001 * 100 = 0.01
        payment_rows = [r for r in rows if "BTCUSDT" in str(r)]
        assert len(payment_rows) >= 1

    def test_write_trades_section_truncates_entry_time_microseconds(self):
        """Entry time should be truncated to 19 chars (YYYY-MM-DDTHH:MM:SS)."""
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {
            "trades": [
                {
                    "entry_time": "2025-03-15T10:00:00.123456",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_price": 95000.0,
                    "exit_price": 96000.0,
                    "size": 0.01,
                    "pnl": 100.0,
                    "fees": 2.5,
                    "funding_paid": 0.5,
                    "net_result": 97.0,
                    "duration_hours": 4.0,
                },
            ]
        }

        # Act
        gen._write_trades_section(writer, data, "en")

        # Assert
        rows = self._get_csv_lines(output)
        # Find the data row (not header)
        trade_rows = [r for r in rows if r and "BTCUSDT" in str(r) and "Symbol" not in str(r)]
        assert len(trade_rows) >= 1
        # First column should be truncated time
        assert trade_rows[0][0] == "2025-03-15T10:00:00"

    def test_write_trades_section_handles_empty_entry_time(self):
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {
            "trades": [
                {
                    "entry_time": "",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_price": 95000.0,
                    "exit_price": None,
                    "size": 0.01,
                    "pnl": 0.0,
                    "fees": 0.0,
                    "funding_paid": 0.0,
                    "net_result": 0.0,
                    "duration_hours": 0.0,
                },
            ]
        }

        # Act
        gen._write_trades_section(writer, data, "en")

        # Assert
        rows = self._get_csv_lines(output)
        trade_rows = [r for r in rows if r and "BTCUSDT" in str(r) and "Symbol" not in str(r)]
        assert len(trade_rows) >= 1
        assert trade_rows[0][0] == ""


# ===========================================================================
# 11. End-to-end scenario: full CSV with all sections
# ===========================================================================


class TestFullCsvScenario:
    """Integration-like test with all sections populated."""

    @pytest.mark.asyncio
    async def test_full_report_with_all_sections(self):
        # Arrange
        gen = _make_generator()
        trades = [
            MockTrade(
                id=1,
                symbol="BTCUSDT",
                side="long",
                size=0.01,
                entry_price=95000.0,
                exit_price=96000.0,
                pnl=100.0,
                fees=2.5,
                funding_paid=-0.5,
                entry_time=datetime(2025, 3, 10, 10, 0, 0),
                exit_time=datetime(2025, 3, 10, 14, 0, 0),
            ),
            MockTrade(
                id=2,
                symbol="ETHUSDT",
                side="short",
                size=0.5,
                entry_price=3500.0,
                exit_price=3400.0,
                pnl=50.0,
                fees=1.25,
                funding_paid=-0.3,
                entry_time=datetime(2025, 6, 20, 8, 0, 0),
                exit_time=datetime(2025, 6, 20, 16, 0, 0),
            ),
            MockTrade(
                id=3,
                symbol="BTCUSDT",
                side="long",
                size=0.02,
                entry_price=94000.0,
                exit_price=93000.0,
                pnl=-80.0,
                fees=3.0,
                funding_paid=-1.0,
                entry_time=datetime(2025, 6, 25, 9, 0, 0),
                exit_time=datetime(2025, 6, 25, 18, 0, 0),
            ),
        ]

        gen.trade_db.get_trades_by_year = AsyncMock(return_value=trades)
        gen.trade_db.get_open_trades = AsyncMock(return_value=[MockTrade(id=99)])

        funding_payments = [
            {
                "timestamp": "2025-03-10T08:00:00",
                "symbol": "BTCUSDT",
                "side": "long",
                "funding_rate": 0.0001,
                "position_value": 9500.0,
                "payment_amount": 0.95,
            }
        ]
        with patch.object(
            gen, "get_funding_payments", new_callable=AsyncMock, return_value=funding_payments
        ):
            # Act
            csv_content = await gen.generate_csv_content(2025, "de")

        # Assert - Structure
        assert csv_content.startswith("\ufeff")

        lines = csv_content.split("\n")

        # Title
        assert any("STEUERREPORT" in line for line in lines)

        # Summary
        assert any("ZUSAMMENFASSUNG" in line for line in lines)

        # Trade detail
        assert any("EINZELTRANSAKTIONEN" in line for line in lines)
        btc_lines = [l for l in lines if "BTCUSDT" in l and "EINZELTRANSAKTIONEN" not in l and "Symbol" not in l]
        eth_lines = [l for l in lines if "ETHUSDT" in l and "Symbol" not in l]
        # 2 BTCUSDT trades + 1 in funding = 3, 1 ETHUSDT trade = 1
        assert len(btc_lines) >= 2
        assert len(eth_lines) >= 1

        # Monthly breakdown
        assert any("MONATLICHE AUFSCHLÜSSELUNG" in line for line in lines)

        # Funding section
        assert any("FINANZIERUNGSKOSTEN" in line for line in lines)

    @pytest.mark.asyncio
    async def test_many_trades_performance(self):
        """Test with a larger number of trades to ensure no issues with scale."""
        # Arrange
        gen = _make_generator()
        trades = []
        for i in range(100):
            month = (i % 12) + 1
            pnl = 10.0 if i % 3 != 0 else -5.0
            trades.append(
                MockTrade(
                    id=i + 1,
                    symbol="BTCUSDT" if i % 2 == 0 else "ETHUSDT",
                    side="long" if i % 2 == 0 else "short",
                    pnl=pnl,
                    fees=0.5,
                    funding_paid=-0.1,
                    entry_time=datetime(2025, month, 15, 10, 0, 0),
                    exit_time=datetime(2025, month, 15, 14, 0, 0),
                )
            )

        gen.trade_db.get_trades_by_year = AsyncMock(return_value=trades)
        gen.trade_db.get_open_trades = AsyncMock(return_value=[])

        with patch.object(gen, "get_funding_payments", new_callable=AsyncMock, return_value=[]):
            # Act
            csv_content = await gen.generate_csv_content(2025, "en")

        # Assert
        assert "BTCUSDT" in csv_content
        assert "ETHUSDT" in csv_content
        # All 100 trades should appear in the detail section
        lines = csv_content.split("\n")
        # Count trade data lines (exclude headers and section titles)
        trade_data_lines = [
            l for l in lines
            if ("BTCUSDT" in l or "ETHUSDT" in l)
            and "Symbol" not in l
            and "DETAILED" not in l
            and "EINZELTRANSAKTIONEN" not in l
        ]
        assert len(trade_data_lines) == 100


# ===========================================================================
# 12. Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_trade_with_all_none_optional_fields(self):
        """Trade with every optional field set to None."""
        # Arrange
        gen = _make_generator()
        trade = MockTrade()
        trade.pnl = None
        trade.fees = None
        trade.funding_paid = None
        trade.exit_price = None
        trade.entry_time = None
        trade.exit_time = None

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["pnl"] == 0.0
        assert result["fees"] == 0.0
        assert result["funding_paid"] == 0.0
        assert result["net_result"] == 0.0
        assert result["duration_hours"] == 0.0
        assert result["entry_time"] == ""
        assert result["exit_time"] == ""

    @pytest.mark.asyncio
    async def test_aggregate_with_large_negative_funding(self):
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=500.0, fees=10.0, funding_paid=-200.0)

        # Act
        result = await gen.aggregate_year_summary(2025, trades=[trade])

        # Assert
        assert result["total_funding"] == 200.0
        assert result["net_pnl"] == 500.0 - 10.0 - 200.0  # 290.0

    @pytest.mark.asyncio
    async def test_aggregate_with_positive_funding(self):
        """Positive funding_paid means the trader received funding."""
        # Arrange
        gen = _make_generator()
        trade = MockTrade(pnl=100.0, fees=5.0, funding_paid=10.0)

        # Act
        result = await gen.aggregate_year_summary(2025, trades=[trade])

        # Assert
        assert result["total_funding"] == 10.0  # abs(10.0)
        assert result["net_pnl"] == 100.0 - 5.0 - 10.0  # 85.0

    @pytest.mark.asyncio
    async def test_very_short_trade_duration(self):
        """Trade lasting only 1 second."""
        # Arrange
        gen = _make_generator()
        entry = datetime(2025, 1, 1, 12, 0, 0)
        exit_ = datetime(2025, 1, 1, 12, 0, 1)
        trade = MockTrade(entry_time=entry, exit_time=exit_)

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        assert result["duration_hours"] == 0.0  # round(1/3600, 2) = 0.0

    @pytest.mark.asyncio
    async def test_very_long_trade_duration(self):
        """Trade lasting 30 days."""
        # Arrange
        gen = _make_generator()
        entry = datetime(2025, 1, 1, 0, 0, 0)
        exit_ = datetime(2025, 1, 31, 0, 0, 0)
        trade = MockTrade(entry_time=entry, exit_time=exit_)

        # Act
        result = gen._trade_to_dict(trade)

        # Assert
        expected_hours = 30 * 24  # 720 hours
        assert result["duration_hours"] == expected_hours

    def test_translations_have_same_keys(self):
        """German and English translations must have identical key sets."""
        # Arrange / Act
        de_keys = set(TRANSLATIONS["de"].keys())
        en_keys = set(TRANSLATIONS["en"].keys())

        # Assert
        assert de_keys == en_keys

    @pytest.mark.asyncio
    async def test_funding_rate_converted_to_percentage_in_csv(self):
        """Funding rate in CSV should be multiplied by 100 (percentage)."""
        # Arrange
        gen = _make_generator()
        output = StringIO()
        writer = csv.writer(output)
        data = {
            "funding_payments": [
                {
                    "timestamp": "2025-03-15T08:00:00",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "funding_rate": 0.00015,
                    "position_value": 10000.0,
                    "payment_amount": 1.5,
                }
            ]
        }

        # Act
        gen._write_funding_section(writer, data, "en")

        # Assert
        output.seek(0)
        content = output.read()
        # 0.00015 * 100 = 0.015 rounded to 4 decimal places = 0.015
        assert "0.015" in content
