#!/usr/bin/env bash
set -euo pipefail

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

json_get_id() {
  python3 -c '
import sys, json
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception:
    print("INVALID_JSON_RESPONSE:", raw, file=sys.stderr)
    raise SystemExit(1)

if "id" not in data:
    print("EXPECTED_ID_MISSING_RESPONSE:", json.dumps(data, indent=2), file=sys.stderr)
    raise SystemExit(1)

print(data["id"])
'
}

echo "===== 1. START LOCAL HTTP DEMO STACK ====="
compose up -d --build
ok "Demo stack started"

echo
echo "===== 2. WAIT FOR DEMO ENDPOINTS ====="
wait_for_http "Frontend /" "$BASE_URL/" "200" "/tmp/cleaning-ticket-demo-frontend.html"
wait_for_http "API /api/auth/me/ without token" "$API/auth/me/" "401" "/tmp/cleaning-ticket-demo-me.json"
wait_for_http "Admin login" "$BASE_URL/admin/login/" "200" "/tmp/cleaning-ticket-demo-admin.html"

echo
echo "===== 3. SEED DEMO USERS AND SCOPE ====="
SEED_OUTPUT="$(compose exec -T backend python manage.py shell <<'PYSEED'
from accounts.models import User, UserRole
from buildings.models import Building, BuildingManagerAssignment
from companies.models import Company, CompanyUserMembership
from customers.models import Customer, CustomerUserMembership


def upsert_user(email, password, role, full_name, is_staff=False, is_superuser=False):
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "username": email,
            "role": role,
            "full_name": full_name,
            "is_staff": is_staff,
            "is_superuser": is_superuser,
            "is_active": True,
        },
    )

    changed = False

    updates = {
        "role": role,
        "full_name": full_name,
        "is_staff": is_staff,
        "is_superuser": is_superuser,
        "is_active": True,
    }

    for field, value in updates.items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            changed = True

    if user.deleted_at is not None:
        user.deleted_at = None
        changed = True

    if changed:
        user.save()

    if created or not user.check_password(password):
        user.set_password(password)
        user.save(update_fields=["password"])

    return user


admin = upsert_user(
    "admin@example.com",
    "Admin12345!",
    UserRole.SUPER_ADMIN,
    "Demo Super Admin",
    is_staff=True,
    is_superuser=True,
)

company_admin = upsert_user(
    "companyadmin@example.com",
    "Test12345!",
    UserRole.COMPANY_ADMIN,
    "Demo Company Admin",
    is_staff=True,
)

manager = upsert_user(
    "manager@example.com",
    "Test12345!",
    UserRole.BUILDING_MANAGER,
    "Demo Building Manager",
    is_staff=True,
)

customer_user = upsert_user(
    "customer@example.com",
    "Test12345!",
    UserRole.CUSTOMER_USER,
    "Demo Customer User",
)

company, _ = Company.objects.get_or_create(
    slug="demo-cleaning-company",
    defaults={
        "name": "Demo Cleaning Company",
        "default_language": "nl",
        "is_active": True,
    },
)

building, _ = Building.objects.get_or_create(
    company=company,
    name="Demo Building",
    defaults={
        "address": "Demo Street 1",
        "city": "Amsterdam",
        "country": "NL",
        "is_active": True,
    },
)

customer, _ = Customer.objects.get_or_create(
    company=company,
    building=building,
    name="Demo Customer",
    defaults={
        "contact_email": "customer@example.com",
        "language": "nl",
        "is_active": True,
    },
)

CompanyUserMembership.objects.get_or_create(company=company, user=company_admin)
CompanyUserMembership.objects.get_or_create(company=company, user=manager)
BuildingManagerAssignment.objects.get_or_create(building=building, user=manager)
CustomerUserMembership.objects.get_or_create(customer=customer, user=customer_user)

print(f"COMPANY_ID={company.id}")
print(f"BUILDING_ID={building.id}")
print(f"CUSTOMER_ID={customer.id}")
PYSEED
)"

echo "$SEED_OUTPUT"

BUILDING_ID="$(printf '%s\n' "$SEED_OUTPUT" | grep '^BUILDING_ID=' | tail -1 | cut -d= -f2 | tr -d '\r')"
CUSTOMER_ID="$(printf '%s\n' "$SEED_OUTPUT" | grep '^CUSTOMER_ID=' | tail -1 | cut -d= -f2 | tr -d '\r')"

[[ -n "$BUILDING_ID" ]] || fail "BUILDING_ID not found"
[[ -n "$CUSTOMER_ID" ]] || fail "CUSTOMER_ID not found"

ok "Demo scope ready: building=$BUILDING_ID customer=$CUSTOMER_ID"

echo
echo "===== 4. CREATE DEMO TICKET ====="
CUSTOMER_TOKEN="$(login customer@example.com 'Test12345!')"

CREATE_RESP="$(curl -sS -X POST "$API/tickets/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"title\":\"Demo cleaning request\",
    \"description\":\"This is a demo ticket created by scripts/demo_up.sh.\",
    \"room_label\":\"Demo Room 101\",
    \"type\":\"REPORT\",
    \"priority\":\"NORMAL\",
    \"building\":$BUILDING_ID,
    \"customer\":$CUSTOMER_ID
  }")"

TICKET_ID="$(printf '%s' "$CREATE_RESP" | json_get_id)"
ok "Demo ticket created id=$TICKET_ID"

echo
echo "======================================"
echo "LOCAL HTTP DEMO READY"
echo "======================================"
echo "URL:"
echo "  $BASE_URL"
echo
echo "Demo users:"
echo "  Super admin:    admin@example.com        / Admin12345!"
echo "  Company admin:  companyadmin@example.com / Test12345!"
echo "  Manager:        manager@example.com      / Test12345!"
echo "  Customer:       customer@example.com     / Test12345!"
echo
echo "Demo ticket id:"
echo "  $TICKET_ID"
echo
echo "Stop demo stack:"
echo "  ./scripts/demo_down.sh"
echo "======================================"
