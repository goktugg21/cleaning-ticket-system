# Sprint 27 — RBAC / permissions / hierarchy source of truth

This is the canonical reference for **who can do what** in the
cleaning-ticket-system. It is generated from a read-only audit of
the code on `master @ 95748b3` (Sprint 26C) and is the spec
reviewers cite during Sprint 27 code review.

The product is vendor-neutral. OSIUS is **one concrete
`companies.Company` row** (slug `osius-demo`) — currently the
first real provider company in production — and the codebase
treats any second provider (e.g. `bright-facilities` in the demo
seed) identically. **No role check, scoping helper, or permission
key references "osius" semantically; the `osius.*` permission-key
namespace is documented technical-debt naming only.**

## 1. Role model summary

### 1.1 `accounts.UserRole` (the single global role enum)

Defined at [accounts/models.py:7-16](../../backend/accounts/models.py#L7-L16):

| Value | Meaning | Side |
|---|---|---|
| `SUPER_ADMIN` | Platform admin. Sees / manages everything globally. | platform |
| `COMPANY_ADMIN` | **Provider** company admin. Strongest user inside one provider company. | provider |
| `BUILDING_MANAGER` | Provider building manager. Scoped to assigned buildings. | provider |
| `STAFF` | Provider field staff / cleaner. Scoped to assigned work + visibility-granted buildings. | provider |
| `CUSTOMER_USER` | Every customer-side user. Per-building access + sub-role lives on the access row, not on `User.role`. | customer |

There are **only five values**. The customer-side hierarchy
(Customer Company Admin / Location Manager / basic User) is
**not** new `User.role` values — it lives on a per-access-row
sub-enum on `CustomerUserBuildingAccess` (see §2).

### 1.2 Membership tables (the source of truth for "who is in scope of what")

| Table | Links | Used by |
|---|---|---|
| [`companies.CompanyUserMembership`](../../backend/companies/models.py#L22-L39) | Provider company ↔ User | Scope COMPANY_ADMIN to their provider company |
| [`buildings.BuildingManagerAssignment`](../../backend/buildings/models.py#L31-L49) | Building ↔ User | Scope BUILDING_MANAGER to their buildings |
| [`buildings.BuildingStaffVisibility`](../../backend/buildings/models.py#L52-L84) | Building ↔ User (+ `can_request_assignment` per-row flag) | Grant STAFF visibility on a building they aren't directly assigned to |
| [`accounts.StaffProfile`](../../backend/accounts/models.py#L104-L133) | One-to-one User (STAFF only; `phone`, `internal_note`, `is_active`, `can_request_assignment`) | Staff profile + global staff-side toggles |
| [`tickets.TicketStaffAssignment`](../../backend/tickets/models.py#L265-L308) | Ticket ↔ User (STAFF) | Direct ticket assignment |
| [`customers.CustomerBuildingMembership`](../../backend/customers/models.py#L83-L114) | Customer org ↔ Building | M:N source of truth for "this customer org operates in this building" |
| [`customers.CustomerUserMembership`](../../backend/customers/models.py#L117-L134) | Customer org ↔ User | Links a `User.role=CUSTOMER_USER` to their customer organization |
| [`customers.CustomerUserBuildingAccess`](../../backend/customers/models.py#L137-L214) | `CustomerUserMembership` ↔ Building (+ `access_role`, `permission_overrides`, `is_active`) | Per-customer-user per-building grant — carries the customer-side sub-role + override JSON |

## 2. Customer access_role sub-enum

Defined at [customers/models.py:168-177](../../backend/customers/models.py#L168-L177):

| Value | Default scope (from `_TICKET_ROLE_DEFAULTS`) |
|---|---|
| `CUSTOMER_USER` | `ticket.create`, `ticket.view_own`, `ticket.approve_own`, `extra_work.create`, `extra_work.view_own`, `extra_work.approve_own` |
| `CUSTOMER_LOCATION_MANAGER` | All `view_own/view_location/approve_own/approve_location` for tickets + extra work, plus `users.assign_location_role` |
| `CUSTOMER_COMPANY_ADMIN` | Every one of the 16 customer permission keys (full customer-org view + management) |

Role-default table at [customers/permissions.py:53-101](../../backend/customers/permissions.py#L53-L101).
Resolver at [customers/permissions.py:109-126](../../backend/customers/permissions.py#L109-L126).
Resolution order:
1. `access.is_active` is False → every key resolves to False.
2. Key present in `access.permission_overrides` JSON → override value wins (True = grant, False = revoke).
3. Otherwise → return the per-`access_role` default.

## 3. Hard invariants (must be enforced AND tested)

These are the security floor. Any change that contradicts them is a P0 regression.

| # | Invariant | Enforced at | Test that locks it |
|---|---|---|---|
| H-1 | **No provider company sees another provider company's data.** | Scoping helpers branch by `CompanyUserMembership` etc. — [accounts/scoping.py:155-296](../../backend/accounts/scoping.py#L155-L296), [extra_work/scoping.py:35-119](../../backend/extra_work/scoping.py#L35-L119) | [test_seed_demo_data.py:286-301](../../backend/accounts/tests/test_seed_demo_data.py#L286-L301), [test_extra_work_mvp.py ProviderScopeTests](../../backend/extra_work/tests/test_extra_work_mvp.py) |
| H-2 | **No customer company sees another customer's data, even in the same building.** | [accounts/scoping.py:232-294](../../backend/accounts/scoping.py#L232-L294) keyed on `customer_id` first | [test_sprint23a_foundation.py:244](../../backend/accounts/tests/test_sprint23a_foundation.py#L244), [test_sprint26a_scope_safety_net.py CrossTicketAttachmentIdSmugglingTests](../../backend/tickets/tests/test_sprint26a_scope_safety_net.py) |
| H-3 | **Customer users never see all building data unless explicitly granted.** | `view_company` / `view_location` / `view_own` resolved per-access via `access_has_permission` — [accounts/scoping.py:273-292](../../backend/accounts/scoping.py#L273-L292) | [test_sprint23a_foundation.py:255-275](../../backend/accounts/tests/test_sprint23a_foundation.py#L255) |
| H-4 | **STAFF always sees work assigned to them — cannot be removed.** | STAFF scope is `assigned OR visible` ([accounts/scoping.py:211-230](../../backend/accounts/scoping.py#L211-L230)); the `assigned` clause has no toggle. | Sprint 27A T-7 adds the regression lock (see §6) |
| H-5 | **STAFF cannot approve customer completion / manager review / pricing / workflow override.** | Ticket state machine has no STAFF → APPROVED/REJECTED transition ([tickets/state_machine.py ALLOWED_TRANSITIONS](../../backend/tickets/state_machine.py#L18-L57)); Extra Work `_is_provider_operator` excludes STAFF ([extra_work/state_machine.py:64-71](../../backend/extra_work/state_machine.py#L64-L71)). | Sprint 27A T-4, T-5 |
| H-6 | **Customer Company Admin cannot promote anyone to Customer Company Admin.** | After Sprint 27A: serializer-level guard at [customers/serializers_memberships.py CustomerUserBuildingAccessUpdateSerializer.validate_access_role](../../backend/customers/serializers_memberships.py#L92) | Sprint 27A T-1, T-3 |
| H-7 | **Only SUPER_ADMIN can grant `CUSTOMER_COMPANY_ADMIN` access_role.** | Same as H-6. | Sprint 27A T-1, T-2 |
| H-8 | **COMPANY_ADMIN cannot self-promote to SUPER_ADMIN.** | [accounts/serializers_users.py:84-98](../../backend/accounts/serializers_users.py#L84-L98) — blocks self-target + blocks SUPER_ADMIN target | [test_user_crud.py:115](../../backend/accounts/tests/test_user_crud.py#L115) (already green) |
| H-9 | **Nobody can grow their own scope.** | No API surface lets a user write `CompanyUserMembership` / `BuildingManagerAssignment` / `CustomerUserMembership` rows referencing themselves; `validate_role` blocks self-target ([serializers_users.py:85-86](../../backend/accounts/serializers_users.py#L85-L86)). | [test_user_crud.py:154](../../backend/accounts/tests/test_user_crud.py#L154), [test_sprint23c_access_role_editor.py:102](../../backend/customers/tests/test_sprint23c_access_role_editor.py#L102) |
| H-10 | **Permission/role/scope changes must be audit-logged.** | Audit signals at [audit/signals.py:424-510](../../backend/audit/signals.py#L424-L510). `User`, `Customer`, `Company`, `Building`, `StaffProfile`, `StaffAssignmentRequest` fully tracked; memberships tracked CREATE/DELETE; `CustomerUserBuildingAccess` tracks `access_role / permission_overrides / is_active`. | [test_audit_membership.py](../../backend/audit/tests/test_audit_membership.py) |
| H-11 | **Permission override and workflow override are separate concepts in code, model, audit.** | Permission override = `CustomerUserBuildingAccess.permission_overrides` JSON + `is_active`. Workflow override = Extra Work's `is_override + override_reason` ([extra_work/state_machine.py:198-273](../../backend/extra_work/state_machine.py#L198-L273)) + `ExtraWorkRequest.override_by/_reason/_at`. **Ticket workflow override is currently NOT separately modeled — see G-B3 in §5.** | Sprint 27A T-6 |

## 4. Permission override vs workflow override (the two are NOT the same)

| Concept | What it represents | Where it lives | Audit |
|---|---|---|---|
| **Permission override** | A persistent toggle that changes what a user/customer is allowed to do over time. Example: "Customer User Tom can create extra work in Building B1, even though basic CUSTOMER_USER access-role default doesn't grant `customer.extra_work.create`." | `CustomerUserBuildingAccess.permission_overrides` JSON ([model:200](../../backend/customers/models.py#L200)) + `is_active` ([model:203](../../backend/customers/models.py#L203)). Also: `StaffProfile.{is_active, can_request_assignment}`, `BuildingStaffVisibility.can_request_assignment`, `Customer.show_assigned_staff_{name,email,phone}`. | Generic `AuditLog` UPDATE diff via per-model signal. |
| **Workflow override** | A one-shot decision a provider-side user makes that normally would be a customer-side action. Example: "Customer phoned us to approve the pricing, so the building manager clicks Override → Customer Approved and types the reason in the audit modal." | Extra Work: `is_override + override_reason` args on `apply_transition` ([extra_work/state_machine.py:198-199](../../backend/extra_work/state_machine.py#L198-L199)), persisted as `ExtraWorkStatusHistory.is_override` ([model:362-368](../../backend/extra_work/models.py#L362-L368)) + `ExtraWorkRequest.override_by/_reason/_at` ([model:200-212](../../backend/extra_work/models.py#L200-L212)). **Ticket equivalent missing — see G-B3.** | Extra Work writes the history-row flag + the request-row triple. Ticket has only an email-context derived `is_admin_override` flag at [tickets/views.py:214-217](../../backend/tickets/views.py#L214-L217), NOT persisted. |

Sprint 27A T-6 locks this conceptual separation by asserting that
toggling a permission override does NOT touch any workflow-override
field, and vice versa.

## 5. Current backend enforcement points

| Concern | File:line |
|---|---|
| Role choices | [accounts/models.py:7-16](../../backend/accounts/models.py#L7-L16) |
| Provider permission resolver (`osius.*` keys) | [accounts/permissions_v2.py:42-121](../../backend/accounts/permissions_v2.py#L42-L121) |
| Customer permission resolver (`customer.*` keys) | [customers/permissions.py:109-126](../../backend/customers/permissions.py#L109-L126) |
| Ticket scope | [accounts/scoping.py:155-296](../../backend/accounts/scoping.py#L155-L296) |
| Extra Work scope | [extra_work/scoping.py:35-119](../../backend/extra_work/scoping.py#L35-L119) |
| Ticket state machine + transitions | [tickets/state_machine.py](../../backend/tickets/state_machine.py) |
| Ticket completion-evidence rule (Sprint 25C) | [tickets/state_machine.py COMPLETION_EVIDENCE_TRANSITIONS](../../backend/tickets/state_machine.py) |
| Extra Work state machine + override | [extra_work/state_machine.py:152-273](../../backend/extra_work/state_machine.py#L152-L273) |
| User role mutation guard | [accounts/serializers_users.py:84-98](../../backend/accounts/serializers_users.py#L84-L98) |
| Customer access-role PATCH | [customers/views_memberships.py:284-298](../../backend/customers/views_memberships.py#L284-L298) + [serializers_memberships.py:92-111](../../backend/customers/serializers_memberships.py#L92-L111) |
| `CUSTOMER_COMPANY_ADMIN`-granting guard (Sprint 27A) | [serializers_memberships.py validate_access_role](../../backend/customers/serializers_memberships.py) |
| StaffProfile PATCH | [accounts/views_staff.py:104-116](../../backend/accounts/views_staff.py#L104-L116) |
| BuildingStaffVisibility CREATE/PATCH/DELETE | [accounts/views_staff.py:153-230](../../backend/accounts/views_staff.py#L153-L230) |
| Audit signals (which models / which fields) | [audit/signals.py:424-510](../../backend/audit/signals.py#L424-L510) |
| Audit log shape | [audit/models.py:11-64](../../backend/audit/models.py#L11-L64) |

## 6. Current frontend gaps (defense-in-depth UI; backend is the real gate)

| Gap | Location | Sprint to close |
|---|---|---|
| **G-F1.** No UI to edit `permission_overrides` JSON. | Deferred at [UserFormPage.tsx:1033-1035](../../frontend/src/pages/admin/UserFormPage.tsx#L1033-L1035) | Sprint 27E |
| **G-F2.** No UI to set `CustomerUserBuildingAccess.is_active=False` without deleting the row. | [CustomerFormPage.tsx:1059-1098](../../frontend/src/pages/admin/CustomerFormPage.tsx#L1059-L1098) edits `access_role` only. | Sprint 27E |
| **G-F3.** Ticket workflow override has no mandatory-reason input. | [TicketDetailPage.tsx:57-67,165-169](../../frontend/src/pages/TicketDetailPage.tsx#L57-L67) — only a confirmation modal. Extra Work pattern at [ExtraWorkDetailPage.tsx:250-273](../../frontend/src/pages/ExtraWorkDetailPage.tsx#L250-L273) is the right shape to mirror. | Sprint 27F (lands together with the backend `TicketStatusHistory.is_override + override_reason` columns) |
| **G-F4.** STAFF role intentionally hidden from `UserFormPage` create/edit. | [UserFormPage.tsx:49-54](../../frontend/src/pages/admin/UserFormPage.tsx#L49-L54). Add a helper note. | Sprint 27E |
| **G-F5.** No company-level policy toggles UI for "this customer company can create extra work" etc. | Only the three `show_assigned_staff_*` toggles exist today on `CustomerFormPage`. | Sprint 27C / 27E |

## 7. Documented gaps (NOT fixed in 27A — sized for later sprints)

| Gap | Severity | Sprint to close |
|---|---|---|
| **G-B2.** `permission_overrides` and `CustomerUserBuildingAccess.is_active` editing is API-deferred ([serializers_memberships.py:97-101](../../backend/customers/serializers_memberships.py#L97-L101)). Backend endpoint exists, only accepts `access_role`. Must ship together with a **self-edit guard** (actor.id ≠ target.user.id) AND a permission-key allow-list. | P1 | Sprint 27C |
| **G-B3.** Ticket workflow override has no `is_override` flag, no reason column, no audit row on the generic `AuditLog`. Only email-context derived flag at [tickets/views.py:214-217](../../backend/tickets/views.py#L214-L217). | P1 | Sprint 27F |
| **G-B4.** `BuildingStaffVisibility.can_request_assignment` UPDATEs are not audited — model registered as CREATE/DELETE-only membership at [audit/signals.py:454-471](../../backend/audit/signals.py#L454-L471). The Sprint 27A T-7 test exists to LOCK the future fix; it is **expected to fail** today and that failure is the documented gap. | P1 | Sprint 27F |
| **G-B5.** Company-level / customer-policy fields are sparse — only three `show_assigned_staff_*` booleans. Needs a `CustomerCompanyPolicy` model for "this customer company can create extra work" etc. | P2 | Sprint 27C |
| **G-B6.** No `reason` column on `AuditLog`. | P2 | Sprint 27F |
| **G-B7.** STAFF cannot see Extra Work at all — `scope_extra_work_for` returns `.none()` for STAFF ([extra_work/scoping.py:67-71](../../backend/extra_work/scoping.py#L67-L71)). | P2 (intentional MVP gap; needs the staff-execution surface) | Sprint 27 follow-up sprint after 27G |
| **G-B8.** `osius.*` permission-key naming-debt rename. | P2 | own future sprint (do not bundle) |
| **G-B9.** `osius.staff.manage`, `osius.building.manage`, `osius.customer_company.manage` keys declared but unwired in resolver. | P2 | Sprint 27D |

## 8. Sprint 27B-G follow-up plan

### Sprint 27B — backend effective-permission service
- Introduce `accounts/permissions_effective.py` composing today's two resolvers behind a single `effective_permissions(user, *, customer_id=None, building_id=None) -> dict[str, bool]` API.
- Migrate one call site to consume the new service; shadow-test that the old and new resolvers agree on every key.
- Add `BuildingStaffVisibility.can_request_assignment` audit signal (closes **G-B4** + makes T-7 pass).

### Sprint 27C — customer-side permission model + write endpoint
- New `CustomerCompanyPolicy` model with three migrated booleans plus the new toggles (G-B5).
- `permission_overrides` write endpoint with self-edit guard + permission-key allow-list (closes G-B2).
- New test: `test_self_cannot_edit_own_permission_overrides`.

### Sprint 27D — provider-side staff / building-manager permission model
- Wire the three stubbed `osius.*` keys (G-B9).
- Add per-building-manager toggles (e.g. workflow-override disable).

### Sprint 27E — frontend permission management UI
- Permission-override editor wired to Sprint 27C endpoint (closes G-F1, G-F2).
- Customer-company-policy panel (G-F5).
- STAFF helper note (G-F4).

### Sprint 27F — audit log hardening + ticket workflow override
- `AuditLog.reason` + `AuditLog.actor_scope` columns (G-B6).
- `TicketStatusHistory.is_override + override_reason` + matching state-machine API (G-B3).
- Frontend ticket-override modal mirroring Extra Work (G-F3).

### Sprint 27G — end-to-end Playwright + demo runbook
- Customer-pricing loop spec with one override at each decision point.
- Refreshed `docs/demo-walkthrough.md`.

## 9. Test footprint (Sprint 27A delta)

Tests added in Sprint 27A (test-first):

| # | Test | File | Expected |
|---|---|---|---|
| T-1 | `test_company_admin_cannot_grant_customer_company_admin_access_role` | `customers/tests/test_sprint27a_rbac_safety_net.py` | Fails before the serializer guard, passes after. |
| T-2 | `test_super_admin_can_grant_customer_company_admin_access_role` | same | Passes today (locks the positive path). |
| T-3 | `test_customer_company_admin_cannot_promote_peer_to_company_admin` | same | Passes today (gate at endpoint role class) — locks current good behavior. |
| T-4 | `test_staff_cannot_approve_or_override_ticket_completion` | `tickets/tests/test_sprint27a_rbac_safety_net.py` | Passes today (state machine has no STAFF approval transition). |
| T-5 | `test_staff_cannot_approve_or_override_extra_work_pricing` | `extra_work/tests/test_sprint27a_rbac_safety_net.py` | Passes today (`_is_provider_operator` excludes STAFF). |
| T-6 | `test_permission_override_is_distinct_from_workflow_override` | `customers/tests/test_sprint27a_rbac_safety_net.py` | Passes today — proves toggling a permission override does NOT touch any workflow-override field, and vice versa. |
| T-7 | `test_building_staff_visibility_can_request_assignment_update_is_audited` | `audit/tests/test_sprint27a_rbac_safety_net.py` | **Expected to FAIL today** — documents gap **G-B4**. Will be closed by Sprint 27B. |

**Backend code change (only one allowed):** add
`validate_access_role` on `CustomerUserBuildingAccessUpdateSerializer`
so the actor must be `UserRole.SUPER_ADMIN` to set
`access_role=CUSTOMER_COMPANY_ADMIN`.
