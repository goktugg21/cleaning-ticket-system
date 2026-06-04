# Osius Cleaning Ticket System — Source of Truth / Final Target State

Last updated: 2026-05-30  
Owner context: Goktug + Ramazan feedback + latest frontend P0/P1 work  
Purpose: This file is the canonical handoff for a new AI/dev chat. It explains what the system must become, what already works, what must be changed next, and the sprint order. It should be used both as a product source of truth and as an implementation checklist.

---

## 0. Current high-level state

The system is now a working cleaning operations platform with:

- Django/DRF backend, React/TypeScript/Vite frontend.
- Multi-tenant provider/customer model.
- Tickets, assignments, workflow statuses, notes, attachments, and audit concepts.
- Extra Work MVP evolved with service catalog/customer pricing, cart-shaped requests, invoice-row UI, proposal/detail improvements, and spawned operational tickets.
- Customer permission matrix UI is now in the desired direction: matrix/optical-answer-sheet style visibility and editing, not raw yes/no fields.
- Frontend P0/P1 polish is mostly done enough for demo, but not final-product complete.

Important: “working” does not mean “finished.” The next phase must focus on backend/source-of-truth correctness for Ramazan’s requested business flows, then frontend can consume those contracts without inventing business logic.

Recent GitHub state also indicates backend work around service catalog/customer pricing, cart-shaped Extra Work requests, and instant Extra Work ticket spawning has already landed or been pushed recently. The exact local branch should still be verified before any sprint work.

---

## 1. Core business definitions

### 1.1 Provider company

The provider company is the cleaning/service company using Osius to manage operations. In the current business example this is Ramazan’s company.

Provider-side roles:

- Super Admin
- Provider Admin / Company Admin / PA
- Building Manager / BM
- Staff / Field Staff

Terminology note: in older conversation “PCA” was sometimes used incorrectly. For this project:

- PA = Provider Admin = Provider Company Admin.
- Customer-side admin should be called Customer Company Admin.
- Avoid using PCA for customer admin because it is confusing.

### 1.2 Customer company

A customer company is the client receiving services from the provider.

Customer-side roles/access levels:

- Customer Company Admin
- Customer Location Manager
- Customer User
- Contacts connected to one or more customer buildings

A customer contact can be linked to multiple buildings under the same customer.

### 1.3 Building

A building belongs operationally to a customer relationship and is the location where tickets, extra work, recurring jobs, staff assignments, and building manager responsibility apply.

A building can have multiple managers and multiple staff visible/assignable.

### 1.4 Ticket

A ticket is the operational work item. Normal cleaning/service issues and spawned Extra Work operations are both ultimately managed through operational tickets.

A ticket must clearly show whether it is:

- Normal ticket
- Extra Work origin ticket
- Recurring/planned job origin ticket, once that exists

Extra Work-origin tickets must not disappear into the normal ticket list as if they were ordinary tickets. The origin must be clear in:

- Ticket list
- Ticket detail
- Dashboard operational queue
- Reports
- Audit/history
- Search/filtering

### 1.5 Extra Work

Extra Work is a commercial/pricing workflow that may later spawn one operational ticket.

Extra Work is not only a ticket. It has a pre-operational pricing/approval stage, then becomes operational after the right condition is met.

Extra Work can contain multiple service lines but should spawn one operational ticket, not one ticket per line.

### 1.6 Service catalog and prices

There are two levels of service pricing:

1. Provider default service catalog/prices
2. Customer-specific agreed prices

Provider default prices are internal provider templates. Customers must not see provider default prices.

Customer-specific agreed prices are visible to that customer’s users when they create Extra Work, according to their customer permissions.

---

## 2. Roles and permissions — final target

### 2.1 Super Admin

Super Admin can see and manage everything globally.

Super Admin must be able to control selected Provider Admin dangerous/global permissions, especially permissions that can create financial/customer-risky flows.

Super Admin can grant/revoke provider-level capabilities such as:

- Allow Provider Admin to bypass customer quote approval and start work from a quote after entering price.
- Allow Provider Admin to manage provider default service catalog/prices.
- Allow Provider Admin to manage customer-specific agreed prices.
- Allow Provider Admin to manage provider staff/building manager assignments.
- Allow Provider Admin to access financial/revenue reports.
- Allow Provider Admin to perform customer-decision overrides.

Not every small PA permission needs to become configurable, but the dangerous and financial ones must be.

Dangerous permissions should default to OFF unless business policy says otherwise. Any usage must be audit logged strongly.

### 2.2 Provider Admin / PA

Provider Admin manages the provider company’s operations.

PA can normally:

- Manage provider staff and BMs within the provider company.
- Manage buildings/customers within provider scope.
- Manage customer-specific agreed prices.
- Create Extra Work on behalf of customers using allowed intents.
- Assign/reassign operational tickets to eligible staff/BMs.
- View reports, unless Super Admin has restricted this.
- Override customer completion approval where allowed by policy/permission, with warning and audit.

PA must not be able to do nonsensical role changes such as turning a customer user into a provider BM through a generic global role dropdown. Provider roles and customer access roles must be handled through the correct membership/assignment screens.

### 2.3 Building Manager / BM

BM is a provider-side user assigned to one or more buildings.

BM can:

- See tickets and Extra Work operational tickets for assigned buildings, according to permissions.
- Be assigned to multiple tickets in those buildings.
- Be one of multiple managers on the same ticket.
- Assign/reassign field staff if permitted.
- View provider default service prices by default, if this helps operations.
- Not edit provider default prices by default.
- Potentially override customer approval only if explicitly permitted and with warning/audit.

A BM can be assigned to as many tickets/Extra Work operational tickets as needed within assigned buildings.

If a manager from another building needs to work on a ticket, PA should first update that manager’s building assignment/visibility, then assign them to the ticket.

### 2.4 Staff / Field Staff

Staff are operational workers.

Staff can:

- See assigned work.
- Post allowed note types.
- Mark work completed / unable to complete if workflow allows.
- Upload evidence/photos where required.

Staff should not access pricing/proposal/customer approval internals.

Staff can be assigned to multiple tickets/Extra Work operational tickets within buildings where they are visible/eligible.

### 2.5 Customer Company Admin

Customer Company Admin manages the customer company’s users/permissions and can create/approve work according to customer permissions.

They must be visible/filterable in the global Users area and customer-specific Users/Permissions screens.

### 2.6 Customer Location Manager

Customer Location Manager is tied to one or more buildings/locations.

They can create Extra Work and can choose auto-start-after-pricing if allowed by the customer role model. The user confirmed the lowest allowed role for auto-start should be location manager; normal customer users should not be grantable this capability.

They must be visible/filterable in Users screens.

### 2.7 Customer User

Customer User is the lower customer-side role.

They can create/view/approve only according to customer permission matrix. They should not be grantable the auto-start-after-pricing choice if the intended minimum is Customer Location Manager.

---

## 3. User and permission UI — known final requirements

### 3.1 Global Users page problem

Current/observed issue from screenshots and user feedback:

- Global Users page makes provider/customer role handling feel wrong.
- A provider admin user can appear editable into strange roles like Super Admin / Provider Admin / Building Manager / Customer User in one generic dropdown.
- Customer Company Admin and Customer Location Manager do not appear clearly as filterable roles/access types in the global Users page.
- Invite user flow only exposes limited role choices such as Customer User, not Customer Company Admin or Customer Location Manager.
- User detail/edit page for field staff has ugly technical copy and cramped “case assignment”/staff profile area.

Final target:

- Global Users page must distinguish global/provider role from customer access role.
- Provider-side role editing must not create invalid cross-domain memberships.
- Customer Company Admin and Customer Location Manager must be searchable/filterable and visible.
- Customer-side permissions should be edited through the customer permission matrix, not through a misleading global role dropdown.
- Staff profile/building visibility should be shown in a clean, product-friendly UI, not technical text.
- Avoid internal/dev copy like “managed under staff profile and per-building staff visibility flow...” in user-facing UI.

Implementation note:

Before building, inspect backend user model, memberships, CustomerUserMembership/access_role, BuildingManagerAssignment, StaffProfile/BuildingStaffVisibility, and frontend Users/Invitations pages. This may be a frontend problem, backend serializer problem, or both.

Shipped:

- The global Users page now SHOWS each user's customer access role(s) as a read-only column/badge, distinct from the global/provider role, and lets you FILTER by customer access role (Customer User / Customer Location Manager / Customer Company Admin). Provider-side users show no customer access role. Backend: `GET /api/users/` exposes a read-only `customer_access_roles` projection (sorted, distinct across the user's ACTIVE per-building grants — inactive grants are excluded to match effective permissions; empty for provider users) and accepts an `?access_role=` filter that mirrors `?role=` and likewise counts only active grants.
- Per-user permission EDITING stays in the per-customer permission matrix (§3.2) and the contact→user surface (a linked contact's "Manage permissions" deep-links into that matrix). The global Users page is read-only for access roles — it never edits customer permissions.

### 3.2 Customer permissions matrix

The desired UI is not raw yes/no toggles.

It should behave like an optical answer sheet / permission matrix:

- Admin can see users as rows.
- Permission families/columns are visible without opening each user.
- Filled bubble = permission/effective state is granted.
- Empty/disabled bubble = not granted or denied by policy.
- Click/Edit opens modal, not right drawer.
- Modal uses bubble/segmented controls for each permission.
- The UI should be readable at a glance: “who can do what?”

Important correction:

The existing backend permission system may already be capable, but UX still matters. Capability existing does not mean stakeholder requirement is met.

Policy narrowing must remain source-of-truth driven, not reimplemented in random UI code.

Policy-denied permissions should be visually distinguishable from normal empty permissions, preferably grey/disabled with explanation.

### 3.3 Customer-specific settings page

Known issue:

- Customer-specific Settings page looks ugly/unfinished.
- This should be redesigned/polished later.

Final target:

- Customer settings should show business-friendly sections:
  - Company details
  - Buildings/locations
  - Contacts
  - Customer policy
  - Permission defaults
  - Extra Work preferences
  - Reporting preferences, if needed

### 3.4 Main Settings page

Known issue:

- Main Settings page looks asymmetrical/empty in parts.
- Previous attempts struggled to find useful content for the empty column.

Final target:

- Revisit later after backend/product flows stabilize.
- Do not waste sprint time before core business flows are correct.

### 3.5 Mobile responsiveness

Add a later dedicated mobile responsiveness sprint.

Scope:

- Users pages
- Customer permissions matrix/modal
- Ticket detail
- Extra Work create/detail/proposal areas
- Dashboards/reports
- Settings/customer settings
- Tables that overflow on half-width screens

Known visual issue:

- Some rows overflow when the page is half-width but are okay full-width. This should be fixed with responsive table/card layouts and action wrap discipline.

---

## 4. Ticket workflow — final target

### 4.1 Normal ticket lifecycle

Normal tickets should follow the existing operational workflow.

Completion approval should work like current normal tickets:

- Staff/provider completes work.
- Customer approval is requested where required.
- PA or permitted BM can override approval with warning and audit.
- Override must be visible in audit/history.

### 4.2 Multiple assignees

A ticket can have:

- Multiple staff assigned.
- Multiple managers assigned.

If a building has 5 managers, all 5 can be assigned to the same ticket.

Staff and managers can be assigned to unlimited tickets as long as they are eligible for the building.

### 4.3 Manager/staff eligibility

Eligibility is building-based:

- Staff must be visible/eligible for the building.
- BM must be assigned to the building.
- PA can change manager/staff building assignment first, then assign them to the ticket.

### 4.4 Unable to complete / reschedule

Ramazan meeting requirement:

If staff cannot complete a job:

- Staff should mark unable to complete or equivalent.
- Staff should provide reason/note and optionally evidence.
- Manager should be notified.
- Manager can reschedule/reassign as needed.

This applies especially to recurring/planned jobs but should be consistent with ticket operations.

### 4.5 Notes

Note types remain important:

- Public reply: visible to customer and provider team.
- Provider internal note: visible only to provider admins/BMs, not customer or field staff.
- Operational note: visible to provider operations/assigned staff, not customer.
- Completion note: visible to customer as proof of completed work.

Note visibility must come from backend serializer/source of truth. Frontend must not infer sensitive visibility from truthiness of hidden fields.

---

## 5. Extra Work — final target business workflow

Extra Work must be redesigned around intent. It is no longer one generic flow.

### 5.1 Three Extra Work intents

Extra Work has exactly three customer-facing usage types:

1. Direct agreed-price order
2. Auto-start after pricing
3. Request a quote

These should likely be represented by an explicit backend field, for example:

- `request_intent = DIRECT_ORDER`
- `request_intent = AUTO_START_AFTER_PRICING`
- `request_intent = QUOTE_REQUEST`

Do not explode the existing status model if intent field keeps the lifecycle cleaner.

### 5.2 Direct agreed-price order

Allowed only when all selected lines have customer-specific agreed prices.

Rules:

- If every selected service line has agreed price, customer can directly start/open Extra Work.
- No provider pricing proposal needed.
- No customer quote approval needed.
- Operational Extra Work ticket spawns immediately.
- Customer sees agreed prices before submitting.
- This is the only allowed option if all lines are agreed-price.

Important final correction:

If all selected lines are agreed-price, the system should not allow Request a Quote or Auto-start-after-pricing. It should only allow direct start. If the user tries another flow, backend/frontend should reject/explain.

### 5.3 Auto-start after pricing

Allowed only when at least one selected line is non-agreed/non-contract/custom.

Meaning:

- Customer or provider chooses: “Start after provider enters price.”
- Provider enters price for non-agreed lines.
- The work starts/spawns operational ticket immediately after provider pricing is completed.
- It does NOT go back to customer approval.
- No maximum budget is required.
- No extra warning to customer is required because this matches the real business process and no payment is taken inside the system.

Customer-side eligibility:

- Minimum customer-side role should be Customer Location Manager.
- Customer Company Admin can use it.
- Normal Customer User should not be grantable this capability.

Provider-side usage:

- Provider can open Extra Work on behalf of customer using direct agreed-price order or auto-start-after-pricing.
- Provider does not need Request a Quote for itself.

### 5.4 Request a quote

Allowed only when at least one selected line is non-agreed/non-contract/custom.

Meaning:

- Customer asks provider for price first.
- Provider prepares and sends quote/proposal to customer.
- Customer can accept or reject.
- If customer accepts, operational Extra Work ticket spawns.
- If customer rejects, Extra Work status becomes REJECTED and no operational ticket is spawned.

Request a Quote may include agreed-price lines too, but it must contain at least one non-agreed/custom line. If all lines are agreed-price, quote is not allowed because price is already known.

### 5.5 Dangerous quote bypass permission

Separate from normal auto-start-after-pricing.

Dangerous scenario:

- Customer created Request a Quote.
- Normally provider sends price back and waits for customer accept/reject.
- A Provider Admin may want to enter price and start operational ticket without customer approval.

Final rule:

- This is dangerous and must default OFF for Provider Admin.
- Super Admin can grant this permission to a Provider Admin/company.
- Even when granted, UI must show serious warning.
- Usage must be strongly audit logged and visually marked red/danger in audit log.

This is not the same as customer/provider choosing Auto-start-after-pricing at creation time. Auto-start is normal business flow; quote-bypass is overriding a quote flow after the customer requested approval.

### 5.6 Service lines

Extra Work can include:

- Existing provider service catalog item with customer agreed price.
- Existing provider service catalog item without customer agreed price.
- Free-text custom/ad-hoc service line.

Free-text custom service lines must not automatically become reusable catalog services. If provider wants a reusable service, they add it manually to service catalog.

### 5.7 Customer-visible prices

Customer can see only customer-specific agreed prices.

Customer must not see provider default prices.

If a customer-specific agreed price exists, customer sees it while creating Extra Work.

If no customer-specific agreed price exists, customer can still request quote or auto-start-after-pricing depending on role/intent.

### 5.8 Provider default service catalog

Provider Admin can manually create provider default services and default prices.

Provider default prices are templates/internal defaults.

BM can view provider default prices by default if operationally useful.

BM cannot edit provider default prices by default.

Customer-specific agreed prices can be created from provider defaults, but can be changed per customer.

Different customers may have different prices for the same service.

### 5.9 Customer-specific agreed prices

Provider can set services/prices for a specific customer.

When setting a customer-specific price:

- Provider may select from provider default service catalog.
- Provider may override the price for that customer.
- Provider may later update the customer-specific price.

Historical/snapshot behavior must be carefully designed so old accepted/started work is not silently rewritten by future price edits.

### 5.10 Operational ticket spawn timing

Spawn exactly one operational ticket per Extra Work request.

Spawn rules:

- Direct agreed-price order: spawn immediately.
- Auto-start-after-pricing: spawn after provider enters price.
- Request a Quote: spawn only after customer accepts quote.
- Request a Quote rejected: no spawn; status REJECTED.
- Quote-bypass by PA with SA-granted permission: spawn after provider enters price, with danger audit.

### 5.11 Extra Work completion approval

Once Extra Work has spawned an operational ticket, completion approval should behave like a normal ticket:

- Customer approval where normal ticket flow requires it.
- PA/permitted BM override possible with warning and audit.

### 5.12 Hourly Extra Work / hourly jobs

Ramazan meeting requirement:

Some services may be hourly or actual-hours based.

Flow:

- Provider/customer starts or quotes using hourly rate or estimated hours as applicable.
- Provider/staff completes work.
- Actual hours are entered at completion/finalization.
- Final amount is calculated from actual hours.
- Customer sees final amount during completion approval.
- This should be reflected in reports/revenue.

Need implementation design:

- Service unit type should support hourly.
- Proposal/agreed price should distinguish fixed quantity vs actual-hours finalization.
- Completion flow may require actual hours before work can be marked ready for customer approval.

Implemented (Sprint 8B) — locked decisions:

- `actual_hours` is a nullable column on BOTH the cart line
  (`ExtraWorkRequestItem`) and the proposal line (`ProposalLine`).
  Entering it NEVER overwrites the ordered `quantity` or the
  snapshotted/quoted unit price — the final amount substitutes
  `actual_hours` for `quantity` only on HOURS-unit lines; every other
  unit type (fixed / item / m²) bills the ordered quantity.
- Entry is **provider-only** (SUPER_ADMIN / COMPANY_ADMIN /
  BUILDING_MANAGER, scoped to the EW's building):
  `POST /api/extra-work/<id>/actual-hours/`. STAFF and customer-side
  roles get HTTP 403 `actual_hours_forbidden`.
- The parent EW carries `final_subtotal_amount` / `final_vat_amount` /
  `final_total_amount` (nullable, NULL until the first entry). They are
  recomputed on every actual-hours entry from the active priced-line
  set (approved proposal lines → cart lines → legacy pricing lines).
- **Completion gate**: an Extra Work operational ticket cannot move to
  `WAITING_CUSTOMER_APPROVAL` while any hourly line is missing
  `actual_hours` (HTTP 400 `actual_hours_required`). Fixed-price and
  non-EW tickets are unaffected.
- **Freeze**: `final_*` is frozen when the operational ticket reaches
  customer approval (`APPROVED`). After the operational ticket is
  `APPROVED`/`CLOSED` the final amount is **locked** — further
  actual-hours entry returns HTTP 400 `final_amount_locked`; a reopen
  (CLOSED → REOPENED_BY_ADMIN → IN_PROGRESS) re-enables editing.
- The customer (and provider) sees `final_*` + per-line `actual_hours`
  on the EW detail, and `final_total_amount` on the ticket
  `extra_work_origin` metadata. STAFF is gated OUT of the commercial
  `final_total_amount` (staff-privacy floor) and sees only the safe
  `actual_hours_required` workflow flag on `extra_work_origin` — no
  amount, no provider-internal fields.
- Audit: the line `actual_hours` change auto-diffs through the existing
  generic AuditLog full-CRUD coverage of `ExtraWorkRequestItem` /
  `ProposalLine`; each actual-hours call also writes one
  `ExtraWorkStatusHistory` annotation row (old==new status) capturing
  actor + per-line old→new hours + old→new `final_total_amount`.

---

## 6. Ticket ↔ Extra Work conversion / linking

Ramazan meeting discussed cases where something starts as a normal ticket but is actually Extra Work or requires pricing.

Final desired logic:

- A normal ticket should not simply be mutated invisibly into pricing work.
- There should be a clear conversion/linking model.
- If an existing ticket needs Extra Work pricing, create/link an Extra Work request from that ticket.
- The original ticket should show that Extra Work was created/linked from it.
- After Extra Work pricing is accepted/auto-started, an operational Extra Work ticket exists/continues and remains linked.

User clarification:

Extra Work already becomes operational ticket after pricing/approval. The important thing is not to lose operational identity, origin, or pricing link.

Recommended implementation:

- Use explicit links rather than changing type silently.
- Normal ticket can have `linked_extra_work_request_id` or an activity/history entry.
- Spawned Extra Work ticket has `extra_work_origin` metadata.
- Reports and UI show origin clearly.

Open implementation detail to inspect:

- Whether current spawned ticket model already supports enough origin metadata.
- Whether normal ticket → Extra Work conversion should close/suspend original ticket or keep it open with linked status.

---

## 7. Reports and dashboards — final target

### 7.1 Operational dashboard

Dashboard can show tickets and Extra Work operational tickets in one queue, but type must be clear.

Current copy like “Tickets and extra work share one queue. Use the type pill to tell them apart” is conceptually okay, but UI must make Extra Work origin impossible to miss.

### 7.2 Extra Work dashboard/reporting

Extra Work must have its own dashboard/report views separate from normal tickets.

Do not show Extra Work only as generic ticket counts.

Extra Work reports should include:

- Revenue earned
- In-progress revenue
- Quoted pipeline
- Lost/rejected quotes
- Service/category breakdown
- Customer breakdown
- Building breakdown
- Agreed-price vs custom/non-contract lines
- Fixed-price vs hourly
- Actual hours and final amounts
- Time-to-quote
- Quote acceptance/rejection rate
- Spawned operational tickets

### 7.3 Revenue recognition

Final rule:

- Earned revenue: operational ticket CLOSED.
- In-progress revenue: operational ticket spawned but not closed.
- Quoted pipeline: quote sent/pending but not accepted.
- Lost quote: customer rejected quote.

### 7.4 Normal ticket reports

Normal ticket reports should remain separate from Extra Work reports, but some combined operational reports are allowed.

Combined reports must have clear type breakdown.

### 7.5 PDF/exports

Ramazan meeting implied reporting/export needs. Final system should support useful PDF/CSV exports for management:

- Monthly/weekly operational reports
- Extra Work revenue reports
- Customer/building reports
- Staff/manager performance or workload reports
- Recurring/planned job completion reports

---

## 8. Recurring / planned jobs — Ramazan meeting requirement

This is a major future feature and should be prioritized after the immediate Extra Work backend source-of-truth updates.

### 8.1 Concept

The provider needs planned/recurring jobs, not only ad-hoc tickets.

Examples:

- Monthly planned cleaning tasks
- Scheduled building work
- Repeating jobs with specific dates/days
- Agenda/calendar of upcoming work

### 8.2 Required capabilities

Recurring/planned jobs should support:

- Customer/building selection.
- Service/task selection.
- Schedule/frequency.
- Multiple planned occurrences.
- Assignment to staff and managers.
- Completion tracking per occurrence.
- Unable-to-complete/reschedule flow.
- Notes/evidence per occurrence.
- Reporting by planned vs completed vs missed/rescheduled.

### 8.3 Operational model

Recommended design:

- A RecurringJob/PlannedJob template defines the repeating work.
- Each due occurrence creates or links to an operational ticket/job occurrence.
- Staff/BM manage each occurrence operationally.
- Reports aggregate template + occurrence performance.

### 8.4 Pricing/revenue

Planned jobs may be fixed-price, hourly, or part of contract. Need inspect product policy before implementation.

If hourly, actual hours at completion should feed final amount/revenue.

### 8.5 Sprint timing

This should not be hacked into current ticket status fields. It deserves its own backend sprint after Extra Work intent/pricing model is cleaned.

---

## 9. Audit log — must become system-wide

User explicitly asked: “genel her şey audit koyulcak buglar bakılcak.”

Final target:

Every meaningful business mutation should have audit coverage.

### 9.1 Must-audit events

Audit should cover at least:

- User created/invited/disabled.
- Global role changes.
- Customer access role changes.
- Customer permission matrix changes.
- Customer policy changes.
- Provider dangerous permission grants/revokes.
- Building manager assignment changes.
- Staff building visibility changes.
- Ticket created/status changed/assigned/reassigned/completed/reopened/overridden.
- Ticket notes added, with note type.
- Attachments uploaded/deleted/accessed where relevant.
- Extra Work created/intent selected.
- Extra Work line added/edited/deleted.
- Provider default service price changes.
- Customer-specific agreed price changes.
- Quote sent/accepted/rejected.
- Quote-bypass used.
- Operational ticket spawned from Extra Work.
- Actual hours entered/edited.
- Revenue-relevant final amount changes.
- Recurring job template created/edited/deleted.
- Recurring occurrence completed/rescheduled/unable-to-complete.

### 9.2 Dangerous/red audit events

Some events must be highlighted as dangerous/red:

- PA bypasses customer quote approval and starts work.
- PA/BM overrides customer completion approval.
- Dangerous provider permission granted by Super Admin.
- Customer permission/policy change that broadens access significantly.
- Price edits that affect future work.
- Manual correction to closed/approved financial work.

### 9.3 Audit UX

Audit should be readable by humans:

- Who did it
- What changed
- Before/after values
- Which customer/building/ticket/EW it affects
- Reason/note if required
- Timestamp
- Severity/color

---

## 10. Bug/audit pass — quality gate

Before considering the system “finished,” run a general audit and bug-hunt sprint.

Checklist:

- Role/scope tests for every endpoint.
- Attachment direct URL access tests.
- Customer/user visibility tests.
- Provider/customer cross-tenant isolation tests.
- Ticket/EW status transition tests.
- Price snapshot tests.
- Audit log coverage tests.
- Frontend route guard tests.
- Mobile/responsive manual QA.
- Report number reconciliation.
- Demo data sanity.
- No ugly technical user-facing text.
- No dead disabled buttons without reason.
- No overflow outside cards.

---

## 11. Backend source-of-truth rules

These rules must guide all future Claude Code/backend work.

### 11.1 Backend is business source of truth

Frontend must not infer:

- Contract vs custom price source.
- Whether an Extra Work line needs proposal.
- Whether a user can perform an action.
- Whether customer can see internal note.
- Whether a permission is denied by policy.
- Whether a quote can start work.

Backend must return explicit fields/actions/statuses for frontend to render.

### 11.2 Snapshot rules

Accepted/submitted/priced work must not be silently changed by future price edits.

Provider default and customer-specific price edits should affect future requests, not historical accepted work, unless explicit manual correction is made and audited.

### 11.3 Explicit intent/status separation

Extra Work intent should likely be explicit and separate from lifecycle status.

Statuses describe where the request is in lifecycle. Intent describes why/how it was created.

### 11.4 No frontend role logic creep

Frontend can present sections differently, but it must not replace backend actions with role checks.

Examples:

- Use `actions.can_*` from API.
- Use `allowed_next_statuses` from API.
- Use explicit permission matrix data from backend.

---

## 12. Sprint order — recommended implementation plan

Ramazan’s requested business flows get priority.

### Sprint 0 — Confirm pushed state and update docs

Goal: ensure local/repo state is clean and this source of truth is committed into the repo.

Tasks:

- Verify current branch/HEAD and recent pushed commits.
- Replace/update docs/source-of-truth file with this document.
- Add a short “current implementation vs target” note if needed.
- Do not code product changes in this sprint.

### Sprint 1 — Backend inspect + design lock for Extra Work intent model

Goal: inspect existing backend models before changing anything.

Tasks:

- Inspect ExtraWorkRequest, statuses, routing_decision, pricing line/proposal models, spawned ticket link.
- Inspect service catalog/customer pricing models.
- Inspect current preview-lines endpoint and create flow.
- Decide exact fields:
  - `request_intent`
  - line source fields
  - free-text custom line representation
  - auto-start flags
  - quote-bypass permission
  - spawned ticket link/origin
- Write migration plan.
- Update tests plan.

Output:

- No big implementation unless design is clear.
- A backend task prompt can be generated after inspection.

### Sprint 2 — Extra Work backend: intents and validation

Goal: implement the three-intent rules.

Tasks:

- Add explicit intent field if not present.
- Enforce direct agreed-price order only when all lines agreed.
- Enforce auto-start only when at least one non-agreed/custom line.
- Enforce quote request only when at least one non-agreed/custom line.
- Enforce customer role eligibility for auto-start: Customer Location Manager or Customer Company Admin, not normal Customer User.
- Enforce provider can use direct/auto-start but not request quote for itself.
- Add clear API error codes/messages.
- Add tests for every allowed/denied combination.

### Sprint 3 — Extra Work backend: provider default services and customer-specific agreed prices

Goal: make pricing model correct and invisible where needed.

Tasks:

- Provider default service catalog/prices.
- Provider default prices invisible to customers.
- BM default view only, no edit by default.
- Customer-specific agreed price creation from provider default template.
- Customer-specific override price.
- Snapshot behavior tests.
- Audit price changes.
- API endpoints/actions for frontend.

### Sprint 4 — Extra Work backend: quote/proposal, auto-start, quote-bypass

Goal: complete pricing-to-operational spawn logic.

Tasks:

- Auto-start after provider enters price.
- Quote send/accept/reject.
- Reject status = REJECTED, no spawn.
- Dangerous quote-bypass permission default OFF.
- Super Admin can grant quote-bypass permission to PA.
- Warning/action metadata for frontend.
- Red audit event when bypass used.
- Tests.

### Sprint 5 — Extra Work backend: hourly/actual-hours finalization

Goal: support hourly work and final amount.

Tasks:

- Unit type/hourly handling.
- Actual hours required before completion/final approval where applicable.
- Final amount calculation.
- Customer sees actual hours/final amount in completion approval.
- Revenue reporting uses final amount.
- Tests.

### Sprint 6 — Ticket/EW origin and conversion/linking

Goal: Extra Work-origin operational tickets are clear and conversion cases are safe.

Tasks:

- Inspect existing `extra_work_origin` metadata.
- Ensure spawned tickets clearly link to ExtraWorkRequest/item/service lines.
- Add normal ticket → Extra Work request conversion/link flow if missing.
- Preserve original ticket history.
- UI/API fields for origin pill/details.
- Reports separate EW-origin tickets.
- Tests.

### Sprint 7 — Assignment model audit and multi-manager/multi-staff

Goal: support desired assignment model.

Tasks:

- Inspect current ticket assignment model.
- Confirm whether multiple staff already supported.
- Add multiple manager assignment if missing.
- Ensure staff/BM can be assigned to unlimited tickets in eligible buildings.
- Ensure eligible staff/BM filtered by building.
- PA can update building assignment then assign.
- Audit assignment changes.
- Tests.

### Sprint 8 — Recurring/planned jobs backend

Goal: implement Ramazan’s planned/recurring work model.

Tasks:

- PlannedJob/RecurringJob template.
- Occurrence generation.
- Assignment per occurrence.
- Complete/unable-to-complete/reschedule.
- Evidence/notes.
- Reports.
- Tests.

### Sprint 9 — Reports backend

Goal: make reporting business-accurate.

Tasks:

- Separate normal ticket reports.
- Separate Extra Work reports.
- Combined operational reports with type breakdown.
- Revenue states: earned/in-progress/pipeline/lost.
- Category/service/customer/building breakdowns.
- Hourly actuals.
- Export/PDF/CSV as needed.
- Tests that reconcile numbers.

### Sprint 10 — System-wide audit backend

Goal: complete audit coverage.

Tasks:

- Audit event model review.
- Add missing audit coverage.
- Red/danger events.
- Before/after values.
- Audit UI/API fields.
- Tests.

### Sprint 11 — Users/invitations/frontend + backend cleanup

Goal: fix user pages and role/access-role confusion.

Tasks:

- Global Users page: show/filter Customer Company Admin and Customer Location Manager.
- Invite flow: correct customer access role choices.
- Prevent nonsensical role changes.
- Staff edit page polish.
- Customer user access and permission links clear.
- Backend serializers may need extra role/access_role fields.
- Tests.

### Sprint 12 — Customer settings + settings polish

Goal: clean ugly settings surfaces.

Tasks:

- Customer-specific settings page redesign.
- Main settings asymmetry review.
- Remove technical copy.
- Ensure customer policy/settings are understandable.

### Sprint 13 — Frontend Extra Work updates consuming new backend

Goal: after backend truth exists, frontend can implement final flows.

Tasks:

- Three intent choices with backend-driven validation.
- Direct order UI.
- Auto-start-after-pricing UI.
- Request quote UI.
- Customer sees only agreed prices.
- Provider default service management UI.
- Customer-specific agreed price UI.
- Quote accept/reject UI.
- Actual hours/final amount UI.
- No frontend inference.

### Sprint 14 — Reports/dashboard frontend

Goal: final management views.

Tasks:

- Extra Work dashboard like ticket dashboard, not just number cards.
- Extra Work revenue reports.
- Combined operational queue with strong type/origin pills.
- Exports.

### Sprint 15 — Mobile responsiveness and visual QA

Goal: make the app demo/production-polished on real screen sizes.

Tasks:

- Responsive tables/cards.
- Permission matrix/mobile behavior.
- Ticket/EW detail mobile layout.
- Settings pages.
- User pages.
- Half-width row overflow.
- Action button wrap discipline.

### Sprint 16 — Final bug/audit acceptance pass

Goal: no critical gaps before pilot/final delivery.

Tasks:

- Full backend tests.
- Frontend build/typecheck/lint.
- E2E smoke.
- Manual QA checklist.
- Security/scope audit.
- Demo data cleanup.
- Documentation updated.

---

## 13. Immediate next action

Do not start frontend-only redesign work that requires backend truth changes.

Recommended immediate next step:

1. Commit this source-of-truth update.
2. Open a backend-only inspection sprint for Extra Work intent/pricing model.
3. Implement backend contracts cleanly.
4. Only then ask frontend/Claude Web to design screens against stable API fields.

---

## 14. Non-negotiables

- Backend is source of truth.
- No frontend price/source inference.
- No hidden Extra Work operational tickets pretending to be normal tickets.
- Customer sees only customer-specific agreed prices, never provider default prices.
- Provider default prices are templates, not customer-visible prices.
- Quote request must contain at least one non-agreed/custom line.
- Direct order only when all lines are agreed-price.
- Auto-start only when at least one non-agreed/custom line and customer role/permission allows it.
- Quote-bypass is dangerous, SA-granted, default off, warning + red audit.
- One Extra Work request spawns one operational ticket.
- Completion approval for Extra Work operational tickets follows normal ticket approval rules.
- Actual hours/final amount needed for hourly work.
- Multi-staff and multi-manager assignment must be supported.
- Recurring/planned jobs are a real future module, not a hack.
- Every important mutation must be audited.
- Final system must be responsive and not show technical/dev copy to users.

---

## 15. Traceability: what this document captures

This source of truth intentionally combines three inputs:

1. **Current implemented product state** as of the latest frontend work reported by the user and the pushed branch review. The recent frontend arc includes the Extra Work invoice-row improvements, draft proposal line visibility, ticket-detail workflow/note clarity, global/local overflow fixes, customer permissions matrix/modal, and customer Extra Work tab work. These are treated as the current UI baseline, not as future requirements.
2. **User/product decisions made in chat** about how Osius must work when finished: Extra Work intent rules, provider default pricing vs customer agreed pricing, dangerous quote-bypass permission, multi-staff/multi-manager assignment, reports/revenue rules, and user/customer permission UX.
3. **Ramazan meeting requirements from the transcript**: contact/person management, hours and hourly work, Extra Work conversion/operational ticket behavior, reporting separation, planned/recurring work, export/report needs, and the need for the system to be understandable for real operational users rather than technically correct but confusing.

This means the document is not only a code audit. It is the target product behavior. If code and this document disagree, inspect first, then either change code or deliberately update this document with a new decision.

---

## 16. Current frontend baseline and known UI backlog

The frontend is considered a working demo baseline, not final product quality. The recent P0/P1 frontend work is reported as completed, including the customer permissions matrix/modal. The remaining UI backlog should not be mixed into backend source-of-truth work unless it needs backend support.

### 16.1 Completed/recently pushed frontend baseline to preserve

- Extra Work create post-submit cart preview uses backend-driven source labels.
- Extra Work detail shows requested service lines and provider pricing lines through the shared invoice-row component.
- Draft proposal lines are visible read-only on Extra Work detail where supported.
- Ticket detail workflow is clearer, with normal vs correction/advanced actions separated using backend-allowed transitions.
- Note type copy explains who sees each note.
- Customer permissions matrix/modal exists and should be preserved as the preferred UX over raw drawer-style permission editing.
- Customer Extra Work tab is wired to the filtered Extra Work list.

### 16.2 Known UI backlog to keep in the final checklist

- **Users area / role model UX audit:** Super Admin currently appears able to change users into broad roles in confusing ways. Customer Company Admin and Customer Location Manager are not first-class enough in the Users listing/filter/invite/edit flow. The page must clearly separate system role from customer access role/membership role.
- **Customer admin/location manager discoverability:** Users list must allow finding/filtering customer-side admins/location managers. A Super Admin and allowed Provider Admin must be able to reach the correct customer-specific permission screen from the user/customer context.
- **Staff edit/profile page polish:** Field staff edit/profile page has technical copy and ugly case-assignment/building visibility layout. Replace developer wording with user-facing copy and polish spacing/cards.
- **Customer-specific settings polish:** Individual customer settings page is visually weak and should be redesigned after backend truth is stable.
- **Global settings page asymmetry:** General settings page remains visually asymmetric; not urgent, but final polish should revisit it.
- **Mobile responsiveness:** Add a dedicated late-stage responsive QA/fix sprint across dashboard, tickets, Extra Work, customers, permissions matrix/modal, users, and settings.
- **Reports UX:** Extra Work reports must not be hidden inside generic ticket reporting. Some charts can combine tickets and Extra Work, but Extra Work revenue/category/hourly/quote pipeline reports must exist separately.

