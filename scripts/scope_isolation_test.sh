#!/usr/bin/env bash
set -euo pipefail

API="http://localhost:8000/api"
PASSWORD="Test12345!"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

ok() {
  echo "[OK] $*"
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

contains_ticket() {
  local token="$1"
  local ticket_id="$2"

  curl -sS "$API/tickets/" \
    -H "Authorization: Bearer $token" \
  | python3 -c "
import sys, json
data = json.load(sys.stdin)
ticket_id = int('$ticket_id')
items = data.get('results', [])
print('YES' if any(item.get('id') == ticket_id for item in items) else 'NO')
"
}

detail_status() {
  local token="$1"
  local ticket_id="$2"

  curl -sS -o /tmp/scope_detail_response.json -w "%{http_code}" \
    "$API/tickets/$ticket_id/" \
    -H "Authorization: Bearer $token"
}

create_cross_scope_status() {
  local token="$1"
  local building_id="$2"
  local customer_id="$3"

  curl -sS -o /tmp/scope_create_response.json -w "%{http_code}" \
    -X POST "$API/tickets/" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "{
      \"title\":\"Cross-scope forbidden ticket\",
      \"description\":\"This should not be allowed.\",
      \"room_label\":\"Forbidden Room\",
      \"type\":\"REPORT\",
      \"priority\":\"NORMAL\",
      \"building\":$building_id,
      \"customer\":$customer_id
    }"
}

echo "===== 1. ENSURE BACKEND IS RUNNING ====="
docker compose up -d backend >/dev/null
docker compose exec -T backend python manage.py check >/dev/null
ok "Backend çalışıyor"

echo
echo "===== 2. SEED SECOND COMPANY SCOPE ====="
SEED_JSON=$(
docker compose exec -T backend python manage.py shell <<'PY' | tail -n 1
import json
from accounts.models import User, UserRole
from companies.models import Company, CompanyUserMembership
from buildings.models import Building, BuildingManagerAssignment
from customers.models import Customer, CustomerUserMembership
from tickets.models import Ticket

PASSWORD = "Test12345!"

def make_user(email, role, full_name):
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={
            "role": role,
            "full_name": full_name,
            "language": "nl",
            "is_active": True,
        },
    )
    user.role = role
    user.full_name = full_name
    user.language = "nl"
    user.is_active = True
    user.deleted_at = None
    user.set_password(PASSWORD)
    user.save()
    return user

company2, _ = Company.objects.get_or_create(
    slug="scope-isolation-company",
    defaults={
        "name": "Scope Isolation Company",
        "default_language": "nl",
        "is_active": True,
    },
)
company2.name = "Scope Isolation Company"
company2.default_language = "nl"
company2.is_active = True
company2.save()

building2, _ = Building.objects.get_or_create(
    company=company2,
    name="Scope Isolation Building",
    defaults={
        "address": "Isolation Street 2",
        "city": "Rotterdam",
        "country": "Netherlands",
        "postal_code": "2000 AA",
        "is_active": True,
    },
)
building2.address = "Isolation Street 2"
building2.city = "Rotterdam"
building2.country = "Netherlands"
building2.postal_code = "2000 AA"
building2.is_active = True
building2.save()

customer2, _ = Customer.objects.get_or_create(
    company=company2,
    building=building2,
    name="Scope Isolation Customer",
    defaults={
        "contact_email": "scope-customer@example.com",
        "phone": "",
        "language": "nl",
        "is_active": True,
    },
)
customer2.contact_email = "scope-customer@example.com"
customer2.language = "nl"
customer2.is_active = True
customer2.save()

company_admin2 = make_user(
    "companyadmin2@example.com",
    UserRole.COMPANY_ADMIN,
    "Scope Company Admin",
)
manager2 = make_user(
    "manager2@example.com",
    UserRole.BUILDING_MANAGER,
    "Scope Building Manager",
)
customer_user2 = make_user(
    "customer2@example.com",
    UserRole.CUSTOMER_USER,
    "Scope Customer User",
)

CompanyUserMembership.objects.get_or_create(user=company_admin2, company=company2)
BuildingManagerAssignment.objects.get_or_create(user=manager2, building=building2)
CustomerUserMembership.objects.get_or_create(user=customer_user2, customer=customer2)

ticket2 = Ticket.objects.create(
    company=company2,
    building=building2,
    customer=customer2,
    created_by=customer_user2,
    title="Scope isolation foreign ticket",
    description="This ticket belongs only to company 2 / customer 2.",
    room_label="Isolation Room",
    type="REPORT",
    priority="NORMAL",
    status="OPEN",
)

print(json.dumps({
    "company2_id": company2.id,
    "building2_id": building2.id,
    "customer2_id": customer2.id,
    "ticket2_id": ticket2.id,
}))
PY
)

COMPANY2_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["company2_id"])' "$SEED_JSON")
BUILDING2_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["building2_id"])' "$SEED_JSON")
CUSTOMER2_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["customer2_id"])' "$SEED_JSON")
FOREIGN_TICKET_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["ticket2_id"])' "$SEED_JSON")

ok "Company2=$COMPANY2_ID Building2=$BUILDING2_ID Customer2=$CUSTOMER2_ID Ticket2=$FOREIGN_TICKET_ID"

echo
echo "===== 3. LOGIN USERS ====="
ADMIN_TOKEN=$(login admin@example.com 'Admin12345!')
COMPANY1_TOKEN=$(login companyadmin@example.com "$PASSWORD")
MANAGER1_TOKEN=$(login manager@example.com "$PASSWORD")
CUSTOMER1_TOKEN=$(login customer@example.com "$PASSWORD")

COMPANY2_TOKEN=$(login companyadmin2@example.com "$PASSWORD")
MANAGER2_TOKEN=$(login manager2@example.com "$PASSWORD")
CUSTOMER2_TOKEN=$(login customer2@example.com "$PASSWORD")

ok "Tüm kullanıcılar login oldu"

echo
echo "===== 4. ADMIN CAN SEE FOREIGN TICKET ====="
STATUS=$(detail_status "$ADMIN_TOKEN" "$FOREIGN_TICKET_ID")
[[ "$STATUS" == "200" ]] || fail "Admin foreign ticket detail göremedi. HTTP=$STATUS"
ok "Admin Company2 ticket detail görebiliyor"

echo
echo "===== 5. COMPANY1 / MANAGER1 / CUSTOMER1 CANNOT SEE FOREIGN DETAIL ====="
STATUS=$(detail_status "$COMPANY1_TOKEN" "$FOREIGN_TICKET_ID")
[[ "$STATUS" == "404" ]] || fail "Company1 admin foreign ticket detail gördü veya beklenmeyen cevap aldı. HTTP=$STATUS"
ok "Company1 admin Company2 ticket detail göremiyor"

STATUS=$(detail_status "$MANAGER1_TOKEN" "$FOREIGN_TICKET_ID")
[[ "$STATUS" == "404" ]] || fail "Manager1 foreign ticket detail gördü veya beklenmeyen cevap aldı. HTTP=$STATUS"
ok "Manager1 Company2 ticket detail göremiyor"

STATUS=$(detail_status "$CUSTOMER1_TOKEN" "$FOREIGN_TICKET_ID")
[[ "$STATUS" == "404" ]] || fail "Customer1 foreign ticket detail gördü veya beklenmeyen cevap aldı. HTTP=$STATUS"
ok "Customer1 Customer2 ticket detail göremiyor"

echo
echo "===== 6. COMPANY1 / MANAGER1 / CUSTOMER1 LIST DOES NOT INCLUDE FOREIGN TICKET ====="
[[ "$(contains_ticket "$COMPANY1_TOKEN" "$FOREIGN_TICKET_ID")" == "NO" ]] || fail "Company1 listesinde Company2 ticket görünüyor"
ok "Company1 admin listesinde foreign ticket yok"

[[ "$(contains_ticket "$MANAGER1_TOKEN" "$FOREIGN_TICKET_ID")" == "NO" ]] || fail "Manager1 listesinde Company2 ticket görünüyor"
ok "Manager1 listesinde foreign ticket yok"

[[ "$(contains_ticket "$CUSTOMER1_TOKEN" "$FOREIGN_TICKET_ID")" == "NO" ]] || fail "Customer1 listesinde Customer2 ticket görünüyor"
ok "Customer1 listesinde foreign ticket yok"

echo
echo "===== 7. COMPANY2 / MANAGER2 / CUSTOMER2 CAN SEE OWN TICKET ====="
[[ "$(contains_ticket "$COMPANY2_TOKEN" "$FOREIGN_TICKET_ID")" == "YES" ]] || fail "Company2 admin kendi ticketını listede göremiyor"
ok "Company2 admin kendi ticketını görüyor"

[[ "$(contains_ticket "$MANAGER2_TOKEN" "$FOREIGN_TICKET_ID")" == "YES" ]] || fail "Manager2 kendi building ticketını listede göremiyor"
ok "Manager2 kendi building ticketını görüyor"

[[ "$(contains_ticket "$CUSTOMER2_TOKEN" "$FOREIGN_TICKET_ID")" == "YES" ]] || fail "Customer2 kendi ticketını listede göremiyor"
ok "Customer2 kendi ticketını görüyor"

echo
echo "===== 8. CUSTOMER1 CANNOT CREATE TICKET IN COMPANY2 ====="
STATUS=$(create_cross_scope_status "$CUSTOMER1_TOKEN" "$BUILDING2_ID" "$CUSTOMER2_ID")
[[ "$STATUS" == "400" || "$STATUS" == "403" || "$STATUS" == "404" ]] || fail "Customer1 Company2 içinde ticket oluşturabildi. HTTP=$STATUS"
ok "Customer1 Company2/Customer2 için ticket oluşturamıyor. HTTP=$STATUS"

echo
echo "======================================"
echo "SCOPE ISOLATION TEST PASSED"
echo "Foreign test ticket id: $FOREIGN_TICKET_ID"
echo "======================================"
