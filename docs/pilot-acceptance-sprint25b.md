# Sprint 25B — pilot acceptance smoke

Sprint 25B ran a real end-to-end acceptance smoke of the
operational ticket workflow using the actual API + Playwright UI.
Every journey listed in the brief passed. **No bugs were found.**
This report is the only artifact this PR ships.

Sprint 25A's domain fix (admin/manager direct staff assignment via
`/api/tickets/<id>/staff-assignments/`) is exercised end-to-end here
and behaves correctly. Sprint 23A scoping, Sprint 23B/24B/24C
staff-request flow, Sprint 24D atomic transitions, and Sprint 24E
verification ladder are all intact under live traffic.

## Journeys smoked

### A. Demo seed + login sanity ✅
- `seed_demo_data --reset-tickets` runs clean.
- Five canonical personas authenticate against `/api/auth/token/`:

```
200  superadmin@cleanops.demo                       (SUPER_ADMIN)
200  ramazan-admin-osius@b-amsterdam.demo           (COMPANY_ADMIN)
200  gokhan-manager-osius@b-amsterdam.demo          (BUILDING_MANAGER)
200  ahmet-staff-osius@b-amsterdam.demo             (STAFF)
200  tom-customer-b-amsterdam@b-amsterdam.demo      (CUSTOMER_USER)
```

### B. CUSTOMER_USER happy path ✅
- Tom (plain `view_own`) sees exactly 2 tickets — the two he
  created. He does not see Iris/Amanda's tickets, even at the
  same customer.
- Tom direct-`GET`s a Bright ticket → **404** (queryset hide).
- Tom tries to create a ticket on a Bright building + customer
  → **400** ("Customer is not linked to the selected building").
- Tom creates a valid ticket on his own (customer, building)
  pair → **201**.
- Tom posts `PUBLIC_REPLY` message → **201**.
- Tom tries `INTERNAL_NOTE` → **400** ("Customer users cannot
  post internal notes").
- Admin posts an `INTERNAL_NOTE` on Tom's ticket → **201**;
  Tom's `GET /messages/` returns only the `PUBLIC_REPLY` row.
- Tom direct-downloads a Bright attachment via guessed
  `/api/tickets/64/attachments/1/download/` → **404**. Super-admin
  and Bright STAFF both succeed (200).

### C. COMPANY_ADMIN / BUILDING_MANAGER operational path ✅
- COMPANY_ADMIN sees the 5 Osius tickets, zero Bright tickets
  (cross-company hidden by queryset).
- `GET /tickets/<id>/assignable-staff/` returns exactly 1 STAFF
  row (Ahmet) — Noah (Bright) is excluded.
- Admin direct-`POST`s `{user_id: <ahmet>}` to
  `/staff-assignments/` → **201** with no staff-side
  `StaffAssignmentRequest` ever created.
- Admin tries to add Noah (Bright STAFF) to an Osius ticket
  → **400** ("Target staff has no visibility on this building").
- Admin `DELETE`s the assignment → **204**.

### D. STAFF operational path ✅
- Ahmet sees 5 Osius tickets, zero Bright.
- Ahmet tries to use the admin direct-assign endpoint
  (`/staff-assignments/`) → **403** ("Staff cannot assign other
  staff to tickets").
- Sprint 23B self-request flow remains intact: Ahmet `POST`s to
  `/staff-assignment-requests/` → **201 PENDING**.
- Sprint 24C self-cancel intact: Ahmet `POST /cancel/` → **200**;
  status flips to CANCELLED.
- After cancel, Sprint 25A admin direct-assign still works on the
  same ticket — `0` PENDING requests outstanding, admin → **201**,
  cleanup → **204**.

### E. Status / approval path ✅
- `allowed_next_statuses` is correctly role-scoped on the same
  `WAITING_CUSTOMER_APPROVAL` ticket:
  - SUPER_ADMIN → `[OPEN, IN_PROGRESS, REJECTED, APPROVED, CLOSED, REOPENED_BY_ADMIN]`
  - COMPANY_ADMIN → `[APPROVED, REJECTED]` (admin override path)
  - BUILDING_MANAGER → `[]` (no buttons → no misclick)
  - CUSTOMER_USER creator (Amanda) → `[APPROVED, REJECTED]`
- Tom (not creator, plain `view_own`) tries to approve Amanda's
  WCA ticket → **404** (scope hides it).
- Manager tries `APPROVED` directly → **400** (state machine
  rejects).
- STAFF (Ahmet) tries `OPEN → IN_PROGRESS` → **400** with
  `code=forbidden_transition`. Sprint 23A intentional design.
- Amanda (creator) sends `APPROVED` → **200**, ticket status
  flips to APPROVED + `approved_at` stamped.

### F. Attachments ✅

Upload via SUPER_ADMIN on an active Osius ticket, mime + extension
both honoured:

| Type | Status |
|---|---|
| `application/pdf` (`.pdf`) | **201** |
| `image/png` (`.png`) | **201** |
| `image/jpeg` (`.jpg`) | **201** |
| `image/webp` (`.webp`) | **201** |
| `image/heic` (`.heic`) | **201** |
| `image/heif` (`.heif`) | **201** |
| `application/x-msdownload` (`.exe`) | **400** |
| `text/plain` (`.txt`) | **400** |
| `application/zip` (`.zip`) | **400** |
| `image/svg+xml` (`.svg`) | **400** |
| `image/gif` (`.gif`) | **400** |

All rejections carry the same human-readable error
(`"Only JPG, JPEG, PNG, WEBP, PDF, HEIC, and HEIF attachments are
allowed."`). Cross-tenant direct-download URL scoping was already
proved in journey B above.

### G. UI readiness ✅
- Frontend image built from `frontend/Dockerfile` (Vite + tsc)
  → success.
- Focused Playwright across the entire smoked surface:

```
login.spec.ts                                  3 tests
routes.spec.ts                                 6 tests
scope.spec.ts                                 11 tests
workflow.spec.ts                               5 tests
admin_crud.spec.ts                            ~95 tests (incl. mobile loops)
sprint25a_direct_staff_assignment.spec.ts      7 tests
                                              ───────
                                              132 passed
                                                2 skipped
                                                0 failed
                                              ~10.3 min total
```

- No raw `staff_admin.*`, `assigned_staff_*`, or
  `request_assignment_*` i18n keys leak (pinned by Sprint 24A /
  24C / 25A specs that were re-run as part of this smoke).
- Mobile invariants from Sprints 23C / 24A / 24C / 25A remain
  green at 390 / 430 / 480 px on the touched pages.

## Bugs found and fixed

**None.** Every journey listed in the brief passed on the first
pass. No backend or frontend changes were required.

## Deferred (P1 / P2) — same as Sprint 25A

- **P2** — Bulk assignment / re-assignment UI.
- **P2** — Searchable assignable-staff dropdown.
- **P2** — Staff-side "you were directly added (no request)" badge.
- **P2** — Auto-cancel of stale Sprint 23B requests when admin
  direct-assigns the same staff to the same ticket.

No item from this list was promoted to P1 by the acceptance smoke.

## Exact test commands

```bash
# Tier 1 — Sprint 24E fast checks (Django check + migrations + tsc)
scripts/verify_fast.sh

# A: demo seed + login sanity (each persona POST /api/auth/token/)
docker compose exec -T backend python manage.py seed_demo_data --reset-tickets

# B-F: ad-hoc curl + urllib walk — see this report's per-journey
# blocks. The exact verification matrix is reproduced in the
# matching focused tests:
#   backend/tickets/tests/test_sprint25a_direct_staff_assignment.py
#   backend/tickets/tests/test_sprint24b_review_note.py
#   backend/tickets/tests/test_sprint24c_staff_cancel.py
#   backend/tickets/tests/test_sprint24d_atomic_transitions.py
#   accounts/tests/test_sprint23a_foundation.py
#   accounts/tests/test_sprint24a_staff_management.py

# G: focused Playwright across the smoked UI surface
docker build -t cleaning-ticket-system-frontend:sprint25b frontend/
docker run -d --name cleaning_ticket_sprint25b_frontend \
  --network cleaning-ticket-system_default -p 5173:80 \
  cleaning-ticket-system-frontend:sprint25b
PLAYWRIGHT_BASE_URL=http://localhost:5173 \
  npx playwright test \
    login.spec.ts routes.spec.ts scope.spec.ts workflow.spec.ts \
    admin_crud.spec.ts sprint25a_direct_staff_assignment.spec.ts
```

Full Playwright deliberately **not** run — Sprint 24E's verification
ladder reserves the full suite for the manual / nightly
`playwright.yml` workflow. No journey in this smoke touched a UI
page outside what the focused set above already covers.

## Summary

Pilot operational workflow is green end-to-end against live API +
Playwright. Sprint 25B ships **only this audit report** — no code,
no migrations, no test changes.
