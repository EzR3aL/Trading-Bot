"""Widen revenue_entries.source to VARCHAR(32) for provenance labels.

Audit finding: RevenueEntry rows need a richer ``source`` column so the
revenue dashboard can distinguish provenance labels like
``fee_auto``, ``referral_bonus``, ``affiliate_import``, ``manual``.
Migration 020 created ``source VARCHAR(20) NOT NULL DEFAULT 'manual'``
which is too narrow for some of the new labels.

This migration widens the column to VARCHAR(32) while preserving the
NOT NULL constraint and the ``'manual'`` default. No data is lost — a
wider VARCHAR is a compatible change.

``batch_alter_table`` is used so the migration works on SQLite
(test environment) where ``ALTER COLUMN TYPE`` is not supported
directly.

Revision ID: 026
Revises: 025
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen revenue_entries.source from VARCHAR(20) to VARCHAR(32)."""
    with op.batch_alter_table("revenue_entries") as batch_op:
        batch_op.alter_column(
            "source",
            existing_type=sa.String(20),
            type_=sa.String(32),
            existing_nullable=False,
            existing_server_default="manual",
        )


def downgrade() -> None:
    """Narrow revenue_entries.source back to VARCHAR(20).

    Any rows whose ``source`` is longer than 20 chars would be
    truncated by Postgres; the downgrade therefore first clamps any
    oversize values back to ``'manual'`` as a safety net.
    """
    op.execute(
        "UPDATE revenue_entries SET source = 'manual' "
        "WHERE length(source) > 20"
    )
    with op.batch_alter_table("revenue_entries") as batch_op:
        batch_op.alter_column(
            "source",
            existing_type=sa.String(32),
            type_=sa.String(20),
            existing_nullable=False,
            existing_server_default="manual",
        )
