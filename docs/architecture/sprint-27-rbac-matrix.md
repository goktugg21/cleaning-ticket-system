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
Resolver at [customers/permissions.py](../../backend/customers/permissions.py).
Resolution order (Sprint 27D — adds the policy DENY layer):
1. `access.is_active` is False → every key resolves to False.
2. Key present in `access.permission_overrides` JSON → override value wins (True = grant, False = revoke).
3. **Sprint 27D**: if the customer's `CustomerCompanyPolicy` field that owns this key's family is False → False. Policy can only NARROW role defaults; it cannot grant a key the role default doesn't already grant.
4. Otherwise → return the per-`access_role` default.

The policy fields and their families (Sprint 27D):

| Policy field | Keys it can deny |
|---|---|
| `customer_users_can_create_tickets` | `customer.ticket.create` |
| `customer_users_can_approve_ticket_completion` | `customer.ticket.approve_own`, `customer.ticket.approve_location` |
| `customer_users_can_create_extra_work` | `customer.extra_work.create` |
| `customer_users_can_approve_extra_work_pricing` | `customer.extra_work.approve_own`, `customer.extra_work.approve_location` |

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
| H-10 | **Permission/role/scope changes must be audit-logged.** | Audit signals at [audit/signals.py](../../backend/audit/signals.py). `User`, `Customer`, `Company`, `Building`, `StaffProfile`, `StaffAssignmentRequest` fully tracked; memberships tracked CREATE/DELETE; `CustomerUserBuildingAccess` tracks `access_role / permission_overrides / is_active`. **Sprint 27B**: `BuildingStaffVisibility.can_request_assignment` UPDATEs now tracked too via a dedicated pre_save / post_save UPDATE-only handler (CREATE/DELETE still via the existing membership handler — shape unchanged). | [test_audit_membership.py](../../backend/audit/tests/test_audit_membership.py), [test_sprint27a_rbac_safety_net.py T-7](../../backend/audit/tests/test_sprint27a_rbac_safety_net.py) |
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
| Audit signals (which models / which fields) | [audit/signals.py](../../backend/audit/signals.py) |
| Effective-permission composer (Sprint 27B) | [accounts/permissions_effective.py](../../backend/accounts/permissions_effective.py) |
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
| ~~**G-B2.** `permission_overrides` and `CustomerUserBuildingAccess.is_active` editing is API-deferred. Backend endpoint exists, only accepts `access_role`. Must ship together with a self-edit guard AND a permission-key allow-list.~~ **CLOSED by Sprint 27C.** The PATCH endpoint at `/api/customers/<cid>/users/<uid>/access/<bid>/` now accepts all three Sprint 23A editable fields: `access_role`, `permission_overrides`, `is_active`. Override keys are allow-listed against `CUSTOMER_PERMISSION_KEYS` (provider `osius.*` keys explicitly rejected). Values must be true Python booleans (`type is bool`, rejecting `0/1` via int↔bool coercion). Full-replacement semantics on the override dict. Self-edit guard added at the view layer (`request.user.id == int(user_id)` → 403, runs before object lookup). Sprint 27A guard (SUPER_ADMIN-only `CUSTOMER_COMPANY_ADMIN`) preserved. UPDATEs land on `AuditLog` via the existing `_CUBA_TRACKED_FIELDS` handler with no change. | ~~P1~~ | ~~Sprint 27C~~ **Sprint 27C ✅** |
| **G-B3.** Ticket workflow override has no `is_override` flag, no reason column, no audit row on the generic `AuditLog`. Only email-context derived flag at [tickets/views.py:214-217](../../backend/tickets/views.py#L214-L217). | P1 | Sprint 27F |
| ~~**G-B4.** `BuildingStaffVisibility.can_request_assignment` UPDATEs are not audited.~~ **CLOSED by Sprint 27B.** A dedicated pre_save snapshot + UPDATE-only post_save handler now writes an `AuditLog` UPDATE row with the before/after pair on `changes`. CREATE/DELETE shape unchanged. The Sprint 27A T-7 regression lock now passes normally. | ~~P1~~ | ~~Sprint 27F~~ **Sprint 27B** |
| **G-B5.** ~~Company-level / customer-policy fields are sparse — only three `show_assigned_staff_*` booleans. Needs a `CustomerCompanyPolicy` model for "this customer company can create extra work" etc.~~ **PERMISSION-POLICY HALF CLOSED by Sprint 27D.** [`CustomerCompanyPolicy`](../../backend/customers/models.py) model and audit (Sprint 27C) + runtime resolver wiring (Sprint 27D): `customers.permissions.access_has_permission` now consults the policy as a DENY layer between explicit overrides and role defaults. The four `customer_users_can_*` booleans actively shape resolution today. **Still deferred:** the runtime read path for `show_assigned_staff_*` continues to consult the legacy `Customer.*` fields — switch is intentionally a separate sprint so the ticket serializer contract is not entangled with the new model. Sprint 27E will land the editor UI on top of the 27C write endpoint + 27D resolver. | ~~P2~~ | ~~Sprint 27C~~ **27C (data) ✅ + 27D (resolver) ✅ → 27E for editor UI; visibility runtime switch deferred** |
| **G-B6.** No `reason` column on `AuditLog`. | P2 | Sprint 27F |
| **G-B7.** STAFF cannot see Extra Work at all — `scope_extra_work_for` returns `.none()` for STAFF ([extra_work/scoping.py:67-71](../../backend/extra_work/scoping.py#L67-L71)). | P2 (intentional MVP gap; needs the staff-execution surface) | Sprint 27 follow-up sprint after 27G |
| **G-B8.** `osius.*` permission-key naming-debt rename. | P2 | own future sprint (do not bundle) |
| ~~**G-B9.** `osius.staff.manage`, `osius.building.manage`, `osius.customer_company.manage` keys declared but unwired in resolver.~~ **CLOSED by Sprint 27D.** [`accounts/permissions_v2.py`](../../backend/accounts/permissions_v2.py) `user_has_osius_permission` now narrows COMPANY_ADMIN's universal-True branch for these three keys to require `CompanyUserMembership`-anchored scope (and if `building_id` is given, the building must belong to one of the actor's companies). SUPER_ADMIN keeps universal True. BUILDING_MANAGER / STAFF / CUSTOMER_USER stay False (the keys are explicitly company-level management; they live above the building-manager pay grade by design). A latent cross-provider leak — previously hidden because no call site passed a foreign `building_id` to a management key — is closed before the first consumer arrives. | ~~P2~~ | ~~Sprint 27D~~ **Sprint 27D ✅** |

## 8. Sprint 27B-G follow-up plan

### Sprint 27B — backend effective-permission service ✅ **DELIVERED**
- ✅ Introduced [`accounts/permissions_effective.py`](../../backend/accounts/permissions_effective.py) composing today's two resolvers behind:
  * `has_permission(user, key, *, customer_id=None, building_id=None) -> bool`
  * `effective_permissions(user, *, customer_id=None, building_id=None) -> dict[str, bool]`

  The composer is **read-only** and behaviorally equivalent to the underlying resolvers — it introduces no new permission rules and broadens no scope. Routing: `osius.*` keys → `user_has_osius_permission`; `customer.*` keys → `user_can` (returns False if `customer_id` is None); unknown keys → False; anonymous user → False.

- ✅ Shadow / parity tests at [`accounts/tests/test_sprint27b_effective_permissions.py`](../../backend/accounts/tests/test_sprint27b_effective_permissions.py) prove the composer ≡ underlying resolver for every key in `OSIUS_PERMISSION_KEYS ∪ CUSTOMER_PERMISSION_KEYS`, across SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER / STAFF / CUSTOMER_USER (each of the three access_role variants). Also locks:
  * Permission overrides on `CustomerUserBuildingAccess.permission_overrides` are honoured.
  * `is_active=False` on a customer access row collapses every customer.* key to False.
  * No cross-customer or cross-provider leak.
  * Anonymous / unknown-key / customer-key-without-customer-id all return False.

- ⏸ **Call-site migration deliberately deferred.** Today's call sites
  (`tickets/views_staff_assignments.py`, `tickets/views_staff_requests.py`,
  `extra_work/state_machine.py`, `extra_work/serializers.py`,
  `accounts/scoping.py`, `extra_work/scoping.py`) all use one of the two
  underlying resolvers directly and work correctly. Swapping any single
  call site to the composer is a behaviorally-equivalent no-op (the
  parity tests prove this), so introducing the churn has no runtime
  benefit until a new consumer (e.g. the Sprint 27C permission-override
  editor or a future "what can this user do here" admin surface) needs
  the unified API. The composer ships unused-from-existing-paths in 27B
  and will pick up its first real consumer in 27C/E. This is documented
  here so the deferred work doesn't get lost.

- ✅ `BuildingStaffVisibility.can_request_assignment` audit signal added (closes **G-B4** above + makes Sprint 27A T-7 pass normally, no longer `@unittest.expectedFailure`).

### Sprint 27C — customer-side permission model + write endpoint ✅ **DELIVERED**
- ✅ `permission_overrides` + `is_active` write support on PATCH `/api/customers/<cid>/users/<uid>/access/<bid>/` (closes **G-B2**):
  * `CustomerUserBuildingAccessUpdateSerializer.Meta.fields` extended to `["access_role", "permission_overrides", "is_active"]`.
  * `validate_permission_overrides`: must be a dict; each key allow-listed against `CUSTOMER_PERMISSION_KEYS` (so `osius.*` is rejected with 400); each value must be a true Python `bool` (`type(v) is bool`, rejecting `0/1` through Python's `bool is int` coercion); full-replacement semantics.
  * Self-edit guard added at the view layer in [`customers/views_memberships.py`](../../backend/customers/views_memberships.py) `patch()`: `request.user.id == int(user_id) → 403` (runs before `_get_access` so existence isn't revealed).
  * Sprint 27A guard (SUPER_ADMIN-only `CUSTOMER_COMPANY_ADMIN`) preserved.
  * UPDATEs continue to land on `AuditLog` via the existing `_CUBA_TRACKED_FIELDS` handler — both `permission_overrides` and `is_active` were already in the tracked tuple.

- ✅ `CustomerCompanyPolicy` model + migration + audit (partially closes **G-B5** — see G-B5 row in §7 for the deferred runtime-read switch):
  * One-to-one with `Customer`. Carries the three legacy `show_assigned_staff_*` booleans (parallel to the Customer ones; **legacy Customer fields kept in place** so the ticket serializer contract is unchanged) plus four new permission-policy booleans (`customer_users_can_{create_tickets, approve_ticket_completion, create_extra_work, approve_extra_work_pricing}`), all defaulting to True.
  * Schema migration `customers/0005_customercompanypolicy.py` + data migration `customers/0006_backfill_customer_company_policy.py` that copies the visibility values into one new policy row per pre-existing Customer.
  * `customers/signals.py` registers a `post_save` handler on `Customer` that auto-creates the policy row for every new Customer with the visibility values mirrored from the parent row.
  * `CustomerCompanyPolicy` registered with the full-CRUD audit trio in [`audit/signals.py`](../../backend/audit/signals.py).
  * **Not done in 27C (deliberately):** the runtime read path for `show_assigned_staff_*` is unchanged; the new permission-policy booleans have no runtime consumer yet. Both wirings will land in 27D (resolver) / 27E (editor UI).

- ⏸ **Effective-permissions call-site migration deferred again.** No existing call site benefits from swapping in `accounts.permissions_effective.has_permission()` — every site that consumes one of the two underlying resolvers gets the byte-identical answer back through the 14 parity tests (locked in 27B). Migrating any site is busy-work for zero behavioral or readability gain. The composer was always shaped for **new** consumers (the Sprint 27E permission editor will call `effective_permissions()` to render the per-key inherit/grant/revoke state). The new `validate_permission_overrides` in Sprint 27C imports `CUSTOMER_PERMISSION_KEYS` from `customers.permissions` directly — not the composer — because the validator only needs the key allow-list, not the resolver.

### Sprint 27D — provider key wiring + customer-policy runtime ✅ **DELIVERED**
- ✅ Wired the three stubbed provider-management keys (closes **G-B9**):
  * `osius.staff.manage`, `osius.building.manage`, `osius.customer_company.manage` now route through a narrowed COMPANY_ADMIN branch in [`accounts/permissions_v2.py`](../../backend/accounts/permissions_v2.py). COMPANY_ADMIN gets these keys only when the actor is a member (via `CompanyUserMembership`) of a provider company AND (when `building_id` is given) the building belongs to one of their companies. SUPER_ADMIN: universal True (unchanged). BUILDING_MANAGER / STAFF / CUSTOMER_USER: False. Closes the latent cross-provider leak before its first consumer.
- ✅ Wired the four `CustomerCompanyPolicy` permission booleans into the customer permission resolver (finishes the permission-policy half of **G-B5**):
  * `customers.permissions.access_has_permission` consults the policy as a DENY layer between explicit `permission_overrides` and per-role defaults.
  * Precedence (high → low): (1) `is_active=False` denies everything; (2) explicit `permission_overrides[key]` wins; (3) `CustomerCompanyPolicy.<field> is False` denies the key's family; (4) otherwise the per-`access_role` default.
  * Policy can only NARROW role defaults — it cannot grant a key the role default doesn't already grant. This keeps the policy's blast radius bounded and prevents accidental scope widening.
  * **Override > policy** is the chosen precedence (vs override < policy). Rationale: an explicit per-user override is operator intent for ONE user; a policy field is the company-wide default. An override written AFTER setting the policy represents the operator's newer, more-specific intent and must beat the company default. The opposite precedence would mean an operator could never re-enable a single user without also flipping the company-wide policy. Safety is preserved because (a) `is_active=False` still beats both, and (b) the override write endpoint (Sprint 27C) has the SUPER_ADMIN-only `CUSTOMER_COMPANY_ADMIN` guard + self-edit guard + provider-side `osius.*` key rejection.
  * Lookup is anchored at `access.membership.customer_id` so the policy that applies is always the access row's own customer — never the caller-supplied `customer_id`. Defends in depth against any future call site that mismatches anchors.
- ⏸ **Effective-permissions call-site migration deferred again.** Same rationale as 27B/27C: no existing call site benefits from swapping to `has_permission()` — every consumer of the two underlying resolvers gets the byte-identical answer back through the now-31 parity tests (14 from 27B + 12 new from 27D + 5 from the 27B dict-shape suite). The composer was always shaped for **new** consumers (the Sprint 27E permission editor will call `effective_permissions()` to render per-key inherit/grant/revoke state with policy + override layered in correctly). Migrating an existing site is busy-work with no behavioral or readability gain — and post-27D the composer's answers now correctly reflect both the policy DENY layer (via `user_can` → `access_has_permission`) and the narrowed provider-management keys (via `user_has_osius_permission`), so the deferred migration is more valuable, not less. Documented here so it doesn't get lost.
- ✅ Audit coverage unchanged: the four `customer_users_can_*` fields are part of `CustomerCompanyPolicy`, which Sprint 27C already registered with the full-CRUD audit trio. No new audit signal handlers needed in 27D — the existing trio already writes a UPDATE row with the before/after diff on every policy field mutation.

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
| T-7 | `test_building_staff_visibility_can_request_assignment_update_is_audited` | `audit/tests/test_sprint27a_rbac_safety_net.py` | Sprint 27A: shipped as `@unittest.expectedFailure` documenting gap **G-B4**. **Sprint 27B: closed the gap and removed the decorator — test now passes normally.** |

**Backend code change (only one allowed):** add
`validate_access_role` on `CustomerUserBuildingAccessUpdateSerializer`
so the actor must be `UserRole.SUPER_ADMIN` to set
`access_role=CUSTOMER_COMPANY_ADMIN`.

## 10. Test footprint (Sprint 27C delta)

Tests added in Sprint 27C (test-first):

### G-B2 — `permission_overrides` + `is_active` write endpoint
[`backend/customers/tests/test_sprint27c_permission_overrides.py`](../../backend/customers/tests/test_sprint27c_permission_overrides.py) — five test classes, 14 tests:

| Class | Tests |
|---|---|
| `PermissionOverridesWriteTests` | happy path, full-replacement semantics, empty-dict clears, unknown key → 400, `osius.*` key → 400, non-bool value → 400 (all of 1/0/string/None/list/dict), non-dict payload → 400 |
| `IsActiveWriteTests` | deactivate + reactivate via PATCH |
| `SelfEditGuardTests` | actor cannot edit own access_role / permission_overrides / is_active (403 — both SUPER_ADMIN and COMPANY_ADMIN) |
| `SprintTwentyASevenGuardStillHoldsTests` | Sprint 27A guard regression net (only SUPER_ADMIN may grant CUSTOMER_COMPANY_ADMIN) |
| `CustomerSideCannotReachEndpointTests` | `User.role=CUSTOMER_USER` (even at `CUSTOMER_COMPANY_ADMIN` access_role) still hits class-level 403 |
| `AuditCoverageTests` | `permission_overrides` UPDATE writes exactly one AuditLog row with the before/after diff; `is_active` UPDATE same |

### G-B5 — CustomerCompanyPolicy
[`backend/customers/tests/test_sprint27c_customer_company_policy.py`](../../backend/customers/tests/test_sprint27c_customer_company_policy.py) — three test classes, 6 tests:

| Class | Tests |
|---|---|
| `CustomerCompanyPolicyDefaultsTests` | one-to-one constraint; safe defaults; cascade delete from Customer |
| `CustomerCompanyPolicyBackfillTests` | new Customer with non-default visibility → policy row carries the same values (live-signal version of the migration backfill) |
| `CustomerCompanyPolicyAuditTests` | CREATE and UPDATE produce exactly one AuditLog row each, with the before/after diff on changed fields |

## 11. Test footprint (Sprint 27D delta)

Tests added in Sprint 27D (test-first):

### G-B9 — provider-management keys
[`backend/accounts/tests/test_sprint27d_provider_permission_keys.py`](../../backend/accounts/tests/test_sprint27d_provider_permission_keys.py) — five test classes, 9 tests:

| Class | Tests |
|---|---|
| `SuperAdminProviderKeyTests` | SUPER_ADMIN has all three keys (no-building, building_a, building_b) |
| `CompanyAdminProviderKeyTests` | own-company True; cross-provider False (both directions); orphan COMPANY_ADMIN (no membership) False |
| `NonAdminProviderKeyTests` | BUILDING_MANAGER, STAFF, CUSTOMER_USER all False for the three keys |
| `EffectivePermissionsParityForProviderKeysTests` | composer ≡ resolver for every (actor × building × key) combination; all three keys still in `OSIUS_PERMISSION_KEYS` |

### G-B5 (resolver half) — CustomerCompanyPolicy runtime
[`backend/customers/tests/test_sprint27d_customer_company_policy_permissions.py`](../../backend/customers/tests/test_sprint27d_customer_company_policy_permissions.py) — four test classes, 15 tests:

| Class | Tests |
|---|---|
| `PolicyDenyAgainstRoleDefaultsTests` | each of the four policy fields disables its key family for basic / loc-mgr / co-admin; policy doesn't grant outside its families; policy doesn't affect unrelated keys |
| `PrecedenceTests` | override-grant beats policy-deny; override-revoke still wins over role+policy True; `is_active=False` beats both; role-default unchanged when policy=True and no override |
| `EffectivePermissionsParityWithPolicyLayerTests` | composer ≡ resolver for every customer key × representative actor × non-trivial policy/override state |
| `NoCrossCustomerPolicyLeakTests` | Customer A's policy never affects Customer B's users (both directions); policy lookup is anchored at the access row's own customer |
