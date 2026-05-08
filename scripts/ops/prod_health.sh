#!/usr/bin/env bash
#
# Hit the public production health endpoints. Read-only; safe to run
# any time. Operator passes the public domain via $DOMAIN or as the
# first positional argument:
#
#   DOMAIN=cleaning.example.com ./scripts/ops/prod_health.sh
#   ./scripts/ops/prod_health.sh cleaning.example.com
#
# Exits non-zero if either /health/live or /health/ready returns
# anything other than HTTP 200.

set -euo pipefail

DOMAIN="${1:-${DOMAIN:-}}"

if [[ -z "$DOMAIN" ]]; then
  echo "Usage: $0 <public-domain>" >&2
  echo "   or: DOMAIN=<public-domain> $0" >&2
  exit 2
fi

probe() {
  local label="$1"
  local path="$2"
  local url="https://${DOMAIN}${path}"
  local body_file
  body_file="$(mktemp)"
  local code
  code="$(curl -sS -o "$body_file" -w '%{http_code}' "$url" || echo 000)"

  if [[ "$code" == "200" ]]; then
    echo "[OK]   ${label}  ${url} -> 200"
    cat "$body_file"
    echo
    rm -f "$body_file"
    return 0
  fi

  echo "[FAIL] ${label}  ${url} -> ${code}" >&2
  echo "--- body ---" >&2
  cat "$body_file" >&2
  echo >&2
  rm -f "$body_file"
  return 1
}

probe "liveness " /api/health/live
probe "readiness" /api/health/ready
echo "All checks passed."
