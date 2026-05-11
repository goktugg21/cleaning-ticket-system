# Sprint 23B — Admin staff-assignment UI

Companion to `sprint-23a-domain-permissions-foundation.md`. Where 23A
laid the model + permission + ticket-payload foundation, 23B wires the
already-merged backend through the React admin surface so the pieces
become operator-usable. Backend changes are deliberately narrow:
serializer field surface only — no new endpoints, no new model fields,
no policy changes.

## Scope

In:

- STAFF persona on the ticket detail page: read-only `assigned_staff`
  panel plus a one-click **Request assignment** button that POSTs to
  `/api/staff-assignment-requests/`.
- Admin nav entry + dedicated route guard
  (`StaffRequestReviewRoute`) for `/admin/staff-assignment-requests`,
  with a one-screen review queue (table + filter +
  approve/reject buttons). The guard admits `SUPER_ADMIN`,
  `COMPANY_ADMIN`, **and `BUILDING_MANAGER`** (building managers do
  not see the rest of the admin nav, but need this single queue).
- Customer admin form: three checkboxes for
  `show_assigned_staff_{name,email,phone}`, plus a read-only access-
  role badge column on the per-customer-user access list (Sprint 23A
  fields surfaced in the UI for the first time).
- Demo seed: one STAFF persona per company, idempotent, with phone +
  per-building `BuildingStaffVisibility`. Used by Playwright fixtures
  (`staffOsius`, `staffBright`) and the manual demo walkthrough.
- Two-locale i18n parity (EN + NL) for every new copy string.

Deferred to Sprint 23C:

- Editor for `access_role` — today reviewers can only see the role and
  must revoke + re-grant to change it.
- Editor for `permission_overrides` (the JSON map; UI is non-trivial).
- BuildingStaffVisibility CRUD UI — visibility today is set via the
  Django admin / seed only.
- StaffProfile CRUD UI (read-only listing is the bar 23B clears).
- Reviewer-note input modal on approve/reject — backend already
  accepts the field; frontend sends `""` today.
- Filter the queue by building / staff / date range.

## Architectural decisions

1. **`StaffRequestReviewRoute` is a separate guard, not a tweak to
   `AdminRoute`.** The latter excludes BUILDING_MANAGER on purpose
   (managers do not get the companies/buildings/users admin pages);
   the staff-request queue is the one admin page they do reach.
   Mirroring this on the sidebar required a parallel role set
   (`STAFF_REQUEST_REVIEW_ROLES`) in `AppShell.tsx`.

2. **STAFF role is added to the frontend `Role` union but kept OUT of
   the `ALL_ROLES` create-form picker.** A STAFF user is a richer
   object than a plain `User` row — it must have a matching
   `StaffProfile` and per-building `BuildingStaffVisibility` rows.
   Promoting a generic user into STAFF via the user form would skip
   that setup. The admin user list filter does include STAFF so
   reviewers can find existing STAFF accounts. Creation/management of
   STAFF accounts is Sprint 23C scope.

3. **`assigned_staff` rendering policy is enforced server-side, not
   client-side.** The ticket-detail payload omits or anonymises staff
   entries for CUSTOMER_USER viewers per Sprint 23A; the frontend
   simply trusts the payload and renders an anonymous fallback label
   (`label_key`) when `anonymous: true` is set. This means a future
   `Customer.show_assigned_staff_*` policy change takes effect on the
   next API call without any frontend redeploy.

4. **Customer contact-visibility flags surface as writable on the
   admin Customer serializer** so OSIUS Admin + owning Company Admin
   can flip them through the existing PATCH path. The viewset
   permission gate (`IsSuperAdminOrCompanyAdmin`) is unchanged;
   building managers and customer users still cannot edit the
   customer record.

5. **Duplicate-request UX on the STAFF-side button** maps the backend
   400 "A pending request already exists" string to a friendly
   "request already pending" message. Backend message string is the
   contract; future refactors of the message will break the friendly
   path, so the regex match (`/pending request/i`) is intentionally
   forgiving.

## Files touched

Backend (additive only):

- `backend/customers/serializers.py` — added three visibility fields
  to `CustomerSerializer.Meta.fields`.
- `backend/customers/serializers_memberships.py` — surface Sprint 23A
  `access_role` / `is_active` / `permission_overrides` read-only on
  `CustomerUserBuildingAccessSerializer`.
- `backend/accounts/management/commands/seed_demo_data.py` — one
  STAFF persona per company plus phone + per-building visibility.
- `backend/accounts/management/commands/check_no_demo_accounts.py` —
  added the two new demo emails to the pilot-readiness guard list.
- `backend/customers/tests/test_sprint23b_serializers.py` (new) — 7
  serializer-surface tests pinning both behaviours.

Frontend:

- `frontend/src/api/types.ts` — STAFF in `Role`, new
  `AssignedStaffEntry` / `StaffAssignmentRequest` /
  `StaffAssignmentRequestStatus` / `CustomerAccessRole`, extended
  `TicketDetail.assigned_staff` and `CustomerAdmin` /
  `CustomerUserBuildingAccess`.
- `frontend/src/api/admin.ts` — three `show_assigned_staff_*` on
  `CustomerWritePayload`, plus four new client functions:
  `listStaffAssignmentRequests`, `createStaffAssignmentRequest`,
  `approveStaffAssignmentRequest`, `rejectStaffAssignmentRequest`.
- `frontend/src/components/StaffRequestReviewRoute.tsx` (new) —
  parallel guard to `AdminRoute` admitting BUILDING_MANAGER too.
- `frontend/src/pages/admin/StaffAssignmentRequestsAdminPage.tsx`
  (new) — single-screen review queue, ~280 lines.
- `frontend/src/pages/TicketDetailPage.tsx` — read-only
  `assigned_staff` card + STAFF-only "Request assignment" button.
- `frontend/src/pages/admin/CustomerFormPage.tsx` — three checkboxes
  bound to the new fields + access-role badge in the per-user access
  pill list.
- `frontend/src/layout/AppShell.tsx` — new sidebar entry guarded by
  `STAFF_REQUEST_REVIEW_ROLES`.
- `frontend/src/App.tsx` — new `/admin/staff-assignment-requests`
  route under `StaffRequestReviewRoute`.
- `frontend/src/pages/{AcceptInvitationPage,admin/InvitationsAdmin,
  admin/UserForm,admin/UsersAdmin}.tsx` — STAFF entry in their
  `Record<Role, string>` role-label maps (display only); STAFF kept
  out of `ALL_ROLES` create lists in the user form (see decision 2).
- `frontend/src/i18n/{en,nl}/common.json` — full key set for the new
  surfaces in two locales.
- `frontend/tests/e2e/fixtures/demoUsers.ts` — STAFF in the role
  union plus `staffOsius` / `staffBright` personas.
- `frontend/tests/e2e/sprint23b_staff_assignment.spec.ts` (new) — 13
  end-to-end checks.

## Permission / scoping rules (recap)

| Surface                                            | SUPER_ADMIN | COMPANY_ADMIN | BUILDING_MANAGER | STAFF       | CUSTOMER_USER |
|----------------------------------------------------|-------------|---------------|------------------|-------------|---------------|
| Sidebar link `/admin/staff-assignment-requests`    | ✓           | ✓             | ✓                | hidden      | hidden        |
| Page `/admin/staff-assignment-requests`            | full        | own company   | own buildings    | redirect    | redirect      |
| `POST /api/staff-assignment-requests/`             | (n/a)       | (n/a)         | (n/a)            | own ticket  | 403           |
| `assigned_staff` panel on `/tickets/:id`           | full        | full          | full             | full        | policy-gated  |
| Ticket-detail "Request assignment" button         | hidden      | hidden        | hidden           | in-scope    | hidden        |
| Customer contact-visibility checkboxes (write)     | ✓           | own company   | 403              | 403         | 403           |
| Customer access-role badge (read-only)             | ✓           | own company   | n/a (no page)    | n/a         | n/a           |

Backend gate is authoritative on every row above — the frontend
mirrors the gate for UX, but a hand-crafted request hits the same
denial path.

## Customer isolation

- The `/api/staff-assignment-requests/` viewset returns `none()` for
  CUSTOMER_USER. The frontend hides the link **and** redirects the
  route — defence in depth: a tampered cached JS bundle still loses
  at the backend.
- `assigned_staff` is computed inside the ticket serializer using the
  viewer's role + the owning `Customer.show_assigned_staff_*`
  flags. The frontend never receives the unfiltered data; toggling
  the customer flags takes effect on the next API read with no
  frontend redeploy.
- Cross-company isolation for STAFF is verified by an API-level
  Playwright test (`Bright STAFF cannot create a request on an Osius
  ticket`).

## Verification

- Backend `python manage.py check`: passes.
- Backend `makemigrations --check --dry-run`: no missing migrations.
- Backend full test suite: **577 passed, 0 failed** (run #1, fresh
  test DB).
- Backend customers + Sprint 23A + tickets re-run after Sprint 23B
  serializer edits: **158 passed**.
- Backend new Sprint 23B serializer tests: **7 passed**.
- Frontend `tsc --noEmit` clean.
- Frontend build (`tsc -b && vite build`): green after `STAFF` added
  to the four `Record<Role, string>` role-label maps.
- Frontend Sprint 23B Playwright spec (13 tests):
  **13 passed in 21.5s**.
- Frontend full Playwright suite (208 tests): **205 passed, 3
  failed.** All 3 failures live in `scope.spec.ts` /
  `workflow.spec.ts` and trace to a single pre-existing rogue
  `Customer` row (`Ramazan Holding`) in the local demo DB that
  pre-dates Sprint 23B and grants Amanda an unintended B1 access
  membership. The auto-mode guard refused an in-place delete of that
  row (correctly — it is shared data the user did not explicitly
  authorise removing). The failures reproduce with the same root
  cause on master; Sprint 23B does not regress them. Cleaning up the
  rogue customer or rebuilding the demo DB volume restores those
  three tests to green.

## Next sprint recommendation (23C)

1. `access_role` editor + `permission_overrides` JSON editor with a
   one-row-per-key checkbox UI (the keys are enumerated in
   `customers/permissions.py::_TICKET_ROLE_DEFAULTS`).
2. BuildingStaffVisibility CRUD (the "which staff sees which
   buildings" matrix) — backend already exists, no UI yet.
3. StaffProfile create form to graduate STAFF into the user form
   without seed-only setup. Pairs with point 2 so a freshly-created
   STAFF user can immediately be made visible on at least one
   building.
4. Investigate + remove the rogue demo `Customer` ("Ramazan Holding")
   that pollutes Amanda's access. Most likely a stray from an earlier
   sprint's manual API testing; cleanest fix is to delete the row
   (cascade clears the access membership) and document the demo-data
   reset playbook.
