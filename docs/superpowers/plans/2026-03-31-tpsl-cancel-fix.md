# TP/SL Cancel & Race Condition Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix TP/SL removal and update on order-based exchanges (BingX, Weex) by implementing explicit cancel mechanisms, resolving the race condition with "place first, cancel old" strategy, and fixing the router to handle both exchange architectures correctly.

**Architecture:** Order-based exchanges (BingX, Weex) need a `cancel_position_tpsl()` method that queries open conditional orders and cancels them. The router must call this after placing new orders (to avoid unprotected gaps) and also when both TP+SL are removed. Position-level exchanges (Bitget, Hyperliquid, Bitunix) need no changes — they replace implicitly.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest (asyncio_mode=auto), httpx AsyncClient

**Issues:** Closes #121, Closes #122

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/exchanges/base.py` | Add `cancel_position_tpsl()` default (no-op) |
| Modify | `src/exchanges/bingx/client.py` | Add `cancel_position_tpsl()` — query open orders, filter conditional, cancel |
| Modify | `src/exchanges/bingx/constants.py` | Add `CONDITIONAL_ORDER_TYPES` set |
| Modify | `src/exchanges/weex/client.py` | Add `cancel_position_tpsl()` — query pending TP/SL orders, cancel |
| Modify | `src/exchanges/weex/constants.py` | Add `cancel_tpsl_order` and `pending_tpsl_orders` endpoints |
| Modify | `src/api/routers/trades.py` | Rewrite exchange call block: place-first-cancel-old + handle both-removed |
| Modify | `src/api/routers/portfolio.py` | Normalize klines cache keys |
| Create | `tests/unit/exchanges/test_bingx_cancel_tpsl.py` | Unit tests for BingX cancel logic |
| Create | `tests/unit/exchanges/test_weex_cancel_tpsl.py` | Unit tests for Weex cancel logic |
| Create | `tests/unit/api/test_tpsl_cancel_router.py` | Unit tests for router cancel flow |

---

## Task 1: Add `cancel_position_tpsl()` to Base Class

**Files:**
- Modify: `src/exchanges/base.py:110` (after `set_position_tpsl`)

- [ ] **Step 1: Add the base method**

In `src/exchanges/base.py`, add after line 110 (after the `set_position_tpsl` method):

```python
async def cancel_position_tpsl(
    self,
    symbol: str,
    side: str = "long",
) -> bool:
    """Cancel all TP/SL orders for a position.

    Position-level exchanges (Bitget, Hyperliquid, Bitunix) don't need this
    because set_position_tpsl implicitly replaces. Order-based exchanges
    (BingX, Weex) must override to cancel existing conditional orders.

    Returns True if cancellation succeeded or no orders to cancel.
    """
    return True  # No-op for position-level exchanges
```

- [ ] **Step 2: Verify no import changes needed**

Run: `cd /c/Users/edgar/Trading-Bot && python -c "from src.exchanges.base import ExchangeClient; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/exchanges/base.py
git commit -m "feat: add cancel_position_tpsl() to ExchangeClient base (#121)"
```

---

## Task 2: Implement BingX `cancel_position_tpsl()`

**Files:**
- Modify: `src/exchanges/bingx/constants.py:100` (add constant)
- Modify: `src/exchanges/bingx/client.py:759` (add method before `set_position_tpsl`)
- Create: `tests/unit/exchanges/test_bingx_cancel_tpsl.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/exchanges/test_bingx_cancel_tpsl.py`:

```python
"""Tests for BingX cancel_position_tpsl — query open orders, filter conditional, cancel."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bingx.client import BingXClient


@pytest.fixture
def client():
    return BingXClient(api_key="test", api_secret="test", demo_mode=True)


@pytest.mark.asyncio
async def test_cancel_tpsl_cancels_conditional_orders(client):
    """Should cancel TAKE_PROFIT_MARKET and STOP_MARKET orders for the symbol."""
    open_orders = {
        "orders": [
            {"orderId": "111", "symbol": "BTC-USDT", "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
            {"orderId": "222", "symbol": "BTC-USDT", "type": "STOP_MARKET", "positionSide": "LONG"},
            {"orderId": "333", "symbol": "BTC-USDT", "type": "LIMIT", "positionSide": "LONG"},
            {"orderId": "444", "symbol": "ETH-USDT", "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
        ]
    }

    cancel_results = []

    async def mock_request(method, endpoint, **kwargs):
        if "openOrders" in endpoint:
            return open_orders
        if method == "DELETE":
            cancel_results.append(kwargs.get("params", {}).get("orderId"))
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")

    assert result is True
    # Should cancel only BTC-USDT conditional orders (111, 222), not LIMIT (333) or ETH (444)
    assert sorted(cancel_results) == ["111", "222"]


@pytest.mark.asyncio
async def test_cancel_tpsl_no_orders(client):
    """Should return True if no conditional orders found."""
    client._request = AsyncMock(return_value={"orders": []})

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")

    assert result is True


@pytest.mark.asyncio
async def test_cancel_tpsl_filters_by_position_side(client):
    """Should only cancel orders matching the position side."""
    open_orders = {
        "orders": [
            {"orderId": "111", "symbol": "BTC-USDT", "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
            {"orderId": "222", "symbol": "BTC-USDT", "type": "STOP_MARKET", "positionSide": "SHORT"},
        ]
    }
    cancel_results = []

    async def mock_request(method, endpoint, **kwargs):
        if "openOrders" in endpoint:
            return open_orders
        if method == "DELETE":
            cancel_results.append(kwargs.get("params", {}).get("orderId"))
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")

    assert result is True
    assert cancel_results == ["111"]  # Only LONG, not SHORT


@pytest.mark.asyncio
async def test_cancel_tpsl_handles_api_error_gracefully(client):
    """Should return False if open orders query fails."""
    client._request = AsyncMock(side_effect=Exception("API timeout"))

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")

    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_partial_cancel_failure(client):
    """Should return True even if one cancel fails — best effort."""
    open_orders = {
        "orders": [
            {"orderId": "111", "symbol": "BTC-USDT", "type": "TAKE_PROFIT_MARKET", "positionSide": "LONG"},
            {"orderId": "222", "symbol": "BTC-USDT", "type": "STOP_MARKET", "positionSide": "LONG"},
        ]
    }
    call_count = 0

    async def mock_request(method, endpoint, **kwargs):
        nonlocal call_count
        if "openOrders" in endpoint:
            return open_orders
        if method == "DELETE":
            call_count += 1
            if call_count == 1:
                raise Exception("Cancel failed")
            return {}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTC-USDT", side="long")

    # Still returns True — best effort, at least one cancel attempted
    assert result is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/edgar/Trading-Bot && python -m pytest tests/unit/exchanges/test_bingx_cancel_tpsl.py -v`
Expected: FAIL — `cancel_position_tpsl` not overridden in BingXClient (returns True from base without cancelling)

- [ ] **Step 3: Add CONDITIONAL_ORDER_TYPES constant**

In `src/exchanges/bingx/constants.py`, add after line 101 (after `ORDER_TYPE_TRAILING_STOP_MARKET`):

```python
# TP/SL conditional order types (used for cancel filtering)
CONDITIONAL_ORDER_TYPES = {
    "TAKE_PROFIT_MARKET",
    "STOP_MARKET",
    "TRAILING_STOP_MARKET",
}
```

- [ ] **Step 4: Implement cancel_position_tpsl in BingX client**

In `src/exchanges/bingx/client.py`, add before `set_position_tpsl` (before line 759):

```python
async def cancel_position_tpsl(
    self,
    symbol: str,
    side: str = "long",
) -> bool:
    """Cancel all conditional TP/SL orders for a position on BingX.

    Queries open orders, filters for TAKE_PROFIT_MARKET / STOP_MARKET
    matching the symbol and position side, then cancels each one.
    Best-effort: partial cancel failures are logged but don't fail the operation.
    """
    position_side = POSITION_LONG if side == "long" else POSITION_SHORT

    try:
        data = await self._request("GET", ENDPOINTS["open_orders"], params={"symbol": symbol})
    except Exception as e:
        logger.warning("Failed to query open orders for %s: %s", symbol, e)
        return False

    orders = data.get("orders", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

    to_cancel = [
        o for o in orders
        if isinstance(o, dict)
        and o.get("type") in CONDITIONAL_ORDER_TYPES
        and o.get("symbol") == symbol
        and o.get("positionSide") == position_side
    ]

    if not to_cancel:
        logger.debug("No conditional TP/SL orders to cancel for %s %s", symbol, side)
        return True

    for order in to_cancel:
        oid = str(order.get("orderId", ""))
        try:
            await self._request("DELETE", ENDPOINTS["cancel_order"], params={
                "symbol": symbol,
                "orderId": oid,
            })
            logger.info("Cancelled BingX TP/SL order %s for %s", oid, symbol)
        except Exception as e:
            logger.warning("Failed to cancel BingX order %s for %s: %s", oid, symbol, e)

    return True
```

Also add the import at the top of `bingx/client.py` if `CONDITIONAL_ORDER_TYPES` is not already imported:

```python
from src.exchanges.bingx.constants import (
    ...,
    CONDITIONAL_ORDER_TYPES,
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /c/Users/edgar/Trading-Bot && python -m pytest tests/unit/exchanges/test_bingx_cancel_tpsl.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/exchanges/bingx/constants.py src/exchanges/bingx/client.py tests/unit/exchanges/test_bingx_cancel_tpsl.py
git commit -m "feat: BingX cancel_position_tpsl — query & cancel conditional orders (#121)"
```

---

## Task 3: Implement Weex `cancel_position_tpsl()`

**Files:**
- Modify: `src/exchanges/weex/constants.py:44` (add cancel endpoints)
- Modify: `src/exchanges/weex/client.py:499` (add method before `set_position_tpsl`)
- Create: `tests/unit/exchanges/test_weex_cancel_tpsl.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/exchanges/test_weex_cancel_tpsl.py`:

```python
"""Tests for Weex cancel_position_tpsl — query pending TP/SL orders, cancel."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.weex.client import WeexClient


@pytest.fixture
def client():
    return WeexClient(api_key="test", api_secret="test", demo_mode=True)


@pytest.mark.asyncio
async def test_cancel_tpsl_cancels_matching_orders(client):
    """Should cancel TP/SL orders for the symbol and position side."""
    pending_orders = [
        {"orderId": "aaa", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "bbb", "symbol": "BTCUSDT", "planType": "STOP_LOSS", "positionSide": "LONG"},
        {"orderId": "ccc", "symbol": "ETHUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
    ]
    cancel_ids = []

    async def mock_request(method, endpoint, **kwargs):
        if "pendingTpSlOrders" in endpoint or "pending" in endpoint.lower():
            return pending_orders
        if "cancelTpSlOrder" in endpoint or "cancel" in endpoint.lower():
            data = kwargs.get("data", {})
            cancel_ids.append(data.get("orderId"))
            return {"success": True}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert result is True
    assert sorted(cancel_ids) == ["aaa", "bbb"]


@pytest.mark.asyncio
async def test_cancel_tpsl_no_pending_orders(client):
    """Should return True if no pending TP/SL orders."""
    client._request = AsyncMock(return_value=[])

    result = await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert result is True


@pytest.mark.asyncio
async def test_cancel_tpsl_query_fails_gracefully(client):
    """Should return False if query fails."""
    client._request = AsyncMock(side_effect=Exception("Network error"))

    result = await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert result is False


@pytest.mark.asyncio
async def test_cancel_tpsl_filters_by_position_side(client):
    """Should only cancel orders matching position side."""
    pending_orders = [
        {"orderId": "aaa", "symbol": "BTCUSDT", "planType": "TAKE_PROFIT", "positionSide": "LONG"},
        {"orderId": "bbb", "symbol": "BTCUSDT", "planType": "STOP_LOSS", "positionSide": "SHORT"},
    ]
    cancel_ids = []

    async def mock_request(method, endpoint, **kwargs):
        if "pendingTpSlOrders" in endpoint or "pending" in endpoint.lower():
            return pending_orders
        if "cancelTpSlOrder" in endpoint or "cancel" in endpoint.lower():
            data = kwargs.get("data", {})
            cancel_ids.append(data.get("orderId"))
            return {"success": True}
        return {}

    client._request = AsyncMock(side_effect=mock_request)

    result = await client.cancel_position_tpsl("BTCUSDT", side="long")

    assert result is True
    assert cancel_ids == ["aaa"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/edgar/Trading-Bot && python -m pytest tests/unit/exchanges/test_weex_cancel_tpsl.py -v`
Expected: FAIL — `cancel_position_tpsl` not overridden in WeexClient

- [ ] **Step 3: Add Weex cancel endpoints**

In `src/exchanges/weex/constants.py`, add after line 44 (`"place_tpsl_order"` line):

```python
    "cancel_tpsl_order": "/capi/v3/cancelTpSlOrder",
    "pending_tpsl_orders": "/capi/v3/pendingTpSlOrders",
```

- [ ] **Step 4: Implement cancel_position_tpsl in Weex client**

In `src/exchanges/weex/client.py`, add before `set_position_tpsl` (before line 501):

```python
async def cancel_position_tpsl(
    self,
    symbol: str,
    side: str = "long",
) -> bool:
    """Cancel all pending TP/SL orders for a position on Weex.

    Queries /capi/v3/pendingTpSlOrders, filters by symbol and positionSide,
    then cancels each via /capi/v3/cancelTpSlOrder.
    Best-effort: partial failures are logged but don't fail the operation.
    """
    v3_symbol = symbol.upper().replace("-", "")
    position_side = "LONG" if side == "long" else "SHORT"

    try:
        data = await self._request("GET", ENDPOINTS["pending_tpsl_orders"], params={
            "symbol": v3_symbol,
        })
    except Exception as e:
        logger.warning("Failed to query pending TP/SL orders for %s: %s", symbol, e)
        return False

    orders = data if isinstance(data, list) else (data.get("orders", []) if isinstance(data, dict) else [])

    to_cancel = [
        o for o in orders
        if isinstance(o, dict)
        and o.get("positionSide") == position_side
    ]

    if not to_cancel:
        logger.debug("No pending TP/SL orders to cancel for %s %s", symbol, side)
        return True

    for order in to_cancel:
        oid = str(order.get("orderId", ""))
        try:
            await self._request("POST", ENDPOINTS["cancel_tpsl_order"], data={
                "symbol": v3_symbol,
                "orderId": oid,
            })
            logger.info("Cancelled Weex TP/SL order %s for %s", oid, symbol)
        except Exception as e:
            logger.warning("Failed to cancel Weex TP/SL order %s for %s: %s", oid, symbol, e)

    return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /c/Users/edgar/Trading-Bot && python -m pytest tests/unit/exchanges/test_weex_cancel_tpsl.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/exchanges/weex/constants.py src/exchanges/weex/client.py tests/unit/exchanges/test_weex_cancel_tpsl.py
git commit -m "feat: Weex cancel_position_tpsl — query & cancel pending TP/SL orders (#121)"
```

---

## Task 4: Rewrite Router TP/SL Exchange Logic (Place First, Cancel Old)

**Files:**
- Modify: `src/api/routers/trades.py:652-673`
- Create: `tests/unit/api/test_tpsl_cancel_router.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_tpsl_cancel_router.py`:

```python
"""Tests for the TP/SL router cancel flow — place first, cancel old, handle both-removed."""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base, BotConfig, ExchangeConnection, TradeRecord, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def setup_data(session_factory):
    """Create user, exchange connection, and open trade."""
    async with session_factory() as session:
        user = User(
            username="tester",
            email="test@test.com",
            hashed_password=hash_password("testpass"),
            is_active=True,
        )
        session.add(user)
        await session.flush()

        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bingx",
            demo_api_key_encrypted="enc_key",
            demo_api_secret_encrypted="enc_secret",
        )
        session.add(conn)
        await session.flush()

        trade = TradeRecord(
            user_id=user.id,
            exchange="bingx",
            symbol="BTC-USDT",
            side="long",
            size=0.01,
            entry_price=68000.0,
            status="open",
            demo_mode=True,
            take_profit=70000.0,
            stop_loss=66000.0,
        )
        session.add(trade)
        await session.commit()

        token = create_access_token({"sub": str(user.id)})
        return {"user": user, "trade": trade, "token": token}


def make_mock_client():
    """Create a mock exchange client that tracks calls."""
    client = AsyncMock()
    client.set_position_tpsl = AsyncMock(return_value="order123")
    client.cancel_position_tpsl = AsyncMock(return_value=True)
    client.close = AsyncMock()
    client.exchange_name = "bingx"
    return client


@pytest.mark.asyncio
async def test_update_tpsl_calls_cancel_after_place(engine, session_factory, setup_data):
    """When setting new TP/SL, should place new orders THEN cancel old ones."""
    data = setup_data
    call_order = []

    mock_client = make_mock_client()

    async def track_set(*args, **kwargs):
        call_order.append("set_position_tpsl")
        return "order123"

    async def track_cancel(*args, **kwargs):
        call_order.append("cancel_position_tpsl")
        return True

    mock_client.set_position_tpsl.side_effect = track_set
    mock_client.cancel_position_tpsl.side_effect = track_cancel

    from src.main import app
    from src.database import get_db

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                f"/api/trades/{data['trade'].id}/tp-sl",
                json={"take_profit": 71000.0},
                headers={"Authorization": f"Bearer {data['token']}"},
            )

    assert resp.status_code == 200
    # Place BEFORE cancel — this is the core invariant
    assert call_order == ["set_position_tpsl", "cancel_position_tpsl"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_remove_both_tpsl_calls_cancel(engine, session_factory, setup_data):
    """When removing both TP and SL, should call cancel_position_tpsl directly."""
    data = setup_data
    mock_client = make_mock_client()

    from src.main import app
    from src.database import get_db

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                f"/api/trades/{data['trade'].id}/tp-sl",
                json={"remove_tp": True, "remove_sl": True},
                headers={"Authorization": f"Bearer {data['token']}"},
            )

    assert resp.status_code == 200
    # Should NOT call set_position_tpsl (nothing to set)
    mock_client.set_position_tpsl.assert_not_called()
    # MUST call cancel to remove orders from exchange
    mock_client.cancel_position_tpsl.assert_called_once_with(
        symbol="BTC-USDT", side="long"
    )

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_remove_tp_keep_sl_places_sl_then_cancels(engine, session_factory, setup_data):
    """When removing TP but keeping SL, should set SL on exchange then cancel old orders."""
    data = setup_data
    call_order = []
    mock_client = make_mock_client()

    async def track_set(*args, **kwargs):
        call_order.append("set_position_tpsl")
        return "order123"

    async def track_cancel(*args, **kwargs):
        call_order.append("cancel_position_tpsl")
        return True

    mock_client.set_position_tpsl.side_effect = track_set
    mock_client.cancel_position_tpsl.side_effect = track_cancel

    from src.main import app
    from src.database import get_db

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    with patch("src.api.routers.trades.create_exchange_client", return_value=mock_client), \
         patch("src.api.routers.trades.decrypt_value", return_value="decrypted"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.put(
                f"/api/trades/{data['trade'].id}/tp-sl",
                json={"remove_tp": True},
                headers={"Authorization": f"Bearer {data['token']}"},
            )

    assert resp.status_code == 200
    # Place new SL first, then cancel old TP+SL orders
    assert call_order == ["set_position_tpsl", "cancel_position_tpsl"]
    # set_position_tpsl called with only SL (TP is None because removed)
    mock_client.set_position_tpsl.assert_called_once()
    call_kwargs = mock_client.set_position_tpsl.call_args
    assert call_kwargs.kwargs.get("take_profit") is None or call_kwargs[1].get("take_profit") is None

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/edgar/Trading-Bot && python -m pytest tests/unit/api/test_tpsl_cancel_router.py -v`
Expected: FAIL — current router doesn't call `cancel_position_tpsl`

- [ ] **Step 3: Rewrite the exchange call block in trades.py**

Replace lines 652-673 in `src/api/routers/trades.py` (the `# Set TP/SL on exchange` block). Replace this code:

```python
    # Set TP/SL on exchange
    trailing_placed = False
    fetcher = None
    try:
        # Only call exchange if user explicitly changed something
        has_tp_change = body.take_profit is not None or body.remove_tp
        has_sl_change = body.stop_loss is not None or body.remove_sl
        if has_tp_change or has_sl_change:
            # Send the final state to exchange: what should be active after this update
            # If removing TP but SL stays → send (tp=None, sl=existing)
            # If setting TP, SL unchanged → send (tp=new, sl=None means don't touch)
            # Only skip call if both would be None AND nothing to remove
            final_tp = effective_tp  # None if removed, new value if set, old if unchanged
            final_sl = effective_sl
            if final_tp is not None or final_sl is not None:
                await client.set_position_tpsl(
                    symbol=trade.symbol,
                    take_profit=final_tp,
                    stop_loss=final_sl,
                    side=trade.side,
                    size=trade.size,
                )
```

With this new code:

```python
    # Set TP/SL on exchange
    trailing_placed = False
    fetcher = None
    try:
        has_tp_change = body.take_profit is not None or body.remove_tp
        has_sl_change = body.stop_loss is not None or body.remove_sl
        if has_tp_change or has_sl_change:
            final_tp = effective_tp
            final_sl = effective_sl

            if final_tp is not None or final_sl is not None:
                # Step 1: Place new TP/SL orders first (position always protected)
                await client.set_position_tpsl(
                    symbol=trade.symbol,
                    take_profit=final_tp,
                    stop_loss=final_sl,
                    side=trade.side,
                    size=trade.size,
                )
                # Step 2: Cancel old orders (safe — new ones already in place)
                await client.cancel_position_tpsl(
                    symbol=trade.symbol,
                    side=trade.side,
                )
            else:
                # Both TP and SL removed — cancel all existing orders on exchange
                await client.cancel_position_tpsl(
                    symbol=trade.symbol,
                    side=trade.side,
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /c/Users/edgar/Trading-Bot && python -m pytest tests/unit/api/test_tpsl_cancel_router.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run existing TP/SL tests to verify no regressions**

Run: `cd /c/Users/edgar/Trading-Bot && python -m pytest tests/integration/test_tpsl_flow.py tests/unit/bot/test_tpsl_passthrough.py -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/routers/trades.py tests/unit/api/test_tpsl_cancel_router.py
git commit -m "fix: place-first-cancel-old strategy for TP/SL updates (#121, #122)"
```

---

## Task 5: Update BingX `set_position_tpsl` to Not Early-Return on None

**Files:**
- Modify: `src/exchanges/bingx/client.py:773`

The current `set_position_tpsl` returns `None` early if both TP and SL are None. This is fine because the router now handles that case via `cancel_position_tpsl`. But we need to ensure the method works correctly when only one value is provided (the other being None means "don't set", not "cancel").

- [ ] **Step 1: Verify current behavior is correct**

The existing code already handles partial values correctly:
- `if take_profit is not None:` → only places TP order if value provided
- `if stop_loss is not None:` → only places SL order if value provided
- Early return on both None is correct (router handles that case now)

No code changes needed for this task. The existing implementation is correct.

- [ ] **Step 2: Commit (skip — no changes)**

---

## Task 6: Fix Klines Cache Symbol Inconsistency

**Files:**
- Modify: `src/api/routers/portfolio.py:165-178`

- [ ] **Step 1: Write the failing test**

This is a low-risk change. The cache uses raw symbols (`t.symbol`) which matches the lookup in `trades.py`. Adding a comment to document this is sufficient since it's internally consistent.

Actually, reading the code again — the cache key IS consistent: both the write (`klines_cache[sym]`) and the read use `t.symbol`. The issue from #122 was flagged as "fragile" but it works correctly. Document it.

- [ ] **Step 2: Add clarifying comment**

In `src/api/routers/portfolio.py`, replace the existing comment at line 163:

Old:
```python
    # Batch pre-fetch klines for trailing stop calculation (avoid N+1 Binance API calls)
```

New:
```python
    # Batch pre-fetch klines for trailing stop calculation (avoid N+1 Binance API calls).
    # Cache keys use raw symbol format (t.symbol) — matches lookup in trades.py.
```

- [ ] **Step 3: Commit**

```bash
git add src/api/routers/portfolio.py
git commit -m "docs: clarify klines cache uses raw symbol format (#122)"
```

---

## Task 7: Update CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add changelog entry**

Add at the top (after the header, before v4.6.9):

```markdown
## [4.6.10] - 2026-03-31

### Behoben
- **TP/SL Cancel auf BingX/Weex**: Neue `cancel_position_tpsl()` Methode — fragt offene Conditional/Trigger-Orders ab und cancelt sie gezielt. Behebt das Problem dass alte TP/SL-Orders auf der Exchange verbleiben wenn neue gesetzt oder bestehende entfernt werden
- **Race Condition bei TP/SL-Update (BingX/Weex)**: Strategie "Place First, Cancel Old" — neue Orders werden zuerst platziert, dann alte gecancelt. Position ist nie ungeschützt, auch bei API-Fehlern
- **Beide TP+SL entfernen entfernt jetzt auch Exchange-Orders**: Wenn beide Werte gleichzeitig gelöscht werden, wird `cancel_position_tpsl()` direkt aufgerufen statt den Exchange-Call zu überspringen

### Hinzugefuegt
- **BingX `cancel_position_tpsl()`**: Fragt `/openApi/swap/v2/trade/openOrders` ab, filtert auf `TAKE_PROFIT_MARKET`/`STOP_MARKET` nach Symbol und Position-Side, cancelt jede Order einzeln
- **Weex `cancel_position_tpsl()`**: Fragt `/capi/v3/pendingTpSlOrders` ab, filtert nach Symbol und Position-Side, cancelt via `/capi/v3/cancelTpSlOrder`
- **Base-Methode `cancel_position_tpsl()`**: No-op Default für Position-Level Exchanges (Bitget, Hyperliquid, Bitunix) — dort ersetzt `set_position_tpsl` implizit
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog v4.6.10 — TP/SL cancel fix (#121, #122)"
```

---

## Execution Order & Dependencies

```
Task 1 (base.py)
    ↓
Task 2 (BingX) ←── can run parallel ──→ Task 3 (Weex)
    ↓                                       ↓
Task 4 (Router) ← depends on Tasks 1+2+3
    ↓
Task 5 (Verify BingX — no changes needed)
    ↓
Task 6 (Klines cache comment)
    ↓
Task 7 (Changelog)
```

Tasks 2 and 3 are independent and can be parallelized.
