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
- SMTP settings if email notifications are used

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

## 5. Configure HTTPS

Put the app behind HTTPS before real public launch.

Recommended simple production approach:

- Use a reverse proxy such as Caddy or Nginx.
- Forward `/` traffic to the frontend container.
- Ensure Django receives the correct forwarded HTTPS header.
- Confirm HTTPS works before enabling HSTS.

## 6. Test email notifications

After SMTP is configured:

    ./scripts/notification_email_test.sh

## 7. Backups

Create database backup:

    ./scripts/backup_postgres.sh

Create media backup:

    ./scripts/backup_media.sh

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
