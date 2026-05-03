#!/usr/bin/env bash
set -euo pipefail

API="http://localhost:8000/api"

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

expect_http() {
  local actual="$1"
  local expected="$2"
  local label="$3"

  if [ "$actual" != "$expected" ]; then
    fail "$label failed. Expected HTTP=$expected got HTTP=$actual"
  fi

  ok "$label"
}

echo "===== 1. LOGIN USERS ====="
ADMIN_TOKEN="$(login admin@example.com 'Admin12345!')"
MANAGER_TOKEN="$(login manager@example.com 'Test12345!')"
CUSTOMER_TOKEN="$(login customer@example.com 'Test12345!')"
ok "Users logged in"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

PUBLIC_FILE="$TMP_DIR/customer-public.png"
HIDDEN_FILE="$TMP_DIR/manager-hidden.png"
PUBLIC_DOWNLOAD="$TMP_DIR/public-download.png"
HIDDEN_DOWNLOAD="$TMP_DIR/hidden-download.png"

python3 - "$PUBLIC_FILE" "$HIDDEN_FILE" <<'PYPNG'
from pathlib import Path
import sys

# Minimal valid 1x1 PNG bytes
png = bytes.fromhex(
    "89504e470d0a1a0a"
    "0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6360000002000100ffff03000006000557bfab00"
    "0000000049454e44ae426082"
)

Path(sys.argv[1]).write_bytes(png)
Path(sys.argv[2]).write_bytes(png)
PYPNG

echo
echo "===== 2. CREATE TEST TICKET ====="
CREATE_RESP="$(curl -sS -X POST "$API/tickets/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title":"Attachment download test ticket",
    "description":"Testing protected attachment downloads.",
    "room_label":"Attachment Download Room",
    "type":"REPORT",
    "priority":"NORMAL",
    "building":1,
    "customer":1
  }')"

TICKET_ID="$(printf '%s' "$CREATE_RESP" | json_get_id)"
ok "Ticket created id=$TICKET_ID"

echo
echo "===== 3. UPLOAD PUBLIC ATTACHMENT AS CUSTOMER ====="
PUBLIC_RESP="$(curl -sS -X POST "$API/tickets/$TICKET_ID/attachments/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -F "file=@$PUBLIC_FILE;type=image/png" \
  -F "is_hidden=false")"

PUBLIC_ATTACHMENT_ID="$(printf '%s' "$PUBLIC_RESP" | json_get_id)"
ok "Public attachment uploaded id=$PUBLIC_ATTACHMENT_ID"

echo
echo "===== 4. UPLOAD HIDDEN ATTACHMENT AS MANAGER ====="
HIDDEN_RESP="$(curl -sS -X POST "$API/tickets/$TICKET_ID/attachments/" \
  -H "Authorization: Bearer $MANAGER_TOKEN" \
  -F "file=@$HIDDEN_FILE;type=image/png" \
  -F "is_hidden=true")"

HIDDEN_ATTACHMENT_ID="$(printf '%s' "$HIDDEN_RESP" | json_get_id)"
ok "Hidden attachment uploaded id=$HIDDEN_ATTACHMENT_ID"

echo
echo "===== 5. CUSTOMER CAN DOWNLOAD PUBLIC ATTACHMENT ====="
STATUS="$(curl -sS -o "$PUBLIC_DOWNLOAD" -w "%{http_code}" \
  "$API/tickets/$TICKET_ID/attachments/$PUBLIC_ATTACHMENT_ID/download/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN")"

expect_http "$STATUS" "200" "Customer public attachment download"

cmp -s "$PUBLIC_FILE" "$PUBLIC_DOWNLOAD" || fail "Downloaded public file content mismatch"
ok "Public downloaded content matches"

echo
echo "===== 6. CUSTOMER CANNOT DOWNLOAD HIDDEN ATTACHMENT ====="
STATUS="$(curl -sS -o /dev/null -w "%{http_code}" \
  "$API/tickets/$TICKET_ID/attachments/$HIDDEN_ATTACHMENT_ID/download/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN")"

if [ "$STATUS" != "403" ] && [ "$STATUS" != "404" ]; then
  fail "Customer downloaded hidden attachment unexpectedly. HTTP=$STATUS"
fi
ok "Customer cannot download hidden attachment. HTTP=$STATUS"

echo
echo "===== 7. MANAGER CAN DOWNLOAD HIDDEN ATTACHMENT ====="
STATUS="$(curl -sS -o "$HIDDEN_DOWNLOAD" -w "%{http_code}" \
  "$API/tickets/$TICKET_ID/attachments/$HIDDEN_ATTACHMENT_ID/download/" \
  -H "Authorization: Bearer $MANAGER_TOKEN")"

expect_http "$STATUS" "200" "Manager hidden attachment download"

cmp -s "$HIDDEN_FILE" "$HIDDEN_DOWNLOAD" || fail "Downloaded hidden file content mismatch"
ok "Hidden downloaded content matches"

echo
echo "===== 8. ADMIN CAN DOWNLOAD HIDDEN ATTACHMENT ====="
STATUS="$(curl -sS -o /dev/null -w "%{http_code}" \
  "$API/tickets/$TICKET_ID/attachments/$HIDDEN_ATTACHMENT_ID/download/" \
  -H "Authorization: Bearer $ADMIN_TOKEN")"

expect_http "$STATUS" "200" "Admin hidden attachment download"

echo
echo "======================================"
echo "ATTACHMENT DOWNLOAD TEST PASSED"
echo "Test ticket id: $TICKET_ID"
echo "======================================"
