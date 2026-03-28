"""Add supabase_user_id and auth_provider columns to users table.

Revision ID: 012
Revises: 011
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("supabase_user_id", sa.String(36), nullable=True, unique=True)
        )
        batch_op.add_column(
            sa.Column(
                "auth_provider",
                sa.String(20),
                nullable=False,
                server_default="local",
            )
        )
        batch_op.create_index(
            "ix_users_supabase_user_id", ["supabase_user_id"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_supabase_user_id")
        batch_op.drop_column("auth_provider")
        batch_op.drop_column("supabase_user_id")
