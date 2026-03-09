"""Add WhatsApp notification columns to bot_configs.

Revision ID: 003
Revises: 002
Create Date: 2026-03-09

Adds whatsapp_phone_number_id, whatsapp_access_token, and whatsapp_recipient
for WhatsApp Business API notifications via Meta Graph API.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column("whatsapp_phone_number_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "bot_configs",
        sa.Column("whatsapp_access_token", sa.Text(), nullable=True),
    )
    op.add_column(
        "bot_configs",
        sa.Column("whatsapp_recipient", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "whatsapp_recipient")
    op.drop_column("bot_configs", "whatsapp_access_token")
    op.drop_column("bot_configs", "whatsapp_phone_number_id")
