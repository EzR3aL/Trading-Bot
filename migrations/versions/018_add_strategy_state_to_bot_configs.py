"""Add strategy_state JSON column to bot_configs.

Revision ID: 018
Revises: 017
Create Date: 2026-04-08

Adds a free-form JSON column for strategies to persist runtime state
that should NOT be part of user-facing strategy_params (e.g. the copy
trading strategy's last_processed_fill_ms).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column("strategy_state", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bot_configs", "strategy_state")
