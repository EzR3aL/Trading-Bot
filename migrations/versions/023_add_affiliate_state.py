"""Add affiliate_state table for tracking cumulative HL referral baseline.

Revision ID: 023
Revises: 022
Create Date: 2026-04-15

The Hyperliquid /info referral endpoint only returns lifetime cumulative
totals. To compute the daily delta we need to remember the previous
cumulative value per exchange.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "affiliate_state",
        sa.Column("exchange", sa.String(50), primary_key=True),
        sa.Column("cumulative_amount_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("affiliate_state")
