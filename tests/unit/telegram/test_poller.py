"""Unit tests for :mod:`src.telegram.poller` (TelegramPoller).

Covers:
- start: skips task creation when token map is empty
- start: creates task and logs when tokens found
- stop: cancels task and clears running flag
- _refresh_token_map: loads and decrypts token→chat→user mapping
- _refresh_token_map: ignores rows with bad encryption
- _refresh_token_map: handles DB exception gracefully
- _register_commands: registers on first call, skips on subsequent
- _register_commands: handles non-200 response
- _poll_token: dispatches updates, advances offset
- _poll_token: returns early on non-200
- _poll_token: handles timeout without crashing
- _handle_update: ignores messages without text
- _handle_update: ignores unknown chat_id
- _handle_update: ignores non-command text
- _handle_update: routes command, sends response
- _send_response: calls Telegram sendMessage API
- _send_response: handles failed send gracefully
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ["ENCRYPTION_KEY"] = "8P5tm7omM-7rNyRwE0VT2HQjZ08Q5Q-IgOyfTnf8_Ts="
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.telegram.poller import TelegramPoller
from src.utils.encryption import encrypt_value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_response(status: int = 200, json_body: dict | None = None):
    """Build a mock aiohttp response usable as async context manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_body or {"ok": True, "result": []})
    resp.text = AsyncMock(return_value="Bad Request")
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_http_session(resp):
    """Wrap response in a mock aiohttp.ClientSession context manager."""
    session = MagicMock()
    session.get = MagicMock(return_value=resp)
    session.post = MagicMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_does_nothing_when_no_tokens():
    poller = TelegramPoller()
    with patch.object(poller, "_refresh_token_map", AsyncMock()):
        poller._token_map = {}  # empty after refresh
        await poller.start()
    assert poller._task is None


@pytest.mark.asyncio
async def test_start_creates_task_when_tokens_exist():
    poller = TelegramPoller()

    async def fake_loop():
        await asyncio.sleep(10)

    with patch.object(poller, "_refresh_token_map", AsyncMock()):
        with patch.object(poller, "_poll_loop", fake_loop):
            poller._token_map = {"token123": {"chat1": 1}}
            await poller.start()

    assert poller._task is not None
    poller._task.cancel()
    try:
        await poller._task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_start_is_idempotent():
    """Calling start() twice does not create a second task."""
    poller = TelegramPoller()

    async def fake_loop():
        await asyncio.sleep(10)

    with patch.object(poller, "_refresh_token_map", AsyncMock()):
        with patch.object(poller, "_poll_loop", fake_loop):
            poller._token_map = {"tok": {"chat": 1}}
            await poller.start()
            task1 = poller._task
            await poller.start()
            task2 = poller._task

    assert task1 is task2
    task1.cancel()
    try:
        await task1
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_stop_cancels_task():
    poller = TelegramPoller()
    poller._running = True

    async def fake_loop():
        await asyncio.sleep(10)

    poller._task = asyncio.create_task(fake_loop())
    await poller.stop()

    assert poller._running is False
    assert poller._task.done()


# ---------------------------------------------------------------------------
# _refresh_token_map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_map_builds_mapping():
    poller = TelegramPoller()

    enc_token = encrypt_value("bot-token-abc")
    enc_chat = encrypt_value("12345")

    mock_rows = [(enc_token, enc_chat, 7)]
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = mock_rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.telegram.poller.get_session", return_value=ctx):
        await poller._refresh_token_map()

    assert "bot-token-abc" in poller._token_map
    assert poller._token_map["bot-token-abc"]["12345"] == 7


@pytest.mark.asyncio
async def test_refresh_token_map_skips_bad_decrypt():
    poller = TelegramPoller()

    # Row with corrupt/non-encrypted token
    mock_rows = [("not-encrypted", "also-not-encrypted", 1)]
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = mock_rows
    mock_db.execute = AsyncMock(return_value=mock_result)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.telegram.poller.get_session", return_value=ctx):
        await poller._refresh_token_map()

    # Token map should be empty since all rows failed to decrypt
    assert poller._token_map == {}


@pytest.mark.asyncio
async def test_refresh_token_map_handles_db_exception():
    poller = TelegramPoller()
    original_map = {"tok": {"chat": 1}}
    poller._token_map = dict(original_map)

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("DB unreachable"))
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.telegram.poller.get_session", return_value=ctx):
        await poller._refresh_token_map()  # must not raise

    # Map should be unchanged when refresh fails
    assert poller._token_map == original_map


# ---------------------------------------------------------------------------
# _register_commands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_commands_on_first_call():
    poller = TelegramPoller()
    resp = _make_http_response(200, {"ok": True})
    mock_session_cls = _make_http_session(resp)

    with patch("src.telegram.poller.aiohttp.ClientSession", mock_session_cls):
        await poller._register_commands("my-bot-token")

    assert "my-bot-token" in poller._commands_registered


@pytest.mark.asyncio
async def test_register_commands_skips_if_already_registered():
    poller = TelegramPoller()
    poller._commands_registered.add("my-bot-token")

    with patch("src.telegram.poller.aiohttp.ClientSession") as mock_cls:
        await poller._register_commands("my-bot-token")
        mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_register_commands_handles_non_200():
    poller = TelegramPoller()
    resp = _make_http_response(400)
    mock_session_cls = _make_http_session(resp)

    with patch("src.telegram.poller.aiohttp.ClientSession", mock_session_cls):
        await poller._register_commands("fail-token")

    # Should NOT be added to registered set
    assert "fail-token" not in poller._commands_registered


# ---------------------------------------------------------------------------
# _poll_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_token_advances_offset_on_update():
    poller = TelegramPoller()
    update_data = {
        "ok": True,
        "result": [
            {
                "update_id": 100,
                "message": {
                    "chat": {"id": "999"},
                    "text": "/status",
                },
            }
        ],
    }
    resp = _make_http_response(200, update_data)
    mock_session_cls = _make_http_session(resp)

    with patch("src.telegram.poller.aiohttp.ClientSession", mock_session_cls):
        with patch.object(poller, "_handle_update", AsyncMock()):
            await poller._poll_token("tok", {"999": 1})

    assert poller._offsets["tok"] == 101


@pytest.mark.asyncio
async def test_poll_token_returns_early_on_non_200():
    poller = TelegramPoller()
    resp = _make_http_response(500)
    mock_session_cls = _make_http_session(resp)

    with patch("src.telegram.poller.aiohttp.ClientSession", mock_session_cls):
        await poller._poll_token("tok", {})

    assert poller._offsets["tok"] == 0  # unchanged


@pytest.mark.asyncio
async def test_poll_token_handles_timeout():
    poller = TelegramPoller()

    session_mock = MagicMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    session_mock.get = MagicMock(side_effect=asyncio.TimeoutError())

    with patch("src.telegram.poller.aiohttp.ClientSession", MagicMock(return_value=session_mock)):
        await poller._poll_token("tok", {})  # must not raise


# ---------------------------------------------------------------------------
# _handle_update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_update_ignores_update_without_message():
    poller = TelegramPoller()
    with patch("src.telegram.poller.handle_command", AsyncMock(return_value="ok")):
        with patch.object(poller, "_send_response", AsyncMock()) as mock_send:
            await poller._handle_update("tok", {"update_id": 1}, {})
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_handle_update_ignores_unknown_chat():
    poller = TelegramPoller()
    update = {
        "update_id": 1,
        "message": {"chat": {"id": "unknown-chat"}, "text": "/status"},
    }
    with patch.object(poller, "_send_response", AsyncMock()) as mock_send:
        await poller._handle_update("tok", update, {"known-chat": 1})
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_handle_update_ignores_non_command_text():
    poller = TelegramPoller()
    update = {
        "update_id": 1,
        "message": {"chat": {"id": "chat1"}, "text": "hello world"},
    }
    with patch.object(poller, "_send_response", AsyncMock()) as mock_send:
        await poller._handle_update("tok", update, {"chat1": 1})
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_handle_update_routes_command_and_sends_response():
    poller = TelegramPoller()
    update = {
        "update_id": 1,
        "message": {"chat": {"id": "chat1"}, "text": "/status"},
    }

    with patch("src.telegram.poller.handle_command", AsyncMock(return_value="Bot is running.")) as mock_cmd:
        with patch.object(poller, "_send_response", AsyncMock()) as mock_send:
            await poller._handle_update("tok", update, {"chat1": 99})

    mock_cmd.assert_awaited_once_with("/status", 99, "")
    mock_send.assert_awaited_once_with("tok", "chat1", "Bot is running.")


@pytest.mark.asyncio
async def test_handle_update_parses_botname_from_command():
    """Handle /command@BotName format."""
    poller = TelegramPoller()
    update = {
        "update_id": 1,
        "message": {"chat": {"id": "chat1"}, "text": "/status@MyTradingBot"},
    }

    with patch("src.telegram.poller.handle_command", AsyncMock(return_value="ok")) as mock_cmd:
        with patch.object(poller, "_send_response", AsyncMock()):
            await poller._handle_update("tok", update, {"chat1": 5})

    # command should be stripped of @botname
    call_args = mock_cmd.call_args[0]
    assert call_args[0] == "/status"


@pytest.mark.asyncio
async def test_handle_update_command_handler_error_returns_fallback():
    poller = TelegramPoller()
    update = {
        "update_id": 1,
        "message": {"chat": {"id": "chat1"}, "text": "/crash"},
    }

    with patch("src.telegram.poller.handle_command", AsyncMock(side_effect=RuntimeError("boom"))):
        with patch.object(poller, "_send_response", AsyncMock()) as mock_send:
            await poller._handle_update("tok", update, {"chat1": 1})

    mock_send.assert_awaited_once()
    sent_text = mock_send.call_args[0][2]
    assert "Fehler" in sent_text or "error" in sent_text.lower()


# ---------------------------------------------------------------------------
# _send_response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_response_posts_to_telegram():
    poller = TelegramPoller()
    resp = _make_http_response(200)
    mock_session_cls = _make_http_session(resp)

    with patch("src.telegram.poller.aiohttp.ClientSession", mock_session_cls):
        await poller._send_response("tok", "chat1", "Hello!")

    # Verify post was called (via the session mock)
    session_instance = mock_session_cls.return_value.__aenter__.return_value
    session_instance.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_response_handles_exception_gracefully():
    poller = TelegramPoller()

    session_mock = MagicMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    session_mock.post = MagicMock(side_effect=aiohttp.ClientError("connection refused"))

    with patch("src.telegram.poller.aiohttp.ClientSession", MagicMock(return_value=session_mock)):
        await poller._send_response("tok", "chat1", "Hello!")  # must not raise
