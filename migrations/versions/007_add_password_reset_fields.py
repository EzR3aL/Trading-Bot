"""Add password reset fields to users table.

Revision ID: 007
Revises: 006
Create Date: 2026-03-11

Adds reset_token_hash and reset_token_expires columns to support
the password reset flow without an email service.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reset_token_hash", sa.String(255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("reset_token_expires", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "reset_token_expires")
    op.drop_column("users", "reset_token_hash")
