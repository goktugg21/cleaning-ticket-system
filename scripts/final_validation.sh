#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FRONTEND_PORT="${FRONTEND_PORT:-8080}"
RESTORE_FRONTEND_PORT="${RESTORE_FRONTEND_PORT:-18080}"

cleanup_prod() {
  docker compose -f docker-compose.prod.yml down --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup_prod EXIT

echo "======================================"
echo "1. GIT STATUS"
echo "======================================"
git status --short

echo
echo "======================================"
echo "2. SHELL SCRIPT SYNTAX"
echo "======================================"
bash -n scripts/*.sh
echo "[OK] shell script syntax valid"

echo
echo "======================================"
echo "3. PRODUCTION ENV TEMPLATE CHECK"
echo "======================================"
ENV_FILE=.env.production.example ALLOW_PLACEHOLDERS=YES ./scripts/prod_env_check.sh

echo
echo "======================================"
echo "4. FULL DEV CHECK"
echo "======================================"
./scripts/check_all.sh

echo
echo "======================================"
echo "5. PRODUCTION SMOKE TEST"
echo "======================================"
FRONTEND_PORT="$FRONTEND_PORT" ./scripts/prod_smoke_test.sh

echo
echo "======================================"
echo "6. STOP PRODUCTION STACK AFTER SMOKE TEST"
echo "======================================"
cleanup_prod
echo "[OK] production stack stopped"

echo
echo "======================================"
echo "7. PRODUCTION UPLOAD/DOWNLOAD TEST"
echo "======================================"
FRONTEND_PORT="$FRONTEND_PORT" ./scripts/prod_upload_download_test.sh

echo
echo "======================================"
echo "8. STOP PRODUCTION STACK BEFORE RESTORE TEST"
echo "======================================"
cleanup_prod
echo "[OK] production stack stopped"

echo
echo "======================================"
echo "9. PRODUCTION POSTGRES RESTORE TEST"
echo "======================================"
RESTORE_TEST_CONFIRM=YES FRONTEND_PORT="$RESTORE_FRONTEND_PORT" ./scripts/prod_restore_test.sh

echo
echo "======================================"
echo "FINAL VALIDATION PASSED"
echo "======================================"
