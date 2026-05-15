# Product Backlog

The live, prioritised list of feature work. Owner: **project-manager**
sub-agent (only the PM edits this file).

Format per row:

```
- [<priority>] [<id>] <title>
  Source: <doc + section, e.g. GAP_ANALYSIS_2026-05 §2a or sprint-27-rbac-matrix §7 G-Bn>
  Owner: backend-engineer | frontend-engineer | both
  Tests: <test file path or NEEDS-TEST>
  Acceptance: <observable behaviour change>
```

Priorities:
- **P0** — security or correctness; do next
- **P1** — product maturity (RBAC sprint follow-ups, dashboard correctness)
- **P2** — polish

---

## Sprint 27F — closed (2026-05-15/16) — see docs/backlog/DONE.md

All three Sprint 27F items shipped on the working tree (uncommitted, awaiting
review). 27F-B1 + 27F-B2 backend changes pass the full 548-test RBAC sweep;
27F-F1 typecheck + lint clean (lint at baseline). G-B3, G-B6, G-F3 closed
in the matrix doc.

---

## Sprint 28 epic — Extra Work shopping-cart + proposal builder

Source: [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md)
(§4–§8). The current Extra Work surface ships a single-line request model
(`ExtraWorkRequest` with one service per request). The 2026-05-15 meeting
re-shaped it into a cart of N line items with two branches (instant-ticket
path for pre-agreed prices, proposal path for custom prices). All items
below are P1 unless noted; the dependency graph is documented per row.

- [P1] [EXTRA-CATALOG-1] Service catalog: introduce `Service` model
  (name, description, `unit_type`, default `unit_price`,
  `default_vat_pct`, `is_active`, FK to `ServiceCategory`) and
  `ServiceCategory` model.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §4 + §5
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28a_service_catalog.py (NEEDS-TEST)
  Acceptance: SUPER_ADMIN / COMPANY_ADMIN can CRUD services and
  categories through `/api/services/` and `/api/service-categories/`
  endpoints; CUSTOMER_USER can list active services scoped to their
  customer; cross-provider attempts 403; audit signals registered on
  both new models.

- [P1] [EXTRA-PRICING-1] Global vs customer-specific contract pricing.
  Introduce `CustomerServicePrice` (FK service, FK customer, `unit_price`,
  `vat_pct`, `valid_from`, `valid_to`, `is_active`).
  Source: docs/product/meeting-2026-05-15-system-requirements.md §5
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28a_pricing_resolver.py (NEEDS-TEST)
  Acceptance: resolver function `resolve_price(service, customer, on=date)`
  returns customer-specific contract price when active, else global
  default; returns `None` when neither exists (routes the line to the
  proposal flow per §4.2); resolver is anchored on customer_id —
  cross-customer attempts return None; full CRUD audit-signal coverage.
  Depends on: EXTRA-CATALOG-1.

- [P1] [EXTRA-CART-1] Cart-shaped Extra Work request with per-item dates.
  Either extend the existing `ExtraWorkRequest` to be the parent and add
  `ExtraWorkRequestItem` (FK request, FK service, `quantity`,
  `requested_date`, `customer_note`), or re-shape the existing model —
  the sprint design decides. Per-item `requested_date` is required (§4).
  Source: docs/product/meeting-2026-05-15-system-requirements.md §4
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28b_cart_request.py (NEEDS-TEST)
  Acceptance: a customer can POST `/api/extra-work/` with N line items,
  each with its own `requested_date`; the response carries the parent +
  N children; scoping enforces customer/building access on every line;
  the existing single-line endpoint either migrates cleanly or is kept
  in parallel with a deprecation flag.
  Depends on: EXTRA-CATALOG-1.

- [P1] [EXTRA-INSTANT-TICKET-1] Skip proposal when all lines have a
  pre-agreed price → instantly create execution Tickets.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §4.1
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28b_instant_ticket_path.py (NEEDS-TEST)
  Acceptance: an `ExtraWorkRequest` whose every line resolves to a price
  via EXTRA-PRICING-1 transitions directly to `IN_PROGRESS` (or new
  `INSTANTIATED`) and spawns one Ticket per line atomically; if ANY line
  is custom-priced the whole request stays in the proposal queue; ticket
  spawn is inside the same `transaction.atomic()` as the transition;
  failure to spawn rolls back the transition.
  Depends on: EXTRA-CART-1, EXTRA-PRICING-1.

- [P1] [EXTRA-PROPOSAL-1] Custom proposal builder with VAT-aware line
  items. Introduce `ExtraWorkProposal` + `ExtraWorkProposalLine` (fields
  per §6 table); customer-facing serializer omits `internal_note`,
  provider-facing serializer includes it.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §6
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28c_proposal_builder.py (NEEDS-TEST)
  Acceptance: provider-side admin can build / edit / send a proposal;
  customer sees the customer-facing payload; proposal can have N lines
  with mixed `vat_pct`; totals (net, VAT, gross) are server-computed and
  exposed read-only on the serializer; full CRUD audit-signal coverage
  on both new models.
  Depends on: EXTRA-CART-1.

- [P1] [EXTRA-NOTES-1] Dual-note system: customer-visible
  `customer_explanation` vs internal `internal_note` on each proposal
  line; assert internal note never leaks.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §6 (Hard rule on the dual-note system)
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28c_dual_note_isolation.py (NEEDS-TEST)
  Acceptance: a regression-lock test serializes a proposal as
  CUSTOMER_USER and grep-asserts `internal_note` is absent from the
  JSON response and from the PDF (when EXTRA-PDF-1 lands); changes to
  `internal_note` write an `AuditLog` UPDATE row.
  Depends on: EXTRA-PROPOSAL-1.

- [P2] [EXTRA-PDF-1] Proposal PDF generation.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §6 (PDF export)
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28d_proposal_pdf.py (NEEDS-TEST)
  Acceptance: `GET /api/extra-work/proposals/<id>/pdf/` returns a
  styled PDF via `fpdf2` (already in `backend/requirements.txt`) with
  every customer-visible field; `internal_note` never appears in the
  rendered bytes (string-search assertion in the test); endpoint gated
  by the same scope as the proposal read endpoint.
  Depends on: EXTRA-PROPOSAL-1, EXTRA-NOTES-1.

- [P1] [EXTRA-TIMELINE-1] Proposal / Ticket timeline events.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §6 (Timeline events)
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28c_timeline_events.py (NEEDS-TEST)
  Acceptance: every proposal lifecycle event (created, submitted,
  customer viewed, customer approved, customer rejected, admin
  overridden) emits an `ExtraWorkProposalTimelineEvent` row; provider
  sees all events; customer sees a filtered subset (no internal note
  text; override-reason metadata visible but flagged as "override").
  Depends on: EXTRA-PROPOSAL-1.

- [P1] [EXTRA-OVERRIDE-1] Admin override on proposal approval — mandatory
  `override_reason`; recorded on status history row + timeline +
  workflow-history table (mirror Sprint 27F-B1 ticket pattern).
  Source: docs/product/meeting-2026-05-15-system-requirements.md §7
  Owner: backend-engineer
  Tests: backend/extra_work/tests/test_sprint28c_proposal_override.py (NEEDS-TEST)
  Acceptance: SUPER_ADMIN / COMPANY_ADMIN can override customer
  approve/reject decisions with a mandatory `override_reason`; missing
  reason → HTTP 400 with stable code `override_reason_required`;
  override fact lives ONLY on the proposal status-history row (NOT on
  the generic AuditLog — H-11 separation); timeline carries the actor +
  timestamp visible to provider, override marker (no free-text reason)
  visible to customer.
  Depends on: EXTRA-PROPOSAL-1.

- [P1] [UX-SIDEBAR-1] Hierarchical left-sidebar customer navigation.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §3
  Owner: frontend-engineer
  Tests: frontend/tests/e2e/sprint28_sidebar_customer_submenu.spec.ts (NEEDS-TEST)
  Acceptance: clicking a customer in the top-level sidebar enters the
  customer-scoped submenu (Buildings / Users / Permissions / Extra
  Work / Contacts / Settings) with a visible Back action; URL encodes
  the submenu state; browser-back returns to the top-level sidebar.

- [P1] [UX-CLOSED-DOOR-1] View-first detail pages with edit modals/pages
  across the admin UI.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §3
  Owner: frontend-engineer
  Tests: frontend/tests/e2e/sprint28_closed_door_audit.spec.ts (NEEDS-TEST)
  Acceptance: every detail page (Ticket, Extra Work, Customer, Building,
  User) loads read-only; every mutation surface (Edit / Add) opens a
  modal or navigates to a focused route; no inline-mutate paths remain
  on list rows. The Sprint 27E `CustomerFormPage` permission-override
  editor is the reference shape — audit the other admin pages against
  it.

- [P1] [CONTACTS-1] Contact records (telephone-book entries) — no login.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §1
  Owner: both
  Tests: backend/customers/tests/test_sprint28_contacts.py +
  frontend/tests/e2e/sprint28_contacts.spec.ts (NEEDS-TEST)
  Acceptance: new `Contact` model (FK customer, FK optional building,
  `full_name`, `email`, `phone`, `role_label`, `notes`) and CRUD
  endpoints; Contact UI lives on the customer-scoped submenu (per
  UX-SIDEBAR-1); UI has NO password field, NO role dropdown, NO login
  action. Deleting a Contact never affects any User. Promotion
  "Contact → User" flow is parked for a later sprint.

- [P2] [FUTURE-SUBSCRIPTION-1] Subscription / abonement architecture
  placeholder.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §9.1
  Owner: project-manager (design doc only)
  Tests: n/a in this sprint
  Acceptance: a short design doc under
  `docs/architecture/future-subscription-architecture.md` describes
  the data-model shape (subscription, frequency, contract anchor) but
  ships no code. The Service / pricing models from EXTRA-CATALOG-1 /
  EXTRA-PRICING-1 are reviewed to confirm they don't bake in
  "one-shot only" assumptions.

- [P2] [FUTURE-BANK-MATCHING-1] Bank-transaction matching architecture
  placeholder.
  Source: docs/product/meeting-2026-05-15-system-requirements.md §9.2
  Owner: project-manager (design doc only)
  Tests: n/a in this sprint
  Acceptance: short design doc under
  `docs/architecture/future-bank-matching-architecture.md` describes
  the schema slot (`external_reference`, `paid_at`, `paid_amount`) on
  proposal / ticket; no code. The EXTRA-PROPOSAL-1 sprint reserves the
  columns or explicitly defers them with a documented migration plan.

---

## Active sprint: 27G — end-to-end Playwright + demo runbook

- [P1] [27G-F1] Playwright spec: customer-pricing loop with one override at
  each decision point (create → approve quote → reject quote → override
  reject → re-approve).
  Source: docs/architecture/sprint-27-rbac-matrix.md §8 (Sprint 27G plan)
  Owner: frontend-engineer
  Tests: frontend/tests/e2e/sprint27g_customer_pricing_loop.spec.ts (NEEDS-TEST)
  Acceptance: spec passes on a fresh seeded DB; covers every transition in
  the extra-work state machine.

- [P2] [27G-D1] Refresh `docs/demo-walkthrough.md` to reflect Sprint 27E +
  27F UI.
  Source: docs/architecture/sprint-27-rbac-matrix.md §8 (Sprint 27G plan)
  Owner: project-manager (docs only)
  Tests: n/a
  Acceptance: demo walkthrough shows screenshots and key sequences for the
  new permission-override editor + ticket override modal.

---

## Standing items from GAP_ANALYSIS_2026-05

The P0 items in §4 of GAP_ANALYSIS_2026-05 (CHANGE-1 through CHANGE-6 plus
CHANGE-7..17, Reports v1, SLA v1, Settings/Profile B1/B2, and the backend
healthcheck) are now on master and have been moved to `DONE.md`. The items
below are the **still-open** ones from §4.

### Backend — schema or cross-cutting

- [P2] [BACKEND-INDEXES-1] Composite DB indexes on `(status, priority)`,
  `(company, status)`, `(building, status)` on Ticket.
  Source: GAP_ANALYSIS_2026-05 §4 (P1)
  Owner: backend-engineer
  Tests: migration-only — verify `EXPLAIN ANALYZE` on the dashboard query
  drops a Seq Scan.
  Acceptance: new indexes show in `\d tickets_ticket` (Postgres).

- [P2] [BACKEND-REQID-1] Request-ID / correlation-ID middleware. (Note:
  `backend/audit/context.py:70-78` already READS an upstream X-Request-Id
  header into the `AuditLog.request_id` column, but nothing GENERATES one
  when the proxy didn't set it, no middleware adds it to the response, and
  Sentry breadcrumbs don't carry it.)
  Source: GAP_ANALYSIS_2026-05 §4 (P1)
  Owner: backend-engineer
  Tests: backend/config/tests/test_request_id_middleware.py (NEEDS-TEST)
  Acceptance: every response has `X-Request-Id` header; request logs
  include the same ID; Sentry breadcrumbs include the ID.

### Frontend — schema or cross-cutting

- [P2] [FRONTEND-DEVICE-1] The "Remember my device for 30 days" checkbox on
  Login is visual-only — bind it or remove it. TODO at
  `frontend/src/pages/LoginPage.tsx:473-475` confirms still open.
  Source: GAP_ANALYSIS_2026-05 §2b
  Owner: frontend-engineer
  Tests: frontend/tests/e2e/login.spec.ts (extend)
  Acceptance: checkbox is either wired (token cookie max-age changes) or
  removed; UI no longer lies to the user.

- [P2] [FRONTEND-OVERRIDE-1] Customer-decision override UX hard-codes
  `(role === "SUPER_ADMIN" || role === "COMPANY_ADMIN")` at
  `frontend/src/pages/TicketDetailPage.tsx:62-67`. CHANGE-11 widened the
  scope to COMPANY_ADMIN at both backend and frontend, but the check is
  still role-driven, not effective-permission-driven. If a future sprint
  carves COMPANY_ADMIN out per-customer via the policy resolver, or grants
  override to a different role, the UI will silently fail to track it.
  Source: GAP_ANALYSIS_2026-05 §2b
  Owner: frontend-engineer
  Tests: extend existing `frontend/tests/e2e/` override spec.
  Acceptance: override button visibility is driven by an effective-
  permission lookup (`customer.ticket.approve_*` keys), not by the
  global User.role enum.

- [P2] [FRONTEND-BILINGUAL-1] Bilingual UI: `LANGUAGE_CODE=nl`,
  `User.language` field exists; UI translation bundles need an audit pass
  for untranslated keys. (`frontend/src/i18n/{nl,en}/*.json` exists per
  bundle but no automated diff check.)
  Source: GAP_ANALYSIS_2026-05 §4 (P2)
  Owner: frontend-engineer
  Tests: a key-coverage script that diffs nl/*.json vs en/*.json (NEEDS-TEST).
  Acceptance: every key in nl bundles has an en counterpart and vice
  versa; CI fails on divergence.

### Operational

- [P2] [OPS-EMAIL-1] HTML email templates for password reset + status-change
  emails. Plain-text is fine for MVP but UI maturity wants HTML alts.
  Source: GAP_ANALYSIS_2026-05 §4 (P2)
  Owner: backend-engineer
  Tests: backend/notifications/tests/test_html_templates.py (NEEDS-TEST)
  Acceptance: every send has a HTML alt; templates carry brand styling;
  MailHog renders the HTML in development.

- [P2] [OPS-NGINX-1] Nginx `client_max_body_size 12M` is barely above the 10
  MB attachment limit. Bump to 20M for headroom or tighten the backend
  validator.
  Source: GAP_ANALYSIS_2026-05 §2c
  Owner: frontend-engineer (the file is `frontend/nginx.conf:30`)
  Tests: scripts/attachment_file_type_test.sh (extend with a 10.5MB file).
  Acceptance: 10.5MB upload succeeds end-to-end; 12MB upload rejected with
  a clear error.

---

## Future / parked

- [P2] [BACKEND-OSIUS-RENAME] Rename the `osius.*` permission-key namespace
  to something vendor-neutral. Currently documented technical debt
  (G-B8). Its own sprint, do not bundle.
- [P2] [BACKEND-STAFF-EXTRAWORK] Open STAFF visibility on Extra Work.
  Currently `scope_extra_work_for` returns `.none()` for STAFF (G-B7).
  Needs a staff-execution surface design first.
- [P2] [OPS-DJANGO-AXES] Per-account / per-IP brute-force protection above
  the existing 5/15-min lockout (e.g. `django-axes`).
