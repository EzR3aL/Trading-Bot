"""Remove TOTP two-factor authentication columns from users.

Revision ID: 017
Revises: 016
Create Date: 2026-04-01

Drops totp_secret, totp_enabled, and totp_backup_codes columns
that were added in migration 006.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("totp_secret", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "users",
        sa.Column("totp_backup_codes", sa.Text(), nullable=True),
    )
