#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-backups/postgres}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT_FILE="$BACKUP_DIR/postgres-$TIMESTAMP.dump"

mkdir -p "$BACKUP_DIR"

echo "Creating PostgreSQL backup: $OUTPUT_FILE"

docker compose -f "$COMPOSE_FILE" exec -T db sh -c \
  'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$OUTPUT_FILE"

echo "Backup completed: $OUTPUT_FILE"
