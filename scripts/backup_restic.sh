#!/usr/bin/env bash
#
# Sprint 134 — off-site, encrypted backup: dumps Postgres and archives the
# backend_media_prod volume (customer contracts, ticket attachments,
# documents, logos, staff credentials — see docs/operations/backups.md
# for the full list of what lives there) into ONE `restic` snapshot.
#
# This is DIFFERENT from scripts/archive/backup_postgres.sh /
# backup_media.sh (which write unencrypted local files under backups/ —
# still fine for a quick pre-migration dump, see docs/engineering/
# backup-restore.md) — this script is the OFF-SITE, ENCRYPTED copy that
# closes the gap described in docs/planning/sprint-checklist.md's
# "Off-site, encrypted backups" NEXT item.
#
# Reads its repository URL and password from /etc/osius-backup.env
# (root-only, deliberately NOT in this repo — see
# scripts/osius-backup.env.example for the variable names, and
# docs/operations/backups.md for how to provision a Hetzner Storage Box
# and fill this file in). Refuses to run without it — no guessed
# credentials, no silent no-op.
#
# Requires the `restic` binary on the host (apt/brew/etc. — see
# docs/operations/backups.md). This is a new dependency beyond the
# `docker compose` / `curl` / `python3` scripts/ops/ standardizes on
# (scripts/ops/README.md) — unavoidable, since an encrypted, deduplicated,
# off-site-native format is exactly what restic exists for and this
# script was asked for BY NAME.
#
# Usage (cron/systemd only — see scripts/systemd/osius-backup-restic.*):
#   ./scripts/backup_restic.sh
#
# To target a different compose file (e.g. staging):
#   COMPOSE_FILE=docker-compose.staging.yml ./scripts/backup_restic.sh
#
# Retention: prunes snapshots older than 30 days on every successful run
# (restic forget --keep-within 30d --prune). This script does NOT restore
# anything — see docs/operations/backups.md for the restore drill.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${OSIUS_BACKUP_ENV_FILE:-/etc/osius-backup.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[FAIL] Backup env file not found: $ENV_FILE" >&2
  echo "Refusing to guess credentials. Provision it first — see" >&2
  echo "docs/operations/backups.md and scripts/osius-backup.env.example." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

for var in RESTIC_REPOSITORY RESTIC_PASSWORD; do
  if [[ -z "${!var:-}" ]]; then
    echo "[FAIL] $var is not set (or empty) in $ENV_FILE." >&2
    exit 1
  fi
done

if ! command -v restic >/dev/null 2>&1; then
  echo "[FAIL] restic is not installed. See docs/operations/backups.md." >&2
  exit 1
fi

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
# A STABLE staging path (not mktemp) — restic diffs a snapshot against its
# parent by path+content, so reusing the same two filenames every run lets
# it dedupe unchanged chunks across nights instead of treating each dump
# as a brand-new, unrelated file.
STAGING_DIR="${STAGING_DIR:-/var/backups/cleaning-ticket/restic-staging}"
mkdir -p "$STAGING_DIR"
PG_DUMP="$STAGING_DIR/postgres.dump"
MEDIA_ARCHIVE="$STAGING_DIR/media.tar.gz"

echo "Compose:     $COMPOSE_FILE"
echo "Staging dir: $STAGING_DIR"
echo "Repository:  $RESTIC_REPOSITORY"

echo "Dumping Postgres..."
docker compose -f "$COMPOSE_FILE" exec -T db sh -c \
  'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "$PG_DUMP"

echo "Archiving media volume..."
docker compose -f "$COMPOSE_FILE" exec -T backend sh -c \
  'mkdir -p /app/media && tar -czf - -C /app media' \
  > "$MEDIA_ARCHIVE"

echo "Verifying archive integrity before it becomes the only off-site copy..."
tar -tzf "$MEDIA_ARCHIVE" >/dev/null

echo "Backing up to restic..."
restic backup "$PG_DUMP" "$MEDIA_ARCHIVE" \
  --tag cleaning-ticket \
  --host "$(hostname)"

echo "Pruning snapshots older than 30 days..."
restic forget --keep-within 30d --prune --tag cleaning-ticket

echo "[OK] Backup complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
