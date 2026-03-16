"""Remove config_presets table and preset FK columns.

Revision ID: 011
Revises: 010
Create Date: 2026-03-16

The Presets feature has been removed. Bot duplication covers the same
use case without extra complexity.  This migration drops:
  - bot_configs.active_preset_id FK
  - bot_instances.active_preset_id FK
  - config_presets table
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop FK columns first (they reference config_presets)
    with op.batch_alter_table("bot_configs") as batch_op:
        batch_op.drop_constraint(
            "fk_bot_configs_active_preset_id", type_="foreignkey"
        ) if _fk_exists("bot_configs", "fk_bot_configs_active_preset_id") else None
        batch_op.drop_column("active_preset_id")

    with op.batch_alter_table("bot_instances") as batch_op:
        batch_op.drop_constraint(
            "fk_bot_instances_active_preset_id", type_="foreignkey"
        ) if _fk_exists("bot_instances", "fk_bot_instances_active_preset_id") else None
        batch_op.drop_column("active_preset_id")

    op.drop_table("config_presets")


def downgrade() -> None:
    # Recreate config_presets table
    op.create_table(
        "config_presets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("exchange_type", sa.String(50), nullable=False, server_default="any"),
        sa.Column("is_active", sa.Boolean, default=False),
        sa.Column("trading_config", sa.Text, nullable=True),
        sa.Column("strategy_config", sa.Text, nullable=True),
        sa.Column("trading_pairs", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # Recreate FK columns
    with op.batch_alter_table("bot_configs") as batch_op:
        batch_op.add_column(
            sa.Column("active_preset_id", sa.Integer, sa.ForeignKey("config_presets.id", ondelete="SET NULL"), nullable=True)
        )

    with op.batch_alter_table("bot_instances") as batch_op:
        batch_op.add_column(
            sa.Column("active_preset_id", sa.Integer, sa.ForeignKey("config_presets.id", ondelete="SET NULL"), nullable=True)
        )


def _fk_exists(table_name: str, constraint_name: str) -> bool:
    """Check if a foreign key constraint exists (SQLite-safe)."""
    from alembic import context
    if context.get_context().dialect.name == "sqlite":
        return True  # SQLite batch mode handles this automatically
    try:
        from sqlalchemy import inspect as sa_inspect
        bind = op.get_bind()
        inspector = sa_inspect(bind)
        fks = inspector.get_foreign_keys(table_name)
        return any(fk.get("name") == constraint_name for fk in fks)
    except Exception:
        return True  # Assume it exists to attempt drop
