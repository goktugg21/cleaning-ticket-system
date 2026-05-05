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

### Password reset link target

The password reset email embeds the reset URL produced by `PASSWORD_RESET_FRONTEND_URL` from the environment. The URL is rendered with Python `str.format` so it must contain `{uid}` and `{token}` literal placeholders.

Recommended value (matches the React route at `/password/reset/confirm`):

    PASSWORD_RESET_FRONTEND_URL=https://tickets.example.com/password/reset/confirm?uid={uid}&token={token}

If the variable is empty, the email still sends but contains the raw `uid` and `token` only, which is poor UX. Set this in production.

## 7. Configure HTTPS flags

After HTTPS is ready, production should use:

    DJANGO_SECURE_SSL_REDIRECT=True
    DJANGO_SESSION_COOKIE_SECURE=True
    DJANGO_CSRF_COOKIE_SECURE=True
    DJANGO_USE_X_FORWARDED_PROTO=True
    DJANGO_SECURE_HSTS_SECONDS=31536000

Only enable HSTS after confirming HTTPS works correctly.

## 8. Celery (async email)

The notification email pipeline is asynchronous. Email sending happens inside a Celery worker so a slow SMTP server cannot block ticket creation, status changes, assignment, or password reset.

Required env vars:

    CELERY_BROKER_URL=redis://redis:6379/1
    CELERY_RESULT_BACKEND=redis://redis:6379/2
    CELERY_TASK_ALWAYS_EAGER=False
    NOTIFICATION_QUEUED_TIMEOUT_MINUTES=30

What each one does:

- `CELERY_BROKER_URL`: Redis connection string the producer uses to enqueue tasks. Defaults to db `1` so it does not collide with anything else on the existing redis container.
- `CELERY_RESULT_BACKEND`: Redis connection string for the task result backend. Defaults to db `2` for the same reason.
- `CELERY_TASK_ALWAYS_EAGER`: Dev-only override. When `True` the task runs inline in the request thread instead of being dispatched to the worker. The Django test runner forces this to `True` regardless of env so `manage.py test` does not need a running worker.
- `NOTIFICATION_QUEUED_TIMEOUT_MINUTES`: How long a `NotificationLog` row may stay in `QUEUED` before a future sweeper task marks it `FAILED`. The sweeper itself ships in a later batch; the constant is in place so the value is decided up front.

Production must keep `CELERY_TASK_ALWAYS_EAGER=False`. With eager mode in prod, slow SMTP would once again block the request thread, which is the exact problem this change is meant to remove.

## 9. Invitations

User onboarding goes through invitation links. The backend signs each invitation with a one-time, hashed-at-rest token; the raw token is only present in the email body.

Required env vars:

    INVITATION_TTL_DAYS=7
    INVITATION_ACCEPT_FRONTEND_URL=https://tickets.example.com/invite/accept?token={token}

What each one does:

- `INVITATION_TTL_DAYS`: how long an invitation stays usable before it expires automatically. Default 7 days. Acceptable to lower for stricter policies; raising it weakens the security argument.
- `INVITATION_ACCEPT_FRONTEND_URL`: the URL written into the email body. Must contain `{token}` as a literal placeholder. The backend formats it with the raw token at send time. If left empty, the email body shows a placeholder string instead of a link, which is bad UX. Set this in production.

The matching React route is `/invite/accept`, which calls `GET /api/auth/invitations/preview/?token=...` on mount and submits to `POST /api/auth/invitations/accept/` with `{token, new_password}`.

## 10. Optional Sentry

Sentry is disabled when `SENTRY_DSN` is empty.

To enable it:

    SENTRY_DSN=https://your-sentry-dsn
    SENTRY_ENVIRONMENT=production
    SENTRY_TRACES_SAMPLE_RATE=0.0

## 11. Validate the final environment file

Run:

    ./scripts/prod_env_check.sh

For checking the template file only:

    ENV_FILE=.env.production.example ALLOW_PLACEHOLDERS=YES ./scripts/prod_env_check.sh
