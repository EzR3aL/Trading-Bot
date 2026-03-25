#!/bin/bash
# Off-host backup script for Trading Bot
#
# Uploads the latest PostgreSQL backup to DigitalOcean Spaces (S3-compatible).
# Run via cron: 0 3 * * * /home/trading/Trading-Bot/deploy/backup-offhost.sh
#
# Prerequisites:
#   1. Install s3cmd: apt install s3cmd
#   2. Configure: s3cmd --configure
#      - Access Key: from DO Spaces API
#      - Secret Key: from DO Spaces API
#      - S3 Endpoint: fra1.digitaloceanspaces.com
#      - DNS-style: %(bucket)s.fra1.digitaloceanspaces.com
#   3. Create a Space: e.g., "tradingbot-backups"
#
# Alternative: Use doctl (already installed):
#   doctl compute droplet-action snapshot <droplet-id>

set -euo pipefail

BACKUP_DIR="/home/trading/Trading-Bot/backups"
S3_BUCKET="${S3_BUCKET:-s3://tradingbot-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
LOG_FILE="/var/log/tradingbot-backup.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Find the latest backup
LATEST=$(ls -t "$BACKUP_DIR"/tradingbot_*.dump 2>/dev/null | head -1)

if [ -z "$LATEST" ]; then
    log "ERROR: No backup files found in $BACKUP_DIR"
    exit 1
fi

FILENAME=$(basename "$LATEST")
log "Uploading $FILENAME to $S3_BUCKET..."

# Upload via s3cmd
if command -v s3cmd &>/dev/null; then
    s3cmd put "$LATEST" "$S3_BUCKET/$FILENAME" --encrypt
    log "Upload complete: $S3_BUCKET/$FILENAME"

    # Clean up old remote backups
    log "Cleaning remote backups older than $RETENTION_DAYS days..."
    CUTOFF=$(date -d "$RETENTION_DAYS days ago" '+%Y%m%d' 2>/dev/null || date -v-${RETENTION_DAYS}d '+%Y%m%d')
    s3cmd ls "$S3_BUCKET/" | while read -r line; do
        FILE=$(echo "$line" | awk '{print $4}')
        if echo "$FILE" | grep -qE "tradingbot_[0-9]{8}"; then
            FILE_DATE=$(echo "$FILE" | grep -oE '[0-9]{8}' | head -1)
            if [ "$FILE_DATE" -lt "$CUTOFF" ] 2>/dev/null; then
                log "Removing old backup: $FILE"
                s3cmd del "$FILE"
            fi
        fi
    done
else
    log "ERROR: s3cmd not found. Install with: apt install s3cmd"
    exit 1
fi

# Also backup the encryption key (encrypted)
ENV_FILE="/home/trading/Trading-Bot/.env"
if [ -f "$ENV_FILE" ]; then
    ENCRYPTED_ENV=$(mktemp)
    gpg --batch --yes --passphrase-file /root/.backup-passphrase -c -o "$ENCRYPTED_ENV" "$ENV_FILE" 2>/dev/null || true
    if [ -s "$ENCRYPTED_ENV" ]; then
        s3cmd put "$ENCRYPTED_ENV" "$S3_BUCKET/env_backup_$(date +%Y%m%d).gpg" --encrypt
        log "Encrypted .env backup uploaded"
    fi
    rm -f "$ENCRYPTED_ENV"
fi

log "Backup complete."
