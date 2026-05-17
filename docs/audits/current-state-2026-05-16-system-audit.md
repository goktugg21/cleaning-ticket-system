# Current-state system audit — 2026-05-16

**Audit scope:** full repository, backend + frontend, against
[`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md)
and [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md).

**Auditor:** Claude Code, dispatched as three parallel read-only sub-agents
(backend deep-dive, frontend deep-dive, validation runner) plus PM-level
synthesis. **No code was modified in this audit.**

**Repo state at audit time:**
- Branch: `master`
- HEAD: `be7b3e4 chore: snapshot sprint 28 pre-audit state`
- Working tree: clean
- All Sprint 27F deliverables on master.

---

## 1. Executive summary

### Overall confidence

**Backend:** GREEN on security / scope / RBAC. YELLOW on product-shape vs the
2026-05-15 spec — the existing tickets domain is solid (Sprint 27A–F shipped
clean), but the Extra Work domain is the wrong shape to support the
shopping-cart + proposal flow the spec describes.

**Frontend:** YELLOW. Sprint 27E and 27F-F1 deliverables are correct.
Everything else is older, with three structural shortfalls:
- the sidebar is flat (no hierarchical customer submenu — spec §3 violation);
- nearly every admin detail page loads as an editable form on first render
  (closed-door / view-first violation — spec §3);
- the three Extra Work pages have **no i18n at all** (hard-coded English).

**Closer to correct: backend.** The backend ships the RBAC invariants, the
audit contract, the override discipline (Sprint 27F), and the customer-side
permission resolver (Sprint 27A–E). It lacks the Sprint 28 product shape
(Contact, Service catalog, cart, proposal). The frontend ships the same
shape as the backend but has accumulated UX debt — the admin pages predate
the Sprint 27E view-first reference, and the Extra Work surface is i18n
broken.

### Biggest current risks

1. **Product-shape gap (P1).** The Extra Work entity is single-line; there is
   no Service catalog, no cart, no proposal model. Until those land,
   spec §4–§8 is unreachable. This is the single largest body of work in
   the backlog.
2. **Dev DB migration drift (P2 operational, not a security issue).** Four
   committed migrations are unapplied on the dev Postgres:
   `audit.0002_auditlog_reason_actor_scope`,
   `customers.0005_customercompanypolicy`,
   `customers.0006_backfill_customer_company_policy`,
   `tickets.0007_ticketstatushistory_is_override_and_more`.
   The Django test runner creates its own `test_*` database and auto-applies
   migrations every run, so the **548-test baseline is correct** — it just
   doesn't reflect the running dev container's schema. Anyone who connects
   to the dev DB via shell or hits the dev API will see the pre-Sprint-27C
   shape. **Fix: run `python manage.py migrate` against the dev container
   exactly once. No data risk; the migrations are schema-only or have
   backfills that are idempotent.**
3. **`getApiError` returns raw HTML 500 bodies verbatim (P1).** When the
   backend returns a Django HTML 500 page (DEBUG=False or unexpected error),
   the frontend interceptor at [`frontend/src/api/client.ts:148`](../../frontend/src/api/client.ts#L148)
   treats the response body as plain text and renders the full HTML inside
   the page's error banner. This matches the "raw HTML in the browser"
   symptom the owner reports. ~5-line fix; should be the first frontend
   change in the next batch.
4. **Sidebar / navigation hierarchy missing (P1).** The spec §3 requires a
   hierarchical customer-scoped submenu (Buildings / Users / Permissions /
   Extra Work / Contacts / Settings / Back). The current sidebar is flat.
   Every other view-first refactor depends on this submenu existing — it's
   the structural anchor for "this page is now customer-scoped". Without
   it, every admin detail page is forced into the "dump everything on one
   route" anti-pattern that is the spec's biggest violation.
5. **Mild backend risk to verify: STAFF reaching `/api/tickets/<id>/assign/`.**
   [`tickets/views.py:250`](../../backend/tickets/views.py#L250) gates with
   `is_staff_role(request.user)` which returns True for STAFF. The
   downstream serializer is the next gate; the backend audit could not
   verify whether `TicketAssignSerializer.validate` refuses STAFF. **Action:
   read `tickets/serializers.py` `TicketAssignSerializer` and confirm STAFF
   cannot mutate `ticket.assigned_to`. Probably fine, but listed as a
   follow-up.**

### Test / build / lint state

- Backend Django check: **0 issues**.
- Backend `makemigrations --dry-run --check`: **clean** (no orphan model
  changes).
- Django test suite: **548/548 OK** on `be7b3e4` from the prior turn — not
  re-run in this audit pass.
- Frontend `tsc --noEmit`: **clean**.
- Frontend `vite build`: **clean** (~433ms, 721 kB main bundle, advisory
  chunk-size warning only).
- Frontend ESLint: **52 problems (49 errors, 3 warnings)** — baseline
  pre-existing; the Sprint 27F-F1 frontend agent verified the new code
  introduces zero new lint hits.

---

## 2. Latest commit / change summary

```
be7b3e4  chore: snapshot sprint 28 pre-audit state         <- HEAD
b08fa10  Sprint 27E: add customer permission management UI
9a593ed  Sprint 27D: wire provider and customer policy permissions
c0db299  Sprint 27C: add customer permission controls and policy model
c91e7eb  Sprint 27B: add effective permissions and audit staff visibility updates
408d8ad  Sprint 27A: add RBAC matrix and safety net tests
```

`be7b3e4` is a single bundled snapshot commit that landed every working-tree
change from the prior turn:

| Area | Files changed | Impact |
|---|---|---|
| Sprint 27F-B1 (ticket workflow override) | `backend/tickets/{models,state_machine,serializers,views}.py`, `backend/tickets/migrations/0007_*`, `backend/tickets/tests/test_sprint27f_workflow_override.py`, two call-site fixes in `seed_demo_data.py` + `test_state_machine.py` | Closes matrix gap G-B3. `TicketStatusHistory` carries `is_override` + `override_reason`. |
| Sprint 27F-B2 (AuditLog reason + actor_scope) | `backend/audit/{models,context,middleware,signals,serializers}.py`, `backend/audit/migrations/0002_*`, `backend/audit/tests/test_sprint27f_audit_columns.py`, `tickets/views.py` soft-delete site | Closes matrix gap G-B6. `AuditLog.reason` (TextField) + `AuditLog.actor_scope` (JSONField). Context plumbing. |
| Sprint 27F-F1 (frontend ticket override modal) | `frontend/src/pages/TicketDetailPage.tsx`, `frontend/src/api/types.ts`, both `i18n/{en,nl}/ticket_detail.json`, `frontend/tests/e2e/sprint27f_ticket_override.spec.ts` | Closes matrix gap G-F3. Two-press confirmation modal with mandatory reason; timeline override badge. |
| Documentation realignment (2026-05-15 product spec) | `CLAUDE.md` (new §2A product context, authoritative-product-sources rule), `.claude/agents/{project-manager,backend-engineer,frontend-engineer}.md` (corrected audit contract + UX rules + i18n namespace pattern), `docs/product/meeting-2026-05-15-system-requirements.md` (new 343-line authoritative doc), `docs/backlog/{PRODUCT_BACKLOG,BUGS,DONE,README}.md` (full reconcile + 14 Sprint 28 epic rows) | Aligns the operating docs with the stakeholder meeting. |

Total: 27 files, ~+2740/-38 lines.

**Uncommitted files at audit time:** none. Working tree is clean.

---

## 3. Current implementation map

What exists today, area by area.

### Backend

| Area | Status | Anchors |
|---|---|---|
| Roles | OK | `UserRole` enum at [`backend/accounts/models.py:7-16`](../../backend/accounts/models.py#L7-L16) — 5 values (matrix §1.1) |
| Memberships / scope | OK | `CompanyUserMembership`, `BuildingManagerAssignment`, `BuildingStaffVisibility`, `CustomerUserMembership`, `CustomerBuildingMembership`, `CustomerUserBuildingAccess` — all present with the matrix shape |
| Provider/customer hierarchy | OK at the model layer | One global `UserRole`; customer-side sub-role lives on `CustomerUserBuildingAccess.access_role` (Sprint 23A) |
| Contacts | **MISSING** | No `Contact` model anywhere in `backend/` |
| Customers / Buildings / Companies | OK | Models + full-CRUD viewsets + scope helpers |
| Staff permissions | **PARTIAL** (P1) | `StaffProfile` is global; `BuildingStaffVisibility` per-row has only `can_request_assignment`. The spec's B1/B2/B3 example (per-building "own-only / see-all / see-all-and-assign") cannot be expressed with the current schema. |
| Tickets | OK | Full state machine (`tickets/state_machine.py`), scope helpers, soft-delete, attachments with `is_hidden`, messages with `INTERNAL_NOTE` type, Sprint 27F-B1 override fields on `TicketStatusHistory` |
| Ticket workflow override | OK (Sprint 27F-B1) | `is_override` + `override_reason` on history row; provider-driven coercion; `override_reason_required` 400 contract |
| Extra Work | **WRONG SHAPE** for spec §4 | Single-line `ExtraWorkRequest` with a free-text category enum (`extra_work/models.py:100-266`); provider-built `ExtraWorkPricingLineItem` lines AFTER the fact. No customer-composed cart. No service FK. No per-line `requested_date`. |
| Service catalog / pricing | **MISSING** | No `Service`, `ServiceCategory`, `CustomerServicePrice`, `Contract` model anywhere |
| Proposal builder | **PARTIAL** | The closest analogue is `ExtraWorkPricingLineItem` (`customer_visible_note` + `internal_cost_note` 2-field split, with customer-facing serializer omitting `internal_cost_note`). But there's no separate `Proposal`/`ProposalLine` entity, no timeline-event log, no PDF export. |
| Dashboard / stats | PARTIAL | `/api/tickets/stats/` + `/api/tickets/stats/by-building/` ship. **No Extra Work stats endpoint exists.** |
| Audit / history / timeline | OK | `AuditLog` with Sprint 27F-B2 columns; `audit/signals.py` registers every model the matrix requires; `TicketStatusHistory` + `ExtraWorkStatusHistory` for workflow events; reports/sla apps in place |
| Reports | OK | 15 endpoints across status / time / SLA / by-type / by-customer / by-building, with CSV/PDF export |
| SLA | OK | Business-hours engine + Celery tasks + signals; ticket SLA fields on `Ticket` |
| Notifications | OK | NotificationLog, NotificationPreference, send services, Celery worker (Sprint 27 stack) |
| Frontend navigation | n/a | (frontend section below) |

### Frontend

| Area | Status | Anchors |
|---|---|---|
| Routes | PARTIAL | All routes defined in [`frontend/src/App.tsx`](../../frontend/src/App.tsx); guards via `AdminRoute` / `SuperAdminRoute` / `ReportsRoute` / `ExtraWorkRoute` / `StaffRequestReviewRoute` |
| Sidebar | **WRONG** for spec §3 | [`frontend/src/layout/AppShell.tsx`](../../frontend/src/layout/AppShell.tsx) — single flat list, no hierarchical / customer-scoped submenu, no Back action |
| Auth | OK | JWT with refresh-token interceptor at [`frontend/src/api/client.ts:56-86`](../../frontend/src/api/client.ts#L56-L86) |
| API types | PARTIAL | [`frontend/src/api/types.ts`](../../frontend/src/api/types.ts) — covers tickets, extra-work-single-line, customers, buildings, staff, permissions; missing `Contact`, `Service`, `ServiceCategory`, `Proposal`, `ProposalLine`, `ExtraWorkRequestItem`, `Cart`. `AuditLog` type is also missing the Sprint 27F-B2 `reason` + `actor_scope` columns. |
| Customer admin pages | PARTIAL | `CustomerFormPage` carries the Sprint 27E view-first reference for permission overrides, but the parent record (name/email/visibility flags) is editable on first load; everything else dumps onto one 1784-line route |
| Ticket detail | OK on Sprint 27F-F1 surfaces, PARTIAL elsewhere | [`frontend/src/pages/TicketDetailPage.tsx`](../../frontend/src/pages/TicketDetailPage.tsx) — override modal correct (lines 1909-2003); status buttons + messages composer + attachment upload + staff-assign dropdown still inline-mutate |
| Extra Work pages | **BROKEN i18n + WRONG SHAPE** | Three pages: `CreateExtraWorkPage`, `ExtraWorkListPage`, `ExtraWorkDetailPage`. None has `useTranslation`. All hard-coded English. All assume the single-line model. No cart UI. |
| Dashboard | PARTIAL | [`frontend/src/pages/DashboardPage.tsx`](../../frontend/src/pages/DashboardPage.tsx) — tickets only; zero Extra Work integration; identical shape for every role |
| Reports | OK | `pages/reports/ReportsPage.tsx` + chart components; the one frontend lint hit is here (`react-hooks/set-state-in-effect`) |
| Override pattern | OK | Ticket: Sprint 27F-F1 modal. Extra Work: inline block at `ExtraWorkDetailPage:774-876` — works but is not a modal and has no i18n; the inconsistency is a P2 polish concern |
| i18n bundles | OK on parity; PARTIAL on coverage | 7 namespaces (`common`, `create_ticket`, `dashboard`, `login`, `reports`, `settings`, `ticket_detail`), perfect EN/NL parity. **No `extra_work` namespace; sidebar "Extra Work" literal at AppShell.tsx:157.** |

---

## 4. Gap matrix

Cross-cutting gaps against the 2026-05-15 spec + RBAC matrix. Statuses:
**OK** / **PARTIAL** / **MISSING** / **WRONG** / **BROKEN** / **UNKNOWN**.
Severities: **P0** (security/scope/workflow blocker) / **P1** (core product
blocker) / **P2** (UX/quality) / **P3** (polish).

| # | Area | Required behaviour | Current implementation | Evidence (file:line) | Status | Severity | Recommended fix |
|---|---|---|---|---|---|---|---|
| 1 | §1 Contacts | `Contact` model + UI separate from `User` | No model, no API, no UI | (no class `Contact` anywhere) | MISSING | **P0** (dependency for Building Manager surface §B.3 and customer Contacts panel §1) | Land backlog row `CONTACTS-1` first; ship model + admin CRUD endpoint + customer-scoped Contacts panel together |
| 2 | §2 Modular per-building permissions | Per-row `access_role` + JSON overrides + policy DENY | All three layers shipped | [`customers/permissions.py:185-207`](../../backend/customers/permissions.py#L185-L207) | OK | — | — |
| 3 | §3 Sidebar hierarchy | Customer-scoped submenu with Back | Flat sidebar | [`frontend/src/layout/AppShell.tsx:138-242`](../../frontend/src/layout/AppShell.tsx#L138-L242) | MISSING | **P1** | Refactor sidebar into a `mode = "top-level" \| "customer-scoped"` with URL-encoded state |
| 4 | §3 View-first / closed-door | Detail pages read-only by default | Sprint 27E permission editor is view-first; **every other admin detail page is editable on first load** | `BuildingFormPage`, `CompanyFormPage`, `CustomerFormPage` (parent record), `UserFormPage` | WRONG | **P1** | Adopt the Sprint 27E pattern: read-only summary card → "Edit" button → modal or inline section |
| 5 | §3 No data-dump pages | Use tabs/search/modals | `CustomerFormPage` (1784 lines on one route); `UserFormPage` (1091 lines) | (same) | WRONG | **P1** | Depends on §3 sidebar — once submenu lands, decompose these pages |
| 6 | §4 Extra Work cart-shaped request | Parent `ExtraWorkRequest` + N `ExtraWorkRequestItem` with per-line service + qty + `requested_date` | Single-line `ExtraWorkRequest`; provider-built pricing lines exist but are NOT customer cart lines | [`extra_work/models.py:100-266`](../../backend/extra_work/models.py#L100-L266) | MISSING | **P1** | Backlog row `EXTRA-CART-1`; reshape the request model |
| 7 | §4.1 Instant-ticket path | Auto-spawn Tickets atomically when every line has a contract price | Not implemented; `apply_transition` does not create Tickets | [`extra_work/state_machine.py:286-303`](../../backend/extra_work/state_machine.py#L286-L303) | MISSING | **P1** | `EXTRA-INSTANT-TICKET-1`; depends on cart + pricing |
| 8 | §5 Service catalog + pricing model | `Service`, `ServiceCategory`, `CustomerServicePrice` + `resolve_price()` resolver; unit types `HOURLY` / `PER_SQM` / `FIXED` / `PER_ITEM` | None of these models exist | (no class `Service`, no `CustomerServicePrice`) | MISSING | **P1** | `EXTRA-CATALOG-1` + `EXTRA-PRICING-1` |
| 9 | §6 Proposal builder | `Proposal` + `ProposalLine` with `customer_explanation` + `internal_note` | Closest analogue is `ExtraWorkPricingLineItem` with `customer_visible_note` + `internal_cost_note` — but bound to the single-line request, not a separate proposal artifact | [`extra_work/models.py:269-336`](../../backend/extra_work/models.py#L269-L336) | PARTIAL | **P1** | `EXTRA-PROPOSAL-1`; port the dual-note privacy contract to a first-class proposal entity |
| 10 | §6 Internal note 3-way privacy | customer / provider-with-staff / provider-only (cost) | Only 2-way: STAFF sees everything provider-side roles see, including `manager_note` + `internal_cost_note` | [`extra_work/serializers.py:238-265`](../../backend/extra_work/serializers.py#L238-L265) — provider-only strip exists but doesn't separate STAFF | PARTIAL | P2 (parked by G-B7: STAFF can't see Extra Work AT ALL today) | When G-B7 closes, add STAFF-specific strip on cost/margin notes |
| 11 | §7 Override audit — ticket | Persisted on `TicketStatusHistory.is_override + override_reason` | Shipped Sprint 27F-B1 | [`tickets/models.py:254-263`](../../backend/tickets/models.py#L254-L263) | OK | — | — |
| 12 | §7 Override audit — proposal | Same shape mirrored on the proposal entity | Proposal entity itself missing; EW request-level override exists but at wrong granularity | [`extra_work/models.py:202-212`](../../backend/extra_work/models.py#L202-L212) | PARTIAL | **P1** | `EXTRA-OVERRIDE-1`; depends on proposal model |
| 13 | §8 Accepted proposal → tickets | Auto-spawn one Ticket per approved line atomically | Not implemented | (state-machine has no Ticket creation) | MISSING | **P1** | Depends on cart + proposal models |
| 14 | §J Dashboard with Tickets + Extra Work cards | Two top-level sections, role-aware shape | Tickets only; identical shape for every role | [`frontend/src/pages/DashboardPage.tsx`](../../frontend/src/pages/DashboardPage.tsx) | PARTIAL | **P1** | Once `/api/extra-work/stats/` lands, surface a parallel set of cards |
| 15 | Extra Work stats endpoint | Backend aggregate | No `stats` action on `ExtraWorkRequestViewSet` | [`extra_work/views.py`](../../backend/extra_work/views.py) | MISSING | **P1** | New `stats` + `stats_by_building` actions |
| 16 | Building Manager read-only customer/contact view | BM sees customers + contacts in assigned buildings, read-only | No surface; `AdminRoute` admits only SUPER_ADMIN + COMPANY_ADMIN | [`frontend/src/components/AdminRoute.tsx:6`](../../frontend/src/components/AdminRoute.tsx#L6) | MISSING | **P1** | New BM-scoped customer list + detail routes; depends on `CONTACTS-1` |
| 17 | Staff per-building permission granularity | Per-row visibility level (`OWN_ONLY` / `BUILDING_READ` / `BUILDING_READ_AND_ASSIGN`) | `BuildingStaffVisibility.visibility_level` enum (ASSIGNED_ONLY / BUILDING_READ / BUILDING_READ_AND_ASSIGN) wired through `scope_tickets_for` + the BM-assign gate. Sprint 28 Batch 10 (backend). No new osius keys — per-row field is enough (PM Q6). | [`buildings/models.py:52-118`](../../backend/buildings/models.py#L52-L118), [`accounts/scoping.py:211-241`](../../backend/accounts/scoping.py#L211-L241), [`tickets/views.py:247-303`](../../backend/tickets/views.py#L247-L303) | OK | — | Closed by Sprint 28 Batch 10. Frontend editor still pending (separate dispatch). |
| 18 | Staff completion routing (default BM review vs direct customer) | Per-staff / per-building toggle for `IN_PROGRESS → WAITING_MANAGER_REVIEW` vs `→ WAITING_CUSTOMER_APPROVAL` | STAFF has zero entries in `ALLOWED_TRANSITIONS` — staff cannot drive transitions at all | [`tickets/state_machine.py:53-92`](../../backend/tickets/state_machine.py#L53-L92) | WRONG | **P1** | Substantial: new `WAITING_MANAGER_REVIEW` status, new STAFF transitions, per-(staff, building) routing flag |
| 19 | Frontend i18n on Extra Work | All user-visible strings via `t()` in both `en/` + `nl/` | Three EW pages have no `useTranslation` import; hard-coded English | [`frontend/src/pages/{Create,List,Detail}ExtraWork*Page.tsx`](../../frontend/src/pages/ExtraWorkListPage.tsx) | BROKEN | **P1** | Create `extra_work` namespace in both locales; thread `t()` through all three pages |
| 20 | `getApiError` raw HTML detection | Detect `<!DOCTYPE`/`<html` in response and downgrade to status fallback | Returns raw response string verbatim — Django 500 HTML pages render in the UI's error banner | [`frontend/src/api/client.ts:148`](../../frontend/src/api/client.ts#L148) | BROKEN | **P1** | ~5-line fix; add HTML-prefix detection |
| 21 | `AuditLog` typescript type carries Sprint 27F-B2 columns | `reason: string; actor_scope: Record<string, unknown>` | Type missing both fields | [`frontend/src/api/types.ts:481-492`](../../frontend/src/api/types.ts#L481-L492) | MISSING | P3 | Add the two fields when next touching this type |
| 22 | Sidebar "Extra Work" via `t()` | i18n'd label | Literal string | [`frontend/src/layout/AppShell.tsx:157`](../../frontend/src/layout/AppShell.tsx#L157) | BROKEN | P3 | One-line fix |
| 23 | STAFF protection on `/tickets/new` | STAFF blocked from creating tickets | `ProtectedRoute` admits STAFF | [`frontend/src/App.tsx:80-86`](../../frontend/src/App.tsx#L80-L86) | WRONG | P2 | Tighten the route guard or hide the "New ticket" sidebar item for STAFF |
| 24 | Dev DB migration drift | All committed migrations applied on dev DB | 4 migrations exist as files but unapplied on `cleaning_ticket_db` (the running dev container). Test DB auto-migrates per run; the 548-test baseline is correct. | `python manage.py showmigrations` output (validation agent §3) | OPERATIONAL | P2 | One-shot `docker exec cleaning_ticket_backend python manage.py migrate` |
| 25 | RBAC invariant H-4 doc attribution | Matrix attributes H-4 lock to "Sprint 27A T-7" but T-7 is the BSV.can_request_assignment audit test, not an H-4-specific test | Invariant H-4 is structurally guarded by the state machine (no STAFF entry anywhere in `ALLOWED_TRANSITIONS`); just lacks a dedicated test labelled "H-4" | [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md) §3 row 4 | OK with doc drift | P3 | Either rewrite the matrix row to cite the structural guard, or add an H-4-specific regression test |
| 26 | Backend follow-up: STAFF reaching `/api/tickets/<id>/assign/` | `TicketAssignSerializer.validate` must refuse STAFF actors | `is_staff_role` lets STAFF through the view layer (returns True for STAFF) — serializer not deeply audited. **Sprint 28 Batch 10**: widened the BM-assign gate for STAFF B3 with an explicit `BuildingStaffVisibility.visibility_level == BUILDING_READ_AND_ASSIGN` check (B1 / B2 STAFF still 403); serializer-side `TicketAssignSerializer.validate` audit remains open as a follow-up. | [`tickets/views.py:247-303`](../../backend/tickets/views.py#L247-L303) | PARTIAL | P2 | Sprint 28 Batch 10 closes the view-layer half; serializer-side audit still open as a follow-up. |
| 27 | `BACKEND-REQID-1` X-Request-Id middleware | Generate request id if upstream proxy didn't send one; echo to response | Only READS upstream header into `AuditLog.request_id` | [`backend/audit/context.py:78-92`](../../backend/audit/context.py#L78-L92) | PARTIAL | P2 | Backlog row open |
| 28 | `BACKEND-INDEXES-1` composite indexes | `(status, priority)`, `(company, status)`, `(building, status)` on Ticket | Not added | (migration absent) | MISSING | P2 | Backlog row open |
| 29 | `OPS-EMAIL-1` HTML email templates | HTML alt for password reset + status change | Plain-text only | `backend/notifications/services.py` | MISSING | P2 | Backlog row open |
| 30 | `OPS-NGINX-1` `client_max_body_size` headroom | Bump from 12M (barely above 10M attachment limit) to 20M | Still 12M | [`frontend/nginx.conf`](../../frontend/nginx.conf) | OPEN | P3 | Backlog row open |
| 31 | `FUTURE-SUBSCRIPTION-1` / `FUTURE-BANK-MATCHING-1` | Design docs (no code) | Not written | (no doc) | OPEN (intentional) | P3 | Backlog row open — design-only |

---

## 5. Role-by-role access matrix

What each role **should** be able to do per spec, vs what the code/UI actually
allows today. Columns: B = backend enforcement; F = frontend surface.

| Role | Should (spec) | Backend allows today | Frontend surfaces today | Status |
|---|---|---|---|---|
| **SUPER_ADMIN** | Everything globally | Universal-True branches in `permissions_v2.py` + scope helpers | Every admin route; every customer-detail page; audit logs | OK |
| **COMPANY_ADMIN (Provider)** | Manage own provider company scope (customers, buildings, building/customer assignments, provider users, building managers, staff, pricing, permissions, ticket + EW workflow). View-first UX. | `CompanyUserMembership`-anchored scope; full CRUD on Customers / Buildings / Users / Memberships; Sprint 27D `osius.*.manage` keys wired | All `/admin/*` routes; but **pages are editable-on-load** (spec §3 violation); pricing UI is missing (no Service catalog yet) | **PARTIAL — UX violation (P1) + pricing gap (P1)** |
| **BUILDING_MANAGER (Provider)** | See customers & contacts in assigned buildings (read-only). Manage operational work in assigned buildings (tickets, EW proposals, state transitions). Cannot change global provider settings. | Scope helper limits Tickets / EW to assigned buildings; manages BM-allowed state transitions; CAN drive `WAITING_CUSTOMER_APPROVAL → APPROVED/REJECTED` only as a workflow override (matrix H-5 isolates this); but `AdminRoute` blocks access to customer admin | **NO customer/contact read-only view at all.** The "BM sees customers in my buildings" surface does not exist. | **MISSING (P1)** |
| **STAFF (Provider)** | Login. Permissions per building. Per-building flavours: own-only / building-wide-read / building-wide-read-and-assign. Always sees own assigned work. Marks done with completion note + optional photo. Routes to BM review (default) OR direct to customer approval (configurable). Cost/margin notes hidden from STAFF. | `BuildingStaffVisibility` is binary; **per-building tri-state granularity does NOT exist**. `ALLOWED_TRANSITIONS` has zero STAFF entries — staff cannot drive ANY transition. No customer-vs-staff vs cost-note privacy strip. Cannot see Extra Work at all (G-B7). | No per-building granularity UI; flat `UserFormPage` staff section | **WRONG (P1)** for granularity + routing + completion + privacy |
| **CUSTOMER_COMPANY_ADMIN** | Manage own customer company users (Customer Location Manager / Customer User). Cannot promote to Customer Company Admin. Cannot grant permissions above own level. | H-6 + H-7 enforced via `CustomerUserBuildingAccessUpdateSerializer.validate_access_role` (Sprint 27A); self-edit guard (Sprint 27C); permission-key allow-list rejects `osius.*` | UI is the same as provider admin — no separate "customer-side admin" surface; permission-override editor (Sprint 27E) is correct | **OK at backend; missing customer-facing admin UI (P1)** |
| **CUSTOMER_LOCATION_MANAGER** | Building/location-scoped manager. Modular permissions per access row. | `access_role` enum value + per-row `permission_overrides` + policy DENY layer | Same UI surface as basic customer user; no location-manager-specific shaping | **OK at backend; flat at frontend (P2)** |
| **CUSTOMER_USER** | Basic customer-side user. Create / view / approve per granted scope. Can view their own contracted Extra Work prices. Can submit cart for contract-priced services (instant ticket) or proposals (custom). | Backend ticket scope works correctly. EW: scope returns own customer's requests; no cart / catalog / pricing visibility (those models don't exist). | Can create EW request (single-line form); approve/reject tickets they own; view dashboard tickets. No cart UI, no proposal viewer, no pricing visibility. | **OK on existing surface; missing cart/proposal UX (P0 by dependency)** |
| **Contact** | Not a login. Communication record only. Visible in customer detail + contextually in ticket/EW screens. | Does not exist as an entity. | Does not exist as a UI. | **MISSING (P0)** |

### Cross-role security floor (RBAC invariants H-1 through H-11)

All 11 invariants verified by the backend audit agent — enforcement and test
references match the matrix doc. One minor doc drift: H-4 attribution in
matrix §3 row 4 cites Sprint 27A T-7, but T-7 (per matrix §9 table) is the
`BuildingStaffVisibility.can_request_assignment` audit test, not an
H-4-specific test. The invariant itself is structurally guarded (state
machine never lets STAFF approve), just unlabelled.

---

## 6. Extra Work workflow audit

The Extra Work domain is the **single largest divergence from the spec.** Per
the 2026-05-15 meeting (§4), the customer composes a request as a **cart of
N line items**, each selecting a catalog service with its own quantity +
requested_date. The request then branches: contract-priced lines go through
the instant-ticket path; custom-priced lines go through the proposal builder.

### Contract fixed-service / shopping-cart path (spec §4.1) — MISSING

| Required | Current |
|---|---|
| Customer browses **service categories** in a catalog | No `Service` / `ServiceCategory` model. No catalog API. No catalog UI. |
| Customer adds N services to a cart, each with own `quantity`, `requested_date`, `customer_note` | `ExtraWorkRequest` is single-line: one `title` + one `description` + one `preferred_date` + one `category` enum. No line-item table. |
| Submission creates one parent + N children | Single request, no children. |
| Pricing resolves to customer-specific contract price | No `CustomerServicePrice` model exists. No `resolve_price()` resolver. |
| Approved cart auto-spawns one Ticket per line, atomically | `apply_transition` does not create Tickets. |

### Custom request / proposal path (spec §4.2) — PARTIAL (wrong shape)

| Required | Current |
|---|---|
| Customer requests a custom service | Customer can create a single-line request with `category=OTHER` (`ExtraWorkRequest.category_other_text`) |
| Provider builds a proposal | Provider builds N `ExtraWorkPricingLineItem` rows on the existing request (`extra_work/models.py:269-336`) — but these are pricing lines on the request itself, NOT a separate proposal artifact |
| Each proposal line: service / qty / unit type / unit price / VAT / customer-visible explanation / internal note | All fields exist on `ExtraWorkPricingLineItem`: `unit_type` (5 values: `HOURS`/`SQUARE_METERS`/`FIXED`/`ITEM`/`OTHER`), `quantity`, `unit_price`, `vat_rate`, `customer_visible_note`, `internal_cost_note`. **Naming differs from spec**: spec says `customer_explanation` + `internal_note`; code uses `customer_visible_note` + `internal_cost_note`. |
| Customer approves or rejects | EW state machine has `CUSTOMER_APPROVED`/`CUSTOMER_REJECTED` transitions (`extra_work/state_machine.py:42-53`) |
| Provider admin can override with mandatory reason | Yes — `extra_work/state_machine.py:250-265` mirror of ticket override; `override_by/_reason/_at` on `ExtraWorkRequest` + `is_override` on `ExtraWorkStatusHistory` |
| Approved proposal auto-spawns Ticket(s) | **Not implemented.** `apply_transition` on `CUSTOMER_APPROVED` only stamps timestamps + override fields. |
| Proposal timeline events | Only status-history rows; no separate `ProposalTimelineEvent` |
| Proposal PDF export | Not implemented. `fpdf2` is in `requirements.txt`. |

### Mixed-cart separation (spec §4 hard rule)

The spec says if a single cart line lacks an agreed price, the WHOLE cart
routes to the proposal flow. This is a per-request branching decision, not
per-line. Today there is no concept of a cart at all, so the branching
question is moot — but when the cart lands, this rule must be encoded as a
property on `ExtraWorkRequest.routing_decision` (or similar).

### Proposal approval → ticket conversion (spec §8) — MISSING

Per spec §8: approval of a proposal must spawn one execution Ticket per
approved line, anchored to the parent request, inside the same
`transaction.atomic()` as the approval transition. **Not implemented.**

### Customer / provider / staff visibility on EW

| Visibility | Customer | Provider non-STAFF | STAFF |
|---|---|---|---|
| Can read EW requests | own customer's requests (resolved via `scope_extra_work_for`) | all in scope per-role | **NONE** (`extra_work/scoping.py:67-71` returns `.none()` — gap G-B7) |
| Sees `manager_note` + `internal_cost_note` on pricing lines | NO (`_PROVIDER_ONLY_FIELDS` strip at `extra_work/serializers.py:238-265`) | YES | YES (when G-B7 opens — but spec §6 says STAFF should NOT see cost/margin) — **P1 follow-up** |
| Sees `customer_visible_note` / `pricing_note` / `customer_visible_note` line field | YES | YES | YES (when G-B7 opens) |

### Override reason / audit on EW

- `ExtraWorkStatusHistory.is_override` (line 374) — present.
- `ExtraWorkRequest.override_by/override_reason/override_at` (lines 202-212)
  — present (the "request-row triple" the matrix doc cites as the difference
  from tickets).
- Provider-driven coercion + `override_reason_required` 400 contract — present
  at [`extra_work/state_machine.py:250-265`](../../backend/extra_work/state_machine.py#L250-L265).
- **OK** for the existing single-line request entity. **Will need re-shaping
  when proposal becomes a first-class entity (P1)**.

---

## 7. Frontend UX audit

### View-first / closed-door violations (spec §3)

The Sprint 27E permission-override editor on `CustomerFormPage` is the
**only** correctly view-first surface. Every other admin detail page renders
an editable form on first load:

| Page | Violation | Lines |
|---|---|---|
| `CustomerFormPage` | Parent customer record (name / email / language / visibility flags) is editable on first load. Only the per-access permission overrides editor (Sprint 27E) is view-first. | [`frontend/src/pages/admin/CustomerFormPage.tsx:823-1071`](../../frontend/src/pages/admin/CustomerFormPage.tsx#L823-L1071) |
| `BuildingFormPage` | Single editable form on first load. Managers section inline add/remove. | [`frontend/src/pages/admin/BuildingFormPage.tsx:279-411`](../../frontend/src/pages/admin/BuildingFormPage.tsx#L279-L411) |
| `CompanyFormPage` | Single editable form on first load. Admins section inline add/remove. | [`frontend/src/pages/admin/CompanyFormPage.tsx`](../../frontend/src/pages/admin/CompanyFormPage.tsx) |
| `UserFormPage` | Single editable form. STAFF profile + visibility sub-section inline. | [`frontend/src/pages/admin/UserFormPage.tsx:705-1010`](../../frontend/src/pages/admin/UserFormPage.tsx#L705-L1010) |
| `TicketDetailPage` | Status buttons + messages composer + attachment uploader + staff-assign dropdown all live in-page and fire mutations directly. Override modal is correct. | [`frontend/src/pages/TicketDetailPage.tsx`](../../frontend/src/pages/TicketDetailPage.tsx) |
| `ExtraWorkDetailPage` | Status transition buttons inline; pricing-line-item form inline; override block inline (not a modal). | [`frontend/src/pages/ExtraWorkDetailPage.tsx`](../../frontend/src/pages/ExtraWorkDetailPage.tsx) |

A grep for `isEditing` / `editMode` over `frontend/src/pages` returns zero
hits outside the CustomerFormPage override editor. The view-first concept is
not in the codebase's vocabulary today.

### Sidebar hierarchy (spec §3)

Single static, flat sidebar at [`frontend/src/layout/AppShell.tsx:138-242`](../../frontend/src/layout/AppShell.tsx#L138-L242).
Selecting a customer at `/admin/customers/<id>` does NOT switch the sidebar
shape — it just navigates to the giant `CustomerFormPage`. No URL-encoded
submenu state. No Back action.

This is the single most impactful frontend gap, because the rest of the
view-first refactor needs the submenu as the structural anchor for sub-views
(Buildings / Users / Permissions / Extra Work / Contacts / Settings).

### Customer/provider terminology confusion

The frontend has **no separate customer-side route prefix**. `CUSTOMER_USER`
lands on the same `/`, `/tickets/:id`, `/extra-work/*` as provider users; the
SPA differentiates via component-internal `me.role` checks (only on
TicketDetailPage and ExtraWorkDetailPage). This works today because backend
scope helpers filter the data, but the UX is identical regardless of role:

- `DashboardPage` renders the same shape for every role (zero `me.role`
  checks inside the page).
- The sidebar shows different items per role, but the routes themselves
  don't separate customer from provider.

### Data-dump pages

- `CustomerFormPage` is 1784 lines on one route — everything (visibility
  flags, contacts-that-don't-exist-yet, users, buildings, access rows,
  permission overrides, company policy) crammed onto a single page.
- `UserFormPage` is 1091 lines (user record + STAFF profile + visibility
  rows).
- `TicketDetailPage` is 2159 lines (header + status + messages + attachments
  + staff assignments + override modal + history timeline).

Decomposition depends on the sidebar refactor (§3) landing first.

### Customer-side Extra Work access

Customer can reach `/extra-work` and create a single-line request. **The
shopping-cart / catalog / pricing UI does not exist.** When the catalog +
cart backend models land, the customer-side EW surface needs a full rewrite.

### Raw HTML error symptom

[`frontend/src/api/client.ts:148`](../../frontend/src/api/client.ts#L148):

```ts
if (typeof data === "string" && data.trim().length > 0) return data;
```

If the backend returns a Django HTML 500 page, axios receives the body as a
string, and `getApiError` returns the whole HTML verbatim. The page's error
banner then renders it. **This matches the "raw HTML in browser" symptom
the owner reports.** Fix: detect `<!DOCTYPE` / `<html` prefix and downgrade
to the status fallback. ~5-line change.

### Missing modals / tabs / pagination

Every admin page that lists rows (CustomersAdminPage, UsersAdminPage,
InvitationsAdminPage, etc.) renders a flat table without search /
pagination beyond the backend's default page size. The "no data dumps"
rule (spec §3) is violated at the list level too — once a tenant has 30+
buildings or users, navigation degrades. Not a P0 today (data volume is
demo-scale) but a P1 for the pilot.

### Override modal consistency

- Ticket override (Sprint 27F-F1): correct modal, mandatory reason, two-press
  confirmation, full i18n in both EN/NL bundles.
- EW override: inline block at `ExtraWorkDetailPage:774-876`. Works
  functionally but uses no `useTranslation` (hard-coded English), is not
  modal-shaped, and the timeline override badge is absent (the
  `status-history` endpoint exists but is never called from the page —
  dead-code path in `frontend/src/api/extraWork.ts:113`).
- Proposal override: doesn't exist (proposal entity missing).

---

## 8. Backend security / scope audit

### URL / route protection

All 60+ routes inventoried by the backend audit agent. Every write surface
has either an explicit DRF permission class or a route-guard role check.
Anonymous-allowed routes are intentional (password reset, invitation
preview/accept, health probes).

Three routes flagged for follow-up:

1. **`POST /api/tickets/<id>/assign/`** — gates via `is_staff_role(request.user)`
   which returns True for STAFF. The serializer (`TicketAssignSerializer`)
   is the actual gate, but the backend agent didn't fully audit it. **Action:
   confirm `TicketAssignSerializer.validate` refuses STAFF actors.**
2. **`POST /api/auth/password/change/`** — declares `permission_classes = []`
   ([`backend/accounts/views.py:144`](../../backend/accounts/views.py#L144))
   and relies on the global JWT authentication class to gate. Acceptable if
   `DEFAULT_AUTHENTICATION_CLASSES` enforces auth (likely yes via `settings.py`).
   **Action: verify by reading the settings + running an anonymous POST in
   a sanity test.**
3. **`/api/tickets/<id>/staff-assignments/`** (Sprint 25A) — gating lives in
   the `_gate_actor` helper, not deeply audited. The matrix's Sprint 25A
   test footprint suggests it's correct, but worth a fresh read for the
   Sprint 28 staff-permission re-shape.

### Attachment access

[`tickets/views.py:493-525`](../../backend/tickets/views.py#L493-L525) —
`TicketAttachmentDownloadView`:
- Scope re-check on the parent ticket (line 499).
- Hidden-flag re-check on the attachment (line 515).
- Inherited hidden via parent `TicketMessage.is_hidden` or
  `message_type=INTERNAL_NOTE` (lines 508-514).
- 404 for absent file.

Locked by `tickets/tests/test_sprint26a_scope_safety_net.py` per matrix H-2.
**OK.**

### Scoped querysets

`scope_companies_for / scope_buildings_for / scope_customers_for /
scope_tickets_for / scope_extra_work_for` all key off the role and the
membership tables. `is_active=True` filter for non-SUPER_ADMIN paths shipped
in CHANGE-6 (per `accounts/scoping.py:127-152`). **OK.**

### Customer/provider role separation

The five-value `UserRole` enum is the single source of truth. Provider keys
(`osius.*`) and customer keys (`customer.*`) are in disjoint namespaces with
disjoint resolvers. Cross-namespace contamination is blocked by:
- The `validate_permission_overrides` allow-list (Sprint 27C) refuses
  `osius.*` keys on customer override write.
- The frontend typed `CUSTOMER_PERMISSION_KEYS` constant prevents the UI
  from ever offering provider keys.

**OK.**

### Generic AuditLog vs workflow-history rules (H-11)

The matrix H-11 invariant is honoured: permission/role/scope changes write
to the generic `AuditLog` via signals; workflow overrides write to
`*StatusHistory` rows with `is_override` + `override_reason`. The two are
never double-written. The Sprint 27F-B2 `AuditLog.reason` + `actor_scope`
columns supplement permission audit, not workflow audit.

The audit signal coverage (lines 520-630 of `audit/signals.py`) matches the
matrix exactly. No drift. **OK.**

---

## 9. Recommended implementation sequence

Strict order. Each batch is small enough to ship in one sprint letter and
defends one or two of the matrix invariants explicitly. Do NOT start a batch
before the previous one lands.

### Batch 1 — Operational health fixes (1 day, no schema)

| Item | Files | Tests | Why first |
|---|---|---|---|
| Run dev DB migrations | (operational; just `python manage.py migrate`) | n/a | Migration drift makes any local dev/demo flaky. Zero risk; schema migrations are already audit-locked. |
| `getApiError` raw-HTML detection | `frontend/src/api/client.ts:148` | extend an existing client test or add a unit test | The "raw HTML in browser" symptom is in this 5-line function. Once fixed, error pages no longer leak Django debug HTML. |
| Add `reason` + `actor_scope` to `AuditLog` TS type | `frontend/src/api/types.ts:481-492` | typecheck only | Keep the typed contract in lockstep with backend after Sprint 27F-B2. |
| Sidebar "Extra Work" via `t()` | `frontend/src/layout/AppShell.tsx:157` + both i18n bundles | typecheck | One-line correctness fix. |

### Batch 2 — Confirm the mild backend risk (½ day, no schema)

| Item | Files | Tests | Why next |
|---|---|---|---|
| Read `TicketAssignSerializer.validate` | `backend/tickets/serializers.py` | If serializer doesn't refuse STAFF, add a regression test that POSTs to `/api/tickets/<id>/assign/` as STAFF and asserts 400/403 | Confirms whether there's a real assignment-bypass risk or whether the existing gates are sufficient. |
| Doc: H-4 attribution | `docs/architecture/sprint-27-rbac-matrix.md` §3 row 4 | n/a | Either rewrite the matrix row to cite the structural guard (no STAFF entries in ALLOWED_TRANSITIONS) or land an H-4-specific test. |

### Batch 3 — Sidebar refactor (1 sprint letter, frontend only, no schema)

| Item | Files | Tests | Why next |
|---|---|---|---|
| Sidebar mode = `top-level` \| `customer-scoped` | `frontend/src/layout/AppShell.tsx` | Playwright spec asserting submenu state shows on `/admin/customers/<id>` and Back returns to top-level | This is the **structural anchor** for every subsequent view-first refactor. Without it, the admin pages can't decompose. |
| URL-encoded submenu state | `frontend/src/App.tsx` route table; `<Routes>` adds nested `<Route path="/admin/customers/:id/*">` | Playwright deep-link spec | Browser-back must behave predictably. |

### Batch 4 — Contact model + UI (1 sprint letter, joint backend + frontend)

| Item | Files | Tests | Why next |
|---|---|---|---|
| `Contact` model | `backend/customers/models.py` (or new `contacts/` app) + migration | `customers/tests/test_sprint28_contacts.py` | Unblocks the Building Manager read-only view AND the Customer Contacts panel. |
| `Contact` admin CRUD viewset + URL | `backend/customers/views_contacts.py` (or similar) + URL routing | API tests for scope + audit signals | — |
| `Contact` audit signal registration | `backend/audit/signals.py` | audit-row test | H-10 invariant continuation. |
| Frontend Contact types | `frontend/src/api/types.ts` | typecheck | — |
| Customer-scoped "Contacts" sub-page | `frontend/src/pages/admin/CustomerContactsPage.tsx` (new), nested under `/admin/customers/:id/contacts` | Playwright spec | Plugs into the Batch 3 sidebar submenu. |

### Batch 5 — Service catalog + pricing (1 sprint letter, backend-heavy)

| Item | Files | Tests | Why next |
|---|---|---|---|
| `Service`, `ServiceCategory` models | `backend/extra_work/models.py` (or new `catalog/` app) + migration | `extra_work/tests/test_sprint28a_service_catalog.py` | Prerequisite for cart + proposal. |
| `CustomerServicePrice` model + `resolve_price()` resolver | `backend/extra_work/pricing.py` | `extra_work/tests/test_sprint28a_pricing_resolver.py` | The "customer-specific contract price beats global default" rule needs the resolver. |
| Audit signal registration | `backend/audit/signals.py` | audit-row test | H-10. |
| Admin CRUD UI | `frontend/src/pages/admin/CatalogAdminPage.tsx` + `PricingAdminPage.tsx` | Playwright | Owner can manage prices through UI (spec §G). |

### Batch 6 — Cart-shaped Extra Work request (1 sprint letter)

| Item | Files | Tests | Why next |
|---|---|---|---|
| Reshape `ExtraWorkRequest`: introduce `ExtraWorkRequestItem` line items with per-line `service`, `quantity`, `requested_date`, `customer_note` | `backend/extra_work/models.py` + migration (with a data backfill for existing single-line requests) | `extra_work/tests/test_sprint28b_cart_request.py` | Foundation for §4 flow. |
| Reshape API + serializers | `backend/extra_work/views.py`, `serializers.py` | Smoke + scope tests | — |
| Frontend cart UI | Replace `CreateExtraWorkPage.tsx` with a cart-shaped page | Playwright | — |
| i18n: new `extra_work` namespace in both `en/` + `nl/` | `frontend/src/i18n/{en,nl}/extra_work.json` | typecheck | First time the EW surface gets i18n at all. |

### Batch 7 — Instant-ticket path (1 sprint letter, depends on Batch 5 + 6)

| Item | Files | Tests | Why next |
|---|---|---|---|
| Branching logic: if every cart line has a `resolve_price()` hit AND price is customer-contract-anchored, route to instant ticket | `backend/extra_work/state_machine.py` | `extra_work/tests/test_sprint28b_instant_ticket_path.py` | spec §4.1 |
| Auto-spawn Tickets atomically (one Ticket per line, anchored to parent request) | `backend/extra_work/services.py` (new module for the spawn) | atomic test (rollback test) | — |

### Batch 8 — Proposal builder (1 sprint letter, depends on Batch 5 + 6)

| Item | Files | Tests | Why next |
|---|---|---|---|
| `Proposal` + `ProposalLine` models with `customer_explanation` / `internal_note` per spec naming | `backend/extra_work/models.py` + migration | `extra_work/tests/test_sprint28c_proposal_builder.py` | spec §6 |
| Customer-facing vs admin-facing serializers (dual-note privacy port from `ExtraWorkPricingLineItem` pattern) | `backend/extra_work/serializers.py` | `test_sprint28c_dual_note_isolation.py` (assert `internal_note` absent from CUSTOMER_USER JSON) | EXTRA-NOTES-1 |
| `ExtraWorkProposalTimelineEvent` model | `backend/extra_work/models.py` + migration | `test_sprint28c_timeline_events.py` | EXTRA-TIMELINE-1 |
| Proposal approval override (mirror Sprint 27F-B1 shape: `is_override` + `override_reason` on proposal status history) | `backend/extra_work/state_machine.py` | `test_sprint28c_proposal_override.py` | EXTRA-OVERRIDE-1 |
| Auto-spawn Tickets on proposal approval (atomic) | `backend/extra_work/services.py` | atomic test | spec §8 |

### Batch 9 — Extra Work dashboard + stats (½ sprint letter)

| Item | Files | Tests | Why next |
|---|---|---|---|
| `/api/extra-work/stats/` + `/api/extra-work/stats/by-building/` actions | `backend/extra_work/views.py` | `extra_work/tests/test_sprint28d_stats.py` | spec §J |
| Dashboard cards: Tickets + Extra Work side by side | `frontend/src/pages/DashboardPage.tsx` | Playwright | — |
| Role-aware dashboard shape | same | Playwright | spec §J |

### Batch 10 — Staff per-building granularity (1 sprint letter)

| Item | Files | Tests | Why next |
|---|---|---|---|
| Add per-row visibility level to `BuildingStaffVisibility` | `backend/buildings/models.py` + migration | `buildings/tests/test_sprint28e_staff_visibility_level.py` | spec §B.4 |
| New `osius.staff.view_building_tickets` + `osius.staff.assign_tickets` permission keys (Sprint 27D infrastructure already supports adding keys) | `backend/accounts/permissions_v2.py` | parity test | — |
| Frontend UI: per-building visibility selector on `UserFormPage` STAFF section | `frontend/src/pages/admin/UserFormPage.tsx` | Playwright | — |

### Batch 11 — Staff completion routing (1 sprint letter)

| Item | Files | Tests | Why next |
|---|---|---|---|
| New `WAITING_MANAGER_REVIEW` ticket status | `backend/tickets/models.py` + migration + state machine | tests for the new transition + back-routing | spec §B.4 (default routing) |
| Per-(staff, building) routing flag on `BuildingStaffVisibility` (or per-StaffProfile) | `backend/buildings/models.py` or `backend/accounts/models.py` + migration | tests | — |
| Frontend completion modal for STAFF: completion note + optional attachment + routing-aware destination text | `frontend/src/pages/TicketDetailPage.tsx` | Playwright | — |

### Batch 12 — Building Manager read-only customer/contact view (½ sprint letter, depends on Batch 4 + 3)

| Item | Files | Tests | Why next |
|---|---|---|---|
| New `BUILDING_MANAGER`-accessible read-only routes for customer detail + contacts panel in assigned buildings | `frontend/src/App.tsx` route table + new pages | Playwright | spec §B.3 |
| Reuse existing scope helpers — no new backend gates needed | — | — | Backend already scopes via `building_ids_for(user)` |

### Batch 13 — View-first refactor of remaining admin pages (1-2 sprint letters)

| Item | Files | Tests | Why next |
|---|---|---|---|
| Decompose `CustomerFormPage` into the customer-scoped sub-pages (Buildings, Users, Permissions, Extra Work, Contacts, Settings) under `/admin/customers/:id/*` routes | `frontend/src/pages/admin/CustomerFormPage.tsx` (delete or trim drastically); new per-sub-page components | Playwright per sub-route | Depends on Batch 3 sidebar landing. Resolves §3 violations 4 and 5. |
| Convert `BuildingFormPage`, `CompanyFormPage`, `UserFormPage` parent records to view-first (read-only summary card → "Edit" button → modal) | same files | Playwright | spec §3 |
| Same on `TicketDetailPage` for the message/status/attachment surfaces | `frontend/src/pages/TicketDetailPage.tsx` | Playwright | — |

### Batch 14 — Proposal PDF + future-architecture design docs (½ sprint letter)

| Item | Files | Why last |
|---|---|---|
| Proposal PDF via `fpdf2` | `backend/extra_work/pdf.py` (new) | EXTRA-PDF-1 — nice-to-have, depends on Batch 8 |
| `docs/architecture/future-subscription-architecture.md` | new doc | FUTURE-SUBSCRIPTION-1 design parking |
| `docs/architecture/future-bank-matching-architecture.md` | new doc | FUTURE-BANK-MATCHING-1 design parking |

---

## 10. Open questions

The audit defaults to the spec for everything where a reasonable default
exists. The following are the only genuinely blocking questions that need
stakeholder input before the corresponding batch can start.

1. **Field naming for proposal lines (Batch 8).** Spec §6 uses
   `customer_explanation` + `internal_note`. The existing
   `ExtraWorkPricingLineItem` uses `customer_visible_note` +
   `internal_cost_note`. When the Proposal model lands, do we **(a)** match
   the spec's naming verbatim (preferred for new code), or **(b)** keep the
   existing names for consistency with the legacy pricing-item rows? The
   audit defaults to (a) and treats the existing line-item model as a
   different concept (single-line request pricing) than the new Proposal
   model (cart-shaped request proposal lines).

2. **Staff completion routing default (Batch 11).** When STAFF marks a
   ticket done with the new `WAITING_MANAGER_REVIEW` flow, what's the BM's
   review obligation? Does the BM transition `WAITING_MANAGER_REVIEW →
   IN_PROGRESS` (rejected), `→ WAITING_CUSTOMER_APPROVAL` (forward to
   customer), or `→ APPROVED` (skip customer)? The audit defaults to the
   first two — `WAITING_MANAGER_REVIEW → WAITING_CUSTOMER_APPROVAL` for
   acceptance, `→ IN_PROGRESS` for rejection. Skip-customer is **not**
   defaulted; it's a workflow override that the spec §7 already constrains.

3. **Cart line `customer_note` vs request-level `customer_note` (Batch 6).**
   Spec §4 puts a `customer_note` on each cart line. The existing
   `ExtraWorkRequest.description` is a free-text field on the request
   itself. Do we **(a)** keep both (line note + request-level description)
   or **(b)** drop the request-level description in favour of per-line
   notes? The audit defaults to (a) — keep both, semantically the
   request-level description is "why I'm submitting this cart" and each
   line carries its own context.

Everything else is decided by the spec or by reasonable default.

---

## Appendix A — terminal output (final)

```
$ git status --short
(empty — working tree clean)

$ git diff --stat
(empty — working tree clean)

$ grep -RnE "Ticket equivalent missing|nl\.json|_TICKET_STATUS_HISTORY_TRACKED_FIELDS" CLAUDE.md .claude/agents docs/architecture docs/product docs/backlog
.claude/agents/backend-engineer.md:56:  `_TICKET_STATUS_HISTORY_TRACKED_FIELDS`. Adding one would double-write
.claude/agents/project-manager.md:100:`_TICKET_STATUS_HISTORY_TRACKED_FIELDS`, and there must not be one
```

Both matches are in **negative explanatory context** (telling future agents
what NOT to do — see audit §4 row "Stale wording sweep"). No stale wording
remains.

---

## Appendix B — Audit sources

This audit was assembled from three parallel sub-agent reports:

- **Backend deep-dive** (66 tool calls): app-by-app model inventory + RBAC
  invariant verification + URL audit + attachment access check + audit
  signal coverage check + Sprint 27F-B1 / B2 verification.
- **Frontend deep-dive** (86 tool calls): route table + sidebar audit +
  view-first audit + Extra Work UI audit + i18n parity check + endpoint
  inventory.
- **Validation runner** (10 tool calls): docker compose ps, `manage.py
  check`, `showmigrations`, `makemigrations --dry-run --check`, `npm run
  typecheck`, `npm run lint`, `npm run build`, final `git status` + grep
  sweep.

All three agents operated read-only. The Django test suite was not re-run
in this audit pass (548-test baseline last validated on commit `be7b3e4`).

**Audit doc owner:** PM. Next refresh: after Batch 1 lands, OR after any
Sprint 28 row from the backlog closes, whichever is sooner.
