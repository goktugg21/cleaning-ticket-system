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

post_json_with_status() {
  local url="$1"
  local token="$2"
  local body="$3"
  local output_file="$4"

  curl -sS -o "$output_file" -w "%{http_code}" \
    -X POST "$url" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "$body"
}


get_with_status() {
  local url="$1"
  local token="$2"
  local output_file="$3"

  curl -sS -o "$output_file" -w "%{http_code}" \
    "$url" \
    -H "Authorization: Bearer $token"
}

echo "===== 1. ENSURE BACKEND IS RUNNING ====="
docker compose up -d backend >/dev/null
docker compose exec -T backend python manage.py check >/dev/null
ok "Backend is running"

echo
echo "===== 2. SEED ASSIGNMENT DATA ====="
SEED_JSON=$(
docker compose exec -T backend python manage.py shell <<'PY_SEED' | tail -n 1
import json
from accounts.models import User, UserRole
from buildings.models import Building, BuildingManagerAssignment
from customers.models import Customer

PASSWORD = "Test12345!"

building = Building.objects.get(pk=1)
customer = Customer.objects.get(pk=1)

manager = User.objects.get(email="manager@example.com")
manager.role = UserRole.BUILDING_MANAGER
manager.is_active = True
manager.deleted_at = None
manager.set_password(PASSWORD)
manager.save()
BuildingManagerAssignment.objects.get_or_create(user=manager, building=building)

other_building, _ = Building.objects.get_or_create(
    company=building.company,
    name="Assignment Other Building",
    defaults={
        "address": "Assignment Other Street",
        "city": "Amsterdam",
        "country": "Netherlands",
        "postal_code": "1000 AA",
        "is_active": True,
    },
)
other_building.is_active = True
other_building.save()

other_manager, _ = User.objects.get_or_create(
    email="assignment-other-manager@example.com",
    defaults={
        "role": UserRole.BUILDING_MANAGER,
        "full_name": "Assignment Other Manager",
        "language": "nl",
        "is_active": True,
    },
)
other_manager.role = UserRole.BUILDING_MANAGER
other_manager.full_name = "Assignment Other Manager"
other_manager.language = "nl"
other_manager.is_active = True
other_manager.deleted_at = None
other_manager.set_password(PASSWORD)
other_manager.save()

BuildingManagerAssignment.objects.get_or_create(user=other_manager, building=other_building)
BuildingManagerAssignment.objects.filter(user=other_manager, building=building).delete()

print(json.dumps({
    "building_id": building.id,
    "customer_id": customer.id,
    "manager_id": manager.id,
    "other_manager_id": other_manager.id,
}))
PY_SEED
)

BUILDING_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["building_id"])' "$SEED_JSON")
CUSTOMER_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["customer_id"])' "$SEED_JSON")
MANAGER_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["manager_id"])' "$SEED_JSON")
OTHER_MANAGER_ID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["other_manager_id"])' "$SEED_JSON")

ok "Building=$BUILDING_ID Customer=$CUSTOMER_ID Manager=$MANAGER_ID OtherManager=$OTHER_MANAGER_ID"

echo
echo "===== 3. LOGIN USERS ====="
COMPANY_TOKEN=$(login companyadmin@example.com "$PASSWORD")
MANAGER_TOKEN=$(login manager@example.com "$PASSWORD")
CUSTOMER_TOKEN=$(login customer@example.com "$PASSWORD")
ok "Company admin, manager, customer logged in"

echo
echo "===== 4. CREATE TEST TICKET ====="
STATUS=$(post_json_with_status "$API/tickets/" "$CUSTOMER_TOKEN" "{
  \"title\":\"Assignment API test ticket\",
  \"description\":\"Created by assignment_api_test.sh\",
  \"room_label\":\"Assignment Room\",
  \"type\":\"REPORT\",
  \"priority\":\"NORMAL\",
  \"building\":$BUILDING_ID,
  \"customer\":$CUSTOMER_ID
}" /tmp/assignment_create_response.json)

[[ "$STATUS" == "201" ]] || { cat /tmp/assignment_create_response.json; fail "Ticket create failed. HTTP=$STATUS"; }

TICKET_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' < /tmp/assignment_create_response.json)
ok "Ticket created id=$TICKET_ID"

echo
echo "===== 5. COMPANY ADMIN ASSIGNS TO BUILDING MANAGER ====="
STATUS=$(post_json_with_status "$API/tickets/$TICKET_ID/assign/" "$COMPANY_TOKEN" "{
  \"assigned_to\": $MANAGER_ID
}" /tmp/assignment_assign_response.json)

[[ "$STATUS" == "200" ]] || { cat /tmp/assignment_assign_response.json; fail "Company admin assign failed. HTTP=$STATUS"; }

python3 - "$MANAGER_ID" /tmp/assignment_assign_response.json <<'PY_CHECK'
import json
import sys
from pathlib import Path

expected_manager_id = int(sys.argv[1])
data = json.loads(Path(sys.argv[2]).read_text())
assert data["assigned_to"] == expected_manager_id, data
assert data["assigned_to_email"] == "manager@example.com", data
print("[OK] Company admin assigned ticket to manager")
PY_CHECK

echo
echo "===== 6. COMPANY ADMIN UNASSIGNS TICKET ====="
STATUS=$(post_json_with_status "$API/tickets/$TICKET_ID/assign/" "$COMPANY_TOKEN" '{
  "assigned_to": null
}' /tmp/assignment_unassign_response.json)

[[ "$STATUS" == "200" ]] || { cat /tmp/assignment_unassign_response.json; fail "Unassign failed. HTTP=$STATUS"; }

python3 - /tmp/assignment_unassign_response.json <<'PY_CHECK'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
assert data["assigned_to"] is None, data
assert data["assigned_to_email"] is None, data
print("[OK] Company admin unassigned ticket")
PY_CHECK

echo
echo "===== 7. BUILDING MANAGER CAN ASSIGN ACCESSIBLE TICKET ====="
STATUS=$(post_json_with_status "$API/tickets/$TICKET_ID/assign/" "$MANAGER_TOKEN" "{
  \"assigned_to\": $MANAGER_ID
}" /tmp/assignment_manager_assign_response.json)

[[ "$STATUS" == "200" ]] || { cat /tmp/assignment_manager_assign_response.json; fail "Manager assign failed. HTTP=$STATUS"; }
ok "Building manager assigned accessible ticket"

echo
echo "===== 8. CUSTOMER CANNOT ASSIGN TICKET ====="
STATUS=$(post_json_with_status "$API/tickets/$TICKET_ID/assign/" "$CUSTOMER_TOKEN" "{
  \"assigned_to\": $MANAGER_ID
}" /tmp/assignment_customer_assign_response.json)

if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
  cat /tmp/assignment_customer_assign_response.json
  fail "Customer was able to assign ticket"
fi
ok "Customer assign rejected. HTTP=$STATUS"

echo
echo "===== 9. MANAGER MUST BELONG TO TICKET BUILDING ====="
STATUS=$(post_json_with_status "$API/tickets/$TICKET_ID/assign/" "$COMPANY_TOKEN" "{
  \"assigned_to\": $OTHER_MANAGER_ID
}" /tmp/assignment_wrong_manager_response.json)

if [[ "$STATUS" == "200" || "$STATUS" == "201" ]]; then
  cat /tmp/assignment_wrong_manager_response.json
  fail "Manager from another building was accepted"
fi
ok "Manager from another building rejected. HTTP=$STATUS"

echo
echo "===== 10. ASSIGNABLE MANAGERS LIST ====="
STATUS=$(get_with_status "$API/tickets/$TICKET_ID/assignable-managers/" "$COMPANY_TOKEN" /tmp/assignment_managers_response.json)

[[ "$STATUS" == "200" ]] || { cat /tmp/assignment_managers_response.json; fail "Assignable managers list failed. HTTP=$STATUS"; }

python3 - "$MANAGER_ID" "$OTHER_MANAGER_ID" /tmp/assignment_managers_response.json <<'PY_CHECK'
import json
import sys
from pathlib import Path

manager_id = int(sys.argv[1])
other_manager_id = int(sys.argv[2])
data = json.loads(Path(sys.argv[3]).read_text())
ids = {item["id"] for item in data}
assert manager_id in ids, data
assert other_manager_id not in ids, data
assert all(item["role"] == "BUILDING_MANAGER" for item in data), data
print("[OK] Assignable managers list is scoped to ticket building")
PY_CHECK

echo
echo "===== 11. CUSTOMER CANNOT VIEW ASSIGNABLE MANAGERS ====="
STATUS=$(get_with_status "$API/tickets/$TICKET_ID/assignable-managers/" "$CUSTOMER_TOKEN" /tmp/assignment_customer_managers_response.json)

if [[ "$STATUS" == "200" ]]; then
  cat /tmp/assignment_customer_managers_response.json
  fail "Customer was able to view assignable managers"
fi
ok "Customer assignable managers list rejected. HTTP=$STATUS"

echo
echo "======================================"
echo "ASSIGNMENT API TEST PASSED"
echo "Test ticket id: $TICKET_ID"
echo "======================================"
