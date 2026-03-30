"""Add performance indexes for demo_mode and funding_payments.

Revision ID: 016
Revises: 015
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_trade_user_demo", "trade_records", ["user_id", "demo_mode"])
    op.create_index("ix_funding_user_timestamp", "funding_payments", ["user_id", "timestamp"])
    op.create_index("ix_funding_user_symbol", "funding_payments", ["user_id", "symbol"])


def downgrade() -> None:
    op.drop_index("ix_trade_user_demo", table_name="trade_records")
    op.drop_index("ix_funding_user_timestamp", table_name="funding_payments")
    op.drop_index("ix_funding_user_symbol", table_name="funding_payments")
