"""Trade sync pipeline service (ARCH-C1 scaffolding)."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import User


class TradeSyncService:
    """POST /sync pipeline: exchange → DB reconciliation. Populated in PR-7 of ARCH-C1."""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
