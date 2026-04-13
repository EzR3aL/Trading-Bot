"""Add pnl_alert_settings column to bot_configs.

Revision ID: 021
Revises: 020
Create Date: 2026-04-13

Per-bot PnL threshold alert configuration. Stored as JSON with fields:
enabled (bool), mode (dollar|percent), threshold (float), direction (profit|loss|both).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bot_configs", sa.Column("pnl_alert_settings", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_configs", "pnl_alert_settings")
