#!/usr/bin/env bash
#
# Sprint 10 — pre-pilot readiness summary.
#
# Reports OK / WARN / FAIL across every gate that can be checked
# without exposing the operator to a real production host. Designed
# to be safe to run on dev OR on the actual pilot host once it
# arrives. No real secrets are required.
#
# Inputs (all optional):
#   ENV_FILE            path to the .env to validate
#                       (default: .env.production if present, else .env)
#   PROD_COMPOSE_FILE   path to docker-compose.prod.yml
#                       (default: docker-compose.prod.yml)
#   DOMAIN              if set, runs scripts/ops/prod_health.sh against it
#   SKIP_BACKEND_CHECK  set to YES to skip the
#                       check_no_demo_accounts call (e.g. backend not up)
#
# The script prints a single OK / WARN / FAIL marker per gate and a
# final summary. It exits 0 if no FAILs were emitted, 1 otherwise.
# WARNs do not fail the report — they document the still-open
# host-only checks the operator must perform manually.
#
# This script NEVER prints secret values.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROD_COMPOSE_FILE="${PROD_COMPOSE_FILE:-$REPO_ROOT/docker-compose.prod.yml}"
SKIP_BACKEND_CHECK="${SKIP_BACKEND_CHECK:-NO}"

# Resolve env file: .env.production wins; fall back to .env; else
# leave empty (env-file gates will WARN, not FAIL).
if [[ -z "${ENV_FILE:-}" ]]; then
  if [[ -f "$REPO_ROOT/.env.production" ]]; then
    ENV_FILE="$REPO_ROOT/.env.production"
  elif [[ -f "$REPO_ROOT/.env" ]]; then
    ENV_FILE="$REPO_ROOT/.env"
  else
    ENV_FILE=""
  fi
fi

OK_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

ok()   { printf '  [OK]   %s\n'   "$*"; OK_COUNT=$((OK_COUNT+1)); }
warn() { printf '  [WARN] %s\n'   "$*"; WARN_COUNT=$((WARN_COUNT+1)); }
err()  { printf '  [FAIL] %s\n'   "$*" >&2; FAIL_COUNT=$((FAIL_COUNT+1)); }

section() { printf '\n# %s\n' "$*"; }

# ------------------------------------------------------------------
# 1. git commit
# ------------------------------------------------------------------
section "git"
if cd "$REPO_ROOT" && git rev-parse HEAD >/dev/null 2>&1; then
  COMMIT="$(git rev-parse --short HEAD)"
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  ok "current commit: $COMMIT (branch: $BRANCH)"
  if [[ -n "$(git status --porcelain 2>/dev/null | grep -v PRODUCTION_READINESS_AUDIT.md || true)" ]]; then
    warn "working tree has uncommitted changes (excluding PRODUCTION_READINESS_AUDIT.md)"
  else
    ok "working tree clean (PRODUCTION_READINESS_AUDIT.md exempt)"
  fi
else
  err "not a git checkout"
fi

# ------------------------------------------------------------------
# 2. env file existence + permissions
# ------------------------------------------------------------------
section "env file"
if [[ -z "$ENV_FILE" ]]; then
  warn "no .env.production or .env present — env validation skipped"
elif [[ ! -f "$ENV_FILE" ]]; then
  err "ENV_FILE=$ENV_FILE does not exist"
else
  ok "env file present: $ENV_FILE"
  # File permissions: secrets file must NOT be world-readable.
  perms="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || stat -f '%A' "$ENV_FILE" 2>/dev/null || echo '???')"
  if [[ "$perms" =~ ^[0-9]+$ ]]; then
    last_digit="${perms: -1}"
    if [[ "$last_digit" != "0" ]]; then
      warn "env file mode is $perms — should be 600 / 640 (no world bits)"
    else
      ok "env file mode is $perms (no world bits)"
    fi
  else
    warn "could not determine env file mode"
  fi
fi

# ------------------------------------------------------------------
# 3. prod_env_check
# ------------------------------------------------------------------
section "prod_env_check"
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
  if ENV_FILE="$ENV_FILE" "$REPO_ROOT/scripts/prod_env_check.sh" >/dev/null 2>&1; then
    ok "prod_env_check.sh passed for $ENV_FILE"
  else
    # Run again to capture stderr but suppress stdout so secrets
    # cannot leak (the validator never echoes values, but we
    # forward only the [FAIL] / [WARN] lines anyway).
    if [[ "$ENV_FILE" == *".env.production.example" || "$ENV_FILE" == *".env.example" ]]; then
      warn "$ENV_FILE is a template (placeholders expected) — set ALLOW_PLACEHOLDERS=YES if you intentionally want to validate it"
    else
      err "prod_env_check.sh failed against $ENV_FILE — re-run directly to see details"
    fi
  fi
else
  warn "skipping prod_env_check (no env file)"
fi

# ------------------------------------------------------------------
# 4. prod compose validation
# ------------------------------------------------------------------
section "prod compose"
if "$REPO_ROOT/scripts/ops/prod_compose_validate.sh" >/dev/null 2>&1; then
  ok "prod_compose_validate.sh passed"
else
  err "prod_compose_validate.sh failed — re-run directly to see details"
fi

# ------------------------------------------------------------------
# 5. docker compose ps (best-effort, dev-friendly)
# ------------------------------------------------------------------
section "running stack"
if command -v docker >/dev/null 2>&1; then
  PS_OUT="$(docker compose -f "$PROD_COMPOSE_FILE" ps --status running --format '{{.Service}}' 2>/dev/null || true)"
  if [[ -z "$PS_OUT" ]]; then
    # Try the dev compose file too, since this script is meant to
    # be safe to run on a dev host as well.
    PS_DEV="$(docker compose ps --status running --format '{{.Service}}' 2>/dev/null || true)"
    if [[ -n "$PS_DEV" ]]; then
      ok "no production stack running (dev stack up: $(echo "$PS_DEV" | tr '\n' ' '))"
    else
      warn "no docker compose stack running"
    fi
  else
    ok "production stack running: $(echo "$PS_OUT" | tr '\n' ' ')"
  fi
else
  warn "docker CLI unavailable — cannot inspect running stack"
fi

# ------------------------------------------------------------------
# 6. demo-account guard (only if a backend container is reachable)
# ------------------------------------------------------------------
section "demo accounts guard"
if [[ "$SKIP_BACKEND_CHECK" == "YES" ]]; then
  warn "demo-account guard skipped (SKIP_BACKEND_CHECK=YES)"
else
  CONTAINER=""
  if docker compose -f "$PROD_COMPOSE_FILE" ps backend --status running --format '{{.Name}}' 2>/dev/null | grep -q .; then
    CONTAINER_CMD="docker compose -f $PROD_COMPOSE_FILE exec -T backend"
    CONTAINER="prod"
  elif docker compose ps backend --status running --format '{{.Name}}' 2>/dev/null | grep -q .; then
    CONTAINER_CMD="docker compose exec -T backend"
    CONTAINER="dev"
  fi
  if [[ -n "$CONTAINER" ]]; then
    if $CONTAINER_CMD python manage.py check_no_demo_accounts >/dev/null 2>&1; then
      ok "check_no_demo_accounts passed (against $CONTAINER stack)"
    else
      err "check_no_demo_accounts FAILED — demo accounts present"
    fi
  else
    warn "no backend container running — demo-account guard skipped"
  fi
fi

# ------------------------------------------------------------------
# 7. backup / restore artifacts
# ------------------------------------------------------------------
section "backup / restore"
for f in scripts/backup_postgres.sh scripts/restore_postgres.sh \
         scripts/backup_media.sh scripts/restore_media.sh \
         scripts/ops/pg_backup.sh scripts/ops/pg_restore_template.sh; do
  if [[ -f "$REPO_ROOT/$f" ]]; then
    ok "present: $f"
  else
    err "missing: $f"
  fi
done

# Optional backup-output directory presence (not a hard requirement
# at install time — it's the operator's responsibility to point the
# scripts at an off-host location).
for d in /var/backups/cleaning-ticket /opt/cleaning-ticket/backups ./backups; do
  if [[ -d "$d" ]]; then
    ok "backup directory found: $d"
    break
  fi
done || true

# ------------------------------------------------------------------
# 8. domain-only checks (skipped unless DOMAIN is set)
# ------------------------------------------------------------------
section "domain checks"
if [[ -n "${DOMAIN:-}" ]]; then
  if DOMAIN="$DOMAIN" "$REPO_ROOT/scripts/ops/prod_health.sh" >/dev/null 2>&1; then
    ok "prod_health.sh passed for DOMAIN=$DOMAIN"
  else
    err "prod_health.sh failed for DOMAIN=$DOMAIN"
  fi
else
  warn "DOMAIN not set — health-endpoint check skipped (host-only)"
fi

if [[ -n "${SMTP_TEST_RECIPIENT:-}" ]]; then
  warn "SMTP delivery is host-only — see scripts/ops/smtp_smoke.sh"
else
  warn "SMTP_TEST_RECIPIENT not set — SES smoke skipped (host-only)"
fi

# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------
echo
echo "Summary: $OK_COUNT OK · $WARN_COUNT WARN · $FAIL_COUNT FAIL"
if (( FAIL_COUNT > 0 )); then
  echo "FAIL count > 0 — pilot launch is blocked." >&2
  exit 1
fi
if (( WARN_COUNT > 0 )); then
  echo "WARN count > 0 — host-only items remain. Continue once host is ready."
fi
echo "OK to proceed if all FAILs are 0 and WARNs are intentional."
exit 0
