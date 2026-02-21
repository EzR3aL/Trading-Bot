"""Initial schema — captures all existing tables.

Revision ID: 001
Revises: None
Create Date: 2026-02-19

For existing databases this migration is stamped (not run).
For fresh databases it creates the full schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables matching the current ORM models."""
    bind = op.get_bind()
    # Import Base so metadata is populated with all models
    from src.models.database import Base  # noqa: F811

    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Drop all tables (reverse order to respect FK constraints)."""
    bind = op.get_bind()
    from src.models.database import Base

    Base.metadata.drop_all(bind=bind)
