# CLAUDE.md — Cleaning Ticket System

Single source of truth for **how Claude Code should work in this repo**. Loaded
into every Claude conversation opened from this directory. Anything that
contradicts these rules is wrong by default — push back instead of complying.

Vendor-neutral cleaning-operations ticket system: Django 5.2 + DRF backend,
React 19 + TypeScript + Vite frontend, Postgres, Redis, Celery, Docker Compose.

**Deployment status:** production is **NOT deployed yet**. `crmtest.osius.nl`
is a dev/test environment (served by the prod compose stack — see §6).
Production deployment is a standing, open milestone.

The full documentation map is [docs/README.md](docs/README.md) — the index of
every live doc. Read it to find anything not covered here.

---

## 1. How we work (the real model)

The **owner does not write code.** The workflow is:

- A web-based Claude (architect / PM / auditor) recons a **read-only clone**,
  designs the work, and writes precise prompts for **Claude Code (CC)**.
- **CC executes** on the dev/test server (this environment).
- The owner pastes CC's logs back to web-Claude. Web-Claude **independently
  verifies the pushed commits from `origin`** — never from CC's self-report —
  and issues a merge verdict. **A CC self-report is never the basis for a merge
  verdict.**
- The owner performs all GitHub UI actions (PRs, merges). CC pushes branches;
  **CC does not open PRs unless explicitly told to.**

---

## 2. Project layout

```
backend/                Django project
  accounts/             Users, roles, scoping, permission resolvers (see §7)
  audit/                Generic AuditLog + signal-driven write path
  buildings/            Building + BuildingManagerAssignment / StaffVisibility
  companies/            Provider company + CompanyUserMembership
  config/               Settings, urls, security validator, pdf_branding
  customers/            Customer org + per-user per-building access + policy
  extra_work/           Extra-work request workflow + pricing + final amounts
  invoicing/            Invoice lifecycle, numbering, reversal, PDF (see §2A)
  notifications/        Email send + NotificationLog
  planned_work/         Recurring work (rule-based + calendar-tick model)
  reports/              Revenue/EW reporting — REAL: views + urls + exports
                        (wired at /api/reports/). NOT a stub.
  sla/                  SLA engine — REAL: business_hours, services, signals,
                        Celery tasks, sla_backfill command, test package.
                        Signal/task-driven, no HTTP surface. NOT a stub.
  tickets/              Ticket model + state machine + views + staff assignment
frontend/               React + TS + Vite SPA
  src/api/              Typed API client + types.ts (CUSTOMER_PERMISSION_KEYS)
  src/auth/             JWT context + interceptors + nav permission gate
  src/lib/              Pure helpers (billing.ts = the earned-amount rule)
  src/i18n/             nl/en translation bundles (strict lockstep)
  src/pages/            Route-level pages
  tests/                Playwright e2e
docs/                   All docs. docs/README.md is the index; docs/archive/
                        is frozen history (do not rely on it).
scripts/ops/            Live operational scripts (backup/restore/health/smoke)
scripts/playwright_admin_smoke/  Measured-geometry admin smoke harness
```

## 2A. Invoicing (shipped PR #110–#114)

Authoritative description:
[docs/product/sot-addendum-b-invoicing.md](docs/product/sot-addendum-b-invoicing.md).
Headline facts (verify against `backend/invoicing/` before changing):

- Lifecycle `DRAFT → ISSUED → SENT`, plus un-issue (`ISSUED → DRAFT`) and
  reversal (a terminal negative credit note).
- **Numbering is assigned at SEND, not at issue** — gapless `YYYY-NNNN`,
  per-company per-year. An ISSUED-but-unsent invoice shows **CONCEPT**.
- A SENT invoice is immutable; corrections go through reversal, which releases
  the original's Extra Work back to the unbilled pool. The release depends on
  the `invoice__reversed_by__isnull=True` predicate in
  `invoicing/selectors.py` — preserve it.
- **`earned` = `rowAmounts()` in `frontend/src/lib/billing.ts`
  (final-with-quoted-fallback) is the ONE billing-total rule.**

---

## 3. Hard rules (do not violate)

### Security floor — RBAC invariants H-1..H-11
The 11 hard invariants in
[docs/reference/rbac-matrix.md §3](docs/reference/rbac-matrix.md) are the
security floor. Any change that contradicts one is a **P0 regression even if
all tests still pass** — extend the safety-net tests instead. **Tenant scoping
is a hard invariant: every endpoint must be verified for cross-tenant /
cross-customer leakage.** Pay particular attention to H-1/H-2 (no cross-tenant
bleed), H-5 (STAFF cannot approve customer-side decisions), H-6/H-7 (only
SUPER_ADMIN grants `CUSTOMER_COMPANY_ADMIN`), H-10 (every permission/role/scope
change writes an `AuditLog`), H-11 (permission override ≠ workflow override).

### Permission keys
- Provider keys: `osius.*` namespace (technical-debt naming — do NOT rename
  without a dedicated sprint). Resolver: `backend/accounts/permissions_v2.py`.
- Customer keys: `customer.*`. Resolver: `backend/customers/permissions.py`.
  Typed valid-key set: frozenset `CUSTOMER_PERMISSION_KEYS`.
- Unified composer: `backend/accounts/permissions_effective.py`. **Never** offer
  `osius.*` keys in customer-side UI (frontend mirrors `CUSTOMER_PERMISSION_KEYS`
  in [frontend/src/api/types.ts](frontend/src/api/types.ts)).

### State machines
- Ticket transitions: `backend/tickets/state_machine.py` — `ALLOWED_TRANSITIONS`
  is the authority. Ticket workflow override (Sprint 27F-B1):
  `TicketStatusHistory.is_override` + `override_reason`; provider-driven
  customer-decision transitions coerce `is_override=True` and REQUIRE
  `override_reason` (HTTP 400 `override_reason_required`).
- Extra-work transitions: `backend/extra_work/state_machine.py` (its own
  `is_override + override_reason` surface).
- Invoicing: `backend/invoicing/state_machine.py` (see §2A).
- Every state mutation writes a `*StatusHistory` row inside the same
  `transaction.atomic()`. The override history row IS the audit trail — do NOT
  additionally register `*StatusHistory` for generic AuditLog (H-11).

### Audit / migrations
- New tracked field on an audited model → edit `_*_TRACKED_FIELDS` in
  `backend/audit/signals.py` AND add a test in `backend/audit/tests/`.
- **Additive migrations only.** No destructive schema change without explicit
  owner sign-off. Every model change needs a migration; never edit an applied
  one. Confirm with `python manage.py makemigrations --dry-run --check`.
  Backfill data migrations required when a new column has a non-default meaning.

### Tests & gates
- **Backend:** run from `backend/`: `python manage.py test`. **Judge by the
  textual `OK` / `FAILED` line, NEVER the exit code.** Real Postgres (CI
  provides one); mock only the SMTP transport. Test-first for new features.
- **Frontend gate** (all three, in `node:22-alpine`):
  `tsc --noEmit -p tsconfig.app.json` + `eslint .` + `npm run build`.
  **ESLint baseline is EXACTLY 48 (46 errors, 2 warnings).** Add **no** new
  violations and **no** new `eslint-disable`. No synchronous `setState` in an
  effect body; for prop-derived state, key the component by id.

### Frontend conventions
- TypeScript strict; no implicit `any`. API types in
  [frontend/src/api/types.ts](frontend/src/api/types.ts), in lockstep with
  backend serializers.
- i18n: every user-visible string through `t()`. **`nl` and `en` bundles in
  strict lockstep — identical key sets** (nl is primary).
- Layout/render claims require **measured rendered geometry, never
  screenshots** (see the playwright_admin_smoke harness).
- **Deriving render order from a hardcoded array literal defeats
  TypeScript's exhaustiveness checking.** An exported ordered constant
  that every consumer iterates is checked by the compiler when a new
  entry is added; a second, independently-maintained array used only for
  render order is not. Sprint 126's `documents` permission group
  rendered a headerless column and was invisible in the per-user
  permission editor for three sprints before Sprint 130 unified both
  consumers onto the single `PERMISSION_GROUPS` constant. Iterate the
  shared exported constant, never a second local copy.
- **A list endpoint's `pagination_class` is a contract with EVERY
  caller, not just the one you're fixing.** Loosening it (e.g. to
  `UnboundedPagination`) to stop one picker's truncation changes the
  response shape for every OTHER caller that reads `count`/`next`/
  `previous` and has real pagination UI. Sprint 134 did this to
  `CompanyViewSet`/`CustomerViewSet`/`BuildingViewSet` to fix admin
  pickers and broke the admin LIST pages' own prev/next in the same
  change; Sprint 135 reverted it and fixed the pickers client-side
  instead (exhaustive paging, the Sprint 120 pattern). Fix the caller
  that has no pagination UI, not the endpoint every caller shares.
- **`ConfirmDialog` / native `<dialog>` is imperative — always render it
  unconditionally and drive it entirely through the ref.** Wrapping it in
  `{condition && <ConfirmDialog .../>}` mounts an INVISIBLE dialog (a
  native `<dialog>` is not visible just because it is in the DOM) and the
  trigger button looks dead (Sprint 128); unmounting one that is still
  open without calling `.close()` first can leave the whole page inert
  (Sprint 118, the frozen-screen bug). Full writeup:
  [docs/engineering/claude-code-operational-notes.md](docs/engineering/claude-code-operational-notes.md).

### Naming / style
- Backend Django/PEP-8: snake_case fields, CamelCase models, dot-namespaced
  permission keys. App-scoped file names (`serializers_users.py`,
  `views_staff.py`) — do not collapse into mega-files.
- Frontend: PascalCase components, camelCase functions, kebab-case CSS.
- **No emojis** in code, comments, commits, or PR titles unless asked; i18n UI
  copy is the only exception.

### Git hygiene
- **Stage every commit by EXPLICIT path.** Never `git add -A` blindly.
- Commit identity: `Goktug YILDIRIM <goktugyildirim2861@gmail.com>`.
- Trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Never stage:** `docs/transkript*`, `PRODUCTION_READINESS_AUDIT.md`,
  any `*:Zone.Identifier`, the **repo-root** `logo.png`, `*.code-workspace`,
  any stray `preview.config.mjs`. (Note:
  `backend/assets/branding/osius_logo.png` IS a normal committed asset — the
  ban is only the repo-root `logo.png`.)

---

## 4. Authoritative product sources & doc hierarchy

- [docs/reference/rbac-matrix.md](docs/reference/rbac-matrix.md) — RBAC / role
  model / hard invariants (security floor).
- [docs/product/source-of-truth.md](docs/product/source-of-truth.md) — what the
  system must become.
- [docs/product/sot-addendum-a-meeting2.md](docs/product/sot-addendum-a-meeting2.md)
  — Addendum A (company-wide CCA, people mgmt, billing month, recurrence).
- [docs/product/sot-addendum-b-invoicing.md](docs/product/sot-addendum-b-invoicing.md)
  — Addendum B (the invoicing subsystem).
- [docs/product/system-business-logic-and-workflows.md](docs/product/system-business-logic-and-workflows.md)
  — plain-English business logic.
- [docs/product/requirements-meeting-2026-05-15.md](docs/product/requirements-meeting-2026-05-15.md)
  — stakeholder requirements (product floor).
- [docs/planning/sprint-checklist.md](docs/planning/sprint-checklist.md) — the
  living gap-closing plan and current sprint state.

**Hierarchy rule:** the Source of Truth is authoritative for *what the system
is*; an **Addendum wins over the base SoT** for the items it covers; **where
docs and code disagree, the code is the truth — report the drift, do not
silently follow the doc.**

---

## 5. Local dev & test

```bash
# Dev stack (Postgres, Redis, MailHog, backend, frontend dev server)
docker compose up -d

# Backend tests (from backend/)
cd backend && python manage.py test        # judge by the OK/FAILED line

# Frontend gate
cd frontend && npm run typecheck && npm run lint && npm run build
```
Captured email: MailHog at <http://localhost:8025>.

Operational gotchas (read before touching shell scripts / the Playwright smoke):
[docs/engineering/claude-code-operational-notes.md](docs/engineering/claude-code-operational-notes.md)
— the Edit tool drops `+x` on `.sh` files; `cmd | tee file | head` truncates via
SIGPIPE (write to file, read separately); Playwright artifacts are root-owned;
multi-line content through the WSL bridge needs a tempfile, not a heredoc.

---

## 6. Infrastructure — crmtest runs the PROD compose stack

`crmtest.osius.nl` is served by the **production compose stack**, not the dev
stack:

- File `docker-compose.prod.yml`, project **`cleaning-ticket-prod`**, **6
  containers**: `db`, `redis`, `backend`, `worker`, `beat`, `frontend`.
- **Every crmtest command needs `-f docker-compose.prod.yml`.** A bare
  `docker compose ...` targets the DEV stack instead.
- The backend startup command auto-runs `migrate && collectstatic && gunicorn`,
  so **migrations auto-apply on backend recreate** — no manual migrate step.
- Only `db`, `redis`, `backend` have healthchecks (the backend uses a TCP
  socket probe, because an HTTP healthcheck would trip the `ALLOWED_HOSTS`
  gate under `DEBUG=False`). `worker` / `beat` / `frontend` showing **Up** with
  no healthcheck is normal.
- Docker commands in this environment are wrapped: `sg docker -c '...'`.
- Deploy runbook: [docs/engineering/deployment.md](docs/engineering/deployment.md).
  Env setup: [docs/engineering/env-setup.md](docs/engineering/env-setup.md).
  CI: [docs/engineering/ci.md](docs/engineering/ci.md).

---

## 7. accounts/ has FOUR overlapping permission modules

All four are **live and imported** — do not assume any one is dead:

- `permissions.py` — DRF permission classes + role helpers (the broadest use).
- `permissions_v2.py` — the `osius.*` provider-key resolver.
- `permissions_effective.py` — the unified `has_permission` /
  `effective_permissions` composer.
- `effective_actions.py` — per-scope role-default / action computation.

Before "simplifying" any of them, grep for its importers first.

---

## 8. Things to NOT do

- **Never commit secrets.** `.env` and `.env.*` are gitignored; the tracked
  `.env.example` and `.env.production.example` are the CONTRACTS. When a new
  env var is introduced, update the template — **never** commit a real value.
- **Do not add backwards-compatibility shims for the deprecated `Customer`
  visibility fields** `show_assigned_staff_name` / `show_assigned_staff_email`
  / `show_assigned_staff_phone`. They are mirrored by `CustomerCompanyPolicy`
  (the `customer.policy` one-to-one) but are still the runtime read source —
  both sets live in parallel and the legacy fields stay until the read-switch
  is deliberately scheduled (deferred from G-B5). The same "don't build on it,
  don't shim it" applies to the deprecated single-building anchor FKs
  `Customer.building` and `Contact.building` — superseded by the M:N
  `CustomerBuildingMembership` / `ContactBuildingLink`, kept nullable for
  back-compat until a future sprint drops them.
- **Test runners.** Backend is Django `manage.py test` — do not introduce an
  alternative. Frontend e2e is Playwright — do not introduce an alternative.
  Frontend **component/unit** tests have **no runner yet**; adding one is
  explicitly in scope for the planned Frontend Testing Sprint and requires
  owner sign-off — do not add one opportunistically in unrelated work.
- **Do not write a new mega-doc** when the content belongs in an existing live
  doc. Every new doc is added to [docs/README.md](docs/README.md) in the SAME
  commit that creates it (the index's own rule).
- **Do not close a sprint without updating
  [docs/planning/sprint-checklist.md](docs/planning/sprint-checklist.md)'s
  NOW / NEXT / SHIPPED sections in that same branch.** This file drifted out
  of date twice before Sprint 122.1 restructured it — both times because the
  update was left for a later, separate docs-only pass instead of being part
  of the sprint that made the old state stale. The update is part of
  finishing a sprint, not optional follow-up.
- **Do not add a local `is_company_admin` short-circuit that grants a
  customer-side ACTION before reaching `customers.permissions.user_can`** — it
  silently bypasses the `CustomerCompanyPolicy` layer. `user_can` resolves a
  company-wide CCA on its own (no access rows needed). Scoping/visibility
  helpers are the deliberate exception (they decide what a CCA sees, not what
  it may do). See
  [docs/product/sot-addendum-a-meeting2.md](docs/product/sot-addendum-a-meeting2.md)
  §A.1.
- **Do not render a list from a SERVER collection without a bound.** Every
  such list is scrollable
  ([frontend/src/components/BoundedList.tsx](frontend/src/components/BoundedList.tsx)),
  paginated, or explicitly capped with a "show all" affordance. Lists over
  fixed local constants (option arrays, enums) are exempt. Real tenants have
  hundreds of buildings, users and tickets — an unbounded list looks fine on
  seed data and breaks on real data.
