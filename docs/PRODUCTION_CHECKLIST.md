# Production Checklist

## Current production target

This checklist tracks the minimum work required before running the cleaning ticket system in production.

## Environment

- [ ] Set `DJANGO_DEBUG=False`.
- [ ] Generate a strong `DJANGO_SECRET_KEY`.
- [ ] Set `DJANGO_ALLOWED_HOSTS` to the real domain.
- [ ] Set `CORS_ALLOWED_ORIGINS` to the real frontend origin.
- [ ] Set `CSRF_TRUSTED_ORIGINS` to the real frontend origin.
- [ ] Use strong PostgreSQL credentials.
- [x] Do not commit `.env`.

## HTTPS and proxy

- [ ] Put the app behind HTTPS.
- [ ] Enable `DJANGO_SECURE_SSL_REDIRECT=True` after HTTPS is ready.
- [ ] Enable `DJANGO_SESSION_COOKIE_SECURE=True`.
- [ ] Enable `DJANGO_CSRF_COOKIE_SECURE=True`.
- [ ] Set `DJANGO_USE_X_FORWARDED_PROTO=True` when using a reverse proxy.
- [ ] Enable HSTS only after confirming HTTPS works.

## Runtime

- [x] Use Gunicorn for Django in production.
- [x] Serve React build with Nginx.
- [x] Proxy `/api/` and `/admin/` to Django.
- [x] Use a persistent Docker volume for PostgreSQL.
- [x] Use a persistent Docker volume for uploaded media.
- [x] Add Docker container log rotation.
- [x] Add optional Sentry error monitoring.

## Files and uploads

- [x] Attachment downloads are protected by an authenticated endpoint.
- [x] Attachment file names are randomized in storage.
- [x] Attachment MIME types are restricted.
- [x] Attachment size is limited to 10 MB.
- [x] Decide whether production media stays on local volume or moves to object storage.

## Backups

- [x] Add PostgreSQL backup script.
- [x] Add restore instructions.
- [x] Test PostgreSQL restore on a clean environment.
- [x] Add uploaded media backup script.
- [x] Add uploaded media restore script.
- [x] Test uploaded media restore on a clean environment.

## Email and notifications

- [x] Document Amazon SES SMTP setup.

- [ ] Configure SMTP settings.
- [x] Add ticket created notification.
- [x] Add ticket status changed notification.
- [x] Add ticket assignment notification.

## Celery worker (async email)

Email sending runs in a Celery worker container. The web request thread enqueues the task and returns immediately, so a slow or failing SMTP server cannot block ticket creation, status changes, assignment, or password reset.

- [ ] Set the four Celery env vars in production `.env` (the production `.env` is not in the repo, so set them manually):

      CELERY_BROKER_URL=redis://redis:6379/1
      CELERY_RESULT_BACKEND=redis://redis:6379/2
      CELERY_TASK_ALWAYS_EAGER=False
      NOTIFICATION_QUEUED_TIMEOUT_MINUTES=30

  Recommended prod values: keep the defaults above unless an external Redis is being used. `CELERY_TASK_ALWAYS_EAGER` must remain `False` in production; setting it to `True` re-introduces the synchronous-SMTP blocking problem this change exists to remove.

- [ ] Start the worker container alongside the rest of the stack:

      docker compose -f docker-compose.prod.yml up -d worker

  Or, more typically, bring everything up:

      docker compose -f docker-compose.prod.yml up -d

- [ ] Confirm the worker can reach the broker:

      docker compose -f docker-compose.prod.yml exec worker celery -A config inspect ping

  A healthy worker replies with `pong`.

## Invitations

User onboarding goes through one-time invitation links. The backend stores only the sha256 hash of each token; the raw token leaves the system once, in the email body.

- [ ] Set the two new env vars in production `.env`:

      INVITATION_TTL_DAYS=7
      INVITATION_ACCEPT_FRONTEND_URL=https://<public-domain>/invite/accept?token={token}

  Both `PASSWORD_RESET_FRONTEND_URL` and `INVITATION_ACCEPT_FRONTEND_URL` must be set; if either is empty, the matching email body shows a placeholder string instead of a real link.

- [ ] Until the admin UI ships (CHANGE-16+), invitations can only be created via the API or via `manage.py shell`. For the first SUPER_ADMIN-issued company-admin invitation, open a shell on the backend container:

      docker compose -f docker-compose.prod.yml exec backend python manage.py shell

  Then run the snippet shown in `docs/ENV_SETUP.md` section 9 with the inviter, target company, and invitee email substituted in. The script prints the invitation id and writes the email through the worker. After CHANGE-16+ the same flow is available through the admin UI.

## Security

- [x] Role-based ticket scoping is tested.
- [x] Cross-company/customer access is tested.
- [x] API throttling is configured.
- [x] Review JWT storage strategy before public launch.
- [x] Add stricter production rate limits.
- [x] Add security headers at the proxy level.

## Validation before launch

- [ ] Run `./scripts/prod_env_check.sh` against final production `.env`.
- [x] Run `./scripts/check_all.sh`.
- [x] Run `docker compose -f docker-compose.prod.yml config`.
- [x] Build production images.
- [x] Run smoke test against production containers.
- [x] Test upload/download on production containers (`./scripts/prod_upload_download_test.sh`).
