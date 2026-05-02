#!/usr/bin/env bash
set -euo pipefail

API="http://localhost:8000/api"

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

get_json() {
  local url="$1"
  local token="$2"

  curl -sS "$url" \
    -H "Authorization: Bearer $token"
}

post_json() {
  local url="$1"
  local token="$2"
  local body="$3"

  curl -sS -X POST "$url" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "$body"
}

echo "===== 1. LOGIN TEST ====="
ADMIN_TOKEN=$(login admin@example.com 'Admin12345!')
COMPANY_TOKEN=$(login companyadmin@example.com 'Test12345!')
MANAGER_TOKEN=$(login manager@example.com 'Test12345!')
CUSTOMER_TOKEN=$(login customer@example.com 'Test12345!')
echo "[OK] Login başarılı: admin, company admin, manager, customer"

echo
echo "===== 2. ROLE / ME TEST ====="

check_me() {
  local label="$1"
  local token="$2"
  local expected_role="$3"

  RESP=$(get_json "$API/auth/me/" "$token")

  python3 -c '
import sys, json
expected = sys.argv[1]
data = json.load(sys.stdin)
assert data["role"] == expected, f"Expected {expected}, got {data['"'"'role'"'"']}"
print(f"[OK] {data['"'"'email'"'"']} role={data['"'"'role'"'"']} companies={data['"'"'company_ids'"'"']} buildings={data['"'"'building_ids'"'"']} customers={data['"'"'customer_ids'"'"']}")
' "$expected_role" <<< "$RESP"
}

check_me "admin" "$ADMIN_TOKEN" "SUPER_ADMIN"
check_me "company" "$COMPANY_TOKEN" "COMPANY_ADMIN"
check_me "manager" "$MANAGER_TOKEN" "BUILDING_MANAGER"
check_me "customer" "$CUSTOMER_TOKEN" "CUSTOMER_USER"

echo
echo "===== 3. ROLE-BASED TICKET LIST TEST ====="

check_tickets() {
  local label="$1"
  local token="$2"

  RESP=$(get_json "$API/tickets/" "$token")

  python3 -c '
import sys, json
label = sys.argv[1]
data = json.load(sys.stdin)
assert "results" in data, data
print(f"[OK] {label}: ticket count={data['"'"'count'"'"']}")
' "$label" <<< "$RESP"
}

check_tickets "ADMIN" "$ADMIN_TOKEN"
check_tickets "COMPANY_ADMIN" "$COMPANY_TOKEN"
check_tickets "MANAGER" "$MANAGER_TOKEN"
check_tickets "CUSTOMER" "$CUSTOMER_TOKEN"

echo
echo "===== 4. CUSTOMER CREATE TICKET TEST ====="

CREATE_RESP=$(post_json "$API/tickets/" "$CUSTOMER_TOKEN" '{
  "title":"Terminal smoke test ticket",
  "description":"Created by smoke_api_test.sh",
  "room_label":"Smoke Test Room",
  "type":"REPORT",
  "priority":"NORMAL",
  "building":1,
  "customer":1
}')

TICKET_ID=$(python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])' <<< "$CREATE_RESP")

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data["status"] == "OPEN", data
print(f"[OK] Customer ticket oluşturdu: id={data['"'"'id'"'"']} ticket_no={data['"'"'ticket_no'"'"']} status={data['"'"'status'"'"']}")
' <<< "$CREATE_RESP"

echo
echo "===== 5. CUSTOMER ILLEGAL STATUS TEST ====="

ILLEGAL_RESP=$(post_json "$API/tickets/$TICKET_ID/status/" "$CUSTOMER_TOKEN" '{
  "to_status":"IN_PROGRESS",
  "note":"Customer should not be able to start work."
}')

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data.get("code") == "forbidden_transition", data
print("[OK] Customer OPEN -> IN_PROGRESS yapamıyor")
' <<< "$ILLEGAL_RESP"

echo
echo "===== 6. MANAGER STATUS CHANGE TEST ====="

RESP=$(post_json "$API/tickets/$TICKET_ID/status/" "$MANAGER_TOKEN" '{
  "to_status":"IN_PROGRESS",
  "note":"Manager started work from smoke test."
}')

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data["status"] == "IN_PROGRESS", data
assert data["first_response_at"] is not None, data
print("[OK] Manager OPEN -> IN_PROGRESS yaptı")
' <<< "$RESP"

RESP=$(post_json "$API/tickets/$TICKET_ID/status/" "$MANAGER_TOKEN" '{
  "to_status":"WAITING_CUSTOMER_APPROVAL",
  "note":"Manager sent for approval from smoke test."
}')

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data["status"] == "WAITING_CUSTOMER_APPROVAL", data
assert data["sent_for_approval_at"] is not None, data
print("[OK] Manager IN_PROGRESS -> WAITING_CUSTOMER_APPROVAL yaptı")
' <<< "$RESP"

echo
echo "===== 7. CUSTOMER APPROVAL TEST ====="

RESP=$(post_json "$API/tickets/$TICKET_ID/status/" "$CUSTOMER_TOKEN" '{
  "to_status":"APPROVED",
  "note":"Customer approved from smoke test."
}')

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data["status"] == "APPROVED", data
assert data["approved_at"] is not None, data
print("[OK] Customer WAITING_CUSTOMER_APPROVAL -> APPROVED yaptı")
' <<< "$RESP"

echo
echo "===== 8. COMPANY ADMIN CLOSE TEST ====="

RESP=$(post_json "$API/tickets/$TICKET_ID/status/" "$COMPANY_TOKEN" '{
  "to_status":"CLOSED",
  "note":"Company admin closed from smoke test."
}')

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data["status"] == "CLOSED", data
assert data["closed_at"] is not None, data
assert len(data["status_history"]) >= 4, data
print("[OK] Company admin APPROVED -> CLOSED yaptı")
' <<< "$RESP"

echo
echo "===== 9. INTERNAL NOTE VISIBILITY TEST ====="

INTERNAL_RESP=$(post_json "$API/tickets/$TICKET_ID/messages/" "$MANAGER_TOKEN" '{
  "message":"Smoke test internal note. Customer must not see this.",
  "message_type":"INTERNAL_NOTE"
}')

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data["message_type"] == "INTERNAL_NOTE", data
assert data["is_hidden"] == True, data
print("[OK] Manager internal note oluşturdu ve is_hidden=true")
' <<< "$INTERNAL_RESP"

PUBLIC_RESP=$(post_json "$API/tickets/$TICKET_ID/messages/" "$CUSTOMER_TOKEN" '{
  "message":"Smoke test customer public reply.",
  "message_type":"PUBLIC_REPLY"
}')

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert data["message_type"] == "PUBLIC_REPLY", data
print("[OK] Customer public reply oluşturdu")
' <<< "$PUBLIC_RESP"

ADMIN_MESSAGES=$(get_json "$API/tickets/$TICKET_ID/messages/" "$ADMIN_TOKEN")
CUSTOMER_MESSAGES=$(get_json "$API/tickets/$TICKET_ID/messages/" "$CUSTOMER_TOKEN")

python3 -c '
import sys, json
data = json.load(sys.stdin)
types = [item["message_type"] for item in data["results"]]
assert "INTERNAL_NOTE" in types, data
print("[OK] Admin internal note görebiliyor")
' <<< "$ADMIN_MESSAGES"

python3 -c '
import sys, json
data = json.load(sys.stdin)
types = [item["message_type"] for item in data["results"]]
messages = [item["message"] for item in data["results"]]
assert "INTERNAL_NOTE" not in types, data
assert not any("internal note" in msg.lower() for msg in messages), data
print("[OK] Customer internal note göremiyor")
' <<< "$CUSTOMER_MESSAGES"

echo
echo "===== 10. CUSTOMER INTERNAL NOTE CREATE DENY TEST ====="

BAD_INTERNAL=$(post_json "$API/tickets/$TICKET_ID/messages/" "$CUSTOMER_TOKEN" '{
  "message":"Customer should not create internal note.",
  "message_type":"INTERNAL_NOTE"
}')

python3 -c '
import sys, json
data = json.load(sys.stdin)
assert "message_type" in data, data
print("[OK] Customer internal note oluşturamıyor")
' <<< "$BAD_INTERNAL"

echo
echo "======================================"
echo "ALL API SMOKE TESTS PASSED"
echo "Created test ticket id: $TICKET_ID"
echo "======================================"
