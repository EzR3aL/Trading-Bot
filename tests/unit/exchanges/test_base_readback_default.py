"""Tests for the default NotImplementedError behavior of readback methods (#191).

Weex and Bitunix intentionally do NOT implement the readback methods.
RiskStateManager (#190) is expected to skip those exchanges; the base
class raises NotImplementedError so silent omissions surface immediately
instead of returning misleading empty snapshots.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bitunix.client import BitunixClient
from src.exchanges.weex.client import WeexClient


@pytest.fixture
def weex_client():
    return WeexClient(api_key="test", api_secret="test", passphrase="test", demo_mode=True)


@pytest.fixture
def bitunix_client():
    return BitunixClient(api_key="test", api_secret="test", demo_mode=True)


@pytest.mark.asyncio
async def test_weex_get_position_tpsl_raises_not_implemented(weex_client):
    """Weex must inherit the base raise — no silent empty snapshot."""
    with pytest.raises(NotImplementedError, match="get_position_tpsl"):
        await weex_client.get_position_tpsl("BTCUSDT", "long")


@pytest.mark.asyncio
async def test_weex_get_trailing_stop_raises_not_implemented(weex_client):
    with pytest.raises(NotImplementedError, match="get_trailing_stop"):
        await weex_client.get_trailing_stop("BTCUSDT", "long")


@pytest.mark.asyncio
async def test_bitunix_readbacks_raise_not_implemented(bitunix_client):
    """Bitunix also inherits the base raise for all three readback methods."""
    with pytest.raises(NotImplementedError, match="get_position_tpsl"):
        await bitunix_client.get_position_tpsl("BTCUSDT", "long")
    with pytest.raises(NotImplementedError, match="get_trailing_stop"):
        await bitunix_client.get_trailing_stop("BTCUSDT", "long")
    with pytest.raises(NotImplementedError, match="get_close_reason_from_history"):
        await bitunix_client.get_close_reason_from_history("BTCUSDT", 0)
