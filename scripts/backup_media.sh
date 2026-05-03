#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-backups/media}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
OUTPUT_FILE="/backup/media-$TIMESTAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "Creating media backup: $BACKUP_DIR/media-$TIMESTAMP.tar.gz"

docker compose -f "$COMPOSE_FILE" run --rm --no-deps \
  -v "$(pwd)/$BACKUP_DIR:/backup" \
  backend sh -c "tar -czf '$OUTPUT_FILE' -C /app/media ."

echo "Media backup completed: $BACKUP_DIR/media-$TIMESTAMP.tar.gz"
