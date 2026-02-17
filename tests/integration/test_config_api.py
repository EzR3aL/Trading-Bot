"""
Integration tests for the user configuration API.

Covers:
    - Auth requirement on config endpoints
    - Fetching config (GET /api/config)
    - Updating trading config (PUT /api/config/trading)
    - Validation enforcement (e.g. leverage limits)

Endpoints under test:
    GET  /api/config/
    PUT  /api/config/trading
"""

import pytest

from tests.integration.conftest import auth_header

# A valid trading config payload that satisfies all schema constraints.
VALID_TRADING_CONFIG = {
    "leverage": 4,
    "position_size_percent": 7.5,
    "max_trades_per_day": 3,
    "take_profit_percent": 4.0,
    "stop_loss_percent": 1.5,
    "daily_loss_limit_percent": 5.0,
    "trading_pairs": ["BTCUSDT"],
    "demo_mode": True,
}


# ---------------------------------------------------------------------------
# Auth requirement
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_config_requires_auth(client, test_db):
    """GET /api/config/ without a token returns 401."""
    response = await client.get("/api/config")
    assert response.status_code in (401, 403, 307)


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_config_authenticated(client, user_token):
    """Authenticated user can fetch their configuration."""
    assert user_token is not None

    response = await client.get(
        "/api/config",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200

    body = response.json()
    # On first access the config is auto-created with defaults
    assert "exchange_type" in body
    assert body["api_keys_configured"] is False
    assert body["demo_api_keys_configured"] is False


@pytest.mark.integration
async def test_get_config_returns_updated_values(client, user_token):
    """After updating trading config, GET /api/config reflects the changes."""
    assert user_token is not None
    headers = auth_header(user_token)

    # Update trading config first
    put_resp = await client.put(
        "/api/config/trading",
        headers=headers,
        json=VALID_TRADING_CONFIG,
    )
    assert put_resp.status_code == 200

    # Now fetch and verify
    get_resp = await client.get("/api/config", headers=headers)
    assert get_resp.status_code == 200

    trading = get_resp.json().get("trading")
    assert trading is not None
    assert trading["leverage"] == 4
    assert trading["position_size_percent"] == 7.5
    assert trading["demo_mode"] is True


# ---------------------------------------------------------------------------
# PUT /api/config/trading
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_trading_config(client, user_token):
    """Authenticated user can update their trading config."""
    assert user_token is not None

    response = await client.put(
        "/api/config/trading",
        headers=auth_header(user_token),
        json=VALID_TRADING_CONFIG,
    )
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert "updated" in body["message"].lower()


@pytest.mark.integration
async def test_update_trading_config_requires_auth(client, test_db):
    """PUT /api/config/trading without a token returns 401."""
    response = await client.put(
        "/api/config/trading",
        json=VALID_TRADING_CONFIG,
    )
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_trading_config_leverage_too_high(client, user_token):
    """Leverage > 20 should be rejected by schema validation (422)."""
    assert user_token is not None

    bad_config = {**VALID_TRADING_CONFIG, "leverage": 50}
    response = await client.put(
        "/api/config/trading",
        headers=auth_header(user_token),
        json=bad_config,
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_update_trading_config_leverage_zero(client, user_token):
    """Leverage < 1 should be rejected by schema validation (422)."""
    assert user_token is not None

    bad_config = {**VALID_TRADING_CONFIG, "leverage": 0}
    response = await client.put(
        "/api/config/trading",
        headers=auth_header(user_token),
        json=bad_config,
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_update_trading_config_position_size_too_high(client, user_token):
    """position_size_percent > 25 should be rejected (422)."""
    assert user_token is not None

    bad_config = {**VALID_TRADING_CONFIG, "position_size_percent": 30.0}
    response = await client.put(
        "/api/config/trading",
        headers=auth_header(user_token),
        json=bad_config,
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_update_trading_config_stop_loss_too_high(client, user_token):
    """stop_loss_percent > 10 should be rejected (422)."""
    assert user_token is not None

    bad_config = {**VALID_TRADING_CONFIG, "stop_loss_percent": 15.0}
    response = await client.put(
        "/api/config/trading",
        headers=auth_header(user_token),
        json=bad_config,
    )
    assert response.status_code == 422
