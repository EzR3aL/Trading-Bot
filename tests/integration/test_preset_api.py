"""
Integration tests for the config preset CRUD API.

Covers:
    - List presets (empty state)
    - Create, read, update, delete presets
    - Duplicate and activate presets

Endpoints under test:
    GET    /api/presets/
    POST   /api/presets/
    GET    /api/presets/{id}
    PUT    /api/presets/{id}
    DELETE /api/presets/{id}
    POST   /api/presets/{id}/activate
    POST   /api/presets/{id}/duplicate
"""

import pytest

from tests.integration.conftest import auth_header

# Reusable preset payload matching PresetCreate schema
SAMPLE_PRESET = {
    "name": "Test Preset",
    "description": "A test trading preset",
    "exchange_type": "bitget",
    "trading_config": {
        "leverage": 4,
        "position_size_percent": 7.5,
        "max_trades_per_day": 3,
        "take_profit_percent": 4.0,
        "stop_loss_percent": 1.5,
        "daily_loss_limit_percent": 5.0,
        "trading_pairs": ["BTCUSDT"],
        "demo_mode": True,
    },
    "strategy_config": {
        "fear_greed_extreme_fear": 20,
        "fear_greed_extreme_greed": 80,
        "long_short_crowded_longs": 2.5,
        "long_short_crowded_shorts": 0.4,
        "funding_rate_high": 0.0005,
        "funding_rate_low": -0.0002,
        "high_confidence_min": 85,
        "low_confidence_min": 60,
    },
    "trading_pairs": ["BTCUSDT"],
}


async def _create_preset(client, token, payload=None):
    """Helper to create a preset and return the response body."""
    resp = await client.post(
        "/api/presets",
        headers=auth_header(token),
        json=payload or SAMPLE_PRESET,
    )
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_presets_empty(client, user_token):
    """A new user has no presets."""
    assert user_token is not None

    response = await client.get(
        "/api/presets",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
async def test_list_presets_after_create(client, user_token):
    """After creating a preset the list endpoint returns it."""
    assert user_token is not None

    await _create_preset(client, user_token)

    response = await client.get(
        "/api/presets",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200
    presets = response.json()
    assert len(presets) == 1
    assert presets[0]["name"] == "Test Preset"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_preset(client, user_token):
    """Creating a preset returns 201 with the full preset body."""
    assert user_token is not None

    body = await _create_preset(client, user_token)

    assert body["name"] == "Test Preset"
    assert body["exchange_type"] == "bitget"
    assert body["is_active"] is False
    assert body["trading_config"] is not None
    assert body["strategy_config"] is not None
    assert "id" in body


@pytest.mark.integration
async def test_create_preset_requires_auth(client, test_db):
    """POST /api/presets/ without auth returns 401."""
    response = await client.post("/api/presets", json=SAMPLE_PRESET)
    assert response.status_code in (401, 403, 307)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_preset(client, user_token):
    """Fetching a single preset by ID returns the correct data."""
    assert user_token is not None

    created = await _create_preset(client, user_token)
    preset_id = created["id"]

    response = await client.get(
        f"/api/presets/{preset_id}",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200
    assert response.json()["id"] == preset_id
    assert response.json()["name"] == "Test Preset"


@pytest.mark.integration
async def test_get_nonexistent_preset(client, user_token):
    """Fetching a preset that does not exist returns 404."""
    assert user_token is not None

    response = await client.get(
        "/api/presets/99999",
        headers=auth_header(user_token),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_update_preset(client, user_token):
    """Updating a preset changes the returned values."""
    assert user_token is not None

    created = await _create_preset(client, user_token)
    preset_id = created["id"]

    response = await client.put(
        f"/api/presets/{preset_id}",
        headers=auth_header(user_token),
        json={"name": "Updated Preset"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Preset"


@pytest.mark.integration
async def test_update_preset_trading_config(client, user_token):
    """Updating trading_config on a preset persists correctly."""
    assert user_token is not None

    created = await _create_preset(client, user_token)
    preset_id = created["id"]

    new_trading = {
        "leverage": 10,
        "position_size_percent": 5.0,
        "max_trades_per_day": 5,
        "take_profit_percent": 6.0,
        "stop_loss_percent": 2.0,
        "daily_loss_limit_percent": 8.0,
        "trading_pairs": ["ETHUSDT"],
        "demo_mode": False,
    }

    response = await client.put(
        f"/api/presets/{preset_id}",
        headers=auth_header(user_token),
        json={"trading_config": new_trading},
    )
    assert response.status_code == 200
    assert response.json()["trading_config"]["leverage"] == 10


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_preset(client, user_token):
    """Deleting a preset removes it from the list."""
    assert user_token is not None

    created = await _create_preset(client, user_token)
    preset_id = created["id"]

    # Delete
    del_resp = await client.delete(
        f"/api/presets/{preset_id}",
        headers=auth_header(user_token),
    )
    assert del_resp.status_code == 204

    # Verify it is gone
    get_resp = await client.get(
        f"/api/presets/{preset_id}",
        headers=auth_header(user_token),
    )
    assert get_resp.status_code == 404


@pytest.mark.integration
async def test_delete_active_preset_fails(client, user_token):
    """Cannot delete a preset that is currently active."""
    assert user_token is not None

    created = await _create_preset(client, user_token)
    preset_id = created["id"]

    # Activate the preset first
    activate_resp = await client.post(
        f"/api/presets/{preset_id}/activate",
        headers=auth_header(user_token),
    )
    assert activate_resp.status_code == 200

    # Attempt to delete should fail
    del_resp = await client.delete(
        f"/api/presets/{preset_id}",
        headers=auth_header(user_token),
    )
    assert del_resp.status_code == 400
    assert "active" in del_resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_duplicate_preset(client, user_token):
    """Duplicating a preset creates a copy with '(Copy)' suffix."""
    assert user_token is not None

    created = await _create_preset(client, user_token)
    preset_id = created["id"]

    response = await client.post(
        f"/api/presets/{preset_id}/duplicate",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200

    copy = response.json()
    assert copy["name"] == "Test Preset (Copy)"
    assert copy["id"] != preset_id
    assert copy["is_active"] is False
    # Trading config should be identical
    assert copy["trading_config"] == created["trading_config"]


@pytest.mark.integration
async def test_duplicate_nonexistent_preset(client, user_token):
    """Duplicating a preset that does not exist returns 404."""
    assert user_token is not None

    response = await client.post(
        "/api/presets/99999/duplicate",
        headers=auth_header(user_token),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Activate
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_activate_preset(client, user_token):
    """Activating a preset sets is_active=True and deactivates others."""
    assert user_token is not None

    preset_a = await _create_preset(client, user_token, {
        **SAMPLE_PRESET,
        "name": "Preset A",
    })
    preset_b = await _create_preset(client, user_token, {
        **SAMPLE_PRESET,
        "name": "Preset B",
    })

    # Activate A
    resp = await client.post(
        f"/api/presets/{preset_a['id']}/activate",
        headers=auth_header(user_token),
    )
    assert resp.status_code == 200

    # Verify A is active
    a_resp = await client.get(
        f"/api/presets/{preset_a['id']}",
        headers=auth_header(user_token),
    )
    assert a_resp.json()["is_active"] is True

    # Activate B
    resp = await client.post(
        f"/api/presets/{preset_b['id']}/activate",
        headers=auth_header(user_token),
    )
    assert resp.status_code == 200

    # Verify B is active and A is no longer active
    b_resp = await client.get(
        f"/api/presets/{preset_b['id']}",
        headers=auth_header(user_token),
    )
    assert b_resp.json()["is_active"] is True

    a_resp2 = await client.get(
        f"/api/presets/{preset_a['id']}",
        headers=auth_header(user_token),
    )
    assert a_resp2.json()["is_active"] is False


@pytest.mark.integration
async def test_activate_nonexistent_preset(client, user_token):
    """Activating a preset that does not exist returns 404."""
    assert user_token is not None

    response = await client.post(
        "/api/presets/99999/activate",
        headers=auth_header(user_token),
    )
    assert response.status_code == 404
