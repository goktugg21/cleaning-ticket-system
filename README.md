# Osius — Cleaning Ticket System

A multi-tenant SaaS platform for the **Dutch B2B cleaning market**. A cleaning
service provider manages its customers, buildings, staff, tickets (meldingen),
recurring work, extra-work requests with pricing/proposals, and invoicing;
customer companies log in to report issues, request extra work, approve work,
and see invoices scoped to their own organisation and buildings.

Role-based access control and strict tenant scoping are enforced throughout —
a user only ever sees and does what their role, company, assigned buildings,
and explicit permissions allow.

> **Deployment status:** production is **not deployed yet**. `crmtest.osius.nl`
> is a dev/test environment. Production deployment is an open milestone.

## Documentation

**[docs/README.md](docs/README.md) is the documentation index** — the map of
every live doc (product source-of-truth + addenda, RBAC matrix, business logic,
engineering runbooks, and the living sprint checklist). Start there.

Contributor working agreement and hard rules live in
[CLAUDE.md](CLAUDE.md).

## Tech stack

- **Backend:** Django 5.2 + Django REST Framework, PostgreSQL, Redis, Celery,
  Simple JWT, django-filter.
- **Frontend:** React 19 + TypeScript + Vite, Axios, React Router.
- **Infra:** Docker Compose (a dev stack and a separate prod stack), FPDF2 for
  PDF generation, optional Sentry (no-op until a DSN is set).

## Local development (dev stack)

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
docker compose up -d          # Postgres, Redis, MailHog, backend, frontend
```

- Frontend dev server and backend API come up under Docker Compose.
- Outgoing email is captured by **MailHog** — inspect it at
  <http://localhost:8025> (SMTP points at `mailhog:1025`; use real SMTP in
  production via `.env.production.example`).

Backend tests (from `backend/`): `python manage.py test` — judge by the textual
`OK` / `FAILED` line. Frontend gate (from `frontend/`):
`npm run typecheck && npm run lint && npm run build`.

## crmtest / prod compose (important)

`crmtest.osius.nl` is served by the **production compose stack**, not the dev
stack above:

- File `docker-compose.prod.yml`, project `cleaning-ticket-prod`, 6 containers
  (`db`, `redis`, `backend`, `worker`, `beat`, `frontend`).
- **Every command against it needs `-f docker-compose.prod.yml`** — a bare
  `docker compose ...` targets the dev stack.
- The backend auto-runs `migrate && collectstatic && gunicorn` on start, so
  migrations apply automatically when the backend container is recreated.

Deploy runbook: [docs/engineering/deployment.md](docs/engineering/deployment.md).

## Sentry (optional)

Both backend (`sentry-sdk`) and frontend (`@sentry/react`) can ship errors to
Sentry, gated on a DSN. The SDK is a complete no-op when the DSN is empty
(`SENTRY_DSN` / `VITE_SENTRY_DSN`), so the integration is safe to merge before a
Sentry org exists. `send_default_pii=False` on both sides — do not flip without
a privacy review.
