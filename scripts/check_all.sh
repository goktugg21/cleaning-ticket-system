#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

echo "======================================"
echo "1. GIT STATUS"
echo "======================================"
git status --short

echo
echo "======================================"
echo "2. BACKEND DJANGO CHECK"
echo "======================================"
docker compose exec backend python manage.py check

echo
echo "======================================"
echo "3. BACKEND TEST SUITE"
echo "======================================"
docker compose exec backend python manage.py test

echo
echo "======================================"
echo "4. PRODUCTION SETTINGS CHECK"
echo "======================================"
docker compose exec backend python manage.py check --deploy --fail-level ERROR

echo
echo "======================================"
echo "5. MIGRATION DRY RUN CHECK"
echo "======================================"
docker compose run --rm backend python manage.py makemigrations --check --dry-run

echo
echo "======================================"
echo "6. API SMOKE TEST"
echo "======================================"
"$ROOT_DIR/scripts/smoke_api_test.sh"

echo
echo "======================================"
echo "7. SCOPE ISOLATION TEST"
echo "======================================"
"$ROOT_DIR/scripts/scope_isolation_test.sh"

echo
echo "======================================"
echo "8. ATTACHMENT API TEST"
echo "======================================"
"$ROOT_DIR/scripts/attachment_api_test.sh"

echo
echo "======================================"
echo "9. ATTACHMENT DOWNLOAD TEST"
echo "======================================"
"$ROOT_DIR/scripts/attachment_download_test.sh"

echo
echo "======================================"
echo "10. ATTACHMENT FILE TYPE TEST"
echo "======================================"
"$ROOT_DIR/scripts/attachment_file_type_test.sh"

echo
echo "======================================"
echo "11. ASSIGNMENT API TEST"
echo "======================================"
"$ROOT_DIR/scripts/assignment_api_test.sh"

echo
echo "======================================"
echo "12. FRONTEND BUILD"
echo "======================================"
cd "$ROOT_DIR/frontend"
npm run build

echo
echo "======================================"
echo "ALL CHECKS PASSED"
echo "======================================"
