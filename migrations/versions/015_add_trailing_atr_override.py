"""Add trailing_atr_override column to trade_records.

Allows users to manually set ATR multiplier for trailing stop
via the edit position panel, overriding the bot strategy default.

Revision ID: 015
Revises: 014
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("trade_records") as batch_op:
        batch_op.add_column(
            sa.Column("trailing_atr_override", sa.Float, nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("trade_records") as batch_op:
        batch_op.drop_column("trailing_atr_override")
