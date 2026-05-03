#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_FILE="${1:-}"

if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: $0 backups/postgres/postgres-YYYYMMDD-HHMMSS.dump" >&2
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if [[ "${CONFIRM_RESTORE:-}" != "YES" ]]; then
  echo "Refusing to restore without confirmation." >&2
  echo "Run with: CONFIRM_RESTORE=YES $0 $BACKUP_FILE" >&2
  exit 1
fi

echo "Restoring PostgreSQL backup: $BACKUP_FILE"

cat "$BACKUP_FILE" | docker compose -f "$COMPOSE_FILE" exec -T db sh -c \
  'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

echo "Restore completed."
