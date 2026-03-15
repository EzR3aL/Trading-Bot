"""
Unit tests for the smaller API routers: affiliate, funding, and exchanges.

Each router is relatively small, so they are grouped into one test file
for convenience, with clear section headers.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-testing-only-not-for-production")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS1mb3ItdGVzdGluZw==")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import AffiliateLink, Base, FundingPayment, User
from src.auth.password import hash_password
from src.auth.jwt_handler import create_access_token
from src.errors import ERR_INVALID_EXCHANGE


# ===========================================================================
# Shared fixtures
# ===========================================================================


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
async def admin_user(session_factory):
    async with session_factory() as session:
        u = User(
            username="admin",
            email="admin@test.com",
            password_hash=hash_password("adminpass123"),
            role="admin",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def regular_user(session_factory):
    async with session_factory() as session:
        u = User(
            username="regular",
            email="regular@test.com",
            password_hash=hash_password("userpass123"),
            role="user",
            is_active=True,
            language="en",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return u


@pytest_asyncio.fixture
async def admin_headers(admin_user):
    token_data = {"sub": str(admin_user.id), "role": admin_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def user_headers(regular_user):
    token_data = {"sub": str(regular_user.id), "role": regular_user.role}
    access_token = create_access_token(token_data)
    return {"Authorization": f"Bearer {access_token}"}


@pytest_asyncio.fixture
async def app(session_factory):
    from fastapi import FastAPI
    from src.api.routers import affiliate, exchanges, funding
    from src.models.session import get_db

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app = FastAPI()
    test_app.include_router(affiliate.router)
    test_app.include_router(funding.router)
    test_app.include_router(exchanges.router)
    test_app.dependency_overrides[get_db] = override_get_db
    yield test_app
    test_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


# ===========================================================================
# AFFILIATE LINK ROUTER
# ===========================================================================


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def affiliate_links(session_factory):
    """Insert sample affiliate links."""
    async with session_factory() as session:
        links = [
            AffiliateLink(
                exchange_type="bitget",
                affiliate_url="https://bitget.com/ref/test",
                label="Bitget referral",
                is_active=True,
                uid_required=True,
            ),
            AffiliateLink(
                exchange_type="weex",
                affiliate_url="https://weex.com/ref/test",
                label="Weex referral",
                is_active=True,
                uid_required=False,
            ),
            AffiliateLink(
                exchange_type="hyperliquid",
                affiliate_url="https://hyperliquid.xyz/ref/test",
                label="HL referral",
                is_active=False,
                uid_required=False,
            ),
        ]
        session.add_all(links)
        await session.commit()
        for link in links:
            await session.refresh(link)
        return links


# ---------------------------------------------------------------------------
# GET /api/affiliate-links
# ---------------------------------------------------------------------------


async def test_list_affiliate_links_returns_active_only(
    client, user_headers, regular_user, affiliate_links
):
    """List affiliate links returns only active links."""
    resp = await client.get("/api/affiliate-links", headers=user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2  # Only bitget and weex are active
    exchanges = [link["exchange_type"] for link in data]
    assert "bitget" in exchanges
    assert "weex" in exchanges
    assert "hyperliquid" not in exchanges


async def test_list_affiliate_links_empty(client, user_headers, regular_user):
    """List affiliate links returns empty list when none exist."""
    resp = await client.get("/api/affiliate-links", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_affiliate_links_requires_auth(client):
    """List affiliate links without auth returns 401."""
    resp = await client.get("/api/affiliate-links")
    assert resp.status_code == 401


async def test_list_affiliate_links_response_fields(
    client, user_headers, regular_user, affiliate_links
):
    """Affiliate link response has expected fields."""
    resp = await client.get("/api/affiliate-links", headers=user_headers)
    data = resp.json()
    link = data[0]
    expected_fields = {"exchange_type", "affiliate_url", "label", "is_active", "uid_required"}
    assert expected_fields.issubset(set(link.keys()))


async def test_list_affiliate_links_regular_user_allowed(
    client, user_headers, regular_user, affiliate_links
):
    """Regular (non-admin) users can list affiliate links."""
    resp = await client.get("/api/affiliate-links", headers=user_headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PUT /api/affiliate-links/{exchange}: create / update
# ---------------------------------------------------------------------------


async def test_upsert_affiliate_link_create(client, admin_headers, admin_user):
    """Admin can create a new affiliate link via PUT (admin only)."""
    resp = await client.put(
        "/api/affiliate-links/bitget",
        headers=admin_headers,
        json={
            "affiliate_url": "https://bitget.com/ref/new",
            "label": "New Bitget link",
            "is_active": True,
            "uid_required": True,
        },
    )
    assert resp.status_code == 200


async def test_upsert_affiliate_link_update(client, admin_headers, admin_user, affiliate_links):
    """Admin can update an existing affiliate link."""
    resp = await client.put(
        "/api/affiliate-links/bitget",
        headers=admin_headers,
        json={
            "affiliate_url": "https://bitget.com/ref/updated",
            "label": "Updated",
            "is_active": False,
            "uid_required": False,
        },
    )
    assert resp.status_code == 200


async def test_upsert_affiliate_link_invalid_exchange(client, admin_headers, admin_user):
    """Invalid exchange name returns 400."""
    resp = await client.put(
        "/api/affiliate-links/kraken",
        headers=admin_headers,
        json={
            "affiliate_url": "https://kraken.com/ref",
            "label": "Kraken",
        },
    )
    assert resp.status_code == 400
    assert ERR_INVALID_EXCHANGE in resp.json()["detail"]


async def test_upsert_affiliate_link_forbidden_for_user(
    client, user_headers, regular_user
):
    """Regular user cannot create/update affiliate links (403)."""
    resp = await client.put(
        "/api/affiliate-links/bitget",
        headers=user_headers,
        json={"affiliate_url": "https://bitget.com/ref/nope"},
    )
    assert resp.status_code == 403


async def test_upsert_affiliate_link_requires_auth(client):
    """Upsert without auth returns 401."""
    resp = await client.put(
        "/api/affiliate-links/bitget",
        json={"affiliate_url": "https://bitget.com/ref/nope"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/affiliate-links/{exchange}
# ---------------------------------------------------------------------------


async def test_delete_affiliate_link_success(client, admin_headers, admin_user, affiliate_links):
    """Admin can delete an affiliate link."""
    resp = await client.delete("/api/affiliate-links/bitget", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["detail"] == "deleted"


async def test_delete_affiliate_link_not_found(client, admin_headers, admin_user):
    """Deleting a non-existent link returns 404."""
    resp = await client.delete("/api/affiliate-links/bitget", headers=admin_headers)
    assert resp.status_code == 404


async def test_delete_affiliate_link_forbidden_for_user(
    client, user_headers, regular_user, affiliate_links
):
    """Regular user cannot delete affiliate links (403)."""
    resp = await client.delete("/api/affiliate-links/bitget", headers=user_headers)
    assert resp.status_code == 403


async def test_delete_affiliate_link_requires_auth(client, affiliate_links):
    """Delete without auth returns 401."""
    resp = await client.delete("/api/affiliate-links/bitget")
    assert resp.status_code == 401


async def test_delete_then_list_excludes(client, admin_headers, admin_user, affiliate_links):
    """After deleting a link, it no longer appears in the list."""
    await client.delete("/api/affiliate-links/bitget", headers=admin_headers)
    resp = await client.get("/api/affiliate-links", headers=admin_headers)
    data = resp.json()
    exchanges = [item["exchange_type"] for item in data]
    assert "bitget" not in exchanges


# ===========================================================================
# FUNDING ROUTER
# ===========================================================================


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def funding_payments(session_factory, regular_user):
    """Insert sample funding payments."""
    now = datetime.now(timezone.utc)
    items = [
        FundingPayment(
            user_id=regular_user.id,
            symbol="BTCUSDT",
            funding_rate=0.0001,
            position_size=0.5,
            position_value=47500.0,
            payment_amount=4.75,
            side="long",
            timestamp=now - timedelta(hours=8),
        ),
        FundingPayment(
            user_id=regular_user.id,
            symbol="BTCUSDT",
            funding_rate=-0.0002,
            position_size=0.5,
            position_value=47500.0,
            payment_amount=-9.50,
            side="long",
            timestamp=now - timedelta(hours=16),
        ),
        FundingPayment(
            user_id=regular_user.id,
            symbol="ETHUSDT",
            funding_rate=0.00015,
            position_size=2.0,
            position_value=7000.0,
            payment_amount=1.05,
            side="short",
            timestamp=now - timedelta(hours=4),
        ),
    ]
    async with session_factory() as session:
        session.add_all(items)
        await session.commit()
        for p in items:
            await session.refresh(p)
    return items


# ---------------------------------------------------------------------------
# GET /api/funding
# ---------------------------------------------------------------------------


async def test_list_funding_payments(client, user_headers, regular_user, funding_payments):
    """List funding payments returns all recent payments."""
    resp = await client.get("/api/funding", headers=user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 3
    assert len(data["payments"]) == 3


async def test_list_funding_payments_filter_by_symbol(
    client, user_headers, regular_user, funding_payments
):
    """Filter funding payments by symbol."""
    resp = await client.get("/api/funding", headers=user_headers, params={"symbol": "ETHUSDT"})
    data = resp.json()
    assert data["total_count"] == 1
    assert data["payments"][0]["symbol"] == "ETHUSDT"


async def test_list_funding_payments_custom_days(
    client, user_headers, regular_user, funding_payments
):
    """Custom days parameter limits results."""
    resp = await client.get("/api/funding", headers=user_headers, params={"days": 1})
    data = resp.json()
    assert data["total_count"] == 3  # All within the last 24h


async def test_list_funding_payments_empty(client, user_headers, regular_user):
    """No funding payments returns empty list."""
    resp = await client.get("/api/funding", headers=user_headers)
    data = resp.json()
    assert data["total_count"] == 0
    assert data["payments"] == []


async def test_list_funding_payments_response_fields(
    client, user_headers, regular_user, funding_payments
):
    """Funding payment has expected response fields."""
    resp = await client.get("/api/funding", headers=user_headers)
    data = resp.json()
    payment = data["payments"][0]
    expected = {"id", "symbol", "funding_rate", "position_size", "payment_amount", "side", "timestamp"}
    assert expected.issubset(set(payment.keys()))


async def test_list_funding_payments_requires_auth(client):
    """Funding endpoint requires auth."""
    resp = await client.get("/api/funding")
    assert resp.status_code == 401


async def test_list_funding_payments_ordered_by_timestamp_desc(
    client, user_headers, regular_user, funding_payments
):
    """Payments are returned newest first."""
    resp = await client.get("/api/funding", headers=user_headers)
    data = resp.json()
    timestamps = [p["timestamp"] for p in data["payments"]]
    assert timestamps == sorted(timestamps, reverse=True)


# ---------------------------------------------------------------------------
# GET /api/funding/summary
# ---------------------------------------------------------------------------


async def test_funding_summary(client, user_headers, regular_user, funding_payments):
    """Funding summary returns aggregated totals."""
    resp = await client.get("/api/funding/summary", headers=user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_days"] == 30
    assert data["total_payments"] == 3
    assert data["total_amount"] == pytest.approx(-3.70, abs=0.01)
    assert data["total_received"] == pytest.approx(5.80, abs=0.01)
    assert data["total_paid"] == pytest.approx(-9.50, abs=0.01)
    assert data["net"] == pytest.approx(-3.70, abs=0.01)


async def test_funding_summary_custom_days(client, user_headers, regular_user, funding_payments):
    """Funding summary with custom days period."""
    resp = await client.get("/api/funding/summary", headers=user_headers, params={"days": 7})
    assert resp.status_code == 200
    data = resp.json()
    assert data["period_days"] == 7


async def test_funding_summary_empty(client, user_headers, regular_user):
    """Funding summary with no payments returns zeroed values."""
    resp = await client.get("/api/funding/summary", headers=user_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_payments"] == 0
    assert data["total_amount"] == 0
    assert data["total_received"] == 0
    assert data["total_paid"] == 0
    assert data["net"] == 0


async def test_funding_summary_requires_auth(client):
    """Funding summary requires auth."""
    resp = await client.get("/api/funding/summary")
    assert resp.status_code == 401


async def test_funding_summary_response_fields(
    client, user_headers, regular_user, funding_payments
):
    """Summary has all expected response fields."""
    resp = await client.get("/api/funding/summary", headers=user_headers)
    data = resp.json()
    expected = {"period_days", "total_payments", "total_amount", "total_received", "total_paid", "net"}
    assert expected.issubset(set(data.keys()))


# ===========================================================================
# EXCHANGES ROUTER
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /api/exchanges
# ---------------------------------------------------------------------------


async def test_list_exchanges(client):
    """List supported exchanges (no auth required)."""
    resp = await client.get("/api/exchanges")
    assert resp.status_code == 200
    data = resp.json()
    assert "exchanges" in data
    assert isinstance(data["exchanges"], list)
    assert len(data["exchanges"]) >= 1


async def test_list_exchanges_includes_bitget(client):
    """Exchange list includes bitget."""
    resp = await client.get("/api/exchanges")
    data = resp.json()
    names = [e["name"] for e in data["exchanges"]]
    assert "bitget" in names


async def test_list_exchanges_includes_weex(client):
    """Exchange list includes weex."""
    resp = await client.get("/api/exchanges")
    data = resp.json()
    names = [e["name"] for e in data["exchanges"]]
    assert "weex" in names


async def test_list_exchanges_includes_hyperliquid(client):
    """Exchange list includes hyperliquid."""
    resp = await client.get("/api/exchanges")
    data = resp.json()
    names = [e["name"] for e in data["exchanges"]]
    assert "hyperliquid" in names


async def test_list_exchanges_response_fields(client):
    """Each exchange has the expected fields."""
    resp = await client.get("/api/exchanges")
    data = resp.json()
    for ex in data["exchanges"]:
        expected_fields = {"name", "display_name", "supports_demo", "auth_type", "requires_passphrase"}
        assert expected_fields.issubset(set(ex.keys()))


async def test_list_exchanges_no_auth_required(client):
    """Exchange listing does not require authentication."""
    resp = await client.get("/api/exchanges")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/exchanges/{exchange_name}/info
# ---------------------------------------------------------------------------


async def test_get_exchange_info_bitget(client):
    """Get details for bitget exchange."""
    resp = await client.get("/api/exchanges/bitget/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "bitget"
    assert data["display_name"] == "Bitget"
    assert data["supports_demo"] is True
    assert data["requires_passphrase"] is True


async def test_get_exchange_info_weex(client):
    """Get details for weex exchange."""
    resp = await client.get("/api/exchanges/weex/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "weex"


async def test_get_exchange_info_hyperliquid(client):
    """Get details for hyperliquid exchange."""
    resp = await client.get("/api/exchanges/hyperliquid/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "hyperliquid"
    assert data["requires_passphrase"] is False


async def test_get_exchange_info_not_found(client):
    """Unknown exchange returns 404."""
    resp = await client.get("/api/exchanges/nonexistent/info")
    assert resp.status_code == 404
    assert "nicht gefunden" in resp.json()["detail"] or "not found" in resp.json()["detail"]


async def test_get_exchange_info_no_auth_required(client):
    """Exchange info does not require authentication."""
    resp = await client.get("/api/exchanges/bitget/info")
    assert resp.status_code == 200
