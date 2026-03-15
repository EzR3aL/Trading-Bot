"""
Async SQLAlchemy Engine and Session Factory.

Supports SQLite (default) and PostgreSQL (via DATABASE_URL env var).
PostgreSQL uses connection pooling optimized for 10k+ concurrent users.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base

# Database URL - easily switch to PostgreSQL:
# DATABASE_URL = "postgresql+asyncpg://user:pass@host/db"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")


def _build_engine_kwargs() -> dict:
    """Build engine kwargs based on the database backend."""
    kwargs = {
        "echo": os.getenv("SQL_ECHO", "false").lower() == "true",
    }
    if _is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL connection pool settings
        kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "20"))
        kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "30"))
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "1800"))
        kwargs["pool_timeout"] = int(os.getenv("DB_POOL_TIMEOUT", "10"))
    return kwargs


engine = create_async_engine(DATABASE_URL, **_build_engine_kwargs())

# Set WAL mode and busy_timeout on EVERY new SQLite connection
if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=1000")
        cursor.close()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def _run_sqlite_migrations(conn) -> None:
    """Run inline migrations for existing SQLite databases.

    PostgreSQL relies on Base.metadata.create_all which generates correct
    schemas from the ORM models (including proper BOOLEAN types).
    These ALTER TABLE statements are SQLite-only because PostgreSQL does
    not need them — the columns already exist from create_all.
    """
    from src.utils.logger import get_logger
    _log = get_logger(__name__)

    migrations = [
        "ALTER TABLE trade_records ADD COLUMN demo_mode BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE trade_records ADD COLUMN bot_config_id INTEGER REFERENCES bot_configs(id) ON DELETE SET NULL",
        "ALTER TABLE bot_instances ADD COLUMN bot_config_id INTEGER REFERENCES bot_configs(id) ON DELETE SET NULL",
        "ALTER TABLE bot_instances ADD COLUMN error_message TEXT",
        # Soft-delete columns for User model
        "ALTER TABLE users ADD COLUMN is_deleted BOOLEAN DEFAULT 0",
        "ALTER TABLE users ADD COLUMN deleted_at DATETIME",
        # Revenue analytics: builder fee tracking
        "ALTER TABLE trade_records ADD COLUMN builder_fee FLOAT DEFAULT 0",
        # Token revocation support
        "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0",
        # Per-bot Discord webhook override
        "ALTER TABLE bot_configs ADD COLUMN discord_webhook_url TEXT",
        # Per-bot Telegram notifications
        "ALTER TABLE bot_configs ADD COLUMN telegram_bot_token TEXT",
        "ALTER TABLE bot_configs ADD COLUMN telegram_chat_id VARCHAR(50)",
        # Active preset tracking
        "ALTER TABLE bot_configs ADD COLUMN active_preset_id INTEGER REFERENCES config_presets(id) ON DELETE SET NULL",
        # Builder fee approval tracking
        "ALTER TABLE exchange_connections ADD COLUMN builder_fee_approved BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE exchange_connections ADD COLUMN builder_fee_approved_at DATETIME",
        # Referral verification tracking
        "ALTER TABLE exchange_connections ADD COLUMN referral_verified BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE exchange_connections ADD COLUMN referral_verified_at DATETIME",
        # System settings (admin-managed key-value store)
        "CREATE TABLE IF NOT EXISTS system_settings (key VARCHAR(100) PRIMARY KEY, value TEXT, updated_at DATETIME)",
        # Affiliate UID verification (Bitget / Weex)
        "ALTER TABLE exchange_connections ADD COLUMN affiliate_uid VARCHAR(100)",
        "ALTER TABLE exchange_connections ADD COLUMN affiliate_verified BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE exchange_connections ADD COLUMN affiliate_verified_at DATETIME",
        # Affiliate link UID requirement flag
        "ALTER TABLE affiliate_links ADD COLUMN uid_required BOOLEAN NOT NULL DEFAULT 0",
        # Account lockout columns (v3.13)
        "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN locked_until DATETIME",
        # Security: clear deprecated plaintext webhook URLs from user_configs
        "UPDATE user_configs SET discord_webhook_url = NULL WHERE discord_webhook_url IS NOT NULL",
        # Backtest runs table
        "CREATE TABLE IF NOT EXISTS backtest_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, strategy_type VARCHAR(50) NOT NULL, symbol VARCHAR(50) NOT NULL DEFAULT 'BTCUSDT', timeframe VARCHAR(10) NOT NULL DEFAULT '1d', start_date DATETIME NOT NULL, end_date DATETIME NOT NULL, initial_capital FLOAT NOT NULL DEFAULT 10000.0, strategy_params TEXT, status VARCHAR(20) NOT NULL DEFAULT 'pending', error_message TEXT, result_metrics TEXT, equity_curve TEXT, trades TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, completed_at DATETIME)",
        # Per-asset configuration column
        "ALTER TABLE bot_configs ADD COLUMN per_asset_config TEXT",
        # Risk stats table (database-backed daily stats)
        "CREATE TABLE IF NOT EXISTS risk_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, bot_config_id INTEGER NOT NULL REFERENCES bot_configs(id) ON DELETE CASCADE, date VARCHAR(10) NOT NULL, stats_json TEXT NOT NULL, daily_pnl FLOAT DEFAULT 0.0, trades_count INTEGER DEFAULT 0, is_halted BOOLEAN DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_stats_bot_date ON risk_stats(bot_config_id, date)",
        # Alerts table
        "CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, bot_config_id INTEGER REFERENCES bot_configs(id) ON DELETE SET NULL, alert_type VARCHAR(20) NOT NULL, category VARCHAR(50) NOT NULL, symbol VARCHAR(50), threshold FLOAT NOT NULL, direction VARCHAR(10), is_enabled BOOLEAN NOT NULL DEFAULT 1, cooldown_minutes INTEGER NOT NULL DEFAULT 15, last_triggered_at DATETIME, trigger_count INTEGER NOT NULL DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME)",
        "CREATE INDEX IF NOT EXISTS ix_alert_user_enabled ON alerts(user_id, is_enabled)",
        # Alert history table
        "CREATE TABLE IF NOT EXISTS alert_history (id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE, triggered_at DATETIME DEFAULT CURRENT_TIMESTAMP, current_value FLOAT, message TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS ix_alert_history_alert ON alert_history(alert_id)",
        # Native trailing stop tracking (v3.36)
        "ALTER TABLE trade_records ADD COLUMN native_trailing_stop BOOLEAN NOT NULL DEFAULT 0",
        # Notification logs table
        "CREATE TABLE IF NOT EXISTS notification_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, bot_config_id INTEGER, channel VARCHAR(20) NOT NULL, event_type VARCHAR(50) NOT NULL, status VARCHAR(10) NOT NULL DEFAULT 'sent', error_message TEXT, retry_count INTEGER DEFAULT 0, payload_summary VARCHAR(500), created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
        "CREATE INDEX IF NOT EXISTS ix_notification_logs_user_id ON notification_logs(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_notif_user_created ON notification_logs(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_notif_channel_status ON notification_logs(channel, status)",
        "CREATE INDEX IF NOT EXISTS ix_notification_logs_created_at ON notification_logs(created_at)",
    ]
    for migration in migrations:
        try:
            await conn.execute(text(migration))
        except Exception as e:
            if "duplicate column" not in str(e).lower():
                _log.warning(f"Migration check: {e}")

    # ── Make trading param columns nullable (SQLite can't ALTER COLUMN) ──
    try:
        result = await conn.execute(text("PRAGMA table_info(bot_configs)"))
        cols = result.fetchall()
        leverage_col = next((c for c in cols if c[1] == 'leverage'), None)
        if leverage_col and leverage_col[3] == 1:  # notnull=1 → needs migration
            col_names = [c[1] for c in cols]

            await conn.execute(text("ALTER TABLE bot_configs RENAME TO _bot_configs_old"))
            await conn.execute(text("""
                CREATE TABLE bot_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    strategy_type VARCHAR(50) NOT NULL,
                    exchange_type VARCHAR(50) NOT NULL,
                    mode VARCHAR(10) NOT NULL DEFAULT 'demo',
                    trading_pairs TEXT NOT NULL DEFAULT '["BTCUSDT"]',
                    leverage INTEGER,
                    position_size_percent FLOAT,
                    max_trades_per_day INTEGER,
                    take_profit_percent FLOAT,
                    stop_loss_percent FLOAT,
                    daily_loss_limit_percent FLOAT,
                    per_asset_config TEXT,
                    strategy_params TEXT,
                    schedule_type VARCHAR(20) NOT NULL DEFAULT 'market_sessions',
                    schedule_config TEXT,
                    rotation_enabled BOOLEAN DEFAULT 0,
                    rotation_interval_minutes INTEGER,
                    rotation_start_time TEXT,
                    discord_webhook_url TEXT,
                    telegram_bot_token TEXT,
                    telegram_chat_id VARCHAR(50),
                    active_preset_id INTEGER REFERENCES config_presets(id) ON DELETE SET NULL,
                    is_enabled BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
            """))
            allowed_cols = {
                'id', 'user_id', 'name', 'description', 'strategy_type', 'exchange_type',
                'mode', 'trading_pairs', 'leverage', 'position_size_percent',
                'max_trades_per_day', 'take_profit_percent', 'stop_loss_percent',
                'daily_loss_limit_percent', 'per_asset_config', 'strategy_params',
                'schedule_type', 'schedule_config', 'rotation_enabled',
                'rotation_interval_minutes', 'rotation_start_time', 'discord_webhook_url',
                'telegram_bot_token', 'telegram_chat_id', 'active_preset_id',
                'is_enabled', 'created_at', 'updated_at',
            }
            old_cols = [c for c in col_names if c in allowed_cols]
            # Whitelist-validated identifiers — safe for interpolation
            shared = ', '.join(f'"{c}"' for c in old_cols)
            await conn.execute(text(f"INSERT INTO bot_configs ({shared}) SELECT {shared} FROM _bot_configs_old"))
            await conn.execute(text("DROP TABLE _bot_configs_old"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_bot_configs_user ON bot_configs(user_id, created_at DESC)"))
    except Exception as e:
        _log.warning(f"Nullable migration: {e}")

    # ── Additional index migrations ──
    additional_migrations = [
        "CREATE INDEX IF NOT EXISTS idx_trade_records_user_status ON trade_records(user_id, status, entry_time DESC)",
        "CREATE INDEX IF NOT EXISTS idx_trade_records_bot_config ON trade_records(bot_config_id, entry_time DESC)",
        "CREATE INDEX IF NOT EXISTS idx_bot_configs_user ON bot_configs(user_id, created_at DESC)",
    ]
    for m in additional_migrations:
        try:
            await conn.execute(text(m))
        except Exception as e:
            _log.warning("Index migration skipped: %s — %s", m[:60], e)

    # Backfill builder_fee for existing closed Hyperliquid trades
    try:
        builder_fee_rate = int(os.environ.get("HL_BUILDER_FEE", "0"))
        if 1 <= builder_fee_rate <= 100:
            await conn.execute(
                text("""
                    UPDATE trade_records
                    SET builder_fee = (entry_price * size + exit_price * size)
                        * (:rate / 1000000.0)
                    WHERE exchange = 'hyperliquid'
                      AND status = 'closed'
                      AND (builder_fee IS NULL OR builder_fee = 0)
                      AND exit_price IS NOT NULL
                """),
                {"rate": builder_fee_rate}
            )
    except Exception as e:
        _log.warning("Builder fee backfill failed: %s", e)


async def init_db() -> None:
    """Create/migrate all tables. Call once at application startup.

    Strategy:
    - Fresh database: run ``alembic upgrade head`` to create schema
    - Existing database (pre-Alembic): stamp as ``head`` then run SQLite patches
    - Existing database (with Alembic): run ``alembic upgrade head`` for pending migrations
    """
    from alembic import command as alembic_cmd
    from alembic.config import Config as AlembicConfig

    alembic_cfg = AlembicConfig("alembic.ini")

    async with engine.begin() as conn:
        # Check whether the database already has tables (pre-Alembic legacy)
        has_tables = await conn.run_sync(
            lambda sync_conn: engine.dialect.has_table(sync_conn, "users")
        )

        # Check whether Alembic version table exists
        has_alembic = await conn.run_sync(
            lambda sync_conn: engine.dialect.has_table(sync_conn, "alembic_version")
        )

    if has_tables and not has_alembic:
        # Legacy database: ensure schema is up to date, then stamp
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if _is_sqlite:
                await _run_sqlite_migrations(conn)
        alembic_cmd.stamp(alembic_cfg, "head")
    else:
        # Fresh or already-migrated database
        alembic_cmd.upgrade(alembic_cfg, "head")
        # Run SQLite-only patches that Alembic migrations don't cover
        if _is_sqlite:
            async with engine.begin() as conn:
                await _run_sqlite_migrations(conn)


async def close_db() -> None:
    """Dispose engine. Call at application shutdown."""
    await engine.dispose()


SESSION_ACQUIRE_TIMEOUT = int(os.getenv("DB_SESSION_TIMEOUT", "10"))


@asynccontextmanager
async def get_session():
    """Provide an async session with automatic commit/rollback."""
    try:
        session = await asyncio.wait_for(
            async_session_factory().__aenter__(),
            timeout=SESSION_ACQUIRE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"Could not acquire database session within {SESSION_ACQUIRE_TIMEOUT}s "
            "(connection pool may be exhausted)"
        )
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.__aexit__(None, None, None)


async def get_db() -> AsyncSession:
    """FastAPI dependency that provides a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
