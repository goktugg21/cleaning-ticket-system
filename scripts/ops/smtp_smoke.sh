#!/usr/bin/env bash
#
# Send a one-line SES smoke email from inside the production
# backend container. Use to verify EMAIL_HOST / EMAIL_HOST_USER /
# EMAIL_HOST_PASSWORD / EMAIL_USE_TLS / DEFAULT_FROM_EMAIL are
# configured correctly after a deploy.
#
# Usage:
#   ./scripts/ops/smtp_smoke.sh you@example.com
#
# The recipient address is the only required input. Everything
# else (sender, host, credentials) comes from the running
# container's env. No credentials are echoed.
#
# Exits non-zero if Django raises during send_mail.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
RECIPIENT="${1:-}"

if [[ -z "$RECIPIENT" ]]; then
  echo "Usage: $0 <recipient-email-address>" >&2
  exit 2
fi

if ! [[ "$RECIPIENT" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]; then
  echo "Recipient does not look like a valid email: $RECIPIENT" >&2
  exit 2
fi

echo "Sending SES smoke email to $RECIPIENT via $COMPOSE_FILE..."
docker compose -f "$COMPOSE_FILE" exec -T backend \
  python manage.py shell -c "
from django.core.mail import send_mail
sent = send_mail(
    subject='[pilot] SES smoke',
    message='SES SMTP smoke from $(hostname) — if you read this, the credentials are correct.',
    from_email=None,
    recipient_list=['$RECIPIENT'],
    fail_silently=False,
)
print('queued', sent)
"

echo
echo "[OK] send_mail returned without error. Confirm delivery to $RECIPIENT."
