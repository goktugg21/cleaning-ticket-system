#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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

echo "===== 1. PROD BUILD + UP ====="
FRONTEND_PORT="$FRONTEND_PORT" docker compose -f "$COMPOSE_FILE" up -d --build
ok "Prod containers started"

echo
echo "===== 2. WAIT FOR PROD ENDPOINTS ====="
wait_for_http "Frontend /" "$BASE_URL/" "200" "/tmp/cleaning-ticket-prod-up-frontend.html"
wait_for_http "API /api/auth/me/ without token" "$BASE_URL/api/auth/me/" "401" "/tmp/cleaning-ticket-prod-up-api-me.json"
wait_for_http "Admin login" "$BASE_URL/admin/login/" "200" "/tmp/cleaning-ticket-prod-up-admin.html"

echo
echo "===== 3. SEED PROD DB IDEMPOTENTLY ====="
SEED_OUTPUT="$(docker compose -f "$COMPOSE_FILE" exec -T backend python manage.py shell <<'PYSEED'
from django.utils.text import slugify

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
    if user.role != role:
        user.role = role
        changed = True
    if user.is_staff != is_staff:
        user.is_staff = is_staff
        changed = True
    if user.is_superuser != is_superuser:
        user.is_superuser = is_superuser
        changed = True
    if not user.is_active:
        user.is_active = True
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
    "admin@example.com", "Admin12345!", UserRole.SUPER_ADMIN,
    "Prod Smoke Admin", is_staff=True, is_superuser=True,
)
manager = upsert_user(
    "manager@example.com", "Test12345!", UserRole.BUILDING_MANAGER,
    "Prod Smoke Manager", is_staff=True,
)
customer_user = upsert_user(
    "customer@example.com", "Test12345!", UserRole.CUSTOMER_USER,
    "Prod Smoke Customer",
)

company, _ = Company.objects.get_or_create(
    slug="prod-smoke-co",
    defaults={"name": "Prod Smoke Company", "default_language": "nl", "is_active": True},
)

building, _ = Building.objects.get_or_create(
    company=company,
    name="Prod Smoke Building",
    defaults={"address": "Test Street 1", "city": "Test", "country": "NL", "is_active": True},
)

customer, _ = Customer.objects.get_or_create(
    company=company,
    building=building,
    name="Prod Smoke Customer",
    defaults={"contact_email": "customer@example.com", "language": "nl", "is_active": True},
)

BuildingManagerAssignment.objects.get_or_create(building=building, user=manager)
CustomerUserMembership.objects.get_or_create(customer=customer, user=customer_user)
CompanyUserMembership.objects.get_or_create(company=company, user=manager)

print(f"BUILDING_ID={building.id}")
print(f"CUSTOMER_ID={customer.id}")
print(f"COMPANY_ID={company.id}")
PYSEED
)"

echo "$SEED_OUTPUT"

BUILDING_ID="$(printf '%s\n' "$SEED_OUTPUT" | grep '^BUILDING_ID=' | tail -1 | cut -d= -f2 | tr -d '\r')"
CUSTOMER_ID="$(printf '%s\n' "$SEED_OUTPUT" | grep '^CUSTOMER_ID=' | tail -1 | cut -d= -f2 | tr -d '\r')"

[ -n "$BUILDING_ID" ] || fail "Could not determine BUILDING_ID from seed output"
[ -n "$CUSTOMER_ID" ] || fail "Could not determine CUSTOMER_ID from seed output"
ok "Seed complete: building=$BUILDING_ID customer=$CUSTOMER_ID"

echo
echo "===== 4. RUN ATTACHMENT DOWNLOAD TEST AGAINST PROD ====="
API="http://localhost:${FRONTEND_PORT}/api" \
BUILDING_ID="$BUILDING_ID" \
CUSTOMER_ID="$CUSTOMER_ID" \
"$ROOT_DIR/scripts/attachment_download_test.sh"

echo
echo "======================================"
echo "PRODUCTION UPLOAD/DOWNLOAD TEST PASSED"
echo "Base URL: $BASE_URL"
echo "Building: $BUILDING_ID  Customer: $CUSTOMER_ID"
echo "======================================"
