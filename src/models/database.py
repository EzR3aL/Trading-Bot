"""
SQLAlchemy ORM Models for the Trading Bot.

Defines all database tables: users, user_configs, config_presets,
trades, funding_payments, bot_instances, exchanges.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # admin | user
    is_active = Column(Boolean, default=True)
    language = Column(String(10), default="de")  # de | en
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    configs = relationship("UserConfig", back_populates="user", cascade="all, delete-orphan")
    presets = relationship("ConfigPreset", back_populates="user", cascade="all, delete-orphan")
    trades = relationship("TradeRecord", back_populates="user", cascade="all, delete-orphan")
    funding_payments = relationship("FundingPayment", back_populates="user", cascade="all, delete-orphan")
    bot_instances = relationship("BotInstance", back_populates="user", cascade="all, delete-orphan")
    exchange_connections = relationship("ExchangeConnection", back_populates="user", cascade="all, delete-orphan")
    bot_configs = relationship("BotConfig", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")


class UserConfig(Base):
    __tablename__ = "user_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange_type = Column(String(50), nullable=False, default="bitget")  # bitget | weex | hyperliquid

    # Encrypted API credentials
    api_key_encrypted = Column(Text, nullable=True)
    api_secret_encrypted = Column(Text, nullable=True)
    passphrase_encrypted = Column(Text, nullable=True)

    # Demo API credentials (encrypted)
    demo_api_key_encrypted = Column(Text, nullable=True)
    demo_api_secret_encrypted = Column(Text, nullable=True)
    demo_passphrase_encrypted = Column(Text, nullable=True)

    # Trading config (JSON stored as text)
    trading_config = Column(Text, nullable=True)  # JSON: max_trades, leverage, position_size, etc.

    # Strategy config (JSON stored as text)
    strategy_config = Column(Text, nullable=True)  # JSON: fear_greed thresholds, funding rate, etc.

    # Discord config
    discord_webhook_url = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="configs")


class ConfigPreset(Base):
    __tablename__ = "config_presets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    exchange_type = Column(String(50), nullable=False)  # bitget | weex | hyperliquid
    is_active = Column(Boolean, default=False)

    # Trading Config (JSON stored as text)
    trading_config = Column(Text, nullable=True)  # JSON: {max_trades, leverage, position_size, ...}

    # Strategy Config (JSON stored as text)
    strategy_config = Column(Text, nullable=True)  # JSON: {fear_greed_thresholds, funding_rate, ...}

    # Trading Pairs (JSON stored as text)
    trading_pairs = Column(Text, nullable=True)  # JSON: ["BTCUSDT", "ETHUSDT"]

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="presets")
    bot_instances = relationship("BotInstance", back_populates="active_preset")


class TradeRecord(Base):
    __tablename__ = "trade_records"
    __table_args__ = (
        Index("ix_trade_user_status", "user_id", "status"),
        Index("ix_trade_user_symbol_side", "user_id", "symbol", "side"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bot_config_id = Column(Integer, ForeignKey("bot_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    exchange = Column(String(50), nullable=False, default="bitget")

    symbol = Column(String(50), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # long | short
    size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    leverage = Column(Integer, nullable=False)
    confidence = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    order_id = Column(String(100), nullable=False)
    close_order_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="open", index=True)  # open | closed | cancelled
    pnl = Column(Float, nullable=True)
    pnl_percent = Column(Float, nullable=True)
    fees = Column(Float, default=0)
    funding_paid = Column(Float, default=0)
    entry_time = Column(DateTime, nullable=False, index=True)
    exit_time = Column(DateTime, nullable=True)
    exit_reason = Column(String(50), nullable=True)
    metrics_snapshot = Column(Text, nullable=True)  # JSON string
    demo_mode = Column(Boolean, default=False, nullable=False, server_default="0")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="trades")
    bot_config = relationship("BotConfig", back_populates="trades", foreign_keys=[bot_config_id])
    funding_payments_rel = relationship("FundingPayment", back_populates="trade")


class FundingPayment(Base):
    __tablename__ = "funding_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trade_id = Column(Integer, ForeignKey("trade_records.id", ondelete="SET NULL"), nullable=True)

    symbol = Column(String(50), nullable=False)
    funding_rate = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)
    position_value = Column(Float, nullable=False)
    payment_amount = Column(Float, nullable=False)
    side = Column(String(10), nullable=True)  # long | short
    timestamp = Column(DateTime, nullable=False)

    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="funding_payments")
    trade = relationship("TradeRecord", back_populates="funding_payments_rel")


class BotInstance(Base):
    __tablename__ = "bot_instances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bot_config_id = Column(Integer, ForeignKey("bot_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    exchange_type = Column(String(50), nullable=False, default="bitget")
    is_running = Column(Boolean, default=False)
    demo_mode = Column(Boolean, default=True)
    active_preset_id = Column(Integer, ForeignKey("config_presets.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="bot_instances")
    active_preset = relationship("ConfigPreset", back_populates="bot_instances")


class ExchangeConnection(Base):
    """Per-exchange API credentials for a user."""
    __tablename__ = "exchange_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "exchange_type", name="uq_user_exchange"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange_type = Column(String(50), nullable=False)  # bitget | weex | hyperliquid

    # Encrypted API credentials (live)
    api_key_encrypted = Column(Text, nullable=True)
    api_secret_encrypted = Column(Text, nullable=True)
    passphrase_encrypted = Column(Text, nullable=True)

    # Encrypted API credentials (demo)
    demo_api_key_encrypted = Column(Text, nullable=True)
    demo_api_secret_encrypted = Column(Text, nullable=True)
    demo_passphrase_encrypted = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="exchange_connections")


class BotConfig(Base):
    """Blueprint for a user-created bot."""
    __tablename__ = "bot_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Strategy
    strategy_type = Column(String(50), nullable=False)  # e.g. "liquidation_hunter"

    # Exchange & mode
    exchange_type = Column(String(50), nullable=False)  # bitget | weex | hyperliquid
    mode = Column(String(10), nullable=False, default="demo")  # demo | live | both

    # Trading parameters
    trading_pairs = Column(Text, nullable=False, default='["BTCUSDT"]')  # JSON array
    leverage = Column(Integer, nullable=False, default=4)
    position_size_percent = Column(Float, nullable=False, default=7.5)
    max_trades_per_day = Column(Integer, nullable=False, default=2)
    take_profit_percent = Column(Float, nullable=False, default=4.0)
    stop_loss_percent = Column(Float, nullable=False, default=1.5)
    daily_loss_limit_percent = Column(Float, nullable=False, default=5.0)

    # Strategy-specific parameters (JSON)
    strategy_params = Column(Text, nullable=True)  # JSON: strategy-specific thresholds

    # Schedule
    schedule_type = Column(String(20), nullable=False, default="market_sessions")  # market_sessions | interval | custom_cron
    schedule_config = Column(Text, nullable=True)  # JSON: {"hours": [1,8,14,21]} or {"interval_minutes": 60}

    # State
    is_enabled = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="bot_configs")
    trades = relationship("TradeRecord", back_populates="bot_config", foreign_keys="TradeRecord.bot_config_id")


class Conversation(Base):
    """Chat conversation between user and AI assistant."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan",
                            order_by="Message.created_at")


class Message(Base):
    """Individual message in a conversation."""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    tool_calls = Column(Text, nullable=True)  # JSON
    tool_results = Column(Text, nullable=True)  # JSON
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    model_used = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")


class Exchange(Base):
    __tablename__ = "exchanges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, default=True)
    supports_demo = Column(Boolean, default=False)
    config_schema = Column(Text, nullable=True)  # JSON schema for exchange-specific config

    created_at = Column(DateTime, server_default=func.now())
