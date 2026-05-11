# Sprint 23A — Domain & permissions foundation

This document is the architectural lock for Sprint 23A. It records
the model audit, the migration-path decision, the role and
permission map, the new models added in this sprint, and the
deliberate deferrals.

The cleaning/service company being modeled is **OSIUS** (spelled
exactly O-S-I-U-S). The codebase stays vendor-neutral so a second
service provider could be onboarded later; OSIUS is one concrete
`companies.Company` row (slug `osius-demo`), and Bright Facilities
is another. Role names, permission keys, and model names never
reference "OSIUS" directly.

## 1. Current-model audit (what's actually in the codebase today)

| App | Model | Meaning |
|---|---|---|
| `accounts` | `User` | every human, with a global `role` (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER / CUSTOMER_USER) |
| `companies` | `Company` | **the service provider** (OSIUS, Bright Facilities). Has `slug`, `default_language`, `is_active`. |
| `companies` | `CompanyUserMembership` | links a service-provider `Company` to a User (used by COMPANY_ADMIN scope) |
| `buildings` | `Building` | physical building, FK to service-provider `Company` |
| `buildings` | `BuildingManagerAssignment` | links a User to a Building (used by BUILDING_MANAGER scope) |
| `customers` | `Customer` | **the customer ORGANIZATION** (B Amsterdam, City Office Rotterdam). Sprint 14 docstring already states this. Legacy `Customer.building` FK is nullable and superseded by `CustomerBuildingMembership`. |
| `customers` | `CustomerBuildingMembership` | Sprint 14 M:N source-of-truth linking a customer organization to the buildings it occupies |
| `customers` | `CustomerUserMembership` | links a CUSTOMER_USER to a Customer (the customer organization) |
| `customers` | `CustomerUserBuildingAccess` | per-customer-user per-building grant (Sprint 14). Today carries only `membership` + `building`. |
| `tickets` | `Ticket` | with `assigned_to` (single FK), soft-delete fields, full SLA shape, status enum |
| `tickets` | `TicketStatusHistory` | immutable transition log |
| `audit` | `AuditLog` | signal-driven; today tracks `User / Company / Building / Customer`. |

**Key implication of the audit:** the entities Sprint 23A calls
"CustomerCompany" / "CustomerCompanyBuildingMembership" /
"CustomerUserBuildingAccess" already exist under the names
`customers.Customer` / `customers.CustomerBuildingMembership` /
`customers.CustomerUserBuildingAccess`. The vocabulary mismatch is
real but the shape is right.

## 2. Migration-path decision

Three options were on the table:

- **A** — rename `customers.Customer` → `customers.CustomerCompany`
  everywhere, plus matching member-model renames.
- **B** — keep the existing DB names; add the new fields & models
  on top; document `customers.Customer` as the canonical
  "customer organization" / "customer company".
- **C** — add new explicit `CustomerCompany` / `CustomerLocation`
  models alongside the old ones, with a back-compat layer.

**Sprint 23A picks Path B.** The reasons:

1. The Sprint 14 docstring on `customers.Customer` already declares
   that the model means "customer organization", and `Customer.building`
   has been deprecated in favour of `CustomerBuildingMembership`
   since Sprint 14. The semantic gap is naming, not data shape.
2. Path A is a multi-app destructive refactor that would touch
   every serializer, view, scope helper, audit-log filter,
   Playwright test, and i18n key. The risk-to-value ratio is
   wrong for a foundation sprint that must not break Sprint 22.
3. Path C creates two parallel notions of "customer" in the DB
   for an unbounded transition period — exactly the situation
   the audit log instrumentation was designed to avoid.
4. All four UserRole values stay unchanged (no production data
   migration of the `role` column). The new `STAFF` value is
   appended.

## 3. New / changed models in Sprint 23A

All schema changes are **additive** — no column drops, no required
fields without sane defaults, no destructive index changes. Each
migration is therefore reversible by `migrate <app> <prev>`.

### 3.1 `accounts.UserRole` — append `STAFF`

```python
class UserRole(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super admin"
    COMPANY_ADMIN = "COMPANY_ADMIN", "Company admin"
    BUILDING_MANAGER = "BUILDING_MANAGER", "Building manager"
    STAFF = "STAFF", "Staff"           # NEW in Sprint 23A
    CUSTOMER_USER = "CUSTOMER_USER", "Customer user"
```

No data migration: existing users keep their role. New value is
opt-in via the staff seeding/invitation flow (built in 23B).

### 3.2 `accounts.StaffProfile` (new model)

```python
class StaffProfile(models.Model):
    user = OneToOneField(User, related_name="staff_profile", on_delete=CASCADE)
    phone = CharField(max_length=64, blank=True)
    internal_note = TextField(blank=True)
    can_request_assignment = BooleanField(default=True)
    is_active = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

One row per User where `user.role == STAFF`. `is_active` lets an
admin disable a staff member without dropping the user row.

### 3.3 `buildings.BuildingStaffVisibility` (new model)

```python
class BuildingStaffVisibility(models.Model):
    building = ForeignKey(Building, related_name="staff_visibility", on_delete=CASCADE)
    user = ForeignKey(User, related_name="building_visibility", on_delete=CASCADE)
    can_request_assignment = BooleanField(default=True)
    created_at = DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("building", "user")]
```

Mirrors `BuildingManagerAssignment` but for STAFF role. A staff
user with a row here can see *all* tickets/work for that building
(read-only on tickets they aren't assigned to). Without a row,
staff only see tickets they are assigned to.

### 3.4 `customers.CustomerUserBuildingAccess` — three new fields

```python
class AccessRole(models.TextChoices):
    CUSTOMER_USER = "CUSTOMER_USER", "Customer user"
    CUSTOMER_LOCATION_MANAGER = "CUSTOMER_LOCATION_MANAGER", "Location manager"
    CUSTOMER_COMPANY_ADMIN = "CUSTOMER_COMPANY_ADMIN", "Company admin"

class CustomerUserBuildingAccess(models.Model):
    # existing:
    membership = ForeignKey(CustomerUserMembership, ...)
    building = ForeignKey(Building, ...)
    created_at = ...
    # NEW in Sprint 23A:
    access_role = CharField(choices=AccessRole.choices, default=AccessRole.CUSTOMER_USER, max_length=32)
    permission_overrides = JSONField(default=dict, blank=True)
    is_active = BooleanField(default=True)
```

Per-building role lets the same User be `CUSTOMER_COMPANY_ADMIN`
in B1 Amsterdam and `CUSTOMER_USER` in B2 Amsterdam under the same
Customer. `permission_overrides` is a `{permission_key: bool}` map
that grants or revokes specific permissions on top of the role's
defaults. `is_active=False` hides the grant from scope without
deleting the audit history.

Backfill: every existing row defaults to
`access_role=CUSTOMER_USER`, `permission_overrides={}`,
`is_active=True` → zero behaviour change for Sprint 22.

### 3.5 `customers.Customer` — three new contact-visibility flags

```python
class Customer(models.Model):
    # ... existing fields ...
    show_assigned_staff_name = BooleanField(default=True)
    show_assigned_staff_email = BooleanField(default=True)
    show_assigned_staff_phone = BooleanField(default=True)
```

Per the spec, the default is "show everything", flipping to
`False` hides the field at the ticket-serializer layer for
customer users. Sprint 23A only ships the **model fields and the
serializer hook** — the admin UI for editing them is deferred to
Sprint 23B.

Putting these on `Customer` (vs a separate
`CustomerContactVisibilityPolicy` table) follows the spec's "If
easier and safe, start as fields on CustomerCompany and document
that it can be extracted later" guidance. Extracting later is a
3-line migration if needed.

### 3.6 `tickets.TicketStaffAssignment` (new model)

```python
class TicketStaffAssignment(models.Model):
    ticket = ForeignKey(Ticket, related_name="staff_assignments", on_delete=CASCADE)
    user = ForeignKey(User, related_name="ticket_staff_assignments", on_delete=CASCADE)
    assigned_by = ForeignKey(User, related_name="staff_assignments_made", null=True, on_delete=SET_NULL)
    assigned_at = DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("ticket", "user")]
```

The existing `Ticket.assigned_to` (single FK) is **NOT** removed
or repurposed in Sprint 23A. It stays as the "primary assignee"
the existing tests and UI both read. `TicketStaffAssignment` is
the new M:N for the multi-staff list. A ticket can have many
rows; any one of those staff completing the work moves it to
"waiting for manager review" (workflow update deferred to 23B).

### 3.7 `tickets.StaffAssignmentRequest` (new model)

```python
class AssignmentRequestStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"

class StaffAssignmentRequest(models.Model):
    staff = ForeignKey(User, related_name="assignment_requests", on_delete=CASCADE)
    ticket = ForeignKey(Ticket, related_name="assignment_requests", on_delete=CASCADE)
    status = CharField(choices=...choices, default=PENDING, max_length=16)
    requested_at = DateTimeField(auto_now_add=True)
    reviewed_by = ForeignKey(User, related_name="reviewed_assignment_requests", null=True, blank=True, on_delete=SET_NULL)
    reviewed_at = DateTimeField(null=True, blank=True)
    reviewer_note = TextField(blank=True)
```

Internal to OSIUS — never returned by any serializer the customer
can hit. The minimal API is implemented in 23A (`list / create /
approve / reject`); the UI surface is deferred to 23B.

## 4. Roles

| Role | What it means today (after Sprint 23A) |
|---|---|
| `SUPER_ADMIN` | platform admin across every service-provider company. No scope limits. |
| `COMPANY_ADMIN` | admin of one service-provider company (e.g. OSIUS). Sees that company's buildings/customers/tickets/users. |
| `BUILDING_MANAGER` | OSIUS-side manager for one or more `Building`s via `BuildingManagerAssignment`. Spec calls this "OSIUS Building Manager". |
| `STAFF` (new) | OSIUS-side field staff. Always sees tickets where they are listed in `TicketStaffAssignment`. May see other tickets in a building if they hold a `BuildingStaffVisibility` row for that building. |
| `CUSTOMER_USER` | customer-side user. Per-building role is held on `CustomerUserBuildingAccess.access_role` (one of `CUSTOMER_USER`, `CUSTOMER_LOCATION_MANAGER`, `CUSTOMER_COMPANY_ADMIN`). |

> **Important**: the global `User.role` for every customer-side
> user stays at `CUSTOMER_USER`. The CUSTOMER_LOCATION_MANAGER and
> CUSTOMER_COMPANY_ADMIN ideas are *per-building access roles*, not
> global role values. This keeps role checks one-dimensional in
> existing code paths while still letting one user hold two
> different per-building roles under the same customer.

## 5. Permission keys

The spec lists ~25 permission keys. Sprint 23A ships only the
helper that resolves *any* permission key against an access row's
`access_role` + `permission_overrides`, plus the small set of keys
the existing ticket/permission code actually needs to consult
after this sprint. The full key set is documented here so 23B can
extend without reshaping the resolution helper.

**Customer-side defaults per `access_role`** (Sprint 23A
implementation lives in `customers/permissions.py::CUSTOMER_ROLE_DEFAULTS`):

| Permission key | CUSTOMER_USER | CUSTOMER_LOCATION_MANAGER | CUSTOMER_COMPANY_ADMIN |
|---|---|---|---|
| `customer.ticket.create` | ✓ | ✓ | ✓ |
| `customer.ticket.view_own` | ✓ | ✓ | ✓ |
| `customer.ticket.view_location` |  | ✓ | ✓ |
| `customer.ticket.view_company` |  |  | ✓ |
| `customer.ticket.approve_own` | ✓ | ✓ | ✓ |
| `customer.ticket.approve_location` |  | ✓ | ✓ |
| `customer.users.invite` |  |  | ✓ |
| `customer.users.manage` |  |  | ✓ |
| `customer.users.assign_location_role` |  | ✓ | ✓ |
| `customer.users.manage_permissions` |  |  | ✓ |
| `customer.extra_work.*` | mirrors `customer.ticket.*` (modelled but inert in 23A) |

Resolution: `permission_overrides[key]` wins if present (`True` =
grant, `False` = revoke), else the role default applies. A row
with `is_active=False` resolves every permission to `False`.

**OSIUS-side defaults per global role** (Sprint 23A implementation
lives in `accounts/permissions_v2.py::OSIUS_ROLE_DEFAULTS`):

| Permission key | STAFF | BUILDING_MANAGER | COMPANY_ADMIN | SUPER_ADMIN |
|---|---|---|---|---|
| `osius.staff.complete_assigned_work` | ✓ | – | – | ✓ |
| `osius.staff.view_building_work` | conditional on `BuildingStaffVisibility` | ✓ | ✓ | ✓ |
| `osius.staff.request_assignment` | conditional on `StaffProfile.can_request_assignment` AND `BuildingStaffVisibility.can_request_assignment` | – | – | ✓ |
| `osius.ticket.assign_staff` |  | ✓ | ✓ | ✓ |
| `osius.ticket.manager_review` |  | ✓ | ✓ | ✓ |
| `osius.assignment_request.approve` |  | (own buildings only) | ✓ | ✓ |
| `osius.assignment_request.reject` |  | (own buildings only) | ✓ | ✓ |
| `osius.building.manage` |  |  | ✓ | ✓ |
| `osius.customer_company.manage` |  |  | ✓ | ✓ |

## 6. Scoping rules

### Tickets — customer side

`scope_tickets_for(user)` (in `accounts/scoping.py`) gains a new
branch when `user.role == CUSTOMER_USER`:

1. **`CUSTOMER_COMPANY_ADMIN` access at any building of the
   customer** → sees every ticket where `ticket.customer ==
   user's customer`, regardless of building.
2. **`CUSTOMER_LOCATION_MANAGER` access** → sees every ticket
   where `(ticket.customer, ticket.building) ∈ {(customer, b) for
   each access row where role >= LOCATION_MANAGER and is_active}`.
3. **`CUSTOMER_USER` access (default)** → keeps Sprint 14
   semantics: sees only tickets where the user is `created_by`
   AND the (customer, building) pair matches one of their access
   rows.

A customer-side user with `view_location` / `view_company`
permission via override sees the same set even if the role
default would have hidden it.

### Tickets — OSIUS side

1. `STAFF` (new):
   - Always sees tickets where they are in `TicketStaffAssignment`.
   - PLUS tickets in any building where they hold a
     `BuildingStaffVisibility` row.
2. `BUILDING_MANAGER`: unchanged — tickets in their assigned
   buildings.
3. `COMPANY_ADMIN`: unchanged — tickets in their service-provider
   company.
4. `SUPER_ADMIN`: unchanged — all tickets.

### Customer isolation guarantee

A `CustomerUserBuildingAccess` row links a User to **exactly one
Customer** (via `membership.customer`). The scope helper filters
by `customer_id IN {customer ids the user holds access to}`, so a
ticket belonging to Customer A is mathematically never returned
to a Customer B user even when both customers share the same
building. Verified by tests 3, 4, 5, 6 below.

## 7. Staff visibility and contact-visibility rules

### Visibility (what STAFF sees)

- A `STAFF` user without any `BuildingStaffVisibility` row sees
  only the tickets in `TicketStaffAssignment` they are part of.
- A `BuildingStaffVisibility` row adds full read visibility on
  tickets in that building, regardless of assignment.
- A `BuildingStaffVisibility` row with
  `can_request_assignment=True` lets the staff user POST a
  `StaffAssignmentRequest` for any unassigned ticket in that
  building.

### Contact visibility (what the CUSTOMER sees about assigned staff)

`TicketDetailSerializer` (for `CUSTOMER_USER` role only) reads
the three `Customer.show_assigned_staff_*` flags before emitting
the assigned-staff list:

- `show_assigned_staff_name=True` → emit each assignee's
  `full_name` (falling back to email-local-part).
- `show_assigned_staff_email=True` → emit `email`.
- `show_assigned_staff_phone=True` → emit
  `staff_profile.phone` (if set).
- All three flags False → emit a single anonymous label
  `"Assigned to the OSIUS team"` (i18n key:
  `tickets.assigned_team_anonymous`).

The serializer wiring is implemented in 23A. The admin UI to
flip these flags is deferred to 23B.

## 8. Staff assignment request rules

- A `StaffAssignmentRequest` is created by a STAFF user POSTing
  `/api/staff-assignment-requests/` with `{ticket_id}`. The view
  validates:
  1. The ticket is in scope of the staff user (visible building
     or pre-assigned).
  2. The staff user has
     `osius.staff.request_assignment` after override resolution.
  3. No other request from the same staff+ticket is already
     `PENDING`.
- A BUILDING_MANAGER can `approve` / `reject` requests for their
  assigned buildings. Approving creates a `TicketStaffAssignment`
  row.
- COMPANY_ADMIN and SUPER_ADMIN can approve/reject any request.
- The serializer **never** returns assignment requests to a
  CUSTOMER_USER. Customers physically cannot list, view, or know
  about the request queue.

## 9. Audit coverage

The existing `audit.signals` machinery is signal-driven. Sprint
23A registers the new models in the registered-tracker list:

- `customers.CustomerBuildingMembership` (already)
- `customers.CustomerUserMembership` (already)
- `customers.CustomerUserBuildingAccess` (already; new
  fields covered automatically by the diff-based change recorder)
- `buildings.BuildingManagerAssignment` (already)
- `accounts.StaffProfile` (NEW)
- `buildings.BuildingStaffVisibility` (NEW)
- `tickets.TicketStaffAssignment` (NEW)
- `tickets.StaffAssignmentRequest` (NEW)

The `audit.signals` registry approach means adding a model is a
one-line change in `audit/apps.py`'s `ready()`; no per-model
handler code.

## 10. Deliberate deferrals (Sprint 23B+)

These are explicitly NOT shipped in 23A. None of them is
blocking for the foundation:

- **Admin UI** for all new management surfaces (StaffProfile
  edit, BuildingStaffVisibility toggle, CustomerUserBuildingAccess
  role + permission_overrides editor, Customer contact-visibility
  policy editor). Backend APIs exist; UI is 23B.
- **Extra Work models, workflow, dashboard, pricing.** Foundation
  fields documented but no models added.
- **Ticket workflow changes** (multi-staff completion, "any one
  completes → manager review"). The current state machine stays
  unchanged; the new `TicketStaffAssignment` rows are
  informational only in 23A. The workflow change is staged for
  23B with its own state-machine test pass.
- **Customer-side `view_location` / `view_company` permission
  override UI.** Backend permission resolver implemented; admin
  toggle UI is 23B.
- **i18n strings for new admin UI.** Only the customer-facing
  "Assigned to the OSIUS team" anonymous label string ships in
  23A (en + nl). All admin-UI strings land in 23B with the UI.

## 11. Migration risk notes

| Migration | Risk | Mitigation |
|---|---|---|
| `accounts/000X_add_staff_role` | LOW. TextChoices is just a Python validator; no DB enum. | Existing rows unchanged. |
| `accounts/000X_add_staffprofile` | LOW. New table, no FK back-references on existing rows. | Reversible by `migrate accounts <prev>`. |
| `buildings/000X_add_staff_visibility` | LOW. New table, no FK back-references on existing rows. | Reversible. |
| `customers/000X_add_access_role_overrides_isactive` | LOW. Three new fields, all with safe defaults. | `default=...` on `add_field` is the standard reversible pattern. Backfill is implicit. |
| `customers/000X_add_contact_visibility_flags` | LOW. Three new boolean fields, default True. | Reversible. |
| `tickets/000X_add_ticket_staff_assignment` | LOW. New M:N-via-through table. | Reversible. |
| `tickets/000X_add_staff_assignment_request` | LOW. New table. | Reversible. |

All migrations land in separate files per app for surgical
rollback. No data migration is required because every new column
has a safe default.

## 12. Test results

(Filled in after the test run — kept in the file so an archive
reader sees the exact green/red status of the foundation.)

See section 14 at the bottom of this file.

## 13. Next sprint recommendation

**Sprint 23B** should pick up exactly four things:

1. Admin UI for StaffProfile, BuildingStaffVisibility, the new
   CustomerUserBuildingAccess columns, and Customer
   contact-visibility flags.
2. Ticket workflow update: any assigned staff completing the
   work moves the ticket to `WAITING_MANAGER_REVIEW` (new
   intermediate state OR repurposed
   `WAITING_CUSTOMER_APPROVAL` depending on the workflow
   discussion).
3. Extra Work models (parallel to Ticket but with the spec's
   different category list + status set).
4. Customer-side `view_location` / `view_company` permission
   editor surfacing.

---

## 14. Test results (Sprint 23A implementation run)

| Step | Result |
|---|---|
| `manage.py check` | **0 issues** |
| All 4 new migrations | Applied cleanly to the live demo DB (`accounts.0003`, `buildings.0002`, `customers.0004`, `tickets.0006`) |
| New Sprint 23A test module (`accounts.tests.test_sprint23a_foundation`) | **17 / 17 OK** (all brief-listed cases pass) in 1.4 s |
| Full backend test suite | **569 / 569 OK** (was 552 on master; exactly +17 from the new module — zero regressions in the pre-existing 552) in 519 s |
| `npm run build` (Vite) | Clean, 508 ms, 2775 modules — confirms the new i18n key `tickets.assigned_team_anonymous` is valid in EN + NL |
| Playwright suite | Not re-run in 23A: no React component changed. The only frontend file touched is `i18n/{en,nl}/common.json` (one new key); no Playwright test asserts on it. The Sprint 22 green run at commit `52efbec` is the last authoritative pass. |

### Files added or changed

```
backend
  accounts/models.py                                   — +STAFF role + StaffProfile model
  accounts/scoping.py                                  — extended building_ids_for + scope_tickets_for
  accounts/permissions_v2.py                           — NEW (OSIUS-side resolver)
  accounts/migrations/0003_alter_invitation_role_alter_user_role_staffprofile.py — NEW
  accounts/tests/test_sprint23a_foundation.py          — NEW (17 tests)
  buildings/models.py                                  — +BuildingStaffVisibility model
  buildings/migrations/0002_buildingstaffvisibility.py — NEW
  customers/models.py                                  — Customer.show_assigned_staff_*, CustomerUserBuildingAccess.access_role/permission_overrides/is_active + AccessRole enum
  customers/permissions.py                             — NEW (customer-side resolver)
  customers/migrations/0004_customer_show_assigned_staff_email_and_more.py — NEW
  tickets/models.py                                    — +TicketStaffAssignment + StaffAssignmentRequest + AssignmentRequestStatus
  tickets/migrations/0006_staffassignmentrequest_ticketstaffassignment.py — NEW
  tickets/serializers.py                               — TicketDetailSerializer.assigned_staff with contact-visibility hook
  tickets/views_staff_requests.py                      — NEW (minimal CRUD + approve/reject)
  tickets/urls.py                                      — router for staff-assignment-requests
  config/urls.py                                       — mount /api/staff-assignment-requests/
  audit/signals.py                                     — register 4 new models (StaffProfile + StaffAssignmentRequest CRUD trio; BuildingStaffVisibility + TicketStaffAssignment membership pattern)
frontend
  src/i18n/en/common.json                              — +tickets.assigned_team_anonymous = "Assigned to the OSIUS team"
  src/i18n/nl/common.json                              — +tickets.assigned_team_anonymous = "Toegewezen aan het OSIUS-team"
docs
  docs/architecture/sprint-23a-domain-permissions-foundation.md — NEW
```

No backend file was deleted. Every migration is additive
(reversible by `migrate <app> <prev>`).

### Honest deferral list

(Already enumerated in §10 above; re-listing here so the reader
sees the final 23A vs 23B split next to the test results.)

- Admin UI for every new management surface — **23B**.
- Full Extra Work models / workflow / dashboard / pricing — **23B+**.
- Multi-staff "any-one-completes → manager review" workflow
  state-machine change — **23B**.
- Customer-side `view_location` / `view_company` permission override
  admin toggle UI — **23B**.
- Per-tenant audit signal for customer-side ticket APPROVAL
  events (the existing audit shape already records the
  TicketStatusHistory row; deciding whether to also audit the
  approve action explicitly is **23B**).
- StaffAssignmentRequest cancellation by the staff member who
  filed it (`POST .../cancel/`) — **23B**.

These deferrals are reflected in the architecture doc so an
incoming Sprint 23B reviewer can plan UI and workflow work
without re-running the audit.
