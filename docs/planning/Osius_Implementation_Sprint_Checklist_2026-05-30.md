# Osius Implementation Sprint Plan + Checklist

**Date:** 2026-05-30  
**Purpose:** This is the execution checklist for the Osius Source of Truth. The Source of Truth explains what the finished system must do; this file is the sprint-by-sprint list to tick off while implementing it.

## How to use this checklist

- Keep this file as the working project checklist.
- Do not mark a sprint complete only because code compiles. Mark it complete only when the acceptance checks pass.
- Backend contract changes must be finished before frontend tasks that consume them.
- Ramazan meeting requirements are prioritised early, but implementation order still keeps risky backend foundations before UI polish.
- Before each sprint: inspect current code, confirm what already exists, then build only the missing piece.
- After each sprint: run backend tests, frontend typecheck/build/lint when frontend is touched, and update this checklist.

---

# Sprint 0 — Baseline verification and repo audit

**Goal:** Make sure the current pushed branch and local system match the documented state before changing backend logic.

- [ ] Confirm current Git branch/PR state and latest pushed commits.
- [ ] Confirm working tree is clean before starting backend work.
- [ ] Verify the recent frontend baseline is present:
  - [ ] Extra Work invoice-row UI.
  - [ ] Draft proposal read-only line display.
  - [ ] Ticket workflow/note copy clarity.
  - [ ] Customer permissions matrix/modal.
  - [ ] Customer Extra Work tab.
- [ ] Run full backend test suite baseline or agreed subset.
- [ ] Run frontend `typecheck`, `build`, and lint baseline.
- [ ] Record known failing tests/lint warnings separately so new regressions are visible.
- [ ] Quick audit for accidental role-based frontend gating replacing backend actions.
- [ ] Quick audit for unsafe direct object access/scope bypass paths.

**Acceptance:** There is a clean baseline report and no sprint starts from an unknown branch state.

---

# Sprint 1 — Source of Truth docs + canonical business rules

**Goal:** Land the updated source-of-truth documents in the repo so every later Claude/AI/backend/frontend session has the same target.

- [ ] Add/update the full Source of Truth markdown in the repo docs.
- [ ] Add this implementation checklist in the repo docs.
- [ ] Make the docs clearly say:
  - [ ] Extra Work has three intents.
  - [ ] Provider default prices are templates and are not visible to customers.
  - [ ] Customer agreed prices are visible to customers.
  - [ ] Request Quote needs at least one non-agreed/custom line.
  - [ ] Direct order is allowed only when all selected lines have agreed prices.
  - [ ] Auto-start after pricing is allowed only when at least one line needs provider pricing.
  - [ ] Quote acceptance/rejection controls operational ticket spawn.
  - [ ] Revenue is earned only when the spawned operational ticket is closed.
  - [ ] Extra Work operational tickets must retain clear origin and reporting separation.
  - [ ] Ramazan meeting requirements are explicitly captured.
- [ ] Add a rule: docs are source of truth; code changes that intentionally differ must update docs in the same sprint.

**Acceptance:** A new chat can read the docs and understand the final system, pending work, and sprint order without needing old conversations.

---

# Sprint 2 — Extra Work backend domain model foundation

**Goal:** Add the backend data model needed for the new Extra Work rules without breaking the current working UI.

## 2.1 Intent model

- [ ] Add request intent field or equivalent canonical state to Extra Work:
  - [ ] `DIRECT_AGREED_PRICE_ORDER`
  - [ ] `AUTO_START_AFTER_PRICING`
  - [ ] `REQUEST_QUOTE`
- [ ] Keep lifecycle status separate from intent; do not explode statuses unnecessarily.
- [ ] Add validation rules:
  - [ ] All-agreed cart permits only Direct Agreed-Price Order.
  - [ ] Mixed/non-agreed cart forbids Direct Agreed-Price Order.
  - [ ] Mixed/non-agreed cart permits Auto-start After Pricing where actor is allowed.
  - [ ] Request Quote requires at least one non-agreed/custom line.
  - [ ] Provider-side creation may use Direct or Auto-start, but not Request Quote.
- [ ] Preserve current existing statuses where possible.
- [ ] Add migrations.
- [ ] Add model/service tests for every cart/intent combination.

## 2.2 Free-text/ad-hoc service lines

- [ ] Support service catalog lines.
- [ ] Support ad-hoc/free-text custom service lines.
- [ ] Ensure ad-hoc text never automatically becomes a reusable provider service.
- [ ] Require provider pricing for ad-hoc lines.
- [ ] Ensure ad-hoc line audit/history is preserved on the request/proposal.

## 2.3 Pricing snapshots

- [ ] Agreed/customer-specific price lines must snapshot unit price, VAT, source, and service identity at request/proposal time.
- [ ] Later customer price edits must not rewrite historical operational/ticket amounts.
- [ ] Provider default price edits must not rewrite historical agreed price snapshots.
- [ ] Tests for historical snapshots after price mutation/deletion.

**Acceptance:** Backend can represent all three Extra Work intents, ad-hoc lines, and historical prices safely.

---

# Sprint 3 — Provider service catalog + provider default prices

**Goal:** Let provider-side users define reusable services and default prices that can later be copied/customised into customer-specific agreed prices.

- [ ] Add/verify provider service catalog model:
  - [ ] service name
  - [ ] category
  - [ ] unit type
  - [ ] active/inactive
  - [ ] optional description
  - [ ] provider company scope
- [ ] Add provider default price model:
  - [ ] service
  - [ ] provider company
  - [ ] default unit price
  - [ ] VAT %
  - [ ] effective date/versioning if needed
  - [ ] active/inactive
- [ ] Visibility rules:
  - [ ] Super Admin can see/manage all.
  - [ ] Provider Admin can manage own provider defaults only if allowed.
  - [ ] Building Manager can see provider default prices by default.
  - [ ] Building Manager cannot edit defaults by default.
  - [ ] Staff/customer users cannot see provider default prices.
  - [ ] Customers never see provider default prices directly.
- [ ] Add permission/action keys for managing defaults if missing.
- [ ] Add backend endpoints for list/create/update/archive.
- [ ] Add audit events for create/update/archive/default price changes.
- [ ] Add tests for visibility and permission boundaries.

**Acceptance:** Provider default prices exist as internal templates only, never as customer-visible prices.

---

# Sprint 4 — Customer agreed prices from provider defaults

**Goal:** Allow provider/admin users to assign customer-specific agreed prices, optionally copying from provider default prices.

- [ ] Add/verify customer agreed price model:
  - [ ] customer
  - [ ] building applicability if needed
  - [ ] service
  - [ ] agreed unit price
  - [ ] VAT %
  - [ ] active/inactive
  - [ ] effective date/versioning if needed
- [ ] Backend create/update flow:
  - [ ] User can manually enter customer-specific price.
  - [ ] User can copy from provider default price, then override for that customer.
  - [ ] Customer agreed price can be changed later.
  - [ ] Changes do not mutate historical Extra Work lines.
- [ ] Customer visibility:
  - [ ] Customer users see agreed prices available to their customer/building scope.
  - [ ] They do not see provider default prices.
- [ ] Add list/filter endpoints for customer-specific service prices.
- [ ] Add audit events for agreed price create/update/archive.
- [ ] Tests for different customers receiving different prices for same provider service.

**Acceptance:** Customer-specific agreed pricing is safe, visible to allowed customer users, and isolated between customers.

---

# Sprint 5 — Extra Work preview/classification endpoint

**Goal:** Backend classifies draft carts before submit so frontend never infers contract/agreed/custom state client-side.

- [ ] Push/integrate the preview-lines endpoint work if still local-only.
- [ ] Endpoint accepts draft cart lines and intent candidate.
- [ ] Endpoint returns per-line classification:
  - [ ] agreed/customer price
  - [ ] needs provider pricing
  - [ ] ad-hoc/free-text
  - [ ] subtotal/VAT/total where available
- [ ] Endpoint returns valid intent options for this cart and actor.
- [ ] Endpoint returns blocking reasons for invalid intent selections.
- [ ] Endpoint is compute-only and persists nothing.
- [ ] Scope checks mirror create path.
- [ ] Tests for Super Admin, Provider Admin, Building Manager, Customer Company Admin, Customer Location Manager, and basic Customer User where relevant.

**Acceptance:** UI can show valid actions before submit without doing its own pricing inference.

---

# Sprint 6 — Extra Work create/submit backend behavior

**Goal:** Enforce the three-intent rules at submission and spawn operational tickets at the correct time.

## 6.1 Direct Agreed-Price Order

- [ ] Allowed only when every line has agreed customer price.
- [ ] Customer can submit directly.
- [ ] System creates Extra Work request and immediately spawns/open operational ticket.
- [ ] No provider pricing proposal step.
- [ ] Ticket has clear `origin = EXTRA_WORK` metadata.

## 6.2 Auto-start After Pricing

- [ ] Allowed only when at least one line needs provider pricing.
- [ ] Customer Location Manager and Customer Company Admin can select it.
- [ ] Basic Customer User must not be able to select it, even via per-user permission.
- [ ] Provider-side user can create on behalf of customer using this intent where allowed.
- [ ] Provider enters prices.
- [ ] After provider submits prices, operational ticket spawns/opens immediately.
- [ ] No customer price approval step.
- [ ] Audit clearly records that customer pre-authorised start after pricing.

## 6.3 Request Quote

- [ ] Allowed only when at least one line needs provider pricing.
- [ ] Customer asks only for a price.
- [ ] Provider prepares quote and sends it to customer.
- [ ] Customer accepts → operational ticket spawns/opens.
- [ ] Customer rejects → Extra Work becomes `REJECTED`; no ticket spawns.
- [ ] Provider cannot use Request Quote to ask itself for a quote.

**Acceptance:** Operational ticket spawn timing exactly matches the agreed business rules.

---

# Sprint 7 — Dangerous provider override permissions and audit

**Goal:** Add the special permission where Provider Admin may convert a customer Request Quote into operational work after pricing, but only if Super Admin enabled it.

- [ ] Add provider/company-level dangerous permission, default OFF:
  - [ ] candidate name: `provider.extra_work.quote_override_start`
  - [ ] only Super Admin can grant/revoke it.
- [ ] Provider Admin cannot self-grant this.
- [ ] Even when enabled, UI/backend must treat it as dangerous.
- [ ] Backend endpoint/action requires explicit confirmation flag/reason.
- [ ] Audit log event is high severity/red category.
- [ ] Audit includes actor, provider company, customer, request, quoted amount, timestamp, reason, old state, new state.
- [ ] Tests for default deny, SA enable, PA use, PA without permission blocked, BM blocked unless explicitly designed otherwise.

**Acceptance:** The risky real-world workflow exists, but is controlled by Super Admin and auditable.

---

# Sprint 8 — Extra Work operational ticket integration

**Goal:** Extra Work can become an operational ticket without losing its origin or confusing operations/reports.

- [ ] Operational ticket generated from Extra Work has explicit origin metadata:
  - [ ] `origin_type = EXTRA_WORK`
  - [ ] link to Extra Work request
  - [ ] source intent
  - [ ] agreed/quoted financial snapshot
- [ ] Ticket list/dashboard shows Extra Work origin clearly.
- [ ] Ticket detail shows linked Extra Work context clearly.
- [ ] Extra Work ticket still follows normal operational workflow.
- [ ] Customer completion approval follows normal ticket rules.
- [ ] PA/BM override rules match normal ticket override/audit behavior.
- [ ] Extra Work cannot disappear as an ordinary ticket in reporting.
- [ ] Tests for link integrity and origin visibility.

**Acceptance:** Operations can manage Extra Work work through tickets, but reports and UI always know it came from Extra Work.

---

# Sprint 9 — Hourly/actual-hours work

**Goal:** Support Ramazan's hourly-work requirement.

- [ ] Add service/unit support for hourly work.
- [ ] For hourly lines, agreed/quoted price may be rate per hour.
- [ ] Provider enters actual hours when work is completed or before completion approval.
- [ ] Final amount is calculated from actual hours and hourly rate.
- [ ] Customer sees actual hours and final amount during completion approval.
- [ ] Completion approval accepts/rejects based on final amount/proof.
- [ ] Historical snapshots preserve quoted rate and actual hours.
- [ ] Tests for hourly final amount, customer completion view, and report totals.

**Acceptance:** Hourly Extra Work can be priced, executed, approved, and reported accurately.

---

# Sprint 10 — Contacts / customer people model

**Goal:** Support contacts/persons under a customer, with one contact linked to multiple buildings.

- [ ] Inspect current customer user/contact model.
- [ ] Define contact vs login user clearly:
  - [ ] A contact may be informational only.
  - [ ] A customer user can be a login-enabled contact/member.
- [ ] A contact can belong to one customer and multiple buildings.
- [ ] Store phone/email/job title/notes as needed.
- [ ] UI/API must distinguish building access from account role.
- [ ] Customer Company Admin and Customer Location Manager handling must be first-class.
- [ ] Tests for one contact across multiple buildings.

**Acceptance:** Customer contacts and customer users are not confused, and multi-building contacts work.

---

# Sprint 11 — Assignment model audit and multi-assignment support

**Goal:** Confirm and, if needed, implement multi-staff and multi-manager assignment to tickets and Extra Work-origin tickets.

- [ ] Inspect current ticket assignment models.
- [ ] Confirm whether multiple staff per ticket already exists.
- [ ] Confirm whether multiple managers per ticket exists.
- [ ] If missing, implement many-to-many assignment model/history.
- [ ] Rules:
  - [ ] A ticket can have multiple staff.
  - [ ] A ticket can have multiple managers.
  - [ ] If a building has 5 managers, all 5 can be assigned to the same ticket.
  - [ ] Staff/manager can be assigned to unlimited tickets in buildings where they are authorised.
  - [ ] A manager from another building must first receive building assignment, then can be assigned.
- [ ] PA can update manager building assignment where allowed, then assign them.
- [ ] Audit assignment changes.
- [ ] Tests for multi-manager, multi-staff, cross-building denial, and reassignment.

**Acceptance:** Assignment matches real operational practice and supports Extra Work-origin tickets too.

---

# Sprint 12 — Users, roles, memberships, and invitation UX/backend audit

**Goal:** Fix the confusing Users area so system role, provider role, customer role, and customer access role are not mixed.

- [ ] Audit backend user model, memberships, access roles, invite flow, and UI assumptions.
- [ ] Clarify terminology:
  - [ ] Super Admin
  - [ ] Provider Admin / Provider Company Admin
  - [ ] Building Manager
  - [ ] Staff / Field Staff
  - [ ] Customer Company Admin
  - [ ] Customer Location Manager
  - [ ] Customer User
- [ ] Users list must show customer admins/location managers as such, not hide them under generic Customer User only.
- [ ] Users list filters must allow Customer Company Admin and Customer Location Manager.
- [ ] Invite flow must support correct customer-side access roles where appropriate.
- [ ] Provider Admin must not be able to make arbitrary users Super Admin / BM / customer admin outside allowed scope.
- [ ] PA must not make a customer user into the provider's BM unless the actual provider-side membership/assignment is created by an allowed path.
- [ ] Editing a user's permissions should route to the correct customer-specific permission matrix where applicable.
- [ ] Remove or rewrite technical helper copy from staff/user pages.
- [ ] Tests for role filters, invite options, and forbidden role changes.

**Acceptance:** Users area becomes a safe navigation/control center instead of a confusing role dropdown.

---

# Sprint 13 — Customer permissions matrix hardening

**Goal:** Preserve the new matrix/modal UX and lock it with tests.

- [ ] Verify current matrix/modal matches stakeholder request:
  - [ ] Excel-like matrix visible without opening each user.
  - [ ] Optical-answer-sheet style clickable permission bubbles.
  - [ ] Edit Permissions opens modal, not the old right drawer.
  - [ ] Right drawer fully removed or no longer primary.
- [ ] Confirm tri-state inherit/allow/deny is preserved.
- [ ] Confirm policy-denied permissions are visually distinct and not editable incorrectly.
- [ ] Confirm effective permissions are computed by existing resolver, not duplicated logic.
- [ ] Add/update tests for matrix rendering, modal editing, and policy narrowing.
- [ ] Preserve accessibility labels and keyboard usability.

**Acceptance:** Permission UX is stakeholder-friendly but still faithful to backend policy logic.

---

# Sprint 14 — Reporting and dashboards: tickets vs Extra Work

**Goal:** Give Ramazan the reporting separation he asked for.

- [ ] Dashboard operational queue shows tickets and Extra Work-origin tickets together with clear type pill.
- [ ] Extra Work-only dashboard/report view exists.
- [ ] Reports can combine tickets + Extra Work where useful.
- [ ] Reports can separate normal tickets vs Extra Work-origin tickets.
- [ ] Extra Work revenue reports:
  - [ ] earned revenue when operational ticket CLOSED
  - [ ] in-progress revenue when spawned but not closed
  - [ ] quoted pipeline when quote sent but not accepted
  - [ ] lost quote when customer rejected
- [ ] Extra Work category/service reports.
- [ ] Hourly work reports: actual hours, rate, final amount.
- [ ] Provider/customer filters.
- [ ] Building/date/status/category filters.
- [ ] Export support where needed.
- [ ] Tests for aggregation correctness and tenant scoping.

**Acceptance:** Extra Work is financially/reporting-wise first-class, not just hidden among tickets.

---

# Sprint 15 — Customer and provider settings polish

**Goal:** Fix visually weak settings/customer pages after backend contracts are stable.

- [ ] Customer-specific settings page redesign/polish.
- [ ] General settings page asymmetry review.
- [ ] Staff profile/edit page copy and layout polish.
- [ ] Remove technical copy like implementation notes from user-facing UI.
- [ ] Ensure settings pages use consistent cards, spacing, and action placement.
- [ ] Tests/snapshots where useful.

**Acceptance:** Settings/user management pages no longer look half-finished.

---

# Sprint 16 — Mobile responsiveness and UI QA pass

**Goal:** Late-stage responsiveness after features are stable.

- [ ] Mobile QA on dashboard.
- [ ] Mobile QA on ticket list/detail.
- [ ] Mobile QA on Extra Work create/detail/proposal/quote flows.
- [ ] Mobile QA on customer permissions matrix/modal.
- [ ] Mobile QA on users/invitations/settings.
- [ ] Fix horizontal row overflow when page is half-width.
- [ ] Ensure cards/tables scroll or stack intentionally.
- [ ] Ensure action clusters wrap inside card boundaries.
- [ ] Avoid global redesign; fix responsiveness defects.

**Acceptance:** No critical workflows break on narrow viewport or half-screen desktop window.

---

# Sprint 17 — Planned / recurring work

**Goal:** Implement planned/recurring operational work after the core Extra Work and reporting changes.

- [ ] Decide recurring job model and recurrence rules.
- [ ] Planned jobs create operational tickets at scheduled times.
- [ ] Planned jobs can be linked to contract/customer/building.
- [ ] Exceptions/cancellations/reschedules are auditable.
- [ ] Reporting separates planned recurring work from ad-hoc tickets and Extra Work.

**Acceptance:** Recurring/planned jobs are supported without polluting Extra Work semantics.

---

# Sprint 18 — Full audit log and bug/regression hardening

**Goal:** Final safety pass before production/pilot.

- [ ] Audit log coverage review:
  - [ ] role/membership changes
  - [ ] customer permission changes
  - [ ] provider dangerous permission changes
  - [ ] provider default price changes
  - [ ] customer agreed price changes
  - [ ] Extra Work intent/status changes
  - [ ] quote accepted/rejected/overridden
  - [ ] ticket assignment changes
  - [ ] completion approval overrides
- [ ] Red/high-severity audit events for dangerous provider override actions.
- [ ] Tenant isolation tests for all new reports/endpoints.
- [ ] Attachment/security regression.
- [ ] API permission regression.
- [ ] Frontend route access regression.
- [ ] End-to-end smoke for core flows.
- [ ] Bug bash using Ramazan demo scenarios.

**Acceptance:** The system is safe to show as a serious pilot, not just a working prototype.

---

# Recommended sprint order summary

1. Sprint 0 — Baseline verification and repo audit
2. Sprint 1 — Source of Truth docs + canonical business rules
3. Sprint 2 — Extra Work backend domain model foundation
4. Sprint 3 — Provider service catalog + provider default prices
5. Sprint 4 — Customer agreed prices from provider defaults
6. Sprint 5 — Extra Work preview/classification endpoint
7. Sprint 6 — Extra Work create/submit backend behavior
8. Sprint 7 — Dangerous provider override permissions and audit
9. Sprint 8 — Extra Work operational ticket integration
10. Sprint 9 — Hourly/actual-hours work
11. Sprint 10 — Contacts / customer people model
12. Sprint 11 — Assignment model audit and multi-assignment support
13. Sprint 12 — Users, roles, memberships, and invitation UX/backend audit
14. Sprint 13 — Customer permissions matrix hardening
15. Sprint 14 — Reporting and dashboards: tickets vs Extra Work
16. Sprint 15 — Customer and provider settings polish
17. Sprint 16 — Mobile responsiveness and UI QA pass
18. Sprint 17 — Planned / recurring work
19. Sprint 18 — Full audit log and bug/regression hardening

## Why this order

- Ramazan's core asks are prioritised: Extra Work behavior, hourly work, contacts, reports, operational clarity.
- Backend truth comes before frontend polish.
- Risky permission/audit work happens before expanding UI controls.
- Mobile responsiveness is intentionally late because screens are still changing.
- Planned/recurring jobs are important but should not be built before the Extra Work/operational model is stable.

