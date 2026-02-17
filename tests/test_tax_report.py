"""
Tests for tax report endpoints.

Covers tax report generation, demo_mode filtering, CSV download,
and empty year results.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Tax report JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tax_report_current_year(client, auth_headers, sample_trades):
    """Get tax report for the current year returns correct data."""
    current_year = datetime.utcnow().year
    response = await client.get(
        "/api/tax-report",
        headers=auth_headers,
        params={"year": current_year},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["year"] == current_year
    assert "total_trades" in data
    assert "total_pnl" in data
    assert "total_fees" in data
    assert "total_funding" in data
    assert "net_pnl" in data
    assert "months" in data
    assert isinstance(data["months"], list)


@pytest.mark.asyncio
async def test_get_tax_report_default_year(client, auth_headers, sample_trades):
    """Get tax report without specifying year defaults to current year."""
    response = await client.get("/api/tax-report", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["year"] == datetime.utcnow().year


@pytest.mark.asyncio
async def test_get_tax_report_totals(client, auth_headers, sample_trades):
    """Tax report totals are correctly computed from closed trades."""
    response = await client.get("/api/tax-report", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    # Total PnL = sum of all closed trades pnl
    # 3 closed trades: +10, +10, -20 = 0
    assert data["total_trades"] == 3
    assert data["total_pnl"] == pytest.approx(0.0, abs=0.01)


@pytest.mark.asyncio
async def test_get_tax_report_monthly_breakdown(client, auth_headers, sample_trades):
    """Tax report includes a monthly breakdown."""
    response = await client.get("/api/tax-report", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    for month in data["months"]:
        assert "month" in month
        assert "trades" in month
        assert "pnl" in month
        assert "fees" in month
        assert "funding" in month


# ---------------------------------------------------------------------------
# Demo mode filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tax_report_demo_mode_true(client, auth_headers, sample_trades):
    """Tax report filtered to demo_mode=true shows only demo trades."""
    response = await client.get(
        "/api/tax-report",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert response.status_code == 200
    data = response.json()

    # 2 closed demo trades
    assert data["total_trades"] == 2
    assert data["total_pnl"] == pytest.approx(20.0, abs=0.01)


@pytest.mark.asyncio
async def test_get_tax_report_demo_mode_false(client, auth_headers, sample_trades):
    """Tax report filtered to demo_mode=false shows only live trades."""
    response = await client.get(
        "/api/tax-report",
        headers=auth_headers,
        params={"demo_mode": False},
    )
    assert response.status_code == 200
    data = response.json()

    # 1 closed live trade
    assert data["total_trades"] == 1
    assert data["total_pnl"] == pytest.approx(-20.0, abs=0.01)


# ---------------------------------------------------------------------------
# Empty year
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tax_report_empty_year(client, auth_headers, test_user):
    """Tax report for a year with no trades returns zeroed values."""
    response = await client.get(
        "/api/tax-report",
        headers=auth_headers,
        params={"year": 2020},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["year"] == 2020
    assert data["total_trades"] == 0
    assert data["total_pnl"] == 0
    assert data["total_fees"] == 0
    assert data["total_funding"] == 0
    assert data["net_pnl"] == 0
    assert data["months"] == []


# ---------------------------------------------------------------------------
# CSV download
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_tax_report_csv(client, auth_headers, sample_trades):
    """Download tax report as CSV returns valid bilingual CSV content."""
    response = await client.get("/api/tax-report/csv", headers=auth_headers)
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]

    content = response.text
    lines = content.strip().split("\n")

    # Bilingual CSV format: has STEUERREPORT header, summary, monthly breakdown, trade details
    assert "STEUERREPORT" in lines[0] or "TAX REPORT" in lines[0]

    # Should contain trade detail section with header row containing Symbol
    trade_header_found = any("Symbol" in line for line in lines)
    assert trade_header_found

    # Should contain the 3 closed trades in the detail section
    trade_data_lines = [l for l in lines if "BTCUSDT" in l or "ETHUSDT" in l]
    assert len(trade_data_lines) == 3


@pytest.mark.asyncio
async def test_download_csv_with_demo_filter(client, auth_headers, sample_trades):
    """CSV download with demo_mode filter returns filtered data."""
    response = await client.get(
        "/api/tax-report/csv",
        headers=auth_headers,
        params={"demo_mode": True},
    )
    assert response.status_code == 200
    content = response.text
    lines = content.strip().split("\n")

    # Bilingual format has sections; trade detail section has 2 demo trades
    trade_data_lines = [l for l in lines if "BTCUSDT" in l or "ETHUSDT" in l]
    # Filter out header row that contains these as column names
    trade_data_lines = [l for l in trade_data_lines if "Richtung" not in l and "Side" not in l]
    assert len(trade_data_lines) == 2


@pytest.mark.asyncio
async def test_download_csv_empty_year(client, auth_headers, test_user):
    """CSV download for empty year returns bilingual report with no trade rows."""
    response = await client.get(
        "/api/tax-report/csv",
        headers=auth_headers,
        params={"year": 2020},
    )
    assert response.status_code == 200
    content = response.text
    lines = content.strip().split("\n")

    # Report still has header sections but no trade data
    assert "STEUERREPORT" in lines[0] or "TAX REPORT" in lines[0]
    # Trade count should be 0
    assert any("0" in line and "Trade Count" in line for line in lines)


@pytest.mark.asyncio
async def test_download_csv_content_disposition(client, auth_headers, sample_trades):
    """CSV download has correct Content-Disposition header."""
    current_year = datetime.utcnow().year
    response = await client.get(
        "/api/tax-report/csv",
        headers=auth_headers,
        params={"year": current_year},
    )
    assert response.status_code == 200
    disposition = response.headers.get("content-disposition", "")
    assert f"steuerreport_{current_year}.csv" in disposition


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tax_report_requires_auth(client, test_user):
    """Tax report endpoint requires authentication."""
    response = await client.get("/api/tax-report")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tax_report_csv_requires_auth(client, test_user):
    """Tax report CSV endpoint requires authentication."""
    response = await client.get("/api/tax-report/csv")
    assert response.status_code == 401
