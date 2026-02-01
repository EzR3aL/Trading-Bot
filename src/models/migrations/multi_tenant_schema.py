"""
Multi-tenant database schema migration.

This migration adds support for:
- Multiple users with authentication
- Per-user API credentials (encrypted)
- Bot instances per user
- User sessions for JWT token management
- Audit logging for security compliance

Compatible with both SQLite (development) and PostgreSQL (production).
"""

import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Migration version
VERSION = "001"
DESCRIPTION = "Add multi-tenant support tables"


def ensure_db_path(db_path: str = "data/trades.db") -> str:
    """Ensure database directory exists and return path."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


async def check_migration_applied(db_path: str = "data/trades.db") -> bool:
    """Check if this migration has already been applied."""
    async with aiosqlite.connect(ensure_db_path(db_path)) as db:
        try:
            cursor = await db.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                (VERSION,)
            )
            row = await cursor.fetchone()
            return row is not None
        except Exception:
            # Table doesn't exist yet
            return False


async def upgrade(db_path: str = "data/trades.db") -> bool:
    """
    Apply the migration.

    Creates all multi-tenant tables and modifies existing tables.
    """
    if await check_migration_applied(db_path):
        logger.info(f"Migration {VERSION} already applied, skipping")
        return True

    logger.info(f"Applying migration {VERSION}: {DESCRIPTION}")

    async with aiosqlite.connect(ensure_db_path(db_path)) as db:
        try:
            # Create schema_migrations table to track migrations
            await db.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    description TEXT,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ============================================
            # USERS TABLE
            # ============================================
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    is_admin INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            logger.info("Created users table")

            # ============================================
            # USER CREDENTIALS TABLE (API Keys - Encrypted)
            # ============================================
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT 'bitget',
                    credential_type TEXT NOT NULL DEFAULT 'live',
                    api_key_encrypted TEXT NOT NULL,
                    api_secret_encrypted TEXT NOT NULL,
                    passphrase_encrypted TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, name),
                    CHECK (credential_type IN ('live', 'demo'))
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_credentials_user ON user_credentials(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_credentials_active ON user_credentials(user_id, is_active)")
            logger.info("Created user_credentials table")

            # ============================================
            # BOT INSTANCES TABLE
            # ============================================
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_instances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    credential_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    config TEXT NOT NULL DEFAULT '{}',
                    is_running INTEGER DEFAULT 0,
                    last_heartbeat TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (credential_id) REFERENCES user_credentials(id) ON DELETE CASCADE,
                    UNIQUE(user_id, name)
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_bot_instances_user ON bot_instances(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_bot_instances_running ON bot_instances(is_running)")
            logger.info("Created bot_instances table")

            # ============================================
            # USER SESSIONS TABLE (JWT Token Management)
            # ============================================
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL,
                    refresh_token_hash TEXT,
                    expires_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    revoked_at TIMESTAMP,
                    ip_address TEXT,
                    user_agent TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(token_hash)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON user_sessions(expires_at)")
            logger.info("Created user_sessions table")

            # ============================================
            # AUDIT LOGS TABLE
            # ============================================
            await db.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    resource_type TEXT,
                    resource_id INTEGER,
                    details TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(created_at DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_logs(user_id, created_at DESC)")
            logger.info("Created audit_logs table")

            # ============================================
            # DAILY STATS TABLE (Per Bot Instance)
            # ============================================
            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    bot_instance_id INTEGER,
                    date TEXT NOT NULL,
                    starting_balance REAL NOT NULL,
                    current_balance REAL NOT NULL,
                    trades_executed INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    total_fees REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    is_trading_halted INTEGER DEFAULT 0,
                    halt_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (bot_instance_id) REFERENCES bot_instances(id) ON DELETE CASCADE,
                    UNIQUE(user_id, bot_instance_id, date)
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_daily_stats_user_date ON daily_stats(user_id, date DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_daily_stats_bot ON daily_stats(bot_instance_id, date DESC)")
            logger.info("Created daily_stats table")

            # ============================================
            # MODIFY EXISTING TRADES TABLE
            # Add user_id and bot_instance_id columns
            # ============================================

            # Check if trades table exists and needs modification
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
            )
            trades_exists = await cursor.fetchone()

            if trades_exists:
                # Check if user_id column already exists
                cursor = await db.execute("PRAGMA table_info(trades)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]

                if 'user_id' not in column_names:
                    await db.execute("ALTER TABLE trades ADD COLUMN user_id INTEGER")
                    logger.info("Added user_id column to trades table")

                if 'bot_instance_id' not in column_names:
                    await db.execute("ALTER TABLE trades ADD COLUMN bot_instance_id INTEGER")
                    logger.info("Added bot_instance_id column to trades table")

                # Create indexes for multi-tenant queries
                await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_user_status ON trades(user_id, status)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_trades_bot_instance ON trades(bot_instance_id)")

            # ============================================
            # RECORD MIGRATION
            # ============================================
            await db.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                (VERSION, DESCRIPTION)
            )

            await db.commit()
            logger.info(f"Migration {VERSION} applied successfully")
            return True

        except Exception as e:
            await db.rollback()
            logger.error(f"Migration {VERSION} failed: {e}")
            raise


async def downgrade(db_path: str = "data/trades.db") -> bool:
    """
    Rollback the migration.

    WARNING: This will delete all multi-tenant data!
    """
    logger.warning(f"Rolling back migration {VERSION}")

    async with aiosqlite.connect(ensure_db_path(db_path)) as db:
        try:
            # Drop tables in reverse order (respecting foreign keys)
            await db.execute("DROP TABLE IF EXISTS audit_logs")
            await db.execute("DROP TABLE IF EXISTS daily_stats")
            await db.execute("DROP TABLE IF EXISTS user_sessions")
            await db.execute("DROP TABLE IF EXISTS bot_instances")
            await db.execute("DROP TABLE IF EXISTS user_credentials")
            await db.execute("DROP TABLE IF EXISTS users")

            # Remove migration record
            await db.execute(
                "DELETE FROM schema_migrations WHERE version = ?",
                (VERSION,)
            )

            await db.commit()
            logger.info(f"Migration {VERSION} rolled back successfully")
            return True

        except Exception as e:
            await db.rollback()
            logger.error(f"Migration {VERSION} rollback failed: {e}")
            raise


async def run_migrations(db_path: str = "data/trades.db") -> None:
    """Run all pending migrations."""
    await upgrade(db_path)


if __name__ == "__main__":
    import asyncio
    asyncio.run(upgrade())
