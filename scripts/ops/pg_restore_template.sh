#!/usr/bin/env bash
#
# DRY-RUN HELPER. This script does NOT restore anything by itself.
# It prints the exact command the operator should paste into their
# shell after they have:
#
#   1. confirmed the destination compose stack is correct
#      (production vs staging — restoring into the wrong one is
#      hard to undo);
#   2. paused user-facing traffic if restoring production;
#   3. confirmed the dump file matches the application schema /
#      migration version they want.
#
# Usage:
#   ./scripts/ops/pg_restore_template.sh                       # latest dump
#   ./scripts/ops/pg_restore_template.sh path/to/postgres-*.dump
#   COMPOSE_FILE=docker-compose.staging.yml ./scripts/ops/pg_restore_template.sh
#
# The script ONLY prints. To actually run the restore, copy the
# printed line and execute it yourself.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-backups/postgres}"

DUMP="${1:-}"
if [[ -z "$DUMP" ]]; then
  DUMP="$(ls -1t "$BACKUP_DIR"/postgres-*.dump 2>/dev/null | head -1 || true)"
  if [[ -z "$DUMP" ]]; then
    echo "No dump found in $BACKUP_DIR. Pass an explicit path." >&2
    exit 2
  fi
fi

if [[ ! -f "$DUMP" ]]; then
  echo "Dump not found: $DUMP" >&2
  exit 2
fi

cat <<EOF
# ============================================================
#  Postgres restore — DRY RUN, COPY THE LINE BELOW TO RUN IT
# ============================================================
#
# Compose:  $COMPOSE_FILE
# Dump:     $DUMP
# Size:     $(du -h "$DUMP" | cut -f1)
# Modified: $(stat -c '%y' "$DUMP" 2>/dev/null || stat -f '%Sm' "$DUMP")
#
# Pre-flight (do these BEFORE pasting the command):
#   - Stop user-facing services if you are restoring production:
#       docker compose -f $COMPOSE_FILE stop backend worker beat
#   - Confirm you are pointing at the stack you intend to write
#     to. If you copied this template into a staging compose
#     file, set COMPOSE_FILE accordingly before running.
#   - Make sure no other operator is in mid-deploy.
#
# Command:

CONFIRM_RESTORE=YES \\
COMPOSE_FILE=$COMPOSE_FILE \\
  ./scripts/restore_postgres.sh \\
  $DUMP

# After:
#   docker compose -f $COMPOSE_FILE start backend worker beat
#   ./scripts/ops/prod_health.sh <your-public-domain>
EOF
