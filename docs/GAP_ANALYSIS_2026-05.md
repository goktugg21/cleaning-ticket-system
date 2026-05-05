# Cleaning Ticket System - Gap Analysis 2026-05

Status as of branch `frontend-claude-design-port` at HEAD `b48c826` ("Port redesigned frontend and refine ticket workflow").

This document supersedes the P0 status portions of `AUDIT_REPORT.md` and `P0_FIX_PLAN.md`. Earlier docs were written at an earlier commit; many P0 items are now closed in code.

All file:line references below were verified by reading the current source.

---

## 1. Verified-already-done

The following items are listed as P0 in `AUDIT_REPORT.md` / `P0_FIX_PLAN.md` but have been implemented and are covered by tests in `backend/*/tests/`.

- Backend test harness with hermetic `APITestCase` coverage exists. 55 test functions across `accounts`, `tickets`, `notifications`, `config` test packages. (`backend/accounts/tests/`, `backend/tickets/tests/`, `backend/notifications/tests/`, `backend/config/tests/`)
- JWT refresh-token rotation and blacklist enabled. `rest_framework_simplejwt.token_blacklist` is in `INSTALLED_APPS`. (backend/config/settings.py:44, backend/config/settings.py:198-199)
- Server-side logout endpoint that blacklists the supplied refresh token. (backend/accounts/views.py:41-61, backend/accounts/urls.py:16)
- `LoginLog` is written on success and failure. Repeated-failure account lockout with a 5-attempt / 15-minute window. (backend/accounts/serializers.py:36-77, backend/accounts/serializers.py:17-18)
- Password reset request and confirm endpoints, with `password_validation.validate_password` enforced on confirm. (backend/accounts/urls.py:17-18, backend/accounts/views.py:64-95, backend/accounts/serializers.py:117-167)
- Password reset email writes a `NotificationLog` row. (backend/notifications/services.py:247-270, backend/notifications/services.py:104-140)
- Explicit `is_staff_role(request.user)` permission gates on `assign`, `change_status`, and `assignable-managers`. Returns 403 not 400 for customer users. (backend/tickets/views.py:73-80, backend/tickets/views.py:102-106, backend/tickets/views.py:133-137)
- Ticket creation wraps the row insert and the `ticket_no` derivation in `transaction.atomic()`. Concurrency test covers it. (backend/tickets/models.py:111-122, backend/tickets/tests/test_ticket_no.py:39-45)
- Production settings validator that fails fast on missing/weak `SECRET_KEY`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `POSTGRES_PASSWORD`, and overly permissive throttle rates. (backend/config/security.py, run from backend/config/settings.py:232-234, tests in backend/config/tests/test_settings_validator.py)
- Demo users gated behind `import.meta.env.DEV || VITE_SHOW_DEMO_USERS`. (frontend/src/pages/LoginPage.tsx:9-10)
- Attachment access control: list view filters hidden + internal-message attachments for non-staff; download view re-checks scope and hidden flags. (backend/tickets/views.py:230-235, backend/tickets/views.py:266-283)
- Attachment validation: 10 MB size limit, MIME and extension whitelist, randomized stored filename, original filename in `Content-Disposition`. (backend/tickets/serializers.py:291-321, backend/tickets/models.py:38-40, tests in backend/tickets/tests/test_attachments.py)
- State machine writes a `TicketStatusHistory` row inside the same atomic block as every transition. (backend/tickets/state_machine.py:99-140)
- Customer rejection note required by serializer. (backend/tickets/serializers.py:359-366)
- Customer rejection-reason guard mirrored in the frontend before the API call. (frontend/src/pages/TicketDetailPage.tsx:343-351)

The audit's P0 list is therefore largely closed at the code level. The remaining open items are listed below.

---

## 2. Verified-still-missing

These were found during this audit and are not addressed in code yet.

### 2a. Backend

- `Ticket.resolved_at` is declared but never written. (backend/tickets/models.py:102, backend/tickets/state_machine.py:58-63)
- `description` is in the ticket search whitelist, so a customer user can substring-search across descriptions of every ticket they have scope for. (backend/tickets/views.py:41)
- `scope_companies_for`, `scope_buildings_for`, and `scope_customers_for` do not filter `is_active=True` for non-super-admin users. Inactive entities still appear in `/api/companies/`, `/api/buildings/`, `/api/customers/`. (backend/accounts/scoping.py:73-94)
- `TicketCreateSerializer` does not reject creation against an inactive building or inactive customer. (backend/tickets/serializers.py:157-204)
- Email send is synchronous. No Celery worker exists in `docker-compose.yml` or `docker-compose.prod.yml` even though Celery and Redis are declared dependencies. Slow SMTP blocks ticket-creation requests up to `GUNICORN_TIMEOUT`. (backend/notifications/services.py:124-131, docker-compose.yml, docker-compose.prod.yml)
- No notification copy distinguishes "customer self-approved/rejected" from "admin-on-behalf-of-customer override". (backend/notifications/services.py:191-221)
- No `/api/tickets/stats/` aggregate endpoint, so the dashboard must compute KPIs from one page of results. (backend/tickets/views.py)
- `reports` Django app is empty: stub `views.py`, stub `models.py`, no `urls.py`, not registered in `config/urls.py`. (backend/reports/, backend/config/urls.py)
- COMPANY_ADMIN cannot override a customer decision (`WAITING_CUSTOMER_APPROVAL -> APPROVED|REJECTED`). State machine only allows `SUPER_ADMIN` and `CUSTOMER_USER`. May or may not be intended; see Section 3. (backend/tickets/state_machine.py:29-36)
- No CRUD on `Company`, `Building`, `Customer`, `User`, `BuildingManagerAssignment`, `CustomerUserMembership`, `CompanyUserMembership`. New tenants can only be created via Django admin or the shell. (backend/companies/views.py, backend/buildings/views.py, backend/customers/views.py)
- No invitation flow; no self-service password change for an authenticated user; no profile PATCH on `/api/auth/me/`.
- Previous assignee is not notified when they are unassigned (`assigned_to -> None`). (backend/notifications/services.py:224-244)

### 2b. Frontend

- No `/password/reset/confirm` route or page. The "Forgot password?" link works (it calls `/api/auth/password/reset/`) but the link inside the email lands on a 404 unless `PASSWORD_RESET_FRONTEND_URL` happens to point at a real page. (frontend/src/App.tsx:32-58)
- Sidebar items "Facilities", "Assets", "Reports", "Settings" are rendered as disabled spans. They imply features that do not exist on the backend. (frontend/src/layout/AppShell.tsx:97-128)
- Dashboard KPIs and the health score are computed from one page of `tickets` results. The number of "active" / "waiting approval" / "urgent" / "closed" rows shown to the user is misleading whenever total count exceeds the page size (25). (frontend/src/pages/DashboardPage.tsx:188-205)
- The "Remember my device for 30 days" checkbox is unbound on the wire; the comment in code notes it is visual-only. (frontend/src/pages/LoginPage.tsx:245-255)
- The customer-decision override two-press UX hard-codes `role === "SUPER_ADMIN"`. If COMPANY_ADMIN ever gets the same override permission on the backend, the frontend will silently fail to surface it. (frontend/src/pages/TicketDetailPage.tsx:38-46, frontend/src/pages/TicketDetailPage.tsx:59-69)
- SLA card on the ticket detail page (`deriveSlaSummary`) is fabricated UI-side. Marked with a TODO. (frontend/src/pages/TicketDetailPage.tsx:152-190)
- Health score "Stable / Watch / Stressed" uses a derived score from the visible page only; the audit (E3) flagged the previous random version, but the current deterministic version is still wrong-by-page-only.

### 2c. Operational

- Throttle defaults in code (`anon=60/min`, `user=5000/hour`, `auth_token=20/min`) match what the production validator requires; safe.
- No request-id / correlation-id middleware. Sentry is wired conditionally if `SENTRY_DSN` is set. (backend/config/settings.py:217-229)
- No backend healthcheck in `docker-compose.yml`. (`docker-compose.prod.yml` does have healthchecks for db and redis.)
- Nginx `client_max_body_size 12M` is barely above the 10 MB attachment limit. (frontend/nginx.conf:12)
- Whitenoise + Nginx-proxy of `/static/` is double-served; no functional bug, just wasted work.

---

## 3. Workflow decisions to be made

These need a product decision before code can move.

1. **COMPANY_ADMIN customer-decision override.** Should COMPANY_ADMIN (and not just SUPER_ADMIN) be able to push `WAITING_CUSTOMER_APPROVAL -> APPROVED` or `-> REJECTED` on behalf of an unresponsive customer?
   - Options: (a) leave as-is (only customer or super admin), (b) allow COMPANY_ADMIN with the two-press confirmation UX and override-aware notification copy.
   - **Recommended default:** (b), with the override copy tagging the actor and notifying the customer.

2. **`Ticket.resolved_at` semantics.** Stamp on entry to `APPROVED` (work done, awaiting close) or stamp on entry to `CLOSED`?
   - **Recommended default:** stamp on `APPROVED`. CHANGE-4 implements this. The most-recent-overwrite behaviour is documented; first/last/duration analytics use `TicketStatusHistory`.

3. **Sidebar items that imply features that do not exist.** Either:
   - implement the features (Facilities, Assets, Reports, Settings) - large project, see Section 8;
   - hide the disabled items entirely until features are built;
   - keep them as visible disabled placeholders to set expectations.
   - **Recommended default:** hide for now; reintroduce per item as the corresponding API ships.

4. **Dashboard health-score and SLA card.** Both are UI-derived and misleading on multi-page result sets. Either ship a real `/api/tickets/stats/` and a real `/api/tickets/{id}/sla/` endpoint, or remove the cards.
   - **Recommended default:** ship `/api/tickets/stats/` (CHANGE-3); replace the health-score card with real KPI counts; leave SLA card as-is (with the TODO) until the SLA engine exists.

5. **Email transport.** Keep synchronous `send_mail` (will block ticket creation if SMTP is slow) or add a Celery worker. If kept sync, drop Celery from `requirements.txt`.
   - **Recommended default:** add a Celery worker container in compose; keep Celery dep. Defer to a dedicated change after the smaller fixes ship.

6. **Inactive entities (`is_active=False`).** Decide whether `is_active=False` means "hidden everywhere" or "archived but visible".
   - **Recommended default:** hidden everywhere for non-super-admin reads; staff (super admin) can still see and re-activate. Existing tickets on an inactive building remain visible to staff. CHANGE-6 implements this.

7. **Customer description search.** Decide whether a customer can substring-search across other tickets' descriptions in their scope.
   - **Recommended default:** no, because descriptions can contain context that is intended to be private to that one ticket (room number, payment context, schedule notes). CHANGE-5 implements this.

---

## 4. Updated P0 / P1 / P2 plan

### P0 - safe, in-scope changes for this branch

These are implemented in Phase 10 of the working session that produced this document. None require a new migration, none change scoping or state-machine semantics.

- P0-A: `/password/reset/confirm` page in the React app + a public route in `App.tsx`. Document `PASSWORD_RESET_FRONTEND_URL` shape. (CHANGE-1)
- P0-B: Override-aware notification copy when staff transitions `WAITING_CUSTOMER_APPROVAL -> APPROVED|REJECTED`. (CHANGE-2)
- P0-C: `/api/tickets/stats/` endpoint + replace dashboard's client-derived stats with real numbers. (CHANGE-3)
- P0-D: Stamp `resolved_at` on entry to `APPROVED`. Document the loop semantics. (CHANGE-4)
- P0-E: Remove `description` from the search field whitelist for non-staff. (CHANGE-5)
- P0-F: Filter inactive entities in `scope_*_for`; reject ticket creation against inactive building/customer. (CHANGE-6)

### P0 - schema or cross-cutting decisions, blocked on user input

- COMPANY_ADMIN customer-decision override (state machine + frontend two-press + override notification copy + tests).
- Self-service admin CRUD for Company/Building/Customer/User/Memberships/Assignments + matching frontend pages under `/admin/...`.
- Invitation flow (`Invitation` model, signed-token email, accept page).
- Profile/settings page: PATCH `/api/auth/me/`, change-password endpoint, language toggle.

### P1 - product/operational maturity

- Reports v1: status distribution, age buckets, manager throughput. Sidebar "Reports" can be enabled when the API exists.
- Move email send to Celery worker; add `worker` service in both compose files; Celery eager-mode in tests.
- Per-account/per-IP brute-force protection above the existing 5/15-min lockout (e.g. `django-axes`).
- `/api/auth/me/` PATCH for full_name, language; `/api/auth/password/change/` for self-service password change (validators reused).
- Composite DB indexes on (`status`, `priority`), (`company`, `status`), (`building`, `status`).
- Healthcheck on backend service in `docker-compose.yml`.
- Request-id correlation header middleware.

### P2 - polish

- Hide or replace the SLA card on ticket detail until a real SLA engine exists.
- Replace `_send_to_users` with batched/threaded send if Celery is rejected.
- Bilingual UI (Dutch/English) since `LANGUAGE_CODE=nl` and `User.language` field exist.
- HTML email templates for the password reset email; better copy for status-change emails.
- Notify the previous assignee when a ticket is reassigned to someone else (today only the new assignee is told).

---

## 5. File-by-file change list per P0 item

### CHANGE-1 - `/password/reset/confirm` page
- Add `frontend/src/pages/ResetPasswordConfirmPage.tsx`.
- Modify `frontend/src/App.tsx` - add public route `/password/reset/confirm`.
- Modify `docs/ENV_SETUP.md` - document `PASSWORD_RESET_FRONTEND_URL` value.
- No backend changes. No migration.

### CHANGE-2 - Override-aware notification copy
- Modify `backend/notifications/services.py` - add `is_admin_override` parameter to `send_ticket_status_changed_email`. New subject and body when `True` and target status is `APPROVED` or `REJECTED`.
- Modify `backend/tickets/views.py` - compute `is_admin_override` in `change_status` and pass it through.
- Modify `backend/notifications/tests/test_email.py` - new test for override copy.
- No migration.

### CHANGE-3 - `/api/tickets/stats/`
- Modify `backend/tickets/views.py` - add `@action(detail=False, methods=["get"], url_path="stats")` on `TicketViewSet`. Single annotate per dimension. Uses `scope_tickets_for(request.user)`.
- Add `backend/tickets/tests/test_stats.py` - per-role assertions.
- Modify `frontend/src/pages/DashboardPage.tsx` - load `/api/tickets/stats/` once on mount; remove derived health-score card; surface real counts.
- Optionally add a stats type to `frontend/src/api/types.ts`.
- No migration.

### CHANGE-4 - `Ticket.resolved_at`
- Modify `backend/tickets/state_machine.py` - add `TicketStatus.APPROVED: "resolved_at"` to `TIMESTAMP_ON_ENTER`. Add a one-line comment that timestamps overwrite on loop.
- Modify `backend/tickets/tests/test_state_machine.py` - add assertions for `resolved_at` on first approval and re-approval.
- No migration. Field already exists.

### CHANGE-5 - Restrict description search to staff
- Modify `backend/tickets/views.py` - override `get_search_fields` on `TicketViewSet` to drop `description` for non-staff.
- Modify `backend/tickets/tests/test_scoping.py` - regression test that a customer's `?search=<word from another ticket's description>` does not leak.
- No migration.

### CHANGE-6 - Filter inactive entities in scoping
- Modify `backend/accounts/scoping.py` - `is_active=True` filter in `scope_companies_for`, `scope_buildings_for`, `scope_customers_for` for non-super-admin users only.
- Modify `backend/tickets/serializers.py` - `TicketCreateSerializer.validate` rejects inactive building or inactive customer with field errors.
- Modify or add `backend/tickets/tests/test_scoping.py` and `backend/tickets/tests/test_assignment.py` (or a new `test_inactive_filtering.py`) - regression tests.
- No migration. `is_active` columns already exist on Company, Building, Customer.

---

## 6. Risk register

| Change | Risk | Mitigation / rollback |
|---|---|---|
| CHANGE-1 | Frontend route only. Could collide with an unknown route - none exists. | Pure addition. Revert by deleting the file and the route entry. |
| CHANGE-2 | New email body shape may surprise downstream tooling that screen-scrapes the subject. | Subject still includes `[ticket_no]` and the status names; only the suffix changes. Revert is one parameter default. |
| CHANGE-3 | New endpoint. If the queryset is wrong, dashboard numbers are wrong but no scope is widened. | Backed by `scope_tickets_for`; returns aggregates not rows. Revert removes the action and restores the client-side stats block. |
| CHANGE-4 | `resolved_at` will start being non-null on existing approved tickets only after the next approval transition. Old rows stay null. | Document in the doc. Backfill is a separate decision. Revert removes the dict entry. |
| CHANGE-5 | A staff user who relied on customers searching by description for triage may notice a behaviour change for those customers. | Staff search is unchanged. Customers can still filter by ticket_no, title, room_label. |
| CHANGE-6 | Inactive buildings will disappear from `/api/buildings/` for non-super-admin. If any current user has only an inactive building/customer, they will see an empty list. Tickets remain visible (we do not change `scope_tickets_for`). Frontend `CreateTicketPage` will not be able to select an inactive building - which is the goal. | Revert removes the `is_active=True` filter from the helpers and the serializer guard. No data loss. |

None of these changes require a Django migration or touch the state machine `ALLOWED_TRANSITIONS` or the scoping rules for tickets.
