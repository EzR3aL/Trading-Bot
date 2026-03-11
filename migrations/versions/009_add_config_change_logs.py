"""Add config_change_logs table for configuration audit trail.

Revision ID: 009
Revises: 008
Create Date: 2026-03-11

Tracks all configuration changes (bot configs, presets, exchange connections,
LLM connections) with before/after diffs for auditing and troubleshooting.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "config_change_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("changes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_config_change_logs_user_id", "config_change_logs", ["user_id"])
    op.create_index("ix_config_change_logs_entity_type", "config_change_logs", ["entity_type"])
    op.create_index("ix_config_change_logs_created_at", "config_change_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("config_change_logs")
