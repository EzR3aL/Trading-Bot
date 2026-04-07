"""Tests for get_all_user_clients — #141 regression.

The factory now returns a list of (exchange_type, demo_mode, client) tuples
instead of a single dict keyed by exchange_type. This allows the portfolio
endpoints to query both live and demo modes per connection, which is
required when a user runs a bot in demo mode on an exchange that only has
live credentials stored (e.g. Bitget with paptrading header).
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force a valid Fernet key for this test module. conftest.py sets a shorter
# placeholder that fails Fernet's 32-byte-base64 validation on first use, but
# encryption is lazy-initialized so overriding here works as long as we do it
# before the first encrypt_value() call.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
from cryptography.fernet import Fernet as _TestFernet
os.environ["ENCRYPTION_KEY"] = _TestFernet.generate_key().decode()

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.factory import get_all_user_clients
from src.utils.encryption import encrypt_value


def _mock_connection(
    exchange_type: str,
    has_live: bool = False,
    has_demo: bool = False,
    has_passphrase: bool = True,
) -> MagicMock:
    """Build a fake ExchangeConnection row with encrypted credentials."""
    conn = MagicMock()
    conn.exchange_type = exchange_type
    conn.api_key_encrypted = encrypt_value("live-key") if has_live else None
    conn.api_secret_encrypted = encrypt_value("live-secret") if has_live else None
    conn.passphrase_encrypted = (
        encrypt_value("live-pass") if (has_live and has_passphrase) else None
    )
    conn.demo_api_key_encrypted = encrypt_value("demo-key") if has_demo else None
    conn.demo_api_secret_encrypted = encrypt_value("demo-secret") if has_demo else None
    conn.demo_passphrase_encrypted = (
        encrypt_value("demo-pass") if (has_demo and has_passphrase) else None
    )
    return conn


async def _mock_db_with(connections):
    """Build a fake db session that returns the given connections."""
    db = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=connections)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_returns_list_of_tuples(mock_create):
    """Factory returns list of (exchange, demo_mode, client) tuples."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with([_mock_connection("bitget", has_live=True)])

    result = await get_all_user_clients(user_id=1, db=db)

    assert isinstance(result, list)
    assert all(isinstance(t, tuple) and len(t) == 3 for t in result)


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_bitget_live_only_produces_both_modes(mock_create):
    """Regression for #141: Bitget supports demo via header on the live key,
    so a user with only live credentials must still get a demo client."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with([_mock_connection("bitget", has_live=True)])

    result = await get_all_user_clients(user_id=1, db=db)

    modes = {(ex, demo) for ex, demo, _ in result}
    assert ("bitget", False) in modes
    assert ("bitget", True) in modes
    assert len(result) == 2


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_bingx_live_only_produces_both_modes(mock_create):
    """BingX VST uses the same key against a separate URL → both modes."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with([_mock_connection("bingx", has_live=True, has_passphrase=False)])

    result = await get_all_user_clients(user_id=1, db=db)

    modes = {(ex, demo) for ex, demo, _ in result}
    assert ("bingx", False) in modes
    assert ("bingx", True) in modes


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_hyperliquid_live_only_skips_demo(mock_create):
    """Hyperliquid demo = testnet = separate wallet → no demo client from
    live-only credentials. Only a live client is produced."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with(
        [_mock_connection("hyperliquid", has_live=True, has_passphrase=False)]
    )

    result = await get_all_user_clients(user_id=1, db=db)

    modes = {(ex, demo) for ex, demo, _ in result}
    assert modes == {("hyperliquid", False)}


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_weex_live_only_skips_demo(mock_create):
    """Weex has no demo support at all → only live client."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with([_mock_connection("weex", has_live=True)])

    result = await get_all_user_clients(user_id=1, db=db)

    modes = {(ex, demo) for ex, demo, _ in result}
    assert modes == {("weex", False)}


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_demo_only_credentials(mock_create):
    """User with only demo credentials gets a single demo client."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with([_mock_connection("hyperliquid", has_demo=True, has_passphrase=False)])

    result = await get_all_user_clients(user_id=1, db=db)

    modes = {(ex, demo) for ex, demo, _ in result}
    assert modes == {("hyperliquid", True)}


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_both_live_and_dedicated_demo_credentials(mock_create):
    """When dedicated demo credentials are stored, the factory must use
    THOSE for the demo client instead of re-using the live key."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with(
        [_mock_connection("bitget", has_live=True, has_demo=True)]
    )

    result = await get_all_user_clients(user_id=1, db=db)

    # One live client, one demo client from dedicated demo key (not from
    # the live key via paptrading header, because dedicated demo creds exist).
    modes = {(ex, demo) for ex, demo, _ in result}
    assert modes == {("bitget", False), ("bitget", True)}
    assert len(result) == 2


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_multiple_connections_mixed_modes(mock_create):
    """Several exchanges at once: Bitget (live-only, produces both),
    Hyperliquid (demo-only), Weex (live-only, skipped demo)."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with([
        _mock_connection("bitget", has_live=True),
        _mock_connection("hyperliquid", has_demo=True, has_passphrase=False),
        _mock_connection("weex", has_live=True),
    ])

    result = await get_all_user_clients(user_id=1, db=db)

    modes = {(ex, demo) for ex, demo, _ in result}
    assert modes == {
        ("bitget", False),
        ("bitget", True),  # from paptrading
        ("hyperliquid", True),
        ("weex", False),
    }


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_no_credentials_skipped(mock_create):
    """Connection row with neither live nor demo creds produces nothing."""
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with([_mock_connection("bitget")])  # no creds

    result = await get_all_user_clients(user_id=1, db=db)

    assert result == []
    mock_create.assert_not_called()


@pytest.mark.asyncio
@patch("src.exchanges.factory.create_exchange_client")
async def test_elpresidente_scenario(mock_create):
    """Full regression for the reported #141 scenario.

    User eLPresidente has:
    - Hyperliquid demo connection
    - Bitget live connection (but no bitget demo creds)
    - A bot running on bitget in demo mode

    The factory must produce a bitget demo client that the portfolio
    endpoint can use to query his simulated trading positions.
    """
    mock_create.return_value = MagicMock(name="client")
    db = await _mock_db_with([
        _mock_connection("hyperliquid", has_demo=True, has_passphrase=False),
        _mock_connection("bitget", has_live=True),
    ])

    result = await get_all_user_clients(user_id=11, db=db)

    modes = {(ex, demo) for ex, demo, _ in result}
    # Bitget demo must exist — otherwise the demo trade is invisible.
    assert ("bitget", True) in modes, (
        "Bitget demo client missing — demo bot trades on a live connection "
        "will not appear in the portfolio view."
    )
    assert ("bitget", False) in modes
    assert ("hyperliquid", True) in modes
