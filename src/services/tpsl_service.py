"""TP/SL/trailing intent dispatch service (ARCH-C1 scaffolding)."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import User


class TpSlService:
    """TP/SL/trailing intent dispatch — thin RSM wrapper. Populated in PR-6 of ARCH-C1."""

    def __init__(self, db: AsyncSession, user: User, risk_state_manager=None) -> None:
        self.db = db
        self.user = user
        self.rsm = risk_state_manager
