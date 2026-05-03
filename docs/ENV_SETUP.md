# Production Environment Setup

This document explains how to prepare the production `.env` file.

## 1. Copy the production template

    cp .env.production.example .env

Do not commit `.env`.

## 2. Generate a strong Django secret key

    ./scripts/generate_secret_key.sh

Copy the generated value into:

    DJANGO_SECRET_KEY=

## 3. Set domain values

For a real domain such as `tickets.example.com`, set:

    DJANGO_ALLOWED_HOSTS=tickets.example.com
    CORS_ALLOWED_ORIGINS=https://tickets.example.com
    CSRF_TRUSTED_ORIGINS=https://tickets.example.com

Use the real public domain. Do not use localhost values in production.

## 4. Set PostgreSQL credentials

Use a strong unique password:

    POSTGRES_PASSWORD=replace-with-a-strong-password

The app containers use:

    POSTGRES_HOST=db
    POSTGRES_PORT=5432

## 5. Configure Redis

For Docker Compose production:

    REDIS_URL=redis://redis:6379/0

## 6. Configure email

Email notifications use SMTP.

For production, Amazon SES SMTP can be used:

    EMAIL_HOST=email-smtp.<region>.amazonaws.com
    EMAIL_PORT=587
    EMAIL_HOST_USER=replace-with-amazon-ses-smtp-user
    EMAIL_HOST_PASSWORD=replace-with-amazon-ses-smtp-password
    EMAIL_USE_TLS=True
    DEFAULT_FROM_EMAIL=no-reply@your-domain.com

Use the real SMTP endpoint, username, password, and sender email provided by the production email provider/admin.

Do not commit real SMTP credentials.

After setting SMTP, run:

    ENV_FILE=.env ./scripts/prod_env_check.sh
    ./scripts/notification_email_test.sh

See also:

    docs/SMTP_AMAZON_SES.md

## 7. Configure HTTPS flags

After HTTPS is ready, production should use:

    DJANGO_SECURE_SSL_REDIRECT=True
    DJANGO_SESSION_COOKIE_SECURE=True
    DJANGO_CSRF_COOKIE_SECURE=True
    DJANGO_USE_X_FORWARDED_PROTO=True
    DJANGO_SECURE_HSTS_SECONDS=31536000

Only enable HSTS after confirming HTTPS works correctly.

## 8. Optional Sentry

Sentry is disabled when `SENTRY_DSN` is empty.

To enable it:

    SENTRY_DSN=https://your-sentry-dsn
    SENTRY_ENVIRONMENT=production
    SENTRY_TRACES_SAMPLE_RATE=0.0

## 9. Validate the final environment file

Run:

    ./scripts/prod_env_check.sh

For checking the template file only:

    ENV_FILE=.env.production.example ALLOW_PLACEHOLDERS=YES ./scripts/prod_env_check.sh
