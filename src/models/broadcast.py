"""
SQLAlchemy ORM Models for the Broadcast Notification System.

Defines tables: broadcasts, broadcast_targets.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from src.models.database import Base


class Broadcast(Base):
    """Admin-created broadcast message sent to multiple notification channels."""
    __tablename__ = "broadcasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    message_markdown = Column(Text, nullable=False)  # Source message (Markdown)
    message_discord = Column(Text, nullable=True)  # Pre-rendered Discord embed JSON
    message_telegram = Column(Text, nullable=True)  # Pre-rendered Telegram HTML
    image_url = Column(String(500), nullable=True)  # Optional image URL
    exchange_filter = Column(String(50), nullable=True)  # NULL=all, or "hyperliquid","bitget",etc.
    status = Column(String(20), nullable=False, default="draft")  # draft/scheduled/sending/completed/failed/cancelled
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    total_targets = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    scheduler_job_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    admin = relationship("User")
    targets = relationship("BroadcastTarget", back_populates="broadcast", cascade="all, delete-orphan")


class BroadcastTarget(Base):
    """Individual delivery target for a broadcast message."""
    __tablename__ = "broadcast_targets"
    __table_args__ = (
        Index("ix_broadcast_targets_status", "broadcast_id", "status"),
        Index("ix_broadcast_targets_channel", "broadcast_id", "channel"),
        UniqueConstraint("broadcast_id", "dedup_key", name="uq_broadcast_target_dedup"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    broadcast_id = Column(Integer, ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)  # discord/telegram
    dedup_key = Column(String(128), nullable=False)  # SHA256 hash
    credentials_encrypted = Column(Text, nullable=False)  # JSON blob of encrypted creds
    user_id = Column(Integer, nullable=True)
    bot_config_id = Column(Integer, nullable=True)
    status = Column(String(20), default="pending")  # pending/sending/sent/failed
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    broadcast = relationship("Broadcast", back_populates="targets")
