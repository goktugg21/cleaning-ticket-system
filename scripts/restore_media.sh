#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: $0 backups/media/media-YYYYMMDD-HHMMSS.tar.gz" >&2
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Media backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if [[ "${CONFIRM_RESTORE:-}" != "YES" ]]; then
  echo "Refusing to restore media without confirmation." >&2
  echo "Run with: CONFIRM_RESTORE=YES $0 $BACKUP_FILE" >&2
  exit 1
fi

echo "Validating media backup: $BACKUP_FILE"
tar -tzf "$BACKUP_FILE" >/dev/null

echo "Restoring media backup: $BACKUP_FILE"

cat "$BACKUP_FILE" | docker compose -f "$COMPOSE_FILE" exec -T backend sh -c '
  set -e
  mkdir -p /app/media
  find /app/media -mindepth 1 -delete
  tar -xzf - -C /app
'

echo "Media restore completed."
