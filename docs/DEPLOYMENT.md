# Production Deployment Guide

This guide explains how to deploy the cleaning ticket system with Docker Compose.

## 1. Prepare environment file

Copy the production example file:

    cp .env.production.example .env

Edit .env and replace all placeholder values:

    nano .env

Minimum required changes:

- DJANGO_SECRET_KEY
- DJANGO_ALLOWED_HOSTS
- CORS_ALLOWED_ORIGINS
- CSRF_TRUSTED_ORIGINS
- POSTGRES_PASSWORD
- SMTP settings if email notifications are enabled

Do not commit .env.

## 2. Build and start production containers

For local production smoke testing:

    FRONTEND_PORT=8080 docker compose -f docker-compose.prod.yml up -d --build

For a real server using port 80:

    FRONTEND_PORT=80 docker compose -f docker-compose.prod.yml up -d --build

The frontend container serves the React build with Nginx and proxies:

- /api/ to Django
- /admin/ to Django
- /static/ to Django static files

## 3. Run checks

    docker compose -f docker-compose.prod.yml exec backend python manage.py check
    docker compose -f docker-compose.prod.yml exec backend python manage.py makemigrations --check --dry-run

Run the production smoke test locally:

    FRONTEND_PORT=8080 ./scripts/prod_smoke_test.sh

Expected results:

- Frontend / returns 200
- /api/auth/me/ returns 401 without token
- /admin/login/ returns 200
- Security headers are present

## 4. Backups

Create PostgreSQL backup:

    ./scripts/backup_postgres.sh

Create media backup:

    ./scripts/backup_media.sh

Restore PostgreSQL backup:

    ./scripts/restore_postgres.sh backups/postgres/<backup-file>.dump

Read the detailed backup guide:

    cat docs/BACKUP_RESTORE.md

## 5. HTTPS

Put the app behind HTTPS before real public launch.

When HTTPS is ready, production .env should include:

    DJANGO_SECURE_SSL_REDIRECT=True
    DJANGO_SESSION_COOKIE_SECURE=True
    DJANGO_CSRF_COOKIE_SECURE=True
    DJANGO_USE_X_FORWARDED_PROTO=True
    DJANGO_SECURE_HSTS_SECONDS=31536000

Only enable HSTS after confirming HTTPS works correctly.

## 6. Stop production containers

    docker compose -f docker-compose.prod.yml down

To remove production volumes too, only when you intentionally want to delete production data:

    docker compose -f docker-compose.prod.yml down -v

Be careful: -v deletes database, Redis, and media volumes.

## 7. Logs

Production containers use Docker log rotation:

- max-size: 10m
- max-file: 5

View recent production logs:

    docker compose -f docker-compose.prod.yml logs --tail=200

Follow logs live:

    docker compose -f docker-compose.prod.yml logs -f --tail=100

