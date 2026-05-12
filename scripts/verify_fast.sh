#!/usr/bin/env bash
# Sprint 24E — Tier 1 (Fast) verification.
#
# Cheapest, no-tests sanity check (~30 seconds total). Runs:
#   1. backend Django system check
#   2. backend `makemigrations --check --dry-run`
#   3. frontend `tsc --noEmit` against tsconfig.app.json
#
# Intended cadence: every save / before every push. Does NOT run any
# test suite — that's Tier 2+. If this passes, the next ladder rung is
# `scripts/verify_focused.sh` (Tier 2) for sprint-touched work.
#
# Requires the dev docker compose stack to be up (`docker compose up
# -d`) so the backend container is reachable. Frontend tsc runs
# against the local node_modules.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/3] backend manage.py check ..."
docker compose exec -T backend python manage.py check

echo "[2/3] backend makemigrations --check --dry-run ..."
docker compose exec -T backend python manage.py makemigrations --check --dry-run

echo "[3/3] frontend tsc --noEmit ..."
cd "$ROOT_DIR/frontend"
# Call the TypeScript compiler directly via node so the check works
# from any shell on any host. `npm run typecheck` would shell out to
# `cmd.exe` on Windows UNC paths and fail with "UNC paths are not
# supported"; the direct node invocation has no shell layer.
node ./node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json

echo
echo "[OK] Tier 1 (fast) verification passed."
echo "Next rung when relevant:"
echo "  scripts/verify_backend_focused.sh <sprint-app-or-pattern>"
echo "  scripts/verify_focused.sh         (fast + build + sprint backend tests)"
echo "  scripts/check_all.sh              (Tier 4 full — pre-merge)"
