#!/bin/zsh
# ────────────────────────────────────────────────────────────────────
# Quarry — PostgreSQL nightly backup script
#
# Runs pg_dump inside the Docker "db" container, compresses the output,
# and stores a date-stamped .sql.gz file locally. Old backups beyond
# the retention window are automatically deleted.
#
# Usage:
#   ./scripts/pg_backup.sh                 # run manually
#   0 2 * * * /path/to/scripts/pg_backup.sh  # cron — every night at 2 AM
#
# Requirements:
#   - Docker Compose services running (docker-compose.prod.yml)
#   - The .env file must set POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#
# ⚠  OFF-SERVER COPY — this script stores backups locally only.
#    You MUST set up an off-server copy mechanism (e.g. rsync to NAS,
#    aws s3 cp, rclone, or scp to a remote host) to protect against
#    disk/host failure. Example:
#
#      aws s3 cp "$BACKUP_DIR/" s3://your-bucket/quarry-backups/ --recursive
#      rsync -avz "$BACKUP_DIR/" backupuser@remote:/backups/quarry/
#
# ────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────
SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.prod.yml"
BACKUP_DIR="${PROJECT_DIR}/backups"
RETENTION_DAYS="${QUARRY_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
BACKUP_FILE="quarry_${TIMESTAMP}.sql.gz"

# Load DB credentials from .env if present
if [[ -f "${PROJECT_DIR}/.env" ]]; then
    source <(grep -E '^POSTGRES_(USER|PASSWORD|DB)=' "${PROJECT_DIR}/.env" | sed 's/^/export /')
fi

DB_USER="${POSTGRES_USER:-quarry}"
DB_NAME="${POSTGRES_DB:-quarry}"

# ── Pre-flight checks ─────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker not found in PATH" >&2
    exit 1
fi

if ! docker compose -f "$COMPOSE_FILE" ps db --status running 2>/dev/null | grep -q "running"; then
    echo "ERROR: db container is not running (compose file: $COMPOSE_FILE)" >&2
    exit 1
fi

# ── Create backup directory ───────────────────────────────────────
mkdir -p "$BACKUP_DIR"

# ── Run pg_dump inside the container ──────────────────────────────
echo "[$(date -u +%H:%M:%S)] Starting backup → ${BACKUP_FILE}"

docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner --no-acl \
    | gzip > "${BACKUP_DIR}/${BACKUP_FILE}"

BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_FILE}" | cut -f1)
echo "[$(date -u +%H:%M:%S)] Backup complete: ${BACKUP_FILE} (${BACKUP_SIZE})"

# ── Retention cleanup ─────────────────────────────────────────────
DELETED=0
for f in "$BACKUP_DIR"/quarry_*.sql.gz; do
    [[ -f "$f" ]] || continue
    # macOS stat -f %m gives modification time as epoch seconds
    FILE_AGE_DAYS=$(( ( $(date +%s) - $(stat -f %m "$f") ) / 86400 ))
    if (( FILE_AGE_DAYS > RETENTION_DAYS )); then
        rm "$f"
        DELETED=$((DELETED + 1))
        echo "  Deleted old backup: $(basename "$f") (${FILE_AGE_DAYS}d old)"
    fi
done

if (( DELETED > 0 )); then
    echo "[$(date -u +%H:%M:%S)] Retention cleanup: removed ${DELETED} backup(s) older than ${RETENTION_DAYS} days"
fi

echo "[$(date -u +%H:%M:%S)] Done. Remember to copy backups off-server!"
