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