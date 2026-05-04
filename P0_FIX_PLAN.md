# P0 Fix Plan

Repository: `cleaning-ticket-system`  
Plan date: 2026-05-04  
Scope: backend production blockers only. No UI redesign, reports, SLA, analytics, or optional product features.

## Implementation Order

1. **Test harness and permission fixtures** - create hermetic backend tests first so every production-blocker fix can be verified without seeded shell-test data.
2. **Multi-tenant/object-level permission fixes** - lock down customer/company/building/ticket scoping and action-level staff gates.
3. **Authentication and password reset** - enable refresh-token rotation/blacklisting, add server-side logout, login audit, brute-force controls, and password reset.
4. **Email notification foundation** - make email dispatch reliable and testable before password-reset and notification flows depend on it.
5. **Attachment security** - preserve private-media behavior, remove duplicated/fragile hidden-file rules, and add object-level regression coverage.
6. **Critical settings/security config** - fail fast for unsafe production env/config, tighten production defaults, and wire checks into CI/deploy validation.

## P0-1: Missing Permission Tests

### Current Problem

The backend has no Python-level tests. All `backend/*/tests.py` files are empty stubs, and the current validation relies on shell scripts that require a populated development database. That leaves object-level permissions, role-based state transitions, attachment access, and authentication behavior unprotected in CI.

### Exact Files To Edit

- `backend/requirements.txt`
- `backend/accounts/tests.py` or replace with `backend/accounts/tests/__init__.py`
- `backend/accounts/tests/test_auth.py`
- `backend/accounts/tests/test_permissions.py`
- `backend/accounts/tests/test_scoping.py`
- `backend/tickets/tests.py` or replace with `backend/tickets/tests/__init__.py`
- `backend/tickets/tests/test_scoping.py`
- `backend/tickets/tests/test_state_machine.py`
- `backend/tickets/tests/test_assignment.py`
- `backend/tickets/tests/test_attachments.py`
- `backend/tickets/tests/test_ticket_no.py`
- `backend/notifications/tests.py` or replace with `backend/notifications/tests/__init__.py`
- `backend/notifications/tests/test_email.py`
- `backend/config/tests/__init__.py`
- `backend/config/tests/test_settings_validator.py`
- `scripts/check_all.sh`

### Exact Tests To Add

- `backend/accounts/tests/test_auth.py`
  - `test_login_active_user_succeeds`
  - `test_login_inactive_user_fails`
  - `test_login_soft_deleted_user_fails`
  - `test_token_refresh_rotates_when_enabled`
  - `test_logout_blacklists_refresh_token`
  - `test_password_reset_request_sends_email_for_existing_active_user`
  - `test_password_reset_request_does_not_disclose_unknown_email`
  - `test_password_reset_confirm_rejects_weak_password`
  - `test_password_reset_confirm_sets_new_password`
- `backend/accounts/tests/test_scoping.py`
  - `test_me_returns_correct_scope_per_role`
  - `test_customer_user_scope_is_limited_to_memberships`
  - `test_company_admin_scope_is_limited_to_member_company`
  - `test_building_manager_scope_is_limited_to_assigned_buildings`
- `backend/accounts/tests/test_permissions.py`
  - `test_inactive_user_cannot_call_me`
  - `test_soft_deleted_user_cannot_call_me`
  - `test_cross_company_company_customer_building_lists_are_not_visible`
- `backend/tickets/tests/test_scoping.py`
  - `test_super_admin_sees_all_tickets`
  - `test_company_admin_only_sees_own_company_tickets`
  - `test_building_manager_only_sees_assigned_building_tickets`
  - `test_customer_only_sees_linked_customer_tickets`
  - `test_customer_cannot_view_internal_notes`
  - `test_search_does_not_leak_other_customer_tickets`
- `backend/tickets/tests/test_assignment.py`
  - `test_only_staff_can_assign`
  - `test_customer_assign_returns_403`
  - `test_customer_change_status_returns_403_for_staff_only_transition`
  - `test_assignee_must_be_building_manager`
  - `test_assignee_must_belong_to_ticket_building`
  - `test_customer_cannot_view_assignable_managers`
- `backend/tickets/tests/test_attachments.py`
  - `test_customer_cannot_upload_hidden_attachment_returns_400_or_403`
  - `test_customer_cannot_download_hidden_attachment_returns_403`
  - `test_attachment_outside_user_scope_returns_404`
  - `test_attachment_size_limit`
  - `test_attachment_mime_whitelist`
  - `test_attachment_filename_randomized_in_storage`
  - `test_download_uses_original_filename_in_response`
- `backend/tickets/tests/test_state_machine.py`
  - `test_allowed_transitions_by_role`
  - `test_disallowed_transitions_return_403`
  - `test_status_history_row_created_on_transition`
  - `test_timestamps_set_on_enter`
  - `test_concurrent_transition_detects_stale_status`
- `backend/tickets/tests/test_ticket_no.py`
  - `test_ticket_number_is_set_on_create`
  - `test_ticket_number_unique_under_concurrent_creation`
- `backend/notifications/tests/test_email.py`
  - `test_ticket_created_emails_only_staff_in_company`
  - `test_assignment_email_sent_on_change_only`
  - `test_actor_excluded_from_recipients`
  - `test_dedupe_users`
  - `test_email_failure_logs_failed_status`
- `backend/config/tests/test_settings_validator.py`
  - `test_missing_secret_key_in_prod_raises`
  - `test_missing_allowed_hosts_in_prod_raises`
  - `test_missing_cors_origins_in_prod_raises`
  - `test_insecure_throttle_defaults_in_prod_raise`

### Expected Behavior

Backend tests build their own companies, buildings, customers, users, memberships, tickets, messages, and attachments. Tests run from a clean database and do not depend on shell smoke-test seed data.

### Acceptance Criteria

- `python manage.py test` or `pytest` runs successfully from `backend/`.
- `scripts/check_all.sh` runs backend tests before shell smoke tests.
- Permission tests fail if a user can see or mutate data outside their role/object scope.
- Tests cover the P0 fixes in this plan before public production.

### Migration Impact

No schema migration is required for the test harness itself.

### Backward Compatibility Risks

Low. Shell scripts may expose assumptions that tests replace with explicit fixtures. CI/runtime requirements may change if `pytest-django` is used instead of Django's built-in test runner.

### Estimated Implementation Order

Implement first. Add fixtures/factories, then auth/scoping tests, then tickets/attachments/notifications/config tests.

## P0-2: Multi-Tenant And Object-Level Permissions

### Current Problem

Object scoping is centralized in `backend/accounts/scoping.py`, but several sensitive actions rely on serializers or state-machine rejection instead of explicit permission gates. Customer users can reach assignment/status endpoints and receive 400-style validation failures where the API should return 403. Building/customer/company list scoping needs regression tests to ensure users never enumerate objects outside their explicit memberships.

### Exact Files To Edit

- `backend/accounts/scoping.py`
- `backend/accounts/serializers.py`
- `backend/accounts/permissions.py`
- `backend/accounts/views.py`
- `backend/companies/views.py`
- `backend/buildings/views.py`
- `backend/customers/views.py`
- `backend/tickets/views.py`
- `backend/tickets/permissions.py`
- `backend/tickets/serializers.py`
- `backend/tickets/state_machine.py`
- `backend/accounts/tests/test_scoping.py`
- `backend/accounts/tests/test_permissions.py`
- `backend/tickets/tests/test_scoping.py`
- `backend/tickets/tests/test_assignment.py`
- `backend/tickets/tests/test_state_machine.py`

### Exact Tests To Add

- `test_cross_company_company_customer_building_lists_are_not_visible`
- `test_me_returns_correct_scope_per_role`
- `test_customer_user_scope_is_limited_to_memberships`
- `test_company_admin_scope_is_limited_to_member_company`
- `test_building_manager_scope_is_limited_to_assigned_buildings`
- `test_customer_only_sees_linked_customer_tickets`
- `test_customer_assign_returns_403`
- `test_customer_change_status_returns_403_for_staff_only_transition`
- `test_customer_cannot_view_assignable_managers`
- `test_disallowed_transitions_return_403`

### Expected Behavior

- Super admins can see all tenant objects.
- Company admins can only see companies, buildings, customers, tickets, users, and assignable managers inside companies where they have membership.
- Building managers can only see tickets/buildings assigned to them.
- Customer users can only see tickets for linked customers and must not perform staff-only actions.
- Staff-only actions return 403 before serializer validation or state-machine mutation logic runs.
- Cross-company object IDs return 404 for object-scoped resources when hiding existence is appropriate, and 403 for role-disallowed actions.

### Acceptance Criteria

- `/api/companies/`, `/api/buildings/`, `/api/customers/`, `/api/tickets/`, ticket messages, and ticket attachments are scoped consistently.
- `POST /api/tickets/{id}/assign/` returns 403 for customer users.
- Staff-only status transitions return 403 for customer users.
- `assignable-managers` is staff-only and scoped to the ticket building/company.
- `MeSerializer` does not expose broader company/building/customer ID lists than the user can query through the API.
- All new object-level permission tests pass.

### Migration Impact

No migration is expected unless the fix adds explicit membership tables or denormalized scope fields. The preferred fix should use existing models: `CompanyMembership`, `BuildingManagerAssignment`, and `CustomerUserMembership`.

### Backward Compatibility Risks

- Existing customer users may lose access to building metadata or customer rows they could previously enumerate.
- API consumers that expected 400 from staff-only endpoints will now receive 403.
- Any seeded/demo scripts that use overly broad accounts may need fixture adjustments.

### Estimated Implementation Order

Implement after the test harness. First add failing scope/action tests, then tighten scoping helpers, then add explicit view/action permission gates, then normalize 403/404 behavior.

## P0-3: Authentication And Password Reset

### Current Problem

JWT refresh tokens are not rotated or blacklistable, and logout only clears frontend storage. A leaked refresh token remains usable until expiry. There is no password reset flow, so account recovery requires Django admin or shell access. `LoginLog` exists but is not written, leaving no foundation for login audit or brute-force controls.

### Exact Files To Edit

- `backend/config/settings.py`
- `backend/config/urls.py`
- `backend/accounts/models.py`
- `backend/accounts/serializers.py`
- `backend/accounts/views.py`
- `backend/accounts/urls.py`
- `backend/accounts/auth.py`
- `backend/accounts/admin.py`
- `backend/accounts/migrations/0002_*.py`
- `backend/notifications/services.py`
- `backend/notifications/models.py`
- `backend/notifications/migrations/0002_*.py`
- `backend/accounts/tests/test_auth.py`
- `backend/accounts/tests/test_permissions.py`
- `backend/notifications/tests/test_email.py`
- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/api/client.ts`

### Exact Tests To Add

- `test_token_refresh_rotates_when_enabled`
- `test_logout_blacklists_refresh_token`
- `test_blacklisted_refresh_token_cannot_be_reused`
- `test_login_active_user_succeeds`
- `test_login_inactive_user_fails`
- `test_login_soft_deleted_user_fails`
- `test_login_success_writes_login_log`
- `test_login_failure_writes_login_log`
- `test_repeated_failed_login_is_throttled_or_locked`
- `test_password_reset_request_sends_email_for_existing_active_user`
- `test_password_reset_request_does_not_disclose_unknown_email`
- `test_password_reset_confirm_rejects_invalid_or_expired_token`
- `test_password_reset_confirm_rejects_weak_password`
- `test_password_reset_confirm_sets_new_password`

### Expected Behavior

- Refresh-token rotation is enabled.
- Old refresh tokens are blacklisted after rotation.
- `POST /api/auth/logout/` blacklists the supplied refresh token.
- Password reset request always returns a generic success response and never discloses whether an email exists.
- Password reset confirm validates token expiry, user state, and password policy before changing the password.
- Login success and failure write audit records with user/email, IP, user-agent, success flag, and reason where available.
- Repeated failed logins are throttled or locked per account and/or source IP.

### Acceptance Criteria

- `rest_framework_simplejwt.token_blacklist` is in `INSTALLED_APPS`.
- SimpleJWT settings include `ROTATE_REFRESH_TOKENS=True` and `BLACKLIST_AFTER_ROTATION=True`.
- Required migrations for token blacklist and any password-reset/login-audit changes are included.
- Logout invalidates refresh tokens server-side.
- Password reset emails use the shared email foundation and are covered by tests with mocked email delivery.
- Inactive and soft-deleted users cannot log in, refresh, reset passwords, or call authenticated endpoints.

### Migration Impact

- Django SimpleJWT blacklist migrations must be applied.
- Possible migration for `LoginLog` fields if the existing model cannot represent failures, reason, IP, or user-agent cleanly.
- Possible migration for a password-reset token model if Django's signed token generator is not sufficient.
- Possible migration for notification/email log fields if reset-email tracking is added.

### Backward Compatibility Risks

- Existing refresh tokens become invalid after deployment if blacklist/rotation behavior changes.
- API clients must handle rotated refresh tokens.
- Logout now requires sending the refresh token to the backend.
- Password policy enforcement may reject passwords that could previously be set through custom programmatic paths.

### Estimated Implementation Order

After permission fixes. Enable blacklist/rotation and migrations first, then logout, then login logging and lockout, then password reset endpoints, then frontend logout API call.

## P0-4: Email Notification Foundation

### Current Problem

Email sending is synchronous in `backend/notifications/services.py`. Slow or failing SMTP can block request/response paths such as ticket creation, assignment, and password reset. The project declares Redis/Celery dependencies but no worker is wired in production. Email failures need reliable logging and tests before authentication and notification flows depend on email.

### Exact Files To Edit

- `backend/config/settings.py`
- `backend/config/celery.py`
- `backend/config/__init__.py`
- `backend/notifications/services.py`
- `backend/notifications/models.py`
- `backend/notifications/apps.py`
- `backend/notifications/migrations/0002_*.py`
- `backend/notifications/tests/test_email.py`
- `backend/accounts/views.py`
- `backend/accounts/serializers.py`
- `backend/tickets/views.py`
- `backend/tickets/serializers.py`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `scripts/check_all.sh`
- `scripts/notification_email_test.sh`
- `docs/SMTP_AMAZON_SES.md`
- `docs/PRODUCTION_CHECKLIST.md`

### Exact Tests To Add

- `test_ticket_created_emails_only_staff_in_company`
- `test_assignment_email_sent_on_change_only`
- `test_actor_excluded_from_recipients`
- `test_dedupe_users`
- `test_password_reset_email_enqueued`
- `test_email_failure_logs_failed_status`
- `test_email_task_retries_transient_failure`
- `test_email_task_does_not_raise_to_api_request`

### Expected Behavior

- API requests enqueue email work and do not block on SMTP.
- Email recipients are scoped to the relevant company/building/customer object.
- The actor who triggered an event is not emailed about their own action.
- Duplicate recipients are removed.
- Delivery attempts and failures are logged.
- Password-reset emails use the same delivery foundation.

### Acceptance Criteria

- Production compose has a worker service if Celery is kept.
- Redis/Celery settings are explicit and environment-driven.
- In tests, email delivery is mocked and request paths do not call SMTP directly.
- Ticket creation, assignment, and password reset still succeed when email delivery fails after enqueue.
- Notification logs record queued/sent/failed states.

### Migration Impact

- Possible migration to add queue/task status, failure reason, or event type fields to notification logs.
- No ticket/account schema migration is expected unless email event references are normalized.

### Backward Compatibility Risks

- Operators must run the worker in production; otherwise emails will queue but not send.
- Existing scripts that expect synchronous email side effects may need to wait for tasks or run Celery eagerly in test mode.
- Email timing changes from immediate send to eventual delivery.

### Estimated Implementation Order

Implement before password-reset email is considered production-ready. First isolate email service APIs, then add logging tests, then Celery worker/task wiring, then update ticket/auth callers.

## P0-5: Attachment Security

### Current Problem

Production correctly avoids public `/media/` serving and uses authenticated attachment downloads, but access-control rules are split across views and serializers. Hidden attachment upload is both coerced in the view and rejected in the serializer, creating brittle behavior. Hidden attachment download is checked, but it needs Python regression tests. Attachment size, MIME, filename randomization, original filename response, and out-of-scope download behavior must be locked down.

### Exact Files To Edit

- `backend/tickets/models.py`
- `backend/tickets/serializers.py`
- `backend/tickets/views.py`
- `backend/tickets/permissions.py`
- `backend/tickets/tests/test_attachments.py`
- `backend/config/settings.py`
- `backend/config/urls.py`
- `frontend/nginx.conf`
- `docs/MEDIA_STORAGE.md`
- `docs/SECURITY_REVIEW.md`
- `scripts/attachment_api_test.sh`
- `scripts/attachment_download_test.sh`
- `scripts/attachment_file_type_test.sh`

### Exact Tests To Add

- `test_customer_cannot_upload_hidden_attachment_returns_400_or_403`
- `test_customer_cannot_download_hidden_attachment_returns_403`
- `test_attachment_outside_user_scope_returns_404`
- `test_attachment_size_limit`
- `test_attachment_mime_whitelist`
- `test_attachment_filename_randomized_in_storage`
- `test_download_uses_original_filename_in_response`
- `test_private_media_not_served_by_urlpatterns_in_production`
- `test_hidden_attachments_not_listed_for_customer`

### Expected Behavior

- Attachments are always accessed through authenticated API endpoints.
- Customers cannot create hidden attachments or internal-only files.
- Customers cannot list or download hidden attachments.
- Out-of-scope attachment IDs do not disclose cross-tenant existence.
- Upload size and MIME allowlist are enforced server-side.
- Stored filenames are randomized; download responses use safe original filenames.
- Production does not expose `MEDIA_ROOT` through static URL routes.

### Acceptance Criteria

- One authoritative layer enforces hidden-upload rules, preferably serializer validation plus view-level object scope.
- Download view checks both ticket scope and hidden flag.
- Attachment list view filters hidden files for non-staff users.
- Nginx body size remains aligned with backend max upload size.
- All attachment tests pass without relying on shell scripts.

### Migration Impact

No migration is expected unless the plan changes attachment metadata fields. If MIME/content-type or checksum fields are added for stronger validation, add a migration.

### Backward Compatibility Risks

- Previously uploaded files with disallowed MIME metadata may become inaccessible if validation is applied retroactively.
- API clients attempting to set `is_hidden` as customer users will receive a consistent rejection instead of mixed coercion/validation behavior.
- Tightening Nginx/body limits may reject borderline uploads that previously reached Django.

### Estimated Implementation Order

After auth and email foundations. Add tests first, normalize hidden-upload enforcement, then verify download/list/object-scope behavior and production media routing.

## P0-6: Critical Settings And Security Config

### Current Problem

Production settings only fail fast on missing `DJANGO_SECRET_KEY` when `DEBUG=False`. Critical values such as `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, throttle rates, and secure proxy/SSL settings can be omitted or left unsafe. The repository has `scripts/prod_env_check.sh`, but it only helps when an operator remembers to run it.

### Exact Files To Edit

- `backend/config/settings.py`
- `backend/config/apps.py`
- `backend/config/checks.py`
- `backend/config/tests/__init__.py`
- `backend/config/tests/test_settings_validator.py`
- `backend/requirements.txt`
- `.env.production.example`
- `scripts/prod_env_check.sh`
- `scripts/check_all.sh`
- `docker-compose.prod.yml`
- `docs/PRODUCTION_CHECKLIST.md`
- `docs/GO_LIVE.md`
- `docs/SECURITY_REVIEW.md`
- `frontend/nginx.conf`

### Exact Tests To Add

- `test_missing_secret_key_in_prod_raises`
- `test_missing_allowed_hosts_in_prod_raises`
- `test_missing_cors_origins_in_prod_raises`
- `test_missing_csrf_trusted_origins_in_prod_raises`
- `test_insecure_throttle_defaults_in_prod_raise`
- `test_debug_false_requires_secure_ssl_redirect_or_proxy_ssl_header`
- `test_prod_env_check_fails_on_placeholder_secret`

### Expected Behavior

- Production boot fails for missing or placeholder critical settings.
- Production defaults are conservative even when env vars are omitted.
- Auth token throttles are strict by default.
- CORS and CSRF trusted origins are explicit in production.
- Security headers and upload limits are documented and consistent between Django and Nginx.

### Acceptance Criteria

- A Django system check or settings validator runs during startup/checks and fails with actionable messages.
- `scripts/check_all.sh` runs the validator.
- `docker-compose.prod.yml` runs or documents the environment check before serving traffic.
- `.env.production.example` contains no insecure production defaults.
- Tests prove unsafe production configurations fail.

### Migration Impact

No database migration is expected.

### Backward Compatibility Risks

- Existing production deploys with incomplete environment variables may fail to boot until configured correctly.
- Local development must keep `DEBUG=True` or explicitly opt into relaxed dev defaults.
- Stricter throttles may affect scripts that rapidly call auth endpoints.

### Estimated Implementation Order

Implement last, after auth/email settings are known. Add validator tests, implement checks, update env examples/scripts/docs, then verify production compose configuration.

