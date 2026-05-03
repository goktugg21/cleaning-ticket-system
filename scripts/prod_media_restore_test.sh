#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PROJECT_NAME="${PROJECT_NAME:-cleaning-ticket-prod-media-restore-test}"
FRONTEND_PORT="${FRONTEND_PORT:-18081}"
BACKUP_DIR="${BACKUP_DIR:-backups/media/restore-test}"
MARKER="media-restore-test-$(date +%Y%m%d%H%M%S)"
MARKER_DIR="/app/media/restore-test"
MARKER_FILE="$MARKER_DIR/$MARKER.txt"
MARKER_CONTENT="marker=$MARKER"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

ok() {
  echo "[OK] $*"
}

compose() {
  FRONTEND_PORT="$FRONTEND_PORT" docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  if [[ "${KEEP_MEDIA_RESTORE_TEST_STACK:-}" == "YES" ]]; then
    echo "[INFO] Keeping media restore test stack because KEEP_MEDIA_RESTORE_TEST_STACK=YES"
    return 0
  fi

  echo
  echo "===== CLEANUP MEDIA RESTORE TEST STACK ====="
  compose down -v --remove-orphans || true
}

trap cleanup EXIT

if [[ "${MEDIA_RESTORE_TEST_CONFIRM:-}" != "YES" ]]; then
  fail "Refusing to run media restore test without confirmation. Run with: MEDIA_RESTORE_TEST_CONFIRM=YES $0"
fi

echo "===== 1. CLEAN OLD MEDIA RESTORE TEST PROJECT ====="
compose down -v --remove-orphans >/dev/null 2>&1 || true
ok "Old media restore test project cleaned"

existing_containers="$(docker ps -a --filter "name=^/cleaning_ticket_prod_" --format "{{.Names}}" || true)"
if [[ -n "$existing_containers" ]]; then
  echo "$existing_containers"
  fail "Production-named containers exist. Run: docker compose -f docker-compose.prod.yml down"
fi

echo
echo "===== 2. START CLEAN TEST STACK ====="
compose up -d --build backend
ok "Media restore test stack started"

echo
echo "===== 3. BACKEND CHECK ====="
compose exec -T backend python manage.py check >/tmp/cleaning-ticket-media-restore-check.txt
cat /tmp/cleaning-ticket-media-restore-check.txt
ok "Backend check passed"

echo
echo "===== 4. CREATE MARKER MEDIA FILE ====="
compose exec -T backend sh -c "
  set -e
  mkdir -p '$MARKER_DIR'
  printf '%s\n' '$MARKER_CONTENT' > '$MARKER_FILE'
  test -f '$MARKER_FILE'
"
ok "Marker media file created: $MARKER_FILE"

echo
echo "===== 5. CREATE MEDIA BACKUP ====="
BACKUP_DIR="$BACKUP_DIR" COMPOSE_FILE="$COMPOSE_FILE" ./scripts/backup_media.sh

BACKUP_FILE="$(find "$BACKUP_DIR" -type f -name 'media-*.tar.gz' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)"
[[ -n "$BACKUP_FILE" ]] || fail "Backup file not found in $BACKUP_DIR"

ls -lh "$BACKUP_FILE"
ok "Media backup created: $BACKUP_FILE"

echo
echo "===== 6. VALIDATE BACKUP CONTAINS MARKER ====="
tar -tzf "$BACKUP_FILE" | grep -F "media/restore-test/$MARKER.txt" >/dev/null || fail "Marker file not found in backup archive"
ok "Marker exists inside backup archive"

echo
echo "===== 7. WIPE MEDIA VOLUME ====="
compose exec -T backend sh -c "
  set -e
  find /app/media -mindepth 1 -delete
  test ! -f '$MARKER_FILE'
"
ok "Media volume wiped"

echo
echo "===== 8. RESTORE MEDIA BACKUP ====="
CONFIRM_RESTORE=YES COMPOSE_FILE="$COMPOSE_FILE" ./scripts/restore_media.sh "$BACKUP_FILE"
ok "Media backup restored"

echo
echo "===== 9. VERIFY RESTORED MARKER ====="
RESTORED_CONTENT="$(compose exec -T backend sh -c "cat '$MARKER_FILE'")"
[[ "$RESTORED_CONTENT" == "$MARKER_CONTENT" ]] || fail "Restored marker content mismatch"
ok "Restored marker verified"

echo
echo "======================================"
echo "PRODUCTION MEDIA RESTORE TEST PASSED"
echo "Project: $PROJECT_NAME"
echo "Backup: $BACKUP_FILE"
echo "Marker: $MARKER"
echo "======================================"
