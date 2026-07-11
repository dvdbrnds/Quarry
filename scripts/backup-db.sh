#!/bin/bash
# Run via cron: 0 2 * * * /path/to/backup-db.sh
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups/quarry"
mkdir -p "$BACKUP_DIR"
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U quarry quarry | gzip > "$BACKUP_DIR/quarry_$TIMESTAMP.sql.gz"
# Keep last 30 days
find "$BACKUP_DIR" -name "quarry_*.sql.gz" -mtime +30 -delete
