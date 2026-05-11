#!/usr/bin/env bash
set -euo pipefail

# Sprint 21: this script now delegates seeding to the canonical
# `seed_demo_data` management command, which provisions two demo
# companies (Osius Demo + Bright Facilities). Previously this file
# inlined a one-off Python shell that created `admin@example.com` and
# friends — those accounts caused naming/password drift versus the
# rest of the demo stack. The pilot-readiness guard
# (`check_no_demo_accounts`) still rejects both the old and the new
# demo emails, so an older clone of this script can't silently leak
# admin credentials into a pilot host.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
BASE_URL="http://localhost:${FRONTEND_PORT}"
API="${BASE_URL}/api"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

ok() {
  echo "[OK] $*"
}

compose() {
  FRONTEND_PORT="$FRONTEND_PORT" docker compose -f "$COMPOSE_FILE" "$@"
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

login() {
  local email="$1"
  local password="$2"

  curl -sS -X POST "$API/auth/token/" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$email\",\"password\":\"$password\"}" \
  | python3 -c '
import sys, json
data = json.load(sys.stdin)
if "access" not in data:
    print("LOGIN_FAILED:", data, file=sys.stderr)
    raise SystemExit(1)
print(data["access"])
'
}

echo "===== 1. START LOCAL HTTP DEMO STACK ====="
compose up -d --build
ok "Demo stack started"

echo
echo "===== 2. WAIT FOR DEMO ENDPOINTS ====="
wait_for_http "Frontend /" "$BASE_URL/" "200" "/tmp/cleaning-ticket-demo-frontend.html"
wait_for_http "API /api/auth/me/ without token" "$API/auth/me/" "401" "/tmp/cleaning-ticket-demo-me.json"
wait_for_http "Admin login" "$BASE_URL/django-admin/login/" "200" "/tmp/cleaning-ticket-demo-admin.html"

echo
echo "===== 3. SEED CANONICAL TWO-COMPANY DEMO ====="
# --i-know-this-is-not-prod is required because docker-compose.prod.yml
# runs the backend with DJANGO_DEBUG=False. The flag does not bypass
# the pilot-launch guard (check_no_demo_accounts) — it only allows the
# seed itself to run on a non-DEBUG settings tree. A real pilot host
# never runs this script.
compose exec -T backend python manage.py seed_demo_data --i-know-this-is-not-prod
ok "seed_demo_data complete"

echo
echo "===== 4. VERIFY DEMO LOGIN ====="
SUPER_TOKEN="$(login superadmin@cleanops.demo 'Demo12345!')"
[[ -n "$SUPER_TOKEN" ]] || fail "superadmin@cleanops.demo login failed"
ok "superadmin@cleanops.demo can log in"

ADMIN_A_TOKEN="$(login ramazan-admin-osius@b-amsterdam.demo 'Demo12345!')"
[[ -n "$ADMIN_A_TOKEN" ]] || fail "Osius admin (Company A) login failed"
ok "ramazan-admin-osius@b-amsterdam.demo (Company A) can log in"

ADMIN_B_TOKEN="$(login sophie-admin-bright@bright-facilities.demo 'Demo12345!')"
[[ -n "$ADMIN_B_TOKEN" ]] || fail "Bright admin (Company B) login failed"
ok "sophie-admin-bright@bright-facilities.demo (Company B) can log in"

echo
echo "======================================"
echo "LOCAL HTTP DEMO READY"
echo "======================================"
echo "URL:"
echo "  $BASE_URL"
echo
echo "Demo password (all accounts): Demo12345!"
echo
echo "Super admin (both companies):"
echo "  superadmin@cleanops.demo"
echo
echo "Company A — Osius Demo (Amsterdam B1/B2/B3 / customer B Amsterdam):"
echo "  ramazan-admin-osius@b-amsterdam.demo            COMPANY_ADMIN"
echo "  gokhan-manager-osius@b-amsterdam.demo           BUILDING_MANAGER  B1/B2/B3"
echo "  murat-manager-osius@b-amsterdam.demo            BUILDING_MANAGER  B1"
echo "  isa-manager-osius@b-amsterdam.demo              BUILDING_MANAGER  B2"
echo "  tom-customer-b-amsterdam@b-amsterdam.demo       CUSTOMER_USER     B1/B2/B3"
echo "  iris-customer-b-amsterdam@b-amsterdam.demo      CUSTOMER_USER     B1/B2"
echo "  amanda-customer-b-amsterdam@b-amsterdam.demo    CUSTOMER_USER     B3"
echo
echo "Company B — Bright Facilities (Rotterdam R1/R2):"
echo "  sophie-admin-bright@bright-facilities.demo      COMPANY_ADMIN"
echo "  bram-manager-bright@bright-facilities.demo      BUILDING_MANAGER  R1/R2"
echo "  lotte-customer-bright@bright-facilities.demo    CUSTOMER_USER     R1/R2"
echo
echo "Stop demo stack:"
echo "  ./scripts/demo_down.sh"
echo "======================================"
