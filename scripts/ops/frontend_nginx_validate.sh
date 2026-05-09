#!/usr/bin/env bash
#
# Sprint 11 — host-agnostic syntax + posture validation for the
# frontend nginx config.
#
# Two checks:
#   1. `nginx -t` against frontend/nginx.conf, run inside the same
#      nginx:1.27-alpine image the production frontend Dockerfile
#      uses — so any rule that would fail at runtime fails here too.
#      The `--add-host=backend:127.0.0.1` flag papers over the
#      upstream DNS so the syntax check does not error out on
#      `proxy_pass http://backend:8000/...`.
#
#   2. Posture grep against the source file:
#        - `location /health/` MUST exist (Sprint 11 fix; without it
#          the public smoke at /health/live falls through to the SPA
#          shell and silently returns HTTP 200 with HTML).
#        - The `/health/` block MUST appear BEFORE the catch-all
#          `location /` block (nginx's location matching on prefix
#          uses longest-match for prefix locations, but visual order
#          matters for code review).
#        - `proxy_set_header X-Forwarded-Proto $forwarded_proto`
#          MUST be present in the /api/ block (otherwise Django's
#          request.is_secure() returns False even behind NPM, which
#          breaks Secure cookies and CSRF).
#
# Safe to run on any host with docker installed. Does not require
# the production stack to be up; pulls a 30 MB nginx image on first
# use (cached afterwards). Cleans up its temp container.
#
# Usage:
#   ./scripts/ops/frontend_nginx_validate.sh
#
# Exits 0 on success, non-zero on any failure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NGINX_CONF="${REPO_ROOT}/frontend/nginx.conf"
NGINX_IMAGE="nginx:1.27-alpine"

[[ -f "$NGINX_CONF" ]] || {
  echo "[FAIL] $NGINX_CONF not found" >&2
  exit 1
}

if ! command -v docker >/dev/null 2>&1; then
  echo "[FAIL] docker CLI not on PATH (this validator runs nginx in a container)" >&2
  exit 1
fi

echo "frontend_nginx_validate: running nginx -t in $NGINX_IMAGE"

# `--add-host=backend:127.0.0.1` makes the upstream name resolve so
# nginx -t does not bail on the upstream DNS lookup. The probe never
# actually proxies anywhere — it just asks nginx to parse the conf.
if ! docker run --rm \
    --add-host=backend:127.0.0.1 \
    -v "${NGINX_CONF}:/etc/nginx/conf.d/default.conf:ro" \
    "$NGINX_IMAGE" \
    nginx -t >/tmp/nginx_validate.out 2>&1; then
  echo "[FAIL] nginx -t reported errors:" >&2
  cat /tmp/nginx_validate.out >&2
  exit 1
fi
grep -q "syntax is ok" /tmp/nginx_validate.out || {
  echo "[FAIL] nginx -t did not report 'syntax is ok':" >&2
  cat /tmp/nginx_validate.out >&2
  exit 1
}
grep -q "test is successful" /tmp/nginx_validate.out || {
  echo "[FAIL] nginx -t did not report 'test is successful':" >&2
  cat /tmp/nginx_validate.out >&2
  exit 1
}
echo "[OK]   nginx -t: syntax is ok / test is successful"

echo "frontend_nginx_validate: posture checks"

if ! grep -qE "^[[:space:]]*location[[:space:]]+/health/[[:space:]]*\{" "$NGINX_CONF"; then
  echo "[FAIL] no 'location /health/' block in $NGINX_CONF" >&2
  echo "       (without this, public /health/live falls through to the SPA fallback" >&2
  echo "        and the smoke test passes on an HTML response — see docs/pre-host-production-hardening.md)" >&2
  exit 1
fi
echo "[OK]   /health/ proxy block present"

# /health/ must appear BEFORE `location /` in source order so the
# intent is clear in review (nginx itself uses longest prefix match,
# so functionally either order works — but a `/health/` block placed
# AFTER `location /` would be a reviewer trip-hazard).
HEALTH_LINE="$(grep -nE "^[[:space:]]*location[[:space:]]+/health/[[:space:]]*\{" "$NGINX_CONF" | head -1 | cut -d: -f1)"
ROOT_LINE="$(grep -nE "^[[:space:]]*location[[:space:]]+/[[:space:]]*\{" "$NGINX_CONF" | head -1 | cut -d: -f1)"

if [[ -n "$HEALTH_LINE" && -n "$ROOT_LINE" ]]; then
  if (( HEALTH_LINE > ROOT_LINE )); then
    echo "[FAIL] location /health/ (line $HEALTH_LINE) is below the catch-all location / (line $ROOT_LINE)" >&2
    exit 1
  fi
  echo "[OK]   /health/ block is above the catch-all location /"
fi

# X-Forwarded-Proto $forwarded_proto must be set on the /api/ block.
# (Sprint 4 fix — if missing, Django sees every request as HTTP and
# Secure cookies never set behind NPM.)
if ! grep -qE "proxy_set_header[[:space:]]+X-Forwarded-Proto[[:space:]]+\\\$forwarded_proto" "$NGINX_CONF"; then
  echo "[FAIL] X-Forwarded-Proto \$forwarded_proto not set on any proxy block" >&2
  echo "       (without this, request.is_secure() returns False under NPM)" >&2
  exit 1
fi
echo "[OK]   X-Forwarded-Proto \$forwarded_proto present"

echo
echo "[OK] frontend/nginx.conf passes syntax + posture validation."
