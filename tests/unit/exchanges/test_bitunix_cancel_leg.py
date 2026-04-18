"""Tests for Bitunix leg-specific cancel: ``cancel_tp_only`` and ``cancel_sl_only``.

Epic #188 follow-up to #192: clearing one leg via the dashboard must not
collateral-cancel the other. On Bitunix, however, a single pending TP/SL
order row carries BOTH ``tpPrice`` and ``slPrice``, and
``/tpsl/cancel_order`` takes only ``orderId`` (no leg selector). Partial
modify semantics are undocumented, so cancelling one leg while preserving
the other cannot be expressed safely via the public API.

The client therefore raises ``NotImplementedError`` from both methods —
RiskStateManager surfaces this as ``CancelFailed`` and marks the leg as
``cancel_failed`` in the DB, which is the intended safe fallback.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.exchanges.bitunix.client import BitunixClient


@pytest.fixture
def client():
    return BitunixClient(api_key="test", api_secret="test", demo_mode=True)


@pytest.mark.asyncio
async def test_cancel_tp_only_raises_not_implemented_with_explanation(client):
    """cancel_tp_only must raise NotImplementedError, not silently cancel both.

    The error message must explain *why* — the combined-order limitation —
    so operators reading the UI error know it's a Bitunix API constraint,
    not a transient failure to retry.
    """
    with pytest.raises(NotImplementedError) as exc_info:
        await client.cancel_tp_only("BTCUSDT", side="long")

    message = str(exc_info.value)
    assert "Bitunix" in message
    assert "combined" in message.lower() or "single" in message.lower()


@pytest.mark.asyncio
async def test_cancel_sl_only_raises_not_implemented_with_explanation(client):
    """cancel_sl_only must raise NotImplementedError symmetrically."""
    with pytest.raises(NotImplementedError) as exc_info:
        await client.cancel_sl_only("BTCUSDT", side="long")

    message = str(exc_info.value)
    assert "Bitunix" in message
    assert "combined" in message.lower() or "single" in message.lower()
