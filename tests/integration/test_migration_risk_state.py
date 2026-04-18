"""Integration tests for migration 024_add_risk_state_fields_to_trade_records.

Covers Issue #189 (Epic #188): the migration adds the columns required by
the upcoming 2-Phase-Commit Risk-State-Manager.

Tested guarantees:
* ``alembic upgrade 024`` adds all 14 expected columns plus the
  ``ix_trade_records_status_synced`` index on top of revision 023.
* ``alembic downgrade 023`` removes them again (round-trip).
* The ``risk_source`` CHECK constraint rejects values outside the
  enum (``native_exchange | software_bot | manual_user | unknown``).
* The server-side default ``risk_source = 'unknown'`` is applied for
  rows that pre-existed before the upgrade and for rows inserted
  without an explicit ``risk_source`` value.
* The ORM model exposes the new columns with the right Python types.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PRE_189_TRADE_RECORDS_DDL = """
CREATE TABLE trade_records (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    bot_config_id INTEGER,
    exchange VARCHAR(50) NOT NULL DEFAULT 'bitget',
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    size FLOAT NOT NULL,
    entry_price FLOAT NOT NULL,
    exit_price FLOAT,
    take_profit FLOAT,
    stop_loss FLOAT,
    leverage INTEGER NOT NULL,
    confidence INTEGER NOT NULL,
    reason TEXT NOT NULL,
    order_id VARCHAR(100) NOT NULL,
    close_order_id VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    pnl FLOAT,
    pnl_percent FLOAT,
    fees FLOAT DEFAULT 0,
    funding_paid FLOAT DEFAULT 0,
    builder_fee FLOAT DEFAULT 0,
    entry_time DATETIME NOT NULL,
    exit_time DATETIME,
    exit_reason VARCHAR(50),
    metrics_snapshot TEXT,
    highest_price FLOAT,
    native_trailing_stop BOOLEAN NOT NULL DEFAULT 0,
    trailing_atr_override FLOAT,
    demo_mode BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);
"""

EXPECTED_NEW_COLUMNS = {
    "tp_order_id": "VARCHAR(100)",
    "sl_order_id": "VARCHAR(100)",
    "trailing_order_id": "VARCHAR(100)",
    "trailing_callback_rate": "FLOAT",
    "trailing_activation_price": "FLOAT",
    "trailing_trigger_price": "FLOAT",
    "risk_source": "VARCHAR(20)",
    "tp_intent": "FLOAT",
    "tp_status": "VARCHAR(20)",
    "sl_intent": "FLOAT",
    "sl_status": "VARCHAR(20)",
    "trailing_intent_callback": "FLOAT",
    "trailing_status": "VARCHAR(20)",
    "last_synced_at": "DATETIME",
}


def _make_alembic_config(db_url: str) -> Config:
    """Build an Alembic Config pointed at the repo's migration directory."""
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _bootstrap_pre_189_schema(sync_db_url: str) -> None:
    """Create just enough schema (trade_records + alembic_version) to run 024."""
    engine = create_engine(sync_db_url)
    with engine.begin() as conn:
        # Create the trade_records table as it looked after revision 023.
        conn.execute(text(PRE_189_TRADE_RECORDS_DDL))
        # Pre-create all indexes that exist on trade_records up to 023.
        conn.execute(text("CREATE INDEX ix_trade_records_user_id ON trade_records (user_id)"))
        conn.execute(text("CREATE INDEX ix_trade_records_bot_config_id ON trade_records (bot_config_id)"))
        conn.execute(text("CREATE INDEX ix_trade_records_symbol ON trade_records (symbol)"))
        conn.execute(text("CREATE INDEX ix_trade_records_status ON trade_records (status)"))
        conn.execute(text("CREATE INDEX ix_trade_user_status ON trade_records (user_id, status)"))
        conn.execute(text("CREATE INDEX ix_trade_user_symbol_side ON trade_records (user_id, symbol, side)"))
        conn.execute(text("CREATE INDEX ix_trade_bot_status ON trade_records (bot_config_id, status)"))
        conn.execute(text("CREATE INDEX ix_trade_entry_time ON trade_records (entry_time)"))
        conn.execute(text("CREATE INDEX ix_trade_exit_time ON trade_records (exit_time)"))
        conn.execute(text("CREATE INDEX ix_trade_user_demo ON trade_records (user_id, demo_mode)"))
        conn.execute(text("CREATE INDEX ix_trade_records_entry_time ON trade_records (entry_time)"))

        # Stamp alembic_version table at revision 023 so upgrade picks 024.
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('023')"))
    engine.dispose()


def _columns(sync_db_url: str) -> dict[str, dict]:
    """Return a {column_name: column_info} mapping for trade_records."""
    engine = create_engine(sync_db_url)
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("trade_records")}
    engine.dispose()
    return cols


def _indexes(sync_db_url: str) -> set[str]:
    """Return the set of index names defined on trade_records."""
    engine = create_engine(sync_db_url)
    insp = inspect(engine)
    names = {ix["name"] for ix in insp.get_indexes("trade_records")}
    engine.dispose()
    return names


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_sqlite_db(tmp_path: Path) -> tuple[str, str]:
    """Provide (sync_url, async_url) for a fresh on-disk SQLite database.

    On-disk is required because Alembic uses a sync driver while the
    application uses an async driver — both must hit the same file.
    """
    db_path = tmp_path / "migration_test.db"
    sync_url = f"sqlite:///{db_path}"
    # env.py honors DATABASE_URL — we hand it the matching aiosqlite URL.
    async_url = f"sqlite+aiosqlite:///{db_path}"
    return sync_url, async_url


def test_upgrade_024_adds_all_risk_state_columns_and_index(temp_sqlite_db) -> None:
    """``alembic upgrade 024`` adds the 14 new columns + the new index."""
    sync_url, async_url = temp_sqlite_db
    _bootstrap_pre_189_schema(sync_url)

    # Sanity: pre-#189 schema does NOT have any of the new columns.
    cols_before = _columns(sync_url)
    for new_col in EXPECTED_NEW_COLUMNS:
        assert new_col not in cols_before, (
            f"Column {new_col} unexpectedly present before migration 024"
        )

    cfg = _make_alembic_config(async_url)
    os.environ["DATABASE_URL"] = async_url
    try:
        command.upgrade(cfg, "024")
    finally:
        os.environ.pop("DATABASE_URL", None)

    cols_after = _columns(sync_url)
    for new_col, expected_type_fragment in EXPECTED_NEW_COLUMNS.items():
        assert new_col in cols_after, f"Column {new_col} missing after upgrade"
        actual_type = str(cols_after[new_col]["type"]).upper()
        # SQLAlchemy may render FLOAT or DOUBLE_PRECISION; both accepted.
        if expected_type_fragment == "FLOAT":
            assert "FLOAT" in actual_type or "DOUBLE" in actual_type or "REAL" in actual_type, (
                f"Column {new_col} has type {actual_type}, expected FLOAT-like"
            )
        elif expected_type_fragment.startswith("VARCHAR"):
            assert "VARCHAR" in actual_type or "CHAR" in actual_type or "TEXT" in actual_type, (
                f"Column {new_col} has type {actual_type}, expected VARCHAR-like"
            )
        elif expected_type_fragment == "DATETIME":
            assert "DATETIME" in actual_type or "TIMESTAMP" in actual_type, (
                f"Column {new_col} has type {actual_type}, expected DATETIME-like"
            )

    # risk_source must be NOT NULL with default 'unknown'.
    risk_source = cols_after["risk_source"]
    assert risk_source["nullable"] is False, "risk_source must be NOT NULL"
    default = (risk_source.get("default") or "").lower()
    assert "unknown" in default, f"risk_source default must be 'unknown', got {default!r}"

    # All other new columns must be nullable.
    for new_col in EXPECTED_NEW_COLUMNS:
        if new_col == "risk_source":
            continue
        assert cols_after[new_col]["nullable"] is True, f"{new_col} should be nullable"

    # The new reconciler index must exist.
    indexes = _indexes(sync_url)
    assert "ix_trade_records_status_synced" in indexes, (
        f"Expected ix_trade_records_status_synced index after upgrade, got {indexes}"
    )


def test_downgrade_023_removes_all_risk_state_columns_and_index(temp_sqlite_db) -> None:
    """``alembic downgrade 023`` reverses the migration cleanly."""
    sync_url, async_url = temp_sqlite_db
    _bootstrap_pre_189_schema(sync_url)

    cfg = _make_alembic_config(async_url)
    os.environ["DATABASE_URL"] = async_url
    try:
        command.upgrade(cfg, "024")
        command.downgrade(cfg, "023")
    finally:
        os.environ.pop("DATABASE_URL", None)

    cols_after = _columns(sync_url)
    for new_col in EXPECTED_NEW_COLUMNS:
        assert new_col not in cols_after, (
            f"Column {new_col} should be gone after downgrade"
        )

    indexes = _indexes(sync_url)
    assert "ix_trade_records_status_synced" not in indexes, (
        "ix_trade_records_status_synced should be gone after downgrade"
    )


def test_risk_source_check_constraint_rejects_invalid_value(temp_sqlite_db) -> None:
    """Inserting risk_source='invalid' must violate the CHECK constraint."""
    sync_url, async_url = temp_sqlite_db
    _bootstrap_pre_189_schema(sync_url)

    cfg = _make_alembic_config(async_url)
    os.environ["DATABASE_URL"] = async_url
    try:
        command.upgrade(cfg, "024")
    finally:
        os.environ.pop("DATABASE_URL", None)

    # Need foreign-key constraint OFF for SQLite minimal setup (no users table).
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        # Valid value should succeed.
        conn.execute(
            text(
                "INSERT INTO trade_records "
                "(user_id, exchange, symbol, side, size, entry_price, leverage, "
                " confidence, reason, order_id, status, entry_time, risk_source) "
                "VALUES (1, 'bitget', 'BTCUSDT', 'long', 0.01, 50000, 5, 75, "
                " 'test', 'order_valid', 'open', '2026-04-18 00:00:00', 'software_bot')"
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO trade_records "
                    "(user_id, exchange, symbol, side, size, entry_price, leverage, "
                    " confidence, reason, order_id, status, entry_time, risk_source) "
                    "VALUES (2, 'bitget', 'BTCUSDT', 'long', 0.01, 50000, 5, 75, "
                    " 'test', 'order_invalid', 'open', '2026-04-18 00:00:00', 'invalid')"
                )
            )

    engine.dispose()


def test_risk_source_default_unknown_for_existing_rows(temp_sqlite_db) -> None:
    """Rows that pre-existed before the upgrade get risk_source='unknown'."""
    sync_url, async_url = temp_sqlite_db
    _bootstrap_pre_189_schema(sync_url)

    # Seed a pre-#189 row before running the migration.
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO trade_records "
                "(user_id, exchange, symbol, side, size, entry_price, leverage, "
                " confidence, reason, order_id, status, entry_time) "
                "VALUES (1, 'bitget', 'BTCUSDT', 'long', 0.01, 50000, 5, 75, "
                " 'pre-existing', 'order_legacy', 'open', '2026-04-18 00:00:00')"
            )
        )
    engine.dispose()

    # Now apply the migration.
    cfg = _make_alembic_config(async_url)
    os.environ["DATABASE_URL"] = async_url
    try:
        command.upgrade(cfg, "024")
    finally:
        os.environ.pop("DATABASE_URL", None)

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT risk_source FROM trade_records WHERE order_id = 'order_legacy'")
        ).all()
    engine.dispose()

    assert len(rows) == 1
    assert rows[0][0] == "unknown", (
        f"Pre-existing row must default to risk_source='unknown', got {rows[0][0]!r}"
    )


def test_risk_source_default_unknown_for_new_rows_without_value(temp_sqlite_db) -> None:
    """Inserting a row without risk_source uses the server default 'unknown'."""
    sync_url, async_url = temp_sqlite_db
    _bootstrap_pre_189_schema(sync_url)

    cfg = _make_alembic_config(async_url)
    os.environ["DATABASE_URL"] = async_url
    try:
        command.upgrade(cfg, "024")
    finally:
        os.environ.pop("DATABASE_URL", None)

    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO trade_records "
                "(user_id, exchange, symbol, side, size, entry_price, leverage, "
                " confidence, reason, order_id, status, entry_time) "
                "VALUES (1, 'bitget', 'BTCUSDT', 'long', 0.01, 50000, 5, 75, "
                " 'no-risk-source', 'order_default', 'open', '2026-04-18 00:00:00')"
            )
        )
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT risk_source FROM trade_records WHERE order_id = 'order_default'")
        ).all()
    engine.dispose()

    assert len(rows) == 1
    assert rows[0][0] == "unknown"


def test_orm_model_exposes_new_risk_state_fields() -> None:
    """The TradeRecord ORM model has the new fields with the right shape."""
    from src.models.database import TradeRecord

    expected_fields = {
        "tp_order_id",
        "sl_order_id",
        "trailing_order_id",
        "trailing_callback_rate",
        "trailing_activation_price",
        "trailing_trigger_price",
        "risk_source",
        "tp_intent",
        "tp_status",
        "sl_intent",
        "sl_status",
        "trailing_intent_callback",
        "trailing_status",
        "last_synced_at",
    }

    actual_fields = {col.name for col in TradeRecord.__table__.columns}
    missing = expected_fields - actual_fields
    assert not missing, f"TradeRecord model missing risk-state fields: {missing}"

    # risk_source must be NOT NULL on the model side too.
    risk_source_col = TradeRecord.__table__.c["risk_source"]
    assert risk_source_col.nullable is False
    # All other risk-state columns are nullable.
    for fname in expected_fields - {"risk_source"}:
        assert TradeRecord.__table__.c[fname].nullable is True, (
            f"{fname} should be nullable on the ORM model"
        )

    # The reconciler index must be declared on the table.
    index_names = {ix.name for ix in TradeRecord.__table__.indexes}
    assert "ix_trade_records_status_synced" in index_names

    # The CHECK constraint must be declared on the table.
    constraint_names = {
        c.name for c in TradeRecord.__table__.constraints if c.name is not None
    }
    assert "ck_trade_records_risk_source" in constraint_names
