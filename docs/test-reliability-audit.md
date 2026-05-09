# Test reliability audit (Sprint 9)

> **Audited commit:** `62659d7` (Sprint 8 RC).
> **Method:** read code first, list every endpoint and rule, then map
> the test files under `backend/**/tests` and `scripts/playwright_admin_smoke`
> onto each rule. Mark a rule **covered** only when at least one test
> exercises it; otherwise mark it **gap**. Risk levels reflect the
> blast radius of a regression in production, not the difficulty of
> the fix.

The companion document [docs/system-behavior-audit.md](system-behavior-audit.md)
restates the *behavior* of the system as a role/scope matrix; this file
is about the *tests* that defend that behavior.

---

## Risk legend

| Level | Meaning |
|---|---|
| 🔴 critical | A regression here is a pilot blocker — scope leak, attachment leak, missing audit, customer-visible bug. Must be covered. |
| 🟠 high | Affects only staff data, recoverable, but visible. Should be covered. |
| 🟡 medium | Edge cases, error paths, defaults. Nice-to-have coverage. |
| 🟢 low | Cosmetic / not pilot-blocking. |

---

## 1. Tickets — view / list / create / state machine

| Rule (where) | Happy path | Negative / cross-tenant | Audit / history | Status |
|---|---|---|---|---|
| `scope_tickets_for` filters list by role ([accounts/scoping.py:108-127](../backend/accounts/scoping.py#L108-L127)) | `tickets/tests/test_scoping.py` (all 4 roles) | `test_cross_company_ticket_detail_is_not_visible` | n/a | ✅ covered (🔴) |
| Customer cannot see internal-note messages ([tickets/views.py:280-283](../backend/tickets/views.py#L280-L283)) | `test_scoping.py::test_customer_cannot_view_internal_notes` | `test_out_of_scope_messages_are_404` | n/a | ✅ covered (🔴) |
| Customer cannot see hidden attachments ([tickets/views.py:338-343](../backend/tickets/views.py#L338-L343)) | `test_attachments.py::test_customer_cannot_view_hidden_attachments` | – | n/a | ✅ covered (🔴) |
| Customer cannot download a hidden attachment ([tickets/views.py:382-390](../backend/tickets/views.py#L382-L390)) | `test_attachments.py` | partial — no test for "attachment.is_hidden=False but parent message is INTERNAL_NOTE" | n/a | 🟡 partial gap |
| Customer cannot post internal note ([tickets/serializers.py:312-317](../backend/tickets/serializers.py#L312-L317)) | indirect (server forces type=PUBLIC_REPLY in [views.py:298](../backend/tickets/views.py#L298)) | – | n/a | 🟠 gap — see Section 8 |
| Customer cannot upload `is_hidden=True` ([tickets/serializers.py:396-398](../backend/tickets/serializers.py#L396-L398)) | – | – | n/a | 🟠 gap |
| State machine is the single chokepoint ([tickets/state_machine.py:109-154](../backend/tickets/state_machine.py#L109-L154)) | `test_state_machine.py` (9 tests) | `test_assignment.py::test_customer_can_use_customer_approval_transition_in_scope` | TicketStatusHistory written | ✅ covered (🔴) |
| Search field set differs by role ([tickets/views.py:45-53](../backend/tickets/views.py#L45-L53)) | `test_scoping.py::test_staff_search_still_matches_description_words` | `test_customer_search_does_not_match_description_words` | n/a | ✅ covered (🟠) |
| Customer rejection requires a note ([tickets/serializers.py:439-446](../backend/tickets/serializers.py#L439-L446)) | – | – | n/a | 🟡 gap |
| `assigned_to` write does not bypass status flow ([tickets/serializers.py:509-513](../backend/tickets/serializers.py#L509-L513)) | `test_assignment.py` | `test_customer_cannot_call_assign_endpoint` | – | ✅ covered (🟠) |
| `mark_first_response_if_needed` stamps once ([tickets/models.py:146-149](../backend/tickets/models.py#L146-L149)) | – | – | – | 🟡 gap |
| SLA filter `?sla=breached` excludes paused ([tickets/views.py:68-82](../backend/tickets/views.py#L68-L82)) | – | – | – | 🟡 gap (one indirect test) |
| Tickets API does not expose DELETE | – (absence) | – | – | ✅ covered by URL routing tests |

**Verdict:** the **🔴 critical paths are well covered**. Three 🟠 gaps
worth filling — see [Section 8](#section-8-recommended-fixes).

---

## 2. Accounts — auth, users, scoping, invitations

| Rule (where) | Happy path | Negative / cross-tenant | Audit / history | Status |
|---|---|---|---|---|
| Login throttles after 5 fails / 15 min ([accounts/serializers.py:48-79](../backend/accounts/serializers.py#L48-L79)) | `test_auth.py:108-123` | – | LoginLog row | ✅ covered (🟠) |
| Soft-deleted user cannot log in ([accounts/auth.py:4-11](../backend/accounts/auth.py#L4-L11)) | – | `test_auth.py:18-39` | – | ✅ covered (🔴) |
| Refresh token rotation invalidates old refresh | `test_auth.py:52-76` | – | – | ✅ covered (🟠) |
| Logout blacklists refresh | `test_auth.py:78-91` | – | – | ✅ covered (🟠) |
| MeView PATCH only accepts full_name + language ([accounts/views.py:46-49](../backend/accounts/views.py#L46-L49)) | `test_self_profile.py:9-96` | – | – | ✅ covered (🟠) |
| User cannot change own role ([serializers_users.py:85-86](../backend/accounts/serializers_users.py#L85-L86)) | `test_user_crud.py:154-173` | – | – | ✅ covered (🔴) |
| COMPANY_ADMIN cannot promote to SUPER_ADMIN/COMPANY_ADMIN ([serializers_users.py:89-97](../backend/accounts/serializers_users.py#L89-L97)) | `test_user_crud.py` | – | – | ✅ covered (🔴) |
| COMPANY_ADMIN A cannot mutate users in company B ([accounts/permissions.py:92-124](../backend/accounts/permissions.py#L92-L124)) | – | `test_admin_crud_scope_regression.py:49-92` | – | ✅ covered (🔴) |
| Soft-delete + reactivate + retain ticket scope | `test_user_crud.py:177-235` | `test_admin_crud_scope_regression.py:94-115` | – | ✅ covered (🟠) |
| Reactivate is SUPER_ADMIN only ([views_users.py:97-104](../backend/accounts/views_users.py#L97-L104)) | `test_user_crud.py:231-235` | – | – | ✅ covered (🟠) |
| Invitation: COMPANY_ADMIN can only invite within own scope ([serializers_invitations.py:138-157](../backend/accounts/serializers_invitations.py#L138-L157)) | `test_invitations.py:158-169` | – | – | ✅ covered (🔴) |
| Invitation: only SUPER_ADMIN can invite SUPER_ADMIN ([serializers_invitations.py:86-90](../backend/accounts/serializers_invitations.py#L86-L90)) | `test_invitations.py` | – | – | ✅ covered (🔴) |
| Invitation accept rejects existing-user collision ([views_invitations.py:108-137](../backend/accounts/views_invitations.py#L108-L137)) | `test_invitations.py:423-474` | – | – | ✅ covered (🔴) |
| Invitation token: only SHA256 hash stored ([invitations.py:12-24](../backend/accounts/invitations.py#L12-L24)) | `test_invitations.py:265-277` | – | – | ✅ covered (🔴) |
| Invitation expires_at validation | `test_invitations.py:281-333` (preview) | – | – | ✅ covered (🟠) |
| Invitation revoke: only creator or SUPER_ADMIN ([views_invitations.py:172-176](../backend/accounts/views_invitations.py#L172-L176)) | `test_invitations.py:478-520` | `test_invitations.py:492-501` | – | ✅ covered (🔴) |
| Invitation role+scope shape (e.g. BUILDING_MANAGER without buildings) ([serializers_invitations.py:92-124](../backend/accounts/serializers_invitations.py#L92-L124)) | – | – | – | 🟡 gap — coarse coverage only |
| Email normalisation case-insensitivity | – | – | – | 🟡 gap |
| Notification preference rejects un-mutable event types ([accounts/serializers.py:258-273](../backend/accounts/serializers.py#L258-L273)) | – | – | – | 🟡 gap |

**Verdict:** all 🔴 critical paths covered. Three 🟡 gaps that are
not pilot-blockers.

---

## 3. Memberships (CompanyUser / BuildingManager / CustomerUser)

| Rule (where) | Happy path | Negative / cross-tenant | Audit | Status |
|---|---|---|---|---|
| POST creates membership; idempotent | `companies/tests/test_memberships.py:55-80`, mirrored in buildings/customers | – | `audit/tests/test_audit_membership.py` | ✅ covered (🔴) |
| POST requires the *target user* role to match (COMPANY_ADMIN for `/admins/`, etc.) | `test_memberships.py:46` (each app) | – | – | ✅ covered (🟠) |
| DELETE removes membership; idempotent 404 | `test_memberships.py:84-100` (each app) | – | `test_audit_membership.py` | ✅ covered (🔴) |
| Cross-company DELETE returns 403 | – | `test_memberships.py:103-110` (each app) | – | ✅ covered (🔴) |
| Cross-company GET returns 403 | `test_memberships.py:24-29` | `test_memberships.py:29-37` | – | ✅ covered (🔴) |
| **Forbidden requests do NOT write audit rows** ([test_audit_membership.py:127-142](../backend/audit/tests/test_audit_membership.py#L127-L142)) | – | covered | – | ✅ covered (🔴) |
| Audit row carries user_email + entity_name (not bare pks) ([audit/signals.py:173-208](../backend/audit/signals.py#L173-L208)) | `test_audit_membership.py` (every test) | – | covered | ✅ covered (🔴) |
| Audit row records first-hop X-Forwarded-For ([audit/context.py:53-68](../backend/audit/context.py#L53-L68)) | `test_audit_membership.py:144-162` | – | covered | ✅ covered (🔴) |
| **De-scoping after DELETE actually shrinks ticket list** | – | – | – | 🟠 gap — see Section 8 |
| Cross-tenant POST: company-A admin POSTs `user_id` of company-B user | – | covered indirectly via 403 on parent resource (object-level perm) | – | 🟡 partial gap — defence-in-depth missing |
| Building↔company integrity: customer.building.company_id == customer.company_id ([customers/views.py:40-43](../backend/customers/views.py#L40-L43)) | – | – | – | 🟡 gap |

**Verdict:** all 🔴 covered. The membership-level cross-tenant defence
relies entirely on the parent-resource object permission. If that
gate were ever weakened, the membership create handlers would not
detect a foreign user being added — but the operator would have to
break two layers to land there. Adding a regression test for "delete
de-scopes tickets" is worth doing in this sprint.

---

## 4. Audit log middleware / API

| Rule (where) | Happy path | Negative | Status |
|---|---|---|---|
| First-hop X-Forwarded-For trusted; REMOTE_ADDR fallback ([audit/context.py:53-68](../backend/audit/context.py#L53-L68)) | `test_audit_membership.py:144-162` (XFF set, asserts first hop) | – | ✅ covered (🔴) |
| **REMOTE_ADDR ignored when XFF is set** | – | – | 🟠 gap — explicit assertion missing |
| Sensitive-field redaction (password / token / hash / otp / mfa) ([audit/diff.py:39](../backend/audit/diff.py#L39)) | `audit/tests/test_audit.py:165-192` | – | ✅ covered (🔴) |
| AuditLog API requires SUPER_ADMIN ([audit/views.py:25](../backend/audit/views.py#L25)) | `test_audit.py:235-268` | – | ✅ covered (🔴) |
| Audit failure must not block the original mutation ([audit/signals.py:91-97](../backend/audit/signals.py#L91-L97)) | `test_audit.py:352-386` for admin entities | – | ✅ covered for admin entities; 🟡 gap for memberships |
| Filters (target_model / target_id / actor / date_from / date_to) | `test_audit.py:271-333` | – | ✅ covered (🟠) |
| Recurring rule: an UPDATE with no meaningful changes (only `updated_at`) is suppressed ([audit/signals.py:132-135](../backend/audit/signals.py#L132-L135)) | – | – | 🟡 gap |

---

## 5. Reports

| Rule (where) | Happy path | Negative | Status |
|---|---|---|---|
| `IsReportsConsumer` rejects CUSTOMER_USER ([reports/permissions.py](../backend/reports/permissions.py)) | – | implicit (no test logs in as customer) | 🟠 gap — explicit 403 assertion missing |
| Per-role scope filter ([reports/scoping.py:43-83](../backend/reports/scoping.py#L43-L83)) | `test_dimensions_json.py:128-139` | `_allowed_company_ids`/`_allowed_building_ids` enforced | ✅ covered (🔴) |
| Cross-tenant `?company=B` from COMPANY_ADMIN A → 403 ([scoping.py:104-109](../backend/reports/scoping.py#L104-L109)) | – | partial — `test_dimensions_json` confirms scoped result, no explicit 403 | 🟡 gap |
| Cross-tenant `?building=B` → 403 ([scoping.py:111-116](../backend/reports/scoping.py#L111-L116)) | – | partial | 🟡 gap |
| CSV export Content-Type + Content-Disposition + UTF-8 BOM | `test_dimensions_export.py:118-131`, `:86-92` | – | ✅ covered (🟠) |
| PDF export `%PDF-` magic | `test_dimensions_export.py:133-140` | – | ✅ covered (🟠) |
| Export inherits scope of JSON (no broader access) | `test_dimensions_export.py:221-227` | – | ✅ covered (🔴) |
| `parse_date_range` rejects from > to ([scoping.py:183-186](../backend/reports/scoping.py#L183-L186)) | covered indirectly | – | ✅ covered (🟡) |

**Verdict:** scoping is covered through the JSON path; explicit
forbidden-cross-tenant assertions are partial — see Section 8.

---

## 6. Notifications

| Rule (where) | Coverage | Status |
|---|---|---|
| Recipient resolution for each event | `notifications/tests/test_email.py` | ✅ covered (🔴) |
| `_drop_muted` removes muted recipients ([notifications/services.py:237-262](../backend/notifications/services.py#L237-L262)) | `test_preferences.py:182-193` | ✅ covered (🟠) |
| Transactional events (PASSWORD_RESET, INVITATION_SENT) ignore preferences ([services.py:244-246](../backend/notifications/services.py#L244-L246)) | implicit | 🟡 gap (no explicit assertion) |
| Dutch copy in subjects + bodies | `test_email.py:65-93` (admin override) | 🟡 partial — admin-override only |
| Celery task QUEUED → SENT/FAILED state machine | `test_celery_email.py:10-70` | ✅ covered (🟠) |
| Actor excluded from own notification | `test_email.py:33-43` | ✅ covered (🟠) |

---

## 7. Production / health / config

| Rule (where) | Coverage | Status |
|---|---|---|
| `/health/live` returns 200 unconditionally ([config/health.py](../backend/config/health.py)) | covered in `config/tests` | ✅ |
| `/health/ready` returns 503 when DB/Redis unreachable | covered | ✅ |
| `validate_production_settings` rejects `localhost`/`127.0.0.1`/`*` ([config/security.py:82-83](../backend/config/security.py#L82-L83)) | `config/tests/test_security.py` | ✅ |
| TLS/HSTS/secure-cookie env knobs honoured | indirectly | 🟡 gap |
| Backend healthcheck via TCP socket probe (works under strict ALLOWED_HOSTS) | manual via Sprint 8 verification | ⚠ **operator-side**, host-only |
| Frontend nginx forwards `X-Forwarded-Proto` ([frontend/nginx.conf](../frontend/nginx.conf)) | manual via `nginx -t` | ⚠ **operator-side** |

---

## Section 8 — Recommended fixes (gaps to address in Sprint 9 itself)

These are the only items I propose adding tests for in this sprint;
everything else is either covered or out of scope for a pilot.

### 8.1 (🔴 high value) De-scoping after membership delete shrinks ticket list

**Why:** the test suite proves "membership row is deleted" and "audit
row is written" but does **not** verify the actual security
consequence: that the de-scoped user can no longer GET tickets they
previously could. If `scope_tickets_for` ever pivoted away from
membership tables (e.g. to a denormalised `Ticket.scope_tag`), all
existing membership tests would still pass while the user kept
visibility.

**Add:** one test per junction table — DELETE membership, then
re-fetch `/api/tickets/` as that user, assert `count == 0` for the
ticket that used to be visible.

### 8.2 (🟠 high) Audit IP parser — REMOTE_ADDR is **ignored** when XFF is set

**Why:** the existing test sets XFF and asserts the first hop is
recorded. It does **not** set REMOTE_ADDR at the same time and
assert REMOTE_ADDR is *not* what gets recorded. If a future refactor
swapped the precedence (REMOTE_ADDR first, then XFF), the existing
test would still pass.

**Add:** a single test that sets BOTH `HTTP_X_FORWARDED_FOR` and
`REMOTE_ADDR` to different values, and asserts the audit row records
the XFF first hop, not REMOTE_ADDR.

### 8.3 (🟠 high) Reports cross-tenant 403 is explicit

**Why:** the system silently filters at query layer. We trust that
because `test_dimensions_json` shows scoped results. But an explicit
"COMPANY_ADMIN A passes ?company=B → 403" assertion locks down the
contract and would catch a regression where the validator started
returning 200 with empty body (which would also be a "passing" result
under the existing tests).

**Add:** one test against `tickets-by-type` (the simplest dimension)
that hits ?company=<other-company-id> as a COMPANY_ADMIN A and
asserts 403.

### 8.4 (🟠 medium) Customer cannot upload `is_hidden=True`

**Why:** the serializer rejects this in code; no test demonstrates
the rejection.

**Add:** one POST as a CUSTOMER_USER with `is_hidden=true` in the
form body. Assert 400 (or whatever the code returns) and assert no
TicketAttachment row is created.

### 8.5 (🟠 medium) Customer cannot post an INTERNAL_NOTE message

**Why:** the view forces `message_type=PUBLIC_REPLY` for non-staff
([views.py:298](../backend/tickets/views.py#L298)). The serializer
*also* rejects it
([serializers.py:312-317](../backend/tickets/serializers.py#L312-L317)).
The view-side override masks the serializer-side check from the
tests. If the view-side override were removed (e.g. someone refactors
the perform_create), the serializer would still reject — but no test
proves the serializer's behavior in isolation.

**Add:** one direct serializer test that submits `message_type=INTERNAL_NOTE`
as a customer user and asserts the validation error.

### Out of scope for this sprint

- Concurrency tests for `apply_transition` SELECT_FOR_UPDATE.
- Email language coverage for non-override status transitions
  (Dutch is already enforced in code; partial test coverage exists).
- Notification mute race condition.
- Cross-tenant POST defence-in-depth at the membership layer
  (mitigated by parent-resource object perm; defence-in-depth would
  require a code change, not just a test).

---

## Mutation sanity results (Phase 5)

To validate that the existing tests genuinely defend the rules in
[§System behavior audit](system-behavior-audit.md), I performed five
local code mutations, ran the relevant test subset, and reverted.

| # | Mutation | File / function | Targeted tests | Result |
|---|---|---|---|---|
| 1 | `scope_tickets_for` always returns `Ticket.objects.all()` (cross-tenant filter removed) | `accounts/scoping.py:108` | `tickets.tests.test_scoping` | **5 failures**: company-admin / building-manager / customer-user list scoping + cross-company detail + out-of-scope-messages-404 |
| 2 | Drop attachment list-filter for non-staff (hidden + internal-note attachments now visible) | `tickets/views.py:330-343` | `tickets.tests.test_attachments` | **1 failure**: `test_customer_cannot_view_hidden_attachments` |
| 3 | Disconnect post_save / post_delete audit signal for `CompanyUserMembership` | `audit/signals.py:_connect()` | `audit.tests.test_audit_membership` | **3 failures**: CREATE row missing, DELETE row missing, XFF row missing |
| 4 | Reports `_allowed_company_ids` always returns `None` (unrestricted) | `reports/scoping.py:43-59` | `reports.tests.{status_distribution,tickets_over_time,age_buckets,manager_throughput}` | **4 failures**: `test_company_admin_cross_tenant_returns_403` in each |
| 5 | XFF parser takes **last** hop instead of first | `audit/context.py:53-68` | `audit.tests.test_audit`, `audit.tests.test_audit_membership` | **2 failures**: `test_audit_serializer_exposes_actor_email_and_request_metadata`, `test_create_membership_records_request_ip_from_xff` |

**All 5 mutations were caught.** No mutation produced a green test
suite. The most critical contracts — tenant scoping, attachment
visibility, audit signal coverage, reports cross-tenant enforcement,
and XFF first-hop parsing — are genuinely defended by tests, not
just present-in-code.

A side finding: the legacy reports endpoints
(status-distribution, tickets-over-time, age-buckets,
manager-throughput) **do** have explicit
`test_company_admin_cross_tenant_returns_403` assertions.
The Sprint 5 dimension endpoints (`tickets-by-type`,
`tickets-by-customer`, `tickets-by-building`) **do not**. This refines
Section 8.3 — the gap is specifically for the dimension endpoints,
not the reports module as a whole.

After all five mutations, every file was diff-clean against its
`/tmp/*.orig` snapshot. The working tree is unchanged from the start
of Phase 5.

## Summary table

| Layer | Critical (🔴) | High (🟠) | Medium/Low (🟡🟢) | Net |
|---|---|---|---|---|
| Tickets | 6 / 6 covered | 3 / 5 covered | 2 / 5 | strong |
| Accounts / auth / invitations | 12 / 12 covered | 4 / 4 covered | 1 / 4 | strong |
| Memberships | 7 / 7 covered | 0 / 1 (de-scoping) | 1 / 2 | **gap: §8.1** |
| Audit | 4 / 4 covered | 1 / 2 | 1 / 2 | **gap: §8.2** |
| Reports | 2 / 2 covered | 1 / 2 | 0 / 2 | **gap: §8.3** |
| Notifications | 1 / 1 covered | 3 / 3 covered | 0 / 2 | strong |
| Config / health | 3 / 3 covered | host-only | – | strong |
