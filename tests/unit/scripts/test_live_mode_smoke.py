"""Unit test for the live-mode smoke probe — mocks the exchange factory."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "live_mode_smoke.py"


@pytest.fixture
def smoke_module():
    spec = importlib.util.spec_from_file_location("live_mode_smoke", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_mode_smoke"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_conn(exchange="bitget", has_keys=True):
    conn = MagicMock()
    conn.exchange_type = exchange
    conn.api_key_encrypted = "enc-key" if has_keys else None
    conn.api_secret_encrypted = "enc-secret" if has_keys else None
    conn.passphrase_encrypted = "enc-pass" if has_keys else None
    return conn


@pytest.mark.asyncio
async def test_returns_no_keys_when_credentials_missing(smoke_module):
    conn = _make_conn(has_keys=False)
    results = await smoke_module._probe_exchange("bitget", conn)
    assert results[0].feature == "live_keys_present"
    assert results[0].ok is False


@pytest.mark.asyncio
async def test_runs_all_probes_when_keys_present(smoke_module):
    conn = _make_conn()
    fake_client = MagicMock()
    fake_client.get_account_balance = AsyncMock(return_value="balance-ok")
    fake_client.get_open_positions = AsyncMock(return_value=[])
    fake_client.get_ticker = AsyncMock(return_value="ticker-ok")
    fake_client.get_funding_rate = AsyncMock(return_value="funding-ok")

    with patch.object(smoke_module, "create_exchange_client", return_value=fake_client), \
         patch.object(smoke_module, "decrypt_value", return_value="dec"):
        results = await smoke_module._probe_exchange("bitget", conn)

    feature_names = [r.feature for r in results]
    assert "get_account_balance" in feature_names
    assert "get_open_positions" in feature_names
    assert "get_ticker" in feature_names
    assert "get_funding_rate" in feature_names
    assert all(r.ok for r in results)


@pytest.mark.asyncio
async def test_marks_failure_when_probe_throws(smoke_module):
    conn = _make_conn()
    fake_client = MagicMock()
    fake_client.get_account_balance = AsyncMock(side_effect=RuntimeError("401 Unauthorized"))
    fake_client.get_open_positions = AsyncMock(return_value=[])
    fake_client.get_ticker = AsyncMock(return_value="ok")
    fake_client.get_funding_rate = AsyncMock(return_value="ok")

    with patch.object(smoke_module, "create_exchange_client", return_value=fake_client), \
         patch.object(smoke_module, "decrypt_value", return_value="dec"):
        results = await smoke_module._probe_exchange("bitget", conn)

    balance_result = next(r for r in results if r.feature == "get_account_balance")
    assert balance_result.ok is False
    assert "401 Unauthorized" in balance_result.detail
