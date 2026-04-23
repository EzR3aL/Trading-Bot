"""User management service (ARCH-C1 Phase 3 PR-2).

FastAPI-free business logic for user-info / user-profile read handlers.
The router stays a thin HTTP adapter: it parses request context, calls
the service, and maps the returned dataclasses / plain dicts onto
Pydantic response models.

Scope is intentionally narrow — only the pure-read handlers that are
safe to pull out of the users / auth routers without touching the
authentication flow. Login, refresh, logout, change-password, and the
Supabase one-time-code bridge stay in the routers because they own
cookie state, rate limiting, and session side effects.

Handlers populated in this PR:
    * ``get_profile(user)``  — transform ``User`` row → profile dict for
      ``GET /api/auth/me``.
    * ``list_users(db)``    — admin-panel listing with batched exchange /
      active-bot / total-trade counts for ``GET /api/users``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import BotConfig, ExchangeConnection, TradeRecord, User


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UserProfileResult:
    """Fields used by ``GET /api/auth/me``'s ``UserProfile`` response.

    Shape mirrors ``src.api.schemas.auth.UserProfile`` 1:1 so the router
    can project with a direct constructor call.
    """

    id: int
    username: str
    email: Optional[str]
    role: str
    language: Optional[str]
    is_active: bool


@dataclass(slots=True)
class AdminUserListItem:
    """One row of the admin-panel user list.

    Matches ``src.api.schemas.user.AdminUserResponse`` field-for-field so
    the router can build the Pydantic response without any extra mapping.
    ``last_login_at`` and ``created_at`` are pre-serialized to ISO-8601
    strings here — the router response model expects strings, and doing
    the isoformat inside the service keeps the adapter trivial.
    """

    id: int
    username: str
    email: Optional[str]
    role: str
    language: str
    is_active: bool
    auth_provider: str
    last_login_at: Optional[str]
    created_at: Optional[str]
    exchanges: list[str]
    active_bots: int
    total_trades: int


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def get_profile(user: User) -> UserProfileResult:
    """Return the profile fields used by ``GET /api/auth/me``.

    Pure transform — no DB access. The caller has already resolved the
    ``User`` row via the ``get_current_user`` dependency.
    """
    return UserProfileResult(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        language=user.language,
        is_active=user.is_active,
    )


async def list_users(db: AsyncSession) -> list[AdminUserListItem]:
    """Return all active (non-soft-deleted) users with support-relevant aggregates.

    Behavior matches the pre-extract ``GET /api/users`` handler exactly:

    * Filters ``is_deleted == False`` and orders by ``id``.
    * Batches three aggregate queries (exchange types, active bot count,
      total trade count) keyed on ``user_id`` to avoid N+1 queries.
    * Returns one ``AdminUserListItem`` per user, with ``exchanges``
      defaulting to ``[]``, ``active_bots`` / ``total_trades`` to ``0``,
      and ``auth_provider`` defaulting to ``"local"`` when ``NULL``.
    """
    result = await db.execute(
        select(User).where(User.is_deleted == False).order_by(User.id)  # noqa: E712
    )
    users = result.scalars().all()
    user_ids = [u.id for u in users]

    if not user_ids:
        return []

    # Batch: distinct exchange types per user
    ex_result = await db.execute(
        select(ExchangeConnection.user_id, ExchangeConnection.exchange_type)
        .where(ExchangeConnection.user_id.in_(user_ids))
        .distinct()
    )
    exchanges_map: dict[int, list[str]] = {}
    for uid, ex_type in ex_result:
        exchanges_map.setdefault(uid, []).append(ex_type)

    # Batch: count of enabled bot configs per user
    bot_result = await db.execute(
        select(BotConfig.user_id, func.count(BotConfig.id))
        .where(BotConfig.user_id.in_(user_ids), BotConfig.is_enabled == True)  # noqa: E712
        .group_by(BotConfig.user_id)
    )
    bots_map = {uid: cnt for uid, cnt in bot_result.all()}

    # Batch: total trade records per user
    trade_result = await db.execute(
        select(TradeRecord.user_id, func.count(TradeRecord.id))
        .where(TradeRecord.user_id.in_(user_ids))
        .group_by(TradeRecord.user_id)
    )
    trades_map = {uid: cnt for uid, cnt in trade_result.all()}

    return [
        AdminUserListItem(
            id=u.id,
            username=u.username,
            email=u.email,
            role=u.role,
            language=u.language,
            is_active=u.is_active,
            auth_provider=u.auth_provider or "local",
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
            created_at=u.created_at.isoformat() if u.created_at else None,
            exchanges=exchanges_map.get(u.id, []),
            active_bots=bots_map.get(u.id, 0),
            total_trades=trades_map.get(u.id, 0),
        )
        for u in users
    ]
