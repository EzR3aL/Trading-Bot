"""Add session_version to user_sessions for optimistic refresh-token rotation (#256).

Rollback: drops the session_version column. Safe as long as no in-flight refresh
rotations rely on the column — deploy order is: migrate forward first, then
deploy application code that writes the column.

Revision ID: 025
Revises: 024
Create Date: 2026-04-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "session_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user_sessions") as batch_op:
        batch_op.drop_column("session_version")
