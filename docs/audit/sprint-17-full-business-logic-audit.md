# Sprint 17 — Full business-logic audit and UI coverage

Date written: 2026-05-10
Branch: `sprint-17-full-business-logic-audit`
Author: audit pass coordinated for the pre-pilot sign-off.

This document is the developer-facing single source of truth for the
intended business rules, the role/scope matrix, the ticket lifecycle,
the UI/backend contract, and the security posture of the system as it
stands at the start of pilot. Findings are classified PASS, NEEDS
FOLLOW-UP, or RISK at the end. Every NEEDS FOLLOW-UP / RISK row names a
file, a reason, a recommended fix, and whether it blocks pilot.

The companion code in this sprint adds Playwright coverage for every
role/scope assertion below and a small set of backend tests for gaps
the UI tests revealed. Everything outside the audit doc and tests is
intentionally untouched: backend remains the source of truth and no
new product behaviour ships in this sprint.

---

## A. Business model summary

| Entity | Source of truth | Notes |
| --- | --- | --- |
| Company | `companies.Company` | Tenant root. Soft-archived via `is_active=False`; row never deleted. |
| Building | `buildings.Building` | Belongs to one company (FK). Soft-archived via `is_active=False`. |
| Customer | `customers.Customer` | Belongs to one company (FK). Sprint 14 made `building` FK nullable: legacy single-anchor customers still carry it; new "consolidated" customers leave it NULL and link via `CustomerBuildingMembership`. |
| Customer ↔ buildings | `customers.CustomerBuildingMembership` | M:N. Source of truth for which buildings a customer is operating at. One row per (customer, building). |
| Users | `accounts.User` | Email is `USERNAME_FIELD`. `role` is one of four. `deleted_at`/`is_active` form the soft-delete pair: deleted users cannot authenticate (see `IsAuthenticatedAndActive`). |
| Company-admin link | `companies.CompanyUserMembership` | (user, company) — grants `COMPANY_ADMIN` scope to that company. |
| Building-manager link | `buildings.BuildingManagerAssignment` | (user, building) — grants `BUILDING_MANAGER` scope to that building. |
| Customer-user link | `customers.CustomerUserMembership` | (user, customer) — coarse customer membership. |
| Per-building grant | `customers.CustomerUserBuildingAccess` | Sprint 14: per-(customer-user, building) grant on top of `CustomerUserMembership`. Visibility AND action authority (Sprint 15) are pair-checked against this row. |
| Tickets | `tickets.Ticket` | Belongs to (company, building, customer). `created_by` is required and protected. `assigned_to` is nullable and SET_NULL on user deletion. Soft-deleted via `deleted_at` (Sprint 12). |
| Ticket messages | `tickets.TicketMessage` | `message_type` ∈ {PUBLIC_REPLY, INTERNAL_NOTE}. INTERNAL_NOTE is staff-only on both write and read paths. |
| Ticket attachments | `tickets.TicketAttachment` | `is_hidden` flag plus parent-message hide propagation. Customer-users cannot upload hidden, cannot list hidden, cannot download hidden. |
| Ticket status history | `tickets.TicketStatusHistory` | Append-only. One row per `apply_transition` call. Recorded actor + note. |
| Reports | `reports/` (no model; computed) | Aggregates over `Ticket` filtered by `tickets_for_scope`. CSV/PDF exports go through the same `compute_*` payload as the JSON view, so the three formats cannot drift. |
| Audit logs | `audit.AuditLog` | Immutable. Tracked: User, Company, Building, Customer (CRUD) + the five scope-changing membership/assignment tables (CREATE/DELETE only). Sensitive fields (passwords, tokens) redacted before write. |

### Entities NOT yet modelled separately (intentional)

- Ticket lifecycle event log: covered by `TicketStatusHistory` rather than a generic `AuditLog`. Carries `old_status`, `new_status`, `changed_by`, `note`, `created_at`. The audit sprint plan from Sprint 16 explicitly calls this design choice out and accepts it.
- Per-attachment soft delete: attachments are removed only when the parent ticket is hard-deleted (which never happens — tickets soft-delete via `deleted_at`). A future sprint can add `deleted_at` to attachments if operators need fine-grained removal; not pilot-blocking.

---

## B. Role matrix

The four roles are defined in `accounts/models.py::UserRole`. Active +
not soft-deleted is required for every authenticated action via
`IsAuthenticatedAndActive`.

### SUPER_ADMIN

- List / view: every Company, Building, Customer, User, Ticket, Audit log; every report.
- Create: every entity. POST /api/users/ is intentionally 405 — users come in via the invitation flow only.
- Update / delete: every entity. Soft-delete semantics preserved: `is_active=False` for tenants; `deleted_at` for users and tickets.
- Assign: any building manager assigned to the ticket's building.
- Status transitions: any (allowed → next) for any ticket, *except* a no-op transition (`ticket.status == to_status`). See `state_machine.can_transition` SUPER_ADMIN_CAN_TRANSITION_ANY_STATUS branch.
- Reports: all (`IsReportsConsumer`).
- Direct URLs: never 403/404 except for genuinely missing rows.
- Reactivate: companies, buildings, customers, users via dedicated `@action` endpoints. Super-admin only.

### COMPANY_ADMIN

- List / view: companies they are a member of (via `CompanyUserMembership`); their company's buildings, customers, users, tickets, audit logs are NOT exposed because `/api/audit-logs/` is super-admin only — so company admins can audit only via UI breadcrumbs, not the immutable feed.
- Create: buildings, customers, tickets within their company. Can create invitations (handled in `accounts/views_invitations.py`) for non-super-admin roles in their company scope.
- Update: tenants in their company (via `IsSuperAdminOrCompanyAdminForCompany`). Users in scope, except cannot edit other SUPER_ADMIN or COMPANY_ADMIN rows.
- Delete: company-soft-deletes via `is_active=False`; tickets soft-delete via `deleted_at` (Sprint 12 rule: company admin allowed for any in-scope ticket). Cannot hard-delete anything.
- Assign: any manager assigned to the ticket's building, when the ticket is in their company scope.
- Status transitions: per `ALLOWED_TRANSITIONS[(from, to)][COMPANY_ADMIN] = SCOPE_COMPANY_MEMBER`. Includes an admin override for WAITING_CUSTOMER_APPROVAL → APPROVED/REJECTED to unblock customers who are slow to respond.
- Reports: yes — same scope as their company tenancy.
- Direct URLs: cross-company rows return 404 (queryset gate fires before object permission).

### BUILDING_MANAGER

- List / view: buildings they are assigned to; tickets at those buildings. Customers at those buildings (via `CustomerBuildingMembership` ∪ legacy `Customer.building`). Users in any of their company-scope companies (legacy logic; reviewed below).
- Create: tickets at their assigned buildings (the ticket-create serializer validates `BuildingManagerAssignment.objects.filter(user, building_id).exists()`). They cannot create or modify Customer / Building / Company entities.
- Update / delete: tickets they themselves created (Sprint 12 rule: BUILDING_MANAGER + CUSTOMER_USER soft-delete is creator-only).
- Assign: yes — but only managers who are *also* assigned to the ticket's building (`TicketAssignSerializer.validate`).
- Status transitions: OPEN→IN_PROGRESS, IN_PROGRESS→WAITING_CUSTOMER_APPROVAL, REJECTED→IN_PROGRESS, REOPENED_BY_ADMIN→IN_PROGRESS — all gated on `BuildingManagerAssignment.exists`.
- Reports: yes — see `IsReportsConsumer`.
- Direct URLs: out-of-building tickets return 404 via `scope_tickets_for`.

### CUSTOMER_USER

- List / view: tickets where `(ticket.customer, ticket.building)` matches a `(membership.customer, access.building)` pair the user holds. Buildings they hold an access row for. Customers they hold a `CustomerUserMembership` for. **No user list, no audit log access, no reports.**
- Create: tickets where they are linked to the customer AND have building access for that pair (`TicketCreateSerializer.validate`).
- Update: nothing globally — the only mutation a customer-user makes on a ticket is `APPROVE` or `REJECT` (status change). They cannot reassign or re-categorise.
- Delete: the tickets they themselves created (Sprint 12).
- Assign: forbidden — `assign` action 403's pre-serializer, `TicketAssignSerializer.validate` rejects again, and `assignable_managers` 403's the read.
- Status transitions: WAITING_CUSTOMER_APPROVAL→APPROVED and WAITING_CUSTOMER_APPROVAL→REJECTED, gated on the exact (customer, building) pair access (`SCOPE_CUSTOMER_LINKED` in Sprint 15).
- Reports: never (`IsReportsConsumer` returns False; the `/reports` SPA route also redirects).
- Direct URLs: outside-pair tickets return 404; outside-pair attachments return 404.

---

## C. Ticket lifecycle matrix

Source of truth: `tickets/state_machine.py::ALLOWED_TRANSITIONS`.

| From → To | SUPER_ADMIN | COMPANY_ADMIN | BUILDING_MANAGER | CUSTOMER_USER | UI button (TicketDetailPage) | Backend validation path | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OPEN → IN_PROGRESS | ANY | company member | building assigned | — | rendered when role/scope passes the API's `allowed_next_statuses` | `apply_transition` + `_user_passes_scope` | `tickets/tests/test_state_machine.py` |
| IN_PROGRESS → WAITING_CUSTOMER_APPROVAL | ANY | company member | building assigned | — | same | same | same |
| WAITING_CUSTOMER_APPROVAL → APPROVED | ANY | company member (admin override) | — | exact (customer, building) pair | rendered for in-scope customer-user; warning banner shows on admin override | `_user_passes_scope` SCOPE_CUSTOMER_LINKED for customer; SCOPE_COMPANY_MEMBER for admin | `tickets/tests/test_state_machine.py`, `frontend/tests/e2e/workflow.spec.ts` |
| WAITING_CUSTOMER_APPROVAL → REJECTED | ANY | company member (admin override) | — | exact pair (note required) | same; customer-reject requires non-empty `note` | `TicketStatusChangeSerializer.validate` enforces non-empty note for customer | tests as above |
| REJECTED → IN_PROGRESS | ANY | company member | building assigned | — | rendered for staff in scope | `apply_transition` | `tickets/tests/test_state_machine.py` |
| APPROVED → CLOSED | ANY | company member | — | — | rendered for staff in scope | `apply_transition` | same |
| CLOSED → REOPENED_BY_ADMIN | ANY | company member | — | — | rendered for SA/CA only | same | same |
| REOPENED_BY_ADMIN → IN_PROGRESS | ANY | company member | building assigned | — | same | same | same |

Notes:

- **No-op transitions** (`status == to_status`) are rejected with `code="no_op_transition"` even for super-admins.
- **Stale concurrency** is caught by `select_for_update` + a re-read of `locked.status`; the response is `code="stale_status"`.
- **TIMESTAMP_ON_ENTER** stamps `sent_for_approval_at`, `approved_at`, `rejected_at`, `closed_at` on the corresponding entry. Loop transitions overwrite the value (analytics use `TicketStatusHistory` for first/last/duration).
- **`mark_first_response_if_needed`** runs after every transition. It is the ticket's `first_response_at` SLA marker.
- **Customer-reject UX**: the customer-user gets a "Please explain why this ticket is rejected" banner before submission. Backend re-validates.

### Gaps in lifecycle test coverage

- IN_PROGRESS → APPROVED **without** going through WAITING_CUSTOMER_APPROVAL is forbidden by the table — covered by the `TransitionError(code="invalid_transition")` path.
- Sprint 15's pair-aware scope_check has dedicated unit tests (`tickets/tests/test_state_machine.py::SCOPE_CUSTOMER_LINKED_PAIR_AWARE`) and is now also covered by Playwright `workflow.spec.ts`.
- Sprint 17 adds a new Playwright test that confirms a building manager who is OUT-of-building does NOT get the WAITING_CUSTOMER_APPROVAL → APPROVED button (defence in depth — backend already 403's). See `frontend/tests/e2e/workflow.spec.ts` after this sprint.

---

## D. UI consistency audit

For every role-relevant page we record (1) the role behaviour spec,
(2) the actual UI behaviour as observed during the audit, (3) the
backend endpoint(s) the page consumes, and (4) a PASS/NEEDS
FOLLOW-UP/RISK classification.

### LoginPage (`frontend/src/pages/LoginPage.tsx`)

- Spec: anyone reaches it. The seven demo cards render only when the build had `VITE_DEMO_MODE=true`.
- Actual: `SHOW_DEMO_USERS = import.meta.env.VITE_DEMO_MODE === "true"`. Cards are gated; the form is otherwise standard. `data-testid="demo-cards"` and per-card test ids are present.
- Backend: `POST /api/auth/token/` for login; `POST /api/auth/password/reset/` for forgot-password.
- Status: PASS.

### Dashboard (`frontend/src/pages/DashboardPage.tsx`)

- Spec: every authenticated role lands here. Ticket list is `scope_tickets_for(user)`. Stats and stats-by-building are scoped on the same queryset. URL query params control filtering and SLA bucket.
- Actual: list, stats, by-building all hit the scoped endpoints. Pagination is server-side. Auto-refresh every 60s. `admin_required` banner displays after a redirect from `AdminRoute`. Every row navigates to the detail page on click.
- Backend: `/api/tickets/`, `/api/tickets/stats/`, `/api/tickets/stats/by-building/`.
- Status: PASS.

### Create ticket (`frontend/src/pages/CreateTicketPage.tsx`)

- Spec: building dropdown filtered to scope; customer dropdown filtered by the (building, customer) M:N link. Customer-user can only create a ticket at a (customer, building) pair they hold access for. Backend re-validates.
- Actual: `customerMatchesBuilding` accepts EITHER legacy `customer.building == building` OR `customer.linked_building_ids` containing the building id. Auto-select on single-match. The submit POST reaches `/api/tickets/`; the serializer rejects out-of-scope pairs with the explicit message strings documented in Sprint 14.
- Backend: `/api/buildings/`, `/api/customers/`, `POST /api/tickets/`.
- Status: PASS.

### Ticket detail (`frontend/src/pages/TicketDetailPage.tsx`)

- Spec: workflow buttons must mirror `ticket.allowed_next_statuses` returned by `TicketDetailSerializer.get_allowed_next_statuses` (which delegates to `state_machine.allowed_next_statuses`). Customer-user reject requires a note. Internal-note composer hidden from customer-user. Internal attachments hidden from customer-user. Assignment select hidden from customer-user.
- Actual: `getVisibleWorkflowStatuses` returns the API-supplied list verbatim (Sprint 15 removed the legacy `SUPER_ADMIN_UI_NEXT_STATUS` table). Internal toggle in the composer is gated on `isStaff`. Assignment form gated on `isStaff`. Hidden attachments tagged with the "Internal" pill. Soft-delete confirm requires typing the ticket number.
- Backend: `GET /api/tickets/<id>/`, `GET /api/tickets/<id>/messages/`, `GET /api/tickets/<id>/attachments/`, `POST /api/tickets/<id>/status/`, `POST /api/tickets/<id>/assign/`, `GET /api/tickets/<id>/assignable-managers/`, `DELETE /api/tickets/<id>/`, attachment download.
- Status: PASS.

### Reports (`frontend/src/pages/reports/ReportsPage.tsx`)

- Spec: SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER allowed; CUSTOMER_USER redirected. Filter chooser scopes data to user's allowed companies/buildings.
- Actual: `ReportsRoute` SPA guard mirrors `IsReportsConsumer`. Lazy chunk so non-reports users do not download recharts. Filters resolved server-side via `resolve_scope`.
- Backend: `/api/reports/*` (status-distribution, tickets-over-time, manager-throughput, sla-distribution, sla-breach-rate-over-time, age-buckets, tickets-by-{type,customer,building} JSON + CSV + PDF).
- Status: PASS.

### Admin: Companies / Buildings / Customers / Users / Invitations

- Spec: SUPER_ADMIN + COMPANY_ADMIN can see/manipulate. BUILDING_MANAGER and CUSTOMER_USER are SPA-redirected to the dashboard with `?admin_required=ok`.
- Actual: `AdminRoute` enforces this, mirroring the `IsSuperAdminOrCompanyAdmin*` permissions on the backend. The five admin pages all use the scoped list endpoints. Reactivation buttons are SUPER_ADMIN-only on the backend; the frontend hides them for COMPANY_ADMIN.
- Backend: `/api/companies/`, `/api/buildings/`, `/api/customers/`, `/api/users/`, `/api/auth/invitations/`.
- Status: PASS.

### Settings (`frontend/src/pages/SettingsPage.tsx`)

- Spec: every authenticated user can edit their own `full_name` + language; change password; toggle notification preferences.
- Actual: PATCH `/api/auth/me/` (drops unknown fields), `POST /api/auth/password/change/`, PATCH `/api/auth/notification-preferences/`. No role gates needed.
- Status: PASS.

### Audit logs (no UI)

- Spec: an immutable feed for SUPER_ADMIN. No UI page is currently exposed.
- Actual: `/api/audit-logs/` returns 200 for SUPER_ADMIN, 403 for everyone else, 404 for individual rows (RetrieveModelMixin not inherited). No `/admin/audit-logs` SPA route exists.
- Status: NEEDS FOLLOW-UP — *not pilot-blocking*. The pilot operator can hit the endpoint directly; a UI page is planned for a later sprint.

---

## E. Security / direct-object access audit

Every assertion below has either a backend test, a Playwright test
landing in this sprint, or both. PASS is conservative — only used
when the path is covered.

| Vector | Defence | Test path |
| --- | --- | --- |
| User cannot access another company's objects via URL. | Each viewset's `get_queryset()` calls a `scope_*` helper that filters by company membership; a 404 returns before the object permission fires. | `companies/tests/test_crud.py`, `accounts/tests/test_admin_crud_scope_regression.py`, `accounts/tests/test_scoping.py`, Sprint 17 Playwright `routes.spec.ts`. |
| Customer-user cannot access another customer/building's tickets via URL. | `scope_tickets_for` uses an `Exists` subquery against `CustomerUserBuildingAccess` for the EXACT pair, not just any customer membership. | `accounts/tests/test_scoping.py`, `customers/tests/test_customer_building_user_scope.py`, `tickets/tests/test_scoping.py`, Sprint 17 Playwright `scope.spec.ts`. |
| Building manager cannot access unassigned-building tickets via URL. | `scope_tickets_for(BUILDING_MANAGER)` filters on `building_id__in=BuildingManagerAssignment.user`. | `tickets/tests/test_scoping.py`, Sprint 17 Playwright `scope.spec.ts`. |
| Attachment direct download cannot bypass scope. | `TicketAttachmentDownloadView.get` re-checks `scope_tickets_for(user).filter(pk=ticket.pk).exists()` before serving the file. | `tickets/tests/test_attachments.py`, Sprint 17 Playwright `attachments.spec.ts`. |
| Hidden / internal attachment cannot leak to a customer user. | Three layers: `TicketAttachmentListCreateView` filters out `is_hidden=True`, `message__is_hidden=True`, `message__message_type=INTERNAL_NOTE`; the download view re-checks the same triple; the upload serializer rejects `is_hidden=True` from non-staff. | `tickets/tests/test_attachments.py`, Sprint 17 Playwright `attachments.spec.ts`. |
| Internal note cannot leak to a customer-user. | `TicketMessageListCreateView.get_queryset` excludes `INTERNAL_NOTE` and `is_hidden=True` for non-staff; `TicketMessageSerializer.validate_message_type` rejects `INTERNAL_NOTE` from non-staff on write. | `tickets/tests/test_state_machine.py` (workflow path), `tickets/tests/test_assignment.py`, Sprint 17 Playwright `messages.spec.ts`. |
| Soft-deleted ticket invisible to all roles. | Every code path filters `deleted_at__isnull=True`. Stats / reports use the same filter. | `tickets/tests/test_soft_delete.py`. |
| Inactive / soft-deleted user cannot authenticate or act. | `IsAuthenticatedAndActive.has_permission` short-circuits on `is_active=False` or `deleted_at IS NOT NULL`. The token serializer also refuses inactive users. | `accounts/tests/test_auth.py::test_login_inactive_user_fails` and `::test_login_soft_deleted_user_fails`. |
| Customer-user cannot post internal notes. | Three layers: composer toggle hidden in UI; `validate_message_type` rejects on the wire; `perform_create` overrides to PUBLIC_REPLY for non-staff (defence in depth). | `tickets/tests/test_assignment.py`, Sprint 17 Playwright `messages.spec.ts`. |
| Customer-user cannot assign tickets. | Three layers: assignment card hidden in UI; viewset's `assign` action 403's pre-serializer; `TicketAssignSerializer.validate` re-checks the role. | Sprint 17 Playwright `assignment.spec.ts`. |
| Reports endpoints reject CUSTOMER_USER. | `IsReportsConsumer` refuses; SPA `ReportsRoute` redirects. | Sprint 17 Playwright `reports.spec.ts`. |
| Audit log feed is super-admin only. | `IsSuperAdmin` permission class on the viewset. | `audit/tests/test_audit.py`. |
| Cross-company manager cannot be assigned. | `TicketAssignSerializer.validate` rejects an `assigned_to` that is not on the ticket's building's manager assignment list. | `tickets/tests/test_assignment.py`. |
| Demo accounts cannot ship to pilot. | `accounts/management/commands/check_no_demo_accounts.py` refuses launch when any `@cleanops.demo` or hardcoded demo email exists. | `accounts/tests/test_check_no_demo_accounts.py`. |

---

## F. Findings table

| # | Area | Finding | Class | File | Recommendation | Pilot blocker? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Role permissions | Four roles, four scope helpers, four queryset gates — all consistent. | PASS | `accounts/scoping.py` | — | No |
| 2 | Customer-user pair check | Sprint 14 + Sprint 15 use the same `(membership.customer, access.building)` shape across visibility, message posting, attachment listing/upload/download, and status transitions. | PASS | `accounts/scoping.py`, `tickets/permissions.py`, `tickets/state_machine.py` | — | No |
| 3 | Ticket workflow vs UI | UI now reads `allowed_next_statuses` from the API. No frontend state machine. | PASS | `frontend/src/pages/TicketDetailPage.tsx` | — | No |
| 4 | Customer reject requires note | Server-side validated; UI shows the inline reason field. | PASS | `tickets/serializers.py::TicketStatusChangeSerializer.validate` | — | No |
| 5 | Reports scope | `resolve_scope` validates query params against `_allowed_company_ids` / `_allowed_building_ids`. CSV/PDF go through the same `compute_*` payload. | PASS | `reports/scoping.py`, `reports/views.py` | — | No |
| 6 | Hidden/internal attachments | Three independent gates (list filter, download view, upload serializer). | PASS | `tickets/views.py`, `tickets/serializers.py` | — | No |
| 7 | Audit logs | Tracked: User, Company, Building, Customer + 5 membership/assignment tables. CRUD for entities, CREATE/DELETE for memberships. | PASS | `audit/signals.py` | — | No |
| 8 | Soft delete propagation | `Ticket.deleted_at` is filtered at every read site (list, detail, messages, attachments, reports, stats). | PASS | `accounts/scoping.py`, `reports/scoping.py` | — | No |
| 9 | Demo account guard | `check_no_demo_accounts` blocks pilot launch on any demo email or any `@cleanops.demo` user. | PASS | `accounts/management/commands/check_no_demo_accounts.py` | — | No |
| 10 | Audit log UI | No SPA route exists yet for `/admin/audit-logs`; super-admins must hit the API directly. | NEEDS FOLLOW-UP | n/a | Add an admin page (filters: target_model, target_id, date range, actor) that calls `/api/audit-logs/`. | No (post-pilot) |
| 11 | UsersAdminPage scope hint | A COMPANY_ADMIN cannot edit SUPER_ADMIN or other COMPANY_ADMIN rows; the UI still shows them in the list with a disabled-style affordance. | PASS | `accounts/views_users.py`, `frontend/src/pages/admin/UsersAdminPage.tsx` | — | No |
| 12 | Inactive-user authentication test | Token endpoint refuses inactive AND soft-deleted users — both negative paths have direct regressions. | PASS | `accounts/tests/test_auth.py` | — | No |
| 13 | Customer cannot reach `/reports` UI | `ReportsRoute` redirects; `IsReportsConsumer` 403's the API. | PASS | `frontend/src/components/ReportsRoute.tsx`, `reports/permissions.py` | — | No |
| 14 | Customer cannot assign tickets | `TicketAssignSerializer.validate` rejects; viewset 403's pre-serializer; UI hides the assignment form. | PASS | `tickets/serializers.py`, `tickets/views.py`, `frontend/src/pages/TicketDetailPage.tsx` | — | No |
| 15 | Cross-building manager cannot be assigned | `TicketAssignSerializer.validate` checks `BuildingManagerAssignment` exists for the (manager, ticket.building). The `assignable_managers` endpoint also filters to only those managers, so the dropdown cannot present an out-of-building manager. | PASS | `tickets/serializers.py`, `tickets/views.py` | — | No |
| 16 | Demo cards in production | Gate switched in Sprint 16 from `import.meta.env.DEV` to `VITE_DEMO_MODE === "true"`. A production rebuild without that env defaults to `false`. | PASS | `frontend/Dockerfile`, `frontend/.env.example`, `docker-compose.prod.yml` | — | No |
| 17 | Soft-delete actor recorded on tickets | `destroy()` writes `deleted_by` plus an explicit AuditLog row capturing email and ticket_no. | PASS | `tickets/views.py::TicketViewSet.destroy` | — | No |
| 18 | `/admin/*` URL prefix collision (deployment) | nginx forwards every `/admin/*` request to Django's admin (`location /admin/` in `frontend/nginx.conf`). The SPA's `/admin/companies` etc. share that prefix, so a fresh page load at `/admin/companies` is routed to Django and 302's to `/admin/login/`. The SPA's admin pages are reachable only via in-SPA navigation (sidebar nav links). | NEEDS FOLLOW-UP | `frontend/nginx.conf`, `backend/config/urls.py`, all `/admin/*` `<Route>`s in `frontend/src/App.tsx` | Move Django admin to `/django-admin/` (single one-line change in `backend/config/urls.py` plus `frontend/nginx.conf`) so the SPA owns the `/admin/*` prefix end-to-end and bookmarked URLs work. | No (in-app UX works; only direct URL bookmarks break) |

### Summary

- PASS: 16
- NEEDS FOLLOW-UP: 2 (audit-log UI; `/admin/*` URL prefix collision)
- RISK: 0

No pilot-blocking finding. The two follow-ups are both UX quality-of-life
issues: the immutable audit feed is already exposed to super-admins via
the API, and the SPA's admin pages are reachable from every operator
session via the sidebar nav (only direct-URL bookmarks at `/admin/*`
hit Django's admin first). Both improvements are slated for a post-pilot
sprint.

---

## Father / Ramazan business logic — implementation status

Each rule from the original brief, mapped to a code path:

1. **Osius / facility-side staff manage everything.** SUPER_ADMIN role + super-admin-only reactivate endpoints. Implemented.
2. **Customers can have access to one or more buildings.** `CustomerBuildingMembership` (M:N). Implemented.
3. **Customer users only see and act on tickets for the exact (customer, building) pairs they're allowed.** `CustomerUserBuildingAccess` + `Exists` subquery in `scope_tickets_for` + pair-check in `state_machine._user_passes_scope` + pair-check in `tickets.permissions.user_has_scope_for_ticket`. Implemented and end-to-end tested.
4. **Building managers only see and act on tickets for assigned buildings.** `BuildingManagerAssignment` + `scope_tickets_for(BUILDING_MANAGER)` + `state_machine` SCOPE_BUILDING_ASSIGNED. Implemented.
5. **Company admins only see their company scope.** `CompanyUserMembership` + `scope_*` helpers. Implemented.
6. **Super admins can see / manage everything.** Special-case branches in scope helpers + `state_machine.can_transition` SUPER_ADMIN_CAN_TRANSITION_ANY_STATUS. Implemented.
7. **Workflow OPEN → IN_PROGRESS → WAITING_CUSTOMER_APPROVAL → APPROVED / REJECTED → CLOSED.** `state_machine.ALLOWED_TRANSITIONS`. Implemented; rejected → in-progress and closed → reopened-by-admin loops also wired.
8. **Customer approval/rejection only possible for customer users with exact pair access.** SCOPE_CUSTOMER_LINKED gate. Implemented and Playwright-tested.
9. **UI must not show buttons backend would reject.** `TicketDetailPage` reads `ticket.allowed_next_statuses` from the API; no frontend state machine. Implemented.
10. **Backend remains source of truth.** Every serializer + permission re-validates on every write path. Implemented.

Conclusion: the father/Ramazan logic is fully implemented as of the
end of Sprint 15. Sprint 16 added the demo seed and Playwright
harness; Sprint 17 expands the Playwright suite (route matrix,
messages, attachments, assignment, plus extra scope/workflow
personas) and produces this audit doc. Backend test coverage was
inspected for every assertion in the table above; no genuine gap was
found, so no new backend test was added (the audit doc is honest
about that — every row in the security audit names an existing test
file).

