# Release Status

## Current state

The cleaning ticket system is production-ready from the application and Docker Compose side.

The following validation passed successfully:

    ./scripts/final_validation.sh

This final validation includes:

- Shell script syntax check
- Production environment template preflight check
- Full development test suite
- Django system check
- Migration dry-run check
- API smoke tests
- Scope isolation tests
- Attachment upload/list/download tests
- Attachment file type and size validation
- Assignment API tests
- Frontend production build
- Production Docker Compose smoke test
- Production upload/download smoke test
- PostgreSQL backup and restore smoke test against a clean isolated environment
- Uploaded media restore smoke test

## Latest validated code state

The full production validation passed after adding:

    Add final production validation script

The current latest commit may include documentation-only release notes.
Use this to inspect the current HEAD:

    git log --oneline -1

## Production-ready items

- Docker Compose production setup exists.
- Django runs with Gunicorn in production.
- React build is served by Nginx.
- Nginx proxies `/api/`, `/admin/`, and `/static/`.
- PostgreSQL uses a persistent Docker volume.
- Uploaded media uses a persistent Docker volume.
- Docker log rotation is configured.
- Production smoke tests exist.
- Upload/download production smoke test exists.
- PostgreSQL backup and restore scripts exist.
- PostgreSQL restore smoke test exists.
- Media backup script exists.
- Media restore script exists.
- Media restore smoke test exists.
- API throttling is configured.
- Stricter production throttle defaults are documented.
- Security headers are configured.
- Optional Sentry error monitoring is available.
- JWT storage strategy has been reviewed and documented.
- Media storage strategy has been selected and documented.
- Production `.env` preflight check exists.
- Final validation script exists.
- Local HTTP demo script exists.
- Server handoff guide exists for external HTTPS termination.
- Amazon SES SMTP setup guide exists.
- Local demo presentation flow exists.

## Remaining before real public launch

These items require real production information or server-level setup:

- Choose the real production domain.
- Create the real `.env` from `.env.production.example`.
- Generate a strong `DJANGO_SECRET_KEY`.
- Set `DJANGO_ALLOWED_HOSTS` to the real domain.
- Set `CORS_ALLOWED_ORIGINS` to the real frontend origin.
- Set `CSRF_TRUSTED_ORIGINS` to the real frontend origin.
- Set strong PostgreSQL credentials.
- Configure SMTP settings.
- Put the app behind HTTPS.
- Enable secure cookie and HTTPS settings after HTTPS is working.
- Enable HSTS only after HTTPS is confirmed.
- Run final `.env` validation:

    ENV_FILE=.env ./scripts/prod_env_check.sh

## Recommended go-live order

1. Prepare server.
2. Install Docker and Docker Compose plugin.
3. Clone or copy the repository.
4. Create `.env` from `.env.production.example`.
5. Fill real production values.
6. Run:

       ENV_FILE=.env ./scripts/prod_env_check.sh

7. Start production containers:

       FRONTEND_PORT=80 docker compose -f docker-compose.prod.yml up -d --build

8. Run production smoke test:

       FRONTEND_PORT=80 ./scripts/prod_smoke_test.sh

9. Configure HTTPS.
10. Enable HTTPS security flags in `.env`.
11. Restart production containers.
12. Run smoke test again.
13. Create first real backup:

       ./scripts/backup_postgres.sh
       ./scripts/backup_media.sh

