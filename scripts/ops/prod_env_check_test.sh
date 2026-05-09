#!/usr/bin/env bash
#
# Sprint 10 — self-test for scripts/prod_env_check.sh.
#
# Constructs in-memory dummy "good" and "bad" env files and confirms
# the validator's exit code matches expectation. No real secrets, no
# external network. Safe to run anywhere.
#
# Usage:
#   ./scripts/ops/prod_env_check_test.sh
#
# Exits 0 if every dummy case behaves as expected; 1 otherwise.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHECKER="${REPO_ROOT}/scripts/prod_env_check.sh"

[[ -x "$CHECKER" ]] || {
  echo "[FAIL] $CHECKER not found / not executable" >&2
  exit 1
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

# Build a baseline well-formed prod env. Tests below COPY this and
# mutate ONE field at a time so we can attribute each [FAIL] to the
# field under test.
write_good_env() {
  local target="$1"
  cat >"$target" <<'EOF'
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=u8jKpQ3xZv2mN7aB9cD0eF1gH4iJ5kL6mN7oP8qR9sT0uV1wX2yZ3aB4cD5eF6gH
DJANGO_ALLOWED_HOSTS=cleaning.acme-pilot.test
CORS_ALLOWED_ORIGINS=https://cleaning.acme-pilot.test
CSRF_TRUSTED_ORIGINS=https://cleaning.acme-pilot.test
DJANGO_USE_X_FORWARDED_PROTO=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_LOG_LEVEL=WARNING
POSTGRES_DB=cleaning_ticket_db
POSTGRES_USER=cleaning_ticket_user
POSTGRES_PASSWORD=qS9pX7vM3hL2nB8c-1zT4eR6kY0jW5fGuI
POSTGRES_HOST=db
POSTGRES_PORT=5432
REDIS_URL=redis://redis:6379/0
EMAIL_HOST=email-smtp.eu-west-1.amazonaws.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=AKIAEXAMPLE0SES0USER
EMAIL_HOST_PASSWORD=BNExAmPlEkEy0NotARealSesPassWord12345==
DEFAULT_FROM_EMAIL=no-reply@cleaning.acme-pilot.test
VITE_API_BASE_URL=/api
FRONTEND_PORT=80
DRF_THROTTLE_ANON_RATE=60/minute
DRF_THROTTLE_USER_RATE=5000/hour
DRF_THROTTLE_AUTH_TOKEN_RATE=20/minute
DRF_THROTTLE_AUTH_TOKEN_REFRESH_RATE=60/minute
GUNICORN_WORKERS=3
GUNICORN_TIMEOUT=120
INVITATION_ACCEPT_FRONTEND_URL=https://cleaning.acme-pilot.test/invite/accept?token={token}
SENTRY_DSN=
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1
EOF
}

# Run the checker against an env file. Echo a single line per case:
#   [PASS-AS-EXPECTED] / [FAIL-AS-EXPECTED] / [UNEXPECTED]
# Mutate exit-codes and update the global FAILED counter accordingly.
run_case() {
  local label="$1"
  local env_file="$2"
  local expected_exit="$3"  # 0 = should pass, 1 = should fail

  set +e
  ENV_FILE="$env_file" "$CHECKER" >"$TMP_DIR/out" 2>"$TMP_DIR/err"
  local actual=$?
  set -e

  if [[ "$actual" == "$expected_exit" ]]; then
    if [[ "$actual" == "0" ]]; then
      printf '  [OK   pass-as-expected] %s\n' "$label"
    else
      printf '  [OK   fail-as-expected] %s\n' "$label"
    fi
    return 0
  else
    printf '  [FAIL  unexpected]      %s (got exit %s, want %s)\n' "$label" "$actual" "$expected_exit"
    if [[ -s "$TMP_DIR/out" ]]; then echo "    stdout:"; sed 's/^/      /' "$TMP_DIR/out"; fi
    if [[ -s "$TMP_DIR/err" ]]; then echo "    stderr:"; sed 's/^/      /' "$TMP_DIR/err"; fi
    return 1
  fi
}

FAILED=0

# ------------------------------------------------------------------
# Cases
# ------------------------------------------------------------------

echo "prod_env_check_test: running positive case"

GOOD="$TMP_DIR/good.env"
write_good_env "$GOOD"
run_case "good baseline must pass" "$GOOD" 0 || FAILED=$((FAILED+1))

echo
echo "prod_env_check_test: running negative cases (each mutates ONE field)"

# -- placeholder -- ---------------------------------------------------
BAD="$TMP_DIR/bad_placeholder.env"
write_good_env "$BAD"
sed -i 's|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=replace-with-a-long-random-secret-key|' "$BAD"
run_case "DJANGO_SECRET_KEY = placeholder must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- weak secret key (low entropy) -----------------------------------
BAD="$TMP_DIR/bad_weak_secret.env"
write_good_env "$BAD"
sed -i 's|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa|' "$BAD"
run_case "DJANGO_SECRET_KEY low entropy must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- short secret key ------------------------------------------------
BAD="$TMP_DIR/bad_short_secret.env"
write_good_env "$BAD"
sed -i 's|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=tooShort1234|' "$BAD"
run_case "DJANGO_SECRET_KEY too short must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- weak postgres password ------------------------------------------
BAD="$TMP_DIR/bad_pg_pw.env"
write_good_env "$BAD"
sed -i 's|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=password|' "$BAD"
run_case "POSTGRES_PASSWORD = 'password' must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- short postgres password (length floor) --------------------------
BAD="$TMP_DIR/bad_pg_short.env"
write_good_env "$BAD"
sed -i 's|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=tooShort1!|' "$BAD"
run_case "POSTGRES_PASSWORD < 16 chars must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- DJANGO_DEBUG = True ---------------------------------------------
BAD="$TMP_DIR/bad_debug.env"
write_good_env "$BAD"
sed -i 's|^DJANGO_DEBUG=False|DJANGO_DEBUG=True|' "$BAD"
run_case "DJANGO_DEBUG = True must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- ALLOWED_HOSTS contains localhost --------------------------------
BAD="$TMP_DIR/bad_hosts.env"
write_good_env "$BAD"
sed -i 's|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=localhost|' "$BAD"
run_case "DJANGO_ALLOWED_HOSTS=localhost must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- ALLOWED_HOSTS = '*' ---------------------------------------------
BAD="$TMP_DIR/bad_hosts_wild.env"
write_good_env "$BAD"
sed -i "s|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=*|" "$BAD"
run_case "DJANGO_ALLOWED_HOSTS=* must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- CORS plain-http origin ------------------------------------------
BAD="$TMP_DIR/bad_cors_http.env"
write_good_env "$BAD"
sed -i "s|^CORS_ALLOWED_ORIGINS=.*|CORS_ALLOWED_ORIGINS=http://cleaning.acme-pilot.test|" "$BAD"
run_case "CORS http:// must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- CSRF plain-http origin ------------------------------------------
BAD="$TMP_DIR/bad_csrf_http.env"
write_good_env "$BAD"
sed -i "s|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=http://cleaning.acme-pilot.test|" "$BAD"
run_case "CSRF http:// must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- missing SES (EMAIL_HOST empty) ----------------------------------
BAD="$TMP_DIR/bad_ses.env"
write_good_env "$BAD"
sed -i "s|^EMAIL_HOST=.*|EMAIL_HOST=|" "$BAD"
run_case "EMAIL_HOST empty must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- EMAIL_HOST still has <region> placeholder -----------------------
BAD="$TMP_DIR/bad_email_region.env"
write_good_env "$BAD"
sed -i "s|^EMAIL_HOST=.*|EMAIL_HOST=email-smtp.<region>.amazonaws.com|" "$BAD"
run_case "EMAIL_HOST <region> must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- DEFAULT_FROM_EMAIL = noreply@example.com ------------------------
BAD="$TMP_DIR/bad_from.env"
write_good_env "$BAD"
sed -i "s|^DEFAULT_FROM_EMAIL=.*|DEFAULT_FROM_EMAIL=no-reply@example.com|" "$BAD"
run_case "DEFAULT_FROM_EMAIL example.com must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- INVITATION_ACCEPT_FRONTEND_URL plain-http -----------------------
BAD="$TMP_DIR/bad_invite_http.env"
write_good_env "$BAD"
sed -i "s|^INVITATION_ACCEPT_FRONTEND_URL=.*|INVITATION_ACCEPT_FRONTEND_URL=http://cleaning.acme-pilot.test/invite/accept?token={token}|" "$BAD"
run_case "INVITATION_ACCEPT_FRONTEND_URL http:// must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- INVITATION_ACCEPT_FRONTEND_URL missing {token} ------------------
BAD="$TMP_DIR/bad_invite_token.env"
write_good_env "$BAD"
sed -i "s|^INVITATION_ACCEPT_FRONTEND_URL=.*|INVITATION_ACCEPT_FRONTEND_URL=https://cleaning.acme-pilot.test/invite/accept|" "$BAD"
run_case "INVITATION_ACCEPT_FRONTEND_URL missing {token} must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- DJANGO_USE_X_FORWARDED_PROTO != True ----------------------------
BAD="$TMP_DIR/bad_xfp.env"
write_good_env "$BAD"
sed -i "s|^DJANGO_USE_X_FORWARDED_PROTO=True|DJANGO_USE_X_FORWARDED_PROTO=False|" "$BAD"
run_case "DJANGO_USE_X_FORWARDED_PROTO=False must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- DJANGO_SESSION_COOKIE_SECURE != True ----------------------------
BAD="$TMP_DIR/bad_session_cookie.env"
write_good_env "$BAD"
sed -i "s|^DJANGO_SESSION_COOKIE_SECURE=True|DJANGO_SESSION_COOKIE_SECURE=False|" "$BAD"
run_case "DJANGO_SESSION_COOKIE_SECURE=False must fail" "$BAD" 1 || FAILED=$((FAILED+1))

# -- DJANGO_CSRF_COOKIE_SECURE != True -------------------------------
BAD="$TMP_DIR/bad_csrf_cookie.env"
write_good_env "$BAD"
sed -i "s|^DJANGO_CSRF_COOKIE_SECURE=True|DJANGO_CSRF_COOKIE_SECURE=False|" "$BAD"
run_case "DJANGO_CSRF_COOKIE_SECURE=False must fail" "$BAD" 1 || FAILED=$((FAILED+1))

echo
if [[ "$FAILED" == "0" ]]; then
  echo "[OK] all prod_env_check cases produced the expected exit code."
  exit 0
fi
echo "[FAIL] $FAILED case(s) did not match expectation." >&2
exit 1
