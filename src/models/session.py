"""
Async SQLAlchemy Engine and Session Factory.

Supports SQLite (default) and PostgreSQL (via DATABASE_URL env var).
"""

import os
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.database import Base

# Database URL - easily switch to PostgreSQL:
# DATABASE_URL = "postgresql+asyncpg://user:pass@host/db"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/bot.db")

engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    # SQLite-specific: enable WAL mode for concurrency
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

# Set WAL mode and busy_timeout on EVERY new SQLite connection
if "sqlite" in DATABASE_URL:
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


async def init_db() -> None:
    """Create all tables. Call once at application startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Migrations for existing SQLite databases
        if "sqlite" in DATABASE_URL:
            from sqlalchemy import text
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
                # Security: clear deprecated plaintext webhook URLs from user_configs
                "UPDATE user_configs SET discord_webhook_url = NULL WHERE discord_webhook_url IS NOT NULL",
                # Backtest runs table
                "CREATE TABLE IF NOT EXISTS backtest_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, strategy_type VARCHAR(50) NOT NULL, symbol VARCHAR(50) NOT NULL DEFAULT 'BTCUSDT', timeframe VARCHAR(10) NOT NULL DEFAULT '1d', start_date DATETIME NOT NULL, end_date DATETIME NOT NULL, initial_capital FLOAT NOT NULL DEFAULT 10000.0, strategy_params TEXT, status VARCHAR(20) NOT NULL DEFAULT 'pending', error_message TEXT, result_metrics TEXT, equity_curve TEXT, trades TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, completed_at DATETIME)",
                # Per-asset configuration column
                "ALTER TABLE bot_configs ADD COLUMN per_asset_config TEXT",
                # Make trading param columns nullable (SQLite workaround via column recreation is not possible;
                # instead we drop the NOT NULL constraint by recreating via a temp table approach)
            ]
            for migration in migrations:
                try:
                    await conn.execute(text(migration))
                except Exception as e:
                    if "duplicate column" not in str(e).lower():
                        from src.utils.logger import get_logger
                        get_logger(__name__).warning(f"Migration check: {e}")

            # ── Make trading param columns nullable (SQLite can't ALTER COLUMN) ──
            try:
                # Check if leverage column is still NOT NULL
                result = await conn.execute(text("PRAGMA table_info(bot_configs)"))
                cols = result.fetchall()
                leverage_col = next((c for c in cols if c[1] == 'leverage'), None)
                if leverage_col and leverage_col[3] == 1:  # notnull=1 → needs migration
                    # Get full column list for bot_configs
                    col_names = [c[1] for c in cols]
                    col_list = ', '.join(col_names)

                    # Build new CREATE TABLE with nullable trading params
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
                    # Copy data (use shared columns only)
                    old_cols = [c for c in col_names if c in [
                        'id', 'user_id', 'name', 'description', 'strategy_type', 'exchange_type',
                        'mode', 'trading_pairs', 'leverage', 'position_size_percent',
                        'max_trades_per_day', 'take_profit_percent', 'stop_loss_percent',
                        'daily_loss_limit_percent', 'per_asset_config', 'strategy_params',
                        'schedule_type', 'schedule_config', 'rotation_enabled',
                        'rotation_interval_minutes', 'rotation_start_time', 'discord_webhook_url',
                        'telegram_bot_token', 'telegram_chat_id', 'active_preset_id',
                        'is_enabled', 'created_at', 'updated_at',
                    ]]
                    shared = ', '.join(old_cols)
                    await conn.execute(text(f"INSERT INTO bot_configs ({shared}) SELECT {shared} FROM _bot_configs_old"))
                    await conn.execute(text("DROP TABLE _bot_configs_old"))
                    # Recreate index
                    await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_bot_configs_user ON bot_configs(user_id, created_at DESC)"))
            except Exception as e:
                from src.utils.logger import get_logger
                get_logger(__name__).warning(f"Nullable migration: {e}")

            # ── Additional index migrations ──
            additional_migrations = [
                "CREATE INDEX IF NOT EXISTS idx_trade_records_user_status ON trade_records(user_id, status, entry_time DESC)",
                "CREATE INDEX IF NOT EXISTS idx_trade_records_bot_config ON trade_records(bot_config_id, entry_time DESC)",
                "CREATE INDEX IF NOT EXISTS idx_bot_configs_user ON bot_configs(user_id, created_at DESC)",
            ]
            for m in additional_migrations:
                try:
                    await conn.execute(text(m))
                except Exception:
                    pass

            # Backfill builder_fee for existing closed Hyperliquid trades
            try:
                builder_fee_rate = int(os.environ.get("HL_BUILDER_FEE", "0"))
                if 1 <= builder_fee_rate <= 100:
                    await conn.execute(text(
                        f"""
                        UPDATE trade_records
                        SET builder_fee = (entry_price * size + exit_price * size)
                            * ({builder_fee_rate} / 1000000.0)
                        WHERE exchange = 'hyperliquid'
                          AND status = 'closed'
                          AND (builder_fee IS NULL OR builder_fee = 0)
                          AND exit_price IS NOT NULL
                        """
                    ))
            except Exception:
                pass


async def close_db() -> None:
    """Dispose engine. Call at application shutdown."""
    await engine.dispose()


@asynccontextmanager
async def get_session():
    """Provide an async session with automatic commit/rollback."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncSession:
    """FastAPI dependency that provides a database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
