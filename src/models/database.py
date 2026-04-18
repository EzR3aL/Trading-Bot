"""
SQLAlchemy ORM Models for the Trading Bot.

Defines all database tables: users, user_configs,
trades, funding_payments, bot_instances, exchanges.
"""


from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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
    token_version = Column(Integer, default=0, nullable=False, server_default="0")
    language = Column(String(10), default="de")  # de | en
    failed_login_attempts = Column(Integer, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    # Supabase Auth Bridge
    supabase_user_id = Column(String(36), unique=True, nullable=True, index=True)
    auth_provider = Column(String(20), nullable=False, default="local", server_default="local")  # local | supabase
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships — use "all" (not "all, delete-orphan") to prevent cascade
    # deletes from wiping trade history and other important child records.
    # Soft deletes (is_deleted + deleted_at) are used instead.
    configs = relationship("UserConfig", back_populates="user", cascade="all")
    trades = relationship("TradeRecord", back_populates="user", cascade="all")
    funding_payments = relationship("FundingPayment", back_populates="user", cascade="all")
    bot_instances = relationship("BotInstance", back_populates="user", cascade="all")
    exchange_connections = relationship("ExchangeConnection", back_populates="user", cascade="all")
    bot_configs = relationship("BotConfig", back_populates="user", cascade="all")
    notification_logs = relationship("NotificationLog", back_populates="user", cascade="all")
    sessions = relationship("UserSession", back_populates="user", cascade="all")


class UserSession(Base):
    """Tracks active login sessions for a user (device/IP/expiry)."""
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_session_user_active", "user_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token_hash = Column(String(255), nullable=False)
    device_name = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    last_activity = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True, server_default="true")

    # Relationships
    user = relationship("User", back_populates="sessions")


class UserConfig(Base):
    __tablename__ = "user_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange_type = Column(String(50), nullable=False, default="bitget")  # bitget | weex | hyperliquid | bitunix | bingx

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

    # DEPRECATED & CLEARED: moved to per-bot BotConfig.discord_webhook_url (encrypted).
    # Migration nullifies any existing plaintext values. Do NOT write to this column.
    discord_webhook_url = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="configs")


class TradeRecord(Base):
    __tablename__ = "trade_records"
    __table_args__ = (
        Index("ix_trade_user_status", "user_id", "status"),
        Index("ix_trade_user_symbol_side", "user_id", "symbol", "side"),
        Index("ix_trade_bot_status", "bot_config_id", "status"),
        Index("ix_trade_entry_time", "entry_time"),
        Index("ix_trade_exit_time", "exit_time"),
        Index("ix_trade_user_demo", "user_id", "demo_mode"),
        Index("ix_trade_records_status_synced", "status", "last_synced_at"),
        CheckConstraint(
            "risk_source IN ('native_exchange', 'software_bot', 'manual_user', 'unknown')",
            name="ck_trade_records_risk_source",
        ),
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
    take_profit = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
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
    builder_fee = Column(Float, default=0)
    entry_time = Column(DateTime(timezone=True), nullable=False, index=True)
    exit_time = Column(DateTime(timezone=True), nullable=True)
    exit_reason = Column(String(50), nullable=True)
    metrics_snapshot = Column(Text, nullable=True)  # JSON string
    highest_price = Column(Float, nullable=True)  # Trailing stop: highest mark price since entry
    native_trailing_stop = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    trailing_atr_override = Column(Float, nullable=True)  # Manual ATR multiplier override (from edit panel)
    demo_mode = Column(Boolean, default=False, nullable=False, server_default=text("false"))

    # Risk-State fields (#189, Epic #188): per-leg native exchange order IDs
    # tracked so the upcoming risk_state_manager can reconcile what is
    # actually live on the exchange against the bot's intent.
    tp_order_id = Column(String(100), nullable=True)
    sl_order_id = Column(String(100), nullable=True)
    trailing_order_id = Column(String(100), nullable=True)

    # Trailing-stop parameters captured at placement time so they survive
    # restarts without having to re-derive them from the strategy.
    trailing_callback_rate = Column(Float, nullable=True)
    trailing_activation_price = Column(Float, nullable=True)
    trailing_trigger_price = Column(Float, nullable=True)

    # Source-of-truth marker for the risk decision. CHECK constraint above
    # restricts to: native_exchange | software_bot | manual_user | unknown.
    risk_source = Column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )

    # 2-Phase-Commit bookkeeping per leg. ``*_intent`` is the price/value
    # the bot *wants*; ``*_status`` reflects the exchange-side state:
    # pending | confirmed | rejected | cleared | cancel_failed.
    tp_intent = Column(Float, nullable=True)
    tp_status = Column(String(20), nullable=True)
    sl_intent = Column(Float, nullable=True)
    sl_status = Column(String(20), nullable=True)
    trailing_intent_callback = Column(Float, nullable=True)
    trailing_status = Column(String(20), nullable=True)

    # Reconciler timestamp — set by risk_state_manager after a successful
    # exchange-side sync. Indexed via ix_trade_records_status_synced.
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="trades")
    bot_config = relationship("BotConfig", back_populates="trades", foreign_keys=[bot_config_id])
    funding_payments_rel = relationship("FundingPayment", back_populates="trade")


class FundingPayment(Base):
    __tablename__ = "funding_payments"
    __table_args__ = (
        Index("ix_funding_user_timestamp", "user_id", "timestamp"),
        Index("ix_funding_user_symbol", "user_id", "symbol"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trade_id = Column(Integer, ForeignKey("trade_records.id", ondelete="SET NULL"), nullable=True)

    symbol = Column(String(50), nullable=False)
    funding_rate = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)
    position_value = Column(Float, nullable=False)
    payment_amount = Column(Float, nullable=False)
    side = Column(String(10), nullable=True)  # long | short
    timestamp = Column(DateTime(timezone=True), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

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
    started_at = Column(DateTime(timezone=True), nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="bot_instances")


class ExchangeConnection(Base):
    """Per-exchange API credentials for a user."""
    __tablename__ = "exchange_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "exchange_type", name="uq_user_exchange"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange_type = Column(String(50), nullable=False)  # bitget | weex | hyperliquid | bitunix | bingx

    # Encrypted API credentials (live)
    api_key_encrypted = Column(Text, nullable=True)
    api_secret_encrypted = Column(Text, nullable=True)
    passphrase_encrypted = Column(Text, nullable=True)

    # Encrypted API credentials (demo)
    demo_api_key_encrypted = Column(Text, nullable=True)
    demo_api_secret_encrypted = Column(Text, nullable=True)
    demo_passphrase_encrypted = Column(Text, nullable=True)

    # Builder fee approval tracking (Hyperliquid)
    builder_fee_approved = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    builder_fee_approved_at = Column(DateTime(timezone=True), nullable=True)

    # Referral verification tracking (Hyperliquid)
    referral_verified = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    referral_verified_at = Column(DateTime(timezone=True), nullable=True)

    # Affiliate UID verification (Bitget / Weex)
    affiliate_uid = Column(String(100), nullable=True)
    affiliate_verified = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    affiliate_verified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="exchange_connections")


class SystemSetting(Base):
    """Global key-value settings (admin-managed, replaces .env for runtime config)."""
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class BotConfig(Base):
    """Blueprint for a user-created bot.

    Stores strategy, exchange, risk, and schedule settings.
    Data source selection is stored in strategy_params["data_sources"].
    """
    __tablename__ = "bot_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Strategy
    strategy_type = Column(String(50), nullable=False)  # e.g. "liquidation_hunter"

    # Exchange & mode
    exchange_type = Column(String(50), nullable=False)  # bitget | weex | hyperliquid | bitunix | bingx
    mode = Column(String(10), nullable=False, default="demo")  # demo | live | both
    margin_mode = Column(String(10), nullable=False, default="cross")  # cross | isolated

    # Trading parameters (all nullable — None = equal split / no TP/SL)
    trading_pairs = Column(Text, nullable=False, default='["BTCUSDT"]')  # JSON array
    leverage = Column(Integer, nullable=True, default=None)
    position_size_percent = Column(Float, nullable=True, default=None)
    max_trades_per_day = Column(Integer, nullable=True, default=None)
    take_profit_percent = Column(Float, nullable=True, default=None)
    stop_loss_percent = Column(Float, nullable=True, default=None)
    daily_loss_limit_percent = Column(Float, nullable=True, default=None)

    # Per-asset configuration (JSON: per-trading-pair overrides)
    per_asset_config = Column(Text, nullable=True)  # JSON: {"BTCUSDT": {"position_pct": 10, "leverage": 5}}

    # Strategy-specific parameters (JSON)
    strategy_params = Column(Text, nullable=True)  # JSON: strategy-specific thresholds
    strategy_state = Column(Text, nullable=True)  # JSON, runtime state managed by the strategy

    # Schedule
    schedule_type = Column(String(20), nullable=False, default="interval")  # interval | custom_cron
    schedule_config = Column(Text, nullable=True)  # JSON: {"hours": [1,8,14,21]} or {"interval_minutes": 60}

    # Legacy rotation columns (kept for DB compatibility, no longer used)
    rotation_enabled = Column(Boolean, default=False)
    rotation_interval_minutes = Column(Integer, nullable=True)
    rotation_start_time = Column(String(5), nullable=True)

    # Per-bot Discord webhook (encrypted, optional — overrides user-level)
    discord_webhook_url = Column(Text, nullable=True)

    # Per-bot Telegram notifications (optional)
    telegram_bot_token = Column(Text, nullable=True)   # Encrypted
    telegram_chat_id = Column(Text, nullable=True)     # Encrypted

    # PnL alert threshold settings (JSON: enabled, mode, threshold, direction)
    pnl_alert_settings = Column(Text, nullable=True)

    # State
    is_enabled = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="bot_configs")
    trades = relationship("TradeRecord", back_populates="bot_config", foreign_keys="TradeRecord.bot_config_id")


class Exchange(Base):
    __tablename__ = "exchanges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    is_enabled = Column(Boolean, default=True)
    supports_demo = Column(Boolean, default=False)
    config_schema = Column(Text, nullable=True)  # JSON schema for exchange-specific config

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AffiliateLink(Base):
    """Global affiliate links per exchange (admin-managed)."""
    __tablename__ = "affiliate_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exchange_type = Column(String(50), unique=True, nullable=False)  # bitget | weex | hyperliquid | bitunix | bingx
    affiliate_url = Column(Text, nullable=False)
    label = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    uid_required = Column(Boolean, default=False, nullable=False, server_default=text("false"))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class RiskStats(Base):
    """Daily risk stats per bot, replacing JSON file storage."""
    __tablename__ = "risk_stats"
    __table_args__ = (
        Index("idx_risk_stats_bot_date", "bot_config_id", "date", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_config_id = Column(Integer, ForeignKey("bot_configs.id", ondelete="CASCADE"), nullable=False)
    date = Column(String(10), nullable=False)  # YYYY-MM-DD
    stats_json = Column(Text, nullable=False)  # Full DailyStats serialized
    daily_pnl = Column(Float, default=0.0)
    trades_count = Column(Integer, default=0)
    is_halted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AuditLog(Base):
    """Request audit log for security and compliance tracking."""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Float, nullable=False)
    client_ip = Column(String(45), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class PendingTrade(Base):
    """Tracks in-flight trades for crash recovery visibility.

    Before placing an order, a pending record is created. After confirmation
    it is marked completed; on error it is marked failed. If the bot crashes
    mid-trade, the record stays as 'pending' and is later marked 'orphaned'
    on the next startup so the user can inspect and manually resolve it.
    """
    __tablename__ = "pending_trades"
    __table_args__ = (
        Index("ix_pending_bot_status", "bot_config_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_config_id = Column(Integer, ForeignKey("bot_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(50), nullable=False)
    side = Column(String(10), nullable=False)  # LONG | SHORT
    action = Column(String(10), nullable=False)  # open | close
    order_data = Column(Text, nullable=True)  # JSON of order params
    status = Column(String(20), default="pending")  # pending | completed | failed | orphaned
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    bot_config = relationship("BotConfig", foreign_keys=[bot_config_id])
    user = relationship("User", foreign_keys=[user_id])


class NotificationLog(Base):
    """Log of notification delivery attempts across all channels."""
    __tablename__ = "notification_logs"
    __table_args__ = (
        Index("ix_notif_user_created", "user_id", "created_at"),
        Index("ix_notif_channel_status", "channel", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bot_config_id = Column(Integer, nullable=True)
    channel = Column(String(20), nullable=False)  # discord | telegram
    event_type = Column(String(50), nullable=False)  # trade_entry | trade_exit | error | status | alert | daily_summary | risk_alert
    status = Column(String(10), nullable=False, default="sent")  # sent | failed
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    payload_summary = Column(String(500), nullable=True)  # truncated message preview
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    user = relationship("User", back_populates="notification_logs")


class ConfigChangeLog(Base):
    """Audit trail for configuration changes (bot configs, exchange connections)."""
    __tablename__ = "config_change_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)  # bot_config | exchange_connection
    entity_id = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)  # create | update | delete
    changes = Column(Text, nullable=True)  # JSON: {"field": {"old": x, "new": y}}
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    user = relationship("User")


class EventLog(Base):
    """Business event log for admin monitoring (bot lifecycle, trades, config changes)."""
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    bot_id = Column(Integer, nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(10), nullable=False, default="info")
    message = Column(String(1000), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class RevenueEntry(Base):
    """Revenue tracking: builder fees, affiliate commissions, referral income per exchange per day."""
    __tablename__ = "revenue_entries"
    __table_args__ = (
        UniqueConstraint("date", "exchange", "revenue_type", name="uq_revenue_date_exchange_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    exchange = Column(String(50), nullable=False, index=True)
    revenue_type = Column(String(50), nullable=False)  # builder_fee | affiliate | referral
    amount_usd = Column(Float, nullable=False, default=0.0)
    source = Column(String(20), nullable=False, default="manual", server_default="manual")  # auto_import | manual
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AffiliateState(Base):
    """Per-exchange last-sync state for the affiliate revenue fetcher.

    cumulative_amount_usd is only used by adapters whose API returns
    lifetime totals (currently: Hyperliquid). last_status is one of:
    "ok" | "error" | "unsupported".
    """
    __tablename__ = "affiliate_state"

    exchange = Column(String(50), primary_key=True)
    cumulative_amount_usd = Column(Float, nullable=False, default=0.0)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(20), nullable=True)
    last_error = Column(Text, nullable=True)
