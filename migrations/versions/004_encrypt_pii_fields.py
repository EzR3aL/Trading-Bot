"""Encrypt PII fields: telegram_chat_id and whatsapp_recipient.

Revision ID: 004
Revises: 003
Create Date: 2026-03-09

Changes column types from String to Text (to hold encrypted ciphertext)
and encrypts existing plaintext values in-place. Idempotent: skips values
that already have the 'v1:' encryption prefix.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen columns to hold encrypted ciphertext
    with op.batch_alter_table("bot_configs") as batch_op:
        batch_op.alter_column(
            "telegram_chat_id",
            existing_type=sa.String(50),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "whatsapp_recipient",
            existing_type=sa.String(20),
            type_=sa.Text(),
            existing_nullable=True,
        )

    # Encrypt existing plaintext values
    from src.utils.encryption import encrypt_value

    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, telegram_chat_id, whatsapp_recipient FROM bot_configs")
    ).fetchall()

    for row in rows:
        bot_id, chat_id, recipient = row
        updates = {}
        if chat_id and not chat_id.startswith("v1:"):
            updates["telegram_chat_id"] = encrypt_value(chat_id)
        if recipient and not recipient.startswith("v1:"):
            updates["whatsapp_recipient"] = encrypt_value(recipient)
        if updates:
            set_clause = ", ".join(f"{k} = :val_{k}" for k in updates)
            params = {f"val_{k}": v for k, v in updates.items()}
            params["id"] = bot_id
            conn.execute(text(f"UPDATE bot_configs SET {set_clause} WHERE id = :id"), params)


def downgrade() -> None:
    # Decrypt values back to plaintext
    from src.utils.encryption import decrypt_value

    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, telegram_chat_id, whatsapp_recipient FROM bot_configs")
    ).fetchall()

    for row in rows:
        bot_id, chat_id, recipient = row
        updates = {}
        if chat_id and chat_id.startswith("v1:"):
            updates["telegram_chat_id"] = decrypt_value(chat_id)
        if recipient and recipient.startswith("v1:"):
            updates["whatsapp_recipient"] = decrypt_value(recipient)
        if updates:
            set_clause = ", ".join(f"{k} = :val_{k}" for k in updates)
            params = {f"val_{k}": v for k, v in updates.items()}
            params["id"] = bot_id
            conn.execute(text(f"UPDATE bot_configs SET {set_clause} WHERE id = :id"), params)

    # Narrow columns back
    with op.batch_alter_table("bot_configs") as batch_op:
        batch_op.alter_column(
            "telegram_chat_id",
            existing_type=sa.Text(),
            type_=sa.String(50),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "whatsapp_recipient",
            existing_type=sa.Text(),
            type_=sa.String(20),
            existing_nullable=True,
        )
