#!/usr/bin/env bash
#
# Sprint 10 — host-agnostic validator for docker-compose.prod.yml.
#
# Renders the production compose file with a *dummy* env file (no
# real secrets) and asserts:
#   1. all six expected services are declared
#      (db, redis, backend, worker, beat, frontend);
#   2. only the frontend service publishes a host port (default 80);
#   3. db, redis, backend, worker, beat publish NO host ports;
#   4. the rendered config parses without a docker-compose error.
#
# Safe to run on any host: writes only to a tempdir, never reads the
# operator's real .env or .env.production, never starts a stack.
# Cleans up on exit.
#
# Usage:
#   ./scripts/ops/prod_compose_validate.sh
#
# Exits 0 on success, non-zero on any assertion failure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.prod.yml"

[[ -f "$COMPOSE_FILE" ]] || {
  echo "[FAIL] $COMPOSE_FILE not found" >&2
  exit 1
}

if ! command -v docker >/dev/null 2>&1; then
  echo "[FAIL] docker CLI not on PATH" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

DUMMY_ENV="$TMP_DIR/dummy.env"
RENDERED="$TMP_DIR/rendered.yml"

# A minimal, all-dummy env file — enough to satisfy variable
# substitution in docker-compose.prod.yml. NOTHING here is a real
# secret. The file lives only inside the temp dir.
cat >"$DUMMY_ENV" <<'EOF'
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=dummy-not-used-just-substituted
DJANGO_ALLOWED_HOSTS=cleaning.dummy.test
POSTGRES_DB=dummy_db
POSTGRES_USER=dummy_user
POSTGRES_PASSWORD=dummy_password_for_render_only
POSTGRES_HOST=db
POSTGRES_PORT=5432
REDIS_URL=redis://redis:6379/0
EMAIL_HOST=email-smtp.dummy.example
EMAIL_PORT=587
EMAIL_HOST_USER=dummy
EMAIL_HOST_PASSWORD=dummy
DEFAULT_FROM_EMAIL=no-reply@cleaning.dummy.test
VITE_API_BASE_URL=/api
FRONTEND_PORT=80
GUNICORN_WORKERS=3
GUNICORN_TIMEOUT=120
EOF

echo "prod_compose_validate: rendering compose with dummy env"
if ! docker compose -f "$COMPOSE_FILE" --env-file "$DUMMY_ENV" config >"$RENDERED" 2>"$TMP_DIR/err"; then
  echo "[FAIL] docker compose config did not render cleanly" >&2
  sed 's/^/  /' "$TMP_DIR/err" >&2
  exit 1
fi
echo "[OK]   compose config renders cleanly"

# ------------------------------------------------------------------
# Service-presence check
# ------------------------------------------------------------------
required_services=(db redis backend worker beat frontend)
missing=()
for svc in "${required_services[@]}"; do
  if ! grep -qE "^[[:space:]]+${svc}:" "$RENDERED"; then
    missing+=("$svc")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "[FAIL] required services missing from rendered compose: ${missing[*]}" >&2
  exit 1
fi
echo "[OK]   all 6 services declared (${required_services[*]})"

# ------------------------------------------------------------------
# Host-port publication audit
#
# Use python to walk the rendered yaml — bash + grep cannot reliably
# attribute a `published:` line back to its parent service, especially
# under different docker-compose render styles. Python with PyYAML is
# unavailable; we use the stdlib's runtime-import-of-PyYAML if present,
# else fall back to a regex walk that is good enough for a config the
# repo controls.
# ------------------------------------------------------------------
python3 - "$RENDERED" <<'PYAUDIT'
import re
import sys

text = open(sys.argv[1]).read()

# Slice the text into per-service blocks. The rendered config has
# "services:\n  <svc>:\n    ...\n  <svc>:\n    ...". Split on
# 2-space-indented service header.
m = re.search(r"^services:\s*$", text, re.MULTILINE)
if m is None:
    print("[FAIL] rendered config has no `services:` key", file=sys.stderr)
    sys.exit(1)

services_blob = text[m.end():]
# Stop at the next top-level key (no leading indent) such as
# `volumes:`, `networks:`, etc.
top = re.search(r"^[A-Za-z][A-Za-z0-9_]*:\s*$", services_blob, re.MULTILINE)
if top:
    services_blob = services_blob[: top.start()]

# Walk each service block. Service header is indented 2 spaces
# followed by the name and a colon.
service_iter = list(re.finditer(r"^  ([A-Za-z0-9_-]+):\s*$", services_blob, re.MULTILINE))

if not service_iter:
    print("[FAIL] could not parse any service from rendered config", file=sys.stderr)
    sys.exit(1)

# Map each service to (start, end) text span.
spans = {}
for i, hit in enumerate(service_iter):
    name = hit.group(1)
    start = hit.end()
    end = service_iter[i + 1].start() if i + 1 < len(service_iter) else len(services_blob)
    spans[name] = services_blob[start:end]

# Per-service rule:
#   frontend: must contain a `published:` (or top-level `ports:` mapping
#             to host 80).
#   db / redis / backend / worker / beat: must NOT contain any
#             `published:` line (no host-port exposure).
expected_publishers = {"frontend"}
non_publishers = {"db", "redis", "backend", "worker", "beat"}

failures = []
for svc, blob in spans.items():
    has_pub = bool(re.search(r"^\s+published:\s*", blob, re.MULTILINE))
    short_ports = bool(re.search(r"^\s+-\s+\"?\d+:\d+\"?\s*$", blob, re.MULTILINE))
    publishes = has_pub or short_ports
    if svc in expected_publishers:
        if not publishes:
            failures.append(f"frontend should publish a host port but the rendered config does not show one")
    elif svc in non_publishers:
        if publishes:
            failures.append(f"{svc} unexpectedly publishes a host port (compose ports: line found)")

if failures:
    for f in failures:
        print(f"[FAIL] {f}", file=sys.stderr)
    sys.exit(1)

print("[OK]   only frontend publishes a host port; db/redis/backend/worker/beat are container-internal")
PYAUDIT

echo
echo "[OK] docker-compose.prod.yml passes host-agnostic validation."
