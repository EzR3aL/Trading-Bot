"""Tests for Bitget cancel_position_tpsl.

Implementation calls cancel-plan-order once per plan type with
``{symbol, productType, planType}``. This is the form Bitget's demo API
actually accepts — the orderIdList variant silently no-ops.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bitget.client import BitgetExchangeClient


@pytest.fixture
def client():
    return BitgetExchangeClient(api_key="test", api_secret="test", passphrase="test", demo_mode=True)


@pytest.mark.asyncio
async def test_cancel_tpsl_iterates_all_plan_types(client):
    """Should call cancel-plan-order once per known plan type."""
    cancelled_types = []

    async def mock_request(method, endpoint, **kwargs):
        if "cancel-plan-order" in endpoint:
            cancelled_types.append(kwargs.get("data", {}).get("planType"))
            return {"successList": [{"orderId": "111"}], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")

    assert result is True
    # Current cancel set: pos_profit, pos_loss, moving_plan, profit_plan, loss_plan
    assert set(cancelled_types) == {"pos_profit", "pos_loss", "moving_plan", "profit_plan", "loss_plan"}


@pytest.mark.asyncio
async def test_cancel_tpsl_returns_true_when_nothing_to_cancel(client):
    """Empty successList should still return True (best-effort semantics)."""
    async def mock_request(method, endpoint, **kwargs):
        if "cancel-plan-order" in endpoint:
            return {"successList": [], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    assert await client.cancel_position_tpsl("ETHUSDT", side="long") is True


@pytest.mark.asyncio
async def test_cancel_tpsl_handles_api_errors_gracefully(client):
    """Best-effort: individual cancel failures should not abort the loop."""
    call_count = 0

    async def mock_request(method, endpoint, **kwargs):
        nonlocal call_count
        if "cancel-plan-order" in endpoint:
            call_count += 1
            if call_count == 1:
                raise Exception("API error")
            return {"successList": [], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")

    assert result is True
    assert call_count == 5  # all 5 plan types attempted despite first failure


@pytest.mark.asyncio
async def test_cancel_tpsl_payload_fields(client):
    """Payload must carry symbol, productType, planType."""
    payloads = []

    async def mock_request(method, endpoint, **kwargs):
        if "cancel-plan-order" in endpoint:
            payloads.append(kwargs.get("data", {}))
            return {"successList": [], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert len(payloads) == 5
    for p in payloads:
        assert p["symbol"] == "BTCUSDT"
        assert "productType" in p
        assert "planType" in p


@pytest.mark.asyncio
async def test_cancel_native_trailing_stop_only(client):
    """cancel_native_trailing_stop must cancel only moving_plan, leaving TP/SL intact."""
    cancelled = []

    async def mock_request(method, endpoint, **kwargs):
        if "cancel-plan-order" in endpoint:
            cancelled.append(kwargs.get("data", {}).get("planType"))
            return {"successList": [{"orderId": "999"}], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    assert await client.cancel_native_trailing_stop("ETHUSDT", "long") is True
    assert cancelled == ["moving_plan"]


# ==================== Pattern C log-level classification (issue #225) ====================


@pytest.mark.asyncio
async def test_cancel_benign_no_match_stays_at_debug(client, caplog):
    """A 'no matching plan' error must log at DEBUG (legitimate no-op)."""
    import logging
    caplog.set_level(logging.DEBUG, logger="src.exchanges.bitget.client")

    async def mock_request(method, endpoint, **kwargs):
        raise Exception("40768 order does not exist")

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")

    assert result is True
    warn_records = [r for r in caplog.records if r.levelno >= logging.WARNING
                    and "cancel" in r.getMessage().lower()]
    assert warn_records == [], (
        f"Benign 'order does not exist' must not escalate to WARN; got: "
        f"{[r.getMessage() for r in warn_records]}"
    )


@pytest.mark.asyncio
async def test_cancel_real_error_escalates_to_warn(client, caplog):
    """A network/auth failure must log at WARN so a real stale plan is visible."""
    import logging
    caplog.set_level(logging.DEBUG, logger="src.exchanges.bitget.client")

    async def mock_request(method, endpoint, **kwargs):
        raise Exception("HTTP 500 Internal Server Error")

    client._request = AsyncMock(side_effect=mock_request)
    await client.cancel_position_tpsl("ETHUSDT", side="long")

    warn_records = [r for r in caplog.records if r.levelno >= logging.WARNING
                    and "cancel" in r.getMessage().lower()]
    assert warn_records, "Real cancel failure must escalate to WARN (Pattern C)"
    assert any("FAILED" in r.getMessage() for r in warn_records)
