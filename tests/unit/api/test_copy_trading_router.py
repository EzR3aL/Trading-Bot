"""Tests for /api/copy-trading and /api/exchanges/{exchange}/leverage-limits."""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ENCRYPTION_KEY", "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo=")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from src.api.routers.copy_trading import router as copy_trading_router  # noqa: E402
from src.auth.dependencies import get_current_user  # noqa: E402
from src.models.database import User  # noqa: E402


@pytest_asyncio.fixture
async def app():
    test_app = FastAPI(title="Test Copy Trading API")
    test_app.include_router(copy_trading_router)

    fake_user = User(id=1, username="tester", email="t@test.com",
                     password_hash="x", role="user", is_active=True)
    test_app.dependency_overrides[get_current_user] = lambda: fake_user

    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.mark.asyncio
async def test_validate_source_rejects_bad_address(client):
    r = await client.post("/api/copy-trading/validate-source", json={
        "wallet": "not-an-address",
        "target_exchange": "bitget",
    })
    assert r.status_code == 400
    assert "Wallet-Adresse" in r.json()["detail"]


@pytest.mark.asyncio
async def test_validate_source_returns_preview(client):
    fake_fills = [
        type("F", (), {"coin": "BTC", "time_ms": 1712568000000, "side": "long",
                       "size": 0.5, "price": 67000, "is_entry": True, "hash": "0xa"})(),
        type("F", (), {"coin": "HYPE", "time_ms": 1712568000000, "side": "long",
                       "size": 100, "price": 12, "is_entry": True, "hash": "0xb"})(),
    ]
    with patch(
        "src.api.routers.copy_trading.HyperliquidWalletTracker"
    ) as TrackerCls, patch(
        "src.api.routers.copy_trading.get_exchange_symbols",
        new=AsyncMock(return_value=["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
    ):
        instance = TrackerCls.return_value
        instance.get_open_positions = AsyncMock(return_value=[])
        instance.get_fills_since = AsyncMock(return_value=fake_fills)
        instance.close = AsyncMock()

        r = await client.post("/api/copy-trading/validate-source", json={
            "wallet": "0x" + "ab" * 20,
            "target_exchange": "bitget",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["trades_30d"] == 2
    assert "BTC" in body["available"]
    assert "HYPE" in body["unavailable"]


@pytest.mark.asyncio
async def test_leverage_limits_endpoint(client):
    r = await client.get("/api/exchanges/bitget/leverage-limits", params={"symbol": "BTCUSDT"})
    assert r.status_code == 200
    assert r.json()["max_leverage"] == 125


@pytest.mark.asyncio
async def test_leverage_limits_unknown_exchange(client):
    r = await client.get("/api/exchanges/kraken/leverage-limits", params={"symbol": "BTCUSDT"})
    assert r.status_code == 404
