"""Add pending_trades table for crash recovery visibility.

Revision ID: 008
Revises: 007
Create Date: 2026-03-11

Tracks in-flight trades so that if the bot crashes mid-order,
orphaned records are visible to the user for manual resolution.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bot_config_id", sa.Integer(), sa.ForeignKey("bot_configs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("order_data", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pending_bot_status", "pending_trades", ["bot_config_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_pending_bot_status", table_name="pending_trades")
    op.drop_table("pending_trades")
