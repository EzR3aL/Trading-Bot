"""Portfolio aggregation service (ARCH-C1 scaffolding)."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.database import User


class PortfolioService:
    """Position aggregation, PnL, exposure. Populated in PR-5 of ARCH-C1."""

    def __init__(self, db: AsyncSession, user: User) -> None:
        self.db = db
        self.user = user
