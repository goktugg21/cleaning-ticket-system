from __future__ import annotations

import re
from collections.abc import Mapping


PLACEHOLDER_SECRET_MARKERS = {
    "change-me",
    "replace-with",
    "dev-secret",
    "secret-key",
}

WEAK_DATABASE_PASSWORDS = {
    "",
    "admin",
    "changeme",
    "change-me",
    "cleaning_ticket_password",
    "password",
    "postgres",
    "test",
}

MAX_PRODUCTION_THROTTLES = {
    "anon": (60, "minute"),
    "auth_token": (20, "minute"),
    "auth_token_refresh": (60, "minute"),
    "user": (5000, "hour"),
}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def _parse_rate(rate: str) -> tuple[int, str] | None:
    match = re.fullmatch(r"\s*(\d+)\s*/\s*([a-zA-Z]+)\s*", str(rate))
    if not match:
        return None
    return int(match.group(1)), match.group(2).lower()


def _rate_exceeds(rate: str, max_count: int, max_period: str) -> bool:
    parsed = _parse_rate(rate)
    if parsed is None:
        return True
    count, period = parsed
    if period != max_period:
        return True
    return count > max_count


def get_production_settings_errors(settings_map: Mapping, environ: Mapping | None = None) -> list[str]:
    environ = environ or {}
    debug = _as_bool(settings_map.get("DEBUG", environ.get("DJANGO_DEBUG", "False")))
    if debug:
        return []

    errors = []

    secret = str(settings_map.get("SECRET_KEY") or "")
    lowered_secret = secret.lower()
    if not secret:
        errors.append("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG=False.")
    elif len(secret) < 50 or any(marker in lowered_secret for marker in PLACEHOLDER_SECRET_MARKERS):
        errors.append("DJANGO_SECRET_KEY must be a long non-placeholder value in production.")

    allowed_hosts = _list(settings_map.get("ALLOWED_HOSTS"))
    if not allowed_hosts:
        errors.append("DJANGO_ALLOWED_HOSTS must be set in production.")
    if any(host in {"*", ".localhost", "localhost", "127.0.0.1"} for host in allowed_hosts):
        errors.append("DJANGO_ALLOWED_HOSTS must not be empty, wildcard, or localhost-only in production.")

    cors_origins = _list(settings_map.get("CORS_ALLOWED_ORIGINS"))
    if not cors_origins:
        errors.append("CORS_ALLOWED_ORIGINS must be set in production.")

    csrf_origins = _list(settings_map.get("CSRF_TRUSTED_ORIGINS"))
    if not csrf_origins:
        errors.append("CSRF_TRUSTED_ORIGINS must be set in production.")

    for name, origins in {
        "CORS_ALLOWED_ORIGINS": cors_origins,
        "CSRF_TRUSTED_ORIGINS": csrf_origins,
    }.items():
        for origin in origins:
            if origin == "*" or origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
                errors.append(f"{name} contains a non-production origin: {origin}.")

    throttle_rates = settings_map.get("REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_RATES", {})
    for scope, (max_count, max_period) in MAX_PRODUCTION_THROTTLES.items():
        rate = throttle_rates.get(scope)
        if not rate:
            errors.append(f"DRF throttle rate for '{scope}' must be set in production.")
        elif _rate_exceeds(rate, max_count, max_period):
            errors.append(f"DRF throttle rate for '{scope}' is too permissive for production: {rate}.")

    db_password = str(settings_map.get("DATABASES", {}).get("default", {}).get("PASSWORD") or "")
    if db_password.lower() in WEAK_DATABASE_PASSWORDS or len(db_password) < 12:
        errors.append("POSTGRES_PASSWORD is missing, placeholder, or too weak for production.")

    return errors


def validate_production_settings(settings_map: Mapping, environ: Mapping | None = None) -> None:
    errors = get_production_settings_errors(settings_map, environ=environ)
    if errors:
        formatted = "\n - ".join(errors)
        raise RuntimeError(f"Unsafe production settings:\n - {formatted}")
