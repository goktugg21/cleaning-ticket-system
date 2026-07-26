#!/usr/bin/env bash
# ARCHIVED — pilot-era one-off (2026-05-03). Not maintained. Do not run against
# any live environment without reading it first.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-backups/media}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT_FILE="$BACKUP_DIR/media-$TIMESTAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "Creating media backup: $OUTPUT_FILE"

docker compose -f "$COMPOSE_FILE" exec -T backend sh -c \
  'mkdir -p /app/media && tar -czf - -C /app media' \
  > "$OUTPUT_FILE"

tar -tzf "$OUTPUT_FILE" >/dev/null

echo "Media backup completed: $OUTPUT_FILE"
