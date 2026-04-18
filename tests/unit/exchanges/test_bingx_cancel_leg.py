"""Tests for BingX leg-specific cancel (``cancel_tp_only`` / ``cancel_sl_only``).

Epic #188 follow-up to #192: clearing the TP leg via the dashboard must not
collaterally cancel SL or trailing orders on the exchange. Mirrors the
Bitget leg-scoped cancel introduced in the same epic.

Mocks ``_request`` directly — matching the pattern already used by
``test_bingx_cancel_tpsl.py`` in this suite.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==",
)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bingx.client import BingXClient


@pytest.fixture
def client():
    return BingXClient(api_key="test", api_secret="test", demo_mode=True)


def _mixed_orders(symbol: str = "BTC-USDT", pos_side: str = "LONG") -> dict:
    """Build an open_orders response with one TP, one SL, one trailing."""
    return {
        "orders": [
            {
                "orderId": "tp-111",
                "symbol": symbol,
                "type": "TAKE_PROFIT_MARKET",
                "positionSide": pos_side,
            },
            {
                "orderId": "sl-222",
                "symbol": symbol,
                "type": "STOP_MARKET",
                "positionSide": pos_side,
            },
            {
                "orderId": "trail-333",
                "symbol": symbol,
                "type": "TRAILING_STOP_MARKET",
                "positionSide": pos_side,
            },
        ],
    }


def _capturing_mock(open_orders: dict, cancelled_ids: list):
    """Return a side-effect fn that serves open_orders and records DELETEs."""

    async def mock_request(method, endpoint, **kwargs):
        if "openOrders" in endpoint:
            return open_orders
        if method == "DELETE":
            cancelled_ids.append(kwargs.get("params", {}).get("orderId"))
            return {}
        return {}

    return mock_request


@pytest.mark.asyncio
async def test_cancel_tp_only_targets_only_take_profit_orders(client):
    """cancel_tp_only must cancel only TAKE_PROFIT_MARKET — leave SL + trailing."""
    cancelled: list[str] = []
    client._request = AsyncMock(
        side_effect=_capturing_mock(_mixed_orders(), cancelled),
    )

    result = await client.cancel_tp_only("BTC-USDT", side="long")

    assert result is True
    assert cancelled == ["tp-111"]


@pytest.mark.asyncio
async def test_cancel_sl_only_targets_only_stop_orders(client):
    """cancel_sl_only must cancel only STOP_MARKET — leave TP + trailing."""
    cancelled: list[str] = []
    client._request = AsyncMock(
        side_effect=_capturing_mock(_mixed_orders(), cancelled),
    )

    result = await client.cancel_sl_only("BTC-USDT", side="long")

    assert result is True
    assert cancelled == ["sl-222"]


@pytest.mark.asyncio
async def test_cancel_tp_only_also_matches_tp_limit_variant(client):
    """The ``TAKE_PROFIT`` type (limit variant) must also be cancelled."""
    cancelled: list[str] = []
    open_orders = {
        "orders": [
            {
                "orderId": "tp-market-1",
                "symbol": "BTC-USDT",
                "type": "TAKE_PROFIT_MARKET",
                "positionSide": "LONG",
            },
            {
                "orderId": "tp-limit-2",
                "symbol": "BTC-USDT",
                "type": "TAKE_PROFIT",
                "positionSide": "LONG",
            },
            {
                "orderId": "sl-1",
                "symbol": "BTC-USDT",
                "type": "STOP",
                "positionSide": "LONG",
            },
        ],
    }
    client._request = AsyncMock(
        side_effect=_capturing_mock(open_orders, cancelled),
    )

    await client.cancel_tp_only("BTC-USDT", side="long")

    assert sorted(cancelled) == ["tp-limit-2", "tp-market-1"]


@pytest.mark.asyncio
async def test_cancel_tp_only_filters_by_position_side(client):
    """With mixed hedge-mode sides, only matching positionSide must be cancelled."""
    cancelled: list[str] = []
    open_orders = {
        "orders": [
            {
                "orderId": "long-tp",
                "symbol": "BTC-USDT",
                "type": "TAKE_PROFIT_MARKET",
                "positionSide": "LONG",
            },
            {
                "orderId": "short-tp",
                "symbol": "BTC-USDT",
                "type": "TAKE_PROFIT_MARKET",
                "positionSide": "SHORT",
            },
        ],
    }
    client._request = AsyncMock(
        side_effect=_capturing_mock(open_orders, cancelled),
    )

    await client.cancel_tp_only("BTC-USDT", side="long")
    assert cancelled == ["long-tp"]

    cancelled.clear()
    client._request = AsyncMock(
        side_effect=_capturing_mock(open_orders, cancelled),
    )
    await client.cancel_tp_only("BTC-USDT", side="short")
    assert cancelled == ["short-tp"]


@pytest.mark.asyncio
async def test_cancel_tp_only_no_orders_returns_true(client):
    """Empty open_orders list is a legitimate no-op."""
    client._request = AsyncMock(return_value={"orders": []})

    result = await client.cancel_tp_only("BTC-USDT", side="long")

    assert result is True


@pytest.mark.asyncio
async def test_cancel_sl_only_no_orders_returns_true(client):
    """Empty open_orders list is a legitimate no-op for SL-only too."""
    client._request = AsyncMock(return_value={"orders": []})

    result = await client.cancel_sl_only("BTC-USDT", side="long")

    assert result is True


@pytest.mark.asyncio
async def test_cancel_tp_only_logs_warn_on_per_order_failure(client, caplog):
    """Per-order cancel failure must not abort the loop — best-effort semantics.

    Response has two TP orders. First DELETE raises; second succeeds. The
    method still returns True, and the failure is recorded at WARNING so
    the operator can investigate.
    """
    open_orders = {
        "orders": [
            {
                "orderId": "tp-fail",
                "symbol": "BTC-USDT",
                "type": "TAKE_PROFIT_MARKET",
                "positionSide": "LONG",
            },
            {
                "orderId": "tp-ok",
                "symbol": "BTC-USDT",
                "type": "TAKE_PROFIT_MARKET",
                "positionSide": "LONG",
            },
        ],
    }
    cancel_calls = 0

    async def mock_request(method, endpoint, **kwargs):
        nonlocal cancel_calls
        if "openOrders" in endpoint:
            return open_orders
        if method == "DELETE":
            cancel_calls += 1
            if cancel_calls == 1:
                raise Exception("Cancel failed: rate-limit")
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    import logging
    with caplog.at_level(logging.WARNING, logger="src.exchanges.bingx.client"):
        result = await client.cancel_tp_only("BTC-USDT", side="long")

    assert result is True
    assert cancel_calls == 2  # second attempt ran despite first failure
    assert any(
        "Failed to cancel BingX order tp-fail" in rec.message
        for rec in caplog.records
    ), f"expected WARN log for tp-fail, got: {[r.message for r in caplog.records]}"


@pytest.mark.asyncio
async def test_cancel_tp_only_handles_open_orders_api_error(client):
    """If the open_orders query itself fails, return False (cannot know state)."""
    client._request = AsyncMock(side_effect=Exception("API timeout"))

    result = await client.cancel_tp_only("BTC-USDT", side="long")

    assert result is False


@pytest.mark.asyncio
async def test_cancel_tp_only_matches_both_position_side_oneway(client):
    """One-way / VST mode emits ``positionSide == BOTH`` — must still cancel."""
    cancelled: list[str] = []
    open_orders = {
        "orders": [
            {
                "orderId": "tp-both",
                "symbol": "BTC-USDT",
                "type": "TAKE_PROFIT_MARKET",
                "positionSide": "BOTH",
            },
        ],
    }
    client._request = AsyncMock(
        side_effect=_capturing_mock(open_orders, cancelled),
    )

    await client.cancel_tp_only("BTC-USDT", side="long")

    assert cancelled == ["tp-both"]
