"""Add risk state fields to trade_records (#189, Epic #188).

Adds columns required by the upcoming 2-Phase-Commit Risk-State-Manager:

* Per-leg order IDs (TP / SL / Trailing) so the bot can reconcile
  exchange-side orders with its own intent.
* Trailing stop parameters that are decided at order placement time and
  must persist across restarts.
* ``risk_source`` enum-like column (CHECK constraint enforced) that
  records who owns the risk decision for the position. Default
  ``'unknown'`` keeps existing rows compatible.
* ``*_intent`` / ``*_status`` columns per leg for 2-phase-commit
  bookkeeping (intent recorded before the API call, status updated
  once the exchange confirms or rejects).
* ``last_synced_at`` for the reconciler.
* ``ix_trade_records_status_synced`` index for the reconciler query
  pattern ``WHERE status = ? ORDER BY last_synced_at``.

All new columns are nullable except ``risk_source`` (NOT NULL with
default ``'unknown'``) so existing code that does not yet know about
these fields keeps working.

Revision ID: 024
Revises: 023
Create Date: 2026-04-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Allowed values for the risk_source enum-like column.
RISK_SOURCE_VALUES = (
    "native_exchange",
    "software_bot",
    "manual_user",
    "unknown",
)
RISK_SOURCE_CHECK_NAME = "ck_trade_records_risk_source"


def upgrade() -> None:
    """Add the risk-state columns plus the reconciler index.

    ``batch_alter_table`` is used so the migration also works on SQLite
    (test environment), where ``ALTER TABLE ... ADD COLUMN`` cannot
    attach a CHECK constraint directly.
    """
    risk_source_check = (
        "risk_source IN ('"
        + "', '".join(RISK_SOURCE_VALUES)
        + "')"
    )

    with op.batch_alter_table("trade_records") as batch_op:
        # Per-leg native exchange order IDs.
        batch_op.add_column(sa.Column("tp_order_id", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("sl_order_id", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("trailing_order_id", sa.String(100), nullable=True))

        # Trailing-stop parameters captured at placement time.
        batch_op.add_column(sa.Column("trailing_callback_rate", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("trailing_activation_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("trailing_trigger_price", sa.Float(), nullable=True))

        # Source-of-truth marker for the risk decision (NOT NULL with default).
        batch_op.add_column(
            sa.Column(
                "risk_source",
                sa.String(20),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.create_check_constraint(RISK_SOURCE_CHECK_NAME, risk_source_check)

        # 2-Phase-Commit intent / status per leg.
        batch_op.add_column(sa.Column("tp_intent", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("tp_status", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("sl_intent", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("sl_status", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("trailing_intent_callback", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("trailing_status", sa.String(20), nullable=True))

        # Reconciler timestamp.
        batch_op.add_column(
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True)
        )

    # Index for the reconciler query pattern.
    op.create_index(
        "ix_trade_records_status_synced",
        "trade_records",
        ["status", "last_synced_at"],
    )


def downgrade() -> None:
    """Drop the index, CHECK constraint and columns in reverse order."""
    op.drop_index("ix_trade_records_status_synced", table_name="trade_records")

    with op.batch_alter_table("trade_records") as batch_op:
        batch_op.drop_column("last_synced_at")
        batch_op.drop_column("trailing_status")
        batch_op.drop_column("trailing_intent_callback")
        batch_op.drop_column("sl_status")
        batch_op.drop_column("sl_intent")
        batch_op.drop_column("tp_status")
        batch_op.drop_column("tp_intent")
        batch_op.drop_constraint(RISK_SOURCE_CHECK_NAME, type_="check")
        batch_op.drop_column("risk_source")
        batch_op.drop_column("trailing_trigger_price")
        batch_op.drop_column("trailing_activation_price")
        batch_op.drop_column("trailing_callback_rate")
        batch_op.drop_column("trailing_order_id")
        batch_op.drop_column("sl_order_id")
        batch_op.drop_column("tp_order_id")
