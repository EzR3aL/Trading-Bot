"""
Integration tests for user-level data isolation.

Verifies that one user cannot see, modify, or delete resources
belonging to another user. This is critical for multi-tenant
security in the trading bot.

The tests create two separate users (alice and bob), each with
their own auth tokens, and assert that presets created by one
are invisible to the other.
"""

import pytest
import pytest_asyncio

from tests.integration.conftest import auth_header

# Reusable preset payload
SAMPLE_PRESET = {
    "name": "Alice Private Preset",
    "description": "Belongs to alice only",
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


# ---------------------------------------------------------------------------
# Fixtures for two independent users
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def alice_token(client, test_db):
    """Create user 'alice' and return her auth token."""
    from src.auth.password import hash_password
    from src.models.database import User
    from src.models.session import get_session

    async with get_session() as session:
        user = User(
            username="alice",
            password_hash=hash_password("alicepass123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(user)

    response = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "alicepass123"},
    )
    assert response.status_code == 200, f"Alice login failed: {response.text}"
    return response.json()["access_token"]


@pytest_asyncio.fixture
async def bob_token(client, test_db):
    """Create user 'bob' and return his auth token."""
    from src.auth.password import hash_password
    from src.models.database import User
    from src.models.session import get_session

    async with get_session() as session:
        user = User(
            username="bob",
            password_hash=hash_password("bobpass123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(user)

    response = await client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "bobpass123"},
    )
    assert response.status_code == 200, f"Bob login failed: {response.text}"
    return response.json()["access_token"]


# ---------------------------------------------------------------------------
# Isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_user_cannot_see_other_users_presets(client, alice_token, bob_token):
    """Presets created by alice should not appear in bob's list."""
    # Alice creates a preset
    create_resp = await client.post(
        "/api/presets",
        headers=auth_header(alice_token),
        json=SAMPLE_PRESET,
    )
    assert create_resp.status_code == 201
    alice_preset_id = create_resp.json()["id"]

    # Alice can see it
    alice_list = await client.get(
        "/api/presets",
        headers=auth_header(alice_token),
    )
    assert alice_list.status_code == 200
    assert len(alice_list.json()) >= 1
    alice_ids = [p["id"] for p in alice_list.json()]
    assert alice_preset_id in alice_ids

    # Bob should see an empty list (he has no presets)
    bob_list = await client.get(
        "/api/presets",
        headers=auth_header(bob_token),
    )
    assert bob_list.status_code == 200
    bob_ids = [p["id"] for p in bob_list.json()]
    assert alice_preset_id not in bob_ids


@pytest.mark.integration
async def test_user_cannot_access_other_users_preset_by_id(client, alice_token, bob_token):
    """Bob cannot fetch alice's preset directly by ID."""
    # Alice creates a preset
    create_resp = await client.post(
        "/api/presets",
        headers=auth_header(alice_token),
        json=SAMPLE_PRESET,
    )
    assert create_resp.status_code == 201
    alice_preset_id = create_resp.json()["id"]

    # Bob tries to access it by ID
    bob_resp = await client.get(
        f"/api/presets/{alice_preset_id}",
        headers=auth_header(bob_token),
    )
    assert bob_resp.status_code == 404


@pytest.mark.integration
async def test_user_cannot_update_other_users_preset(client, alice_token, bob_token):
    """Bob cannot update alice's preset."""
    # Alice creates a preset
    create_resp = await client.post(
        "/api/presets",
        headers=auth_header(alice_token),
        json=SAMPLE_PRESET,
    )
    assert create_resp.status_code == 201
    alice_preset_id = create_resp.json()["id"]

    # Bob tries to update it
    bob_resp = await client.put(
        f"/api/presets/{alice_preset_id}",
        headers=auth_header(bob_token),
        json={"name": "Hacked by Bob"},
    )
    assert bob_resp.status_code == 404

    # Verify alice's preset name is unchanged
    alice_resp = await client.get(
        f"/api/presets/{alice_preset_id}",
        headers=auth_header(alice_token),
    )
    assert alice_resp.status_code == 200
    assert alice_resp.json()["name"] == "Alice Private Preset"


@pytest.mark.integration
async def test_user_cannot_delete_other_users_preset(client, alice_token, bob_token):
    """Bob cannot delete alice's preset."""
    # Alice creates a preset
    create_resp = await client.post(
        "/api/presets",
        headers=auth_header(alice_token),
        json=SAMPLE_PRESET,
    )
    assert create_resp.status_code == 201
    alice_preset_id = create_resp.json()["id"]

    # Bob tries to delete it
    bob_resp = await client.delete(
        f"/api/presets/{alice_preset_id}",
        headers=auth_header(bob_token),
    )
    assert bob_resp.status_code == 404

    # Verify alice's preset still exists
    alice_resp = await client.get(
        f"/api/presets/{alice_preset_id}",
        headers=auth_header(alice_token),
    )
    assert alice_resp.status_code == 200


@pytest.mark.integration
async def test_user_cannot_activate_other_users_preset(client, alice_token, bob_token):
    """Bob cannot activate alice's preset."""
    # Alice creates a preset
    create_resp = await client.post(
        "/api/presets",
        headers=auth_header(alice_token),
        json=SAMPLE_PRESET,
    )
    assert create_resp.status_code == 201
    alice_preset_id = create_resp.json()["id"]

    # Bob tries to activate it
    bob_resp = await client.post(
        f"/api/presets/{alice_preset_id}/activate",
        headers=auth_header(bob_token),
    )
    assert bob_resp.status_code == 404


@pytest.mark.integration
async def test_user_cannot_duplicate_other_users_preset(client, alice_token, bob_token):
    """Bob cannot duplicate alice's preset."""
    # Alice creates a preset
    create_resp = await client.post(
        "/api/presets",
        headers=auth_header(alice_token),
        json=SAMPLE_PRESET,
    )
    assert create_resp.status_code == 201
    alice_preset_id = create_resp.json()["id"]

    # Bob tries to duplicate it
    bob_resp = await client.post(
        f"/api/presets/{alice_preset_id}/duplicate",
        headers=auth_header(bob_token),
    )
    assert bob_resp.status_code == 404


@pytest.mark.integration
async def test_each_user_sees_only_own_config(client, alice_token, bob_token):
    """Each user's GET /api/config returns their own config, not the other's."""
    # Alice updates her trading config
    alice_config = {
        "leverage": 10,
        "position_size_percent": 5.0,
        "max_trades_per_day": 2,
        "take_profit_percent": 3.0,
        "stop_loss_percent": 1.0,
        "daily_loss_limit_percent": 4.0,
        "trading_pairs": ["ETHUSDT"],
        "demo_mode": False,
    }
    await client.put(
        "/api/config/trading",
        headers=auth_header(alice_token),
        json=alice_config,
    )

    # Bob's config should still be at defaults (no trading config set)
    bob_resp = await client.get(
        "/api/config",
        headers=auth_header(bob_token),
    )
    assert bob_resp.status_code == 200
    bob_body = bob_resp.json()
    # Bob has not set trading config, so it should be None
    assert bob_body.get("trading") is None

    # Alice's config should reflect her update
    alice_resp = await client.get(
        "/api/config",
        headers=auth_header(alice_token),
    )
    assert alice_resp.status_code == 200
    alice_body = alice_resp.json()
    assert alice_body["trading"] is not None
    assert alice_body["trading"]["leverage"] == 10
