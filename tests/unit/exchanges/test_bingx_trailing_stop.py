"""Tests for BingX place_trailing_stop — #133 regression.

BingX rejects orders that send both ``price`` and ``priceRate`` in the same
TRAILING_STOP_MARKET request (error 109400). The correct field for activation
is ``activationPrice``, per BingX's own GitHub docs issue:
https://github.com/BingX-API/BingX-swap-api-doc/issues/28
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bingx.client import BingXClient


@pytest.fixture
def client():
    return BingXClient(api_key="test", api_secret="test", demo_mode=True)


@pytest.mark.asyncio
async def test_place_trailing_stop_uses_activationPrice_not_price(client, monkeypatch):
    """Regression: the order payload must contain activationPrice, never price.

    Sending `price` alongside `priceRate` triggers BingX error 109400 because
    BingX treats `price` as "fixed USDT trail distance" and refuses to combine
    it with the percentage-based `priceRate`.
    """
    captured_payload = {}

    async def fake_request(method, endpoint, **kwargs):
        if "openOrders" in endpoint:
            return {"orders": []}
        if "trade/order" in endpoint and method == "POST":
            captured_payload.update(kwargs.get("data", {}))
            return {"order": {"orderId": "9999"}}
        return {}

    monkeypatch.setattr(client, "_request", AsyncMock(side_effect=fake_request))
    monkeypatch.setattr(client, "_round_quantity", lambda v: v)

    await client.place_trailing_stop(
        symbol="BTC-USDT",
        hold_side="long",
        size=0.5,
        callback_ratio=3.10,
        trigger_price=70526.31,
    )

    assert "activationPrice" in captured_payload, (
        "Must use 'activationPrice' field (BingX docs). Got: " + str(captured_payload)
    )
    assert "price" not in captured_payload, (
        "Must NOT use 'price' field — that means 'USDT trail distance' and "
        "conflicts with priceRate (error 109400). Got: " + str(captured_payload)
    )
    assert captured_payload["activationPrice"] == "70526.31"
    assert captured_payload["priceRate"] == str(round(3.10 / 100, 4))
    assert captured_payload["type"] == "TRAILING_STOP_MARKET"


@pytest.mark.asyncio
async def test_place_trailing_stop_short_position(client, monkeypatch):
    """SHORT positions must use BUY close_side and SHORT positionSide."""
    captured_payload = {}

    async def fake_request(method, endpoint, **kwargs):
        if "openOrders" in endpoint:
            return {"orders": []}
        if "trade/order" in endpoint and method == "POST":
            captured_payload.update(kwargs.get("data", {}))
            return {"order": {"orderId": "9999"}}
        return {}

    monkeypatch.setattr(client, "_request", AsyncMock(side_effect=fake_request))
    monkeypatch.setattr(client, "_round_quantity", lambda v: v)

    await client.place_trailing_stop(
        symbol="ETH-USDT",
        hold_side="short",
        size=1.0,
        callback_ratio=2.5,
        trigger_price=2000.0,
    )

    assert captured_payload["side"] == "BUY"
    assert captured_payload["positionSide"] == "SHORT"
    assert captured_payload["activationPrice"] == "2000.0"
