#!/usr/bin/env bash
# Sprint 24E — Tier 2 (Focused) backend verification.
#
# Runs a subset of the Django test suite that's relevant to the
# sprint/area you're touching, instead of the full ~385-test
# regression. Pass one or more Django test labels OR pass no args to
# default to the most recent sprint suites.
#
# Examples:
#   ./scripts/verify_backend_focused.sh accounts.tests
#   ./scripts/verify_backend_focused.sh tickets.tests.test_sprint24d_atomic_transitions
#   ./scripts/verify_backend_focused.sh                 # → default sprint set
#
# Negative-path tests emit
#   `WARNING django.request: Bad Request: ...`
#   `WARNING django.request: Forbidden: ...`
#   `WARNING django.request: Not Found: ...`
# from Django's request handler when they assert 400/403/404. These
# are EXPECTED and are not test failures — only the final line
# (`OK` / `FAILED (errors=...)`) indicates the result.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Default focused set — keep this list short. Most recent sprint
# tests + the cross-sprint state-machine + scoping suites. Update
# when a new sprint test file lands.
DEFAULT_LABELS=(
  "tickets.tests.test_sprint24b_review_note"
  "tickets.tests.test_sprint24c_staff_cancel"
  "tickets.tests.test_sprint24d_atomic_transitions"
  "accounts.tests.test_sprint23a_foundation"
  "accounts.tests.test_sprint24a_staff_management"
  "customers.tests.test_sprint23c_access_role_editor"
)

if [[ $# -gt 0 ]]; then
  LABELS=("$@")
else
  LABELS=("${DEFAULT_LABELS[@]}")
fi

echo "[focused backend] running: ${LABELS[*]}"
docker compose exec -T backend python manage.py test \
  --noinput \
  --verbosity=1 \
  "${LABELS[@]}"

echo
echo "[OK] Tier 2 focused backend tests passed."
echo "Note: 'WARNING django.request: ...' lines from negative-path tests"
echo "are expected. Only OK / FAILED on the last line determines result."
