"""Add index on exit_time for trade_records.

PNL charts now group by exit_time instead of entry_time.
Index ensures performant queries as trade volume grows.

Revision ID: 014
Revises: 013
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_trade_exit_time", "trade_records", ["exit_time"])


def downgrade() -> None:
    op.drop_index("ix_trade_exit_time", table_name="trade_records")
