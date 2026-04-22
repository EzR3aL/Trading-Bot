"""Trade CRUD, filters, pagination, export service (ARCH-C1 scaffolding)."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import User


class TradesService:
    """Trade CRUD, filters, pagination, export. Populated in PR-3/PR-4 of ARCH-C1."""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
