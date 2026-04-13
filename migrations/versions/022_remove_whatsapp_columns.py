"""Remove all WhatsApp columns from bot_configs and broadcasts.

Revision ID: 022
Revises: 021
Create Date: 2026-04-13

WhatsApp notification support has been removed. Drops the three
WhatsApp-related columns from bot_configs and message_whatsapp
from broadcasts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("bot_configs", "whatsapp_phone_number_id")
    op.drop_column("bot_configs", "whatsapp_access_token")
    op.drop_column("bot_configs", "whatsapp_recipient")
    op.drop_column("broadcasts", "message_whatsapp")


def downgrade() -> None:
    op.add_column("broadcasts", sa.Column("message_whatsapp", sa.Text(), nullable=True))
    op.add_column("bot_configs", sa.Column("whatsapp_recipient", sa.Text(), nullable=True))
    op.add_column("bot_configs", sa.Column("whatsapp_access_token", sa.Text(), nullable=True))
    op.add_column("bot_configs", sa.Column("whatsapp_phone_number_id", sa.Text(), nullable=True))
