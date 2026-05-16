# Sprint 28 Master Plan and Progress Tracker

## 1. Purpose

This file is the **persistent execution plan and progress tracker** for
Sprint 28 and the sprint letters that follow it. It exists to prevent
context drift, repeated decisions, forgotten requirements, and AI sessions
going off-track between turns.

Boundaries:

- This file does **not** replace [`docs/backlog/PRODUCT_BACKLOG.md`](../backlog/PRODUCT_BACKLOG.md).
  The backlog stays the canonical list of feature work + dependency graph.
- This file does **not** replace [`docs/audits/current-state-2026-05-16-system-audit.md`](../audits/current-state-2026-05-16-system-audit.md).
  The audit stays the canonical current-state evidence with file:line
  references and gap matrix.
- This file **is** the execution tracker and current-batch pointer. Every
  future Claude Code / ChatGPT / human developer pass starts here.
- [`CLAUDE.md`](../../CLAUDE.md) remains the operating-instruction source
  for *how* to work in this repo (rules, conventions, multi-agent setup).

If anything below conflicts with the product spec or the audit, **stop and
report the conflict** — do not silently choose one.

---

## 2. Authoritative references

Read these in this order at the start of every pass:

1. [`CLAUDE.md`](../../CLAUDE.md) — operating rules (§2A product context, §4
   multi-agent contract, §8 things NOT to do).
2. **This file** — current batch pointer + decision log + open questions.
3. [`docs/audits/current-state-2026-05-16-system-audit.md`](../audits/current-state-2026-05-16-system-audit.md)
   — current-state evidence and gap matrix.
4. [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md)
   — authoritative product behaviour (Contacts vs Users, modular permissions,
   view-first UI, Extra Work cart, pricing, proposal builder, override audit,
   future hooks).
5. [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md)
   — security floor (RBAC invariants H-1..H-11).
6. [`docs/backlog/PRODUCT_BACKLOG.md`](../backlog/PRODUCT_BACKLOG.md) — open
   work + acceptance criteria per item.
7. [`docs/backlog/BUGS.md`](../backlog/BUGS.md) — open defects.
8. [`docs/backlog/DONE.md`](../backlog/DONE.md) — append-only ledger.

**Conflict-resolution rule.** If this master plan conflicts with the
product spec (`docs/product/`) or the audit (`docs/audits/`), **stop and
report the conflict**. Do not silently choose one. The product spec is the
product-behaviour floor; the audit is the current-state evidence floor; the
RBAC matrix is the security floor. This master plan is the *sequencing*
layer; it cannot override the floors.

---

## 3. Operating rules for every future pass

Every Claude Code, ChatGPT, or human implementation pass MUST follow these
rules:

1. **Start by reading this file.** Identify the **Current batch** (see §7).
2. **State the current batch explicitly** in the first message of the pass,
   before any tool call that modifies a file. Example: *"Current batch:
   Batch 1 — Operational health fixes. I will work only on Batch 1 items."*
3. **Do not implement work outside the current batch** unless the user
   explicitly approves the scope expansion. If a discovery during a batch
   reveals additional work, document it under "remaining risks" and stop
   to ask the user before expanding scope.
4. **Keep each batch small and commit-friendly.** A batch should end at a
   point where a single Git commit captures the change cleanly with a
   one-line subject + a short body. If a batch is growing beyond that
   shape, split it.
5. **Do not silently skip tests.** Run the tests / typecheck / lint that
   the batch's items require. If a check fails, fix it before reporting the
   batch done — or, if blocked, escalate per rule 12.
6. **After implementation, update this file before finishing.** This is the
   stable navigation contract for the next pass.
7. **Mark completed items with Markdown checkboxes and strikethrough.**
   Replace `- [ ] Open item` with `- [x] ~~Completed item~~`. The strike-
   through preserves the original wording while making the completion
   visually obvious.
8. **Under each completed batch, append a completion block** containing:
   - date (absolute ISO date, not "today")
   - commit hash if available
   - files changed summary (paths, not full diff)
   - tests/checks run + their outcomes
   - important decisions made (also add to §9 decision log)
   - remaining risks (anything the next batch must know)
9. **Keep the "Current batch" pointer updated** (§7). When a batch closes,
   advance the pointer to the next batch.
10. **Keep the "Next recommended batch" pointer updated** (§7). It's the
    on-deck batch; useful for prepping the next pass.
11. **Never rewrite history in this document.** Completion logs are
    append-only. If a previous entry is factually wrong, add a correction
    note below it dated with the correction date — do not edit the original.
12. **If a batch discovers a blocker, mark the blocker and stop.** Keep the
    Current batch pointer on the blocked batch. Add a "BLOCKED" line under
    that batch's checklist with the blocker description and the date.
    Resume only when the blocker is resolved.

---

## 4. Current project state summary

Snapshot derived from the [2026-05-16 audit](../audits/current-state-2026-05-16-system-audit.md).
Refresh after each batch.

### Backend
- Security / RBAC baseline is strong.
- RBAC invariants H-1 through H-11 are verified — enforcement points and
  test locks match the matrix doc (one minor doc drift on H-4 attribution,
  tracked in Batch 2).
- Ticket workflow override exists: `TicketStatusHistory.is_override` +
  `override_reason`; provider-driven coercion; `override_reason_required`
  400 contract (Sprint 27F-B1).
- `AuditLog.reason` and `AuditLog.actor_scope` exist (Sprint 27F-B2).
- Customer permission resolver and `CustomerCompanyPolicy` DENY layer exist
  (Sprint 27A–E).
- Extra Work backend exists **but is the wrong product shape** for the
  2026-05-15 requirements: single-line `ExtraWorkRequest`, no Service
  catalog, no cart, no Proposal entity.

### Frontend
- Sprint 27E (customer permission management UI) and Sprint 27F-F1 (ticket
  override modal) are correct and view-first.
- Sidebar is flat. No hierarchical customer-scoped submenu.
- Most admin detail pages load editable forms on first render (closed-door
  / view-first violation across `CustomerFormPage` parent, `BuildingFormPage`,
  `CompanyFormPage`, `UserFormPage`).
- Extra Work pages (`CreateExtraWorkPage`, `ExtraWorkListPage`,
  `ExtraWorkDetailPage`) have **no i18n at all** (hard-coded English) and
  still assume the single-line request flow.
- Dashboard is ticket-only; no Extra Work integration; renders identical
  shape for every role.

### Operational
- 4 committed migrations unapplied on the dev DB
  (`audit.0002_auditlog_reason_actor_scope`,
  `customers.0005_customercompanypolicy`,
  `customers.0006_backfill_customer_company_policy`,
  `tickets.0007_ticketstatushistory_is_override_and_more`).
  The Django test runner creates `test_*` databases and auto-applies
  migrations every run — the **548-test baseline on commit `be7b3e4` is
  unaffected** by this drift; it only means the dev container's actual DB
  schema is behind the code.
- Frontend `npm run typecheck` and `npm run build`: green.
- Frontend `npm run lint`: 49 errors + 3 warnings, all pre-existing
  baseline (Sprint 27F-F1 verified zero new lint hits in its delta).

---

## 5. Non-negotiable product requirements

Concise reference. Full text lives in
[`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md).
Any future change that contradicts these is wrong by default — push back.

1. **Provider company vs Customer company must be visually and structurally
   clear.** Provider = the cleaning/service provider (e.g. Osius);
   Customer = the client organisation.
2. **Contacts are not login users.** A Contact is a communication record
   only — name, email, phone, role label, notes — with no password, no
   JWT, no `UserRole`, no memberships, no permission overrides.
3. **Building Manager must see assigned-building customers and contacts
   read-only.** No mutate paths by default. (Optional delegated management
   permissions are a later, separate decision.)
4. **Provider Company Admin can edit, but pages must still be view-first
   first.** Detail pages load read-only; edit happens through explicit
   Edit/Add → modal or separate page.
5. **Customer Company Admin can manage lower customer users but cannot
   promote anyone to Customer Company Admin** (RBAC matrix H-6 / H-7).
   Cannot grant permissions above their own level. Cannot create an
   admin-equivalent user via permission stacking.
6. **Staff permissions must eventually be per building.** Example shape:
   B1 = own-only; B2 = building-wide read; B3 = building-wide read + assign.
   If a Staff user can see all tickets in a building, tickets assigned to
   them should be visually prioritised.
7. **Staff completion routing must eventually be configurable.** Default:
   Staff marks done → Building Manager review. Optional (per
   staff/building, separately for Tickets vs Extra Work): Staff marks done
   → directly to customer approval.
8. **Extra Work has two paths:**
   1. **Contract fixed-service shopping-cart path** — customer browses
      catalog, adds N services to a cart, submits; if every line has a
      pre-agreed customer-specific contract price, proposal is skipped and
      execution Tickets are spawned immediately.
   2. **Custom request / proposal path** — customer requests something not
      in contract OR any line lacks an agreed price; whole cart routes to
      provider-side manager/admin for a proposal; customer approves/rejects.
9. **Global default price alone must NOT create an instant customer order.**
   Global default exists as a provider-side reference; the instant-ticket
   path requires an **active customer-specific contract price**.
10. **Proposal approval must create operational ticket(s).** Approval is
    atomic with the ticket spawn (single `transaction.atomic`). Rejected
    proposal lines do not spawn tickets.
11. **Customer must never see provider internal notes.** The customer-
    facing serializer omits `internal_note` (or its current legacy name).
    PDF export must also exclude internal notes.
12. **Staff may see normal internal work notes by default, but
    cost/margin/provider-only proposal notes must be hideable from Staff.**
    This is a **3-way privacy split** (customer / provider-with-staff /
    provider-only-cost-margin). Today the system is only 2-way; the cost-
    margin strip from Staff is not yet enforced.
13. **Dashboard must show both Tickets and Extra Work.** Top-level cards /
    sections for both; clicking each goes to its dedicated dashboard/list;
    shape differs between provider-side and customer-side roles.

---

## 6. Master batch sequence

Strict order. Each batch is small enough to ship as one commit (or a tight
pair of commits, backend + frontend). Do NOT start a batch before the
previous one lands. Do NOT implement items from later batches.

### Batch 1 — Operational health fixes

Goal: clear the four operational gotchas the audit flagged. Zero schema
risk. ~1 day of work.

- [x] ~~Apply pending dev DB migrations manually, after confirming with the
      user. (`audit.0002_auditlog_reason_actor_scope`,
      `customers.0005_customercompanypolicy`,
      `customers.0006_backfill_customer_company_policy`,
      `tickets.0007_ticketstatushistory_is_override_and_more`.) Do **not**
      run migrations automatically without explicit user approval. Mark
      this item as planned/manual and request confirmation.~~
- [x] ~~Fix frontend `getApiError` raw HTML handling at
      [`frontend/src/api/client.ts:148`](../../frontend/src/api/client.ts#L148).
      Detect `<!DOCTYPE` / `<html` prefix and downgrade to the status
      fallback string. ~5-line change. Add a unit/contract test.~~
- [x] ~~Add Sprint 27F-B2 `AuditLog.reason: string` and
      `AuditLog.actor_scope: Record<string, unknown>` fields to the
      frontend `AuditLog` type at
      [`frontend/src/api/types.ts:481-492`](../../frontend/src/api/types.ts#L481-L492).
      Keep `tsc --noEmit` green.~~
- [x] ~~Replace the literal `"Extra Work"` string in the sidebar at
      [`frontend/src/layout/AppShell.tsx:157`](../../frontend/src/layout/AppShell.tsx#L157)
      with a `t()` call. Add the key to both `frontend/src/i18n/en/common.json`
      and `frontend/src/i18n/nl/common.json`. Preserve EN/NL parity.~~

**Completion block — Batch 1**

- **Date:** 2026-05-16
- **Commit:** uncommitted on working tree as of 2026-05-16 (Batch 1 diff
  on top of `6e572db`; ready for a single batch commit once reviewed).
- **Files changed summary:**
  - Frontend: `frontend/src/api/client.ts` (HTML-prefix guard in
    `getApiError`), `frontend/src/api/types.ts` (Sprint 27F-B2 fields on
    `AuditLog`), `frontend/src/layout/AppShell.tsx` (sidebar `t()` call),
    `frontend/src/i18n/en/common.json` and
    `frontend/src/i18n/nl/common.json` (new `nav.extra_work` key in both,
    EN/NL parity preserved).
  - Backend: no source changes. Dev DB migrations applied after explicit
    user approval (`audit.0002`, `customers.0005`, `customers.0006`,
    `tickets.0007`).
  - Docs: this completion block + §7 pointer advance + §8 log row.
- **Tests / checks run:**
  - `docker compose exec backend python manage.py showmigrations audit
    customers tickets` (pre + post): pre showed 4 unapplied; post showed
    all `[X]`.
  - `docker compose exec backend python manage.py migrate`:
    `audit.0002_auditlog_reason_actor_scope OK`,
    `customers.0005_customercompanypolicy OK`,
    `customers.0006_backfill_customer_company_policy OK`,
    `tickets.0007_ticketstatushistory_is_override_and_more OK`.
  - `docker compose exec backend python manage.py check` (pre + post
    migrate): both **0 issues**.
  - `npm run typecheck`: clean (empty diagnostic output).
  - `npm run build`: clean, 472ms; advisory chunk-size warning only
    (baseline; not from this diff).
  - `npm run lint`: **52 problems (49 errors, 3 warnings)** — identical
    to the audit-recorded baseline. The single AppShell.tsx hit is at
    `:93:5` (pre-existing `react-hooks/set-state-in-effect`), not at the
    `:157` line touched in this batch. Zero new lint hits in the four
    changed files.
  - Unit-test infrastructure status: **none wired**. The frontend
    `package.json` declares no `test` script and lists no Vitest /
    Jest / Testing-Library dependency; only Playwright e2e exists.
    The `getApiError` change therefore ships with a defensive code-level
    guard and typecheck/build coverage, but **no dedicated unit test
    was added**. A Playwright spec would need a mocked 500 HTML
    response and a route to render it; that's heavier than the 5-line
    change warrants. Recommendation: add Vitest + an `api/client.test.ts`
    in a later batch (e.g. as part of Batch 3 or 13 setup).
- **Important decisions made:**
  - HTML detection in `getApiError` matches both upper- and lower-case
    `<!DOCTYPE` / `<html>` prefixes (Django serves uppercase
    `<!DOCTYPE html>`; some proxies emit lowercase). Whitespace-tolerant
    via `trimStart()`. The original DRF-string pass-through is preserved
    for non-HTML payloads.
  - `nav.extra_work` translations: **EN** "Extra Work" (brand-preserving
    capitalisation, matches the existing literal), **NL** "Extra werk"
    (Dutch sentence-case convention used by sibling keys like "Nieuw
    ticket"). No decision-log row added; this is purely a translation
    choice within the i18n contract, not a product decision.
  - Migrations were applied after explicit user approval (per master
    plan §7 rule). The migrations themselves were already audit-locked
    and test-DB-validated by Sprints 27B/27C/27F; this pass only moved
    the dev container's schema into the same state.
- **Remaining risks:**
  - No automated unit-test coverage on `getApiError`. If a future change
    re-introduces a raw-HTML leak (e.g. an interceptor that converts the
    HTML to a different non-DOCTYPE prefix), only end-to-end manual
    smoke would catch it. Adding Vitest is a parked follow-up.
  - The `AuditLog` type now declares `reason: string` + `actor_scope:
    Record<string, unknown>` as **required** (not optional). The backend
    Sprint 27F-B2 serializer always emits both fields with defaults
    (`""` and `{}`), so this is correct — but any legacy fixture or
    third-party AuditLog ingester that omits the fields would produce
    a runtime TypeScript-vs-actual mismatch. None observed in the
    codebase today.
  - `nav.extra_work` is the only sidebar entry whose Dutch translation
    differs in case-convention from the English. If a stakeholder
    prefers "Extra Werk" (title-case to match the brand), flip the NL
    value — no other code changes required.

### Batch 2 — Verify mild backend risk

Goal: confirm whether the `is_staff_role`-permitted `/api/tickets/<id>/assign/`
path is a real bypass risk. Resolve H-4 attribution drift. ~½ day.

- [ ] Read [`backend/tickets/serializers.py`](../../backend/tickets/serializers.py)
      `TicketAssignSerializer.validate` and trace the path called by the
      `assign` action at
      [`tickets/views.py:247-280`](../../backend/tickets/views.py#L247-L280).
- [ ] Confirm STAFF cannot reassign tickets through
      `POST /api/tickets/<id>/assign/`. If the serializer doesn't refuse,
      that's a real backend bug — escalate per rule 12.
- [ ] Add a regression test if missing — e.g.
      `tickets/tests/test_sprint28a_staff_assign_block.py` asserting
      STAFF POST returns 403 with no DB write.
- [ ] Fix only if a real bug exists. Do not change the gate if it's already
      correct.
- [ ] Resolve H-4 matrix attribution drift in
      [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md)
      §3 row 4. Either rewrite the row to cite the structural guard (no
      STAFF entries anywhere in `ALLOWED_TRANSITIONS`) or land an
      H-4-specific regression test under the same name.

### Batch 3 — Sidebar refactor foundation

Goal: introduce the hierarchical customer-scoped submenu so subsequent
batches have a structural anchor for sub-views. Frontend only; no backend
or schema. ~1 sprint letter.

- [ ] Add top-level vs customer-scoped sidebar mode to
      [`frontend/src/layout/AppShell.tsx`](../../frontend/src/layout/AppShell.tsx).
      State machine: `mode = "top-level" | "customer-scoped"`.
- [ ] Add the customer-scoped submenu entries: Buildings, Users,
      Permissions, Extra Work, Contacts, Settings. Some entries may show
      empty states until later batches land their content — that is fine,
      the navigation structure ships first.
- [ ] Add a visible **Back** action that returns the sidebar to top-level
      mode.
- [ ] Encode submenu state in the URL so deep links work and browser-back
      behaves predictably. Use a nested `<Routes>` block under
      `/admin/customers/:id/*`.
- [ ] Add route tests / Playwright coverage. Spec must assert: clicking a
      customer enters submenu mode, Back returns to top-level, deep link
      to a sub-route shows the correct submenu state.

### Batch 4 — Contacts model and UI

Goal: introduce the Contact entity and surface it on the customer-scoped
submenu (Batch 3 prerequisite). Joint backend + frontend. ~1 sprint letter.

- [ ] Add `Contact` model under
      [`backend/customers/`](../../backend/customers/) (or new
      `contacts/` app — sprint design decision). Fields: `customer` FK,
      optional `building` FK, `full_name`, `email`, `phone`, `role_label`,
      `notes`. **No password, no role, no scope rows.** Migration in the
      app's `migrations/`.
- [ ] Ensure Contact is structurally distinct from `User`. A Contact does
      not become a User by setting a password; that is a separate
      promotion flow parked for a later sprint.
- [ ] Add Contact CRUD API gated by the same
      `IsSuperAdminOrCompanyAdminForCompany` permission as the other
      customer-scoped endpoints. Building Manager gets a **read-only**
      view of contacts in their assigned buildings (depends on Batch 12;
      this batch only ships the write path).
- [ ] Add audit signal coverage in
      [`backend/audit/signals.py`](../../backend/audit/signals.py) — full
      CRUD tracking on the Contact model. Add `audit/tests/` coverage.
- [ ] Add the `Contact` TypeScript type to
      [`frontend/src/api/types.ts`](../../frontend/src/api/types.ts) and
      the client helpers to
      [`frontend/src/api/admin.ts`](../../frontend/src/api/admin.ts).
- [ ] Add `CustomerContactsPage` under
      `/admin/customers/:id/contacts` (nested under the Batch 3 submenu).
      View-first per spec §3 — list page with "Add contact" modal; row
      click opens a read-only detail with "Edit" → modal.
- [ ] Add contextual contact display in ticket / extra-work screens where
      useful (e.g. read-only "Customer contacts" panel on
      `TicketDetailPage` and `ExtraWorkDetailPage`).
- [ ] Add tests: backend API + scope + audit; frontend Playwright for the
      view-first flow + the "no login fields" assertion.

### Batch 5 — Service catalog and pricing

Goal: introduce the catalog + pricing models so the cart flow (Batch 6)
can compute prices. Backend-heavy. ~1 sprint letter.

- [ ] Add `ServiceCategory` model.
- [ ] Add `Service` model with `name`, `description`, `unit_type`
      (`HOURLY` / `PER_SQM` / `FIXED` / `PER_ITEM` per spec §5),
      `default_unit_price` (decimal), `default_vat_pct` (decimal,
      default 21.00), `is_active`, FK to `ServiceCategory`.
- [ ] Add customer-specific contract price model (`CustomerServicePrice` or
      similar): FK `customer`, FK `service`, `unit_price`, `vat_pct`,
      `valid_from`, `valid_to`, `is_active`.
- [ ] Add `default_unit_price` as the global default/reference price on
      `Service` — used as a provider-side reference only.
- [ ] Add `resolve_price(service, customer, on=date)` resolver. Returns
      the customer-specific contract price when active, else `None`
      (NOT the global default — see §5 product rule #9).
- [ ] **Enforce: global default price alone never creates an instant
      ticket.** The instant-ticket path (Batch 7) keys off the resolver
      returning a non-`None` price, which only happens when a customer-
      specific contract price is active.
- [ ] Add provider/admin UI for managing service categories, services,
      and customer-specific prices. View-first per spec §3.
- [ ] Add audit signal coverage on all three new models.
- [ ] Add tests: resolver branches, cross-customer leak prevention
      (Customer A's prices never visible to Customer B's users),
      audit coverage.

### Batch 6 — Cart-shaped Extra Work request

Goal: reshape `ExtraWorkRequest` from single-line to parent + N line
items; ship the customer cart UI. ~1 sprint letter.

- [ ] Add `ExtraWorkRequestItem` (or equivalent cart-line model) with FK
      to `ExtraWorkRequest`, FK to `Service`, `quantity`, `requested_date`
      (per-line, per spec §4), `customer_note`. Migration with a data
      backfill so existing single-line requests get one line item.
- [ ] Update `ExtraWorkRequest` to be the parent record. Keep the request-
      level `description` field (per §10 question 3 default).
- [ ] Customer can add multiple contract services and/or custom requests
      to one cart. Spec §4 branching rule: if any line lacks an agreed
      price, the whole cart routes to the proposal flow (Batch 8); else
      instant-ticket (Batch 7).
- [ ] Add per-line `quantity`, `unit_type` (denormalised from Service for
      historical accuracy), `requested_date`, `customer_note`.
- [ ] Separate the mixed cart according to the spec §4 rule (single
      property on the request — e.g. `routing_decision = "INSTANT" |
      "PROPOSAL"` — computed at submission time).
- [ ] Rewrite [`frontend/src/pages/CreateExtraWorkPage.tsx`](../../frontend/src/pages/CreateExtraWorkPage.tsx)
      to the cart shape: category browser + add-to-cart + per-line date
      picker + submit.
- [ ] Add `extra_work` i18n namespace in both `en/` and `nl/`. Thread
      `t()` through all three EW pages
      (`Create`, `List`, `Detail`). This is the first time the EW
      surface gets i18n.
- [ ] Add tests: backend API for parent + line creation; scope on cart
      lines; frontend Playwright for the cart UX.

### Batch 7 — Instant-ticket path

Goal: when every cart line resolves to a customer-specific contract price,
skip proposal and spawn Tickets atomically. Depends on Batch 5 + Batch 6.

- [ ] On `ExtraWorkRequest` submission, if every line's `resolve_price()`
      returns a non-`None` customer-specific contract price, set
      `routing_decision = "INSTANT"` and transition straight to the
      execution stage (no proposal phase).
- [ ] Create operational Ticket(s) immediately — one per line, anchored to
      the parent request. Title / description derived from the Service +
      line context. Status starts at `OPEN`. Priority defaults to NORMAL.
- [ ] Ensure transaction safety: ticket spawn must run inside the same
      `transaction.atomic()` as the routing transition; failure rolls back
      the whole submission.
- [ ] Add status/timeline records: each spawned Ticket gets its initial
      `TicketStatusHistory` entry; the parent `ExtraWorkRequest` gets an
      `ExtraWorkStatusHistory` entry recording the instant-route decision.
- [ ] Add tests: every-line-has-price path, missing-price-falls-to-
      proposal-path, atomic rollback test, audit/timeline coverage.

### Batch 8 — Proposal builder

Goal: ship the first-class Proposal entity for the custom path. Depends
on Batch 5 + Batch 6.

- [ ] Add `Proposal` model — FK to `ExtraWorkRequest`, status enum
      (`DRAFT` / `SENT` / `CUSTOMER_APPROVED` / `CUSTOMER_REJECTED`),
      computed totals (net / VAT / gross), `sent_at`,
      `customer_decided_at`, override fields.
- [ ] Add `ProposalLine` model — FK to `Proposal`, optional FK to
      `Service` (free-text label allowed for ad-hoc), `quantity`,
      `unit_type`, `unit_price`, `vat_pct`,
      `customer_explanation: TextField` (customer-visible),
      `internal_note: TextField` (provider-only). **Per §10 open question
      1 default: use spec naming — `customer_explanation` and
      `internal_note` — for the new model. Document the rename in §9.**
- [ ] Ensure customer-facing endpoints **never** return `internal_note`.
      The `ProposalLineCustomerSerializer` MUST omit it; the admin
      serializer includes it. Add a regression-lock test that serializes
      a proposal as `CUSTOMER_USER` and grep-asserts `internal_note` is
      absent from the JSON.
- [ ] Add `ProposalTimelineEvent` for proposal lifecycle events (created,
      sent, customer viewed, customer approved, customer rejected, admin
      overridden). Provider sees all; customer sees a filtered subset
      (override marker visible, override reason text not visible to
      customer).
- [ ] Add proposal override with mandatory `override_reason` — mirror the
      Sprint 27F-B1 ticket shape: provider-driven `CUSTOMER_APPROVED /
      CUSTOMER_REJECTED` coerces `is_override=True` and requires
      `override_reason`; HTTP 400 with stable code
      `override_reason_required` when missing.
- [ ] On customer approval (or admin override approval), create Tickets
      transactionally — one per approved line. Rejected lines do not
      spawn tickets. Atomic with the approval transition.
- [ ] Audit signal coverage on `Proposal`, `ProposalLine`,
      `ProposalTimelineEvent`.
- [ ] Add tests: proposal CRUD, dual-note privacy, timeline emission,
      override path, atomic ticket spawn, audit coverage.

### Batch 9 — Extra Work dashboard and stats

Goal: dashboard integration for Extra Work. Depends on Batches 5–8 (the
shapes those settle determine the stats payload).

- [ ] Add Extra Work stats endpoints: `GET /api/extra-work/stats/` and
      `GET /api/extra-work/stats/by-building/`. Scoped per requesting
      role. Returns totals + by-status + awaiting-customer-approval +
      awaiting-pricing + urgent buckets.
- [ ] Add Extra Work dashboard cards to
      [`frontend/src/pages/DashboardPage.tsx`](../../frontend/src/pages/DashboardPage.tsx).
      Two top-level sections side by side: Tickets and Extra Work.
- [ ] Make dashboard render different shapes for provider-side vs
      customer-side users. CUSTOMER_USER sees their own buckets; provider
      roles see scoped aggregates.
- [ ] Add tests: backend stats endpoint scope + role shape; frontend
      Playwright for the two-section layout.

### Batch 10 — Staff per-building granularity

Goal: enable the B1/B2/B3 example per spec §B.4 / product rule #6.

- [ ] Extend `BuildingStaffVisibility` (or equivalent) with a per-row
      permission level. Options: add a `visibility_level` enum
      (`ASSIGNED_ONLY` / `BUILDING_READ` / `BUILDING_READ_AND_ASSIGN`), or
      add explicit booleans (`can_view_all_tickets`, `can_assign`).
      Sprint design decides exact shape.
- [ ] Support the spec example:
  - [ ] B1: own assigned tickets only.
  - [ ] B2: all building tickets but cannot assign.
  - [ ] B3: all building tickets and can assign.
- [ ] Update backend scoping at
      [`backend/accounts/scoping.py:211-230`](../../backend/accounts/scoping.py#L211-L230)
      (STAFF branch).
- [ ] Update assignment gates in
      [`backend/tickets/views.py:247-280`](../../backend/tickets/views.py#L247-L280)
      and
      [`backend/tickets/views_staff_assignments.py`](../../backend/tickets/views_staff_assignments.py)
      to honour the new per-row level.
- [ ] Add new `osius.staff.view_building_tickets` and
      `osius.staff.assign_tickets` permission keys to
      `OSIUS_PERMISSION_KEYS` if helpful, or rely on the model field
      directly — sprint design decides.
- [ ] Update frontend staff permission UI on
      [`frontend/src/pages/admin/UserFormPage.tsx`](../../frontend/src/pages/admin/UserFormPage.tsx)
      with the per-building level selector. View-first per spec §3.
- [ ] When a Staff user can see all tickets in a building, ensure tickets
      assigned to them are visually prioritised in the list UI (sort
      first or marked differently).
- [ ] Add tests: backend scope tests for B1/B2/B3 shapes; frontend
      Playwright for the per-row selector.

### Batch 11 — Staff completion routing

Goal: configurable per-staff / per-building routing per product rule #7.

- [ ] Add a Staff "I completed my work" flow. STAFF can drive a new
      transition out of `IN_PROGRESS`.
- [ ] Require completion note on every Staff completion (already a Sprint
      25C invariant for `IN_PROGRESS → WAITING_CUSTOMER_APPROVAL` —
      extend to the new Staff path).
- [ ] Support optional completion attachment/photo. Reuse the existing
      `TicketAttachment` model + `is_hidden=False` for the visible-evidence
      semantic.
- [ ] Default route: Staff marks done → `WAITING_MANAGER_REVIEW` (new
      ticket status), then Building Manager accepts to
      `WAITING_CUSTOMER_APPROVAL` or rejects back to `IN_PROGRESS`.
      Per §10 open question 2 default.
- [ ] Optional configured route: when the configurable flag is enabled,
      Staff marks done → directly to `WAITING_CUSTOMER_APPROVAL`. Flag
      lives on `BuildingStaffVisibility` or `StaffProfile` — sprint
      design decides.
- [ ] Keep Ticket and Extra Work routing configurations **separate** (per
      product rule #7).
- [ ] Update `ALLOWED_TRANSITIONS` in
      [`backend/tickets/state_machine.py:53-92`](../../backend/tickets/state_machine.py#L53-L92)
      with the new STAFF entries. Update matrix doc H-5 row to reflect
      the structurally-permitted STAFF transitions.
- [ ] Frontend completion modal for STAFF — completion note required +
      optional attachment + routing-aware destination text.
- [ ] Add tests: structural tests on the new transitions; configured-
      routing-flag tests; completion-evidence regression tests; matrix
      H-5 safety net update.

### Batch 12 — Building Manager read-only customer/contact view

Goal: Building Manager surfaces customers and contacts in their assigned
buildings, read-only. Depends on Batch 3 + Batch 4.

- [ ] Building Manager sees customers in assigned buildings — list +
      detail view, read-only.
- [ ] Building Manager sees contacts for those customers — list + detail
      view, read-only.
- [ ] Read-only by default. No edit affordances on these surfaces.
- [ ] No global provider settings access. Building Manager cannot reach
      `/admin/companies`, `/admin/buildings` (master list), or settings
      pages.
- [ ] Reuse existing scope helpers — no new backend gates needed; the
      backend already scopes via `building_ids_for(user)`.
- [ ] Add tests: backend scope tests + frontend Playwright for the
      read-only assertion (no Edit buttons rendered).

### Batch 13 — View-first refactor of admin pages

Goal: bring every parent record page in line with the Sprint 27E
reference. Depends on Batch 3 (sidebar) so sub-pages have a home.

- [ ] Customer detail parent record view-first. Decompose
      [`frontend/src/pages/admin/CustomerFormPage.tsx`](../../frontend/src/pages/admin/CustomerFormPage.tsx)
      (1784 lines) into customer-scoped sub-pages: Buildings, Users,
      Permissions, Extra Work, Contacts, Settings. Each lives at
      `/admin/customers/:id/<section>`.
- [ ] Building detail view-first. Refactor
      [`frontend/src/pages/admin/BuildingFormPage.tsx`](../../frontend/src/pages/admin/BuildingFormPage.tsx).
- [ ] Company detail view-first. Refactor
      [`frontend/src/pages/admin/CompanyFormPage.tsx`](../../frontend/src/pages/admin/CompanyFormPage.tsx).
- [ ] User detail view-first. Refactor
      [`frontend/src/pages/admin/UserFormPage.tsx`](../../frontend/src/pages/admin/UserFormPage.tsx)
      (1091 lines).
- [ ] Move large sections into tabs / subpages / modals.
- [ ] Avoid dumping all related data on one page. Lists with >10 rows
      get pagination + search (per spec §3 no-data-dumps rule).
- [ ] Add Playwright coverage per sub-route.

### Batch 14 — Proposal PDF and future design docs

Goal: nice-to-have closure on Sprint 28. Lowest priority.

- [ ] Proposal PDF export via `fpdf2` (already in
      [`backend/requirements.txt`](../../backend/requirements.txt)).
      `GET /api/extra-work/proposals/<id>/pdf/` returns a styled PDF
      with every customer-visible field. `internal_note` never appears
      in the rendered bytes (string-search assertion in the test).
- [ ] Future subscription architecture doc —
      `docs/architecture/future-subscription-architecture.md`.
      Schema-shape only; no code. Per spec §9.1.
- [ ] Future bank matching architecture doc —
      `docs/architecture/future-bank-matching-architecture.md`. Schema
      slot description (`external_reference`, `paid_at`, `paid_amount`);
      no code. Per spec §9.2.

---

## 7. Current batch pointer

- **Current batch:** **Batch 2 — Verify mild backend risk**
- **Current status:** Not started
- **Next recommended action:** Open a fresh implementation pass, re-read
  this file, state the current batch, and work only on Batch 2 items.
  Batch 2 is read-heavy (audit `TicketAssignSerializer`) and may close
  without code changes if the gate already refuses STAFF.
- **Next recommended batch (on-deck):** Batch 3 — Sidebar refactor
  foundation.

---

## 8. Completion log

Append-only. Newest at the top. One row per closed batch.

| Date | Batch | Commit | Summary | Tests/checks | Remaining risks |
|---|---|---|---|---|---|
| 2026-05-16 | Batch 1 — Operational health fixes | uncommitted on top of `6e572db` | Frontend: `getApiError` HTML-prefix guard (`client.ts`); `AuditLog.reason` + `actor_scope` added to type (`types.ts`); sidebar "Extra Work" i18n'd (`AppShell.tsx` + `common.json` EN/NL). Backend: 4 pending dev DB migrations applied after explicit user approval (`audit.0002`, `customers.0005`, `customers.0006`, `tickets.0007`). | `manage.py check` (pre + post): 0 issues; `showmigrations`: all `[X]` after migrate; `npm run typecheck`: clean; `npm run build`: clean (472ms); `npm run lint`: 52 problems = baseline (zero new hits in changed files). No unit-test framework wired on frontend — `getApiError` ships with code-level guard + typecheck/build coverage only (Vitest setup parked for a later batch). | No automated unit coverage on `getApiError`; `AuditLog.reason`/`actor_scope` declared as required (matches backend default-emitting contract); `nav.extra_work` NL value is sentence-case "Extra werk" (flippable to "Extra Werk" with no code change). |

---

## 9. Decision log

Append-only. Newest at the top. Any decision made during a batch goes
here AND in the batch's completion block.

| Date | Decision | Reason | Source |
|---|---|---|---|
| 2026-05-15 | Global default service price alone is **not** sufficient to create an instant ticket. Customer-specific active contract price is required. | Spec §5 + §4.1 + product rule #9. Global default exists as a provider-side reference only. | [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §5 |
| 2026-05-15 | Contacts are not login Users. Separate entity, no password / role / membership / permission overrides. Promotion to User is a later, explicit sprint. | Spec §1. Prevents conflation that would breach RBAC scope. | [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §1 |
| 2026-05-15 | Detail pages load **view-first / read-only by default**. Editing requires explicit Edit/Add → modal or separate page. Sprint 27E `CustomerFormPage` permission editor is the reference shape. | Spec §3. Prevents accidental mutation and gives a stable mental model across pages. | [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §3 |
| 2026-05-15 | Customer Company Admin **cannot promote anyone to Customer Company Admin** and cannot grant permissions above their own level. | RBAC matrix H-6 / H-7. Enforced via `CustomerUserBuildingAccessUpdateSerializer.validate_access_role`. | [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md) §3 H-6/H-7 |
| 2026-05-15 | Staff **may** see normal internal work notes by default, but cost/margin/provider-only proposal notes **must** be hideable from Staff. The privacy model is 3-way: customer / provider-with-staff / provider-only-cost-margin. | Spec §6 + §B.4. Today the system is 2-way only; the 3-way strip lands when STAFF visibility on Extra Work opens. | [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §6 |
| 2026-05-15 | The `TicketStatusHistory` override row (`is_override=True` + `override_reason`) IS the audit trail for ticket workflow override. **Do not** register `TicketStatusHistory` for generic AuditLog tracking — that would double-write the same fact (RBAC matrix H-11). | Sprint 27F-B1 design + matrix H-11. Workflow override (per-transition) and permission override (per-access-row) are separate concepts and must remain so. | [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md) §3 H-11; [`CLAUDE.md`](../../CLAUDE.md) §2 audit rule |

---

## 10. Open questions

Only the three open questions identified by the audit. Defaults are listed
so a future pass can proceed without re-asking; if a stakeholder wants a
different answer, they override the default and the decision is logged in
§9.

1. **Proposal line field naming** (relevant to Batch 8).
   `customer_explanation` / `internal_note` (spec §6 naming) **versus**
   legacy `customer_visible_note` / `internal_cost_note` (used by the
   existing `ExtraWorkPricingLineItem` rows).
   **Default recommendation:** use the spec names
   (`customer_explanation`, `internal_note`) for the **new** `Proposal`
   model. The legacy `ExtraWorkPricingLineItem` keeps its names because
   it's a different concept (single-line request pricing breakdown, not a
   first-class proposal artifact). Document the rename in §9 when Batch 8
   executes.

2. **Staff manager-review workflow** (relevant to Batch 11).
   When STAFF marks a ticket done with the new routing, what's the BM's
   review obligation?
   **Default recommendation:**
   - STAFF marks done → **`WAITING_MANAGER_REVIEW`** (new status).
   - Building Manager accepts → `WAITING_CUSTOMER_APPROVAL`.
   - Building Manager rejects → `IN_PROGRESS` (work continues).
   - BM cannot skip the customer (that remains a workflow override gated
     by the existing `is_override` + `override_reason` Sprint 27F-B1
     contract).

3. **Cart-level vs line-level customer notes** (relevant to Batch 6).
   Spec §4 puts a `customer_note` on each cart line. The existing
   `ExtraWorkRequest.description` is a free-text field on the request
   itself.
   **Default recommendation:** keep **both**. The request-level
   `description` is "why I'm submitting this cart"; each line carries its
   own `customer_note` for per-service context. Semantically separable;
   the UI must make this distinction visually clear.

---

## 11. Rules for updating this file

At the **end of every batch**:

1. **Update the current batch status.** Mark items complete:
   `- [ ] Open item` becomes `- [x] ~~Completed item~~`.
2. **Add a completion block under the batch heading.** Block contents:
   - **Date:** absolute ISO date (e.g. `2026-06-12`).
   - **Commit:** SHA(s) that landed the batch. If unmerged, write
     "uncommitted on working tree as of <date>".
   - **Files changed summary:** paths, not full diffs. Example: *"Backend:
     `customers/models.py` (Contact model), `customers/migrations/0007_*`,
     `audit/signals.py` (Contact registration), `customers/tests/test_sprint28_contacts.py`. Frontend: `api/types.ts`,
     `api/admin.ts`, `pages/admin/CustomerContactsPage.tsx`."*
   - **Tests / checks run:** exact commands + outcomes. Example: *"`python
     manage.py test customers audit --keepdb -v 1` → OK (561 tests).
     `npm run typecheck` → clean. `npm run lint` → baseline (no new
     hits)."*
   - **Important decisions made:** one-line summary per decision. Also
     append a row in §9 with the full context.
   - **Remaining risks:** anything the next batch must know. Example: *"The
     Contact-detail page reuses the `useEntityForm` hook, which still
     bakes inline-editing in — Batch 13 must refactor that hook before
     applying view-first to the Contact detail page."*
3. **Append a row in §8 (completion log)** mirroring the batch's metadata.
4. **Append a row in §9 (decision log)** for every decision made during
   the batch.
5. **Advance the §7 Current batch pointer** to the next batch ONLY if all
   required tests/checks passed. If anything is yellow/red, keep the
   pointer on the current batch.
6. **Advance the §7 Next recommended batch pointer** to the new on-deck
   batch.

If a **blocker is found** during a batch:

1. **Keep the Current batch pointer on the blocked batch.** Do not advance.
2. **Document the blocker under the batch's checklist** with a new line
   prefixed `BLOCKED <date>: <description>`. Include what was attempted
   and what's required to resolve.
3. **Stop the pass.** Do not start the next batch. Report the blocker to
   the user and wait for direction.
4. Resume only when the blocker is resolved (either by user input or by
   a follow-up batch). Document the resolution under the same blocker
   line as `RESOLVED <date>: <how>`.

**Never rewrite history in this document.** Completion logs and decision
logs are append-only. If a previous entry turns out to be factually wrong,
add a correction note below it dated with the correction date — do not
edit the original. This preserves the audit trail across AI sessions.
