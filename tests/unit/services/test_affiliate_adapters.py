"""Unit tests for affiliate revenue adapters (mocked HTTP)."""

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.services.affiliate.bingx_fetcher import BingxAffiliateAdapter
from src.services.affiliate.bitget_fetcher import BitgetAffiliateAdapter
from src.services.affiliate.bitunix_fetcher import BitunixAffiliateAdapter
from src.services.affiliate.weex_fetcher import WeexAffiliateAdapter


def _mock_session(payload):
    """Create an aiohttp.ClientSession context manager that returns `payload`."""
    response = MagicMock()
    response.json = AsyncMock(return_value=payload)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=response)
    session.post = MagicMock(return_value=response)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=session)


@pytest.mark.asyncio
async def test_bitget_returns_not_configured_when_keys_missing():
    a = BitgetAffiliateAdapter(api_key="", api_secret="", passphrase="")
    res = await a.fetch(date.today() - timedelta(days=1), date.today())
    assert res.status == "not_configured"
    assert res.rows == []


@pytest.mark.asyncio
async def test_bitget_aggregates_per_day():
    from datetime import datetime, time, timezone
    today = date.today()
    ts1 = int(datetime.combine(today, time(10, 0), tzinfo=timezone.utc).timestamp() * 1000)
    ts2 = int(datetime.combine(today, time(14, 0), tzinfo=timezone.utc).timestamp() * 1000)

    payload = {
        "code": "00000",
        "msg": "ok",
        "data": [
            {"cTime": ts1, "commission": "1.5"},
            {"cTime": ts2, "commission": "2.5"},
        ],
    }
    a = BitgetAffiliateAdapter(api_key="k", api_secret="s", passphrase="p")
    with patch("src.services.affiliate.bitget_fetcher.aiohttp.ClientSession", _mock_session(payload)):
        res = await a.fetch(today - timedelta(days=1), today)
    assert res.status == "ok"
    assert len(res.rows) == 1
    assert res.rows[0].day == today
    assert res.rows[0].amount_usd == 4.0


@pytest.mark.asyncio
async def test_bitget_propagates_api_error():
    payload = {"code": "40001", "msg": "Invalid signature"}
    a = BitgetAffiliateAdapter(api_key="k", api_secret="s", passphrase="p")
    with patch("src.services.affiliate.bitget_fetcher.aiohttp.ClientSession", _mock_session(payload)):
        res = await a.fetch(date.today() - timedelta(days=1), date.today())
    assert res.status == "error"
    assert "40001" in res.error


@pytest.mark.asyncio
async def test_weex_clamps_to_90_day_range():
    a = WeexAffiliateAdapter(api_key="k", api_secret="s", passphrase="p")
    payload = {"code": "0", "data": {"list": [], "pages": 1}}
    with patch("src.services.affiliate.weex_fetcher.aiohttp.ClientSession", _mock_session(payload)):
        res = await a.fetch(date.today() - timedelta(days=400), date.today())
    assert res.status == "ok"
    assert res.rows == []


@pytest.mark.asyncio
async def test_bingx_not_configured_when_no_creds():
    a = BingxAffiliateAdapter(api_key="", api_secret="")
    res = await a.fetch(date.today() - timedelta(days=1), date.today())
    assert res.status == "not_configured"


@pytest.mark.asyncio
async def test_bingx_includes_source_key_header_when_set():
    a = BingxAffiliateAdapter(api_key="k", api_secret="s", source_key="src-123")
    payload = {"code": "0", "data": {"list": []}}
    mock_factory = _mock_session(payload)
    with patch("src.services.affiliate.bingx_fetcher.aiohttp.ClientSession", mock_factory):
        await a.fetch(date.today() - timedelta(days=1), date.today())
    session = mock_factory.return_value
    headers = session.get.call_args.kwargs.get("headers") or session.get.call_args[1]["headers"]
    assert headers["X-BX-APIKEY"] == "k"
    assert headers["X-SOURCE-KEY"] == "src-123"


@pytest.mark.asyncio
async def test_bitunix_always_unsupported():
    a = BitunixAffiliateAdapter()
    assert not a.configured
    res = await a.fetch(date.today() - timedelta(days=1), date.today())
    assert res.status == "unsupported"
    assert "Bitunix" in res.error
