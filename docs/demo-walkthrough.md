# Local demo walkthrough

> Two-browser script for demoing the system to a customer on
> `localhost`. Pairs with the
> [`seed_demo_data`](../backend/accounts/management/commands/seed_demo_data.py)
> management command. The demo runs entirely on the local machine —
> no public hostname, no real SMTP, no TLS.

## 1. Purpose

Show the customer flow end-to-end on `localhost`:

- a customer creates a ticket with a photo,
- the building manager progresses it through the lifecycle,
- the customer approves (or rejects + retake),
- an admin closes the approved ticket,
- reports / dashboard show the activity.

Sprint 21 added a second isolated demo company (Bright Facilities,
Rotterdam) so you can also show that Company A and Company B do not
see each other's tickets, buildings, customers, or audit log. See
section 5 for the cross-company isolation walkthrough.

## 2. Start the stack

```bash
cd /home/goktug/cleaning-ticket-system

# Backend + Postgres + Redis + MailHog + Celery worker / beat
docker compose up -d

# Apply migrations and seed the canonical two-company demo
# (idempotent — safe to re-run).
docker compose exec -T backend python manage.py migrate
docker compose exec -T backend python manage.py seed_demo_data

# Frontend dev server (uses local nvm Node 24)
export PATH="/home/goktug/.nvm/versions/node/v24.15.0/bin:$PATH"
cd frontend
npm run dev
```

Frontend: <http://localhost:5173>
Backend:  <http://localhost:8000>
MailHog:  <http://localhost:8025>  ← outgoing-email inbox

> **Re-running `seed_demo_data` is safe.** It updates the demo
> password, reactivates the demo users, and won't duplicate company /
> building / customer / membership rows. Use
> `python manage.py seed_demo_data --reset-tickets` if you want a
> fresh ticket set without touching anything else.

## 3. Demo accounts

All passwords are `Demo12345!`. Roles match the existing scoping
helpers in [`backend/accounts/scoping.py`](../backend/accounts/scoping.py).

### Super admin (spans both companies)

| Email | Password | Role | What to show |
|---|---|---|---|
| `super@cleanops.demo` | `Demo12345!` | SUPER_ADMIN | Full visibility: every ticket / company / building / customer; super-admin-only audit feed at `/api/audit-logs/` if the audience asks |

### Company A — Osius Demo (Amsterdam, B1 / B2 / B3)

| Email | Role | Building scope |
|---|---|---|
| `admin@cleanops.demo` | COMPANY_ADMIN | Osius Demo |
| `gokhan@cleanops.demo` | BUILDING_MANAGER | B1, B2, B3 |
| `murat@cleanops.demo` | BUILDING_MANAGER | B1 |
| `isa@cleanops.demo` | BUILDING_MANAGER | B2 |
| `tom@cleanops.demo` | CUSTOMER_USER | B1, B2, B3 |
| `iris@cleanops.demo` | CUSTOMER_USER | B1, B2 |
| `amanda@cleanops.demo` | CUSTOMER_USER | B3 |

### Company B — Bright Facilities (Rotterdam, R1 / R2)

| Email | Role | Building scope |
|---|---|---|
| `admin-b@cleanops.demo` | COMPANY_ADMIN | Bright Facilities |
| `manager-b@cleanops.demo` | BUILDING_MANAGER | R1, R2 |
| `customer-b@cleanops.demo` | CUSTOMER_USER | R1, R2 |

### Pre-seeded tickets

All tickets carry the `[DEMO]` prefix so an operator can delete and
re-create them with `seed_demo_data --reset-tickets` without
touching real demo activity.

| Title | Company | Building | Status |
|---|---|---|---|
| `[DEMO] Open lobby light` | Osius Demo | B1 Amsterdam | OPEN |
| `[DEMO] In progress hallway scuff` | Osius Demo | B2 Amsterdam | IN_PROGRESS |
| `[DEMO] Pantry zeepdispenser` | Osius Demo | B3 Amsterdam | WAITING_CUSTOMER_APPROVAL |
| `[DEMO] Closed kitchen tap` | Osius Demo | B1 Amsterdam | CLOSED |
| `[DEMO] Reception lights flickering` | Bright Facilities | R1 Rotterdam | OPEN |
| `[DEMO] Lobby floor polish scheduled` | Bright Facilities | R2 Rotterdam | IN_PROGRESS |

## 4. Two-browser walkthrough (single company — Osius Demo)

Open **two separate browser sessions** so the JWT tokens do not
collide:

- **Browser A (normal window)** — staff (manager / admin).
- **Browser B (incognito / private window)** — customer.

### 4.1 Happy path (approve)

| Step | Browser A — staff | Browser B — customer | Expected |
|---|---|---|---|
| 1. Login as customer | – | open <http://localhost:5173/login>, login as `tom@cleanops.demo` / `Demo12345!` | dashboard renders, "Nieuw ticket" / "New ticket" button visible |
| 2. Customer creates ticket | – | click "New ticket", fill: title / description / customer / building / type / priority → optionally attach a JPG → submit | ticket created in `OPEN`, photo attached |
| 3. Login as building manager | open <http://localhost:5173/login>, login as `gokhan@cleanops.demo` / `Demo12345!` | – | dashboard tile shows the new open ticket |
| 4. Take it In Progress | click "Take work" | – | status flips to `IN_PROGRESS` |
| 5. Send for approval | click "Send to customer approval" | – | status `WAITING_CUSTOMER_APPROVAL`; email lands in MailHog |
| 6. Customer approves | – | refresh ticket → click "Goedkeuren" | status `APPROVED` |
| 7. Admin closes | logout → login as `admin@cleanops.demo` → open the ticket → click "Close" | – | status `CLOSED` |
| 8. Show reports | open `/reports` | – | report cards render |

### 4.2 Alternative path (reject + retake)

If the audience asks "what happens if the customer is not happy?":
use the pre-seeded `[DEMO] Pantry zeepdispenser` ticket — it is
already in `WAITING_CUSTOMER_APPROVAL`, so the customer can reject it
and the manager can retake it without walking through the whole
happy path twice.

## 5. Cross-company isolation walkthrough (Company A vs Company B)

This is the Sprint 21 demo: prove that Company A and Company B do
not leak data between each other.

| Step | Browser A | Browser B | Expected |
|---|---|---|---|
| 1. Login as super | super@cleanops.demo | – | dashboard shows tickets from BOTH Osius Demo and Bright Facilities |
| 2. Login as Company A admin | admin@cleanops.demo | – | tickets, buildings, customers, users list only Osius Demo |
| 3. Login as Company B admin | – | admin-b@cleanops.demo | tickets, buildings, customers, users list only Bright Facilities |
| 4. Cross-company ticket URL | (still on Company A) try opening `/tickets/<id>` from one of Company B's tickets — get the id from the super admin session | – | 404 / forbidden — Company A cannot read Company B's ticket |
| 5. Reports | open `/reports` as `admin@cleanops.demo` | open `/reports` as `admin-b@cleanops.demo` | the two report dashboards show disjoint datasets |

The Playwright suite `cross_company_isolation.spec.ts` exercises
this same matrix end-to-end on every build.

## 6. What NOT to over-explain in the demo

- **Audit logs.** The super-admin-only `/api/audit-logs/` feed
  records every User / Company / Building / Customer mutation.
  Mention only if the audience asks about compliance / change
  history.
- **Production HTTPS / TLS.** Handled upstream by NGINX Proxy
  Manager / Serdar's firewall, not by our app. Nothing to show on
  `localhost`.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| Login fails for any demo user | Re-run `docker compose exec -T backend python manage.py seed_demo_data`. The command resets passwords and reactivates the accounts. |
| Frontend behaves stale (e.g. 404 on a route that should exist) | Hard refresh (`Ctrl + Shift + R`). If still broken, restart the dev server: `Ctrl + C` then `npm run dev`. |
| MailHog is full of irrelevant emails | <http://localhost:8025> → "Delete all messages" |
| Demo tickets are missing | `python manage.py seed_demo_data` creates them. To start from scratch: `python manage.py seed_demo_data --reset-tickets`. |
| Status button is missing for the customer | Customers can only act on `WAITING_CUSTOMER_APPROVAL` tickets. The `[DEMO] Pantry zeepdispenser` seed ticket is in that state — use it. |
