#!/usr/bin/env bash
#
# Thin wrapper around scripts/backup_postgres.sh that:
#   - defaults COMPOSE_FILE to docker-compose.prod.yml
#   - prints the resulting dump filename and size
#   - does NOT prune (that's the operator's cron decision)
#
# Use from cron OR ad-hoc:
#   ./scripts/ops/pg_backup.sh
#
# To override:
#   COMPOSE_FILE=docker-compose.staging.yml \
#   BACKUP_DIR=/var/backups/cleaning-ticket/postgres \
#     ./scripts/ops/pg_backup.sh

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
export BACKUP_DIR="${BACKUP_DIR:-backups/postgres}"

echo "Repo:        $REPO_ROOT"
echo "Compose:     $COMPOSE_FILE"
echo "Backup dir:  $BACKUP_DIR"

before_count="$(ls -1 "$BACKUP_DIR" 2>/dev/null | wc -l || echo 0)"

./scripts/backup_postgres.sh

after_count="$(ls -1 "$BACKUP_DIR" 2>/dev/null | wc -l || echo 0)"

if (( after_count <= before_count )); then
  echo "[FAIL] Dump count did not increase (was $before_count, now $after_count)." >&2
  exit 1
fi

latest="$(ls -1t "$BACKUP_DIR"/postgres-*.dump 2>/dev/null | head -1)"
size="$(du -h "$latest" | cut -f1)"
echo
echo "[OK] New dump: $latest ($size)"
