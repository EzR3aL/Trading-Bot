"""Add broadcasts and broadcast_targets tables.

Revision ID: 019
Revises: 018
Create Date: 2026-04-12

Broadcast notification system: admin-created messages delivered to
multiple notification channels (Discord, Telegram, WhatsApp) with
deduplication, scheduling, and per-target delivery tracking.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- broadcasts --
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message_markdown", sa.Text(), nullable=False),
        sa.Column("message_discord", sa.Text(), nullable=True),
        sa.Column("message_telegram", sa.Text(), nullable=True),
        sa.Column("message_whatsapp", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("exchange_filter", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_targets", sa.Integer(), server_default="0"),
        sa.Column("sent_count", sa.Integer(), server_default="0"),
        sa.Column("failed_count", sa.Integer(), server_default="0"),
        sa.Column("scheduler_job_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcasts_admin_user_id", "broadcasts", ["admin_user_id"])

    # -- broadcast_targets --
    op.create_table(
        "broadcast_targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("broadcast_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("dedup_key", sa.String(128), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("bot_config_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broadcast_id"], ["broadcasts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broadcast_id", "dedup_key", name="uq_broadcast_target_dedup"),
    )
    op.create_index("ix_broadcast_targets_broadcast_id", "broadcast_targets", ["broadcast_id"])
    op.create_index("ix_broadcast_targets_status", "broadcast_targets", ["broadcast_id", "status"])
    op.create_index("ix_broadcast_targets_channel", "broadcast_targets", ["broadcast_id", "channel"])


def downgrade() -> None:
    op.drop_table("broadcast_targets")
    op.drop_table("broadcasts")
