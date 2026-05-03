# Server Handoff

This document explains how the cleaning ticket system should be deployed on a VPS when HTTPS is terminated outside the application.

## Expected network setup

The application itself runs over plain HTTP.

Expected request flow:

    Browser
      -> HTTPS / 443
      -> Firewall or Nginx Proxy Manager
      -> HTTP to this VPS/app port
      -> Docker Compose frontend container
      -> Django backend container
      -> PostgreSQL / Redis / media volume

The app containers do not manage SSL certificates.

## Important rule

Do not configure SSL inside this application.

Do not enable these Django settings until the external proxy behavior is confirmed:

    DJANGO_SECURE_SSL_REDIRECT=True
    DJANGO_SESSION_COOKIE_SECURE=True
    DJANGO_CSRF_COOKIE_SECURE=True
    DJANGO_USE_X_FORWARDED_PROTO=True
    DJANGO_SECURE_HSTS_SECONDS=31536000

If the proxy does not send the correct `X-Forwarded-Proto: https` header, enabling SSL redirect may cause redirect loops.

## Recommended internal app port

Use:

    FRONTEND_PORT=8080

The app will be reachable inside the server/network at:

    http://SERVER_IP:8080

or locally on the server at:

    http://localhost:8080

The external firewall / Nginx Proxy Manager can forward public HTTPS traffic to this internal HTTP port.

## Server requirements

Install:

    docker
    docker compose plugin
    git

## Deployment steps

Clone or copy the repository:

    git clone <repository-url>
    cd cleaning-ticket-system

Create the production environment file:

    cp .env.production.example .env

Generate a strong Django secret key:

    ./scripts/generate_secret_key.sh

Edit `.env`:

    nano .env

Minimum required values:

    DJANGO_DEBUG=False
    DJANGO_SECRET_KEY=<generated-secret-key>
    DJANGO_ALLOWED_HOSTS=<domain-or-server-ip>
    CORS_ALLOWED_ORIGINS=http://<domain-or-server-ip>:8080
    CSRF_TRUSTED_ORIGINS=http://<domain-or-server-ip>:8080
    POSTGRES_PASSWORD=<strong-password>

If the public domain is already behind HTTPS, use the HTTPS public origin for CORS and CSRF:

    CORS_ALLOWED_ORIGINS=https://<public-domain>
    CSRF_TRUSTED_ORIGINS=https://<public-domain>

## Amazon SMTP

Email is sent through SMTP settings.

For Amazon SES SMTP, use the SMTP host, username, password, and sender email provided by Amazon.

Example:

    EMAIL_HOST=email-smtp.eu-central-1.amazonaws.com
    EMAIL_PORT=587
    EMAIL_HOST_USER=<amazon-smtp-username>
    EMAIL_HOST_PASSWORD=<amazon-smtp-password>
    EMAIL_USE_TLS=True
    DEFAULT_FROM_EMAIL=<verified-sender-email>

After SMTP is configured, test email notifications:

    ./scripts/notification_email_test.sh

## Validate `.env`

Run:

    ENV_FILE=.env ./scripts/prod_env_check.sh

## Start the app

For HTTP on port 8080:

    FRONTEND_PORT=8080 docker compose -f docker-compose.prod.yml up -d --build

Check running containers:

    docker compose -f docker-compose.prod.yml ps

View logs:

    docker compose -f docker-compose.prod.yml logs --tail=200

Follow logs live:

    docker compose -f docker-compose.prod.yml logs -f --tail=100

## Run smoke test

For internal HTTP port 8080:

    FRONTEND_PORT=8080 ./scripts/prod_smoke_test.sh

For upload/download validation:

    FRONTEND_PORT=8080 ./scripts/prod_upload_download_test.sh

## Local/demo startup

For a quick local HTTP demo with seeded demo users:

    FRONTEND_PORT=8080 ./scripts/demo_up.sh

Open:

    http://localhost:8080

Demo users:

    Super admin:    admin@example.com        / Admin12345!
    Company admin:  companyadmin@example.com / Test12345!
    Manager:        manager@example.com      / Test12345!
    Customer:       customer@example.com     / Test12345!

Stop demo:

    ./scripts/demo_down.sh

## Backup

Create PostgreSQL backup:

    ./scripts/backup_postgres.sh

Create media backup:

    ./scripts/backup_media.sh

Both backups are required. PostgreSQL backup without the media backup is incomplete.

## Restore validation

Run restore smoke test only in isolated test mode:

    RESTORE_TEST_CONFIRM=YES FRONTEND_PORT=18080 ./scripts/prod_restore_test.sh

## Stop app

Stop containers but keep data volumes:

    docker compose -f docker-compose.prod.yml down

Stop containers and delete all production volumes:

    docker compose -f docker-compose.prod.yml down -v

Be careful: `-v` deletes database, Redis, and uploaded media volumes.

## Amazon SES SMTP handoff

Email delivery will be configured through Amazon SES SMTP.

The application needs these values in `.env`:

    EMAIL_HOST=
    EMAIL_PORT=587
    EMAIL_HOST_USER=
    EMAIL_HOST_PASSWORD=
    EMAIL_USE_TLS=True
    DEFAULT_FROM_EMAIL=

The real SMTP endpoint, username, password, and verified sender email must be provided by the production email/admin side.

After the values are added, run:

    ENV_FILE=.env ./scripts/prod_env_check.sh
    ./scripts/notification_email_test.sh

Do not commit real SMTP credentials.

