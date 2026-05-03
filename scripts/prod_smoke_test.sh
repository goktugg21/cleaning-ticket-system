#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
BASE_URL="http://localhost:${FRONTEND_PORT}"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

ok() {
  echo "[OK] $*"
}

echo "===== 1. PROD COMPOSE CONFIG ====="
FRONTEND_PORT="$FRONTEND_PORT" docker compose -f "$COMPOSE_FILE" config >/tmp/cleaning-ticket-prod-compose.yml
ok "Prod compose config valid"

echo
echo "===== 2. PROD BUILD + UP ====="
FRONTEND_PORT="$FRONTEND_PORT" docker compose -f "$COMPOSE_FILE" up -d --build
ok "Prod containers started"

echo
echo "===== 3. PROD CONTAINERS ====="
docker compose -f "$COMPOSE_FILE" ps

echo
echo "===== 4. BACKEND CHECKS ====="
docker compose -f "$COMPOSE_FILE" exec -T backend python manage.py check
docker compose -f "$COMPOSE_FILE" exec -T backend python manage.py makemigrations --check --dry-run
ok "Backend checks passed"

echo
echo "===== 5. HTTP CHECKS ====="
FRONTEND_HTTP="$(curl -sS -o /tmp/prod_frontend.html -w "%{http_code}" "$BASE_URL/")"
[[ "$FRONTEND_HTTP" == "200" ]] || fail "Frontend expected HTTP 200, got $FRONTEND_HTTP"
ok "Frontend / returns 200"

API_ME_HTTP="$(curl -sS -o /tmp/prod_api_me.json -w "%{http_code}" "$BASE_URL/api/auth/me/")"
[[ "$API_ME_HTTP" == "401" ]] || fail "API /api/auth/me/ expected HTTP 401 without token, got $API_ME_HTTP"
ok "API auth/me returns 401 without token"

ADMIN_HTTP="$(curl -sS -o /tmp/prod_admin.html -w "%{http_code}" "$BASE_URL/admin/login/")"
[[ "$ADMIN_HTTP" == "200" ]] || fail "Admin login expected HTTP 200, got $ADMIN_HTTP"
ok "Admin login returns 200"

echo
echo "======================================"
echo "PRODUCTION SMOKE TEST PASSED"
echo "Base URL: $BASE_URL"
echo "======================================"
