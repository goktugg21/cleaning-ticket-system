#!/usr/bin/env bash
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
]

recommended = [
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "DEFAULT_FROM_EMAIL",
    "SENTRY_DSN",
    "SENTRY_ENVIRONMENT",
    "SENTRY_TRACES_SAMPLE_RATE",
]

values = {}

for raw_line in env_file.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip().strip('"').strip("'")

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
]

if not allow_placeholders:
    for key, val in values.items():
        lowered = val.lower()
        if any(marker in lowered for marker in placeholder_markers):
            errors.append(f"{key} still contains placeholder value")

if value("DJANGO_DEBUG") != "False":
    errors.append("DJANGO_DEBUG must be False in production")

secret = value("DJANGO_SECRET_KEY")
if secret and len(secret) < 50 and not allow_placeholders:
    errors.append("DJANGO_SECRET_KEY looks too short; generate a stronger key")

for key in ["DJANGO_ALLOWED_HOSTS", "CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"]:
    val = value(key)
    if val in {"*", "http://localhost:5173", "http://127.0.0.1:5173"}:
        errors.append(f"{key} is not production-safe: {val}")

for key in ["CORS_ALLOWED_ORIGINS", "CSRF_TRUSTED_ORIGINS"]:
    val = value(key)
    if val and not allow_local_origins:
        origins = [item.strip() for item in val.split(",") if item.strip()]
        for origin in origins:
            if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
                errors.append(f"{key} contains local origin: {origin}")
            if not origin.startswith("https://") and "example.com" not in origin:
                errors.append(f"{key} should use https:// origin in production: {origin}")

if value("POSTGRES_PASSWORD").lower() in {"password", "postgres", "admin", "test", "changeme"}:
    errors.append("POSTGRES_PASSWORD is too weak")

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

print(f"Checked environment file: {env_file}")

for warning in warnings:
    print(f"[WARN] {warning}")

if errors:
    for error in errors:
        print(f"[FAIL] {error}", file=sys.stderr)
    raise SystemExit(1)

print("[OK] Production environment preflight passed")
PYCHECK
