"""Characterization tests for ``src/api/routers/portfolio.py``.

These tests freeze the current HTTP behavior of the 4 portfolio handlers
(``/summary``, ``/positions``, ``/daily``, ``/allocation``) BEFORE the
business logic is extracted into ``src/services/portfolio_service.py``
(see ``Anleitungen/refactor_plan_service_layer.md``, ARCH-C1 PR-5).

They intentionally mirror the *current* response shape — field names,
types, and edge-case outputs — so that the upcoming extraction PR has a
safety net. Assertions target the keys and shapes the handler produces
today; they are NOT aspirational.

The ``characterization`` marker is not registered in ``pytest.ini`` yet;
we intentionally do not modify the pytest config just for this batch, so
pytest will emit an unknown-marker warning but accept it at runtime.

Fixture pattern mirrors ``tests/integration/test_statistics.py`` (same
``admin_token`` / ``test_user_obj`` / ``get_session`` flow).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-for-testing-only-not-for-production",
)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.integration.conftest import auth_header

from src.api.routers import portfolio as portfolio_router
from src.exchanges.types import Balance, Position
from src.models.database import TradeRecord
from src.models.session import get_session


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_portfolio_cache():
    """Each test starts with a clean router-level cache."""
    portfolio_router._cache.clear()
    yield
    portfolio_router._cache.clear()


@pytest_asyncio.fixture
async def test_user_obj(admin_token):
    """Return the admin user row created by the ``admin_token`` fixture."""
    from sqlalchemy import select

    from src.models.database import User

    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.username == "admin")
        )
        return result.scalar_one()


@pytest_asyncio.fixture
async def auth_headers(admin_token):
    """Build auth headers from the admin token."""
    return auth_header(admin_token)


@pytest_asyncio.fixture
async def populated_trades(test_user_obj):
    """Insert a mixed set of closed trades spanning two exchanges."""
    now = datetime.now(timezone.utc)
    trades = [
        TradeRecord(
            user_id=test_user_obj.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            leverage=4,
            confidence=75,
            reason="winner bitget",
            order_id="char_001",
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
            reason="winner bitget",
            order_id="char_002",
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
            size=0.02,
            entry_price=94000.0,
            exit_price=93000.0,
            leverage=4,
            confidence=60,
            reason="loser hyperliquid",
            order_id="char_003",
            status="closed",
            pnl=-20.0,
            pnl_percent=-1.06,
            fees=0.4,
            funding_paid=0.08,
            entry_time=now - timedelta(days=2),
            exit_time=now - timedelta(days=1),
            exit_reason="STOP_LOSS",
            exchange="hyperliquid",
            demo_mode=False,
        ),
    ]
    async with get_session() as session:
        session.add_all(trades)
    return trades


def _make_client(
    positions: list[Position] | None = None,
    balance: Balance | None = None,
) -> MagicMock:
    """Build a mock exchange client mirroring the interface the router uses."""
    client = MagicMock()
    client.get_open_positions = AsyncMock(return_value=positions or [])
    client.get_account_balance = AsyncMock(
        return_value=balance
        or Balance(
            total=0.0, available=0.0, unrealized_pnl=0.0, currency="USDT"
        )
    )
    return client


# ---------------------------------------------------------------------------
# GET /api/portfolio/summary  (3 tests)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_summary_empty_user_returns_zeroed_shape(
    client, auth_headers, test_user_obj
):
    """Empty user: every scalar is 0 and ``exchanges`` is []."""
    resp = await client.get(
        "/api/portfolio/summary", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()

    # Exact keys from PortfolioSummary pydantic schema
    assert set(body.keys()) == {
        "total_pnl",
        "total_trades",
        "overall_win_rate",
        "total_fees",
        "total_funding",
        "exchanges",
    }
    assert body["total_pnl"] == 0
    assert body["total_trades"] == 0
    assert body["overall_win_rate"] == 0
    assert body["total_fees"] == 0
    assert body["total_funding"] == 0
    assert body["exchanges"] == []


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_summary_populated_user_returns_aggregated_totals(
    client, auth_headers, populated_trades
):
    """Populated user: totals match sums across all closed trades and the
    per-exchange breakdown carries the expected keys."""
    resp = await client.get(
        "/api/portfolio/summary?days=30", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()

    # 3 closed trades across two exchanges: 10 + 10 - 20 = 0 total PnL
    assert body["total_trades"] == 3
    assert body["total_pnl"] == pytest.approx(0.0, abs=0.01)
    assert body["total_fees"] == pytest.approx(0.5 + 0.3 + 0.4, abs=0.01)
    assert body["total_funding"] == pytest.approx(0.1 + 0.05 + 0.08, abs=0.01)
    # 2 winners out of 3
    assert body["overall_win_rate"] == pytest.approx(2 / 3 * 100, abs=0.1)

    exchanges = {row["exchange"]: row for row in body["exchanges"]}
    assert set(exchanges.keys()) == {"bitget", "hyperliquid"}

    bg = exchanges["bitget"]
    assert set(bg.keys()) == {
        "exchange",
        "total_pnl",
        "total_trades",
        "winning_trades",
        "win_rate",
        "total_fees",
        "total_funding",
    }
    assert bg["total_trades"] == 2
    assert bg["winning_trades"] == 2
    assert bg["win_rate"] == pytest.approx(100.0, abs=0.1)
    assert bg["total_pnl"] == pytest.approx(20.0, abs=0.01)

    hl = exchanges["hyperliquid"]
    assert hl["total_trades"] == 1
    assert hl["winning_trades"] == 0
    assert hl["win_rate"] == 0
    assert hl["total_pnl"] == pytest.approx(-20.0, abs=0.01)


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_summary_second_call_returns_identical_response(
    client, auth_headers, populated_trades
):
    """Two back-to-back GETs return identical JSON.

    The /summary handler has no in-memory cache (cache is only used for
    /positions and /allocation), so identity here characterizes the
    deterministic DB aggregation rather than TTL caching. The extract PR
    must preserve this: repeated calls within the same second agree.
    """
    first = await client.get(
        "/api/portfolio/summary?days=30", headers=auth_headers
    )
    second = await client.get(
        "/api/portfolio/summary?days=30", headers=auth_headers
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


# ---------------------------------------------------------------------------
# GET /api/portfolio/positions  (3 tests)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_positions_empty_user_returns_empty_list(
    client, auth_headers, test_user_obj
):
    """No exchange connections → handler short-circuits to []."""
    resp = await client.get(
        "/api/portfolio/positions", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_positions_populated_user_returns_expected_fields(
    client, auth_headers, test_user_obj, monkeypatch
):
    """When the factory returns one connected exchange with one open
    position, the handler yields a PortfolioPosition dict with every key
    declared by the schema."""
    fake_position = Position(
        symbol="BTCUSDT",
        side="long",
        size=0.01,
        entry_price=95000.0,
        current_price=96000.0,
        unrealized_pnl=10.0,
        leverage=4,
        exchange="bitget",
        margin=237.5,
    )
    fake_client = _make_client(positions=[fake_position])

    async def fake_get_all(user_id, db):  # noqa: ARG001 - signature mirror
        return [("bitget", False, fake_client)]

    monkeypatch.setattr(
        portfolio_router, "_get_all_user_clients", fake_get_all
    )

    resp = await client.get(
        "/api/portfolio/positions", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1

    entry = body[0]
    # Every key declared in the PortfolioPosition pydantic schema
    expected_keys = {
        "trade_id",
        "exchange",
        "symbol",
        "side",
        "size",
        "entry_price",
        "current_price",
        "unrealized_pnl",
        "leverage",
        "margin",
        "bot_name",
        "demo_mode",
        "take_profit",
        "stop_loss",
        "trailing_stop_active",
        "trailing_stop_price",
        "trailing_stop_distance_pct",
        "trailing_atr_override",
        "native_trailing_stop",
        "can_close_at_loss",
    }
    assert set(entry.keys()) == expected_keys
    assert entry["exchange"] == "bitget"
    assert entry["symbol"] == "BTCUSDT"
    assert entry["side"] == "long"
    assert entry["size"] == pytest.approx(0.01)
    assert entry["unrealized_pnl"] == pytest.approx(10.0)
    assert entry["leverage"] == 4


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_positions_exchange_query_param_current_behavior(
    client, auth_headers, test_user_obj, monkeypatch
):
    """Characterization note: the handler does NOT accept an ``exchange``
    query filter today. An unknown query param is silently ignored and
    the same payload is returned. This test freezes that behavior so the
    extraction PR must explicitly opt in to changing it.
    """
    positions_by_exchange = {
        "bitget": [
            Position(
                symbol="BTCUSDT",
                side="long",
                size=0.01,
                entry_price=95000.0,
                current_price=96000.0,
                unrealized_pnl=10.0,
                leverage=4,
                exchange="bitget",
                margin=237.5,
            )
        ],
        "hyperliquid": [
            Position(
                symbol="ETHUSDT",
                side="short",
                size=0.1,
                entry_price=3500.0,
                current_price=3400.0,
                unrealized_pnl=10.0,
                leverage=4,
                exchange="hyperliquid",
                margin=87.5,
            )
        ],
    }

    def _client_for(ex):
        return _make_client(positions=positions_by_exchange[ex])

    async def fake_get_all(user_id, db):  # noqa: ARG001
        return [
            ("bitget", False, _client_for("bitget")),
            ("hyperliquid", False, _client_for("hyperliquid")),
        ]

    monkeypatch.setattr(
        portfolio_router, "_get_all_user_clients", fake_get_all
    )

    resp_all = await client.get(
        "/api/portfolio/positions", headers=auth_headers
    )
    # Clear cache so the second call really re-evaluates
    portfolio_router._cache.clear()
    resp_filtered = await client.get(
        "/api/portfolio/positions?exchange=bitget", headers=auth_headers
    )

    assert resp_all.status_code == 200
    assert resp_filtered.status_code == 200
    all_exchanges = {p["exchange"] for p in resp_all.json()}
    filtered_exchanges = {p["exchange"] for p in resp_filtered.json()}
    # Current behavior: param is ignored, both responses span both exchanges.
    assert all_exchanges == {"bitget", "hyperliquid"}
    assert filtered_exchanges == {"bitget", "hyperliquid"}


# ---------------------------------------------------------------------------
# GET /api/portfolio/daily  (2 tests)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_daily_empty_user_returns_empty_list(
    client, auth_headers, test_user_obj
):
    resp = await client.get(
        "/api/portfolio/daily", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_daily_populated_user_returns_grouped_entries(
    client, auth_headers, populated_trades
):
    """Each entry is grouped by (date, exchange) with the schema keys."""
    resp = await client.get(
        "/api/portfolio/daily?days=30", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1

    for row in body:
        assert set(row.keys()) == {
            "date",
            "exchange",
            "pnl",
            "trades",
            "fees",
        }
        assert isinstance(row["date"], str)
        assert isinstance(row["exchange"], str)
        assert isinstance(row["trades"], int)

    # Total trades and pnl across all rows equal the seeded closed trades
    assert sum(r["trades"] for r in body) == 3
    assert sum(r["pnl"] for r in body) == pytest.approx(0.0, abs=0.01)
    assert {r["exchange"] for r in body} == {"bitget", "hyperliquid"}


# ---------------------------------------------------------------------------
# GET /api/portfolio/allocation  (2 tests)
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_allocation_empty_user_returns_empty_list(
    client, auth_headers, test_user_obj
):
    resp = await client.get(
        "/api/portfolio/allocation", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.characterization
@pytest.mark.asyncio
async def test_allocation_populated_user_returns_balance_buckets(
    client, auth_headers, test_user_obj, monkeypatch
):
    """Characterization: the handler returns one bucket PER exchange with
    ``{exchange, balance, currency}``. It does NOT normalize to percentages
    — the frontend computes the pie-chart shares. We freeze that raw shape.
    """
    bitget_client = _make_client(
        balance=Balance(
            total=1000.0,
            available=800.0,
            unrealized_pnl=0.0,
            currency="USDT",
        )
    )
    hl_client = _make_client(
        balance=Balance(
            total=500.0,
            available=500.0,
            unrealized_pnl=0.0,
            currency="USDT",
        )
    )

    async def fake_get_all(user_id, db):  # noqa: ARG001
        return [
            ("bitget", False, bitget_client),
            ("hyperliquid", False, hl_client),
        ]

    monkeypatch.setattr(
        portfolio_router, "_get_all_user_clients", fake_get_all
    )

    resp = await client.get(
        "/api/portfolio/allocation", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2

    for row in body:
        assert set(row.keys()) == {"exchange", "balance", "currency"}
        assert row["currency"] == "USDT"
        assert isinstance(row["balance"], (int, float))

    balances = {row["exchange"]: row["balance"] for row in body}
    assert balances["bitget"] == pytest.approx(1000.0)
    assert balances["hyperliquid"] == pytest.approx(500.0)
