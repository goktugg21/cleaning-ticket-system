# Done

Append-only ledger of closed backlog / bug items. Newest at the top.

Format per row:

```
- [<id>] <title>
  Closed-by: <commit-sha>
  Closed-on: <YYYY-MM-DD>
  Notes: <one line — what shipped, what's deferred>
```

---

## 2026-05-16 — Sprint 27F delivered (working tree, awaiting commit)

- [27F-B1] Ticket workflow override columns + state-machine API.
  Closed-by: (uncommitted — git diff on working tree)
  Closed-on: 2026-05-15
  Notes: `TicketStatusHistory.is_override` + `override_reason` columns
  (migration `tickets/0007`). `apply_transition` accepts the two kwargs,
  coerces `is_override=True` for SUPER_ADMIN / COMPANY_ADMIN driving
  WAITING_CUSTOMER_APPROVAL → APPROVED/REJECTED (mirrors Extra Work
  `state_machine.py:250-265`), rejects with stable code
  `override_reason_required` (HTTP 400) when reason is missing. Both
  serializers extended. Tests at
  `backend/tickets/tests/test_sprint27f_workflow_override.py` (5 tests
  in 2 classes — all green). `seed_demo_data` + 2 cases in
  `test_state_machine.py` updated to pass an override_reason on the now-
  always-an-override transitions. Closes G-B3.

- [27F-B2] AuditLog `reason` + `actor_scope` columns + context plumbing.
  Closed-by: (uncommitted)
  Closed-on: 2026-05-15
  Notes: `AuditLog.reason: TextField` + `AuditLog.actor_scope: JSONField`
  shipped (migration `audit/0002`). `audit/context.py` gained
  `set_current_reason / get_current_reason / set_current_actor_scope /
  get_current_actor_scope / snapshot_actor_scope`. Middleware seeds
  actor_scope per-request; signal handler resolves lazily off
  `request.user` when the JWT-auth-after-middleware case yields an
  AnonymousUser snapshot. Both AuditLog.objects.create call sites in
  the repo (`audit/signals.py` + `tickets/views.py` soft-delete) carry
  the two new kwargs explicitly. `AuditLogSerializer` extended. 5 new
  tests at `backend/audit/tests/test_sprint27f_audit_columns.py` — all
  green. Full RBAC-app sweep 548 tests, OK. Closes G-B6.

- [27F-F1] Ticket override modal + timeline override badge.
  Closed-by: (uncommitted)
  Closed-on: 2026-05-15
  Notes: `TicketDetailPage.tsx` two-press override modal (mirrors
  Extra Work `ExtraWorkDetailPage.tsx:250-273` shape). Sends
  `is_override:true` + `override_reason` to the backend; on 400 with
  `code === "override_reason_required"` shows the inline i18n error.
  Timeline rendering shows override badge + reason for every
  `is_override=true` history row. Types: `TicketStatusHistory` extended
  with required `is_override` + `override_reason`; new
  `TicketStatusChangePayload` interface for the request body. 9 new i18n
  keys in both `frontend/src/i18n/{en,nl}/ticket_detail.json`. Spec at
  `frontend/tests/e2e/sprint27f_ticket_override.spec.ts` (3 cases:
  happy path, empty-reason blocks submission, CUSTOMER_USER sees no
  override modal). Playwright run blocked by root-owned
  `frontend/test-results/` artifacts (known `CLAUDE_CODE_OPERATIONAL_NOTES.md`
  gotcha); spec written but not locally validated. `npm run typecheck`
  clean; `npm run lint` at baseline (no new errors). Closes G-F3.

---

## 2026-05-15 — Backlog reconciliation against current master

The PM agent re-verified every "verified-still-missing" item from
GAP_ANALYSIS_2026-05 (dated 2026-05) against current source on `master`
after Sprint 27A-E shipped. The items below were already closed by
commits that landed BEFORE the backlog file was created on 2026-05-15
but were carried in BUGS.md / PRODUCT_BACKLOG.md as historical
references. They are recorded here for the audit trail.

- [BUG-B1] `Ticket.resolved_at` declared but never written.
  Closed-by: 5d669de (CHANGE-4: Stamp Ticket.resolved_at on entry to APPROVED)
  Closed-on: pre-2026-05-15
  Notes: `backend/tickets/state_machine.py:108` defines `RESOLVED_AT_ON_STATUS`
  = `{TicketStatus.APPROVED}`; `apply_transition` stamps `resolved_at = now`
  inside the existing atomic block (lines 204-206). Re-approvals overwrite,
  per the doc comment.

- [BUG-B2] `description` in ticket search whitelist leaks to customer users.
  Closed-by: 2e3954e (CHANGE-5: Restrict description search to staff users)
  Closed-on: pre-2026-05-15
  Notes: `backend/tickets/views.py:80-88` now exposes `search_fields` as a
  property that drops `description` when `is_staff_role(self.request.user)`
  is False.

- [BUG-B3] `scope_companies_for` / `scope_buildings_for` / `scope_customers_for`
  don't filter `is_active=True` for non-super-admin users.
  Closed-by: 46feb20 (CHANGE-6: Filter inactive entities in scoping helpers)
  Closed-on: pre-2026-05-15
  Notes: `backend/accounts/scoping.py:127-152` adds `is_active=True` to all
  three helpers for non-SUPER_ADMIN paths.

- [BUG-B4] `TicketCreateSerializer` doesn't reject inactive building/customer.
  Closed-by: 46feb20 (CHANGE-6: Filter inactive entities in scoping helpers)
  Closed-on: pre-2026-05-15
  Notes: `backend/tickets/serializers.py:311-318` rejects with field-keyed
  ValidationError when building.is_active or customer.is_active is False.

- [BUG-B5] Email send is synchronous; no Celery worker in compose.
  Closed-by: 7e2ad3b (CHANGE-13: Async email via Celery worker) +
  940cc9f (CHANGE-14: Run Celery worker as non-root)
  Closed-on: pre-2026-05-15
  Notes: `docker-compose.yml` now declares `worker` and `beat` services
  (`celery -A config worker -l info`).

- [BUG-B6] Notification copy doesn't distinguish customer self-action from
  admin override.
  Closed-by: 9147e11 (CHANGE-2: Override-aware notification copy on
  customer-decision push)
  Closed-on: pre-2026-05-15
  Notes: `backend/notifications/services.py:314-323` accepts
  `is_admin_override` param; `backend/tickets/views.py:214-225` computes it
  from actor role + old/new status pair before dispatch.

- [BUG-B7] No `/api/tickets/stats/` aggregate endpoint; dashboard KPIs
  computed from one page.
  Closed-by: 2b49349 (CHANGE-3: /api/tickets/stats/ endpoint and real
  dashboard KPIs) + 2e64135 (CHANGE-9: /stats/by-building/)
  Closed-on: pre-2026-05-15
  Notes: `backend/tickets/views.py:268,293` define `stats` and
  `stats_by_building` actions; frontend wires both in DashboardPage.tsx.

- [BUG-B8] `reports` Django app is empty.
  Closed-by: 063d03b (Reports v1 B1: backend endpoints) + 8524127
  (Reports v1 B2: frontend page with four charts)
  Closed-on: pre-2026-05-15
  Notes: `backend/reports/views.py` now ships ten view classes
  (status distribution, tickets-over-time, manager throughput, SLA
  distribution + breach rate, age buckets, by-type/by-customer/by-building
  with CSV + PDF export); `backend/reports/urls.py` registered in
  `backend/config/urls.py`.

- [BUG-F1] No `/password/reset/confirm` route in React app.
  Closed-by: 4dec9c2 (CHANGE-1: Add /password/reset/confirm React page)
  Closed-on: pre-2026-05-15
  Notes: `frontend/src/App.tsx:67-68` registers the public route binding
  to `ResetPasswordConfirmPage` (imported at line 18).

- [BUG-F2] Dashboard health score computed from visible page only.
  Closed-by: 2b49349 (CHANGE-3 — same as BUG-B7; the dashboard now reads
  real aggregates from /api/tickets/stats/)
  Closed-on: pre-2026-05-15
  Notes: `frontend/src/pages/DashboardPage.tsx:101,195` reads `TicketStats`
  from the new endpoint; the derived health-score card was removed.

- [BUG-F5] SLA card on ticket detail is fabricated UI-side.
  Closed-by: cfb8902 (SLA v1 B2: ticket UI surface + filter)
  Closed-on: pre-2026-05-15
  Notes: card is now backed by real `sla_display_state`,
  `sla_remaining_business_seconds`, `sla_paused_at` fields on
  `TicketDetailSerializer` (`backend/tickets/serializers.py:188-201`);
  rendered via `SLABadge` at `TicketDetailPage.tsx:1651`.

- [BUG-O1] No backend healthcheck in `docker-compose.yml`.
  Closed-by: 593b6e7 (Sprint 1.1: backend /health endpoints + structured
  LOGGING)
  Closed-on: pre-2026-05-15
  Notes: `docker-compose.yml:41-48` defines a 30s healthcheck against
  `http://localhost:8000/health/live`.

- [BACKEND-CRUD-1] Admin CRUD on Company, Building, Customer, User,
  Memberships.
  Closed-by: 437b23c (CHANGE-16: Backend admin CRUD) +
  35febbb (CHANGE-17A: Frontend admin UI for tenant entities) +
  62ad1c6 (CHANGE-17B: Frontend admin UI for users, invitations,
  memberships)
  Closed-on: pre-2026-05-15
  Notes: `CompanyViewSet`, `BuildingViewSet`, `CustomerViewSet`,
  `UserViewSet` are all `ModelViewSet`s with POST/PATCH/DELETE; Sprint
  27D wired the `osius.*.manage` gates.

- [BACKEND-INVITE-1] Invitation flow.
  Closed-by: 9293d4f (CHANGE-15: Invitation flow)
  Closed-on: pre-2026-05-15
  Notes: `backend/accounts/views_invitations.py` + `serializers_invitations.py`
  + `filters_invitations.py` + `invitations.py` (token + email). Frontend
  `/invite/accept` route at `App.tsx:70` → `AcceptInvitationPage`.

- [BACKEND-AUTH-1] /api/auth/me/ PATCH + /api/auth/password/change/.
  Closed-by: 08361c3 (Settings/Profile B1: self-edit name, language,
  password) + 98ad69f (Settings/Profile B2: notification preferences)
  Closed-on: pre-2026-05-15
  Notes: `backend/accounts/urls.py:27-28` register `password/change/` and
  `me/`; `MeView.patch` validates through `MeUpdateSerializer` (full_name +
  language only).

- [BACKEND-CELERY-1] Move email send to Celery worker.
  Closed-by: 7e2ad3b (CHANGE-13) + 940cc9f (CHANGE-14)
  Closed-on: pre-2026-05-15
  Notes: same as BUG-B5.

- [BACKEND-REPORTS-1] Reports v1.
  Closed-by: 063d03b + 8524127 (Reports v1 B1/B2)
  Closed-on: pre-2026-05-15
  Notes: same as BUG-B8.

- [BACKEND-NOTIFY-1] Notify previous assignee on reassign.
  Closed-by: 3a14d30 (CHANGE-8: Notify previous assignee on reassign or
  unassign)
  Closed-on: pre-2026-05-15
  Notes: `backend/notifications/services.py:420` exposes
  `send_ticket_unassigned_email`; `backend/tickets/views.py` (assign
  action) sends to both the new and previous assignee on PATCH.

- [BACKEND-HEALTHCHECK-1] Backend service healthcheck in dev compose.
  Closed-by: 593b6e7 (Sprint 1.1)
  Closed-on: pre-2026-05-15
  Notes: same as BUG-O1.

- [FRONTEND-SIDEBAR-1] Sidebar items "Facilities", "Assets", "Reports",
  "Settings" implying features that don't exist.
  Closed-by: b48f5c4 (CHANGE-7: Hide disabled sidebar items). Reports
  re-introduced for real by the Reports v1 B2 commit; Settings re-introduced
  for real by Settings/Profile B1.
  Closed-on: pre-2026-05-15
  Notes: `frontend/src/layout/AppShell.tsx` has no "Facilities" or "Assets"
  references; Reports and Settings are real `NavLink`s to real pages.

- [FRONTEND-SLA-1] SLA card on ticket detail is fabricated.
  Closed-by: cfb8902 (SLA v1 B2)
  Closed-on: pre-2026-05-15
  Notes: same as BUG-F5.

---

## 2026-05-15 — Project ops setup

- [OPS-AGENT-SETUP] Create CLAUDE.md, three-agent setup
  (project-manager, backend-engineer, frontend-engineer), and the live
  backlog under `docs/backlog/`.
  Closed-by: (this commit)
  Closed-on: 2026-05-15
  Notes: PM is the only writer of `docs/backlog/*.md`. Engineer briefs
  must cite file:line + acceptance + tests. Parallel-dispatch contract
  documented in CLAUDE.md §4.

---

## Earlier closes (pre-backlog era)

Recent sprint deliveries are recorded in `git log` and in the matrix
doc's "CLOSED by Sprint <N><letter>" annotations. The backlog ledger
starts here.

Reference for archaeology:
- Sprint 27A — RBAC safety net (test-first), commit `408d8ad`
- Sprint 27B — effective-permissions composer, commit `c91e7eb`
- Sprint 27C — customer permission write endpoint + policy model, commit `c0db299`
- Sprint 27D — provider key wiring + policy runtime, commit `9a593ed`
- Sprint 27E — customer permission management UI, commit `b08fa10`
