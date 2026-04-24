"""Add partial unique index on (exchange, order_id) to trade_records (ARCH-M7).

Audit finding ARCH-M7: duplicate ``order_id`` values can appear across
different exchanges because the venues reuse similar numeric id schemas.
A unique constraint on ``order_id`` alone would break multi-exchange
setups, so we enforce uniqueness per exchange instead.

Implementation notes:

* ``trade_records.exchange`` already exists (added in migration 001 /
  carried forward), so no backfill is needed.
* Historical rows may have ``order_id`` values that are NULL or empty
  (cancelled / failed placements captured for audit). A plain UNIQUE
  constraint would fail or block legitimate inserts, so we use a
  **PARTIAL unique index** on ``(exchange, order_id) WHERE order_id
  IS NOT NULL AND order_id <> ''`` — this is the Alembic idiom
  (``postgresql_where=``) and only applies to Postgres. On SQLite
  (test harness) the ``postgresql_where`` kwarg is silently ignored
  by Alembic/SQLAlchemy; the test env has a single exchange so the
  predicate is effectively always true there.

Revision ID: 028
Revises: 027
Create Date: 2026-04-21
(Renumbered from 025 to 028 in #346 to resolve a duplicate-025 head
that existed alongside ``025_add_session_version.py``. Neither migration
had been applied to prod at renumbering time — last deploy was commit
``fd77ba9`` on 2026-04-21, which pre-dates both 025 files — so the
renumber is a pure file/metadata change with no prod-DB reconciliation
needed.)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "uq_trade_records_exchange_order_id"


def upgrade() -> None:
    """Create the partial unique index on (exchange, order_id)."""
    op.create_index(
        INDEX_NAME,
        "trade_records",
        ["exchange", "order_id"],
        unique=True,
        postgresql_where=sa.text("order_id IS NOT NULL AND order_id <> ''"),
    )


def downgrade() -> None:
    """Drop the partial unique index."""
    op.drop_index(INDEX_NAME, table_name="trade_records")
