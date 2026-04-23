"""Characterization tests for ``src/api/routers/trades.py``.

These tests are a **safety net** for the upcoming ARCH-C1 service-layer
extraction (see ``Anleitungen/refactor_plan_service_layer.md``). They freeze
the *current* behavior of the six HTTP handlers in ``trades.py`` so that any
change to request/response shape, status codes, or error semantics during
the extract is caught immediately.

Characterization principles observed here
-----------------------------------------
* Tests assert on **whatever the handler returns today**, not on an
  idealized future shape. Weirdnesses are intentional.
* A test breaking is a *signal*: either the extract regressed behavior or
  the spec in the refactor plan needs to be updated — not the test.

Notable behavior frozen by these tests (surprises worth calling out)
-------------------------------------------------------------------
* ``GET /api/trades/{trade_id}`` returns **404** for both "trade does not
  exist" and "trade exists but is owned by another user". There is no 403
  path — the ownership check is fused into the WHERE clause.
* ``GET /api/trades/{trade_id}/risk-state`` returns **404** when the
  ``risk_state_manager_enabled`` feature flag is off, even for a valid
  trade. The 404 is used as "endpoint disabled".
* ``PUT /api/trades/{trade_id}/tp-sl`` likewise returns **404** (not 403)
  when the trade is not owned by the caller, on both the flag-on
  (manager) and flag-off (legacy) paths.
* ``POST /api/trades/sync`` has **no ``exchange`` query/body parameter**.
  It syncs every open trade the user owns, grouped by exchange internally.
  The response shape is ``{"synced": int, "closed_trades": list}`` — NOT
  ``{"synced_count": ...}``. The "happy path" test below reflects reality.
* The response body of ``PUT /api/trades/{trade_id}/tp-sl`` differs by
  feature flag: flag-on (manager) returns a ``TpSlResponse`` with
  ``trade_id``/``tp``/``sl``/``trailing``/``overall_status``; flag-off
  (legacy) returns ``{"status": "ok", ...}``. The happy-path test here
  exercises the flag-on path, matching how production runs today.
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import patch

import pytest
import pytest_asyncio

# Must be set before any src imports so jwt_handler / encryption initialise.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.integration.conftest import auth_header  # noqa: E402

from src.exchanges.base import PositionTpSlSnapshot, TrailingStopSnapshot  # noqa: E402
from src.models.database import ExchangeConnection, TradeRecord  # noqa: E402
from src.models.session import get_session  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_user_obj(admin_token):
    """Return the admin user created by the ``admin_token`` fixture."""
    from sqlalchemy import select
    from src.models.database import User

    async with get_session() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        return result.scalar_one()


@pytest_asyncio.fixture
async def auth_headers(admin_token):
    """Build auth headers from the admin token."""
    return auth_header(admin_token)


@pytest_asyncio.fixture
async def other_user(test_user_obj):
    """Create a second user — used to verify ownership guards."""
    from src.auth.password import hash_password
    from src.models.database import User

    async with get_session() as session:
        user = User(
            username="other_user",
            password_hash=hash_password("other_pw123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user


@pytest_asyncio.fixture
async def sample_trades(test_user_obj):
    """Seed a handful of trades spanning statuses, symbols and demo_mode."""
    now = datetime.now(timezone.utc)
    trades_data = [
        TradeRecord(
            user_id=test_user_obj.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="Trade 1",
            order_id="char_order_001",
            status="closed",
            pnl=10.0,
            pnl_percent=1.05,
            fees=0.5,
            funding_paid=0.1,
            entry_time=now - timedelta(days=5),
            exit_time=now - timedelta(days=4),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=test_user_obj.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            exit_price=3400.0,
            leverage=4,
            confidence=80,
            reason="Trade 2",
            order_id="char_order_002",
            status="closed",
            pnl=10.0,
            pnl_percent=2.86,
            fees=0.3,
            funding_paid=0.05,
            entry_time=now - timedelta(days=3),
            exit_time=now - timedelta(days=2),
            exit_reason="TAKE_PROFIT",
            exchange="bitget",
            demo_mode=True,
        ),
        TradeRecord(
            user_id=test_user_obj.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95500.0,
            leverage=4,
            confidence=70,
            reason="Trade 3 - open",
            order_id="char_order_003",
            status="open",
            entry_time=now - timedelta(hours=2),
            exchange="bitget",
            demo_mode=True,
        ),
    ]

    async with get_session() as session:
        session.add_all(trades_data)

    # Re-fetch to pick up autogenerated IDs (the session above auto-commits).
    from sqlalchemy import select
    async with get_session() as session:
        rows = await session.execute(
            select(TradeRecord)
            .where(TradeRecord.user_id == test_user_obj.id)
            .order_by(TradeRecord.id.asc())
        )
        return list(rows.scalars().all())


@pytest_asyncio.fixture
async def open_trade_with_exchange(test_user_obj):
    """An open trade plus an ExchangeConnection for tp-sl / risk-state tests."""
    async with get_session() as session:
        conn = ExchangeConnection(
            user_id=test_user_obj.id,
            exchange_type="bitget",
            demo_api_key_encrypted="enc_key",
            demo_api_secret_encrypted="enc_secret",
            demo_passphrase_encrypted="enc_pp",
        )
        session.add(conn)

        trade = TradeRecord(
            user_id=test_user_obj.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=68200.0,
            leverage=10,
            confidence=80,
            reason="characterization open trade",
            order_id="char_open_001",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(trade)

    from sqlalchemy import select
    async with get_session() as session:
        row = await session.execute(
            select(TradeRecord).where(TradeRecord.order_id == "char_open_001")
        )
        return row.scalar_one()


@pytest_asyncio.fixture
async def other_user_trade(other_user):
    """A trade owned by ``other_user`` — used in ownership-guard tests."""
    async with get_session() as session:
        trade = TradeRecord(
            user_id=other_user.id,
            symbol="SOLUSDT",
            side="long",
            size=1.0,
            entry_price=150.0,
            leverage=3,
            confidence=60,
            reason="owned by another user",
            order_id="other_user_trade_001",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(trade)

    from sqlalchemy import select
    async with get_session() as session:
        row = await session.execute(
            select(TradeRecord).where(TradeRecord.order_id == "other_user_trade_001")
        )
        return row.scalar_one()


# ---------------------------------------------------------------------------
# Fake exchange client + RiskStateManager wiring (copied from test_tp_sl_endpoint_v2)
# ---------------------------------------------------------------------------


@dataclass
class _FakeExchangeClient:
    """Stateful exchange double — the minimum surface RiskStateManager touches."""

    exchange_name: str = "fake"

    place_returns: Any = None
    trailing_place_returns: Any = None

    readback_tp: Optional[float] = None
    readback_sl: Optional[float] = None
    readback_tp_id: Optional[str] = None
    readback_sl_id: Optional[str] = None
    readback_trailing_callback: Optional[float] = None
    readback_trailing_activation: Optional[float] = None
    readback_trailing_trigger: Optional[float] = None
    readback_trailing_id: Optional[str] = None

    cancel_calls: List[tuple] = field(default_factory=list)
    place_calls: List[dict] = field(default_factory=list)
    trailing_calls: List[dict] = field(default_factory=list)
    readback_calls: List[tuple] = field(default_factory=list)

    async def cancel_position_tpsl(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "all"))
        return True

    async def cancel_tp_only(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "tp_only"))
        return True

    async def cancel_sl_only(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "sl_only"))
        return True

    async def cancel_native_trailing_stop(self, symbol: str, side: str = "long") -> bool:
        self.cancel_calls.append((symbol, side, "trailing_only"))
        return True

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        return True

    async def set_position_tpsl(
        self,
        symbol: str,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        side: str = "long",
        size: float = 0,
        **_,
    ) -> Any:
        self.place_calls.append(
            {
                "symbol": symbol,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "side": side,
                "size": size,
            }
        )
        return self.place_returns

    async def place_trailing_stop(self, **kwargs) -> Any:
        self.trailing_calls.append(kwargs)
        return self.trailing_place_returns

    async def get_position_tpsl(self, symbol: str, hold_side: str) -> PositionTpSlSnapshot:
        self.readback_calls.append(("tpsl", symbol, hold_side))
        return PositionTpSlSnapshot(
            symbol=symbol,
            side=hold_side,
            tp_price=self.readback_tp,
            tp_order_id=self.readback_tp_id,
            tp_trigger_type="mark_price",
            sl_price=self.readback_sl,
            sl_order_id=self.readback_sl_id,
            sl_trigger_type="mark_price",
        )

    async def get_trailing_stop(self, symbol: str, hold_side: str) -> TrailingStopSnapshot:
        self.readback_calls.append(("trailing", symbol, hold_side))
        return TrailingStopSnapshot(
            symbol=symbol,
            side=hold_side,
            callback_rate=self.readback_trailing_callback,
            activation_price=self.readback_trailing_activation,
            trigger_price=self.readback_trailing_trigger,
            order_id=self.readback_trailing_id,
        )

    async def get_open_positions(self):
        """Empty list → sync will treat every open DB trade as "gone from exchange"."""
        return []

    async def get_close_fill_price(self, symbol: str):
        return 95000.0

    async def get_ticker(self, symbol: str):
        class _Ticker:
            last_price = 95000.0
        return _Ticker()

    async def get_trade_total_fees(self, **_):
        return 0.0

    async def get_funding_fees(self, **_):
        return 0.0

    async def close(self) -> None:
        return None


def _wire_manager_for_test(fake: _FakeExchangeClient) -> None:
    """Install a RiskStateManager that returns ``fake`` for every call."""
    from src.api.dependencies.risk_state import set_risk_state_manager
    from src.bot.risk_state_manager import RiskStateManager

    @asynccontextmanager
    async def _session_factory_cm():
        async with get_session() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    def _client_factory(_uid: int, _exchange: str, _demo: bool):
        return fake

    manager = RiskStateManager(
        exchange_client_factory=_client_factory,
        session_factory=_session_factory_cm,
    )
    set_risk_state_manager(manager)


def _enable_risk_flag(monkeypatch, value: bool = True) -> None:
    from config.settings import settings as _settings
    monkeypatch.setattr(_settings.risk, "risk_state_manager_enabled", value)


@pytest.fixture(autouse=True)
def _reset_risk_state_singletons():
    """Reset module-level singletons between tests in this file."""
    from src.api.dependencies.risk_state import (
        IdempotencyCache,
        set_idempotency_cache,
        set_risk_state_manager,
    )
    set_risk_state_manager(None)
    set_idempotency_cache(IdempotencyCache())
    yield
    set_risk_state_manager(None)
    set_idempotency_cache(IdempotencyCache())


# ---------------------------------------------------------------------------
# GET /api/trades — list handler (line 158)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_list_trades_empty_user_returns_empty_list(
    client, auth_headers, test_user_obj
):
    """With no trades seeded, ``GET /api/trades`` returns the empty list shape."""
    response = await client.get("/api/trades", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "trades": [],
        "total": 0,
        "page": 1,
        "per_page": 50,
    }


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_list_trades_filter_by_symbol_returns_matching_only(
    client, auth_headers, sample_trades
):
    """``?symbol=ETHUSDT`` filters to trades whose symbol matches (ilike)."""
    response = await client.get(
        "/api/trades", headers=auth_headers, params={"symbol": "ETHUSDT"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["per_page"] == 50
    assert len(data["trades"]) == 1
    assert data["trades"][0]["symbol"] == "ETHUSDT"


# ---------------------------------------------------------------------------
# GET /api/trades/filter-options (line 303)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_filter_options_empty_user_returns_empty_collections(
    client, auth_headers, test_user_obj
):
    """No trades + no bots → all four lists are empty."""
    response = await client.get("/api/trades/filter-options", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "symbols": [],
        "bots": [],
        "exchanges": [],
        "statuses": [],
    }


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_filter_options_populated_user_returns_distinct_values(
    client, auth_headers, sample_trades
):
    """Populated user → distinct symbols, exchanges and statuses are returned."""
    response = await client.get("/api/trades/filter-options", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    # Top-level keys are stable
    assert set(data.keys()) == {"symbols", "bots", "exchanges", "statuses"}

    # Distinct sorted symbols from the three sample trades (BTC + ETH)
    assert data["symbols"] == ["BTCUSDT", "ETHUSDT"]
    # Only ``bitget`` in the fixture
    assert data["exchanges"] == ["bitget"]
    # Distinct statuses — "closed" and "open" from the fixture
    assert set(data["statuses"]) == {"closed", "open"}
    # No bots seeded
    assert data["bots"] == []


# ---------------------------------------------------------------------------
# POST /api/trades/sync (line 377)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_sync_trades_no_exchange_param_no_open_trades_returns_zero(
    client, auth_headers, test_user_obj
):
    """Characterization: the handler takes NO ``exchange`` parameter. Invoking
    it when the user has no open trades short-circuits with ``synced == 0``.

    (The task spec asked for "missing exchange param → 400"; the current
    handler has no such guard — it simply returns ``synced=0`` when there is
    nothing to sync. We freeze the actual observed behavior.)
    """
    response = await client.post("/api/trades/sync", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    # Shape is ``{"synced": int, "closed_trades": list}`` — NOT ``synced_count``
    assert data == {"synced": 0, "closed_trades": []}


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_sync_trades_happy_path_returns_report_shape(
    client, auth_headers, test_user_obj, open_trade_with_exchange
):
    """Happy path with a mocked exchange that reports "position gone" closes the trade.

    Asserts on the current response shape, which uses the ``synced`` key
    (NOT ``synced_count``) and includes a ``closed_trades`` list.
    """
    fake = _FakeExchangeClient()

    with patch(
        "src.api.routers.trades.create_exchange_client", return_value=fake
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v
    ):
        response = await client.post("/api/trades/sync", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert "synced" in data
    assert "closed_trades" in data
    assert data["synced"] == 1
    assert len(data["closed_trades"]) == 1
    closed = data["closed_trades"][0]
    assert closed["symbol"] == "BTCUSDT"
    assert closed["side"] == "long"
    assert "exit_price" in closed
    assert "pnl" in closed
    assert "exit_reason" in closed


# ---------------------------------------------------------------------------
# GET /api/trades/{trade_id} — detail (line 631)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_get_trade_detail_not_found_returns_404(
    client, auth_headers, test_user_obj
):
    """A non-existent trade_id → 404."""
    response = await client.get("/api/trades/99999", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_get_trade_detail_not_owned_returns_404(
    client, auth_headers, test_user_obj, other_user_trade
):
    """A trade owned by another user returns **404** (not 403).

    Characterization finding: the handler fuses ownership into the WHERE
    clause, so "not yours" is indistinguishable from "does not exist".
    No 403 path exists.
    """
    response = await client.get(
        f"/api/trades/{other_user_trade.id}", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_get_trade_detail_happy_path_returns_expected_fields(
    client, auth_headers, sample_trades
):
    """Happy path: expected top-level TradeResponse fields are present."""
    trade_id = sample_trades[0].id
    response = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    # Core identifiers
    assert data["id"] == trade_id
    assert data["symbol"] == "BTCUSDT"
    assert data["side"] == "long"
    assert data["status"] == "closed"
    # Numeric fields from the schema
    for key in (
        "size",
        "entry_price",
        "leverage",
        "confidence",
        "pnl",
        "pnl_percent",
        "fees",
        "funding_paid",
    ):
        assert key in data, f"missing key: {key}"
    # ISO timestamps (may be str or None)
    assert "entry_time" in data
    assert "exit_time" in data
    # Exchange metadata
    assert data["exchange"] == "bitget"
    assert data["demo_mode"] is True


# ---------------------------------------------------------------------------
# GET /api/trades/{trade_id}/risk-state (line 870)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_get_risk_state_not_found_returns_404(
    client, auth_headers, test_user_obj, monkeypatch
):
    """Non-existent trade → 404, even with the flag on.

    Characterization finding: when the feature flag is OFF (the default),
    this endpoint *also* returns 404 for *any* trade — it uses 404 as the
    "endpoint disabled" signal. Here we enable the flag to exercise the
    genuine not-found branch.
    """
    _enable_risk_flag(monkeypatch)
    fake = _FakeExchangeClient()
    _wire_manager_for_test(fake)

    response = await client.get(
        "/api/trades/99999/risk-state", headers=auth_headers
    )
    assert response.status_code == 404


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_get_risk_state_happy_path_returns_snapshot_shape(
    client, auth_headers, test_user_obj, open_trade_with_exchange, monkeypatch
):
    """Happy path: response contains ``trade_id`` + per-leg tp/sl keys."""
    _enable_risk_flag(monkeypatch)
    fake = _FakeExchangeClient(
        readback_tp=70000.0,
        readback_tp_id="tp_1",
        readback_sl=66000.0,
        readback_sl_id="sl_1",
    )
    _wire_manager_for_test(fake)

    response = await client.get(
        f"/api/trades/{open_trade_with_exchange.id}/risk-state",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    # Required keys from TpSlResponse
    assert data["trade_id"] == open_trade_with_exchange.id
    assert "tp" in data
    assert "sl" in data
    assert "trailing" in data
    assert "applied_at" in data
    assert "overall_status" in data
    # tp_sl legs are dicts (or None)
    assert data["tp"] is not None
    assert data["sl"] is not None


# ---------------------------------------------------------------------------
# PUT /api/trades/{trade_id}/tp-sl (line 1062)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_put_tp_sl_invalid_intent_schema_returns_422(
    client, auth_headers, open_trade_with_exchange, monkeypatch
):
    """An unknown/extra field violates ``extra='forbid'`` → 422 schema error.

    ``UpdateTpSlRequest`` sets ``model_config = {"extra": "forbid"}``, so
    passing a field that isn't in the schema is a pydantic validation
    failure (422), which happens *before* the endpoint body runs.
    """
    _enable_risk_flag(monkeypatch)
    fake = _FakeExchangeClient()
    _wire_manager_for_test(fake)

    response = await client.put(
        f"/api/trades/{open_trade_with_exchange.id}/tp-sl",
        headers=auth_headers,
        json={"totally_unknown_field": True},
    )
    assert response.status_code == 422


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_put_tp_sl_not_owned_returns_404(
    client, auth_headers, test_user_obj, other_user_trade, monkeypatch
):
    """Editing another user's trade returns **404** (not 403).

    Characterization finding: the ownership check is fused into the WHERE
    clause on both the manager path and the legacy path. Not-yours looks
    identical to not-exists.
    """
    _enable_risk_flag(monkeypatch)
    fake = _FakeExchangeClient()
    _wire_manager_for_test(fake)

    response = await client.put(
        f"/api/trades/{other_user_trade.id}/tp-sl",
        headers=auth_headers,
        json={"take_profit": 200.0},
    )
    assert response.status_code == 404


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_put_tp_sl_happy_path_returns_partial_result_shape(
    client, auth_headers, open_trade_with_exchange, monkeypatch
):
    """Happy path on the manager (flag-on) route returns the TpSlResponse shape.

    Keys: ``trade_id``, ``tp``, ``sl``, ``trailing``, ``applied_at``,
    ``overall_status``. Each leg is either ``None`` (not touched) or a
    dict with ``status``, ``value``, ``order_id``, ``latency_ms``.
    """
    _enable_risk_flag(monkeypatch)
    fake = _FakeExchangeClient(
        place_returns={"orderId": "tp_native_char"},
        readback_tp=70000.0,
        readback_tp_id="tp_native_char",
    )
    _wire_manager_for_test(fake)

    response = await client.put(
        f"/api/trades/{open_trade_with_exchange.id}/tp-sl",
        headers=auth_headers,
        json={"take_profit": 70000.0},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["trade_id"] == open_trade_with_exchange.id
    assert "tp" in data
    assert "sl" in data
    assert "trailing" in data
    assert "applied_at" in data
    assert "overall_status" in data
    # Only TP was touched, so sl / trailing legs are None
    assert data["sl"] is None
    assert data["trailing"] is None
    # TP leg dict shape
    assert data["tp"] is not None
    assert data["tp"]["status"] == "confirmed"
    assert data["tp"]["value"] == 70000.0
    assert data["overall_status"] == "all_confirmed"
