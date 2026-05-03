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
- [ ] Do not commit `.env`.

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
- [ ] Add server-level log rotation.
- [ ] Add error monitoring.

## Files and uploads

- [x] Attachment downloads are protected by an authenticated endpoint.
- [x] Attachment file names are randomized in storage.
- [x] Attachment MIME types are restricted.
- [x] Attachment size is limited to 10 MB.
- [ ] Decide whether production media stays on local volume or moves to object storage.

## Backups

- [x] Add PostgreSQL backup script.
- [x] Add restore instructions.
- [ ] Test restore on a clean environment.
- [x] Add uploaded media backup script.

## Email and notifications

- [ ] Configure SMTP settings.
- [x] Add ticket created notification.
- [x] Add ticket status changed notification.
- [x] Add ticket assignment notification.

## Security

- [x] Role-based ticket scoping is tested.
- [x] Cross-company/customer access is tested.
- [x] API throttling is configured.
- [ ] Review JWT storage strategy before public launch.
- [ ] Add stricter production rate limits.
- [ ] Add security headers at the proxy level.

## Validation before launch

- [ ] Run `./scripts/check_all.sh`.
- [ ] Run `docker compose -f docker-compose.prod.yml config`.
- [ ] Build production images.
- [ ] Run smoke test against production containers.
- [ ] Test upload/download on production containers.
