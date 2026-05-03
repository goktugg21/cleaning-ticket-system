# Production Go-Live Guide

This is the final checklist for launching the cleaning ticket system on a real server.

## 1. Prepare server

Install on the Ubuntu server:

    docker
    docker compose plugin
    git

Clone the repository and enter the project directory.

## 2. Create `.env`

Copy the production template:

    cp .env.production.example .env

Edit it:

    nano .env

Required real values:

- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `CORS_ALLOWED_ORIGINS`
- `CSRF_TRUSTED_ORIGINS`
- `POSTGRES_PASSWORD`
- Amazon SES SMTP settings if email notifications are used

Validate it:

    ./scripts/prod_env_check.sh

## 3. Start production containers

For a real server using port 80:

    FRONTEND_PORT=80 docker compose -f docker-compose.prod.yml up -d --build

For local production test:

    FRONTEND_PORT=8080 docker compose -f docker-compose.prod.yml up -d --build

## 4. Run production checks

    docker compose -f docker-compose.prod.yml config
    FRONTEND_PORT=8080 ./scripts/prod_smoke_test.sh
    FRONTEND_PORT=8080 ./scripts/prod_upload_download_test.sh

For restore validation:

    RESTORE_TEST_CONFIRM=YES FRONTEND_PORT=18080 ./scripts/prod_restore_test.sh

## 5. HTTPS / firewall / reverse proxy

The application itself can run over plain HTTP on the server.

Expected setup:

- External firewall / Nginx Proxy Manager / reverse proxy handles HTTPS.
- The request is forwarded internally to this app over HTTP.
- The app listens on `FRONTEND_PORT`, for example `8080` or `80`.
- Do not configure SSL certificates inside the app containers.

Only enable Django HTTPS flags after confirming the proxy sends:

    X-Forwarded-Proto: https

Do not enable HSTS or SSL redirect until HTTPS routing is confirmed.

## 6. Test email notifications

After Amazon SES SMTP is configured in `.env`:

    ENV_FILE=.env ./scripts/prod_env_check.sh
    ./scripts/notification_email_test.sh

Read:

    docs/SMTP_AMAZON_SES.md

## 7. Backups

Create database backup:

    ./scripts/backup_postgres.sh

Create media backup:

    ./scripts/backup_media.sh

Restore media only when needed:

    CONFIRM_RESTORE=YES ./scripts/restore_media.sh backups/media/media-YYYYMMDD-HHMMSS.tar.gz

Back up both PostgreSQL and media together.

## 8. Logs

View recent logs:

    docker compose -f docker-compose.prod.yml logs --tail=200

Follow logs:

    docker compose -f docker-compose.prod.yml logs -f --tail=100

## 9. Final launch validation

Before accepting real users:

- Login as admin, manager, and customer.
- Create a ticket.
- Upload and download an attachment.
- Change ticket status.
- Assign a ticket.
- Confirm email notification delivery.
- Confirm backup scripts work.
- Confirm HTTPS and secure cookies work.

## Local HTTP demo

For a local or VPS HTTP-only demo, run:

    FRONTEND_PORT=8080 ./scripts/demo_up.sh

Then open:

    http://localhost:8080

Read:

    docs/LOCAL_HTTP_DEMO.md

## Server handoff

For VPS deployment where HTTPS is handled by firewall or Nginx Proxy Manager, read:

    docs/SERVER_HANDOFF.md
