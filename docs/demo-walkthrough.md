# Local demo walkthrough

> Two-browser script for demoing the system to Ramazan / a customer
> on `localhost`. Pairs with the
> [`seed_demo`](../backend/accounts/management/commands/seed_demo.py)
> management command added in Sprint 3.7. The demo runs entirely on
> the local machine — no public hostname, no real SMTP, no TLS.

## 1. Purpose

Show the customer flow end-to-end on `localhost`:

- a customer creates a ticket with a photo,
- the company / building manager progresses it through the
  lifecycle,
- the customer approves (or rejects + retake),
- an admin closes the approved ticket,
- reports / dashboard show the activity.

Audit logs, hierarchy refactor questions, and Sprint-5 reports
(by-type / by-customer / by-building, CSV/PDF export) are
**out of scope** for this demo unless the audience asks.

## 2. Start the stack

```bash
cd /home/goktug/cleaning-ticket-system

# Backend + Postgres + Redis + MailHog + Celery worker / beat
docker compose up -d

# Apply migrations and seed the demo objects (idempotent)
docker compose exec -T backend python manage.py migrate
docker compose exec -T backend python manage.py seed_demo

# Frontend dev server (uses local nvm Node 24)
export PATH="/home/goktug/.nvm/versions/node/v24.15.0/bin:$PATH"
cd frontend
npm run dev
```

Frontend: <http://localhost:5173>
Backend:  <http://localhost:8000> (you usually do not open this directly)
MailHog:  <http://localhost:8025>  ← outgoing-email inbox
PG / Redis: not exposed publicly; reachable only via the docker network.

> **Tip — clean inbox before demo:** MailHog "Delete all messages"
> button. Otherwise old test runs will distract Ramazan.

> **Re-running `seed_demo` is safe.** It updates the demo password,
> reactivates the demo users, and won't duplicate company / building
> / customer / membership rows. Use
> `python manage.py seed_demo --reset-demo-tickets` if you want a
> fresh ticket set without touching anything else.

## 3. Demo accounts

All passwords are `Demo12345!`. Roles match the existing scoping
helpers in [`backend/accounts/scoping.py`](../backend/accounts/scoping.py).

| Email | Password | Role | What to show |
|---|---|---|---|
| `demo-super@example.com` | `Demo12345!` | SUPER_ADMIN | Full visibility: every ticket / company / building / customer; super-admin-only audit feed at `/api/audit-logs/` if the audience asks |
| `demo-company-admin@example.com` | `Demo12345!` | COMPANY_ADMIN | Manages "Demo Cleaning BV": invitations, building/customer/user management, can override approvals |
| `demo-manager@example.com` | `Demo12345!` | BUILDING_MANAGER | Assigned to "Demo Building A": picks up open tickets, sends to customer approval |
| `demo-customer@example.com` | `Demo12345!` | CUSTOMER_USER | Linked to "Acme Demo Customer" (one customer-location). Creates tickets, approves / rejects |

Pre-seeded scope:
- **Company:** Demo Cleaning BV
- **Building:** Demo Building A (Demoweg 1, Amsterdam, NL, 1000 AA)
- **Customer-location:** Acme Demo Customer (under Demo Building A)
- **Memberships:** demo-company-admin → company; demo-manager →
  building; demo-customer → customer
- **Pre-seeded tickets** (prefixed `[DEMO]`):
  - `[DEMO] Lekkage in vergaderzaal A` — OPEN, HIGH
  - `[DEMO] Schoonmaak vloer toiletruimte` — IN_PROGRESS,
    assigned to demo-manager
  - `[DEMO] Lampen vervangen kantine` — WAITING_CUSTOMER_APPROVAL,
    assigned to demo-manager
  - `[DEMO] Offerteaanvraag glasbewassing` — APPROVED,
    assigned to demo-manager (ready for admin to close)

## 4. Two-browser walkthrough

Open **two separate browser sessions** so the JWT tokens do not
collide:

- **Browser A (normal window)** — company / admin side.
- **Browser B (incognito / private window)** — customer side.

### 4.1 Happy path (approve)

| Step | Browser A — staff | Browser B — customer | Expected |
|---|---|---|---|
| 1. Login as customer | – | open <http://localhost:5173/login>, login as `demo-customer@example.com` / `Demo12345!` | dashboard renders, "Nieuw ticket" / "New ticket" button visible |
| 2. Customer creates ticket | – | click "Nieuw ticket", fill: title `Verstopte afvoer`, description `Wastafel keuken loopt langzaam af`, kies klant `Acme Demo Customer`, kies type `Melding`, prioriteit `Hoog` → drag-and-drop a JPG → submit | ticket `TCK-…` created, status `Open`, photo attached |
| 3. Login as building manager | open <http://localhost:5173/login>, login as `demo-manager@example.com` / `Demo12345!` | – | dashboard tile shows the new open ticket |
| 4. Open the ticket | click the ticket from the dashboard | – | TicketDetailPage shows photo, customer description |
| 5. Take it In Behandeling | click "In Behandeling" / "Take work" | – | status flips to `IN_PROGRESS`, status history row appended |
| 6. Public reply | type `Begrepen, monteur op weg` → "Verzenden" / public reply | – | reply visible in thread |
| 7. Send for approval | click "Verzenden ter goedkeuring" / "Send to customer approval" | – | status `WAITING_CUSTOMER_APPROVAL`; an email lands in MailHog |
| 8. Customer approves | – | refresh ticket → click "Goedkeuren" | status `APPROVED`; admin-side notification email in MailHog |
| 9. Admin closes (login as company admin) | logout → login as `demo-company-admin@example.com` → open the ticket → click "Sluiten" | – | status `CLOSED` |
| 10. Show reports | open `/reports` | – | 6 chart cards render: status distribution, tickets-over-time, manager throughput, age buckets, SLA distribution, SLA breach rate |

### 4.2 Alternative path (reject + retake)

If the audience asks "what happens if the customer is not happy?":

| Step | Browser A — staff | Browser B — customer | Expected |
|---|---|---|---|
| 8b. Customer rejects | – | on a `WAITING_CUSTOMER_APPROVAL` ticket → click "Afwijzen", fill reason `Lek nog steeds aanwezig` | status `REJECTED` |
| 8b.1 Staff sees rejected | open the ticket as demo-manager | – | rejection visible; the ticket is back in the manager's queue |
| 8b.2 Staff retakes | click "In Behandeling" | – | status `REJECTED → IN_PROGRESS`. **This is intentional**: staff must explicitly acknowledge the rejection (not auto-flipped) so ownership is clear. |

The pre-seeded `[DEMO] Lampen vervangen kantine` ticket is already
in `WAITING_CUSTOMER_APPROVAL` — use it for the rejection demo
instead of clicking through the whole happy path twice.

## 5. What NOT to over-explain in the demo

- **Audit logs.** The super-admin-only `/api/audit-logs/` feed (Sprint
  2.2) records every User / Company / Building / Customer mutation.
  Mention only if the audience asks about compliance / change
  history.
- **CustomerAccount / hierarchy refactor.** Sprint 3.6's
  [pilot-readiness roadmap](pilot-readiness-roadmap.md) explicitly
  records that we will not refactor without business confirmation.
  Don't open this thread unless the audience wants it.
- **Reports by type / customer / building, CSV/PDF export.**
  Scheduled for **Sprint 5**. Show the existing 6 chart cards; if
  asked about per-type or per-customer breakdowns, say "next
  sprint".
- **Production HTTPS / TLS.** Handled upstream by NGINX Proxy
  Manager / Serdar's firewall, not by our app. Nothing to show on
  `localhost`.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Login fails for any demo user | Re-run `docker compose exec -T backend python manage.py seed_demo`. The command resets passwords and reactivates the accounts. |
| Frontend behaves stale (e.g. 404 on a route that should exist) | Hard refresh (`Ctrl + Shift + R`). If still broken, restart the dev server: `Ctrl + C` then `npm run dev`. |
| MailHog is full of irrelevant emails | <http://localhost:8025> → "Delete all messages" |
| Port 5173 / 8000 / 5432 / 6379 / 1025 / 8025 already in use | Stop whatever is holding them or change the host port mapping in `docker-compose.yml`. The defaults match what `seed_demo` and this walkthrough assume. |
| Demo tickets are missing | `python manage.py seed_demo` creates them. To start from scratch: `python manage.py seed_demo --reset-demo-tickets`. |
| Photo upload shows "too large" | The frontend enforces a max attachment size (see `attachment_too_large` i18n key). Use a smaller JPG/PNG (under a few MB). |
| Status button is missing for the customer | Customers can only act on `WAITING_CUSTOMER_APPROVAL` tickets. The `[DEMO] Lampen vervangen kantine` seed ticket is in that state — use it. |
| Sentry / Sentry init logs in the console | Only fires if `VITE_SENTRY_DSN` is set in `frontend/.env`. Empty DSN = no-op (Sprint 1.3 default). |
