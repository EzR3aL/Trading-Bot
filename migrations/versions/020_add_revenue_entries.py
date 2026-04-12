"""Add revenue_entries table.

Revision ID: 020
Revises: 019
Create Date: 2026-04-12

Revenue tracking: builder fees, affiliate commissions, and referral
income per exchange per day. Supports both manual and automated entry
with a unique constraint on (date, exchange, revenue_type).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revenue_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("exchange", sa.String(50), nullable=False),
        sa.Column("revenue_type", sa.String(50), nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "exchange", "revenue_type", name="uq_revenue_date_exchange_type"),
    )
    op.create_index("ix_revenue_entries_date", "revenue_entries", ["date"])
    op.create_index("ix_revenue_entries_exchange", "revenue_entries", ["exchange"])


def downgrade() -> None:
    op.drop_table("revenue_entries")
