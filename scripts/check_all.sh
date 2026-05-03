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
echo "3. MIGRATION DRY RUN CHECK"
echo "======================================"
docker compose run --rm backend python manage.py makemigrations --check --dry-run

echo
echo "======================================"
echo "4. API SMOKE TEST"
echo "======================================"
./scripts/smoke_api_test.sh

echo
echo "======================================"
echo "5. SCOPE ISOLATION TEST"
echo "======================================"
./scripts/scope_isolation_test.sh

echo
echo "======================================"
echo "6. FRONTEND BUILD"
echo "======================================"
cd "$ROOT_DIR/frontend"
npm run build

echo
echo "======================================"
echo "ALL CHECKS PASSED"
echo "======================================"
