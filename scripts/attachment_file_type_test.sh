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

extract_id() {
  python3 -c '
import sys, json
data = json.load(sys.stdin)
if "id" not in data:
    print("EXPECTED_ID_MISSING_RESPONSE:", json.dumps(data, indent=2), file=sys.stderr)
    raise SystemExit(1)
print(data["id"])
'
}

upload_and_expect_success() {
  local token="$1"
  local ticket_id="$2"
  local file_path="$3"
  local mime_type="$4"

  local response
  response=$(curl -sS -X POST "$API/tickets/$ticket_id/attachments/" \
    -H "Authorization: Bearer $token" \
    -F "file=@${file_path};type=${mime_type}" \
    -F "is_hidden=false")

  echo "$response" | extract_id >/dev/null
}

upload_and_expect_failure() {
  local token="$1"
  local ticket_id="$2"
  local file_path="$3"
  local mime_type="$4"

  local http_code
  http_code=$(curl -sS -o /tmp/attachment_type_fail_response.json -w "%{http_code}" \
    -X POST "$API/tickets/$ticket_id/attachments/" \
    -H "Authorization: Bearer $token" \
    -F "file=@${file_path};type=${mime_type}" \
    -F "is_hidden=false")

  if [[ "$http_code" == "200" || "$http_code" == "201" ]]; then
    cat /tmp/attachment_type_fail_response.json
    fail "Invalid attachment was accepted: $(basename "$file_path")"
  fi
}

echo "===== 1. LOGIN CUSTOMER ====="
CUSTOMER_TOKEN=$(login customer@example.com "$PASSWORD")
ok "Customer logged in"

echo
echo "===== 2. CREATE TEST TICKET ====="
CREATE_RESPONSE=$(curl -sS -X POST "$API/tickets/" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Attachment file type test",
    "description": "Testing allowed attachment file types.",
    "room_label": "File Type Room",
    "type": "REPORT",
    "priority": "NORMAL",
    "building": 1,
    "customer": 1
  }')

TICKET_ID=$(echo "$CREATE_RESPONSE" | extract_id)
ok "Ticket created id=$TICKET_ID"

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Minimal file contents. Validation is based on extension + MIME type.
printf '\x89PNG\r\n\x1a\n' > "$TMP_DIR/allowed.png"
printf '\xff\xd8\xff\xd9' > "$TMP_DIR/allowed.jpg"
printf '\xff\xd8\xff\xd9' > "$TMP_DIR/allowed.jpeg"
printf 'RIFF....WEBP' > "$TMP_DIR/allowed.webp"
printf '%s\n' '%PDF-1.4' > "$TMP_DIR/allowed.pdf"
printf '\x00\x00\x00\x18ftypheic' > "$TMP_DIR/allowed.heic"
printf '\x00\x00\x00\x18ftypheif' > "$TMP_DIR/allowed.heif"
printf 'not allowed' > "$TMP_DIR/not-allowed.txt"
python3 - "$TMP_DIR/too-large.pdf" <<'PY_CREATE_LARGE_FILE'
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.write_bytes(b"%PDF-1.4\n" + (b"0" * ((10 * 1024 * 1024) + 1)))
PY_CREATE_LARGE_FILE

echo
echo "===== 3. ALLOWED TYPES ====="
upload_and_expect_success "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/allowed.png" "image/png"
ok "PNG accepted"

upload_and_expect_success "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/allowed.jpg" "image/jpeg"
ok "JPG accepted"

upload_and_expect_success "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/allowed.jpeg" "image/jpeg"
ok "JPEG accepted"

upload_and_expect_success "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/allowed.webp" "image/webp"
ok "WEBP accepted"

upload_and_expect_success "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/allowed.pdf" "application/pdf"
ok "PDF accepted"

upload_and_expect_success "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/allowed.heic" "image/heic"
ok "HEIC accepted"

upload_and_expect_success "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/allowed.heif" "image/heif"
ok "HEIF accepted"

echo
echo "===== 4. DISALLOWED TYPE ====="
upload_and_expect_failure "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/not-allowed.txt" "text/plain"
ok "TXT rejected"

echo
echo "===== 5. FILE SIZE LIMIT ====="
upload_and_expect_failure "$CUSTOMER_TOKEN" "$TICKET_ID" "$TMP_DIR/too-large.pdf" "application/pdf"
ok "Oversized PDF rejected"

echo
echo "======================================"
echo "ATTACHMENT FILE TYPE TEST PASSED"
echo "Test ticket id: $TICKET_ID"
echo "======================================"
