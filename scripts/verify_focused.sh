#!/usr/bin/env bash
# Sprint 24E — Tier 2 (Focused) PR verification.
#
# What every small PR should pass before requesting review:
#   1. backend system check + makemigrations dry-run + frontend tsc
#      (delegated to scripts/verify_fast.sh)
#   2. backend focused test labels — default is the recent-sprint set
#      from scripts/verify_backend_focused.sh; override with
#      VERIFY_BACKEND_LABELS="<space-separated labels>"
#   3. frontend `npm run build` (tsc -b && vite build)
#
# Does NOT run Playwright. That's Tier 3 (smoke) / Tier 4 (full).
# Smoke Playwright:
#   PLAYWRIGHT_BASE_URL=http://localhost:5173 \
#     npm --prefix frontend run test:e2e:smoke
# Full Playwright (local):
#   PLAYWRIGHT_BASE_URL=http://localhost:5173 \
#     npm --prefix frontend run test:e2e
# Full Playwright (CI): trigger the `playwright` workflow manually
# from the Actions tab, or wait for the nightly schedule.
#
# Negative-path tests emit expected
#   `WARNING django.request: Bad Request | Forbidden | Not Found`
# lines from Django's request handler — those are not failures.
# Only the final OK / FAILED line determines the result.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "===== [1/3] Tier 1 fast checks ====="
"$ROOT_DIR/scripts/verify_fast.sh"

echo
echo "===== [2/3] Focused backend tests ====="
if [[ -n "${VERIFY_BACKEND_LABELS:-}" ]]; then
  # Word-split the env var so callers can pass multiple labels.
  # shellcheck disable=SC2086
  "$ROOT_DIR/scripts/verify_backend_focused.sh" ${VERIFY_BACKEND_LABELS}
else
  "$ROOT_DIR/scripts/verify_backend_focused.sh"
fi

echo
echo "===== [3/3] Frontend build (tsc + vite) ====="
cd "$ROOT_DIR/frontend"
npm run build

echo
echo "[OK] Tier 2 focused PR verification passed."
echo "Optional next rungs:"
echo "  npm --prefix frontend run test:e2e:smoke   (Tier 3 smoke Playwright, ~5 min)"
echo "  scripts/check_all.sh                       (Tier 4 full, pre-merge)"
echo "  Actions → 'playwright' workflow_dispatch   (Tier 4 full in CI, no local cost)"
