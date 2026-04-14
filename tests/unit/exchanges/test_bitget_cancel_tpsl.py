"""Tests for Bitget cancel_position_tpsl — hedge-mode-safe two-step cancel.

The current implementation lists pending plans via ``orders-plan-pending``,
filters by ``posSide`` matching the requested side, then cancels each by
``orderId`` via cancel-plan-order with ``orderIdList``. One-shot
``{symbol, planType}`` cancellation silently no-ops for moving_plan in
hedge mode, which is why we switched to the orderIdList form.
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


def _plan(plan_type, pos_side, order_id):
    return {
        "planType": plan_type,
        "posSide": pos_side,
        "orderId": order_id,
        "planStatus": "live",
    }


@pytest.mark.asyncio
async def test_cancel_tpsl_cancels_all_matching_plan_types(client):
    """All long-side TP/SL/moving plans should end up in orderIdList."""
    pending = [
        _plan("pos_profit", "long", "111"),
        _plan("pos_loss", "long", "222"),
        _plan("moving_plan", "long", "333"),
    ]
    cancel_payload = {}

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-pending" in endpoint:
            return {"entrustedList": pending}
        if "cancel-plan-order" in endpoint:
            cancel_payload.update(kwargs.get("data", {}))
            return {"successList": [{"orderId": p["orderId"]} for p in pending], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")

    assert result is True
    order_ids = sorted(x["orderId"] for x in cancel_payload["orderIdList"])
    assert order_ids == ["111", "222", "333"]


@pytest.mark.asyncio
async def test_cancel_tpsl_filters_by_pos_side(client):
    """Short-side plans must not be cancelled when side=long is requested."""
    pending = [
        _plan("moving_plan", "long", "111"),
        _plan("moving_plan", "short", "999"),  # opposite side — keep alive
    ]
    cancel_payload = {}

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-pending" in endpoint:
            return {"entrustedList": pending}
        if "cancel-plan-order" in endpoint:
            cancel_payload.update(kwargs.get("data", {}))
            return {"successList": [{"orderId": "111"}], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    await client.cancel_position_tpsl("ETHUSDT", side="long")

    order_ids = [x["orderId"] for x in cancel_payload["orderIdList"]]
    assert order_ids == ["111"]


@pytest.mark.asyncio
async def test_cancel_tpsl_returns_true_when_nothing_to_cancel(client):
    """Empty pending list should short-circuit without calling cancel endpoint."""
    cancel_called = False

    async def mock_request(method, endpoint, **kwargs):
        nonlocal cancel_called
        if "orders-plan-pending" in endpoint:
            return {"entrustedList": []}
        if "cancel-plan-order" in endpoint:
            cancel_called = True
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")

    assert result is True
    assert cancel_called is False


@pytest.mark.asyncio
async def test_cancel_tpsl_handles_list_error(client):
    """Failure of the pending-list query should return False."""
    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-pending" in endpoint:
            raise Exception("list API down")
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    result = await client.cancel_position_tpsl("ETHUSDT", side="long")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_includes_symbol_and_product_type(client):
    """Cancel payload must carry symbol, productType, marginCoin."""
    pending = [_plan("moving_plan", "long", "555")]
    cancel_data = {}

    async def mock_request(method, endpoint, **kwargs):
        if "orders-plan-pending" in endpoint:
            return {"entrustedList": pending}
        if "cancel-plan-order" in endpoint:
            cancel_data.update(kwargs.get("data", {}))
            return {"successList": [{"orderId": "555"}], "failureList": []}
        return {}

    client._request = AsyncMock(side_effect=mock_request)
    await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert cancel_data["symbol"] == "BTCUSDT"
    assert "productType" in cancel_data
    assert cancel_data["marginCoin"] == "USDT"
