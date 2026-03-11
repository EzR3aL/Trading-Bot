"""Add TOTP two-factor authentication columns to users.

Revision ID: 006
Revises: 005
Create Date: 2026-03-11

Adds totp_secret (encrypted), totp_enabled, and totp_backup_codes
to the users table for TOTP-based 2FA support.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
