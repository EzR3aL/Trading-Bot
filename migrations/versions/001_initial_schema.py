"""Initial schema — captures all tables that existed at revision 001.

Revision ID: 001
Revises: None
Create Date: 2026-02-19

For existing databases this migration is stamped (not run).
For fresh databases it creates the 2026-02-19 schema via the frozen
ORM snapshot in ``migrations/_initial_schema_models.py``.

**Do NOT import the live ``src.models.database.Base`` here** — that would
create the fully-evolved current schema on a fresh DB, and every
post-001 migration would then fail at its first ``op.add_column()``
with ``DuplicateColumnError`` (tracked as #350).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the 2026-02-19 schema from the frozen ORM snapshot."""
    bind = op.get_bind()
    from migrations._initial_schema_models import Base  # noqa: F811

    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Drop the 2026-02-19 tables (reverse order respects FK constraints)."""
    bind = op.get_bind()
    from migrations._initial_schema_models import Base

    Base.metadata.drop_all(bind=bind)
