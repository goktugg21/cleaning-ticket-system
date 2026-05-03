# Amazon SES SMTP Setup

This project can send ticket notification emails through Amazon SES SMTP.

## Current state

Email sending is supported by Django SMTP settings.

If `EMAIL_HOST` is empty, the project uses Django console email backend.

If `EMAIL_HOST` is set, Django uses SMTP email backend.

## Required values

The production `.env` needs these values:

    EMAIL_HOST=
    EMAIL_PORT=587
    EMAIL_HOST_USER=
    EMAIL_HOST_PASSWORD=
    EMAIL_USE_TLS=True
    DEFAULT_FROM_EMAIL=

For Amazon SES, the provider/admin should give:

- SMTP endpoint / host
- SMTP username
- SMTP password
- Verified sender email address
- Port and TLS requirement

Do not commit real SMTP credentials.

## Example shape

Use the real Amazon SES SMTP endpoint and credentials:

    EMAIL_HOST=email-smtp.<region>.amazonaws.com
    EMAIL_PORT=587
    EMAIL_HOST_USER=replace-with-amazon-ses-smtp-user
    EMAIL_HOST_PASSWORD=replace-with-amazon-ses-smtp-password
    EMAIL_USE_TLS=True
    DEFAULT_FROM_EMAIL=no-reply@your-domain.com

The exact region and sender email must come from the production email provider/admin.

## Validate settings

After filling `.env`, run:

    ENV_FILE=.env ./scripts/prod_env_check.sh

## Test notification email

After SMTP is configured, run:

    ./scripts/notification_email_test.sh

Then confirm:

- The command succeeds.
- The email is received.
- The sender address is correct.
- The email does not go to spam.
- Ticket notification content is acceptable.

## Local demo note

For local HTTP demo, SMTP is not required unless email delivery will be demonstrated.

The local demo can run with console email backend when `EMAIL_HOST` is empty.

## Production note

HTTPS is handled outside this application by firewall or Nginx Proxy Manager.

SMTP is independent from HTTPS termination. The app only needs valid SMTP values in `.env`.
