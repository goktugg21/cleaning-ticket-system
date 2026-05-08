# Sprint 3.5 — Product / demo readiness audit

> Pure audit. No code changes in this batch besides this document.
> Dated: 2026-05-08 against `master` at `49818e2` (post Sprint 3 merge).

---

## 1. Executive summary

**Directionally aligned: YES.** The current system already implements
the customer flow the business described. The biggest deltas are
report dimensions (type/customer breakdowns) and packaging the local
demo, not architecture or core domain.

**Demo-ready today:**
- Login, role separation (super admin / company admin / building
  manager / customer user).
- Customer ticket creation with photo attachment.
- Full ticket lifecycle: OPEN → IN_PROGRESS → WAITING_CUSTOMER_APPROVAL
  → APPROVED/REJECTED → CLOSED (and REJECTED → IN_PROGRESS,
  CLOSED → REOPENED_BY_ADMIN → IN_PROGRESS).
- Public replies + internal notes on tickets, with attachments.
- Existing dashboards: status distribution, tickets-over-time,
  manager throughput, age buckets, SLA distribution, SLA breach rate.
- Multi-tenant scoping: a customer user only sees tickets / customers
  / buildings they are explicitly linked to.
- Dutch UI (frontend default `nl`), English UI (`en`). Notification
  emails are Dutch only (Sprint B5).
- Audit log (Sprint 2.2): every User / Company / Building / Customer
  mutation is recorded; super admins can browse `/api/audit-logs/`.

**Not demo-ready / gaps to call out:**
- No "tickets by ticket-type" chart and no "tickets by customer"
  chart in `ReportsPage`. Monthly counts work via the existing
  `tickets-over-time` endpoint when a wide enough range is selected,
  but there is no per-type or per-customer breakdown surfaced.
- No "tickets by building" CHART (there is a JSON
  `/api/tickets/stats/by-building/` endpoint, but no chart card).
- No demo-seed script + scripted walkthrough for Ramazan; the
  existing `scripts/demo_up.sh` brings the stack up but does not
  hand the operator a step-by-step demo flow.
- The customer reject path leaves the ticket in `REJECTED`. Returning
  it to `IN_PROGRESS` is staff-driven, NOT automatic. The state
  machine *allows* `REJECTED → IN_PROGRESS` for staff but the
  customer's reject does not auto-flip; that is a deliberate "staff
  must acknowledge" design — see §3.

---

## 2. Domain mapping

| Business requirement | Backend artefact | Status |
|---|---|---|
| Buildings exist | [`buildings.Building`](../backend/buildings/models.py) — FK to `companies.Company`, has name/address/city/country/postal_code, `is_active` soft-delete | ✓ |
| A building can have multiple customers | [`customers.Customer`](../backend/customers/models.py) has `company` FK + `building` FK; one customer maps to one building, but a building can have many customers (1:N) | ✓ |
| Customer users belong to customers | [`customers.CustomerUserMembership`](../backend/customers/models.py) (M:N user↔customer) | ✓ |
| Customer users only see authorized tickets/customers/buildings | [`accounts.scoping.scope_tickets_for`](../backend/accounts/scoping.py#L108-L127) filters by `customer_id__in=memberships`. `scope_customers_for` and `scope_buildings_for` similarly filter. Tested in [`tickets/tests/test_scoping.py`](../backend/tickets/tests/test_scoping.py) and [`accounts/tests/test_scoping.py`](../backend/accounts/tests/test_scoping.py) | ✓ |
| Rooms exist conceptually but NOT modeled | No `Room` model. `Ticket.room_label` is a free-text `CharField(max_length=255, blank=True)` — same row, no separate table | ✓ aligned (intentionally deferred) |

**Decision recorded:** Rooms are deferred. The existing `room_label`
text field is the workaround. Defer the Room model until the
business asks for room-level reporting / room-level scoping. When it
lands, migrate `room_label` → `Room` via a data migration.

---

## 3. Ticket workflow mapping

State machine table from
[`tickets/state_machine.py`](../backend/tickets/state_machine.py#L18-L57)
mapped against the business flow:

| Business step | Status transition | Allowed roles | Status |
|---|---|---|---|
| Customer creates ticket | (new) → `OPEN` | Any authenticated user with customer scope | ✓ |
| Customer attaches photo on create or later | `POST /api/tickets/<id>/attachments/` | Any user with ticket scope | ✓ |
| Company takes the ticket | `OPEN → IN_PROGRESS` | SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER | ✓ |
| Company adds public reply / internal note + attachments | `POST /api/tickets/<id>/messages/`, `POST /api/tickets/<id>/attachments/` | Staff for INTERNAL_NOTE; PUBLIC_REPLY visible to customer | ✓ |
| Company sends to customer | `IN_PROGRESS → WAITING_CUSTOMER_APPROVAL` | Staff | ✓ |
| Customer approves | `WAITING_CUSTOMER_APPROVAL → APPROVED` | CUSTOMER_USER (or staff override) | ✓ |
| Customer rejects | `WAITING_CUSTOMER_APPROVAL → REJECTED` | CUSTOMER_USER (or staff override). Reject reason required (validated in `TicketStatusChangeSerializer`) | ✓ |
| Reject returns to work | `REJECTED → IN_PROGRESS` | SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER. **Explicit staff action; NOT automatic.** | ✓ aligned, see decision below |
| Admin closes approved ticket | `APPROVED → CLOSED` | SUPER_ADMIN, COMPANY_ADMIN | ✓ |
| Reopen for late issue | `CLOSED → REOPENED_BY_ADMIN → IN_PROGRESS` | SUPER_ADMIN, COMPANY_ADMIN; manager can take it from there | ✓ (extra escape hatch) |

**REJECT semantics — design note.** The brief says "REJECT returns
the ticket to work/in-progress". The current implementation requires
staff to *explicitly* move `REJECTED → IN_PROGRESS`. That is the
right shape: it makes the staff acknowledge the rejection, attach a
reply, and re-plan. Auto-flipping to `IN_PROGRESS` would silently
re-queue the ticket without the next-step ownership being clear and
would also lose the `REJECTED` row in `TicketStatusHistory` becoming
visible work for the operator. **Recommendation: keep the explicit
two-step.** If the business pushes for auto-flip later, that's a
small state-machine edit + 1 test.

**Customer-side UI confirmed.** `frontend/src/pages/TicketDetailPage.tsx`
renders Approve and Reject buttons for `WAITING_CUSTOMER_APPROVAL`
state, and a rejection-reason textbox is enforced (`workflow_customer_rejection_required`
i18n key, validated server-side).

---

## 4. Ticket type / category gap

### Backend enum
[`backend/tickets/models.py:9-14`](../backend/tickets/models.py#L9-L14):

```python
class TicketType(models.TextChoices):
    REPORT        = "REPORT",        "Melding / Report"
    COMPLAINT     = "COMPLAINT",     "Klacht / Complaint"
    REQUEST       = "REQUEST",       "Verzoek / Request"
    SUGGESTION    = "SUGGESTION",    "Suggestie / Suggestion"
    QUOTE_REQUEST = "QUOTE_REQUEST", "Offerteaanvraag / Quote Request"
```

### Frontend Dutch labels
[`frontend/src/i18n/nl/create_ticket.json`](../frontend/src/i18n/nl/create_ticket.json):

```
type_report         = "Melding"
type_complaint      = "Klacht"
type_request        = "Verzoek"
type_suggestion     = "Suggestie"
type_quote_request  = "Offerteverzoek"
```

### Required (per business)
| Required | Backend value | NL label | Status |
|---|---|---|---|
| melding | `REPORT` | Melding | ✓ exact |
| klacht / şikayet | `COMPLAINT` | Klacht | ✓ NL label exact; Turkish hint not yet in any locale |
| verzoek / istek | `REQUEST` | Verzoek | ✓ NL label exact |
| suggestie / öneri | `SUGGESTION` | Suggestie | ✓ NL label exact |
| offerte / teklif | `QUOTE_REQUEST` | Offerteverzoek | ✓ semantically equivalent ("offerte aanvragen") |

### Recommendation

- **Keep enum values unchanged.** Renaming any of `REPORT` /
  `COMPLAINT` / `REQUEST` / `SUGGESTION` / `QUOTE_REQUEST` would
  require a `RenameField`-equivalent on a `TextChoices` and a
  bidirectional data migration on the `tickets.Ticket.type` column,
  plus an audit-log replay (changes already in `audit_log.changes`
  would lose meaning). For zero gain — the enum names are internal,
  the user-visible labels already match.
- **Optional: add Turkish locale** if the business actually wants TR
  UI alongside NL/EN. That is a frontend i18n batch (add `tr`
  resources, populate `type_report = "Bildirim"`, `type_complaint =
  "Şikayet"`, etc.). Not implementation in this audit batch.
- **Migration risk if enum changes:** medium. Tickets in the wild
  hold the string value in the column; an enum rename without a
  data migration would orphan all existing rows.

---

## 5. Photos / attachments

| Aspect | Implementation | Status |
|---|---|---|
| Model | [`tickets.TicketAttachment`](../backend/tickets/models.py#L190-L221) — FK to `Ticket` (and optional FK to `TicketMessage`), `file = FileField`, `original_filename`, `mime_type`, `file_size`, `is_hidden` | ✓ |
| Storage path | `tickets/<ticket_id>/<uuid4>.<ext>` (randomised filename, original kept in `original_filename`) | ✓ — no path traversal risk |
| Upload — create flow | `CreateTicketPage` `<label className="upload-zone">` → after ticket POST returns id, FormData PUT to `/api/tickets/<id>/attachments/` | ✓ |
| Upload — detail page | `TicketDetailPage` upload-zone with size guard | ✓ |
| Download | `GET /api/tickets/<id>/attachments/<attachment_id>/download/` returns the stored bytes with `Content-Disposition` carrying `original_filename` | ✓ |
| MIME / size whitelist | Validated in `TicketAttachmentSerializer`; tested in [`test_attachments.py`](../backend/tickets/tests/test_attachments.py) | ✓ |
| Visibility / scoping | `is_hidden` attachments and attachments tied to internal-note messages are filtered out for customer users; covered by `test_customer_cannot_view_hidden_attachments`, `test_customer_cannot_download_attachment_linked_to_internal_message`, `test_attachment_outside_scope_is_denied` | ✓ |
| Demo-readiness | Drag-and-drop UI exists, file-size hint shown, replace flow works | ✓ |

**No work needed for the demo.** Photos work end-to-end and have
adversarial tests.

---

## 6. Reports — gap analysis

### Implemented (under [`backend/reports/`](../backend/reports/))
| Endpoint | Frontend chart card | Dimension |
|---|---|---|
| `GET /api/reports/status-distribution/` | `StatusDistributionChart` | counts per status |
| `GET /api/reports/tickets-over-time/` | `TicketsOverTimeChart` | counts per period (granularity auto-picks daily / weekly / monthly based on `from`/`to` range — **monthly works when the range is ≥ 60 days**) |
| `GET /api/reports/manager-throughput/` | `ManagerThroughputChart` | tickets approved per manager per period |
| `GET /api/reports/age-buckets/` | `AgeBucketsChart` | open tickets bucketed by age |
| `GET /api/reports/sla-distribution/` | `SLADistributionChart` | counts by SLA status |
| `GET /api/reports/sla-breach-rate-over-time/` | `SLABreachRateChart` | breach % per period |
| `GET /api/tickets/stats/` | dashboard tiles | total, by_status, by_priority, my_open, urgent |
| `GET /api/tickets/stats/by-building/` | dashboard tile | counts per building |

### Missing (per business)
| Required dimension | State | Action |
|---|---|---|
| Monthly ticket count | ✓ implicitly available via `tickets-over-time` with monthly granularity | document in demo script |
| **By ticket type** (melding / klacht / …) | ✗ no endpoint, no chart | Sprint 5 — add `/api/reports/tickets-by-type/` + chart card |
| **By customer** | ✗ no endpoint, no chart | Sprint 5 — add `/api/reports/tickets-by-customer/` + chart card |
| **By building** | ⚠ JSON exists at `tickets/stats/by-building/` but no chart card | Sprint 5 — add chart card; consider whether building stats belong in Reports or Dashboard |
| By status | ✓ `StatusDistributionChart` | done |

**Recommended Sprint 5 work:** three new report endpoints + three
chart cards (by-type, by-customer, by-building). Each follows the
existing `StatusDistributionView` shape (count-by-bucket-with-scope-
isolation) so the diff is small and safe. Estimated 1 sprint.

---

## 7. Local demo script for Ramazan

**Stack to run before the demo (one-time per session):**

```bash
docker compose up -d
docker compose exec -T backend python manage.py migrate
docker compose exec -T backend python manage.py loaddata accounts/fixtures/users.json  # if seed exists
# else: docker compose exec -T backend python manage.py shell to create demo accounts
export PATH="/home/goktug/.nvm/versions/node/v24.15.0/bin:$PATH"
(cd frontend && npm run dev &)   # serves on http://localhost:5173
```

**MailHog** for outgoing emails: <http://localhost:8025>

**Two browser sessions (one normal, one incognito) so different
auth tokens do not collide.**

| Step | Browser A — company side | Browser B (incognito) — customer side | Expected result |
|---|---|---|---|
| 0. Reset | (closed) | (closed) | clean session |
| 1. Login as company admin | open `http://localhost:5173/login`, login as `companyadmin@example.com` / `Test12345!` | – | dashboard renders with tiles |
| 2. Login as customer | – | open `http://localhost:5173/login`, login as `customer@example.com` / `Test12345!` | dashboard renders, "New ticket" button visible |
| 3. Customer creates ticket | – | click "Nieuw ticket" → fill title "Lekkage in Ruimte 4 / Building A", description "Water onder bureau, urgent", category=Melding, priority=High → drag-and-drop a JPG photo → submit | ticket TCK-2026-NNNNNN created, status OPEN, photo attached |
| 4. Company picks up | refresh dashboard, click the new ticket | – | TicketDetailPage opens, photo visible |
| 5. Company takes IN_PROGRESS | click "In behandeling" button | – | status flips to IN_PROGRESS, status history row added |
| 6. Company posts public reply | type "Begrepen, monteur op weg" → "Versturen" (public reply) | – | reply visible in thread |
| 7. Company sends to customer | click "Wacht op goedkeuring" / "Verzenden ter goedkeuring" | – | status flips to WAITING_CUSTOMER_APPROVAL; customer notification email lands in MailHog |
| 8. Customer reviews | – | refresh ticket; thread shows the staff reply + photo | "Goedkeuren" / "Afwijzen" buttons appear |
| 9a. Customer approves | – | click "Goedkeuren" | status APPROVED, MailHog has admin-override-OK email |
| 9b. (alternate) Customer rejects | – | click "Afwijzen", fill reason "Lek nog steeds aanwezig" | status REJECTED, company side will get email |
| 10. (after 9b) Company re-takes | click the ticket → "In behandeling" again | – | status returns to IN_PROGRESS — explicit acknowledgement, **not** automatic |
| 11. Admin closes approved ticket | (after 9a) click "Afsluiten" | – | status CLOSED |
| 12. Show reports | open `/reports` | – | 6 chart cards render: status distribution, tickets-over-time, manager throughput, age buckets, SLA distribution, SLA breach rate |
| 13. Show audit (super admin only) | logout, login as `smoke-super@example.com` / `Test12345!` → `/api/audit-logs/?target_model=tickets.Ticket` | – | super-admin-only feed shows the User / Company / Building / Customer mutations performed during the demo (NOTE: ticket mutations are not yet audited — Sprint 2.2 covers admin entities only) |

**Caveats for the demo:**
- The "by ticket type / by customer / by building" charts are NOT
  in `/reports` yet. If the business asks for them in the demo,
  show the existing dashboards and tickets-over-time, and note that
  the requested dimensions are scheduled for Sprint 5.
- If MailHog has stale messages, click "Delete all messages" before
  starting so only the demo's emails are visible.

---

## 8. Deployment direction (correction)

The earlier `.env.production.example` and `docker-compose.prod.yml`
implied an end-to-end TLS posture (HSTS, secure cookies, SSL
redirect). The business has now clarified that **TLS termination
happens upstream of our app** (NGINX Proxy Manager / Serdar's
firewall). Our app should run **internal HTTP on a port** and trust
the proxy.

| Concern | Current state | What needs to change for prod |
|---|---|---|
| TLS termination | Settings support both: `DJANGO_SECURE_SSL_REDIRECT` and `DJANGO_USE_X_FORWARDED_PROTO` are env-toggled at [`config/settings.py`](../backend/config/settings.py#L233-L246) | Set `DJANGO_SECURE_SSL_REDIRECT=False` (the proxy handles redirect), `DJANGO_USE_X_FORWARDED_PROTO=True`, leave HSTS toggles to operator preference. **No code change.** |
| `ALLOWED_HOSTS` | Env-driven via `DJANGO_ALLOWED_HOSTS` | Set to the public hostname once known + the internal docker hostname the proxy hits (`backend`, or whatever the upstream block configures) |
| `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` | Env-driven | Set to the public `https://` origin |
| Proxy headers | `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` activated when the env var above is True | NPM must forward `X-Forwarded-Proto`, `X-Forwarded-For`, `Host` (or `X-Forwarded-Host`). Audit-log middleware [`audit/context.py:54-65`](../backend/audit/context.py#L54-L65) already trusts the FIRST hop of `X-Forwarded-For`; that matches NPM's behavior. |
| Healthcheck | `/health/live` and `/health/ready` exist (Sprint 1.1). Note from sprint 1.1 doc: in prod, `DEBUG=False` enforces `ALLOWED_HOSTS` so the docker-compose internal probe must either include the internal hostname in `ALLOWED_HOSTS` OR be replaced with an in-process script | When the public hostname is known, add `127.0.0.1`-equivalent or container hostname to `DJANGO_ALLOWED_HOSTS` so the prod `docker-compose.prod.yml` healthcheck wget-against-localhost passes |
| SMTP (Amazon SES) | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` are all env-driven | Operator points env at `email-smtp.<region>.amazonaws.com:587` with SES credentials and the verified `From` address. **No code change.** |
| Postgres / Redis exposure | `docker-compose.prod.yml` exposes ports for db/redis | Remove the `ports:` blocks for `db` and `redis` in production (only `backend` and `frontend` should expose ports; db/redis are container-internal). Tracked as Sprint 4. |
| TLS / certbot / Caddy | Not in our scope | Out of scope. Serdar / NPM owns this. |

**Action items for the deployment-prep batch (Sprint 4):**
1. Update `.env.production.example` to reflect HTTP-internal posture.
   Default `DJANGO_SECURE_SSL_REDIRECT=False`, document that NPM
   should be set to "Force SSL" upstream.
2. Remove the `ports: 5432:5432` and `ports: 6379:6379` blocks from
   `docker-compose.prod.yml` so db/redis are not reachable from
   outside the docker network.
3. Document the NPM proxy config snippet (forward headers, websocket
   pass-through if SLA dashboard ever uses websockets — currently it
   does not).
4. Document the SES credential bootstrap (verifying domain/sender,
   IAM SMTP creds vs IAM keys).

---

## 9. Recommended next batches

| Batch | Scope | Estimate |
|---|---|---|
| **A — minimal demo fixes** | Verify dev seed accounts (`companyadmin@`, `customer@`, `manager@`, `smoke-super@`) all have `Test12345!` and proper memberships; if not, ship a one-line `manage.py` data-fix command. No feature work. | small |
| **B — local demo seed + script** | Add `scripts/demo_seed.py` that idempotently creates a Company, Building, Customer, ticket fixtures, and the four demo accounts with predictable passwords. Add `docs/demo-walkthrough.md` (mirror of §7). | small/medium |
| **C — internal HTTP prod compose prep** | Update `.env.production.example` for HTTP-internal posture, drop public db/redis ports, document NPM headers + SES SMTP. (Per Sprint 4 plan; this batch is just the deltas the business correction requires.) | medium |
| **D — reports polish** | Three new endpoints + chart cards: tickets-by-type, tickets-by-customer, tickets-by-building. Tests follow `test_status_distribution.py` shape. | medium |
| **E — Room model (deferred)** | Only when the business asks for room-level reports. Add `Room` model + data migration from `Ticket.room_label` → `Room`. | medium/large |

---

## 10. What this batch did NOT do

- No code changes to ticket workflow, enums, scoping, or reports.
- No new models or migrations.
- No deployment / Docker edits.
- No frontend changes.
- No tests added.
- No production secrets touched.

This document is the deliverable; the next batches act on it.
