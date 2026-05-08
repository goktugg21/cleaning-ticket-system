# Cleaning Ticket System

A role-based cleaning operations ticket system built with Django REST Framework and React.

## Features

- JWT login and token refresh
- Role-based access control
- Multi-company / building / customer scoping
- Customer ticket creation
- Manager ticket workflow
- Customer approval workflow
- Company admin ticket closing
- Internal staff notes hidden from customer users
- Ticket filtering, search, and pagination
- React dashboard and ticket detail UI
- API smoke tests and scope isolation tests

## Tech Stack

### Backend
- Django
- Django REST Framework
- PostgreSQL
- Redis
- Simple JWT
- django-filter
- django-cors-headers

### Frontend
- React
- TypeScript
- Vite
- Axios
- React Router

## Local Development

Copy environment files:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env
```

Start the stack:

```bash
docker compose up -d
```

### Email in development

Outgoing email is captured by the `mailhog` service rather than delivered.
Inspect captured messages at http://localhost:8025. The default `.env.example`
already points SMTP at `mailhog:1025`; for production replace with real SMTP
credentials (see `.env.production.example`).

### Sentry (optional)

Both backend (`sentry-sdk`) and frontend (`@sentry/react`) can ship error
events to Sentry, gated on a DSN env var. The SDK is a complete no-op when
the DSN is empty — there is zero overhead and the integration is safe to
merge before owning a Sentry org.

- **Enable**: create a Sentry project (Django for backend, React for
  frontend), set `SENTRY_DSN` in `.env` and `VITE_SENTRY_DSN` in
  `frontend/.env`. Restart the backend container and rebuild the frontend.
- **Default sample rate**: `0.0` in dev (no performance traces), `0.1` in
  prod (see `.env.production.example`).
- **Privacy posture**: `send_default_pii=False` on both sides; user emails
  and IP addresses are NOT auto-sent. Do not flip without a privacy review.
- **What gets captured**: backend uses `DjangoIntegration`, `CeleryIntegration`,
  and `LoggingIntegration` (event_level=`ERROR`), so any `logger.error` /
  `logger.exception` call — including unhandled task failures — becomes a
  Sentry event. Frontend's top-level `ErrorBoundary` forwards the React
  component stack as context on `componentDidCatch`.
- **Source maps / release tracking**: not wired in this batch. Set
  `SENTRY_RELEASE` / `VITE_SENTRY_RELEASE` to a git SHA via CI when
  Sprint 3 wires the deployment pipeline.