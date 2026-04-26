"""Characterization tests for ``src/api/routers/trades.py``.

Phase 0 safety net for issue #325 — freezes the *current observable*
behaviour of every trades-router endpoint NOT YET extracted to the
service layer. ``list_trades`` and ``get_filter_options`` are already
covered by the ``TradesService`` tests from #255 and are intentionally
out of scope here.

Endpoints characterised by this file
------------------------------------
* ``POST /api/trades/sync``                  — lines ~261-512
* ``GET  /api/trades/{trade_id}``            — lines ~515-572
* ``GET  /api/trades/{trade_id}/risk-state`` — lines ~754-830
* ``PUT  /api/trades/{trade_id}/tp-sl``      — lines ~946-1234

Characterization principles
---------------------------
* Tests assert what the handler *currently* returns, including
  documented surprises. Response-shape correctness is the contract.
* If a test looks wrong (e.g. a 500 that should be 404), it is frozen
  with a ``# FIXME`` and flagged in the return summary as a follow-up
  candidate — production code is never modified here.

Notable observed behaviour frozen by these tests
------------------------------------------------
* ``GET /api/trades/{trade_id}`` returns **404** for both "not found"
  and "owned by another user". The ownership check is fused into the
  WHERE clause — no 403 path exists.
* ``GET /api/trades/{trade_id}/risk-state`` returns **404** when the
  ``risk_state_manager_enabled`` feature flag is off, regardless of
  whether the trade exists. 404 doubles as "endpoint disabled".
* ``PUT /api/trades/{trade_id}/tp-sl`` returns **different response
  shapes** depending on the feature flag: ``TpSlResponse`` (manager)
  when on, ``{"status": "ok", ...}`` (legacy) when off.
* The legacy path returns **400** on TP/SL mutex conflicts; the manager
  path returns **422** for the same conflict.
* ``POST /api/trades/sync`` takes no parameters at all — invoking it
  with a user that has no open trades short-circuits with
  ``{"synced": 0, "closed_trades": []}``.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

# Must be set BEFORE any src imports — jwt_handler / encryption bail out
# with a hard error if they see unset secrets on import.
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-for-testing-only-not-for-production",
)
os.environ.setdefault(
    "ENCRYPTION_KEY",
    "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==",
)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.auth.jwt_handler import create_access_token  # noqa: E402
from src.auth.password import hash_password  # noqa: E402
from src.bot.risk_state_manager import (  # noqa: E402
    RiskLeg,
    RiskOpResult,
    RiskOpStatus,
)
from src.models.database import (  # noqa: E402
    Base,
    BotConfig,
    ExchangeConnection,
    TradeRecord,
    User,
    UserConfig,
)


# ---------------------------------------------------------------------------
# Low-level DB / app / client fixtures (self-contained — no cross-file deps)
# ---------------------------------------------------------------------------


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
async def user(session_factory):
    async with session_factory() as session:
        u = User(
            username="char_trader",
            email="char_trader@test.com",
            password_hash=hash_password("password123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def other_user(session_factory):
    async with session_factory() as session:
        u = User(
            username="char_other_user",
            email="char_other@test.com",
            password_hash=hash_password("password456"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def auth_headers(user):
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def bot_config(session_factory, user):
    async with session_factory() as session:
        bc = BotConfig(
            user_id=user.id,
            name="CharBot",
            description="Characterization bot",
            strategy_type="edge_indicator",
            exchange_type="bitget",
            mode="demo",
            trading_pairs='["BTCUSDT"]',
            leverage=4,
            is_enabled=False,
        )
        session.add(bc)
        await session.commit()
        await session.refresh(bc)
        return bc


@pytest_asyncio.fixture
async def open_trade(session_factory, user):
    """An open trade owned by ``user`` — foundation for tp-sl / risk-state tests."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=68200.0,
            take_profit=70000.0,
            stop_loss=67000.0,
            leverage=10,
            confidence=80,
            reason="char open trade",
            order_id="char_open_001",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def open_trade_short(session_factory, user):
    """An open SHORT trade — needed to exercise SHORT-side TP/SL validation."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            leverage=4,
            confidence=70,
            reason="char short trade",
            order_id="char_short_001",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def closed_trade(session_factory, user, bot_config):
    """A closed trade with bot linkage — used by ``get_trade`` happy path."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        t = TradeRecord(
            user_id=user.id,
            bot_config_id=bot_config.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=95000.0,
            exit_price=96000.0,
            take_profit=97000.0,
            stop_loss=94000.0,
            leverage=4,
            confidence=75,
            reason="char closed trade",
            order_id="char_closed_001",
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
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def other_user_trade(session_factory, other_user):
    """An open trade owned by another user — used for ownership-guard tests."""
    async with session_factory() as session:
        t = TradeRecord(
            user_id=other_user.id,
            symbol="SOLUSDT",
            side="long",
            size=1.0,
            entry_price=150.0,
            leverage=3,
            confidence=60,
            reason="owned by another user",
            order_id="char_other_user_trade",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        return t


@pytest_asyncio.fixture
async def exchange_connection(session_factory, user):
    """An ExchangeConnection with demo credentials — needed by sync / tp-sl."""
    async with session_factory() as session:
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
            demo_api_key_encrypted="enc_key",
            demo_api_secret_encrypted="enc_secret",
            demo_passphrase_encrypted="enc_pp",
        )
        session.add(conn)
        await session.commit()
        await session.refresh(conn)
        return conn


@pytest_asyncio.fixture
async def app(session_factory):
    from fastapi import FastAPI
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    from src.api.routers import trades
    from src.api.routers.auth import limiter
    from src.models.session import get_db

    limiter.enabled = False

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app = FastAPI()
    test_app.state.limiter = limiter
    test_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    test_app.include_router(trades.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture(autouse=True)
def _reset_risk_state_singletons():
    """Reset module-level risk-state singletons between tests.

    The router module caches a :class:`RiskStateManager` in
    ``src.api.dependencies.risk_state``. A test that swaps the manager
    must not leak into the next test.
    """
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
# Helpers
# ---------------------------------------------------------------------------


def _flag_settings(enabled: bool) -> MagicMock:
    """Build a stand-in ``settings`` with ``risk.risk_state_manager_enabled``."""
    fake = MagicMock()
    fake.risk.risk_state_manager_enabled = enabled
    return fake


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/trades/sync
# ═══════════════════════════════════════════════════════════════════════════


async def test_sync_trades_requires_auth_returns_401(client):
    """Unauthenticated ``POST /sync`` returns 401."""
    resp = await client.post("/api/trades/sync")
    assert resp.status_code == 401


async def test_sync_trades_no_open_trades_returns_envelope(client, auth_headers, user):
    """Characterization: no open trades -> short-circuit response shape.

    The handler takes NO request body / query parameters. The observed
    shape is ``{"synced": int, "closed_trades": list}`` — the "synced"
    key is NOT called "synced_count".
    """
    resp = await client.post("/api/trades/sync", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"synced": 0, "closed_trades": []}


async def test_sync_trades_skips_when_no_exchange_connection(
    client, auth_headers, open_trade,
):
    """Open trade but no ``ExchangeConnection`` -> synced=0 (skip branch)."""
    resp = await client.post("/api/trades/sync", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0
    assert data["closed_trades"] == []


async def test_sync_trades_closes_position_not_on_exchange(
    client, auth_headers, open_trade, exchange_connection,
):
    """Happy path: exchange reports the position as gone -> trade gets closed.

    Freezes the response envelope shape including the per-trade dict
    keys: ``id``, ``symbol``, ``side``, ``exit_price``, ``pnl``,
    ``exit_reason``.
    """
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_close_fill_price = AsyncMock(return_value=None)
    mock_client.get_ticker = AsyncMock(
        return_value=MagicMock(last_price=68500.0)
    )
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.05)
    mock_client.close = AsyncMock()

    with patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
    assert len(data["closed_trades"]) == 1
    closed = data["closed_trades"][0]
    assert set(closed.keys()) >= {
        "id", "symbol", "side", "exit_price", "pnl", "exit_reason",
    }
    assert closed["symbol"] == "BTCUSDT"
    assert closed["side"] == "long"
    # Heuristic (flag off) — exit price == ticker.last_price = 68500 is
    # not within 0.5% of TP (70000) nor SL (67000), so it resolves to
    # MANUAL_CLOSE.
    assert closed["exit_reason"] == "MANUAL_CLOSE"


async def test_sync_trades_keeps_position_still_on_exchange(
    client, auth_headers, open_trade, exchange_connection,
):
    """If the exchange still reports the position, the trade stays open."""
    pos = MagicMock(symbol=open_trade.symbol, side=open_trade.side)
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[pos])
    mock_client.close = AsyncMock()

    with patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 0
    assert data["closed_trades"] == []


async def test_sync_trades_exchange_error_returns_zero_synced(
    client, auth_headers, open_trade, exchange_connection,
):
    """A thrown exchange error is swallowed — response still 200 with synced=0."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(
        side_effect=Exception("exchange blew up")
    )
    mock_client.close = AsyncMock()

    with patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"synced": 0, "closed_trades": []}


async def test_sync_trades_sends_discord_webhook_when_configured(
    client, auth_headers, open_trade, exchange_connection, session_factory, user,
):
    """Closed-trade Discord notification path is exercised when configured.

    We seed a :class:`UserConfig` with a fake ``discord_webhook_url`` and
    verify the ``DiscordNotifier.send_trade_exit`` coroutine is awaited
    once per closed trade. The current handler catches & logs notifier
    failures — the sync response is unaffected.
    """
    async with session_factory() as session:
        cfg = UserConfig(user_id=user.id, discord_webhook_url="encrypted_hook")
        session.add(cfg)
        await session.commit()

    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_close_fill_price = AsyncMock(return_value=None)
    mock_client.get_ticker = AsyncMock(
        return_value=MagicMock(last_price=68500.0)
    )
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.05)
    mock_client.close = AsyncMock()

    fake_notifier = MagicMock()
    fake_notifier.send_trade_exit = AsyncMock()
    fake_notifier.close = AsyncMock()

    with patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ), patch(
        "src.notifications.discord_notifier.DiscordNotifier",
        return_value=fake_notifier,
    ):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["synced"] == 1
    fake_notifier.send_trade_exit.assert_awaited()


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/trades/{trade_id}
# ═══════════════════════════════════════════════════════════════════════════


async def test_get_trade_requires_auth_returns_401(client, open_trade):
    """Unauthenticated detail read -> 401."""
    resp = await client.get(f"/api/trades/{open_trade.id}")
    assert resp.status_code == 401


async def test_get_trade_nonexistent_returns_404(client, auth_headers, user):
    """Unknown ``trade_id`` -> 404."""
    resp = await client.get("/api/trades/999999", headers=auth_headers)
    assert resp.status_code == 404
    # Error body has a ``detail`` key
    assert "detail" in resp.json()


async def test_get_trade_other_users_trade_returns_404(
    client, auth_headers, other_user_trade,
):
    """Characterization: another user's trade is indistinguishable from 404.

    Ownership is fused into the WHERE clause — there is NO 403 branch.
    """
    resp = await client.get(
        f"/api/trades/{other_user_trade.id}", headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_get_trade_happy_path_response_shape(
    client, auth_headers, closed_trade,
):
    """Closed trade returns the full ``TradeResponse`` shape.

    Asserts presence of every documented key and the bot linkage fields.
    Values that are hard-coded in the fixture (``pnl=10.0``) are
    deterministic and therefore exact-matched.
    """
    resp = await client.get(
        f"/api/trades/{closed_trade.id}", headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    expected_keys = {
        "id", "symbol", "side", "size", "entry_price", "exit_price",
        "take_profit", "stop_loss", "leverage", "confidence", "reason",
        "status", "pnl", "pnl_percent", "fees", "funding_paid",
        "entry_time", "exit_time", "exit_reason", "exchange", "demo_mode",
        "bot_name", "bot_exchange",
    }
    assert expected_keys.issubset(set(data.keys()))

    assert data["id"] == closed_trade.id
    assert data["symbol"] == "BTCUSDT"
    assert data["side"] == "long"
    assert data["status"] == "closed"
    assert data["pnl"] == 10.0
    assert data["bot_name"] == "CharBot"
    assert data["bot_exchange"] == "bitget"


async def test_get_trade_open_trade_has_null_exit_fields(
    client, auth_headers, open_trade,
):
    """Open trade -> ``exit_price`` / ``exit_time`` / ``exit_reason`` are None."""
    resp = await client.get(
        f"/api/trades/{open_trade.id}", headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["exit_price"] is None
    assert data["exit_time"] is None
    assert data["exit_reason"] is None
    # Bot fields are None for a trade without bot_config_id
    assert data["bot_name"] is None
    assert data["bot_exchange"] is None


async def test_get_trade_with_trailing_strategy_long_active_branch(
    client, auth_headers, session_factory, user,
):
    """Open LONG trade with edge_indicator bot hits the trailing_active branch.

    Seed a trade where ``highest_price - entry`` >> ATR*breakeven_atr so
    the "was_profitable" path runs and returns populated trailing fields.
    """
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        bc = BotConfig(
            user_id=user.id,
            name="TrailingBot",
            description="Edge Indicator bot",
            strategy_type="edge_indicator",
            exchange_type="bitget",
            mode="demo",
            trading_pairs='["BTCUSDT"]',
            leverage=4,
            is_enabled=False,
        )
        session.add(bc)
        await session.flush()

        t = TradeRecord(
            user_id=user.id,
            bot_config_id=bc.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=60000.0,
            leverage=4,
            confidence=75,
            reason="trailing char long",
            order_id="char_trailing_long",
            status="open",
            # highest - entry = 10k, atr*breakeven (200*1.5=300) << 10k
            highest_price=70000.0,
            entry_time=now - timedelta(hours=5),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        trade_id = t.id

    fetcher_mock = MagicMock()
    fetcher_mock.get_binance_klines = AsyncMock(
        return_value=[[0, 0, 0, 0, 0, 0]] * 30,
    )
    fetcher_mock.close = AsyncMock()
    mdf_cls = MagicMock(return_value=fetcher_mock)
    mdf_cls.calculate_atr = MagicMock(return_value=[200.0])
    # After #363 split, _compute_trailing_stop lives in _trades_helpers
    # which holds the top-level MarketDataFetcher binding. The router
    # patch is retained for parity with the rest of the suite (no-op
    # for GET /trades/{id} but harmless).
    with (
        patch("src.api.routers.trades.MarketDataFetcher", mdf_cls),
        patch("src.services._trades_helpers.MarketDataFetcher", mdf_cls),
    ):
        resp = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "open"
    # LONG was_profitable -> trailing active
    assert data["trailing_stop_active"] is True
    assert data["can_close_at_loss"] is False
    assert data["trailing_stop_price"] is not None


async def test_get_trade_with_trailing_strategy_short_active_branch(
    client, auth_headers, session_factory, user,
):
    """Open SHORT trade with trailing strategy hits the short-active branch.

    Short: ``entry - highest_price`` (where highest_price is the LOWEST
    since entry for shorts) must exceed the breakeven threshold.
    """
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        bc = BotConfig(
            user_id=user.id,
            name="TrailingShortBot",
            description="Edge Indicator bot",
            strategy_type="edge_indicator",
            exchange_type="bitget",
            mode="demo",
            trading_pairs='["ETHUSDT"]',
            leverage=4,
            is_enabled=False,
        )
        session.add(bc)
        await session.flush()

        t = TradeRecord(
            user_id=user.id,
            bot_config_id=bc.id,
            symbol="ETHUSDT",
            side="short",
            size=0.1,
            entry_price=3500.0,
            leverage=4,
            confidence=75,
            reason="trailing char short",
            order_id="char_trailing_short",
            status="open",
            highest_price=3000.0,  # price dropped 500 from entry
            entry_time=now - timedelta(hours=5),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        trade_id = t.id

    fetcher_mock = MagicMock()
    fetcher_mock.get_binance_klines = AsyncMock(
        return_value=[[0, 0, 0, 0, 0, 0]] * 30,
    )
    fetcher_mock.close = AsyncMock()
    mdf_cls = MagicMock(return_value=fetcher_mock)
    mdf_cls.calculate_atr = MagicMock(return_value=[50.0])  # atr*1.5=75 << 500
    # After #363 split, _compute_trailing_stop lives in _trades_helpers
    # which holds the top-level MarketDataFetcher binding.
    with (
        patch("src.api.routers.trades.MarketDataFetcher", mdf_cls),
        patch("src.services._trades_helpers.MarketDataFetcher", mdf_cls),
    ):
        resp = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "open"
    assert data["trailing_stop_active"] is True
    assert data["can_close_at_loss"] is False
    assert data["trailing_stop_price"] is not None


async def test_get_trade_with_trailing_no_highest_price_returns_inactive(
    client, auth_headers, session_factory, user,
):
    """Trade without highest_price -> early return with inactive+can_close."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        bc = BotConfig(
            user_id=user.id,
            name="TrailingBotNoHigh",
            description="Edge Indicator",
            strategy_type="edge_indicator",
            exchange_type="bitget",
            mode="demo",
            trading_pairs='["BTCUSDT"]',
            leverage=4,
            is_enabled=False,
        )
        session.add(bc)
        await session.flush()

        t = TradeRecord(
            user_id=user.id,
            bot_config_id=bc.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=60000.0,
            leverage=4,
            confidence=75,
            reason="no highest",
            order_id="char_no_highest",
            status="open",
            entry_time=now - timedelta(hours=1),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        trade_id = t.id

    resp = await client.get(f"/api/trades/{trade_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["trailing_stop_active"] is False
    assert data["can_close_at_loss"] is True


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/trades/{trade_id}/risk-state
# ═══════════════════════════════════════════════════════════════════════════


async def test_risk_state_requires_auth_returns_401(client, open_trade):
    """Unauthenticated risk-state read -> 401."""
    resp = await client.get(f"/api/trades/{open_trade.id}/risk-state")
    assert resp.status_code == 401


async def test_risk_state_feature_flag_off_returns_404(
    client, auth_headers, open_trade,
):
    """Characterization: flag off -> 404 with 'feature flag off' detail.

    404 doubles as "endpoint disabled" because no HTTP status cleanly
    maps to "feature is toggled off".
    """
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.get(
            f"/api/trades/{open_trade.id}/risk-state", headers=auth_headers,
        )
    assert resp.status_code == 404
    assert "feature flag" in resp.json()["detail"].lower()


async def test_risk_state_flag_on_nonexistent_trade_returns_404(
    client, auth_headers, user,
):
    """Flag on + unknown trade_id -> genuine not-found 404."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.get(
            "/api/trades/999999/risk-state", headers=auth_headers,
        )
    assert resp.status_code == 404


async def test_risk_state_flag_on_other_users_trade_returns_404(
    client, auth_headers, other_user_trade,
):
    """Flag on + trade owned by another user -> 404, not 403."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.get(
            f"/api/trades/{other_user_trade.id}/risk-state", headers=auth_headers,
        )
    assert resp.status_code == 404


async def test_risk_state_flag_on_happy_path_returns_snapshot_shape(
    client, auth_headers, open_trade,
):
    """Flag on + valid trade -> TpSlResponse shape.

    Legs are returned as dicts (or None). ``overall_status`` is derived
    from the per-leg statuses.
    """
    # Build a fake manager whose reconcile returns a synthetic snapshot.
    snapshot = MagicMock()
    snapshot.tp = {
        "value": 70000.0,
        "status": RiskOpStatus.CONFIRMED.value,
        "order_id": "tp_1",
        "error": None,
        "latency_ms": 12,
    }
    snapshot.sl = {
        "value": 67000.0,
        "status": RiskOpStatus.CONFIRMED.value,
        "order_id": "sl_1",
        "error": None,
        "latency_ms": 8,
    }
    snapshot.trailing = None
    snapshot.last_synced_at = datetime.now(timezone.utc)

    fake_manager = MagicMock()
    fake_manager.reconcile = AsyncMock(return_value=snapshot)

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ):
        resp = await client.get(
            f"/api/trades/{open_trade.id}/risk-state", headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) >= {
        "trade_id", "tp", "sl", "trailing", "applied_at", "overall_status",
    }
    assert data["trade_id"] == open_trade.id
    assert data["tp"]["status"] == RiskOpStatus.CONFIRMED.value
    assert data["sl"]["status"] == RiskOpStatus.CONFIRMED.value
    assert data["trailing"] is None
    assert data["overall_status"] == "all_confirmed"


async def test_risk_state_reconcile_value_error_returns_404(
    client, auth_headers, open_trade,
):
    """``RiskStateManager.reconcile`` raising ValueError -> 404 with detail."""
    fake_manager = MagicMock()
    fake_manager.reconcile = AsyncMock(side_effect=ValueError("row vanished"))

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ):
        resp = await client.get(
            f"/api/trades/{open_trade.id}/risk-state", headers=auth_headers,
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "row vanished"


# ═══════════════════════════════════════════════════════════════════════════
# PUT /api/trades/{trade_id}/tp-sl  —  shared schema validation (422)
# ═══════════════════════════════════════════════════════════════════════════


async def test_put_tp_sl_requires_auth_returns_401(client, open_trade):
    """Unauthenticated tp-sl update -> 401."""
    resp = await client.put(
        f"/api/trades/{open_trade.id}/tp-sl",
        json={"take_profit": 70000.0},
    )
    assert resp.status_code == 401


async def test_put_tp_sl_extra_field_returns_422(
    client, auth_headers, open_trade,
):
    """``UpdateTpSlRequest`` forbids unknown fields (extra='forbid') -> 422."""
    resp = await client.put(
        f"/api/trades/{open_trade.id}/tp-sl",
        headers=auth_headers,
        json={"unknown_field": True},
    )
    assert resp.status_code == 422


async def test_put_tp_sl_trailing_atr_out_of_range_returns_422(
    client, auth_headers, open_trade,
):
    """Trailing callback_pct outside [1.0, 5.0] -> pydantic validator 422."""
    resp = await client.put(
        f"/api/trades/{open_trade.id}/tp-sl",
        headers=auth_headers,
        json={"trailing_stop": {"callback_pct": 10.0}},
    )
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# PUT /api/trades/{trade_id}/tp-sl  —  legacy path (flag OFF)
# ═══════════════════════════════════════════════════════════════════════════


async def test_put_tp_sl_legacy_not_found_returns_404(
    client, auth_headers, user,
):
    """Legacy path + unknown trade -> 404."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            "/api/trades/999999/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )
    assert resp.status_code == 404


async def test_put_tp_sl_legacy_other_user_returns_404(
    client, auth_headers, other_user_trade,
):
    """Legacy path + another user's trade -> 404 (no 403 branch)."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{other_user_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 200.0},
        )
    assert resp.status_code == 404


async def test_put_tp_sl_legacy_remove_and_set_tp_conflict_returns_400(
    client, auth_headers, open_trade,
):
    """Characterization: legacy path returns **400** on TP mutex conflict.

    (The manager path returns 422 for the same conflict — this divergence
    is intentional and frozen so PR-2 knows both behaviours.)
    """
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0, "remove_tp": True},
        )
    assert resp.status_code == 400


async def test_put_tp_sl_legacy_remove_and_set_sl_conflict_returns_400(
    client, auth_headers, open_trade,
):
    """Legacy path: SL mutex conflict -> 400."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"stop_loss": 67000.0, "remove_sl": True},
        )
    assert resp.status_code == 400


async def test_put_tp_sl_legacy_tp_below_entry_long_returns_400(
    client, auth_headers, open_trade,
):
    """Long trade + TP <= entry_price -> 400 with error code detail."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 60000.0},  # below entry_price=68200
        )
    assert resp.status_code == 400
    assert "detail" in resp.json()


async def test_put_tp_sl_legacy_sl_above_entry_long_returns_400(
    client, auth_headers, open_trade,
):
    """Long trade + SL >= entry_price -> 400."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"stop_loss": 69000.0},  # above entry_price=68200
        )
    assert resp.status_code == 400


async def test_put_tp_sl_legacy_tp_above_entry_short_returns_400(
    client, auth_headers, open_trade_short,
):
    """Short trade + TP >= entry_price -> 400."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade_short.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 4000.0},  # above entry_price=3500
        )
    assert resp.status_code == 400


async def test_put_tp_sl_legacy_tp_non_positive_returns_400(
    client, auth_headers, open_trade,
):
    """Legacy path rejects non-positive TP with 400."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": -1.0},
        )
    assert resp.status_code == 400


async def test_put_tp_sl_legacy_no_exchange_connection_returns_400(
    client, auth_headers, open_trade,
):
    """Legacy path + missing ``ExchangeConnection`` -> 400 not 404."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )
    assert resp.status_code == 400


async def test_put_tp_sl_legacy_closed_trade_returns_400(
    client, auth_headers, closed_trade,
):
    """Legacy path: editing a closed trade -> 400 'Trade is not open'."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{closed_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 99000.0},
        )
    assert resp.status_code == 400


async def test_put_tp_sl_legacy_happy_path_returns_status_ok_shape(
    client, auth_headers, open_trade, exchange_connection,
):
    """Legacy happy path returns ``{"status": "ok", ...}`` shape (NOT TpSlResponse).

    This is the critical shape-divergence from the manager path and must
    be preserved verbatim until the frontend migration completes.
    """
    mock_client = AsyncMock()
    mock_client.cancel_position_tpsl = AsyncMock(return_value=True)
    mock_client.set_position_tpsl = AsyncMock(return_value=None)
    mock_client.close = AsyncMock()
    # No SUPPORTS_NATIVE_TRAILING_PROBE attribute -> probe is skipped.

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0, "stop_loss": 67000.0},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert data["take_profit"] == 70000.0
    assert data["stop_loss"] == 67000.0
    assert "trailing_stop_placed" in data
    assert "trailing_stop_software" in data


async def test_put_tp_sl_legacy_exchange_error_returns_502(
    client, auth_headers, open_trade, exchange_connection,
):
    """Legacy path: a generic exchange failure -> 502 with translated detail."""
    mock_client = AsyncMock()
    mock_client.cancel_position_tpsl = AsyncMock(
        side_effect=RuntimeError("some opaque network error")
    )
    mock_client.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )

    assert resp.status_code == 502


async def test_put_tp_sl_legacy_exchange_validation_error_returns_400(
    client, auth_headers, open_trade, exchange_connection,
):
    """Legacy path: exchange returns a 'price ...' hint -> surfaced as 400."""
    mock_client = AsyncMock()
    mock_client.cancel_position_tpsl = AsyncMock(
        side_effect=RuntimeError("price must be greater than 0")
    )
    mock_client.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )

    assert resp.status_code == 400


async def test_put_tp_sl_legacy_not_implemented_returns_400(
    client, auth_headers, open_trade, exchange_connection,
):
    """Legacy path: exchange raises NotImplementedError -> 400 with detail."""
    mock_client = AsyncMock()
    mock_client.cancel_position_tpsl = AsyncMock(side_effect=NotImplementedError())
    mock_client.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )

    assert resp.status_code == 400


async def test_put_tp_sl_legacy_missing_api_keys_returns_400(
    client, auth_headers, open_trade, session_factory, user,
):
    """Legacy path: ExchangeConnection present but no API keys at all -> 400."""
    async with session_factory() as session:
        # No demo_api_key_encrypted AND no api_key_encrypted — all None
        conn = ExchangeConnection(
            user_id=user.id,
            exchange_type="bitget",
        )
        session.add(conn)
        await session.commit()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )

    assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# PUT /api/trades/{trade_id}/tp-sl  —  manager path (flag ON)
# ═══════════════════════════════════════════════════════════════════════════


async def test_put_tp_sl_manager_remove_and_set_tp_conflict_returns_422(
    client, auth_headers, open_trade,
):
    """Characterization: manager path returns **422** for TP mutex (not 400).

    This is the documented divergence from the legacy path.
    """
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0, "remove_tp": True},
        )
    assert resp.status_code == 422


async def test_put_tp_sl_manager_remove_and_set_sl_conflict_returns_422(
    client, auth_headers, open_trade,
):
    """Manager path: SL mutex conflict -> 422."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"stop_loss": 67000.0, "remove_sl": True},
        )
    assert resp.status_code == 422


async def test_put_tp_sl_manager_remove_and_set_trailing_conflict_returns_422(
    client, auth_headers, open_trade,
):
    """Manager path: trailing mutex conflict -> 422 with descriptive detail."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={
                "trailing_stop": {"callback_pct": 2.5},
                "remove_trailing": True,
            },
        )
    assert resp.status_code == 422


async def test_put_tp_sl_manager_not_found_returns_404(
    client, auth_headers, user,
):
    """Manager path + unknown trade_id -> 404."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            "/api/trades/999999/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )
    assert resp.status_code == 404


async def test_put_tp_sl_manager_other_user_returns_404(
    client, auth_headers, other_user_trade,
):
    """Manager path + trade owned by another user -> 404 (no 403 branch)."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{other_user_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 200.0},
        )
    assert resp.status_code == 404


async def test_put_tp_sl_manager_closed_trade_returns_400(
    client, auth_headers, closed_trade,
):
    """Manager path: editing a closed trade -> 400 'Trade is not open'."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{closed_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 99000.0},
        )
    assert resp.status_code == 400


async def test_put_tp_sl_manager_tp_below_entry_long_returns_400(
    client, auth_headers, open_trade,
):
    """Manager path: long trade + TP <= entry_price -> 400 (shared validator)."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 60000.0},
        )
    assert resp.status_code == 400


async def test_put_tp_sl_manager_happy_path_returns_tpsl_response_shape(
    client, auth_headers, open_trade,
):
    """Manager happy path returns ``TpSlResponse`` shape.

    Keys: ``trade_id`` / ``tp`` / ``sl`` / ``trailing`` / ``applied_at``
    / ``overall_status``. Untouched legs are None; touched legs are
    dicts with ``status`` / ``value`` / ``order_id`` / ``latency_ms``.
    """
    fake_manager = MagicMock()
    fake_manager.apply_intent = AsyncMock(
        return_value=RiskOpResult(
            trade_id=open_trade.id,
            leg=RiskLeg.TP,
            status=RiskOpStatus.CONFIRMED,
            value=70000.0,
            order_id="tp_native_char",
            error=None,
            latency_ms=15,
        )
    )

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) >= {
        "trade_id", "tp", "sl", "trailing", "applied_at", "overall_status",
    }
    assert data["trade_id"] == open_trade.id
    assert data["sl"] is None
    assert data["trailing"] is None
    assert data["tp"] is not None
    assert data["tp"]["status"] == RiskOpStatus.CONFIRMED.value
    assert data["tp"]["value"] == 70000.0
    assert data["overall_status"] == "all_confirmed"
    fake_manager.apply_intent.assert_awaited()


async def test_put_tp_sl_manager_per_leg_exception_becomes_rejected(
    client, auth_headers, open_trade,
):
    """A raised exception inside ``apply_intent`` surfaces as a REJECTED leg.

    Per-leg try/except is load-bearing — one leg crashing must not kill
    the others. The response stays 200 with overall_status='all_rejected'.
    """
    fake_manager = MagicMock()
    fake_manager.apply_intent = AsyncMock(side_effect=RuntimeError("boom"))

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 70000.0},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["tp"]["status"] == RiskOpStatus.REJECTED.value
    assert data["tp"]["error"] == "boom"
    assert data["overall_status"] == "all_rejected"


async def test_put_tp_sl_legacy_trailing_only_runs_atr_and_place_paths(
    client, auth_headers, open_trade, exchange_connection,
):
    """Legacy path: trailing-only request exercises the ATR + place branch.

    Forces the cancel_native_trailing_stop + get_binance_klines +
    place_trailing_stop subtree to execute deterministically.
    """
    mock_client = AsyncMock()
    mock_client.cancel_native_trailing_stop = AsyncMock(return_value=True)
    mock_client.place_trailing_stop = AsyncMock(
        return_value={"orderId": "trail_1"}
    )
    mock_client.close = AsyncMock()
    # No SUPPORTS_NATIVE_TRAILING_PROBE -> probe skipped.

    fetcher_mock = MagicMock()
    fetcher_mock.get_binance_klines = AsyncMock(
        return_value=[[0, 0, 0, 0, 0, 0]] * 30,
    )
    fetcher_mock.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ), patch(
        "src.api.routers.trades.MarketDataFetcher", return_value=fetcher_mock,
    ) as mdf_cls:
        mdf_cls.calculate_atr = MagicMock(return_value=[500.0])
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"trailing_stop": {"callback_pct": 2.5}},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert data["trailing_stop_placed"] is True
    mock_client.cancel_native_trailing_stop.assert_awaited_once()
    mock_client.place_trailing_stop.assert_awaited_once()


async def test_put_tp_sl_legacy_trailing_atr_fetch_failure_uses_fallback(
    client, auth_headers, open_trade, exchange_connection,
):
    """ATR fetch failure -> fallback to 1.5%% estimate; place still called."""
    mock_client = AsyncMock()
    mock_client.cancel_native_trailing_stop = AsyncMock(return_value=True)
    mock_client.place_trailing_stop = AsyncMock(return_value=None)
    mock_client.close = AsyncMock()

    fetcher_mock = MagicMock()
    fetcher_mock.get_binance_klines = AsyncMock(side_effect=RuntimeError("binance down"))
    fetcher_mock.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ), patch(
        "src.api.routers.trades.MarketDataFetcher", return_value=fetcher_mock,
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"trailing_stop": {"callback_pct": 2.5}},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    # place_trailing_stop returned None -> software trailing branch
    assert data["trailing_stop_placed"] is False
    assert data["trailing_stop_software"] is True


async def test_put_tp_sl_legacy_with_bot_config_reads_margin_mode(
    client, auth_headers, session_factory, user, exchange_connection,
):
    """Legacy path: trade bound to a bot uses the bot's ``margin_mode``."""
    async with session_factory() as session:
        bc = BotConfig(
            user_id=user.id,
            name="LegacyMarginBot",
            description="for legacy margin test",
            strategy_type="edge_indicator",
            exchange_type="bitget",
            mode="demo",
            trading_pairs='["BTCUSDT"]',
            leverage=5,
            margin_mode="isolated",
            is_enabled=False,
        )
        session.add(bc)
        await session.flush()

        t = TradeRecord(
            user_id=user.id,
            bot_config_id=bc.id,
            symbol="BTCUSDT",
            side="long",
            size=0.01,
            entry_price=68000.0,
            leverage=5,
            confidence=75,
            reason="legacy margin trade",
            order_id="char_legacy_margin",
            status="open",
            entry_time=datetime.now(timezone.utc),
            exchange="bitget",
            demo_mode=True,
        )
        session.add(t)
        await session.commit()
        await session.refresh(t)
        trade_id = t.id

    mock_client = AsyncMock()
    mock_client.cancel_position_tpsl = AsyncMock(return_value=True)
    mock_client.set_position_tpsl = AsyncMock(return_value=None)
    mock_client.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.put(
            f"/api/trades/{trade_id}/tp-sl",
            headers=auth_headers,
            json={"take_profit": 72000.0},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_put_tp_sl_legacy_probe_branch_runs_when_supported(
    client, auth_headers, open_trade, exchange_connection,
):
    """Client with ``SUPPORTS_NATIVE_TRAILING_PROBE`` True runs the probe branch.

    Freezes the branch that reconciles ``trailing_placed`` against the
    exchange-reported state (line ~1167 of trades.py).
    """
    class _ClientWithProbe:
        SUPPORTS_NATIVE_TRAILING_PROBE = True

        def __init__(self):
            self.close = AsyncMock()

        async def cancel_position_tpsl(self, **kwargs):
            return True

        async def set_position_tpsl(self, **kwargs):
            return None

        async def cancel_native_trailing_stop(self, *args, **kwargs):
            return True

        async def place_trailing_stop(self, **kwargs):
            return {"orderId": "trail_probe_1"}

        async def has_native_trailing_stop(self, symbol, side):
            # Probe says the trailing stop is indeed live
            return True

    client_instance = _ClientWithProbe()

    fetcher_mock = MagicMock()
    fetcher_mock.get_binance_klines = AsyncMock(
        return_value=[[0, 0, 0, 0, 0, 0]] * 30,
    )
    fetcher_mock.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=client_instance,
    ), patch(
        "src.api.routers.trades.MarketDataFetcher", return_value=fetcher_mock,
    ) as mdf_cls:
        mdf_cls.calculate_atr = MagicMock(return_value=[500.0])
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"trailing_stop": {"callback_pct": 2.5}},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ok"
    assert data["trailing_stop_placed"] is True


async def test_sync_trades_classify_close_wins_when_rsm_enabled(
    client, auth_headers, open_trade, exchange_connection,
):
    """Characterization: with the RSM flag on, sync defers to ``classify_close``.

    The response's ``exit_reason`` reflects the manager's attribution —
    the legacy heuristic does not run.
    """
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_close_fill_price = AsyncMock(return_value=None)
    mock_client.get_ticker = AsyncMock(
        return_value=MagicMock(last_price=68500.0)
    )
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.05)
    mock_client.close = AsyncMock()

    fake_manager = MagicMock()
    fake_manager.classify_close = AsyncMock(return_value="TAKE_PROFIT_NATIVE")
    fake_manager.reconcile = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
    assert data["closed_trades"][0]["exit_reason"] == "TAKE_PROFIT_NATIVE"
    fake_manager.classify_close.assert_awaited_once()
    fake_manager.reconcile.assert_awaited_once()


async def test_sync_trades_classify_close_failure_falls_back_to_heuristic(
    client, auth_headers, open_trade, exchange_connection,
):
    """RSM on + classify_close raising -> legacy heuristic wins silently."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_close_fill_price = AsyncMock(return_value=None)
    mock_client.get_ticker = AsyncMock(
        return_value=MagicMock(last_price=70000.0)  # within 0.5%% of TP=70000
    )
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.0)
    mock_client.get_funding_fees = AsyncMock(return_value=0.0)
    mock_client.close = AsyncMock()

    fake_manager = MagicMock()
    fake_manager.classify_close = AsyncMock(side_effect=RuntimeError("boom"))
    fake_manager.reconcile = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
    # Heuristic kicks in; exit_price==70000 matches TP within the 0.5%% band
    assert data["closed_trades"][0]["exit_reason"] in {
        "TAKE_PROFIT", "STOP_LOSS", "MANUAL_CLOSE",
    }


async def test_sync_trades_uses_close_fill_price_when_available(
    client, auth_headers, open_trade, exchange_connection,
):
    """``get_close_fill_price`` takes precedence over ticker price if set."""
    mock_client = AsyncMock()
    mock_client.get_open_positions = AsyncMock(return_value=[])
    mock_client.get_close_fill_price = AsyncMock(return_value=69500.0)
    mock_client.get_trade_total_fees = AsyncMock(return_value=0.5)
    mock_client.get_funding_fees = AsyncMock(return_value=0.05)
    mock_client.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(False),
    ), patch(
        "src.api.routers.trades.decrypt_value", side_effect=lambda v: v,
    ), patch(
        "src.api.routers.trades.create_exchange_client", return_value=mock_client,
    ):
        resp = await client.post("/api/trades/sync", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] == 1
    # close fill price (69500) is the exit_price; get_ticker was NOT awaited
    assert data["closed_trades"][0]["exit_price"] == 69500.0
    mock_client.get_ticker.assert_not_called()


async def test_put_tp_sl_manager_remove_tp_and_sl_calls_apply_intent(
    client, auth_headers, open_trade,
):
    """Manager path: remove_tp + remove_sl each call apply_intent with None.

    Exercises the ``remove_*`` branches in ``_handle_tp_sl_via_manager``.
    """
    fake_manager = MagicMock()
    fake_manager.apply_intent = AsyncMock(
        return_value=RiskOpResult(
            trade_id=open_trade.id,
            leg=RiskLeg.TP,
            status=RiskOpStatus.CLEARED,
            value=None,
            order_id=None,
            error=None,
            latency_ms=5,
        )
    )

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"remove_tp": True, "remove_sl": True},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Both legs cleared -> overall_status = all_confirmed (CLEARED is OK)
    assert data["tp"] is not None
    assert data["sl"] is not None
    assert fake_manager.apply_intent.await_count == 2


async def test_put_tp_sl_manager_trailing_stop_path_runs(
    client, auth_headers, open_trade,
):
    """Manager path with a ``trailing_stop`` payload hits the ATR helper.

    Verifies that ``_compute_atr_for_trailing`` +
    ``_build_trailing_intent`` are consumed and ``apply_intent`` receives
    the TRAILING leg.
    """
    fake_manager = MagicMock()

    async def _apply_intent(trade_id, leg, value):
        return RiskOpResult(
            trade_id=trade_id,
            leg=leg,
            status=RiskOpStatus.CONFIRMED,
            value=value,
            order_id="trail_char_1",
            error=None,
            latency_ms=3,
        )

    fake_manager.apply_intent = AsyncMock(side_effect=_apply_intent)

    fetcher_mock = MagicMock()
    fetcher_mock.get_binance_klines = AsyncMock(
        return_value=[[0, 0, 0, 0, 0, 0]] * 30,
    )
    fetcher_mock.close = AsyncMock()

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ), patch(
        "src.api.routers.trades.MarketDataFetcher", return_value=fetcher_mock,
    ) as mdf_cls:
        mdf_cls.calculate_atr = MagicMock(return_value=[500.0])
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"trailing_stop": {"callback_pct": 2.5}},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["trailing"] is not None
    assert data["trailing"]["status"] == RiskOpStatus.CONFIRMED.value
    fake_manager.apply_intent.assert_awaited_once()
    # The leg passed through is TRAILING
    call_args = fake_manager.apply_intent.await_args
    assert call_args.args[1] == RiskLeg.TRAILING


async def test_put_tp_sl_manager_sl_below_entry_long_returns_400(
    client, auth_headers, open_trade,
):
    """Manager validator: long trade + SL >= entry -> 400."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"stop_loss": 69000.0},  # above entry=68200 (invalid for long)
        )
    assert resp.status_code == 400


async def test_put_tp_sl_manager_sl_non_positive_returns_400(
    client, auth_headers, open_trade,
):
    """Manager validator: non-positive SL -> 400."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=auth_headers,
            json={"stop_loss": -1.0},
        )
    assert resp.status_code == 400


async def test_put_tp_sl_manager_sl_below_entry_short_returns_400(
    client, auth_headers, open_trade_short,
):
    """Manager validator: short trade + SL <= entry -> 400."""
    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ):
        resp = await client.put(
            f"/api/trades/{open_trade_short.id}/tp-sl",
            headers=auth_headers,
            json={"stop_loss": 3000.0},  # below entry=3500 (invalid for short)
        )
    assert resp.status_code == 400


async def test_put_tp_sl_manager_idempotency_key_caches_response(
    client, auth_headers, open_trade,
):
    """Repeated request with same Idempotency-Key returns cached response.

    ``apply_intent`` should be awaited exactly once across the two calls.
    """
    fake_manager = MagicMock()
    fake_manager.apply_intent = AsyncMock(
        return_value=RiskOpResult(
            trade_id=open_trade.id,
            leg=RiskLeg.TP,
            status=RiskOpStatus.CONFIRMED,
            value=70000.0,
            order_id="tp_idem_1",
            error=None,
            latency_ms=5,
        )
    )

    headers = {**auth_headers, "Idempotency-Key": "char-idem-key-1"}

    with patch(
        "src.api.routers.trades.settings", _flag_settings(True),
    ), patch(
        "src.api.routers.trades.get_risk_state_manager",
        return_value=fake_manager,
    ):
        r1 = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=headers,
            json={"take_profit": 70000.0},
        )
        r2 = await client.put(
            f"/api/trades/{open_trade.id}/tp-sl",
            headers=headers,
            json={"take_profit": 70000.0},
        )

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert fake_manager.apply_intent.await_count == 1
