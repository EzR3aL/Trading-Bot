"""
Integration tests for the manual close-position endpoint (Issue #275).

Asserts that ``POST /api/bots/{bot_id}/close-position/{symbol}`` goes through
the shared TradeCloser helper: writes fees/funding/builder_fee, dispatches
Discord+Telegram notifications, broadcasts on the WebSocket manager, emits
``trade_closed`` on the SSE event bus, and updates RiskManager daily stats.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
# Use a valid 32-byte Fernet key so encrypt_value/decrypt_value work in fixtures.
os.environ["ENCRYPTION_KEY"] = "iDh4DatDZy2cb_esIAoNk_blWkQx3zDG14cj1lq8Rgo="
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.integration.conftest import auth_header

from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User
from src.models.session import get_session
from src.utils.encryption import encrypt_value


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def user_obj(user_token):
    """Return the test user object created by user_token fixture."""
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(select(User).where(User.username == "testuser"))
        return result.scalar_one()


@pytest_asyncio.fixture
async def manual_close_fixtures(user_obj):
    """Seed a bot config, exchange connection, and an open trade for manual close."""
    config = BotConfig(
        user_id=user_obj.id,
        name="Manual Close Bot",
        strategy_type="edge_indicator",
        exchange_type="bitget",
        mode="demo",
        trading_pairs=json.dumps(["BTCUSDT"]),
        leverage=5,
        position_size_percent=10.0,
        max_trades_per_day=3,
        take_profit_percent=2.0,
        stop_loss_percent=1.0,
        daily_loss_limit_percent=5.0,
        is_enabled=False,
        # Notifier credentials — dummy, but the encryption round-trip
        # must decrypt successfully inside the endpoint handler.
        discord_webhook_url=encrypt_value("https://discord.test/hook"),
        telegram_bot_token=encrypt_value("fake-bot-token"),
        telegram_chat_id=encrypt_value("123456"),
    )
    async with get_session() as session:
        session.add(config)

    # Reload to fetch the id after commit
    from sqlalchemy import select
    async with get_session() as session:
        config = (await session.execute(
            select(BotConfig).where(BotConfig.user_id == user_obj.id)
        )).scalar_one()

    conn = ExchangeConnection(
        user_id=user_obj.id,
        exchange_type="bitget",
        demo_api_key_encrypted=encrypt_value("demo-key"),
        demo_api_secret_encrypted=encrypt_value("demo-secret"),
        demo_passphrase_encrypted=encrypt_value("demo-pass"),
    )
    async with get_session() as session:
        session.add(conn)

    now = datetime.now(timezone.utc)
    trade = TradeRecord(
        user_id=user_obj.id,
        bot_config_id=config.id,
        symbol="BTCUSDT",
        side="long",
        size=0.01,
        entry_price=100_000.0,
        take_profit=102_000.0,
        stop_loss=99_000.0,
        leverage=5,
        confidence=80,
        reason="entry",
        order_id="entry_order_1",
        status="open",
        entry_time=now - timedelta(minutes=30),
        exchange="bitget",
        demo_mode=True,
    )
    async with get_session() as session:
        session.add(trade)

    async with get_session() as session:
        trade = (await session.execute(
            select(TradeRecord).where(TradeRecord.bot_config_id == config.id)
        )).scalar_one()

    return {"config": config, "trade": trade, "user": user_obj}


class _StubPosition:
    def __init__(self, size: float = 0.0):
        self.size = size


class _StubTicker:
    def __init__(self, last_price: float):
        self.last_price = last_price


class _StubCloseOrder:
    def __init__(self, order_id: str = "close_order_1"):
        self.order_id = order_id


class _StubExchangeClient:
    """Minimal ExchangeClient stand-in for the manual-close endpoint."""

    def __init__(self, *args, **kwargs):
        self.close_calls: list = []
        self.builder_fee_called = False

    async def close_position(self, symbol, side, margin_mode="cross"):
        self.close_calls.append((symbol, side, margin_mode))
        return _StubCloseOrder()

    async def get_position(self, symbol):
        # Report the position as fully closed so the verification succeeds
        return _StubPosition(size=0.0)

    async def get_close_fill_price(self, symbol):
        return 101_500.0

    async def get_ticker(self, symbol):
        return _StubTicker(last_price=101_500.0)

    async def get_trade_total_fees(self, symbol, entry_order_id, close_order_id=None):
        return 1.23

    async def get_funding_fees(self, symbol, start_time_ms, end_time_ms):
        return 0.45

    def calculate_builder_fee(self, entry_price, exit_price, size):
        self.builder_fee_called = True
        return 0.07


@pytest.fixture
def stub_exchange_factory(monkeypatch):
    """Replace ``create_exchange_client`` with a stub so no network calls happen."""
    stub = _StubExchangeClient()

    def _factory(*args, **kwargs):
        return stub

    import src.exchanges.factory as factory_module
    monkeypatch.setattr(factory_module, "create_exchange_client", _factory)
    # The endpoint imports via ``from src.exchanges.factory import create_exchange_client``
    # inside the function body, which resolves against the module attribute,
    # so patching factory_module is enough.
    return stub


@pytest.fixture
def stub_notifiers(monkeypatch):
    """Patch DiscordNotifier + TelegramNotifier so dispatch can be asserted."""
    discord_calls: list = []
    telegram_calls: list = []

    class _StubDiscord:
        def __init__(self, webhook_url: str):
            self.webhook_url = webhook_url

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send_trade_exit(self, **kwargs) -> bool:
            discord_calls.append(kwargs)
            return True

    class _StubTelegram:
        def __init__(self, bot_token: str, chat_id: str):
            self.bot_token = bot_token
            self.chat_id = chat_id

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send_trade_exit(self, **kwargs) -> bool:
            telegram_calls.append(kwargs)
            return True

    # Patch the symbols at their import sites inside src.bot.notifications
    import src.bot.notifications as bot_notif_module
    monkeypatch.setattr(bot_notif_module, "DiscordNotifier", _StubDiscord)

    # TelegramNotifier is imported lazily inside _load_notifiers_from_config,
    # so patch it on the telegram_notifier module itself.
    import src.notifications.telegram_notifier as tg_module
    monkeypatch.setattr(tg_module, "TelegramNotifier", _StubTelegram)

    # log_notification writes to DB; stub to a no-op so missing tables don't
    # break the assertions.
    async def _noop_log(**kwargs):
        return None

    monkeypatch.setattr(bot_notif_module, "log_notification", _noop_log)

    return {"discord": discord_calls, "telegram": telegram_calls}


@pytest.fixture
def stub_ws_manager(monkeypatch):
    """Record WebSocket broadcasts instead of sending them."""
    calls: list = []

    async def _broadcast_to_user(user_id, event_type, data):
        calls.append((user_id, event_type, data))

    import src.api.websocket.manager as ws_module
    monkeypatch.setattr(ws_module.ws_manager, "broadcast_to_user", _broadcast_to_user)
    return calls


@pytest.fixture
def event_bus_listener(monkeypatch):
    """Reset the SSE event bus and record trade events."""
    import src.bot.event_bus as eb_module

    eb_module.reset_event_bus()
    bus = eb_module.get_event_bus()

    events: list = []

    original_publish = bus.publish

    async def _capture(event_type, user_id, trade_id=None, data=None):
        events.append({
            "event": event_type,
            "user_id": user_id,
            "trade_id": trade_id,
            "data": data,
        })
        await original_publish(event_type, user_id, trade_id, data)

    monkeypatch.setattr(bus, "publish", _capture)
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_close_returns_ok_with_pnl_and_exit_price(
    client,
    user_token,
    manual_close_fixtures,
    stub_exchange_factory,
    stub_notifiers,
    stub_ws_manager,
    event_bus_listener,
):
    """Endpoint returns 200 with pnl + exit_price and marks the trade closed in DB."""
    fixtures = manual_close_fixtures
    bot_id = fixtures["config"].id

    response = await client.post(
        f"/api/bots/{bot_id}/close-position/BTCUSDT",
        headers=auth_header(user_token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["exit_price"] == 101_500.0
    # long 0.01 @ 100k → 101.5k = +15
    assert body["pnl"] == pytest.approx(15.0, rel=1e-3)

    from sqlalchemy import select

    async with get_session() as session:
        trade = (await session.execute(
            select(TradeRecord).where(TradeRecord.id == fixtures["trade"].id)
        )).scalar_one()

    assert trade.status == "closed"
    assert trade.exit_reason == "MANUAL_CLOSE"
    assert trade.exit_price == 101_500.0
    assert trade.exit_time is not None


@pytest.mark.asyncio
async def test_manual_close_persists_fee_fields(
    client,
    user_token,
    manual_close_fixtures,
    stub_exchange_factory,
    stub_notifiers,
    stub_ws_manager,
    event_bus_listener,
):
    """Exchange fees, funding payments, and builder fee land on the trade row."""
    fixtures = manual_close_fixtures
    bot_id = fixtures["config"].id

    response = await client.post(
        f"/api/bots/{bot_id}/close-position/BTCUSDT",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200, response.text

    from sqlalchemy import select

    async with get_session() as session:
        trade = (await session.execute(
            select(TradeRecord).where(TradeRecord.id == fixtures["trade"].id)
        )).scalar_one()

    assert trade.fees == pytest.approx(1.23, rel=1e-3)
    assert trade.funding_paid == pytest.approx(0.45, rel=1e-3)
    # builder_fee column may be 0.07 (bitget still has calculate_builder_fee
    # in the stub, so we verify it landed on the trade record).
    assert trade.builder_fee == pytest.approx(0.07, rel=1e-3)
    assert trade.close_order_id == "close_order_1"


@pytest.mark.asyncio
async def test_manual_close_triggers_discord_and_telegram_notifications(
    client,
    user_token,
    manual_close_fixtures,
    stub_exchange_factory,
    stub_notifiers,
    stub_ws_manager,
    event_bus_listener,
):
    """Manual close dispatches trade_exit notifications to both channels."""
    fixtures = manual_close_fixtures
    bot_id = fixtures["config"].id

    response = await client.post(
        f"/api/bots/{bot_id}/close-position/BTCUSDT",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200, response.text

    assert len(stub_notifiers["discord"]) == 1, "Discord send_trade_exit not called"
    assert len(stub_notifiers["telegram"]) == 1, "Telegram send_trade_exit not called"

    discord_payload = stub_notifiers["discord"][0]
    assert discord_payload["symbol"] == "BTCUSDT"
    assert discord_payload["side"] == "long"
    assert discord_payload["reason"] == "MANUAL_CLOSE"
    assert discord_payload["exit_price"] == 101_500.0
    assert discord_payload["pnl"] == pytest.approx(15.0, rel=1e-3)


@pytest.mark.asyncio
async def test_manual_close_broadcasts_on_websocket(
    client,
    user_token,
    manual_close_fixtures,
    stub_exchange_factory,
    stub_notifiers,
    stub_ws_manager,
    event_bus_listener,
):
    """WebSocket manager receives a ``trade_closed`` broadcast for the user."""
    fixtures = manual_close_fixtures
    bot_id = fixtures["config"].id

    response = await client.post(
        f"/api/bots/{bot_id}/close-position/BTCUSDT",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200, response.text

    # The close helper schedules the broadcast as a background task; give
    # the loop a tick to run pending callbacks.
    await asyncio.sleep(0)

    assert any(
        event == "trade_closed" and data.get("symbol") == "BTCUSDT"
        for (_, event, data) in stub_ws_manager
    ), f"WS broadcast missing, got: {stub_ws_manager}"


@pytest.mark.asyncio
async def test_manual_close_emits_sse_trade_closed(
    client,
    user_token,
    manual_close_fixtures,
    stub_exchange_factory,
    stub_notifiers,
    stub_ws_manager,
    event_bus_listener,
):
    """Manual close publishes ``trade_closed`` on the SSE event bus."""
    from src.bot.event_bus import EVENT_TRADE_CLOSED

    fixtures = manual_close_fixtures
    bot_id = fixtures["config"].id

    response = await client.post(
        f"/api/bots/{bot_id}/close-position/BTCUSDT",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200, response.text

    # publish_trade_event schedules a task — allow it to run
    await asyncio.sleep(0)

    matching = [e for e in event_bus_listener if e["event"] == EVENT_TRADE_CLOSED]
    assert matching, f"No trade_closed event emitted, got: {event_bus_listener}"
    assert matching[0]["user_id"] == fixtures["user"].id
    assert matching[0]["trade_id"] == fixtures["trade"].id


@pytest.mark.asyncio
async def test_manual_close_uses_live_worker_risk_manager_when_running(
    client,
    test_app,
    user_token,
    manual_close_fixtures,
    stub_exchange_factory,
    stub_notifiers,
    stub_ws_manager,
    event_bus_listener,
):
    """If a BotWorker is live, its RiskManager.record_trade_exit is called."""
    fixtures = manual_close_fixtures
    bot_id = fixtures["config"].id

    # Build a fake worker whose _risk_manager records trade exits.
    record_calls: list = []

    class _FakeRiskManager:
        def record_trade_exit(self, **kwargs):
            record_calls.append(kwargs)
            return True

    send_calls: list = []

    async def _fake_send_notification(send_fn, event_type="unknown", summary=None):
        send_calls.append((event_type, summary))

    fake_worker = MagicMock()
    fake_worker._risk_manager = _FakeRiskManager()
    fake_worker._send_notification = _fake_send_notification

    # Replace the orchestrator's _workers dict so the endpoint finds our worker.
    test_app.state.orchestrator._workers = {bot_id: fake_worker}

    response = await client.post(
        f"/api/bots/{bot_id}/close-position/BTCUSDT",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200, response.text

    assert len(record_calls) == 1, "Live RiskManager.record_trade_exit was not used"
    call = record_calls[0]
    assert call["symbol"] == "BTCUSDT"
    assert call["side"] == "long"
    assert call["reason"] == "MANUAL_CLOSE"
    assert call["fees"] == pytest.approx(1.23, rel=1e-3)
    assert call["funding_paid"] == pytest.approx(0.45, rel=1e-3)

    # The live worker's notification dispatcher must also have been used
    assert any(event == "trade_exit" for event, _ in send_calls)
