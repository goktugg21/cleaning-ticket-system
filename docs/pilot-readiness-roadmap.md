# Sprint 3.6 — Pilot readiness roadmap and decision log

> Documentation only. No code, schema, deployment, frontend, or test
> changes are introduced by this sprint. Dated: 2026-05-08 against
> `master` at `0c2ff1f` (post Sprint 3.5 merge).

This document is the canonical reference for: where the system stands
after Sprint 3.5, what we deliberately decided NOT to change before
the pilot, what the next two sprints (4 and 5) will own, and the
go / no-go criteria the team will use to call demo and pilot.

---

## 1. Current state

After Sprint 3.5 the system is **directionally aligned** with the
business intent. The end-to-end customer ticket flow works on
`localhost`, the multi-tenant scoping holds across roles, and CI is
in place. Concretely:

- **Demo flow works.** Customer creates ticket with photo →
  company/building-manager progresses → customer approves or rejects
  → admin closes. Two-browser walkthrough is scripted in §7 of
  [docs/product-demo-readiness-audit.md](product-demo-readiness-audit.md).
- **Ticket lifecycle works.** State machine in
  [`backend/tickets/state_machine.py`](../backend/tickets/state_machine.py)
  enforces every transition and records the history.
- **Attachments / photos work.** `TicketAttachment` with randomised
  storage path, MIME + size whitelist, scope-isolation tests.
- **Multi-tenant scoping works.**
  [`backend/accounts/scoping.py`](../backend/accounts/scoping.py)
  filters tickets / customers / buildings per role, with adversarial
  tests in `tests/test_scoping.py` files across multiple apps.
- **CI exists.** Sprint 3 (`fbae8c8`) added
  [.github/workflows/test.yml](../.github/workflows/test.yml) (PR
  validation: backend tests on real Postgres + Redis services,
  frontend build) and
  [.github/workflows/build-images.yml](../.github/workflows/build-images.yml)
  (GHCR publishing on master). Frontend lint is INFORMATIONAL ONLY
  due to 33 pre-existing errors.
- **Audit infrastructure exists.** Sprint 2.2 (`0cc8972`) ships an
  `audit` app that records CREATE / UPDATE / DELETE events on User,
  Company, Building, Customer with a super-admin-only feed at
  `GET /api/audit-logs/`.
- **Reports exist but are incomplete.** Status distribution,
  tickets-over-time, manager throughput, age buckets, SLA
  distribution, SLA breach rate. **Missing dimensions: by ticket
  type, by customer, by building (chart card).** No CSV/PDF export.
- **Production deployment prep is still needed.** Settings already
  support HTTP-internal-behind-a-proxy posture via env toggles, but
  `.env.production.example` still ships HTTPS-redirect-on /
  HSTS-on defaults that contradict the new business direction
  (NPM/Serdar handles TLS upstream). Sprint 4 owes that cleanup.

Quality baseline (commit `0c2ff1f`):
- Backend tests: **416/416 PASS** (Sprint 3.5 verification).
- Frontend build: clean (`tsc -b && vite build`).
- Admin smoke: **PASS=58 FAIL=0 SKIP=0**.

---

## 2. Confirmed product assumptions (kept for demo + pilot)

These are the assumptions we are **deliberately accepting** as
correct enough for demo and pilot. They are NOT accidental
limitations; they are recorded decisions that we will revisit only
after explicit business confirmation.

1. **Hierarchy is `Company → Building → Customer`.**
   `Building.company` is a hard FK; `Customer.company` and
   `Customer.building` are both hard FKs (see
   [`backend/customers/models.py`](../backend/customers/models.py)).
   The unique constraint is `(company, building, name)`, which means
   a `Customer` row is effectively a *customer-at-a-building*
   (customer-location), not a global account.
2. **`CustomerUserMembership` controls customer access.** A customer
   user is granted access to one or more `Customer` rows
   (customer-locations). Scoping in
   [`accounts.scoping.scope_tickets_for`](../backend/accounts/scoping.py#L108-L127)
   filters the ticket queryset by `customer_id__in=memberships`.
3. **Rooms remain free-text.** `Ticket.room_label CharField(max_length=255)`
   is the workaround. There is no `Room` model. Adding one is
   deferred until the business asks for room-level reports.
4. **Reject flow is explicit.** Customer rejects →
   `WAITING_CUSTOMER_APPROVAL → REJECTED`. Returning to work is a
   separate, explicit staff transition (`REJECTED → IN_PROGRESS`)
   driven by SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER. We
   keep this two-step semantics so staff must acknowledge a
   rejection rather than silently re-queueing.
5. **Email identity ≠ customer-account identity.** A `User.email`
   identifies a person. It is **not** a safe long-term grouping key
   for "the same customer across multiple buildings", because the
   same email may legitimately appear at multiple customers (a
   facility manager who works for two unrelated tenants would land
   here). Any future "by customer account" rollup must explicitly
   model the account, not infer it from email.
6. **Reports are aware of customer-locations, not customer
   accounts.** All current and Sprint-5-planned report endpoints
   group by `Customer` row, which is location-level. `building_name`
   is included alongside `customer_name` in CSVs so
   "Acme – Building A" and "Acme – Building B" are not silently
   merged.

---

## 3. Open business questions

These questions must be answered with concrete examples before any
hierarchy refactor is even discussed:

1. **Is "Customer" a global account, or a customer-location under
   a building?** Today it is the latter. Business voice messages
   imply the former might be desired ("müşterinin yetkilileri sonra
   bu insanların binaya yetkisi var") but this is not confirmed.
2. **Can the same customer span multiple buildings?** If yes, how
   should reporting roll up — by account, by location, or both
   simultaneously?
3. **Can one customer user access only some buildings under that
   customer?** If yes, we need per-building permissions per user
   *within* a single customer account. That is a different shape
   than the current per-`Customer` membership.
4. **Should "by customer" reports group by customer account or by
   customer/building location?** Different SQL, different headers,
   different CSV columns.
5. **Should ticket creation start from building-first or
   customer-first?** Currently the customer user picks a customer
   they're a member of, and the building/company are derived from
   that. If "customer" becomes account-level, the form might need
   to ask the user to pick the building too.
6. **If the same email appears in multiple customer records, is
   that one person?** *Yes for user identity* — `User.email` is
   unique, one row, one login. *Not enough for customer-account
   identity* — that conflates personal identity with organisational
   grouping.
7. **Are rooms only labels, or should they become managed entities
   later?** If managed (assignable, scoped, reportable), the
   migration from `room_label` → a `Room` FK is a separate batch.

We will not refactor on the strength of voice-message hints alone.

---

## 4. Hierarchy refactor decision

**State clearly: no hierarchy refactor now. The current model is
correct enough for demo and pilot.** The customer-location row IS
the right shape for "this customer at this building", and the
`CustomerUserMembership` table IS the right shape for "this user
can act on this customer-location".

We will refactor only if and when the business answers the §3
questions in a way that requires it.

### Future safe migration path (only when triggered)

If §3 confirms a true customer-account hierarchy is needed, the
refactor must be **additive**, not destructive:

1. Add a new `CustomerAccount` model (`name`, `company` FK, optional
   `contact_email`, `is_active`, timestamps).
2. Add a **nullable** `Customer.account` FK pointing at
   `CustomerAccount`. Existing rows keep `account=NULL`.
3. **Data migration** groups existing `Customer` rows by `company`
   plus a normalised key (e.g. trimmed lowercase name where the
   business confirms two location rows belong to the same account).
   The migration is reversible (drop the FK, leave Customer
   untouched).
4. **Keep `Customer` as a customer-location row.** Do NOT collapse
   it into `CustomerAccount`. Buildings still attach to `Customer`,
   tickets still attach to `Customer`. The new `CustomerAccount` is
   a parent grouping, not a replacement.
5. Update scoping helpers in
   [`accounts.scoping`](../backend/accounts/scoping.py) so that an
   account-level membership grants access to *all* customer
   locations under that account, while location-level memberships
   keep working unchanged.
6. Update reports: add `?group_by=account|location` switch on the
   by-customer endpoints rather than forking the queries.
7. Update frontend forms only **after** the API has been stable
   through one release cycle.
8. Expand tests for: scoping (account-level grants, mixed
   account+location grants), reports (account vs location group_by),
   ticket creation (building-first vs customer-first), audit log
   (CustomerAccount mutations).

### Risk assessment

| Path | Risk | Notes |
|---|---|---|
| Stay on current model for demo + pilot | **low** | Already shipped, already tested, business has not contradicted the shape with concrete examples |
| Additive `CustomerAccount` refactor later | **medium**, manageable | Additive FK + reversible data migration; no existing API contract is broken |
| Replacing `Customer` with `CustomerAccount` directly | **high**, avoid | Forces a destructive data migration, breaks every report URL and frontend form, breaks audit-log retrospect |

**Default path: low risk.** Refactor only on explicit business
trigger.

---

## 5. Sprint 4 plan — production / internal HTTP hardening

The business has clarified that **TLS termination happens upstream**
(NGINX Proxy Manager / Serdar's external firewall). Our app runs
internal HTTP on a port. We do NOT configure TLS, certbot, Caddy,
or any HTTPS redirect inside the app.

### Required changes
- **`.env.production.example`:** flip `DJANGO_SECURE_SSL_REDIRECT`
  default from `True` to `False`. The proxy handles the redirect.
  Keep the env var so an operator who DOES want app-level redirect
  can opt in.
- **`.env.production.example`:** keep `DJANGO_USE_X_FORWARDED_PROTO=True`.
  This activates `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
  in [`config/settings.py`](../backend/config/settings.py#L233-L246) so
  Django treats requests forwarded by NPM as secure.
- **`.env.production.example`:** document that HSTS toggles
  (`DJANGO_SECURE_HSTS_SECONDS`, `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`,
  `DJANGO_SECURE_HSTS_PRELOAD`) are now operator decisions; they
  affect what Django *sets* on responses, but the proxy is the
  authoritative HSTS source. Default `0` is acceptable when NPM
  sets HSTS itself.
- **Document required NPM proxy headers**:
  - `X-Forwarded-Proto` — required for the SSL header trust above.
  - `X-Forwarded-For` — first hop is recorded in `AuditLog.request_ip`
    by the audit middleware (already trusted via
    [`audit/context.py:54-65`](../backend/audit/context.py#L54-L65)).
  - `Host` (or `X-Forwarded-Host`) — must arrive as the public
    hostname so `ALLOWED_HOSTS` matches.
  - Optionally `X-Request-Id` / `X-Correlation-Id` — recorded in
    `AuditLog.request_id` if the proxy sets one.
- **`docker-compose.prod.yml`:** **already correct** — db and redis
  do NOT expose ports. Sprint 4 only verifies and documents this.
  Frontend (`FRONTEND_PORT:80`) is the only exposed port and is what
  NPM proxies into.
- **SES SMTP**: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` are
  already env-driven. Sprint 4 documents the AWS SES bootstrap:
  - verify the sending domain (or single `From` address) in SES.
  - generate IAM SMTP credentials (NOT raw IAM keys).
  - use `email-smtp.<region>.amazonaws.com:587` with TLS on.
  - exit SES sandbox if production sending volume requires it.
- **Healthcheck + `ALLOWED_HOSTS`:** with `DEBUG=False`, Django
  enforces `ALLOWED_HOSTS`. The prod docker-compose healthcheck
  probes `localhost:8000/health/live`, which will be rejected
  unless an internal hostname is added to `DJANGO_ALLOWED_HOSTS`.
  Sprint 4 documents one of:
  - include the container hostname (or `localhost`) in
    `DJANGO_ALLOWED_HOSTS` alongside the public domain, OR
  - replace the HTTP probe with an in-process Django `manage.py`
    healthcheck call.
- **Production secrets policy**: keep all real DSNs / SES
  credentials / Postgres passwords out of the repo. The committed
  `.env.production.example` documents shape only, with
  `replace-with-...` placeholders. Operators set real values via
  the orchestrator's secret store.

### Sprint 4 deliverables
- Updated `.env.production.example`.
- Updated `docs/ci.md` (or new `docs/deployment.md`) with the NPM
  config snippet, the SES bootstrap, the healthcheck/`ALLOWED_HOSTS`
  caveat, and the secret-handling policy.
- No application code change.
- Quality gates unchanged: 416/416 backend, 58/58 smoke.

---

## 6. Sprint 5 plan — reports + CSV/PDF export

The business asked for monthly counts and breakdowns by type,
customer, and building. Tickets-over-time already produces monthly
counts (granularity auto-picked when range ≥ 60 days). The three
missing dimensions plus export are Sprint 5.

### New report endpoints

Recommended pattern, mirroring the existing
`StatusDistributionView` shape (count-by-bucket-with-scope-isolation):

| Endpoint | Bucket | Filters | Default ordering |
|---|---|---|---|
| `GET /api/reports/tickets-by-type/` | `Ticket.type` | from, to, company_id, building_id, customer_id, status | -count |
| `GET /api/reports/tickets-by-customer/` | `Customer` row (customer-location, **NOT** account; see §2.6) | from, to, company_id, building_id, type, status | -count |
| `GET /api/reports/tickets-by-building/` | `Building` row | from, to, company_id, customer_id, type, status | -count |

All three respect the existing scope helpers
([`scope_tickets_for`](../backend/accounts/scoping.py#L108-L127),
`scope_companies_for`, `scope_buildings_for`,
`scope_customers_for`). A customer user only sees buckets that
contain tickets they themselves can read; a building manager only
sees their assigned buildings; etc.

### Export pattern

Two choices. Pick **B (separate export endpoints)** to keep the
JSON endpoints small and let the export endpoints carry their own
content negotiation, file naming, and streaming buffer:

```
GET /api/reports/tickets-by-type/export.csv
GET /api/reports/tickets-by-type/export.pdf
GET /api/reports/tickets-by-customer/export.csv
GET /api/reports/tickets-by-customer/export.pdf
GET /api/reports/tickets-by-building/export.csv
GET /api/reports/tickets-by-building/export.pdf
```

Same query-string filters as the JSON endpoint. Reuse the same
scope-resolved queryset.

### CSV columns (include IDs to avoid ambiguity)

| Endpoint | Columns |
|---|---|
| tickets-by-type | `ticket_type`, `ticket_type_label`, `count`, `period_from`, `period_to` |
| tickets-by-customer | `customer_id`, `customer_name`, `building_id`, `building_name`, `company_id`, `company_name`, `count`, `period_from`, `period_to` |
| tickets-by-building | `building_id`, `building_name`, `company_id`, `company_name`, `count`, `period_from`, `period_to` |

Crucially for **tickets-by-customer**: `building_name` is in the row
so two `Customer` rows that happen to share `name` (e.g. "Acme") at
different buildings are visibly distinct. The CSV must be
location-aware, not account-aware.

### PDF format (good-enough business report, not pixel-perfect)

- Title (e.g. "Tickets by customer — 2026-04-01 to 2026-04-30").
- Date range.
- `generated_at` timestamp.
- Scope summary (which company / building / customer filter was
  applied; "All" if not).
- Table with the same columns as the CSV (drop the period columns,
  put them in the header instead).
- Optional embedded chart image only if it ships easily; table-first
  is acceptable.
- A4 portrait, default font, no logo bake-in.

### Filters

| Filter | by-type | by-customer | by-building |
|---|---|---|---|
| from / to | ✓ | ✓ | ✓ |
| company_id (where allowed) | ✓ | ✓ | ✓ |
| building_id | ✓ | ✓ | — |
| customer_id | ✓ | — | ✓ |
| ticket type | — | ✓ | ✓ |
| status | ✓ | ✓ | ✓ |

### Tests

- **Scope isolation** for each new endpoint (super admin sees all,
  company admin sees own company only, building manager sees
  assigned buildings only, customer user sees linked customers
  only). Mirror `tests/test_scoping.py`.
- **CSV** tests: `Content-Type: text/csv`, `Content-Disposition`
  with sane filename, header row matches column spec, row count
  matches the JSON endpoint's `len(results)`.
- **PDF** tests: `Content-Type: application/pdf`, response body
  starts with `%PDF-`, non-empty, contains the title text.
- **Permission** tests for every role × every endpoint combination.

### Frontend

- Three new chart cards in
  [`frontend/src/pages/reports/`](../frontend/src/pages/reports/):
  `TicketsByTypeChart`, `TicketsByCustomerChart`,
  `TicketsByBuildingChart`. Use `recharts` like the existing cards
  (already in the lazy-loaded `ReportsPage` chunk).
- Each card has an "Export CSV" button + an "Export PDF" button.
  Buttons hit the export endpoints with the active filter set.
- Dutch + English labels; mirror existing report i18n keys in
  [`frontend/src/i18n/{nl,en}/reports.json`](../frontend/src/i18n/nl/reports.json).

### Out of scope for Sprint 5

- Account-level rollups (would require §4's `CustomerAccount`
  refactor first).
- Real-time / websocket pushes.
- Per-user saved-filter presets.

---

## 7. Pilot readiness assessment: 2-3 companies / ~50 users

**After Sprint 4 + Sprint 5, the system should be pilot-ready for
2-3 companies and roughly 50 users**, *assuming*:

- VPS is stable (operator's responsibility).
- DB backups are configured (operator's responsibility — `pg_dump`
  cron or managed-Postgres snapshot, plus a one-time restore drill).
- SES SMTP credentials are valid (verified domain, IAM SMTP creds,
  out of sandbox if needed).
- NGINX Proxy Manager / firewall proxy is configured to forward the
  headers documented in §5.
- Demo / admin users from the dev fixtures are either deleted or
  given non-trivial passwords. (No `Test12345!` accounts on a
  publicly reachable host.)
- Basic monitoring and log access exist. The Sprint 1.1 LOGGING
  config writes structured stdout; the operator pipes
  `docker compose logs` into whatever they already use, or wires
  Sentry via the SDK that Sprint 1.3 already shipped (empty DSN by
  default, set to enable).
- Support process is manual but known: who handles ticket-related
  questions, who has super-admin, what the escalation path is.

### Pilot-ready vs Enterprise-ready

| Question | Answer |
|---|---|
| Pilot-ready (2-3 companies / ~50 users) after Sprint 4 + 5? | **Yes.** |
| Enterprise / large-scale production-ready? | **No, not yet.** |

### Non-blocking future work (do after pilot)

- Backup / restore *rehearsal* (not just configured — actually
  tested by destroying and restoring a staging DB).
- Monitoring / alerting (Sentry release tagging, uptime probe on
  `/health/ready`, log-volume alert).
- Stronger audit UI (the current super-admin browser is JSON-only;
  a paginated UI with target-model picker is a Sprint 6+ item).
- Ticket mutation auditing (Sprint 2.2 covers User / Company /
  Building / Customer; ticket-row audits are a separate decision —
  there's an existing `TicketStatusHistory` table for status
  transitions specifically).
- Reports polish (saved filters, drill-down, export-to-Excel).
- Role / scope admin UX polish.
- Optional `CustomerAccount` hierarchy refactor (only if §3 is
  answered).
- Optional `Room` model.

---

## 8. Go / no-go checklist

### Go for demo

- [ ] `manage.py test --keepdb`: 416/416 OK.
- [ ] Frontend: `npm run build` clean.
- [ ] Admin smoke: `PASS=58 FAIL=0 SKIP=0`.
- [ ] Demo seed accounts verified (`companyadmin@example.com`,
      `customer@example.com`, `manager@example.com`,
      `smoke-super@example.com`, all on `Test12345!`).
- [ ] Customer-side flow: ticket creation with photo works end-to-end.
- [ ] Company-side flow: status transitions and reply work; emails
      land in MailHog.
- [ ] Customer approves and rejects produce expected status changes
      and notifications.
- [ ] MailHog visible at `http://localhost:8025`.
- [ ] Reports page renders all 6 existing chart cards without error.

### Go for pilot

- [ ] Sprint 4 deployment hardening completed (env file refreshed,
      NPM headers documented, SES bootstrap documented,
      healthcheck/`ALLOWED_HOSTS` caveat documented).
- [ ] db / redis not publicly exposed (`docker-compose.prod.yml`
      has no `ports:` blocks for these — already true; verify on
      the deployed host).
- [ ] SES configured: domain verified, IAM SMTP creds active, test
      send from production succeeds.
- [ ] NPM proxy headers tested against the running stack —
      `X-Forwarded-Proto`, `X-Forwarded-For`, `Host`/`X-Forwarded-Host`.
- [ ] Backups configured: `pg_dump` or managed-Postgres snapshots
      with retention; one restore drill performed.
- [ ] Sprint 5 reports + CSV/PDF export merged.
- [ ] At least one admin can onboard: company → building → customer
      → user, end-to-end via the admin UI.
- [ ] Support contact / process documented (who, where, how).

### No-go (any one is a hard stop)

- Tests failing in CI or locally.
- Smoke failing.
- Any role can read tickets / customers / buildings outside its
  scope (scope leak).
- Hidden / internal-note attachments visible to customer users.
- DB or Redis reachable from outside the docker network.
- No backup or no successful restore drill.
- SMTP not working — no email delivery to a real inbox.
- Production env / secrets unclear or in the repo.

---

## 9. Recommended order from here

1. **Sprint 3.6 (this batch)** — roadmap and decision log.
2. **Sprint 3.7 / 4.0** — demo seed + walkthrough script. The
   walkthrough already exists in §7 of
   [docs/product-demo-readiness-audit.md](product-demo-readiness-audit.md);
   the missing piece is an idempotent `scripts/demo_seed.py` that
   creates the accounts, company, building, customer, and a couple
   of demo tickets in a clean state.
3. **Sprint 4** — production / internal HTTP hardening per §5
   (env file refresh, deployment doc, no app code).
4. **Sprint 5** — reports dimensions + CSV/PDF export per §6.
5. **Pilot** with 2-3 companies / ~50 users. Collect feedback for
   2-4 weeks before any further architecture work.
6. **Only after pilot feedback** — `CustomerAccount` hierarchy
   refactor *if explicitly required* by the business answers in §3.

---

## 10. What this sprint does not do

- No app code (no Python, no TypeScript).
- No database migrations.
- No frontend UI changes.
- No reports implementation (Sprint 5 owns it).
- No deployment changes (Sprint 4 owns them).
- No hierarchy refactor.
- No new tests.

This document is the deliverable; the next batches act on it.
