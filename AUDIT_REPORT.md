# Cleaning Ticket System — Technical Audit

Repository: `cleaning-ticket-system`
Audit date: 2026-05-04
Scope: Read-only audit of backend (Django/DRF), frontend (React/TS/Vite), Docker Compose, scripts, and docs.
No code was modified.

---

## A. Executive Summary

This is a focused, minimal multi-tenant cleaning/facility ticket system. Backend uses Django 5.2 + DRF + SimpleJWT + PostgreSQL + Redis (declared but unused). Frontend is React 19 + TypeScript + Vite, served by Nginx in production. Production deployment via `docker-compose.prod.yml` with Gunicorn, Whitenoise, and an Nginx reverse proxy.

**Strengths:**
- Authorization is enforced server-side. Every list endpoint runs through a centralized scoping layer (`accounts/scoping.py`) and the ticket workflow has a real state machine with role + scope guards (`tickets/state_machine.py`).
- Attachment uploads go through a private, authenticated download endpoint (no public `/media/` exposure in prod). MIME and size are validated. Stored filenames are randomized via UUID.
- Multi-tenant isolation is exercised by shell smoke tests (`scope_isolation_test.sh`, `attachment_*.sh`, `assignment_api_test.sh`).
- Production hardening is largely in place: env-driven security flags, Whitenoise + manifest static files, security headers at Nginx, throttling, optional Sentry, log rotation.

**Major gaps:**
- **Zero Python-level tests.** All seven `backend/*/tests.py` are empty stubs. The whole correctness story rests on shell smoke tests that depend on a populated dev DB.
- **JWT refresh-token rotation/blacklist is not enabled** and there is no logout endpoint that invalidates a refresh token; tokens stored in `localStorage` are vulnerable to XSS exfiltration. (Already documented as a known risk in `docs/SECURITY_REVIEW.md`.)
- **No password reset, no user invitation, no self-service user/company/building/customer admin.** The only user creation paths are the Django admin and management shell — which is fine for an internal tool but blocks any "real" tenant onboarding.
- **No SLA engine, no reports/analytics endpoints**, despite the UI advertising "SLA-ready workflows" and the routing including a `reports` Django app that is empty. The dashboard's "stats" are computed client-side from one page of results, so they are misleading.
- **A few real backend correctness bugs:** the assign endpoint is reachable by customer users (returns 400 instead of 403), customer users can see all buildings/customers within their company (over-broad scoping), `LoginLog` is declared but never written, ticket numbers contain a TOCTOU race, and `TicketStatus` has a `resolved_at` field that no transition ever sets.

**Production readiness:** The system is **MVP-ready for a small, internal, cooperative tenant** but is **not yet ready for an external multi-tenant launch**. See section B for the maturity rating and section J for the roadmap.

---

## B. Maturity Rating

| Stage | Rating | Reason |
|---|---|---|
| Demo-ready | ✅ Yes | Login, create, list, assign, transition, attach, download, audit trail all work end-to-end. Demo users in [LoginPage.tsx:7-12](frontend/src/pages/LoginPage.tsx#L7-L12). |
| MVP-ready (internal/single-tenant) | 🟡 Mostly | Workflow is correct for happy path. Authorization is enforced server-side. Missing: password reset, user invitation, real reporting, automated test suite. |
| Production-ready (external multi-tenant) | ❌ No | Blockers: no automated test coverage, JWT in localStorage with no refresh rotation/blacklist or logout, customer scope leaks all building/customer rows in their company, no SLA engine, no reports endpoints, ticket-number race, no rate limiting on auth-token endpoint scope until env override is set, customer can hit assign endpoint, no admin UX for tenant lifecycle. |

---

## C. P0 Blockers (must fix before public production)

### C1. No automated backend test suite
- **Severity:** P0
- **Risk:** Every existing test is a shell script that requires a running dev DB with a specific seed. There are zero `TestCase`/`APITestCase` classes ([`backend/*/tests.py`](backend/accounts/tests.py) all 3 lines, empty). Any regression in scoping, state machine, or attachment access control will ship silently. CI cannot run hermetic tests.
- **Evidence:** `wc -l backend/*/tests.py` → all 3 lines. `grep -rn 'def test_' backend/` → empty.
- **Recommended fix:** Add `pytest-django` and write Django `APITestCase` coverage for the items in section I. Wire into `check_all.sh`.
- **Tests needed?** Yes — this finding *is* the testing gap.

### C2. JWT refresh tokens are not rotated or blacklistable; no server-side logout
- **Severity:** P0 for public launch (P1 for internal)
- **Risk:** [`backend/config/settings.py:184-188`](backend/config/settings.py#L184-L188) configures only `ACCESS_TOKEN_LIFETIME` and `REFRESH_TOKEN_LIFETIME`. `ROTATE_REFRESH_TOKENS`, `BLACKLIST_AFTER_ROTATION`, and `rest_framework_simplejwt.token_blacklist` are not enabled. A leaked refresh token is valid for 7 days with no way to revoke it. Frontend `logout()` only clears `localStorage` ([AuthContext.tsx:30-35](frontend/src/auth/AuthContext.tsx#L30-L35)) — the token remains valid server-side until expiry.
- **Recommended fix:** Add `rest_framework_simplejwt.token_blacklist` to `INSTALLED_APPS`, run its migration, set `ROTATE_REFRESH_TOKENS = True` and `BLACKLIST_AFTER_ROTATION = True`. Add `POST /api/auth/logout/` that blacklists the supplied refresh token. Optionally migrate refresh-token storage to an HttpOnly cookie as already noted in [SECURITY_REVIEW.md:36-46](docs/SECURITY_REVIEW.md#L36-L46).
- **Tests needed?** Yes — token blacklist + logout endpoint.

### C3. Customer/building scoping leaks the whole company tree
- **Severity:** P0 for true multi-tenant
- **Risk:** A `CUSTOMER_USER` has `building_ids_for(user)` return *every building of every customer they are linked to* ([`scoping.py:46-47`](backend/accounts/scoping.py#L46-L47)). For `COMPANY_ADMIN`, `building_ids_for` returns **all buildings of any company they are a member of** ([`scoping.py:39-41`](backend/accounts/scoping.py#L39-L41)) — fine if a company admin owns the whole company, but the same is true for customer scoping: `customer_ids_for(COMPANY_ADMIN)` returns all customers of every company they belong to ([`scoping.py:59-61`](backend/accounts/scoping.py#L59-L61)). Also, the `MeSerializer` returns these full lists to the client ([`accounts/serializers.py:34-41`](backend/accounts/serializers.py#L34-L41)), which can be a sensitive enumeration vector for large tenants.
- **More concerning bug:** The `BuildingViewSet` and `CustomerViewSet` (`scope_buildings_for`/`scope_customers_for`) return the union for any company-admin/customer-user. So a customer user logged in against company A can list **every** customer/building they are a member of, plus any others returned by their joined memberships. Today that's mostly correct since memberships are explicit, but the *building scope for customer user* is "all buildings under any customer they are linked to" — which still includes only what they are linked to, so the actual leak is limited.
  - **Real residual bug:** `customer_ids_for(CUSTOMER_USER)` is exact (their memberships), but a customer user who is invited to one customer in a building gets **only that customer**, however `building_ids_for(CUSTOMER_USER)` exposes the building, and via the `BuildingViewSet` they see the building's metadata (address, postal code, etc.) — that may be intended.
- **Strong recommendation:** Add an explicit allow-list test (`tests.py`) per role for `/api/buildings/`, `/api/customers/`, `/api/companies/` and verify that two memberships in different companies do not see each other's data. Reject the suggestion to broaden any scope.
- **Tests needed?** Yes.

### C4. `assign`, `change_status`, `assignable-managers`, `messages`, and `attachments` viewsets do not call `is_staff_role` consistently
- **Severity:** P0 (subtle — current behavior is mostly safe but inconsistent and brittle)
- **Risk:**
  - `TicketViewSet.assign` ([views.py:90-112](backend/tickets/views.py#L90-L112)) only uses `CanViewTicket`. The serializer's `validate()` ([serializers.py:354-388](backend/tickets/serializers.py#L354-L388)) rejects customer users with HTTP 400, but this means a customer user can hit the assign endpoint at all, which is wrong both for HTTP semantics (should be 403) and because a future serializer refactor could regress.
  - `change_status` ([views.py:68-87](backend/tickets/views.py#L68-L87)) is similarly only viewing-scoped; the state machine prevents bad transitions, but the same brittleness applies.
  - `TicketAttachmentListCreateView.perform_create` silently coerces `is_hidden=False` for non-staff ([views.py:234-236](backend/tickets/views.py#L234-L236)), but the serializer also raises a 400 for the same case ([serializers.py:308-317](backend/tickets/serializers.py#L308-L317)). Two different code paths gate the same rule — keep one.
- **Recommended fix:** Add an explicit `is_staff_role(request.user)` permission gate on `assign`, `change_status`, and `assignable-managers` (already done for the latter inline). Decide whether `is_hidden` is enforced at the serializer or the view, and remove the duplication.
- **Tests needed?** Yes.

### C5. Ticket number generation has a write-after-write race
- **Severity:** P0 for high-volume / multi-worker prod
- **Risk:** [`Ticket.save`](backend/tickets/models.py#L111-L117) saves the row, then sets `ticket_no = TCK-{year}-{id:06d}` and saves again. Two concurrent inserts in the same year race-free (unique on `ticket_no`). But the second `super().save(update_fields=["ticket_no"])` uses the auto-now `updated_at` and bypasses any signal logic. More importantly, **between the two saves the ticket exists with `ticket_no=""`**, which `notifications.services.send_ticket_created_email` can reference (it calls the function after `serializer.save()`, but the *creation* of the row is not in a transaction, so a Celery worker / concurrent reader could see a blank `ticket_no`). Also, the format depends on `id`, which is fine, but is not test-covered.
- **Recommended fix:** Wrap creation in `transaction.atomic()`; or generate the number from a sequence/UUID; or use a `pre_save` signal that derives from `id` only after the row is committed. Add a unit test verifying uniqueness under concurrent insert.
- **Tests needed?** Yes.

### C6. `.env` is loaded into the prod container but never validated at boot
- **Severity:** P0 for unattended deploys
- **Risk:** [`backend/config/settings.py:20-25`](backend/config/settings.py#L20-L25) only fails on missing `DJANGO_SECRET_KEY` when `DEBUG=False`. There is no boot-time check for `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `POSTGRES_PASSWORD` strength, etc. The repo has [`scripts/prod_env_check.sh`](scripts/prod_env_check.sh) which is good but only runs if the operator runs it.
- **Recommended fix:** Either run `prod_env_check.sh` as a healthcheck/init container, or add an `apps.py` `ready()` hook in `config` that validates required settings when `DEBUG=False`.
- **Tests needed?** Yes (settings validator unit test).

---

## D. P1 Important Issues

### D1. `LoginLog` is declared but never written
- **Severity:** P1
- **Risk:** [`accounts/models.py:99-118`](backend/accounts/models.py#L99-L118) defines `LoginLog`, registered in admin ([`accounts/admin.py:35-40`](backend/accounts/admin.py#L35-L40)), but no view writes to it. `ScopedTokenObtainPairView` ([`accounts/views.py:10-12`](backend/accounts/views.py#L10-L12)) is a thin wrapper. Login auditing is silently broken.
- **Recommended fix:** Subclass `TokenObtainPairSerializer.validate()` (or override `post`) to write a `LoginLog` row with IP and user-agent. Capture failures too.
- **Tests needed?** Yes.

### D2. No password reset / forgot-password flow
- **Severity:** P1
- **Risk:** Users locked out can only be reset via the Django admin or shell. Not viable for any external user base.
- **Recommended fix:** Add `dj-rest-auth` or build a custom token-based reset (`POST /api/auth/password/reset/` → email; `POST /api/auth/password/reset/confirm/`).
- **Tests needed?** Yes.

### D3. No user invitation / company onboarding flow
- **Severity:** P1
- **Risk:** Adding a new company admin requires manual shell scripting (`prod_upload_download_test.sh` shows how). There is no API to invite a `CUSTOMER_USER` or `BUILDING_MANAGER`.
- **Recommended fix:** Add an `Invitation` model + endpoint, signed token by email, accept-flow that sets password.
- **Tests needed?** Yes.

### D4. No password policy on creation
- **Severity:** P1
- **Risk:** Django's `AUTH_PASSWORD_VALIDATORS` are configured ([`settings.py:99-104`](backend/config/settings.py#L99-L104)), but they only fire on Django form / admin creation. The `UserManager._create_user` ([`accounts/models.py:22-30`](backend/accounts/models.py#L22-L30)) does not call `password_validation.validate_password`, and there is no "register" or "set password" API yet that runs validators. When invitations are added (D3), they must explicitly call `validate_password`.
- **Recommended fix:** Centralize password validation in a serializer mixin to be reused by reset, invitation, and admin paths.
- **Tests needed?** Yes.

### D5. Customer can post to `/api/tickets/{id}/messages/` but cannot see internal notes — duplicated rule
- **Severity:** P1
- **Risk:** [`tickets/views.py:169-184`](backend/tickets/views.py#L169-L184) and [`tickets/serializers.py:232-237`](backend/tickets/serializers.py#L232-L237) both enforce that customers cannot post internal notes. The view *coerces* the type to `PUBLIC_REPLY`, while the serializer raises 400. If the serializer raises first, the view's coercion never runs. Behavior is correct, but the dual logic is fragile.
- **Recommended fix:** Pick one (prefer serializer raising 400). Add tests.

### D6. Throttling defaults are far too permissive in code; only env can tighten
- **Severity:** P1
- **Risk:** [`settings.py:174-179`](backend/config/settings.py#L174-L179) ships `anon=1000/minute`, `user=10000/hour`, `auth_token=200/minute`. The `.env.production.example` overrides to `60/minute` etc., but if the operator forgets to set them or copies from `.env.example`, prod runs with the loose defaults.
- **Recommended fix:** Make production defaults the strict set, and let dev relax via env. Or, fail-fast if `DEBUG=False` and `DRF_THROTTLE_ANON_RATE` is unset.
- **Tests needed?** No (config-level).

### D7. No rate limiter or lockout on `/api/auth/token/` brute force
- **Severity:** P1
- **Risk:** The DRF scoped throttle gives ~200/min by default (or 20/min with prod env). That's per-IP/per-user, but does not implement an account lockout. For a public launch, an attacker can grind 20/min × ∞ minutes against one email.
- **Recommended fix:** Add a per-account failed-login counter (could live on `LoginLog`) with progressive backoff, or use `django-axes`.
- **Tests needed?** Yes.

### D8. Ticket model `resolved_at` is dead — no transition sets it
- **Severity:** P1 (data integrity)
- **Risk:** [`tickets/models.py:102`](backend/tickets/models.py#L102) declares `resolved_at`, but `tickets/state_machine.py` `TIMESTAMP_ON_ENTER` ([`state_machine.py:58-63`](backend/tickets/state_machine.py#L58-L63)) only stamps `sent_for_approval_at`, `approved_at`, `rejected_at`, `closed_at`. Any reporting that depends on "resolved" will be empty.
- **Recommended fix:** Either remove `resolved_at` or define what "resolved" means and stamp it (probably on entering `APPROVED`).

### D9. `TicketAttachmentListCreateView` does not also enforce hidden-attachment access at object level
- **Severity:** P1
- **Risk:** The list view filters out hidden attachments for non-staff users ([`views.py:217-220`](backend/tickets/views.py#L217-L220)), but a customer user with a guessed attachment ID can still hit `GET /tickets/{id}/attachments/{aid}/download/`. The download view does check ([`views.py:263-264`](backend/tickets/views.py#L263-L264)). However, the `ALL/PATCH/DELETE/individual GET on the attachment list endpoint` doesn't exist (it is list-create only), so no individual retrieve leak. Confirmed safe.
- **Recommended fix:** Add a regression test.
- **Tests needed?** Yes.

### D10. `_get_ticket()` is called multiple times per request
- **Severity:** P1 (performance / consistency)
- **Risk:** [`TicketMessageListCreateView._get_ticket`](backend/tickets/views.py#L147-L153) is called from `get_queryset`, `get_serializer_context`, and `perform_create`. Each call runs the scoping query again. This is a minor perf issue but also means the ticket can change between the queries (e.g., status changes). Same for `TicketAttachmentListCreateView`.
- **Recommended fix:** Memoize on `self` per request.

### D11. `TicketListSerializer` and `TicketDetailSerializer` expose `description` only on detail — but search filter lets enumerable substring search across all tickets in scope
- **Severity:** P1 (information disclosure)
- **Risk:** [`tickets/views.py:41`](backend/tickets/views.py#L41): `search_fields = ["ticket_no", "title", "description", "room_label"]`. A customer user can search for "salary" or "internal" across descriptions of every ticket they have scope for — including any internal notes that snuck into descriptions.
- **Recommended fix:** Document this as intended, or remove `description` from `search_fields` and require staff role to enable description search.

### D12. Compose `redis` is started but no Celery worker is wired in
- **Severity:** P1 (architectural)
- **Risk:** `requirements.txt` includes `celery>=5.4` and `redis>=5.2`. `docker-compose.prod.yml` runs Redis with a healthcheck, but neither the dev nor prod compose has a `worker` service. Email sending is **synchronous** ([`notifications/services.py:115-129`](backend/notifications/services.py#L115-L129)), so any slow SMTP server blocks the request thread up to `GUNICORN_TIMEOUT`. On SES throttle / DNS fail, ticket creation requests will hang.
- **Recommended fix:** Either: (a) move email sending to a background thread / Celery worker (preferred), or (b) drop Celery from requirements.

### D13. Soft delete is only modeled on `User` and is not respected uniformly
- **Severity:** P1
- **Risk:** `User` has `deleted_at` and `is_active`. Most queries filter both. But `Building`, `Customer`, `Company` only have `is_active`, and the scoping queries do **not** filter `is_active=True`. A "deactivated" company still has visible tickets. The customer/building list views also do not filter inactive.
- **Recommended fix:** Decide whether `is_active=False` means hidden; if so, filter in `scope_*_for`. Otherwise rename to `is_archived` and add an explicit "show archived" toggle.

### D14. No `Ticket.description`/`title` length on create — DB column is 255 for title only
- **Severity:** P1
- **Risk:** [`models.py:75-76`](backend/tickets/models.py#L75-L76): `title=CharField(255)`, `description=TextField()`. Frontend caps title to 255 ([`CreateTicketPage.tsx:240`](frontend/src/pages/CreateTicketPage.tsx#L240)) but no minimum length / sanitization. `description` has no max — a multi-MB description crashes the page render and bloats indexes.
- **Recommended fix:** Add `MaxLengthValidator(10000)` in serializer; trim whitespace; reject empty after strip.

### D15. Ticket list ordering is not exposed via `?ordering=` correctly with query
- **Severity:** P1 (low-impact)
- **Risk:** `ordering_fields` is set ([`views.py:42`](backend/tickets/views.py#L42)) but the default `Meta.ordering = ['-created_at']` on the model overrides the queryset default. Verify ordering plumbing under pagination.

---

## E. P2 Improvements

### E1. Reports app is empty
- [`backend/reports/`](backend/reports) has only stubs; no `urls.py`, no model. The frontend has a disabled "Reports" sidebar entry ([`AppShell.tsx:100-103`](frontend/src/layout/AppShell.tsx#L100-L103)). Either delete the app or fill it with at least a basic ticket-volume / status-distribution endpoint.

### E2. Dashboard "stats" are computed on one page of results
- [`DashboardPage.tsx:132-151`](frontend/src/pages/DashboardPage.tsx#L132-L151) computes "active", "waiting approval", "urgent", "closed" by filtering the `tickets` array, which is the current page only (max 25). The displayed numbers will be wildly off whenever count > 25.
- **Fix:** Add `/api/tickets/stats/` (or pre-aggregate counts in DashboardPage with `?status=...&page_size=1`).

### E3. Health-score formula is fake
- [`DashboardPage.tsx:153-155`](frontend/src/pages/DashboardPage.tsx#L153-L155): clamped synthetic score between 56-98. Misleading. Replace with a real metric or remove.

### E4. "Remember this device for 30 days" checkbox does nothing
- [`LoginPage.tsx:131-134`](frontend/src/pages/LoginPage.tsx#L131-L134): the checkbox is unbound. Either wire it (longer refresh token) or remove.

### E5. Demo users are hardcoded in production frontend bundle
- [`LoginPage.tsx:7-12`](frontend/src/pages/LoginPage.tsx#L7-L12): `DEMO_USERS` ships in the prod build. Anyone can read the array and try the credentials. If the prod DB has the same passwords — game over. The seeded prod test data uses `Admin12345!` / `Test12345!`, **so this is exploitable** if the prod smoke-test seed (`scripts/prod_upload_download_test.sh`) is left in place.
- **Fix:** Gate `DEMO_USERS` behind `import.meta.env.DEV` or a `VITE_SHOW_DEMO_USERS` flag. Rotate the seeded prod passwords or delete those users post-validation.
- **Severity reconsidered:** This is closer to **P1** if the seeded users are kept after a real launch. Mark it as such if you don't strip seed users.

### E6. `getApiError` swallows array errors silently
- [`client.ts:131-138`](frontend/src/api/client.ts#L131-L138): only the first error key is shown; nested validation errors disappear.

### E7. `frontend/package.json` pins typescript `~6.0.2` and vite `^8.0.10`
- These are not yet stable releases at time of this audit; verify they're not pre-release/alpha. If so, this is a supply-chain risk and a build-fragility risk.

### E8. `notifications/services.py` does not throttle / batch
- For 100 ticket assignments in one minute, you get 100 sync `send_mail` calls per request. See D12.

### E9. `TicketAttachment.message` foreign key is unused in current upload flow
- The upload view never sets `message=` ([`views.py:229-245`](backend/tickets/views.py#L229-L245)). Either drop the FK or implement attaching files to a specific message.

### E10. `Whitenoise` is in the middleware but `STATIC_ROOT` is configured under the backend container
- Nginx already proxies `/static/` to backend ([`nginx.conf:37-42`](frontend/nginx.conf#L37-L42)). Whitenoise + Nginx-proxy is double-serving statics; not a bug but wasted effort.

### E11. No request-id / correlation-id middleware for log tracing
- For Sentry to be useful you'll want one.

### E12. `scope_isolation_test.sh` and other shell tests rely on dev DB seed
- Fragile. Re-running on a fresh DB requires manual seeding via Django shell (see `prod_upload_download_test.sh`). Move seed into a Django management command (`python manage.py seed_demo`).

### E13. Dev compose has no healthcheck on backend
- [`docker-compose.yml`](docker-compose.yml) has no healthchecks for db/redis/backend. Compose-up race conditions.

### E14. Admin URL is on default `/admin/`
- Standard Django default. Optional: move to a non-default path or behind IP allowlist.

### E15. `customer.contact_email` may be PII; not encrypted at rest
- Database column. PII. Decide whether GDPR scope applies.

---

## F. Security Findings

| # | Severity | Finding | File |
|---|---|---|---|
| F1 | P0 | JWT in `localStorage`; no refresh rotation/blacklist; no logout endpoint | [config/settings.py:184-188](backend/config/settings.py#L184-L188), [client.ts:31-43](frontend/src/api/client.ts#L31-L43), [SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) |
| F2 | P0 | Throttle defaults too loose; no per-account brute-force lockout | [settings.py:169-179](backend/config/settings.py#L169-L179) |
| F3 | P1 | Demo creds hard-coded in prod bundle | [LoginPage.tsx:7-12](frontend/src/pages/LoginPage.tsx#L7-L12) |
| F4 | P1 | Customer description search exposes other tickets in scope | [tickets/views.py:41](backend/tickets/views.py#L41) |
| F5 | P1 | Customer can hit `assign`/`change-status` endpoints (rejected at serializer with 400 instead of 403) | [tickets/views.py:90-112](backend/tickets/views.py#L90-L112) |
| F6 | P1 | `LoginLog` not written; brute-force / suspicious-login auditing absent | [accounts/views.py:10-12](backend/accounts/views.py#L10-L12) |
| F7 | P1 | No password reset; no invitation; password policy not enforced on programmatic user creation | [accounts/models.py:32-49](backend/accounts/models.py#L32-L49) |
| F8 | P1 | `MeSerializer` returns full id-lists for company/building/customer; potential enumeration | [accounts/serializers.py:34-41](backend/accounts/serializers.py#L34-L41) |
| F9 | P2 | Admin not gated by IP / 2FA | [config/urls.py:8](backend/config/urls.py#L8) |
| F10 | P2 | No CSRF protection on JWT endpoints (acceptable for Bearer-token APIs but document) | [settings.py:154-158](backend/config/settings.py#L154-L158) |
| F11 | P2 | `MEDIA_ROOT` in `DEBUG` mode is publicly served by Django | [config/urls.py:16-17](backend/config/urls.py#L16-L17) |
| F12 | P2 | `client_max_body_size 12M` in Nginx ([`nginx.conf:12`](frontend/nginx.conf#L12)) is barely above the 10 MB limit; no defense in depth at gateway against multipart-bomb |
| F13 | P2 | `Permissions-Policy` only disables 3 features; no `Content-Security-Policy` set anywhere | [nginx.conf:7-10](frontend/nginx.conf#L7-L10) |
| F14 | P3 | Django admin discloses internal user model fields, login logs, notification logs to anyone with staff cookie | [accounts/admin.py](backend/accounts/admin.py) |

---

## G. Backend Correctness Findings

### G1. State machine is solid (positive finding)
- [`tickets/state_machine.py`](backend/tickets/state_machine.py) implements an explicit `(from, to) → {role: scope}` map; uses `select_for_update()` to detect stale concurrent transitions; writes a `TicketStatusHistory` row in the same atomic block. **Good.**

### G2. Attachment download enforces ticket scope **and** hidden-flag (positive finding)
- [`TicketAttachmentDownloadView.get`](backend/tickets/views.py#L251-L273) checks `scope_tickets_for` then re-checks `is_hidden` against `is_staff_role`. Verified by the `attachment_download_test.sh` shell test.

### G3. Tickets can be created for any customer in your scope, but only validates customer-belongs-to-building, not customer-belongs-to-company
- [`TicketCreateSerializer.validate`](backend/tickets/serializers.py#L157-L204) checks `customer.building_id == building.id`. Indirectly that means the company is correct because customer.building.company == building.company by `Customer` model FK. **OK.**

### G4. `closed_at` ticket can be reopened, but no rule prevents editing a closed ticket's title/description
- There is no "edit ticket" endpoint at all, so closed-ticket edit-restriction is moot today. If a future PATCH endpoint is added, enforce it.

### G5. `assigned_to` on a ticket is `SET_NULL` when the user is deleted
- [`tickets/models.py:67-71`](backend/tickets/models.py#L67-L71) — fine.

### G6. `created_by` is `PROTECT`
- [`tickets/models.py:60-64`](backend/tickets/models.py#L60-L64) — means a user with tickets cannot be hard-deleted. `User.soft_delete` ([`accounts/models.py:92-96`](backend/accounts/models.py#L92-L96)) sets `is_active=False` and `deleted_at`. Consistent.

### G7. `Customer.on_delete=PROTECT` for the Building FK
- [`customers/models.py:11-15`](backend/customers/models.py#L11-L15) means a building cannot be deleted without first deleting customers. Tickets keep building (`PROTECT`) and customer (`PROTECT`). **OK.**

### G8. `Company.on_delete=CASCADE` everywhere
- Deleting a company nukes buildings, customers, tickets, notifications. Probably what you want for tenant offboarding, but make sure there's no UI/API path that exposes Company-delete (today there isn't — companies are read-only via `CompanyViewSet`).

### G9. `Ticket.priority` does not affect ordering or notifications
- The state machine ignores priority. There's no escalation logic. SLA does not exist.

### G10. No explicit DB indexes added beyond Django defaults
- All FKs get an index automatically. But common filters (`status`, `priority`, `(company, status)`, `(building, status)`, `(customer, status)`) are not composite-indexed. At ~50k tickets scoped to one building manager, the `Ticket.objects.filter(building_id__in=…)` will sequential-scan in PG.
- **Fix:** Add `Meta.indexes = [models.Index(fields=['status', 'priority']), models.Index(fields=['company', 'status'])]` (and similar). Tests not strictly needed; benchmark instead.

### G11. No optimistic concurrency on `Ticket.assigned_to` or `Ticket.priority`
- Not a real risk yet (no two-staff-edit-same-ticket UX), but flag for future.

### G12. `TicketMessage.is_hidden` and `message_type=INTERNAL_NOTE` are *both* used to hide; ambiguity
- `TicketMessageListCreateView.perform_create` sets `is_hidden=(message_type == INTERNAL_NOTE)` ([`views.py:179-184`](backend/tickets/views.py#L179-L184)). They're synonyms today. Pick one in DB schema; the redundancy invites inconsistency.

### G13. `TicketCreateSerializer` does not validate against soft-deleted users / inactive buildings / inactive customers
- A closed building can still be the target of a new ticket. Add `is_active=True` filters or explicit validation.

### G14. The `notifications.services._ticket_customer_users` includes `ticket.created_by` even if they were never linked via membership
- [`notifications/services.py:62-71`](backend/notifications/services.py#L62-L71). This is intentional but expand the comment. A staff-created ticket on behalf of a customer will not satisfy `created_by.role==CUSTOMER_USER` and so won't notify them. If staff create on behalf of a customer, no customer email is sent.

---

## H. Missing Product Features

| # | Feature | Notes |
|---|---|---|
| H1 | Password reset / forgot password | Hard blocker for any non-internal user. |
| H2 | User invitation flow | Today: shell script. |
| H3 | Self-service company / building / customer admin | Read-only viewsets only. |
| H4 | SLA engine (first response, resolution due, business hours, paused-states) | Models have `first_response_at`/`sent_for_approval_at` but no policy or due-date computation. |
| H5 | Reports endpoints (volume, status, manager throughput, customer satisfaction) | `reports/` app is empty. Frontend "Reports" link is disabled. |
| H6 | CSV / PDF exports | None. |
| H7 | Customer survey / approval-with-rating | `WAITING_CUSTOMER_APPROVAL → APPROVED/REJECTED` exists but no rating capture. |
| H8 | Ticket merge / link related tickets | None. |
| H9 | File preview for attachments | Today: download only. |
| H10 | Search across attachments / OCR | None. |
| H11 | Inline @mentions in messages | None. |
| H12 | Push notifications / WebSocket updates | None. ASGI is not wired (`asgi.py` is default). |
| H13 | Audit log for non-status events (who edited assignment, who hid attachment, who disabled a user) | Only `TicketStatusHistory` exists. |
| H14 | Multi-language UI | Frontend is English-only despite backend `LANGUAGE_CODE=nl`. |
| H15 | Bulk actions (close many tickets, reassign, delete) | None. |
| H16 | Saved views / bookmarked filters | None. |
| H17 | Time tracking / labor logging | None. |
| H18 | Dashboard with **real** scope-wide metrics (see E2). |

---

## I. Test Coverage Gaps

**Current state:** zero pytest/unittest tests; ~9 shell smoke scripts that require a populated dev DB.

### Concrete test files to add (priority order)

1. **`backend/accounts/tests.py`**
   - `test_login_active_user_succeeds`
   - `test_login_inactive_user_fails`
   - `test_login_soft_deleted_user_fails`
   - `test_token_refresh_rotates_when_enabled`
   - `test_logout_blacklists_refresh_token` (after C2 fix)
   - `test_me_returns_correct_scope_per_role`

2. **`backend/tickets/tests/test_scoping.py`** (split tests.py into a package)
   - `test_super_admin_sees_all_tickets`
   - `test_company_admin_only_sees_own_company`
   - `test_building_manager_only_sees_assigned_buildings`
   - `test_customer_only_sees_linked_customers`
   - `test_customer_cannot_view_internal_notes`
   - `test_customer_cannot_view_hidden_attachments`
   - `test_search_does_not_leak_other_customer_tickets` (covers F4)

3. **`backend/tickets/tests/test_state_machine.py`**
   - `test_each_allowed_transition_with_correct_role`
   - `test_each_disallowed_transition_returns_forbidden_transition`
   - `test_concurrent_transition_raises_stale_status` (uses `select_for_update`)
   - `test_status_history_row_created_on_transition`
   - `test_timestamps_set_on_enter`

4. **`backend/tickets/tests/test_attachments.py`**
   - `test_customer_cannot_upload_hidden_attachment_returns_400`
   - `test_customer_cannot_download_hidden_attachment_returns_403`
   - `test_attachment_size_limit`
   - `test_attachment_mime_whitelist`
   - `test_attachment_filename_randomized_in_storage`
   - `test_download_uses_original_filename_in_response`
   - `test_attachment_outside_user_scope_returns_404`

5. **`backend/tickets/tests/test_assignment.py`**
   - `test_only_staff_can_assign`
   - `test_assignee_must_be_building_manager`
   - `test_assignee_must_belong_to_building`
   - `test_customer_cannot_view_assignable_managers` (currently 403 — verify)
   - `test_assignment_email_sent_on_change_only`

6. **`backend/notifications/tests.py`**
   - `test_ticket_created_emails_only_staff_in_company`
   - `test_actor_excluded_from_recipients`
   - `test_dedupe_users`
   - `test_email_failure_logs_failed_status` (mock `send_mail` raise)

7. **`backend/tickets/tests/test_ticket_no.py`** (covers C5)
   - `test_ticket_number_unique_under_concurrent_creation`

8. **`backend/config/tests/test_settings_validator.py`** (covers C6)
   - `test_missing_secret_key_in_prod_raises`
   - `test_missing_allowed_hosts_in_prod_raises`

9. **`backend/accounts/tests/test_permissions.py`**
   - `test_inactive_user_cannot_call_me`
   - `test_soft_deleted_user_blocked_in_authentication_rule`

10. **CI integration**
    - Add `pytest-django` to requirements.
    - Run `python manage.py test` (or `pytest`) in CI before any shell tests.

**Coverage target:** 70% line coverage on `backend/{accounts,tickets,notifications}/`. Critical paths (scoping, state machine, attachment access) should be 95%+.

---

## J. Recommended Implementation Roadmap

**Phase 0 — Hardening sprint (1 week, must ship before any real launch)**
1. C1: Bootstrap `pytest-django` + write the 10 test modules in section I (parallelizable).
2. C2: Enable `token_blacklist`, add logout endpoint.
3. C4: Add explicit `is_staff_role` guards on `assign` / `change_status`.
4. C5: Wrap ticket creation in `transaction.atomic()`, add concurrency test.
5. C6: Add boot-time settings validator OR document `prod_env_check.sh` as required.
6. F3 / E5: Strip demo users from prod build.

**Phase 1 — User lifecycle (1-2 weeks)**
1. D1: `LoginLog` writer in `ScopedTokenObtainPairView`.
2. D2: Password reset endpoint + email template.
3. D3: Invitation model + endpoint.
4. D4: Centralize password validation.
5. D7: Brute-force lockout via `LoginLog` counter or `django-axes`.

**Phase 2 — Operational maturity (2 weeks)**
1. D6: Tighten throttle defaults.
2. D8: Decide `resolved_at`.
3. D11: Restrict `description` from search for non-staff.
4. D12: Move email sending to a Celery worker (and add the worker service in compose).
5. D13: Decide `is_active` semantics across all models.
6. G10: Add composite indexes; benchmark.
7. E1: Either delete `reports/` or build the v1 endpoints (status distribution, age buckets, manager throughput).
8. E2: Replace dashboard's client-side stats with a real `/api/tickets/stats/` endpoint.

**Phase 3 — Product features (separate plan)**
1. H4: Real SLA engine (durations, business hours, paused states).
2. H5: Reports + CSV/PDF export.
3. H7: Customer rating capture on approval/rejection.
4. H12: Notifications and live updates.
5. H14: Multi-language UI.

---

## K. Files That Need Changes

| File | Section refs | Nature of change |
|---|---|---|
| `backend/config/settings.py` | C2, C6, D6 | Add `token_blacklist`, rotation flags, settings validator, tighter throttle defaults. |
| `backend/accounts/urls.py` | C2, D2, D3 | Add logout, password reset, invitation routes. |
| `backend/accounts/views.py` | C2, D1, D2, D3 | LogoutView, LoginLog writer, reset/invitation views. |
| `backend/accounts/serializers.py` | D4 | Centralize password validation. |
| `backend/accounts/scoping.py` | C3 | Add tests; consider tightening building/customer scope for non-super-admin roles. |
| `backend/accounts/tests.py` → `accounts/tests/*.py` | C1, I | New test package. |
| `backend/tickets/views.py` | C4, D5, D9, D10 | Add explicit `is_staff_role` checks; memoize `_get_ticket`. |
| `backend/tickets/models.py` | C5, D8, G10, G12, D14 | Atomic ticket-no, drop unused field, indexes, validators. |
| `backend/tickets/serializers.py` | D14, G13 | Min/max validation, active-only filtering. |
| `backend/tickets/tests.py` → `tickets/tests/*.py` | C1, I | New test package. |
| `backend/notifications/services.py` | D12, E8 | Async send via Celery. |
| `backend/reports/` | E1, H5 | Either delete or build endpoints. |
| `frontend/src/auth/AuthContext.tsx` | C2 | Call new logout endpoint. |
| `frontend/src/pages/LoginPage.tsx` | E5, F3 | Hide demo users in prod build. |
| `frontend/src/pages/DashboardPage.tsx` | E2, E3 | Real stats endpoint; remove fake health score. |
| `frontend/src/api/client.ts` | E6 | Better error message extraction. |
| `frontend/nginx.conf` | F12, F13 | Lower `client_max_body_size` to 11M and add CSP. |
| `docker-compose.prod.yml` | D12 | Add `worker` service if Celery is kept. |
| `docker-compose.yml` | E13 | Add healthchecks. |
| `scripts/check_all.sh` | I | Run `python manage.py test` before shell tests. |
| `docs/PRODUCTION_CHECKLIST.md` | C2, D2, D3 | Add real-launch blockers (logout, password reset, invitation, demo-creds removal). |

---

## L. Commands Run

```
wsl bash -c "find . -type f \( -name '*.py' -o … \) | sort"
wsl bash -c "wc -l backend/**/*.py frontend/src/**/*.ts*"
wsl bash -c "grep -rn 'def test_' backend/ --include='*.py'"
wsl bash -c "wc -l backend/*/tests.py"
wsl bash -c "grep -n 'db_index\|class Meta\|indexes' backend/*/models.py"
wsl bash -c "ls .env*"
wsl bash -c "cat .gitignore"
wsl bash -c "ls scripts/"
wsl bash -c "head/cat <files>"  # Read tool used for ~30 source files
```

All inspection done via `Read` / `Grep` / `Glob` and `Bash` (read-only). No code modified; no containers started; no migrations run.

---

## M. Assumptions and Unknowns

1. **Assumption:** "Production" means single-region, single-server Docker Compose deploy behind external HTTPS reverse proxy. The repo's `docs/SERVER_HANDOFF.md` and `nginx.conf` confirm this is the intended target. If the target is Kubernetes / multi-region, several findings (Celery, Redis usage, log aggregation) escalate.
2. **Assumption:** "Customer" means an end-user account belonging to a tenant building. `CustomerUserMembership` confirms this.
3. **Unknown:** Whether the prod DB will share the dev seed (`admin@example.com / Admin12345!` etc.). If yes, F3 / E5 escalate to P0. The `prod_upload_download_test.sh` script seeds those users — they must be deleted or rotated before public launch.
4. **Unknown:** Whether GDPR / EU PII rules apply (the system handles `contact_email` and Dutch language defaults). If yes, add data-retention policy, right-to-be-forgotten flow, and DPA documentation.
5. **Unknown:** Whether the system is intended to scale beyond ~10k tickets / single building manager. If yes, see G10 (composite indexes) and D11 (search scope).
6. **Unknown:** Whether internal notes ever need to be visible to a "customer admin" (a role that doesn't exist today). If a future requirement comes, the `INTERNAL_NOTE` / `is_hidden` redundancy (G12) becomes a liability.
7. **Unknown:** Whether there is a separate planned mobile / Slack / API consumer. If yes, the JWT-in-cookie migration (C2) needs a CSRF design. Today only the web app consumes the API.
8. **Unknown:** What happens to `media/` on a backend redeploy. The `backend_media_prod` named volume persists, but the file paths are stable only if `MEDIA_ROOT` and the upload-path function don't change. Confirmed stable today.

---

*End of audit.*
