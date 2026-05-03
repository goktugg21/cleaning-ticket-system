#!/usr/bin/env bash
set -euo pipefail

API="${API:-http://localhost:8000/api}"

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

request_with_status() {
  local body_file="$1"
  shift

  local status
  status=$(curl -sS -o "$body_file" -w "%{http_code}" "$@")
  echo "$status"
}

echo "===== 1. LOGIN USERS ====="
ADMIN_TOKEN=$(login admin@example.com 'Admin12345!')
MANAGER_TOKEN=$(login manager@example.com 'Test12345!')
CUSTOMER_TOKEN=$(login customer@example.com 'Test12345!')
ok "Admin, manager, customer login oldu"

echo
echo "===== 2. CREATE TEST TICKET ====="
CREATE_BODY=$(mktemp)

STATUS=$(request_with_status "$CREATE_BODY" \
  -X POST "$API/tickets/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title":"Attachment API smoke test ticket",
    "description":"Testing ticket attachments.",
    "room_label":"Attachment Room",
    "type":"REPORT",
    "priority":"NORMAL",
    "building":1,
    "customer":1
  }')

[ "$STATUS" = "201" ] || {
  cat "$CREATE_BODY"
  fail "Ticket oluşturulamadı. HTTP=$STATUS"
}

TICKET_ID=$(python3 -c 'import sys,json; print(json.load(open(sys.argv[1]))["id"])' "$CREATE_BODY")
ok "Test ticket oluşturuldu: id=$TICKET_ID"

printf '\x89PNG\r\n\x1a\n' > /tmp/customer-public.png
printf '\x89PNG\r\n\x1a\n' > /tmp/manager-hidden.png

echo
echo "===== 3. CUSTOMER PUBLIC ATTACHMENT ====="
PUBLIC_BODY=$(mktemp)

STATUS=$(request_with_status "$PUBLIC_BODY" \
  -X POST "$API/tickets/$TICKET_ID/attachments/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -F "file=@/tmp/customer-public.png;type=image/png")

[ "$STATUS" = "201" ] || {
  cat "$PUBLIC_BODY"
  fail "Customer public attachment yükleyemedi. HTTP=$STATUS"
}

PUBLIC_HIDDEN=$(python3 -c 'import sys,json; print(json.load(open(sys.argv[1]))["is_hidden"])' "$PUBLIC_BODY")
[ "$PUBLIC_HIDDEN" = "False" ] || fail "Customer public attachment is_hidden=false değil"
ok "Customer public attachment yükledi"

echo
echo "===== 4. CUSTOMER HIDDEN ATTACHMENT SHOULD FAIL ====="
CUSTOMER_HIDDEN_BODY=$(mktemp)

STATUS=$(request_with_status "$CUSTOMER_HIDDEN_BODY" \
  -X POST "$API/tickets/$TICKET_ID/attachments/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -F "file=@/tmp/customer-public.png;type=image/png" \
  -F "is_hidden=true")

[ "$STATUS" = "400" ] || {
  cat "$CUSTOMER_HIDDEN_BODY"
  fail "Customer hidden attachment yükleyebildi, bu olmamalıydı. HTTP=$STATUS"
}
ok "Customer hidden/internal attachment yükleyemiyor"

echo
echo "===== 5. MANAGER HIDDEN ATTACHMENT ====="
MANAGER_HIDDEN_BODY=$(mktemp)

STATUS=$(request_with_status "$MANAGER_HIDDEN_BODY" \
  -X POST "$API/tickets/$TICKET_ID/attachments/" \
  -H "Authorization: Bearer $MANAGER_TOKEN" \
  -F "file=@/tmp/manager-hidden.png;type=image/png" \
  -F "is_hidden=true")

[ "$STATUS" = "201" ] || {
  cat "$MANAGER_HIDDEN_BODY"
  fail "Manager hidden attachment yükleyemedi. HTTP=$STATUS"
}

MANAGER_IS_HIDDEN=$(python3 -c 'import sys,json; print(json.load(open(sys.argv[1]))["is_hidden"])' "$MANAGER_HIDDEN_BODY")
[ "$MANAGER_IS_HIDDEN" = "True" ] || fail "Manager attachment is_hidden=true değil"
ok "Manager hidden/internal attachment yükledi"

echo
echo "===== 6. ADMIN SEES ALL ATTACHMENTS ====="
ADMIN_LIST_BODY=$(mktemp)

STATUS=$(request_with_status "$ADMIN_LIST_BODY" \
  "$API/tickets/$TICKET_ID/attachments/" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

[ "$STATUS" = "200" ] || {
  cat "$ADMIN_LIST_BODY"
  fail "Admin attachment list alamadı. HTTP=$STATUS"
}

ADMIN_COUNT=$(python3 -c 'import sys,json; print(json.load(open(sys.argv[1]))["count"])' "$ADMIN_LIST_BODY")
[ "$ADMIN_COUNT" = "2" ] || {
  cat "$ADMIN_LIST_BODY"
  fail "Admin 2 attachment görmeliydi, count=$ADMIN_COUNT"
}
ok "Admin public + hidden attachment görebiliyor"

echo
echo "===== 7. CUSTOMER SEES ONLY PUBLIC ATTACHMENTS ====="
CUSTOMER_LIST_BODY=$(mktemp)

STATUS=$(request_with_status "$CUSTOMER_LIST_BODY" \
  "$API/tickets/$TICKET_ID/attachments/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN")

[ "$STATUS" = "200" ] || {
  cat "$CUSTOMER_LIST_BODY"
  fail "Customer attachment list alamadı. HTTP=$STATUS"
}

CUSTOMER_COUNT=$(python3 -c 'import sys,json; print(json.load(open(sys.argv[1]))["count"])' "$CUSTOMER_LIST_BODY")
[ "$CUSTOMER_COUNT" = "1" ] || {
  cat "$CUSTOMER_LIST_BODY"
  fail "Customer sadece 1 public attachment görmeliydi, count=$CUSTOMER_COUNT"
}

CUSTOMER_HAS_HIDDEN=$(python3 -c '
import sys, json
data = json.load(open(sys.argv[1]))
print(any(item.get("is_hidden") for item in data["results"]))
' "$CUSTOMER_LIST_BODY")

[ "$CUSTOMER_HAS_HIDDEN" = "False" ] || {
  cat "$CUSTOMER_LIST_BODY"
  fail "Customer hidden attachment görüyor, bu güvenlik hatası"
}
ok "Customer hidden attachment göremiyor"

echo
echo "======================================"
echo "ATTACHMENT API TEST PASSED"
echo "Test ticket id: $TICKET_ID"
echo "======================================"
