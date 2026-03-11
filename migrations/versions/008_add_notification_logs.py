"""Add notification_logs table for tracking notification delivery.

Revision ID: 008
Revises: 007
Create Date: 2026-03-11

Tracks all notification delivery attempts (Discord, Telegram, WhatsApp)
with status, error messages, and payload summaries for debugging.
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
        "notification_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("bot_config_id", sa.Integer(), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="sent"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("payload_summary", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_logs_user_id", "notification_logs", ["user_id"])
    op.create_index("ix_notif_user_created", "notification_logs", ["user_id", "created_at"])
    op.create_index("ix_notif_channel_status", "notification_logs", ["channel", "status"])
    op.create_index("ix_notification_logs_created_at", "notification_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("notification_logs")
