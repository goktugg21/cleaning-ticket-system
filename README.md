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