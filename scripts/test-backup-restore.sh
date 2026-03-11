#!/bin/bash
# =============================================================================
# Backup Restore Test Script for Trading Bot
# =============================================================================
# Tests that the latest pg_dump backup can be restored and contains valid data.
#
# Usage (from host):
#   docker exec tradingbot-postgres bash /scripts/test-backup-restore.sh
#
# Usage (remote):
#   ssh trading-bot "docker exec tradingbot-postgres bash /scripts/test-backup-restore.sh"
#
# The script must be mounted into the postgres container. Add to docker-compose:
#   volumes:
#     - ./scripts:/scripts:ro
#
# Or copy it in:
#   docker cp scripts/test-backup-restore.sh tradingbot-postgres:/tmp/
#   docker exec tradingbot-postgres bash /tmp/test-backup-restore.sh
# =============================================================================
set -euo pipefail

BACKUP_DIR="/backups"
TEST_DB="restore_test_$(date +%s)"
PGUSER="${PGUSER:-tradingbot}"
PGHOST="${PGHOST:-localhost}"

# Key tables that must exist after restore
KEY_TABLES="users bot_configs trade_records exchange_connections bot_instances"

# ---------- helpers ----------------------------------------------------------

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
fail() { log "FAIL: $*"; cleanup; exit 1; }

cleanup() {
  log "Cleaning up test database ${TEST_DB}..."
  dropdb --if-exists -U "$PGUSER" -h "$PGHOST" "$TEST_DB" 2>/dev/null || true
}

# Ensure cleanup runs on exit (success or failure)
trap cleanup EXIT

# ---------- find latest backup -----------------------------------------------

if [ ! -d "$BACKUP_DIR" ]; then
  fail "Backup directory $BACKUP_DIR does not exist"
fi

LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/tradingbot_*.dump 2>/dev/null | head -1)

if [ -z "$LATEST_BACKUP" ]; then
  fail "No backup files found in $BACKUP_DIR"
fi

BACKUP_SIZE=$(stat -c%s "$LATEST_BACKUP" 2>/dev/null || stat -f%z "$LATEST_BACKUP" 2>/dev/null)
log "Latest backup: $(basename "$LATEST_BACKUP") (${BACKUP_SIZE} bytes)"

if [ "$BACKUP_SIZE" -lt 1024 ]; then
  fail "Backup file is suspiciously small (${BACKUP_SIZE} bytes)"
fi

# ---------- create test database ---------------------------------------------

log "Creating test database: ${TEST_DB}"
createdb -U "$PGUSER" -h "$PGHOST" "$TEST_DB" || fail "Could not create test database"

# ---------- restore ----------------------------------------------------------

log "Restoring backup into ${TEST_DB}..."
pg_restore -U "$PGUSER" -h "$PGHOST" -d "$TEST_DB" --no-owner --no-privileges "$LATEST_BACKUP" \
  || fail "pg_restore failed"

log "Restore completed successfully"

# ---------- integrity checks -------------------------------------------------

log "Running integrity checks..."

# Check total table count
TABLE_COUNT=$(psql -U "$PGUSER" -h "$PGHOST" -d "$TEST_DB" -t -A -c \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';")

log "Total tables found: ${TABLE_COUNT}"

if [ "$TABLE_COUNT" -lt 5 ]; then
  fail "Expected at least 5 tables, found ${TABLE_COUNT}"
fi

# Check each key table exists and get row count
ERRORS=0
for TABLE in $KEY_TABLES; do
  EXISTS=$(psql -U "$PGUSER" -h "$PGHOST" -d "$TEST_DB" -t -A -c \
    "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '${TABLE}');")

  if [ "$EXISTS" = "t" ]; then
    ROW_COUNT=$(psql -U "$PGUSER" -h "$PGHOST" -d "$TEST_DB" -t -A -c \
      "SELECT count(*) FROM \"${TABLE}\";")
    log "  ${TABLE}: ${ROW_COUNT} rows"
  else
    log "  ${TABLE}: MISSING"
    ERRORS=$((ERRORS + 1))
  fi
done

# Check alembic version (migrations marker)
HAS_ALEMBIC=$(psql -U "$PGUSER" -h "$PGHOST" -d "$TEST_DB" -t -A -c \
  "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'alembic_version');")

if [ "$HAS_ALEMBIC" = "t" ]; then
  MIGRATION=$(psql -U "$PGUSER" -h "$PGHOST" -d "$TEST_DB" -t -A -c \
    "SELECT version_num FROM alembic_version LIMIT 1;")
  log "  alembic_version: ${MIGRATION}"
else
  log "  alembic_version: not present (warning)"
fi

# ---------- result -----------------------------------------------------------

if [ "$ERRORS" -gt 0 ]; then
  fail "${ERRORS} key table(s) missing from restore"
fi

log "========================================="
log "PASS: Backup restore test successful"
log "  Backup:  $(basename "$LATEST_BACKUP")"
log "  Tables:  ${TABLE_COUNT}"
log "  Missing: 0"
log "========================================="
