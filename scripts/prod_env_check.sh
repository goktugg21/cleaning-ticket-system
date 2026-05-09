#!/usr/bin/env bash
#
# Validate a production env file before bringing the stack up. The
# validator NEVER prints secret values — only key names and the
# nature of the failure (e.g. "POSTGRES_PASSWORD is too weak", not
# the password itself).
#
# Modes:
#   ENV_FILE=.env.production scripts/prod_env_check.sh             # strict
#   ALLOW_PLACEHOLDERS=YES   scripts/prod_env_check.sh             # allows
#                                                                    `replace-with-*` placeholders
#                                                                    so .env.production.example
#                                                                    can be smoke-tested
#   ALLOW_LOCAL_ORIGINS=YES  scripts/prod_env_check.sh             # allows http://localhost:*
#                                                                    in CORS / CSRF (dev-only)
#
# Sprint 10 strengthens the validator:
#   - SES fields (EMAIL_HOST/USER/PASSWORD/DEFAULT_FROM_EMAIL) are
#     REQUIRED in production, not just recommended.
#   - INVITATION_ACCEPT_FRONTEND_URL must be https:// and carry
#     `{token}`.
#   - DJANGO_USE_X_FORWARDED_PROTO must be True (we run HTTP-internal
#     behind NPM; without trusting the header request.is_secure()
#     stays False and Secure cookies never set).
#   - DJANGO_SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE must be True
#     in production (independent of SSL_REDIRECT).
#   - POSTGRES_PASSWORD must be >= 16 chars (a length floor on top of
#     the well-known-weak-passwords blocklist).

set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"
ALLOW_PLACEHOLDERS="${ALLOW_PLACEHOLDERS:-NO}"
ALLOW_LOCAL_ORIGINS="${ALLOW_LOCAL_ORIGINS:-NO}"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

ok() {
  echo "[OK] $*"
}

[[ -f "$ENV_FILE" ]] || fail "Environment file not found: $ENV_FILE"

python3 - "$ENV_FILE" "$ALLOW_PLACEHOLDERS" "$ALLOW_LOCAL_ORIGINS" <<'PYCHECK'
from pathlib import Path
import sys

env_file = Path(sys.argv[1])
allow_placeholders = sys.argv[2] == "YES"
allow_local_origins = sys.argv[3] == "YES"

required = [
    "DJANGO_DEBUG",
    "DJANGO_SECRET_KEY",
    "DJANGO_ALLOWED_HOSTS",
    "CORS_ALLOWED_ORIGINS",
    "CSRF_TRUSTED_ORIGINS",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "REDIS_URL",
    "VITE_API_BASE_URL",
    "FRONTEND_PORT",
    "GUNICORN_WORKERS",
    "GUNICORN_TIMEOUT",
    "DRF_THROTTLE_ANON_RATE",
    "DRF_THROTTLE_USER_RATE",
    "DRF_THROTTLE_AUTH_TOKEN_RATE",
    "DRF_THROTTLE_AUTH_TOKEN_REFRESH_RATE",
    # Sprint 10: SES is required, not optional, when DJANGO_DEBUG=False.
    # Pilot launch needs invitation + password-reset emails to deliver,
    # so an empty / missing email config is a hard failure.
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "DEFAULT_FROM_EMAIL",
    # Sprint 10: invitations rely on this URL to construct the email
    # body. A missing or http:// URL silently breaks the invitation
    # flow.
    "INVITATION_ACCEPT_FRONTEND_URL",
]

recommended = [
    "SENTRY_DSN",
    "SENTRY_ENVIRONMENT",
    "SENTRY_TRACES_SAMPLE_RATE",
]

values = {}

for raw_line in env_file.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value_raw = line.split("=", 1)
    values[key.strip()] = value_raw.strip().strip('"').strip("'")

errors = []
warnings = []

def value(key):
    return values.get(key, "")

for key in required:
    if key not in values:
        errors.append(f"Missing required variable: {key}")
    elif value(key) == "":
        errors.append(f"Required variable is empty: {key}")

placeholder_markers = [
    "replace-with",
    "example.com",
    "your-sentry-dsn",
    "smtp.example.com",
    "your-domain.example",
    "<region>",
]

# Sentinel exact values that are clearly placeholders (not partial
# matches against a real prod value).
placeholder_exact = {
    "ci-dummy-secret-do-not-use-in-prod",
    "ci-dummy-postgres-password",
    "changeme",
    "test",
    "dummy",
    "placeholder",
}

if not allow_placeholders:
    for key, val in values.items():
        lowered = val.lower()
        if any(marker in lowered for marker in placeholder_markers):
            errors.append(f"{key} still contains placeholder value")
        if lowered in placeholder_exact:
            errors.append(f"{key} contains a known placeholder/dummy value")

if value("DJANGO_DEBUG") != "False":
    errors.append("DJANGO_DEBUG must be False in production")

secret = value("DJANGO_SECRET_KEY")
if secret and not allow_placeholders:
    if len(secret) < 50:
        errors.append("DJANGO_SECRET_KEY looks too short; generate a stronger key (>= 50 chars)")
    # Block trivially-low-entropy keys: all-ascii-letters, all-digits,
    # or single repeated character. Real Django keys mix letters,
    # digits, and punctuation.
    if secret.isalpha() or secret.isdigit() or len(set(secret)) < 10:
        errors.append("DJANGO_SECRET_KEY has too little entropy")

for key in ["DJANGO_ALLOWED_HOSTS", "CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"]:
    val = value(key)
    if val == "*":
        errors.append(f"{key} cannot be '*' in production")
    if val.split(",")[0].strip() in {"localhost", "127.0.0.1"}:
        errors.append(f"{key} starts with localhost/127.0.0.1")

# DJANGO_ALLOWED_HOSTS must not list the loopback or wildcard hosts.
hosts = [h.strip() for h in value("DJANGO_ALLOWED_HOSTS").split(",") if h.strip()]
for host in hosts:
    if host in {"*", "localhost", "127.0.0.1", ".localhost"}:
        errors.append(f"DJANGO_ALLOWED_HOSTS contains forbidden host: {host}")

for key in ["CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"]:
    val = value(key)
    if val and not allow_local_origins:
        origins = [item.strip() for item in val.split(",") if item.strip()]
        for origin in origins:
            if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
                errors.append(f"{key} contains local origin: {origin}")
            elif origin.startswith("http://"):
                # Sprint 10: any plain-http origin is a hard fail in
                # production — TLS terminates at NPM upstream and
                # browsers must hit https only.
                errors.append(f"{key} contains plain-http origin: {origin}")
            elif not origin.startswith("https://") and "example.com" not in origin:
                errors.append(f"{key} should use https:// origin in production: {origin}")

# POSTGRES_PASSWORD: deny the well-known weaks AND require length floor.
pg_pw = value("POSTGRES_PASSWORD")
if pg_pw.lower() in {"password", "postgres", "admin", "test", "changeme"}:
    errors.append("POSTGRES_PASSWORD is too weak (well-known value)")
if pg_pw and not allow_placeholders and len(pg_pw) < 16:
    errors.append("POSTGRES_PASSWORD is too short (need >= 16 chars)")

# Cookie / proxy security must be on in prod regardless of SSL_REDIRECT
# (we do NOT enable SSL_REDIRECT because NPM owns the redirect, but
# the cookie + proxy flags must still be set).
if not allow_placeholders:
    if value("DJANGO_USE_X_FORWARDED_PROTO") != "True":
        errors.append("DJANGO_USE_X_FORWARDED_PROTO must be True (NPM upstream sends proxied https)")
    if value("DJANGO_SESSION_COOKIE_SECURE") != "True":
        errors.append("DJANGO_SESSION_COOKIE_SECURE must be True in production")
    if value("DJANGO_CSRF_COOKIE_SECURE") != "True":
        errors.append("DJANGO_CSRF_COOKIE_SECURE must be True in production")

# Recommended (warn only) variables.
for key in recommended:
    if key not in values:
        warnings.append(f"Recommended variable missing: {key}")

if value("DJANGO_SECURE_SSL_REDIRECT") == "True":
    for key in [
        "DJANGO_SESSION_COOKIE_SECURE",
        "DJANGO_CSRF_COOKIE_SECURE",
        "DJANGO_USE_X_FORWARDED_PROTO",
    ]:
        if value(key) != "True":
            errors.append(f"{key} should be True when HTTPS redirect is enabled")

if value("DJANGO_SECURE_HSTS_SECONDS") and value("DJANGO_SECURE_HSTS_SECONDS") != "0":
    try:
        seconds = int(value("DJANGO_SECURE_HSTS_SECONDS"))
        if seconds < 31536000:
            warnings.append("DJANGO_SECURE_HSTS_SECONDS is lower than 31536000")
    except ValueError:
        errors.append("DJANGO_SECURE_HSTS_SECONDS must be an integer")

# Sprint 10: invitation-accept URL must be https and carry the token
# placeholder. A missing token placeholder bricks every invitation
# email — the recipient gets a URL with no actual token.
invite_url = value("INVITATION_ACCEPT_FRONTEND_URL")
if invite_url and not allow_placeholders:
    if not invite_url.startswith("https://"):
        errors.append("INVITATION_ACCEPT_FRONTEND_URL must use https://")
    if "{token}" not in invite_url:
        errors.append("INVITATION_ACCEPT_FRONTEND_URL must contain '{token}' placeholder")

# Sprint 10: DEFAULT_FROM_EMAIL sanity (must look like an email and
# not be a placeholder domain).
from_email = value("DEFAULT_FROM_EMAIL")
if from_email and not allow_placeholders:
    if "@" not in from_email:
        errors.append("DEFAULT_FROM_EMAIL is not a valid email address")
    if from_email.lower().endswith("@example.com") or from_email.lower().endswith(".example"):
        errors.append("DEFAULT_FROM_EMAIL still uses an example/placeholder domain")

# Sprint 10: EMAIL_HOST sanity (the SES region template must be
# substituted before launch).
email_host = value("EMAIL_HOST")
if email_host and not allow_placeholders:
    if "<region>" in email_host or email_host.lower() == "localhost":
        errors.append("EMAIL_HOST still uses a placeholder/loopback value")

print(f"Checked environment file: {env_file}")

for warning in warnings:
    print(f"[WARN] {warning}")

if errors:
    for error in errors:
        print(f"[FAIL] {error}", file=sys.stderr)
    raise SystemExit(1)

print("[OK] Production environment preflight passed")
PYCHECK
