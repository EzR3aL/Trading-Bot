"""Add soft-delete columns to bot_configs (ARCH-M3 prep).

Audit finding ARCH-M3: BotConfig currently supports hard-delete only,
which means trade history referencing a deleted bot loses context
(FK is ``ON DELETE SET NULL``). Soft-delete keeps the row for
historical joins and enables an "undo delete" UX.

Adds:

* ``deleted_at TIMESTAMP WITH TIME ZONE NULL`` — NULL means "alive".
* ``deleted_by_user_id INTEGER NULL`` — FK to ``users.id`` with
  ``ON DELETE SET NULL`` so deleting the acting user later does not
  cascade-wipe bot configs.
* Partial index ``ix_bot_configs_alive`` on ``(user_id)
  WHERE deleted_at IS NULL`` — speeds up the common "list alive
  bots for user X" query. Postgres-only (``postgresql_where=``).

This migration only adds columns and an index. It deliberately does
**not** change any existing query — router-level soft-delete is the
ARCH-M3 follow-up, outside this migration's scope.

Revision ID: 027
Revises: 026
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_ALIVE = "ix_bot_configs_alive"
FK_DELETED_BY = "fk_bot_configs_deleted_by_user_id"


def upgrade() -> None:
    """Add deleted_at / deleted_by_user_id columns plus alive partial index."""
    with op.batch_alter_table("bot_configs") as batch_op:
        batch_op.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("deleted_by_user_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            FK_DELETED_BY,
            "users",
            ["deleted_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Partial index on alive rows — Postgres-only. The ``postgresql_where``
    # kwarg is silently ignored on SQLite (test env), which is fine: tests
    # get a regular non-partial index and query semantics are identical.
    op.create_index(
        INDEX_ALIVE,
        "bot_configs",
        ["user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Drop the index, FK and columns in reverse order."""
    op.drop_index(INDEX_ALIVE, table_name="bot_configs")

    with op.batch_alter_table("bot_configs") as batch_op:
        batch_op.drop_constraint(FK_DELETED_BY, type_="foreignkey")
        batch_op.drop_column("deleted_by_user_id")
        batch_op.drop_column("deleted_at")
