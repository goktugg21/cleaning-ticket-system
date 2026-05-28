# Cleaning Ticket System — Business Logic, Roles, Permissions, and Workflows

This document explains how the system is supposed to work in plain English.

It is intentionally written as product logic, not as code logic. Developers and AI tools should read this before changing the backend or frontend. If the current code behaves differently from this document, the developer should stop, report the mismatch, and propose a safe fix instead of guessing.

---

## 1. The basic idea of the system

This system is for a cleaning/service provider company that serves multiple customer companies.

The provider company manages buildings, cleaning work, tickets, extra work requests, customer contacts, customer users, pricing, proposals, and operational assignments.

Customer companies use the system to report issues, request extra work, approve work when approval is needed, and see the work related to their own company and their own buildings.

The most important rule is simple:

A user should only see and do things that make sense for their role, their company, their assigned buildings, and their explicit permissions.

---

## 2. Provider company vs customer company

There are two different company concepts.

### Provider company

The provider company is the cleaning/service company.

In the current business situation, there is basically one provider company. Because of this, provider-side permission rules can stay simple for now.

Provider-side people are:

- Super Admin
- Provider Company Admin
- Building Manager
- Staff / Field Worker

The provider company owns the service operation. It manages buildings, customers, pricing, extra work, staff assignments, provider-side notes, and provider-side approvals.

### Customer company

A customer company is a client of the provider company.

Each customer company can have its own buildings, users, contacts, contract prices, and special rules.

Customer-side people are:

- Customer Company Admin
- Customer Location Manager
- Customer User

Each customer company may have a different contract with the provider company. This is very important for Extra Work pricing.

For example:

Customer A may have contract pricing for window cleaning but not for grass cutting.

Customer B may have contract pricing for grass cutting but not for window cleaning.

So Extra Work must not work the same way for every customer. It depends on that customer company's contract prices.

---

## 3. Core objects in the system

### Building

A building is a location where work happens.

A building can be linked to one or more customer companies.

A user should not see a building unless their role, company, or assigned permissions allow it.

### Room / area

A room or area is a smaller location inside a building. Tickets and work can be tied to rooms/areas when needed.

### Ticket

A ticket is normal operational work.

Examples:

- Something is dirty.
- Something is broken.
- A customer reports an issue.
- A provider employee creates a task.
- A staff member is assigned to do work.

A ticket may need customer approval at some points, depending on the workflow.

### Extra Work

Extra Work is work outside the normal cleaning routine.

Examples:

- Window cleaning
- Deep cleaning
- Grass cutting
- Special event cleaning
- One-time cleaning request
- Any work that may have a separate price or contract rule

Extra Work can follow two different paths:

1. Contract-priced Extra Work
2. Non-contract Extra Work that needs a proposal

This is explained in detail later.

### Service

A service is an item the provider can perform.

Examples:

- Window cleaning per square meter
- Grass cutting per square meter
- Floor polishing per hour
- Deep cleaning per room

Services are the general catalog.

### Customer-specific contract price

A customer-specific contract price says:

For this customer company, this service has this agreed price.

Example:

For Customer A:
- Window cleaning = EUR 5 per square meter

For Customer B:
- Grass cutting = EUR 2 per square meter

This is not the same as the general service catalog. The same service can have different prices for different customers.

### Proposal

A proposal is a price offer prepared by the provider when the requested Extra Work is not already covered by the customer's contract pricing.

A proposal is sent to the customer for approval or rejection.

A proposal can have multiple line items.

A proposal has customer-visible information and provider-only information.

Provider-only internal notes must never be visible to customers or staff when the note is financial/management-only.

---

## 4. Role hierarchy

## 4.1 Super Admin

The Super Admin is the highest-level system user.

Super Admin can:

- See all provider data
- See all customer companies
- See all buildings
- See all tickets
- See all extra work
- Manage provider admins
- Manage customer users
- Manage building managers
- Manage staff
- Manage permissions
- Manage global settings
- Override decisions when the system allows it
- See provider-only information
- Configure whether Provider Admins can manage customer-specific permissions

Super Admin should be able to fix or configure anything in the system.

Super Admin actions that change customer decisions or financial outcomes should still be logged clearly.

---

## 4.2 Provider Company Admin

Provider Company Admin is the main admin role for the provider company.

Because there is currently only one provider company, this role can be treated as the main operational admin role.

By default, Provider Company Admin can:

- Manage customer companies
- Manage buildings
- Manage customer-building links
- Manage customer contacts
- Manage customer users, except where restricted
- Manage staff and building managers
- Manage customer-specific pricing
- Manage services
- Create and manage tickets
- Create and manage Extra Work
- Prepare proposals
- Send proposals to customers
- Override customer approval/rejection when allowed
- Manage customer-specific permissions by default
- See provider-only notes and financial/provider-side information

Super Admin can limit or configure what Provider Company Admin is allowed to manage.

Provider Company Admin should not silently act as the customer. If they approve or reject something on behalf of a customer, the system must make that clear and store who did it and why.

---

## 4.3 Building Manager

A Building Manager belongs to the provider side and is assigned to one or more buildings.

Inside their assigned buildings, a Building Manager can by default move operational work forward and can also record a customer decision on the customer's behalf when needed.

When a Building Manager approves or rejects something that normally belongs to the customer, that is an **override**, not a normal customer approval.

Default Building Manager behavior (inside assigned buildings):

- Can see assigned buildings.
- Can see tickets in assigned buildings.
- Can manage operational status for work in assigned buildings.
- Can create or manage Extra Work for assigned buildings.
- Can prepare proposals for assigned buildings.
- **Can override a customer approval / rejection on the customer's behalf, by default.** This is not a normal customer approval — it is a provider-side override of a customer decision.
- Can see provider-side operational notes for assigned buildings.
- Can see staff instructions related to assigned work.

Override rules (when a Building Manager — or any provider-side user — records a customer-side decision on the customer's behalf):

- The acting user **must** enter an override reason.
- The system **must** record who did it, when, what decision they made, and the reason.
- The frontend must show a clear warning / confirmation before the action is committed.
- The backend **must** reject the action if the override reason is missing or blank.
- The audit / history row for the decision must clearly mark it as a provider-side override of a customer decision — never as if the customer clicked the button themselves.
- This default override capability **can be removed** for a specific Building Manager (or any provider-side user) by an explicit permission revoke. Removing it leaves the rest of the role's defaults intact.

A Building Manager still cannot, by default:

- See buildings they are not assigned to.
- Manage customer user permissions.
- Change provider-company-wide settings.
- See provider-level financial / commercial internal notes unless explicitly allowed.
- See customer-company areas outside their assigned building scope.

Each of the items above can be granted by an explicit permission to a specific Building Manager when needed — the rule above only states the default.

---

## 4.4 Staff / Field Worker

Staff are the people who do the actual work.

Staff should have a clean operational view. They should not see management or pricing details.

Staff should see Extra Work only after it has become an actual assigned job/ticket/task.

Correct Staff rule:

Staff sees the operational part after Extra Work is approved and assigned to them as work.

Staff should not see:

- Proposal drafts
- Proposal prices
- Customer approval/rejection controls
- Provider financial notes
- Internal margin/cost notes
- Customer contract price management
- Permission management
- Customer company management
- Provider admin settings

Staff can see:

- Assigned work.
- Building / location where they need to work.
- Work description.
- Operational instructions.
- Staff-visible notes (the staff-instruction / operational note category in §9).
- Attachments needed for the job.
- Status actions needed for their assignment, such as start, complete, report issue, or add operational update.

Staff completion evidence:

When a Staff user moves their assigned work onward (e.g. marks it ready for manager review or customer approval), they must attach completion evidence — either a non-empty staff completion note or at least one visible attachment (a photo of the work). This requirement applies to Staff actors only; provider admins and Building Managers do not have this gate. See the "Staff completion note" category in §9 and the Rule-4 wording in §4 of this document.

Staff should not approve customer decisions.

Staff should not prepare price proposals.

Staff should not see internal notes like "our cost is EUR X" or "margin is low".

But staff may need notes like:

- "The windows are very dirty; bring stronger material."
- "Use ladder."
- "Customer asked to avoid entrance B."
- "Bring extra cloths."

So the system needs different note visibility levels.

---

## 4.5 Customer Company Admin

Customer Company Admin is the highest customer-side user for one customer company.

Customer Company Admin can usually:

- See their own customer company
- See buildings linked to their customer company, depending on permissions
- See tickets for their customer company
- Create tickets
- Request Extra Work
- Approve or reject proposals for their company
- See customer-visible prices and proposal details
- See customer-visible comments and attachments
- Manage some customer-side users if allowed by provider permissions

Customer Company Admin should not:

- Create another Customer Company Admin by default
- Manage provider-side users
- See other customer companies
- See provider-only notes
- See staff-only internal operational notes unless those are made customer-visible
- See provider financial/cost/margin notes
- Change provider settings
- Manage provider permissions

Important correction (who creates / promotes Customer Company Admins):

A Customer Company Admin must **not** be able to create or promote another Customer Company Admin themselves.

Power to create or promote a Customer Company Admin sits on the platform / provider side, not the customer side:

- Super Admin can always create or promote a Customer Company Admin.
- Provider Company Admin can, by default, manage customer-side users for customers under their provider company, **including assigning the Customer Company Admin access role**, unless Super Admin has restricted that specific Provider Admin through permissions.
- Super Admin can restrict / revoke this provider-admin capability per-Provider-Admin (or globally) when the situation requires it.

If a Customer Company Admin needs to manage lower-level customer users (Customer Location Manager, Customer User) within their own customer scope, that can be granted by an explicit permission. The "create another Customer Company Admin" path is **always** provider-side; it never sits inside a customer organisation's own admin.

Lower-user management capability (B4):

The backend now exposes the four customer-user-management endpoints to a Customer Company Admin actor whose access row resolves the existing `customer.users.manage` permission to True:

- `GET / POST /api/customers/<id>/users/` — list / link a Customer User to the CCA's own customer.
- `DELETE /api/customers/<id>/users/<user_id>/` — unlink a lower customer user.
- `GET / POST /api/customers/<id>/users/<user_id>/access/` — list / grant per-building access at a building where the CCA holds `customer.users.manage`.
- `PATCH / DELETE /api/customers/<id>/users/<user_id>/access/<building_id>/` — edit / revoke a lower user's per-building access (subject to the per-building manage check).

CCA hard constraints, enforced server-side:

- CCA can manage only **Customer User** and **Customer Location Manager** targets. CCA cannot edit, remove, or grant new access on a target who currently holds a `CUSTOMER_COMPANY_ADMIN` access row under the same customer (HTTP 403, stable code `cca_cannot_manage_cca`).
- CCA cannot set `access_role=CUSTOMER_COMPANY_ADMIN` via any PATCH payload — the existing H-7 serializer guard rejects with HTTP 400.
- CCA cannot operate at a building where their own access row does not resolve `customer.users.manage` (HTTP 403, stable code `cca_lacks_building_manage`).
- CCA cannot self-manage their own membership or access rows.
- CCA cannot reach customer-policy or customer↔building-link endpoints; those stay Provider Admin / Super Admin only.
- Cross-customer URL typing returns HTTP 403 / 404 via the same guard that blocks cross-company COMPANY_ADMIN access.

B5 (now implemented) — Super Admin-controlled policy toggle for whether Provider Company Admin may manage Customer Company Admin users/permissions on customers under their provider company.

The toggle lives on the provider company: `companies.Company.provider_admin_may_manage_customer_company_admins` (BooleanField, default True; migration `companies/0002_b5_provider_admin_may_manage_customer_company_admins.py`). The boolean is audited automatically through the existing full-CRUD `Company` audit handler — flipping it lands one `AuditLog` UPDATE row with the before/after diff (matrix H-10).

- **Default (True):** Provider Company Admin retains every CCA-management capability they had after B4: create, grant, promote, edit, demote, and revoke the CUSTOMER_COMPANY_ADMIN access role on any customer under their provider company. This preserves operational behaviour for the current one-provider deployment.
- **Disabled (False):** Provider Company Admin cannot create, grant, promote, edit, demote, revoke, or otherwise manage any CCA-tier user/access for customers under that provider company. Only Super Admin may do so. Provider Admin's ability to manage lower customer users (Customer User / Customer Location Manager + their `permission_overrides` / `is_active`) is **not** affected by this toggle.

Backend enforcement when policy=False (Provider Admin actor):

- `PATCH /api/customers/<cid>/users/<uid>/access/<bid>/` on a row whose current `access_role` is CCA — blocked at the view layer with HTTP 403 + stable code `cca_policy_disabled`. Covers `access_role` flips (demote), `permission_overrides` edits, and `is_active=False` revoke.
- `DELETE /api/customers/<cid>/users/<uid>/access/<bid>/` on a CCA-tier row — blocked with HTTP 403 + `cca_policy_disabled`.
- `DELETE /api/customers/<cid>/users/<uid>/` on a target that holds any CCA access under this customer — blocked with HTTP 403 + `cca_policy_disabled` (a membership delete cascades to all access rows including CCA-tier ones).
- `POST /api/customers/<cid>/users/<uid>/access/` extending a CCA target's reach to a new building — blocked with HTTP 403 + `cca_policy_disabled` (the new row would default to `CUSTOMER_USER` tier, but it still extends a CCA user's reach).
- `PATCH /api/customers/<cid>/users/<uid>/access/<bid>/` setting `access_role=CCA` on a non-CCA target (the grant path) — blocked at the serializer layer (`validate_access_role`) with HTTP 400 (pre-B5 invariant shape; this is the original H-7 rejection code).

Out of scope for the toggle (not blocked):

- `PATCH /api/customers/<cid>/policy/` (CustomerCompanyPolicy) — affects all customer-side users, not specifically CCAs. Stays open to Provider Admin.
- `DELETE /api/customers/<cid>/buildings/<bid>/` (customer↔building link) — a building-level operation, not a per-CCA-user operation. Stays open to Provider Admin.
- Editing a CCA user's lower-tier access row on a different building (e.g. user is CCA on building A and CUSTOMER_USER on building B; Provider Admin edits building B's row). The row-level check fires only when the row itself is CCA, mirroring the B4 CCA-actor guard shape.

Toggle write authority:

- Only Super Admin may flip the policy. The write surface is the existing `PATCH /api/companies/<id>/` endpoint; the field is exposed on the `CompanySerializer` with a field validator that rejects writes from any actor whose role is not SUPER_ADMIN (HTTP 400).
- Provider Company Admin retains PATCH access to other Company fields (name, slug, default_language) but cannot change the toggle itself.
- Customer Company Admin still cannot create another Customer Company Admin under any policy state — the H-7 leg of `validate_access_role` rejects every non-SA / non-COMPANY_ADMIN actor unconditionally.

Effective-permissions endpoint:

- New derived action `can_manage_customer_company_admins` reflects the live policy. True for Super Admin always; True for Company Admin in scope only when the toggle is True; False otherwise (including for Building Manager, Staff, Customer Company Admin, and lower customer users).
- `can_manage_customer_permissions` for Provider Admin **remains True** regardless of the toggle — B5 narrows only CCA-tier management, not the broader lower-user permission management codified in B4.
- The `notes` block surfaces the live policy state when the target is a Company Admin (both the enabled and the disabled wording call out that lower-user management is unaffected).

B5 does not change Staff extra-work privacy, cart-first Extra Work pricing/proposal workflow, BM defaults, or the ticket/customer override workflow.

B6 (now implemented) — Building Manager defaults are now selectively revocable per-(BM, building) through the existing `osius.*` permission system.

Two new permission keys, both default `True` for any BM assigned to a building:

- `osius.building_manager.override_customer_decision` — controls whether the BM may approve / reject on behalf of the customer on tickets (`WAITING_CUSTOMER_APPROVAL → APPROVED|REJECTED`), Extra Work requests (`PRICING_PROPOSED → CUSTOMER_APPROVED|CUSTOMER_REJECTED`), and proposals (`SENT → CUSTOMER_APPROVED|CUSTOMER_REJECTED`).
- `osius.building_manager.prepare_extra_work_proposal` — controls whether the BM may create, edit, send, or cancel extra-work proposals at the building (proposal POST, line POST/PATCH/DELETE, proposal transitions `DRAFT → SENT`, `DRAFT → CANCELLED`, `SENT → CANCELLED`).

Storage: per-(BM, building) overrides live on the new `BuildingManagerAssignment.permission_overrides` JSONField (migration `buildings/0005_*`). An explicit `False` entry for either key narrows the BM's default for that one (BM, building) pair to `False`; a missing entry or any non-`False` value (including `True`) means "use the default" — which today resolves `True`. Only `False` values have semantic effect, so toggling a key back to `True` is equivalent to clearing it.

Backend enforcement when a key resolves False for a BM actor:

- `POST /api/tickets/<id>/status/` driving `WAITING_CUSTOMER_APPROVAL → APPROVED|REJECTED` — `TransitionError` with stable code `bm_override_disabled` (HTTP 400). No state mutation, no `TicketStatusHistory` row.
- `POST /api/extra-work/<ew_id>/transition/` driving `PRICING_PROPOSED → CUSTOMER_APPROVED|CUSTOMER_REJECTED` — same code, same shape.
- `POST /api/extra-work/<ew_id>/proposals/<pid>/transition/` driving `SENT → CUSTOMER_APPROVED|CUSTOMER_REJECTED` — same code, same shape.
- `POST /api/extra-work/<ew_id>/proposals/` (proposal create) — HTTP 403 with stable code `bm_proposal_preparation_disabled`. No proposal row materialises.
- `POST/PATCH/DELETE /api/extra-work/<ew_id>/proposals/<pid>/lines/[<lid>/]` — HTTP 403 with stable code `bm_proposal_preparation_disabled`.
- `POST /api/extra-work/<ew_id>/proposals/<pid>/transition/` driving `DRAFT → SENT`, `DRAFT → CANCELLED`, or `SENT → CANCELLED` (provider-driven proposal-prep transitions) — `TransitionError` with stable code `bm_proposal_preparation_disabled` (HTTP 400). No state mutation, no `ProposalStatusHistory` row.

Super Admin and Provider Company Admin are not revocable through this surface — both keys resolve `True` for SA always and for COMPANY_ADMIN by their existing role-default branch in `accounts.permissions_v2.user_has_osius_permission`. Customer approval / rejection of SENT proposals stays open to the customer — only the BM provider-override leg is affected. STAFF remains entirely locked out of every Proposal and EW commercial endpoint (P0 staff-privacy posture preserved).

Write authority for the override map:

- Existing `PATCH /api/buildings/<building_id>/managers/<user_id>/` endpoint accepts `{"permission_overrides": {...}}`. The new `BuildingManagerAssignmentUpdateSerializer` allow-lists exactly the two B6 keys and rejects every other key (other `osius.*`, `customer.*`, unknown strings) with HTTP 400 to prevent scope-bleed via the override map.
- Values must be real Python booleans — ints (0/1), strings (`"true"`/`"false"`), `None`, lists, and dicts are rejected. Full-replacement semantics: the PATCH body's `permission_overrides` overwrites the previous dict entirely.
- The class-level `IsSuperAdminOrCompanyAdminForCompany` permission gate admits Super Admin and Provider Company Admin of the building's company; BM cannot flip their own row (403), STAFF / CUSTOMER_USER cannot reach the endpoint (403).
- Every flip writes a single `AuditLog` UPDATE row with the before/after diff via the new `_on_building_manager_assignment_post_save_update` handler (matrix H-10).

B6 narrows **write** authority. Read visibility is not affected — the same provider-operator scope rules apply as before. In particular, the proposal PDF endpoint (`GET /api/extra-work/<ew_id>/proposals/<pid>/pdf/`) and the proposal detail / status-history / timeline / lines GET endpoints stay open to a BM in scope even when `prepare_extra_work_proposal=False`. STAFF remains entirely excluded from every proposal endpoint via the existing `scope_extra_work_for` floor (P0 staff-privacy). The canonical doc's §4.3 + §9.2 note that a BM's default view of provider-level commercial / financial information is broader than ideal — tightening it is deliberately deferred to B7 (four-tier note taxonomy), which will introduce a dedicated read-visibility surface for commercial notes and may add a paired view-side BM key with its own override map.

**Invariant — BM pricing / PDF visibility survives the prep revoke.** An assigned Building Manager whose `osius.building_manager.prepare_extra_work_proposal` resolves False at a building MUST still see proposal pricing AND the proposal PDF for any proposal under that building. This is the canonical product rule and is the contract behind two action-block booleans the frontend reads from `GET /api/extra-work/<ew_id>/proposals/<pid>/`: `actions.can_view_proposal_pricing` and `actions.can_view_proposal_pdf` both stay `True` for an in-scope BM even when the prep key is revoked. Only the **write** action booleans on the same record (`can_edit_lines`, `can_send`, `can_cancel`, `can_direct_publish`) flip `False` when the prep key is revoked. See §5 "Per-record actions blocks (runtime gating)" for the full action-block contract.

The proposal detail endpoint (`/api/extra-work/<ew_id>/proposals/<pid>/`) currently exposes only `GET` — there is no PATCH / PUT / DELETE verb on the detail surface, so B6 only needs to gate the writable surfaces enumerated above. A regression test asserts the missing verbs return HTTP 405 so a future refactor adding a writable detail endpoint must explicitly wire the B6 gate or the test will fail.

B6 does not give BM cross-building access — the per-(BM, building) override map is read at the same site as the existing `BuildingManagerAssignment` scope check, so revoking a key on building A has no effect on the BM's authority at building B (separate assignment row, separate overrides). It also does not give BM any customer-user permission-management rights or any cross-provider reach.

Effective-permissions endpoint:

- `can_override_customer_decision` and `can_prepare_extra_work_proposal` now consult the live resolver for BM targets at the request's (customer, building) pair. True by default; False when the corresponding key is set to `False` on the BM's assignment row. SA / COMPANY_ADMIN always True. STAFF / CUSTOMER_USER always False.
- BM `notes` block now describes the two revocable keys and where they're stored, replacing the old "future B6" placeholder.

B6 does not change Staff extra-work privacy, cart-first Extra Work pricing rules, the B5 Provider Admin / CCA policy, or B4 CCA lower-user management. B7 (four-tier note taxonomy) remains future work.

---

## 4.6 Customer Location Manager

Customer Location Manager is a customer-side manager for one or more buildings.

A Customer Location Manager can be assigned to multiple buildings if allowed by Customer Company Admin, Provider Admin, or Super Admin.

A Customer Location Manager can usually:

- See assigned buildings
- See tickets for assigned buildings
- Create tickets for assigned buildings
- Request Extra Work for assigned buildings
- Approve or reject work/proposals for assigned buildings if permission allows
- See customer-visible comments, prices, and proposal information for assigned buildings

A Customer Location Manager should not:

- See buildings they are not assigned to
- See provider-only notes
- See provider financial/cost/margin notes
- Manage provider users
- Manage provider settings
- Create Customer Company Admin users
- Manage permissions unless explicitly allowed

---

## 4.7 Customer User

Customer User is a basic customer-side user.

A Customer User can usually:

- See only their allowed customer/building scope
- Create tickets if permission allows
- Request Extra Work if permission allows
- Comment on tickets if permission allows
- View customer-visible information

A Customer User may or may not approve/reject depending on permissions.

A Customer User should not:

- See provider-only notes
- See staff-only notes
- See other customers
- Manage users
- Manage permissions
- See provider internal pricing/costs

---

## 5. Permission model

The permission system should have two levels.

### Level 1: Default permissions by role

Every role has default behavior.

Example:

- Super Admin can do everything.
- Provider Admin can manage most provider-side things.
- Building Manager can manage assigned-building operations.
- Staff can see assigned operational work.
- Customer Company Admin can manage their customer-side scope.
- Customer Location Manager can manage assigned buildings.
- Customer User has limited customer-side access.

These defaults should make the system usable without setting custom permissions for every user.

### Level 2: Custom permission overrides

A user can have custom permissions that override the default.

Custom permissions should be scoped.

A permission should answer:

- Which user?
- Which customer company?
- Which building?
- Which action?
- Is it allowed or denied?

Examples:

- Allow this Building Manager to prepare proposals in Building A.
- Deny this Building Manager from approving on behalf of customers.
- Allow this Customer Location Manager to approve Extra Work only in Building B.
- Deny this Customer User from creating Extra Work.
- Allow this Provider Admin to manage customer permissions.
- Allow Customer Company Admin to manage Customer Users but not create another Customer Company Admin.

### Who can grant permissions?

Simple rule for the current one-provider setup:

Super Admin can grant or remove anything.

Provider Company Admin can manage customer-specific permissions by default. This includes:

- Which customer users can create tickets.
- Which customer users can approve proposals.
- Which customer users can request Extra Work.
- Which Customer Location Managers can manage which buildings.
- Which Building Managers can approve/reject on behalf of customers (this is the override default; see §4.3).
- Which Building Managers can prepare proposals.
- **Assigning or revoking the Customer Company Admin access role on a customer-side user.** This is a provider-side power by default — Super Admin can restrict an individual Provider Admin from doing it, but no customer-side user has it.

Super Admin can control whether a Provider Company Admin is allowed to manage these permissions. The toggle is per-Provider-Admin (or by company-level policy) and is the only switch that narrows the provider-admin defaults.

Customer Company Admin should have limited permission management only if Provider Admin or Super Admin allows it. A Customer Company Admin must never be able to create / promote another Customer Company Admin (see §4.5).

Customer Location Manager should not manage permissions unless explicitly allowed.

Staff should not manage permissions.

### Important permission principle

The UI should show who has access to what in a clear way.

The same saved permissions should be visible in multiple useful places:

- On the Customer Permissions page
- In the user's row after permissions are saved
- In the Customer Users tab
- On the specific user's profile page

The user profile page should first display the user's access rights clearly. Editing should be possible, but viewing should come first.

### Effective-permissions endpoint (backend source of truth)

The backend exposes a read-only endpoint that answers, for a target user in a given (customer, building) context, "what can this user actually do?":

```
GET /api/users/<id>/effective-permissions/?customer_id=<id>&building_id=<id optional>
```

Authorization (caller):

- Super Admin can query anyone.
- Provider Company Admin can query users inside their own provider company AND only when the supplied `customer_id` is in their own provider company. Cross-company queries return 403.
- Building Manager, Staff, and Customer User cannot call this endpoint (they get 403).

The response carries:

- `user` — id, email, role, is_active of the queried user.
- `context` — the customer_id, building_id, and the inferred company_id.
- `scope` — `in_scope: bool` + human-readable `reason` (whether the target has reach into this customer/building).
- `role_defaults` — the access_role and its default permission keys (for customer-side users with an access row).
- `overrides` — the target's active `CustomerUserBuildingAccess` rows for this customer (each carries `building_id`, `access_role`, `is_active`, and the raw `permission_overrides` JSON).
- `effective_permissions` — `{key: bool}` for every known permission key (provider + customer side), computed by the existing composer.
- `effective_actions` — derived business booleans (e.g. `can_view_tickets`, `can_create_extra_work`, `can_use_contract_price_direct_order`, `can_override_customer_decision`, `can_view_provider_internal_notes`, `can_view_staff_operational_notes`, etc.). These are read-only derived facts, not new permission keys. They are the single source of truth for the Customer Permissions page, the Customer Users tab, and the User profile page — frontend code must not re-derive them.
- `notes` — plain-text caveats. Future-feature gaps (CCA-callable lower-user management, Super-Admin toggle to disable Provider-Admin customer-permission writes, BM-revocation keys, four-tier note taxonomy) are listed here when relevant; the action booleans reflect current backend truth, not a forecast.

Future B5 will add a Super Admin-controlled policy/toggle for whether Provider Admin may manage Customer Company Admin permissions. Current behaviour remains provider-admin-allowed by default — see §4.5.

### Per-record actions blocks (runtime gating)

The frontend must NOT call the effective-permissions endpoint above to gate buttons or modals at runtime. That endpoint is for **admin permission-overview screens only** (the Customer Permissions page, the Customer Users tab, the User detail page) — its caller gate is `CanManageUser` (Super Admin / Provider Company Admin only), so it cannot answer "what can THIS user — the one currently signed in — do here?" for a Building Manager, a Staff user, or a Customer User. None of them can call the endpoint at all.

Runtime per-button / per-modal frontend gating MUST instead read the per-record `actions` object on each detail serializer. The backend computes each boolean against the live resolvers + state machine for the requesting user, on the specific record being displayed, so the answer the UI shows is always exactly the answer the user gets when they POST. The frontend never re-derives a permission rule — it inspects `actions.<key>` on the record it just fetched.

The four surfaces that emit a per-record `actions` block:

#### Ticket detail (`GET /api/tickets/<id>/`)

```json
"actions": {
  "allowed_next_statuses": ["..."],
  "can_override_customer_decision": true,
  "can_post_provider_internal_note": true,
  "can_post_staff_operational_note": true,
  "can_post_staff_completion_note": true,
  "can_upload_hidden_attachment": true,
  "status_transitions": { "OPEN": false, "IN_PROGRESS": true, "...": false }
}
```

Field meanings:
- `allowed_next_statuses` — the list of TicketStatus values the requesting user may drive THIS ticket to right now. Same data as the top-level `allowed_next_statuses` field; both come from the same cached `allowed_next_statuses(user, ticket)` call so they cannot drift.
- `status_transitions` — the same answer reshaped as a `{ <every TicketStatus value>: bool }` map so the UI can do an O(1) lookup per status button instead of re-scanning the list.
- `can_override_customer_decision` — True only when the viewer holds override authority AND the ticket is at the customer-decision step RIGHT NOW. Authority gate: Super Admin, OR Company Admin in the ticket's provider company, OR Building Manager assigned to the ticket's building with `osius.building_manager.override_customer_decision` resolving True. Current-record gate: the ticket's status is `WAITING_CUSTOMER_APPROVAL` AND `APPROVED` or `REJECTED` is in `allowed_next_statuses`. Outside the customer-decision step (e.g. an `OPEN`, `IN_PROGRESS`, or already-`APPROVED` ticket) the answer is False even for an SA, because the underlying state-machine transition would 400 the click. Mirrors the `provider_driven_customer_decision` coercion block in `tickets.state_machine.apply_transition`.
- `can_post_provider_internal_note` — True iff the requesting user is provider management (SA / Provider Company Admin / Building Manager). Mirrors the §9.2 PROVIDER_INTERNAL gate enforced by `TicketMessageSerializer.validate_message_type` on `message_type=INTERNAL_NOTE`.
- `can_post_staff_operational_note` — True iff the requesting user is provider-side (SA / Company Admin / BM / STAFF). The §9.3 STAFF_OPERATIONAL tier.
- `can_post_staff_completion_note` — True iff the requesting user is provider-side. The §9.4 STAFF_COMPLETION tier.
- `can_upload_hidden_attachment` — True iff the requesting user is provider management. Mirrors `TicketAttachmentSerializer.validate_is_hidden` (which rejects `is_hidden=True` from STAFF or customer-side authors).

There is intentionally no `can_post_public_reply` boolean — every authenticated viewer in scope on the ticket may author a PUBLIC_REPLY, so the frontend doesn't need a per-record answer.

#### Extra Work detail (`GET /api/extra-work/<id>/`)

```json
"actions": {
  "allowed_next_statuses": ["..."],
  "can_prepare_extra_work_proposal": true,
  "can_override_customer_decision": true,
  "can_view_pricing": true,
  "can_view_proposal_pdf": true,
  "can_approve": false,
  "can_reject": false
}
```

Field meanings:
- `allowed_next_statuses` — same shape / same cache as the ticket case.
- `can_prepare_extra_work_proposal` — True for SA always; True for Company Admin in scope always; True for BM in the assigned building gated by `osius.building_manager.prepare_extra_work_proposal`; False for STAFF and Customer User.
- `can_override_customer_decision` — same shape as the ticket analog: viewer holds override authority (SA / CA in scope / BM in assigned building + B6 override key) AND the EW is at the customer-decision step RIGHT NOW (`status == PRICING_PROPOSED`). Outside `PRICING_PROPOSED` (e.g. `REQUESTED`, `UNDER_REVIEW`, `CUSTOMER_APPROVED`, `IN_PROGRESS`, `COMPLETED`) the answer is False even for an SA, because the underlying state-machine transition would 400 the click.
- `can_view_pricing` — True for any provider operator in scope (SA / Company Admin in scope / BM in scope — the BM prep-key revoke does NOT remove pricing visibility, see §4.3 invariant). True for Customer User iff they hold any `customer.extra_work.approve_*` key.
- `can_view_proposal_pdf` — mirrors `can_view_pricing` exactly today; kept as a separate boolean so the backend can split them later without a wire-shape break.
- `can_approve` / `can_reject` — True only when the EW status is `PRICING_PROPOSED` AND the requesting user is either a Customer User with the right `customer.extra_work.approve_*` key (`approve_location` at the pair, OR creator-of-this-request AND `approve_own`) OR a provider operator who could legally override the customer decision. False otherwise.

STAFF never reaches this serializer at all — `extra_work.scoping.scope_extra_work_for` returns `.none()` for STAFF (P0 staff-privacy floor). The action booleans intentionally do not branch on the STAFF role; the resolver helpers return False for STAFF anyway and the endpoint gate makes the question moot.

#### Proposal detail (`GET /api/extra-work/<ew_id>/proposals/<pid>/`)

```json
"actions": {
  "allowed_next_statuses": ["..."],
  "can_view_proposal_pricing": true,
  "can_view_proposal_pdf": true,
  "can_edit_lines": true,
  "can_send": true,
  "can_cancel": true,
  "can_approve": false,
  "can_reject": false,
  "can_direct_publish": true
}
```

Field meanings:
- `allowed_next_statuses` — proposal-specific next-status list (`allowed_next_proposal_statuses`).
- `can_view_proposal_pricing` — True for any provider operator in scope (SA / Company Admin in scope / BM in scope). **The BM prep-key revoke does NOT remove pricing visibility** — only mutation is locked. True for Customer User iff they hold any `customer.extra_work.approve_*` key.
- `can_view_proposal_pdf` — mirrors `can_view_proposal_pricing` exactly today (see §4.3 invariant).
- `can_edit_lines` — provider operator in scope AND proposal is DRAFT. For BM, additionally requires `osius.building_manager.prepare_extra_work_proposal`.
- `can_send` — provider operator in scope AND proposal is DRAFT AND parent EW is `UNDER_REVIEW`. For BM, additionally requires the prep key. Cart-coverage / contract-price validations still run at POST time; the action boolean only checks the cheap gates so the Send button doesn't render against a parent in the wrong status.
- `can_cancel` — provider operator in scope AND proposal is DRAFT or SENT. For BM, additionally requires the prep key. (SENT cancel is coerced to `is_override=True` + reason required by `apply_proposal_transition` — the boolean only reports the role gate.)
- `can_approve` / `can_reject` — True only when proposal is SENT AND the requesting user is either a Customer User with the right approve key (`approve_location` at the pair, OR creator-of-the-parent-EW AND `approve_own`) OR a provider operator who could legally override the customer decision. For BM that means BOTH `osius.building_manager.prepare_extra_work_proposal` AND `osius.building_manager.override_customer_decision` resolve True.
- `can_direct_publish` — True only when `can_send` is True (i.e. all the cheap send preconditions hold — DRAFT proposal + parent EW `UNDER_REVIEW` + provider mutation / prep gate) AND the viewer holds override authority for BM (override authority is implicit for SA / Company Admin in scope). Derived from `can_send` in the serializer so the two cannot drift — when `can_send` is False (parent EW in any status other than `UNDER_REVIEW`, proposal not DRAFT, BM with prep key revoked), `can_direct_publish` is also False regardless of who's looking. False for Customer User and STAFF unconditionally. See §7.2.1 for the endpoint contract.

#### Customer detail + customer-user-membership rows

`GET /api/customers/<id>/` AND every row of `GET /api/customers/<id>/users/` carry:

```json
"actions": {
  "can_manage_customer_users": true,
  "can_manage_customer_company_admins": true,
  "allowed_target_customer_access_roles": ["CUSTOMER_USER", "CUSTOMER_LOCATION_MANAGER", "CUSTOMER_COMPANY_ADMIN"]
}
```

Field meanings:
- `can_manage_customer_users` — True for SA always; True for Company Admin in the customer's provider company; True for Customer User whose customer-level `customer.users.manage` resolves True (the CCA default). Mirrors the B4 admit shape.
- `can_manage_customer_company_admins` — True for SA always; True for Company Admin in scope ONLY when `companies.Company.provider_admin_may_manage_customer_company_admins` is True (the B5 policy toggle); False otherwise. The CCA tier is NEVER manageable from a customer-side actor (H-7).
- `allowed_target_customer_access_roles` — the list of `CustomerUserBuildingAccess.AccessRole` values the requesting user may SET on a target customer-side user under this customer. The frontend renders the role dropdown directly from this list:
  - SA: all three (`CUSTOMER_USER`, `CUSTOMER_LOCATION_MANAGER`, `CUSTOMER_COMPANY_ADMIN`).
  - Company Admin in scope: all three iff the B5 policy is True; otherwise only `CUSTOMER_USER` + `CUSTOMER_LOCATION_MANAGER`.
  - CCA in scope (admitted by `customer.users.manage`): only `CUSTOMER_USER` + `CUSTOMER_LOCATION_MANAGER` — H-7 blocks CCA from promoting to CCA.
  - Any other role / out-of-scope actor: empty list.

The membership row's `actions` block is computed against the row's parent customer + the requesting user, so a single membership-list response carries one `actions` object per row reflecting that exact (viewer, customer) pair. Duplicating the block per row is intentional: the list is bounded (one customer at a time), and the alternative — overriding the view to wrap an envelope — would break the existing `{count, next, previous, results}` pagination shape that the typed frontend client already consumes.

#### What `actions` is NOT for

- Not for cross-record "what could this user do on a record they have not loaded?" questions — for that, the admin caller uses the effective-permissions endpoint above.
- Not for proxying as the current user's permission inventory — there is no "list every key this signed-in user has". The frontend reads only the per-record answers; if it needs the answer for record X, it fetches record X.
- Not a substitute for the backend gate — the gate IS the resolver, and the resolver IS what fills the `actions` block. The frontend can disable a button when `actions.can_x === false`, but the POST that bypasses the disabled state still gets the same 400/403 from the resolver.

---

## 6. Ticket workflow

A ticket is normal operational work.

### Normal ticket flow

A simple ticket flow can be:

1. Customer or provider creates a ticket.
2. Provider reviews it.
3. Provider assigns it to a Building Manager or Staff.
4. Staff performs the work.
5. Provider or Building Manager updates the status.
6. If customer approval is needed, the ticket waits for customer approval.
7. Customer approves or rejects.
8. Work is closed or reopened based on the decision.

The exact status names can vary, but the business meaning should stay clear.

Useful statuses:

- Open
- In progress
- Waiting for customer approval
- Approved
- Rejected
- Closed
- Reopened by admin

### Who sees tickets?

Super Admin sees all tickets.

Provider Admin sees provider-scope tickets.

Building Manager sees tickets in assigned buildings.

Staff sees assigned operational tickets/jobs.

Customer Company Admin sees tickets for their customer company.

Customer Location Manager sees tickets for assigned buildings.

Customer User sees tickets in their allowed scope.

### Customer approval in tickets

Sometimes a ticket requires customer approval.

Default rule:

The customer should approve or reject their own customer decision.

But there is an important business exception:

Provider Admin or Building Manager may approve/reject on behalf of the customer when the customer approved outside the system, for example by phone or verbally.

This is allowed by default for Building Manager if the role has the permission, but it must be removable by permissions.

When provider-side users approve/reject on behalf of the customer:

- Show a strong warning in the frontend.
- Require deliberate confirmation.
- Store who performed the action.
- Store that it was done on behalf of the customer.
- Store a reason or note if possible.
- Show it clearly in history/audit.
- Never make it look like the customer personally clicked the button.

Staff should not perform customer approval/rejection.

---

## 7. Extra Work workflow

Extra Work is the most important complex workflow.

Extra Work must support two different paths.

---

## 7.0 Extra Work is always a cart with line items

Extra Work is **always** a cart-like object at the business-logic level. The frontend may later display the cart compactly (e.g. as a one-line summary), but the backend must always represent it as one request containing **one or more line items**. There is no "single-line Extra Work request"; the single-item case is just a cart of length one.

The canonical rules are:

1. A customer creates **one** Extra Work request (the cart).
2. The cart contains **one or more** line items. Each line carries: a Service reference, a unit type, a quantity, a requested date, and optionally a customer note.
3. Each line item is independently classified as either:
   - **Contract-priced for this specific customer** — there is an active `CustomerServicePrice` row for `(this customer, this service, this requested date)` — or
   - **Custom / non-contract** — the resolver returns no contract row for that pair.
4. **Routing rule (whole-cart):** the routing decision is computed once at submission time across the whole cart.
   - If **every** line in the cart resolves to a contract price, the request is routed to the **instant path**: no proposal is required, the customer sees the calculated prices, the customer submits it like an order, and the request enters the operational workflow directly.
   - If **at least one** line in the cart does **not** resolve to a contract price, the whole cart is routed to the **proposal path** — even if the other lines are contract-priced.
5. **In the proposal path**, the contract-priced lines remain represented in the resulting proposal as already-priced lines (their contract price flows through), and provider-side actors add prices and customer-visible explanations for the custom / non-contract lines only. The customer reviews the entire proposal (contract + custom together) and approves or rejects the whole proposal — there is no per-line approve / reject loop at the cart level.
6. **Staff must not see proposal pricing**, provider commercial notes, customer approval controls, or any internal commercial decision data. This applies to both paths.
7. **Staff sees the operational work only after the request / proposal has been approved** and the work has been spawned into one operational ticket / task per cart line. The ticket carries safe operational metadata (parent request id, title, status, service name) but never the pricing or commercial notes.

The cart-first design is permanent: changes that collapse Extra Work back into a single-line concept (or that strip the proposal of its contract-priced lines) violate this section and must be rejected.

Concrete cart example (the canonical mental model — every Extra Work request must support this shape):

A customer submits one Extra Work request with three lines:

- 50 m² window cleaning
- 20 m² grass cutting
- 3 hours deep cleaning

Each line is independently classified by the resolver:

- If **every** line resolves to a customer-specific contract price → the request is routed to the instant / direct-order path: the system computes the total automatically, the customer places it like an order from a food-delivery app, and it immediately enters the provider's operational queue.
- If **even one** line has no contract price for that customer → the whole request goes into the proposal flow. The contract-priced lines stay in the cart at their known prices; the provider prices the missing / custom line(s) and sends a proposal back to the customer; the customer approves or rejects the whole proposal; on approval the request enters the operational queue.

Frontend hint for later (not a backend rule): when the frontend displays the cart it should render the line items as compact single rows rather than large stacked cards. This is a layout preference, not a business-logic constraint — the backend always treats the cart as a list of N lines regardless of how the UI lays them out.

---

## 7.1 Path A: Contract-priced Extra Work

This is like buying something from a shopping cart.

The customer already has a contract price for the service.

Example:

Customer A has this contract:

- Window cleaning = EUR 5 per square meter

Customer A wants:

- 50 square meters of window cleaning

The system should show:

- Service: Window cleaning
- Unit price: EUR 5 per square meter
- Quantity: 50 square meters
- Total: EUR 250

The customer can select it, add it to a cart-like request, and submit directly.

There is no need for provider proposal preparation because the price is already agreed in the contract.

This should behave like:

1. Customer opens Extra Work request.
2. Customer sees available contract-priced services for their company.
3. Customer adds one or more line items, like a cart.
4. Each line has service, unit type, quantity, unit price, and total.
5. Customer sees total price before submitting.
6. Customer submits.
7. The request goes directly into provider operations.
8. Provider schedules/assigns it.
9. Staff sees it only when it becomes assigned operational work.

Important:

The customer must only see contract-priced services that are valid for their customer company.

If the customer company does not have a contract price for that service, it should not be treated as direct fixed-price work.

### Multiple line items

Extra Work should allow multiple line items.

Example:

- 50 square meters window cleaning
- 2 hours deep cleaning
- 1 special floor treatment

The customer should be able to add items like a cart.

The frontend must not force everything into one confusing line. The business concept is still a cart, even if the UI later chooses a compact layout.

---

## 7.2 Path B: Non-contract Extra Work that needs proposal

This is for work that is not already priced in the customer's contract.

Example:

Customer A does not have grass cutting in their contract.

Customer A requests:

- "I want 100 square meters of grass cutting."

Then the provider must prepare a proposal.

Flow:

1. Customer requests custom Extra Work.
2. Provider Admin or allowed Building Manager sees the request.
3. Provider prepares a price proposal.
4. Proposal can contain multiple line items.
5. Provider sends the proposal to customer.
6. Customer reviews customer-visible proposal details.
7. Customer approves or rejects.
8. If approved, the work becomes operational work and can be assigned to staff.
9. Staff sees only the assigned operational work, not pricing/proposal/internal financial notes.

### Proposal statuses

Proposal statuses should mean:

- Draft: Provider is preparing it. Customer should not see it.
- Sent: Customer can see it and decide.
- Approved: Customer accepted it, or provider-side user approved on behalf of customer with audit.
- Rejected: Customer rejected it, or provider-side user rejected on behalf of customer with audit.
- Cancelled: Provider cancelled it.
- Expired: Optional future status if proposal deadlines are added.

### Who can prepare proposals?

Super Admin can prepare proposals.

Provider Admin can prepare proposals.

Building Manager can prepare proposals by default for assigned buildings.

Permissions can remove proposal preparation from a Building Manager.

Staff should not prepare proposals.

Customer users should not prepare provider proposals.

### Who can approve/reject proposals?

Customer Company Admin can approve/reject for their customer company if allowed.

Customer Location Manager can approve/reject for assigned buildings if allowed.

Customer User can approve/reject only if explicitly allowed.

Provider Admin can approve/reject on behalf of the customer when the customer approved outside the system, if allowed.

Building Manager can approve/reject on behalf of the customer by default for assigned buildings, if allowed by permissions.

When provider-side users approve/reject on behalf of a customer, the same warning/audit rules apply:

- Warning
- Confirmation
- Reason/note
- Audit/history
- Clear "on behalf of customer" label

Staff cannot approve/reject proposals.

### 7.2.1 Direct-publish (provider override of the customer-approval step)

When a provider operator already knows the customer's decision out-of-band (the customer phoned in, signed off in person, sent an email) and wants to skip the customer-facing approval step entirely on a DRAFT proposal, they POST to a dedicated direct-publish endpoint instead of walking the proposal through DRAFT → SENT → CUSTOMER_APPROVED in two HTTP calls. This is the proposal-side analog of the §6 ticket workflow override.

**Endpoint:**

```
POST /api/extra-work/<ew_id>/proposals/<pid>/direct-publish/
```

**Payload:**

```json
{
  "note": "optional free-text note (plumbed through to the DRAFT->SENT status-history row)",
  "override_reason": "operator-typed reason — REQUIRED, non-blank"
}
```

**Permission gate:**

- Provider operator in scope on the parent EW's customer + building. SA: always; Provider Company Admin: in the building's company; Building Manager: assigned to the building.
- BM additionally MUST hold BOTH `osius.building_manager.prepare_extra_work_proposal` AND `osius.building_manager.override_customer_decision` at the building. Either revoked → HTTP 403 with stable code `bm_proposal_preparation_disabled` or `bm_override_disabled` respectively.
- STAFF and CUSTOMER_USER are blocked. The exact code depends on which gate fires first: STAFF reaches a 404 because `scope_extra_work_for(STAFF)` is `.none()` (the parent EW is invisible to them) before the view's role guard runs; CUSTOMER_USER reaches a 404 because `_resolve_proposal_or_404` treats DRAFT proposals as invisible to customer-side readers. If either reaches the role guard (e.g. on a hypothetical non-DRAFT proposal), the response is HTTP 403 `Provider-side action only.`. The 200 outcome is unreachable for both roles regardless of which gate handles the rejection.

**Preconditions:**

- Proposal status MUST be `DRAFT` → HTTP 400 with stable code `direct_publish_requires_draft` otherwise.
- Parent EW must satisfy the same preconditions as the normal SEND path (UNDER_REVIEW status, etc.).
- Proposal must pass the same SEND-time validations: at least one line, cart-coverage exact (no extra lines, no missing cart items), contract-priced lines match the active `CustomerServicePrice`, non-contract lines have a positive unit price. Failures surface the same stable codes the normal SEND path emits (`proposal_lines_required`, `proposal_send_requires_under_review`, `proposal_has_extra_line`, `proposal_does_not_cover_cart`, `proposal_contract_price_drift`, `proposal_custom_line_missing_price`).
- `override_reason` MUST be non-blank after `.strip()` → HTTP 400 with stable code `override_reason_required` otherwise. The endpoint does NOT silently default the reason; the codebase-wide override-reason convention (Sprint 27F-B1 tickets, `apply_proposal_transition`, EW state machine) is "operator MUST type a reason", and this endpoint matches.

**Behaviour (atomic two-step):**

The handler runs both legs inside one `transaction.atomic()`:

1. DRAFT → SENT (normal send-time validation).
2. SENT → CUSTOMER_APPROVED as a provider override (`is_override=True` + `override_reason=<payload>`).
3. The parent EW transitions to CUSTOMER_APPROVED via the existing proposal-approval hook.
4. Operational tickets spawn from the approved proposal lines via the existing post-approval auto-spawn hook.

If step 2 (or anything beyond) raises, step 1's status mutation + `ProposalStatusHistory` row + parent-EW advance + timeline event all roll back together. `apply_proposal_transition` is itself `@transaction.atomic`-wrapped; Django nested atomics use savepoints, so the outer block correctly encompasses both legs.

**Audit:**

The override fact is recorded on the SENT → CUSTOMER_APPROVED `ProposalStatusHistory` row (`is_override=True` + `override_reason=<payload>`). The `Proposal` row's `override_by` / `override_reason` / `override_at` fields fire generic `AuditLog` rows via the existing audit signal. NO new audit log table or signal is introduced — the override history row IS the audit trail for the workflow override (matrix H-11), exactly as for the Extra Work and ticket overrides.

**Response (200):** `ProposalDetailSerializer(proposal).data` including the new `actions` block. Proposal status is now `CUSTOMER_APPROVED`; the operational tickets spawned by the parent-EW approval hook are not part of this response (the caller fetches them through the ticket endpoints).

**Existing `transition/` endpoint is unchanged.** The normal DRAFT → SENT → customer-clicks-approve / customer-clicks-reject path still works for cases where the customer will actually decide in the app. The direct-publish endpoint is additive — it is the *only* way to bypass the customer-facing SENT phase in one atomic call.

---

## 8. Pricing and Services

The Services page should manage the general catalog of services.

Example services:

- Window cleaning
- Grass cutting
- Deep cleaning
- Floor polishing

The Pricing page should manage customer-specific contract prices.

A service alone does not mean every customer can order it at a fixed price.

A customer-specific price is what makes a service available for direct contract-priced Extra Work.

Each customer should have its own contract-price setup.

Example:

Customer A:
- Window cleaning: EUR 5 per square meter
- Deep cleaning: EUR 40 per hour

Customer B:
- Grass cutting: EUR 2 per square meter
- Window cleaning: not contracted, proposal required

The customer detail area should allow provider admins to enter and manage that customer's contract prices.

The customer-specific pricing must be clear enough that the frontend can show:

- Which services are available directly for this customer
- The unit price
- The unit type
- Whether approval/proposal is needed
- Whether the price is active

### 8.1 `CustomerServicePrice` is the only commercial source of truth for direct orders

`Service.default_unit_price` is **NOT** the commercial source of truth for direct (contract-priced) orders. It is a reference value used for catalog display and as a fallback default the operator can copy from when seeding a proposal; it never drives the routing decision and never substitutes for a missing customer-specific contract row.

`CustomerServicePrice` is the only authoritative customer-specific contract price. The same `Service` may carry different `CustomerServicePrice` rows for different customers (Customer A may have a contract price for window cleaning at EUR 5/m²; Customer B may have a different contract price for the same service, or no contract row at all). The resolver `extra_work.pricing.resolve_price(service, customer, on=date)` returns the customer-specific row (if any active row exists at the requested date) or `None`.

### 8.2 Cart routing decision

The routing decision is computed at submission time across the whole cart, using the rule already stated in §7.0 rule 4:

- **All cart lines** map to an active `CustomerServicePrice` for the customer → `routing_decision = INSTANT`. The proposal phase is skipped; operational tickets spawn immediately from the cart line items (one ticket per line, anchored to the parent `ExtraWorkRequest`). The customer's submission IS the approval.
- **At least one cart line** lacks an active `CustomerServicePrice` → `routing_decision = PROPOSAL`. The whole cart goes through the provider-side proposal phase, even if other lines are contract-priced.

`Service.default_unit_price` does NOT count toward the INSTANT routing condition. Only an active `CustomerServicePrice` for the (customer, service, requested_date) triple does.

### 8.3 Proposal lines seeded from a cart

When a proposal is created on a PROPOSAL-routed cart with no explicit `lines` payload (the auto-seed path in `ProposalCreateSerializer.create`), the serializer reads the parent EW's cart items and seeds one `ProposalLine` per `ExtraWorkRequestItem`:

- For each cart line the resolver is called again with the cart item's own `requested_date`. If a contract row is returned, the seeded proposal line's `unit_price` and `vat_pct` are pre-filled from the contract row — contract-priced lines preserve their contract pricing into the proposal.
- For cart lines without a contract row, `unit_price` defaults to `0.00` and `vat_pct` defaults to 21%. The operator MUST set a positive price before SEND — the SEND-time validator rejects custom lines whose `unit_price <= 0` with stable code `proposal_custom_line_missing_price`.

When the caller sends explicit `lines` on proposal create, the serializer creates exactly those rows. SEND-time validation (`apply_proposal_transition`) is the safety net for the cart-coverage / contract-price-drift / custom-line-priced contract regardless of whether the lines were auto-seeded or hand-built.

---

## 9. Notes and visibility

The system needs different types of notes. Do not treat every internal note as the same thing.

The canonical model has **four** note categories. Every note in the system (on a ticket, on an Extra Work request, on a proposal, on a proposal line, on a status-history row) belongs to exactly one of these categories, and the category determines who can read it.

### 9.1 Customer-visible note

Visible to: customer and provider.

Used for normal customer-facing communication.

Examples:

- "The work is planned for Friday."
- "We will be on site between 09:00 and 11:00."

### 9.2 Provider internal note

Visible to: provider admin and Building Manager (subject to permissions).

Not visible to: customer, staff (by default).

Used for commercial / internal / provider-side comments such as cost, margin, negotiation, pricing strategy, and internal commercial decisions.

Examples:

- "Our cost is EUR 120."
- "Margin is low — flag if approved."
- "Customer is difficult with payments — require pre-payment next time."
- "Do not discount this request."
- "Discuss pricing with Ramazan first."

### 9.3 Staff instruction / operational note

Visible to: provider and staff.

Not visible to: customer.

Used for operational instructions that the field-staff team needs to actually do the work. This is the operational hand-off note — it must never contain commercial / pricing / margin context.

Examples:

- "Bring stronger cleaning material."
- "These windows are very dirty — schedule extra time."
- "Use the back entrance — security has been notified."
- "Bring a ladder."

### 9.4 Staff completion note

Written by: staff, when they are completing their assigned work or sending it onward (to manager review or customer approval).

Used as completion evidence — together with or instead of a photo attachment.

Required for Staff when they move a piece of work onward. Optional for managers / admins driving the same transition on behalf of a staff member.

Examples:

- "Completed at 14:30 — all windows polished, no damage observed."
- "Cabinet front replaced, see attached photo."

### Implementation status (B7)

B7 (now implemented) — the four-tier taxonomy is the live shape of `tickets.models.TicketMessageType`:

- `PUBLIC_REPLY` → CUSTOMER_VISIBLE
- `INTERNAL_NOTE` → PROVIDER_INTERNAL (literal kept for backwards compatibility; legacy rows keep their semantic without a data migration)
- `STAFF_OPERATIONAL` → STAFF_OPERATIONAL
- `STAFF_COMPLETION` → STAFF_COMPLETION

Backend enforcement:

- `TicketMessageListCreateView` queryset filter narrows by viewer role: provider management (SA / Provider Company Admin / BM) sees every tier including hidden moderation rows; STAFF sees PUBLIC_REPLY + STAFF_OPERATIONAL + STAFF_COMPLETION; customer-side sees PUBLIC_REPLY + STAFF_COMPLETION only.
- `TicketAttachmentListCreateView` queryset + `TicketAttachmentDownloadView` mirror the same four-tier filter on the parent message's `message_type`. Hidden attachments are provider-management-only.
- `TicketMessageSerializer.validate_message_type` rejects: STAFF or customer-side authoring `INTERNAL_NOTE`; customer-side authoring any STAFF_* tier. The view also force-normalises non-provider-side authors to `PUBLIC_REPLY` before the validator fires (defence in depth).
- `TicketAttachmentSerializer.validate_is_hidden` rejects `is_hidden=True` from any actor that is not provider management.
- `TicketStatusHistorySerializer.to_representation` extends the B1 customer redaction: STAFF readers also do not see `note` or `override_reason` on rows where the author was a provider management role AND `is_override=True` (PROVIDER_INTERNAL override commentary).
- `tickets.state_machine._ticket_has_visible_attachment` now also excludes attachments whose parent message is `STAFF_OPERATIONAL` — only PUBLIC_REPLY and STAFF_COMPLETION attachments count as customer-visible completion evidence.
- A new role helper `accounts.permissions.is_provider_management_role` carries the new gate; `is_staff_role` is preserved for the operational completion-evidence / first-response branches that still admit STAFF.

Extra Work and Proposal note classification:

- Every text/note/metadata field on `ExtraWorkRequest`, `ExtraWorkRequestItem`, `ExtraWorkStatusHistory`, `Proposal`, `ProposalLine`, `ProposalStatusHistory`, and `ProposalTimelineEvent` is classified-by-purpose and already enforced at the serializer/scoping layer (no new column needed):
  - PROVIDER_INTERNAL by purpose: `ExtraWorkRequest.manager_note`, `ExtraWorkRequest.internal_cost_note`, `ExtraWorkRequest.override_reason`, `ProposalLine.internal_note`, `ProposalStatusHistory.override_reason`, `ProposalTimelineEvent.metadata`. Stripped via `_PROVIDER_ONLY_FIELDS` or omitted from the customer serializer entirely.
  - CUSTOMER_VISIBLE by purpose: `ExtraWorkRequest.description` / `customer_visible_note` / `pricing_note`, `ExtraWorkRequestItem.customer_note`, `ProposalLine.customer_explanation`. Included in customer serializers.
  - STAFF never reaches any Extra Work or Proposal endpoint — `scope_extra_work_for` returns `.none()` for STAFF (P0 staff-privacy floor preserved).
- The free-text `note` field on `ExtraWorkStatusHistory` / `ProposalStatusHistory` carries B1-style customer redaction: rows authored by a provider-side actor have `note` blanked for CUSTOMER_USER readers.

The four-tier classification is enforced at the data-shape level on `TicketMessage` (the only model that historically allowed a single field to carry every tier) and at the serializer-by-purpose level for every other model where the field name + serializer-strip logic already encodes the classification. A typed `note_type` column on every other model was deliberately not added in B7 to avoid a large data-model rewrite when classification-by-purpose already meets the visibility floor.

---

## 10. What each role should see

### Super Admin dashboard

Should see the whole system.

- All active tickets
- All Extra Work
- Approval queues
- Urgent work
- Customer/company overview
- System settings
- Permissions
- Pricing
- Services
- Users

### Provider Admin dashboard

Should see provider operations.

- Tickets
- Extra Work
- Pending proposals
- Customer approval queue
- Staff workload
- Building workload
- Customer-specific pricing
- Services
- Customer users/contacts
- Permissions they are allowed to manage

### Building Manager dashboard

Should see assigned-building operations.

- Tickets for assigned buildings
- Extra Work for assigned buildings
- Work needing scheduling/assignment
- Proposal preparation if allowed
- Approval/rejection on behalf of customer if allowed
- Staff operational status for assigned buildings

Should not see unassigned buildings.

### Staff dashboard

Should see only operational work assigned to them.

- Assigned tickets/jobs
- Location
- Description
- Staff-visible notes
- Attachments needed for work
- Operational status updates

Should not see proposal/pricing/customer approval controls.

### Customer Company Admin dashboard

Should see customer-company work.

- Tickets for their company
- Extra Work requests
- Proposals waiting for approval
- Contract-priced services
- Customer-visible prices
- Customer users if allowed
- Customer buildings

### Customer Location Manager dashboard

Should see assigned buildings.

- Tickets for assigned buildings
- Extra Work for assigned buildings
- Proposals/approvals for assigned buildings if allowed
- Customer-visible prices for assigned buildings if relevant

### Customer User dashboard

Should see limited customer-side work.

- Tickets they can see
- Extra Work they can request or view
- Customer-visible comments
- Their allowed buildings

---

## 11. Customer detail pages

When a provider admin opens a customer, the customer-specific pages should be meaningful.

### Overview

Shows the customer relationship:

- Customer name
- Provider company
- Active/inactive status
- Linked buildings
- Contacts
- Users
- Pricing rules
- Quick links to management areas

### Buildings

Shows which buildings this customer is linked to.

This matters because tickets and Extra Work can only be created for valid customer-building combinations.

### Users

Shows customer users.

Each row should clearly show what the user can access.

Saved permissions should be visible here after they are saved.

This page should display first, then allow editing.

### Permissions

Shows detailed access and permission controls.

This is where admins tune user access by customer/building/action.

### Pricing

Shows customer-specific contract prices.

This is where the provider enters the customer's agreed prices for services.

This page is essential for contract-priced Extra Work.

### Services

Services are the provider's general catalog.

Services are not the same as customer-specific prices.

### Extra Work

Customer-specific Extra Work page should eventually show:

- Direct contract-priced Extra Work available to this customer
- Non-contract requests
- Proposals
- Approval state
- History

If currently empty, it must be filled later.

### Settings

Shows customer-wide settings such as visibility preferences and lifecycle actions.

---

## 12. Audit and history rules

Important actions must be traceable.

The system should store:

- Who did the action
- What they did
- When they did it
- Which role they had
- Whether they acted on behalf of a customer
- Why they acted on behalf of a customer, if applicable
- Before/after state where useful

Actions that must be audited:

- Permission changes
- Customer approval/rejection
- Provider-side approval/rejection on behalf of customer
- Proposal sent
- Proposal approved/rejected/cancelled
- Ticket status changes
- Assignment changes
- Pricing changes
- Customer-building membership changes
- User membership changes

---

## 13. Non-negotiable privacy rules

Customers must not see:

- Provider internal financial notes
- Provider cost/margin information
- Internal staff/management notes
- Other customer companies
- Buildings outside their scope
- Users outside their scope

Staff must not see:

- Proposal pricing
- Customer approval controls
- Provider financial notes
- Customer contract management
- Permissions management

Building Managers must not see:

- Unassigned buildings
- Provider-wide settings
- Customer user permission management by default, unless explicitly allowed
- Provider-only financial notes unless explicitly allowed

Provider-side users must not silently pretend to be customer users.

If they approve/reject on behalf of a customer, the system must show and store that clearly.

---

## 14. What developers should do next

Before implementing new frontend polish, the backend rules should be checked against this document.

Recommended order:

1. Check current backend role visibility.
2. Check current ticket workflow.
3. Check current Extra Work workflow.
4. Check contract-priced Extra Work support.
5. Check non-contract proposal workflow.
6. Check customer-specific pricing.
7. Check note visibility types.
8. Check permission overrides.
9. Check who can grant which permissions.
10. Check audit/history for approval-on-behalf-of-customer.
11. Only after backend behavior is correct, polish the frontend.

---

## 15. Instructions for Claude Code or any AI developer

Read this document first.

Then inspect the current repository yourself.

Do not assume the code already matches this document.

Do not invent new product rules.

Do not redesign the frontend before checking backend behavior.

Do not make huge mixed changes.

First produce a report with these sections:

1. What already matches this document.
2. What conflicts with this document.
3. What is missing.
4. What backend changes are required.
5. What frontend changes are required later.
6. Which changes need migrations.
7. Which changes need tests.
8. Which changes are risky and should be split into separate batches.

If you do not know how something should work, do not guess. Search the code and docs first. If it is still unclear, ask.

Backend should be made correct first.

Frontend should then be made premium, clear, and easy to use based on the corrected backend behavior.

Screenshots can be provided for pages that look wrong, but the developer should also inspect the frontend directly and propose easier review methods, such as:

- Running the app locally
- Using Playwright screenshots
- Creating a visual route inventory
- Listing empty/placeholder pages
- Listing pages with broken UX
- Creating a before/after screenshot folder
- Creating a frontend audit document

---

## 16. One-sentence summary

The system is a provider-company operations platform where customer companies request normal tickets and Extra Work, customer-specific contract prices allow direct cart-like Extra Work ordering, non-contract work needs provider proposals, roles have default permissions plus custom overrides, provider-side users may act on behalf of customers only with warning and audit, and staff only see assigned operational work after approval, never pricing or provider-only notes.
