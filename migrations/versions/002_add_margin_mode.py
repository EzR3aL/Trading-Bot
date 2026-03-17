"""Add margin_mode column to bot_configs.

Revision ID: 002
Revises: 001
Create Date: 2026-02-24

Allows users to choose cross or isolated margin per bot.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='bot_configs' AND column_name='margin_mode'"
        )
    )
    if not result.fetchone():
        op.add_column(
            "bot_configs",
            sa.Column("margin_mode", sa.String(10), nullable=False, server_default="cross"),
        )


def downgrade() -> None:
    op.drop_column("bot_configs", "margin_mode")
