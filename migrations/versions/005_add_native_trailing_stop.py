"""Add native_trailing_stop column to trade_records.

Revision ID: 003
Revises: 002
Create Date: 2026-03-09

Tracks whether a native trailing stop has been placed on the exchange
for an open position, preventing duplicate placement.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trade_records",
        sa.Column("native_trailing_stop", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("trade_records", "native_trailing_stop")
