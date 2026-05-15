# CLAUDE.md — Cleaning Ticket System

This file is the single source of truth for **how Claude Code should work in
this repository**. It is loaded automatically into every Claude conversation
opened from this directory. Anything contradicting these rules is wrong by
default — push back instead of complying.

The repository is a vendor-neutral cleaning operations ticket system:
Django 5.2 + DRF backend, React 19 + TypeScript + Vite frontend, Postgres,
Redis, Celery, Docker Compose. Production is live (see
[docs/RELEASE_STATUS.md](docs/RELEASE_STATUS.md)).

---

## 1. Project layout (where things live)

```
backend/                Django project (apps below)
  accounts/             Users, roles, scoping helpers, permission resolvers
  audit/                Generic AuditLog + signal-driven write path
  buildings/            Building model + BuildingManagerAssignment / StaffVisibility
  companies/            Provider company + CompanyUserMembership
  config/               Django settings, urls, security validator
  customers/            Customer org + per-user per-building access rows + policy
  extra_work/           Extra-work request workflow (separate state machine)
  notifications/        Email send + NotificationLog
  reports/              (stub — not wired)
  sla/                  (stub — not wired)
  tickets/              Ticket model + state machine + views + staff assignment
frontend/               React + TS + Vite SPA
  src/
    api/                Typed API client + types.ts (CUSTOMER_PERMISSION_KEYS lives here)
    auth/               JWT context + interceptors
    components/         Shared UI primitives
    hooks/              React hooks
    i18n/               nl/en translation bundles
    layout/             AppShell, sidebar, nav
    pages/              Route-level pages (admin/, customer-facing, ticket detail)
    utils/              Pure helpers
  tests/                Playwright e2e
docs/                   All architecture / audit / runbook docs
  architecture/         Sprint design docs (sprint-27-rbac-matrix.md is canonical RBAC ref)
  audit/                Codebase audits (sprint-16/17/19/21/22)
  backlog/              **Live product backlog + bug board (see §5)**
  frontend-design/      Design handoff
scripts/                Operational shell scripts + Playwright admin smoke
.claude/                **Claude Code agent definitions (see §4)**
.github/workflows/      CI (test.yml, playwright.yml, build-images.yml)
```

---

## 2. Hard rules (do not violate)

### Security floor — RBAC invariants H-1 through H-11
The 11 hard invariants in
[docs/architecture/sprint-27-rbac-matrix.md §3](docs/architecture/sprint-27-rbac-matrix.md#3-hard-invariants-must-be-enforced-and-tested)
are the security floor. Any change that contradicts one is a **P0 regression
even if all tests still pass** — extend the safety-net tests instead. Pay
particular attention to:
- H-1 / H-2: no cross-provider or cross-customer data bleed
- H-5: STAFF cannot approve/override customer-side decisions
- H-6 / H-7: only SUPER_ADMIN may grant `CUSTOMER_COMPANY_ADMIN` access_role
- H-10: every permission / role / scope change writes an `AuditLog` row
- H-11: permission override and workflow override are SEPARATE concepts

### Permission keys
- Provider keys live in the `osius.*` namespace (technical-debt naming —
  do NOT rename without a dedicated sprint). Resolver:
  `backend/accounts/permissions_v2.py`.
- Customer keys live in `customer.*`. Resolver:
  `backend/customers/permissions.py`. The typed list of valid keys is the
  frozenset `CUSTOMER_PERMISSION_KEYS`.
- The unified composer is `backend/accounts/permissions_effective.py`
  (`has_permission` / `effective_permissions`). New consumers should call it;
  existing call sites stay on the underlying resolvers (the parity tests
  prove they are byte-equivalent).
- **Never** offer `osius.*` keys in customer-side UI (frontend mirrors the
  typed `CUSTOMER_PERMISSION_KEYS` constant in [src/api/types.ts](frontend/src/api/types.ts)).

### State machines
- Ticket transitions: `backend/tickets/state_machine.py` —
  `ALLOWED_TRANSITIONS` is the authority. Don't add transitions outside it.
- Extra-work transitions: `backend/extra_work/state_machine.py` — has an
  explicit `is_override + override_reason` override surface.
- **Ticket workflow override (Sprint 27F-B1)** — ticket parity is shipped:
  `TicketStatusHistory` carries `is_override: bool` + `override_reason: str`
  columns; `tickets.state_machine.apply_transition` accepts
  `is_override` + `override_reason` kwargs; provider-driven customer-decision
  transitions (SUPER_ADMIN / COMPANY_ADMIN driving WAITING_CUSTOMER_APPROVAL
  → APPROVED|REJECTED) coerce `is_override=True` and REQUIRE
  `override_reason` (HTTP 400 with stable code `override_reason_required`).
  `TicketStatusChangeSerializer` accepts both fields on the wire.
- Every state mutation writes a `*StatusHistory` row inside the same
  `transaction.atomic()` block. Don't bypass.
- The override history row IS the audit trail for ticket / extra-work
  workflow overrides. Do NOT additionally register `TicketStatusHistory`
  or `ExtraWorkStatusHistory` for generic AuditLog tracking — that would
  double-write the same fact (matrix H-11).

### Audit
- All schema-tracked models are registered in `backend/audit/signals.py`.
  Adding a new tracked field on `User`, `Customer`, `Company`, `Building`,
  `StaffProfile`, `CustomerUserBuildingAccess`, `CustomerCompanyPolicy`,
  `BuildingStaffVisibility`, or `StaffAssignmentRequest` requires editing the
  `_*_TRACKED_FIELDS` tuple in `audit/signals.py` AND adding a test in
  `backend/audit/tests/`.

### Migrations
- Every model change needs a migration. The current migration count per app
  is preserved by sprint-tagged filenames (`0007_*.py` is the next free slot
  in `customers/migrations/`, etc.). Confirm with `python manage.py
  makemigrations --dry-run --check` before committing.
- Never edit an applied migration. Add a new one.
- Backfill data migrations are required when a new column has a non-default
  semantic value (e.g. Sprint 27C `0006_backfill_customer_company_policy.py`).

### Tests
- Backend: Django `APITestCase` with hermetic per-test data. Run from
  `backend/`: `python manage.py test`. ~385+ tests, ~5–8 min on CI.
- Frontend: Playwright e2e under `frontend/tests/e2e/`. No unit-test runner —
  type checking + Playwright is the contract. Smoke: `npm run test:e2e:smoke`.
- New features: **test-first** is the convention (see Sprint 27A–E test
  footprints in the RBAC matrix). Land the failing test in the same PR as
  the code that turns it green.
- Mocks of the database are forbidden in integration tests — use the real
  Postgres service (CI provides one). Mock the SMTP transport only.

### Frontend conventions
- TypeScript strict mode; no implicit `any`. The `tsc --noEmit -p
  tsconfig.app.json` check is Tier 1 — break it and you break the build.
- API types live in [frontend/src/api/types.ts](frontend/src/api/types.ts).
  Keep them in lockstep with backend serializers.
- i18n: every user-visible string goes through `t()`. Both `nl` and `en`
  bundles must carry every key (the project's primary locale is `nl`).
- The customer-decision override UX (two-press confirmation) is the only
  allowed pattern for workflow overrides. Mirror the Extra Work
  `ExtraWorkDetailPage` shape when adding ticket override (Sprint 27F).

### Naming / code style
- Backend: Django/PEP-8. Snake_case for fields, CamelCase for models. Permission
  keys: dot-namespaced (`osius.staff.manage`, `customer.ticket.approve_own`).
- Frontend: PascalCase components, camelCase functions, kebab-case CSS.
- File naming: app-scoped (`serializers_users.py`, `views_staff.py`) — do not
  collapse into a single mega-file.
- **No emojis in code, comments, commits, or PR titles** unless the user
  explicitly asks. UI copy (Dutch/English in the i18n bundles) is the only
  place emojis may appear, and only when designed in.

### Authoritative product sources
- The hard RBAC invariants (matrix doc §3, H-1 to H-11) are the
  **security floor** — non-negotiable.
- The product requirements under [docs/product/](docs/product/), starting
  with the 2026-05-15 stakeholder meeting
  ([docs/product/meeting-2026-05-15-system-requirements.md](docs/product/meeting-2026-05-15-system-requirements.md)),
  are **authoritative for system behaviour** at the same level as the RBAC
  matrix. When a backlog item or sprint design conflicts with a documented
  product requirement, the product requirement wins — open a backlog row
  to reconcile rather than implementing the conflicting version. New
  product documents written from a stakeholder meeting MUST be referenced
  from this section + linked from `CLAUDE.md` §9 (Reference docs).

---

## 2A. Product context (2026-05-15 stakeholder meeting)

Authoritative source: [docs/product/meeting-2026-05-15-system-requirements.md](docs/product/meeting-2026-05-15-system-requirements.md).
Headline rules every Claude session must respect:

1. **Contacts vs Users are distinct entities.**
   - **Contact** = a person listed only for communication (phone, email,
     role label). No login, no role enum, no permissions, no scope rows.
   - **User** = an authenticated principal with a `UserRole`, scope
     memberships, optional per-building access rows, and permission
     overrides. Every login is a User; every Contact is not.
   - New backend models or admin UIs must not conflate them. A Contact
     does not become a User by adding a password; it must be promoted
     explicitly (separate sprint).

2. **Modular per-location permissions.** A single User may have
   `CUSTOMER_USER` access on Building A and `CUSTOMER_LOCATION_MANAGER`
   on Building B inside the same Customer. Admins can grant specific
   rights (e.g. `customer.extra_work.approve_own`) via
   `CustomerUserBuildingAccess.permission_overrides` WITHOUT promoting
   the user's global role. This is the matrix's §2 sub-enum + Sprint 27C
   override editor.

3. **Frontend: view-first / closed-door design.** Detail pages load
   **read-only** by default. Editing happens only through explicit
   "Edit" / "Add" actions that open a modal or a separate page. The
   left sidebar is the **primary navigation anchor**:
   - "Customers" / "Relations" opens the list of authorized customers.
   - Selecting a customer **switches the sidebar into a customer-scoped
     submenu** (Buildings, Users, Permissions, Extra Work, Contacts,
     Settings) with a visible **Back** action.
   - Never dump 30 buildings or 16 permission rows onto one page. Use
     tabs, dropdowns, search, modals, or paginated tables.

4. **Extra Work shopping-cart flow.** Customers compose a request by
   adding multiple **service catalog items** to a cart, each with its
   own requested date. Submission produces one parent request with N
   line items.
   - If every line item resolves to a **pre-agreed price** (global
     default OR customer-specific contract price), the proposal phase
     is **skipped** and execution Tickets are created immediately.
   - If any line item is custom-priced or has no agreed price, the
     whole request goes to a manager/admin for a **proposal**.

5. **Pricing: global default + customer/contract overrides.** Same
   service can have different prices for different customers in the
   same building. Pricing unit types: hourly, per m², fixed price, per
   item. VAT default 21% but editable per line.

6. **Proposal builder.** Each proposal line carries `quantity`,
   `unit_price`, `vat_pct`, `customer_explanation` (visible to the
   customer), and `internal_note` (provider-side only — must never be
   serialized to a customer-facing endpoint). Proposals emit timeline
   events. PDF export is a planned deliverable.

7. **Approval + admin override.** Customer approves/rejects the
   proposal. A provider-side admin can override the customer decision
   ONLY with a mandatory reason. The override is recorded on the status
   history row (`is_override=true` + `override_reason`) AND on the
   timeline / audit log with actor + timestamp. (Already shipped for
   tickets in Sprint 27F-B1; the proposal surface must follow the same
   shape.)

8. **Accepted proposal → tickets.** Approval of a proposal automatically
   spawns operational Tickets — one per approved line item — anchored
   to a parent `ExtraWorkRequest` with `ExtraWorkRequestItem` rows.
   Rejected lines do not spawn tickets.

9. **Future-parked architecture.** Subscription / abonement billing and
   bank-transaction matching are explicitly out of scope until
   scheduled. Models and APIs should leave room (no premature
   columns), but **do not** ship feature code for them in 27F/G.

---

## 3. Sprint cadence

Each sprint has a doc under `docs/architecture/sprint-<n><letter>-<topic>.md`.
The naming convention is:
- `<n>` = numeric sprint (current: 27)
- `<letter>` = sub-sprint (`A` test-first safety net, `B` backend, `C/D`
  resolver, `E` frontend UI, `F/G` follow-on / e2e)

When closing a sprint:
1. Update the **matrix doc** (currently
   [docs/architecture/sprint-27-rbac-matrix.md](docs/architecture/sprint-27-rbac-matrix.md))
   — strike through closed gaps with `~~text~~ **CLOSED by Sprint <n><letter>**`.
2. Add a test footprint section (`## N. Test footprint (Sprint <n><letter>
   delta)`).
3. Update [docs/RELEASE_STATUS.md](docs/RELEASE_STATUS.md) if user-visible.
4. Commit message: `Sprint <n><letter>: <imperative one-liner>` (match
   recent log: `Sprint 27E: add customer permission management UI`).

---

## 4. Multi-agent setup

Claude Code runs three named sub-agents in this repo. They live under
[.claude/agents/](./.claude/agents/) and are invoked via the `Agent` tool with
`subagent_type:` matching the filename:

| Agent | Purpose | Tools |
|---|---|---|
| `project-manager` | Reads the live backlog, prioritises, dispatches work to the engineer agents, validates outcomes. **Always called first** when a fresh task arrives. | Read-mostly + Write for backlog files only |
| `backend-engineer` | Owns `backend/**`, migrations, audit, RBAC, state machines, Celery. | Full |
| `frontend-engineer` | Owns `frontend/**`, Playwright e2e, i18n bundles. | Full |

**Routing rule:** if a task touches both halves (e.g. Sprint 27F has a
backend `TicketStatusHistory.is_override` column AND a frontend override
modal), the PM agent splits it into two work items and dispatches in
parallel via two Agent calls.

**Coordination contract:** the PM agent is the only one who edits files
under `docs/backlog/`. Engineer agents read the backlog but never rewrite
it — they report status back, and the PM updates the board.

---

## 5. Backlog and bug board

The live work tracker lives in
[docs/backlog/](docs/backlog/):

| File | What it holds |
|---|---|
| `PRODUCT_BACKLOG.md` | Prioritised feature work. Sprint-tagged items + standing GAP_ANALYSIS_2026-05 P0/P1/P2 items. |
| `BUGS.md` | Open defects with reproduction notes. Each row references the failing test (or NEEDS-TEST). |
| `DONE.md` | Append-only ledger of closed items + the commit SHA. |

The PM agent reads all three on every turn. Engineer agents read the
specific item they're dispatched. Closing an item: PM moves the row from
`PRODUCT_BACKLOG.md` / `BUGS.md` to `DONE.md` with `closed-by: <commit-sha>`
and the matrix-doc update happens in the SAME commit.

---

## 6. Local dev quickstart

```bash
# Start the stack (Postgres, Redis, MailHog, backend, frontend dev server)
docker compose up -d

# Backend tests (hermetic — no docker compose needed once Postgres is up)
cd backend && python manage.py test

# Frontend type check + lint
cd frontend && npm run typecheck && npm run lint

# Playwright smoke
cd frontend && npm run test:e2e:smoke

# Full local validation gate (the script CI uses)
./scripts/final_validation.sh
```

Inspect captured email at <http://localhost:8025> (MailHog).

---

## 7. Operational gotchas

These are hard-won lessons. Re-reading
[docs/CLAUDE_CODE_OPERATIONAL_NOTES.md](docs/CLAUDE_CODE_OPERATIONAL_NOTES.md)
before touching shell scripts or the Playwright admin smoke is mandatory.
Highlights:
- The Edit tool drops the `+x` bit on `.sh` files — re-`chmod +x` after every
  edit and verify with `ls -l`.
- `command | tee file | head -N` truncates the file via SIGPIPE. Always
  write to file first, then read separately.
- Playwright container artifacts are root-owned on the host. Clean via a
  throwaway container, not host `rm`.
- Multi-line content through the WSL bridge needs a tempfile, not a heredoc.

---

## 8. Things to NOT do

- Do not rename `osius.*` permission keys (technical-debt naming; documented
  in the RBAC matrix; rename is its own future sprint).
- Do not collapse `serializers_users.py`, `views_staff.py`, etc. into single
  app-wide files.
- Do not introduce a new test-runner. Django `manage.py test` for backend,
  Playwright for frontend, full stop.
- Do not bypass audit signals — adding a new column writes the migration AND
  registers the column in `_*_TRACKED_FIELDS`.
- Do not add backwards-compatibility shims for the deprecated visibility
  fields on `Customer` — they're staying until the runtime read switch is
  scheduled (deferred from G-B5).
- Do not write a new mega-doc when a sprint design fits in the matrix.
- Do not commit secrets. `.env` is gitignored; `.env.example` /
  `.env.production.example` are the contracts.

---

## 9. Reference docs

- [README.md](README.md) — top-level project intro
- [docs/architecture/sprint-27-rbac-matrix.md](docs/architecture/sprint-27-rbac-matrix.md) — canonical RBAC + role model
- [docs/product/meeting-2026-05-15-system-requirements.md](docs/product/meeting-2026-05-15-system-requirements.md) — authoritative product behaviour (Contacts vs Users, modular permissions, view-first UI, Extra Work cart, pricing model, proposal builder, override audit, future hooks)
- [docs/GAP_ANALYSIS_2026-05.md](docs/GAP_ANALYSIS_2026-05.md) — standing P0/P1/P2 list (load-bearing through Sprint 27)
- [docs/RELEASE_STATUS.md](docs/RELEASE_STATUS.md) — what's shipped
- [docs/CLAUDE_CODE_OPERATIONAL_NOTES.md](docs/CLAUDE_CODE_OPERATIONAL_NOTES.md) — WSL / shell / container gotchas
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — production deploy runbook
- [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) — last security review
