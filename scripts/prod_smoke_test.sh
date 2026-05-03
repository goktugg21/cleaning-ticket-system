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

wait_for_http() {
  local label="$1"
  local url="$2"
  local expected="$3"
  local output_file="$4"

  local code="000"

  for attempt in $(seq 1 30); do
    code="$(curl -sS -o "$output_file" -w "%{http_code}" "$url" || true)"

    if [[ "$code" == "$expected" ]]; then
      ok "$label returns $expected"
      return 0
    fi

    echo "[WAIT] $label expected HTTP $expected, got $code (attempt $attempt/30)"
    sleep 2
  done

  fail "$label expected HTTP $expected, got $code"
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
wait_for_http "Frontend /" "$BASE_URL/" "200" "/tmp/cleaning-ticket-prod-frontend.html"
wait_for_http "API /api/auth/me/ without token" "$BASE_URL/api/auth/me/" "401" "/tmp/cleaning-ticket-prod-api-me.json"
wait_for_http "Admin login" "$BASE_URL/admin/login/" "200" "/tmp/cleaning-ticket-prod-admin.html"

echo
echo "===== 6. SECURITY HEADER CHECKS ====="
HEADERS="$(curl -sSI "$BASE_URL/")"

echo "$HEADERS" | grep -qi '^X-Content-Type-Options: nosniff' || fail "Missing X-Content-Type-Options header"
ok "X-Content-Type-Options header exists"

echo "$HEADERS" | grep -qi '^X-Frame-Options: SAMEORIGIN' || fail "Missing X-Frame-Options header"
ok "X-Frame-Options header exists"

echo "$HEADERS" | grep -qi '^Referrer-Policy: strict-origin-when-cross-origin' || fail "Missing Referrer-Policy header"
ok "Referrer-Policy header exists"

echo "$HEADERS" | grep -qi '^Permissions-Policy:' || fail "Missing Permissions-Policy header"
ok "Permissions-Policy header exists"

echo
echo "======================================"
echo "PRODUCTION SMOKE TEST PASSED"
echo "Base URL: $BASE_URL"
echo "======================================"
