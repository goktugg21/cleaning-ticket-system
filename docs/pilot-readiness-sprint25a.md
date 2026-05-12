# Sprint 25A — pilot-readiness audit

Sprint 25A audited the real operational ticket workflow against
the pilot brief. Below is what was checked, what passed, what was
fixed, and what is deferred.

## Journeys audited

### A. Customer ticket creation
**PASS.** `TicketCreateSerializer.validate()`
([backend/tickets/serializers.py:274–412](../backend/tickets/serializers.py))
enforces every required gate:

- M:N `CustomerBuildingMembership` link between customer + building.
- Active customer + active building.
- Per-role scoping: SUPER_ADMIN passes; COMPANY_ADMIN requires
  `CompanyUserMembership`; BUILDING_MANAGER requires
  `BuildingManagerAssignment`; CUSTOMER_USER requires an ACTIVE
  `CustomerUserBuildingAccess` row resolving the
  `customer.ticket.create` permission. `CUSTOMER_COMPANY_ADMIN`
  spans buildings.
- Direct URL access to out-of-scope tickets returns 404 via
  `scope_tickets_for` (verified by existing Sprint 23A foundation
  tests).

### B. Ticket messages + internal notes
**PASS.** Three layers of defence in
[backend/tickets/views.py:359–406](../backend/tickets/views.py)
and [backend/tickets/serializers.py:432–437](../backend/tickets/serializers.py):

- Queryset filter strips `is_hidden=True` and `INTERNAL_NOTE` rows
  for non-staff.
- `perform_create` forces non-staff to `PUBLIC_REPLY`.
- Serializer-level `validate_message_type` rejects `INTERNAL_NOTE`
  from non-staff.

### C. Attachments
**PASS.**
- Upload: `validate_file` enforces 10 MB cap + the
  `ALLOWED_ATTACHMENT_MIME_TYPES` + `ALLOWED_ATTACHMENT_EXTENSIONS`
  allow-list (jpg/jpeg/png/webp/heic/heif/pdf).
- Download: `TicketAttachmentDownloadView.get` runs
  `scope_tickets_for` then the hidden-attachment gate
  (`is_hidden` OR parent `INTERNAL_NOTE`/`is_hidden` message) so
  CUSTOMER_USER cannot download internal attachments by ID.
- List queryset strips `is_hidden` attachments + INTERNAL_NOTE
  parent attachments for non-staff.

### D. Direct staff assignment
**BUG — fixed in this PR.** See _Bugs found and fixed_ below.

### E. Status workflow
**PASS.**
- `ALLOWED_TRANSITIONS`
  ([backend/tickets/state_machine.py:18–57](../backend/tickets/state_machine.py))
  is per-role and per-scope. STAFF is intentionally NOT in the
  table — Sprint 23A models field-staff as workers who do not
  drive workflow transitions; their supervisor (BUILDING_MANAGER)
  does.
- `change_status` rejects non-staff trying to move outside the
  customer-only APPROVED/REJECTED targets.
- CUSTOMER_USER transitions require pair-access on
  `(customer, building)` via `SCOPE_CUSTOMER_LINKED`, mirroring
  `scope_tickets_for`.
- Sprint 24D's `select_for_update` keeps the read→write window
  atomic.
- Frontend renders buttons from `ticket.allowed_next_statuses`
  computed per-role server-side, so no role gets a button it
  cannot actually use.

### F. UI readiness
- **No raw i18n keys** on the touched ticket-detail surface
  (verified by the new Sprint 25A Playwright invariant — see
  Tests below).
- **Mobile**: the new Sprint 25A admin block is a vertical
  flex/stack with a flex-wrap on the add row, so it does not
  introduce horizontal overflow on touched ticket-detail pages.
  Existing Sprint 23C / 24A / 24C invariants at 390 / 430 / 480
  px remain pinned by their specs.
- The block is gated on the existing `isStaff` flag (SUPER_ADMIN /
  COMPANY_ADMIN / BUILDING_MANAGER) so CUSTOMER_USER and STAFF
  never see it.

## Bugs found and fixed

### D1 — No admin/manager path to direct-assign a STAFF user

**Bug**: The Sprint 23B `StaffAssignmentRequest` flow was the
**only** path to populate `TicketStaffAssignment` (the M:N field-
staff list shown on the ticket detail card). The existing
`TicketViewSet.assign` action only accepts a `BUILDING_MANAGER`
into `ticket.assigned_to`; `TicketAssignSerializer.validate()`
explicitly rejects STAFF role
([backend/tickets/serializers.py:614](../backend/tickets/serializers.py)).
This contradicts the pilot brief's explicit domain statement:

> A staff member does NOT need to request assignment in order to
> be assigned to a ticket. Staff self-request is optional.
> **Admin/manager direct staff assignment is the main operational
> assignment flow.**

**Fix (minimal):**
- New endpoint module
  [backend/tickets/views_staff_assignments.py](../backend/tickets/views_staff_assignments.py):
  - `GET  /api/tickets/<id>/assignable-staff/` (exposed via a viewset
    `@action` on `TicketViewSet`).
  - `GET  /api/tickets/<id>/staff-assignments/`
  - `POST /api/tickets/<id>/staff-assignments/`  `{user_id}` → add.
  - `DELETE /api/tickets/<id>/staff-assignments/<user_id>/` → remove.
- Permission gate mirrors Sprint 23B's approve flow:
  caller must be `is_staff_role()` AND hold
  `osius.ticket.assign_staff` for the ticket's building. STAFF and
  CUSTOMER_USER are rejected. Cross-company actors hit
  `scope_tickets_for` → 404.
- Target STAFF must hold `role=STAFF`, have an active
  `StaffProfile`, AND have `BuildingStaffVisibility` on the
  ticket's building.
- Idempotent POST (`get_or_create`).
- Audit logs: the existing `audit/signals.py` handlers track
  `TicketStaffAssignment` create/delete since Sprint 23A, so no
  new audit wiring is needed.
- Sprint 23B's `staff-assignment-requests/<id>/approve/` is
  unchanged. The two paths converge on the same
  `TicketStaffAssignment` row.
- Frontend: new "Assign field staff" block inside the existing
  assigned-staff card on `TicketDetailPage`, visible only to
  SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER. Per-row remove
  with a `ConfirmDialog`. EN + NL i18n keys.

## What is deferred (P1 / P2)

- **P2** — Bulk assignment / re-assignment UI (add multiple staff
  in one go). Sprint 25A ships a single-row add per click; pilot
  load does not justify bulk yet.
- **P2** — Searchable assignable-staff dropdown. Single building
  rarely has > ~20 eligible staff in the pilot data set, so a
  flat `<select>` is enough.
- **P2** — Staff-side "your direct assignments" indicator on
  TicketDetailPage. Today STAFF still see assignments via the
  ticket-detail `assigned_staff` payload; the explicit "you were
  added directly (no request from you)" badge can wait until pilot
  feedback says it's needed.
- **P2** — Auto-cancel any open Sprint 23B `StaffAssignmentRequest`
  from the same STAFF user when an admin directly assigns them to
  the same ticket. Today both paths can coexist (the staff's open
  request just stays PENDING and the admin can still
  approve/reject it independently). Pilot feedback will tell us
  whether this leads to confusion worth automating away.

## What was NOT touched

- Sprint 23A CUSTOMER_USER tightening.
- Sprint 24A StaffProfile / BuildingStaffVisibility editor.
- Sprint 24B reviewer-note modal.
- Sprint 24C STAFF self-cancel.
- Sprint 24D atomic state transitions + filtered pending discovery.
- Sprint 24E verification ladder.
- Status workflow (`apply_transition`, `ALLOWED_TRANSITIONS`).
- Customer ticket creation gate, message gate, attachment gate.

No migrations were required.
