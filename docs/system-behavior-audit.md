# System behavior audit (Sprint 9)

> **Audited commit:** `62659d7` (Sprint 8 RC).
> **Purpose:** restate, from the **current code**, the rules the
> system actually enforces — independent of what the tests claim.
> The companion document
> [docs/test-reliability-audit.md](test-reliability-audit.md) maps
> these rules onto the test suite. This file is the *contract*
> against which the operator can verify pilot behaviour by hand.

---

## Roles

| Role | Scope basis | Notes |
|---|---|---|
| `SUPER_ADMIN` | global | global read/write across all tenants |
| `COMPANY_ADMIN` | `CompanyUserMembership` | one or more companies |
| `BUILDING_MANAGER` | `BuildingManagerAssignment` | one or more buildings |
| `CUSTOMER_USER` | `CustomerUserMembership` | one or more customer-locations (a customer row is a customer-LOCATION, not a global account) |

A user is "active" when `is_active=True` AND `deleted_at IS NULL`
([accounts/permissions.py:6-15](../backend/accounts/permissions.py#L6-L15)).
JWT auth rejects any token whose user is no longer active
([accounts/auth.py:4-11](../backend/accounts/auth.py#L4-L11)).

---

## 1. Role capability matrix

| Action | SUPER_ADMIN | COMPANY_ADMIN | BUILDING_MANAGER | CUSTOMER_USER |
|---|---|---|---|---|
| Login | ✅ | ✅ | ✅ | ✅ |
| Edit own `full_name` / `language` | ✅ | ✅ | ✅ | ✅ |
| Edit own `role` | ❌ | ❌ | ❌ | ❌ |
| Change own password | ✅ | ✅ | ✅ | ✅ |
| Manage notification preferences | ✅ | ✅ | ✅ | ✅ |
| List users | ✅ all | ✅ in scope | ❌ | ❌ |
| Invite a user | ✅ any role | ✅ within own companies, never SUPER_ADMIN nor COMPANY_ADMIN | ❌ | ❌ |
| Promote user to SUPER_ADMIN | ✅ | ❌ | ❌ | ❌ |
| Promote user to COMPANY_ADMIN | ✅ | ❌ | ❌ | ❌ |
| Soft-delete user | ✅ | ✅ in scope | ❌ | ❌ |
| Reactivate soft-deleted user | ✅ | ❌ | ❌ | ❌ |
| Manage Companies (CRUD) | ✅ | read-only own | read-only own (via membership) | ❌ |
| Manage Buildings | ✅ | ✅ in own company | read-only own | ❌ |
| Manage Customers | ✅ | ✅ in own company | read-only own | ❌ |
| Add CompanyUserMembership | ✅ | ✅ for own company | ❌ | ❌ |
| Add BuildingManagerAssignment | ✅ | ✅ for own building | ❌ | ❌ |
| Add CustomerUserMembership | ✅ | ✅ for own customer | ❌ | ❌ |
| Create ticket | ✅ | ✅ in scope | ✅ in scope | ✅ in scope |
| List own-scope tickets | ✅ all | ✅ company tickets | ✅ building tickets | ✅ customer tickets |
| View internal notes | ✅ | ✅ | ✅ | ❌ |
| Post internal note | ✅ | ✅ | ✅ | ❌ |
| Post public reply | ✅ | ✅ | ✅ | ✅ |
| Upload public attachment | ✅ | ✅ | ✅ | ✅ |
| Upload hidden attachment | ✅ | ✅ | ✅ | ❌ |
| OPEN → IN_PROGRESS | ✅ | ✅ company | ✅ building | ❌ |
| IN_PROGRESS → WAITING_CUSTOMER_APPROVAL | ✅ | ✅ company | ✅ building | ❌ |
| WAITING_CUSTOMER_APPROVAL → APPROVED | ✅ | ✅ company (admin override) | ❌ | ✅ own customer |
| WAITING_CUSTOMER_APPROVAL → REJECTED | ✅ | ✅ company (admin override) | ❌ | ✅ own customer (note required) |
| REJECTED → IN_PROGRESS (retake) | ✅ | ✅ company | ✅ building | ❌ |
| APPROVED → CLOSED | ✅ | ✅ company | ❌ | ❌ |
| CLOSED → REOPENED_BY_ADMIN | ✅ | ✅ company | ❌ | ❌ |
| Assign manager to ticket | ✅ | ✅ company | ✅ own building | ❌ |
| List assignable managers | ✅ | ✅ | ✅ | ❌ |
| Read reports | ✅ | ✅ company | ✅ building | ❌ (403) |
| Export CSV / PDF | ✅ | ✅ | ✅ | ❌ |
| Read audit log (`/api/audit-logs/`) | ✅ | ❌ | ❌ | ❌ |

References: `accounts/permissions.py`, `accounts/scoping.py`,
`tickets/permissions.py`, `tickets/state_machine.py`,
`reports/permissions.py`, `audit/views.py`.

---

## 2. Data scope matrix

The queryset for each list endpoint is filtered by:

| Endpoint | SUPER_ADMIN | COMPANY_ADMIN | BUILDING_MANAGER | CUSTOMER_USER |
|---|---|---|---|---|
| `GET /api/companies/` | all | own (`CompanyUserMembership`) + active | derived from `BuildingManagerAssignment.building.company` + active | derived from `CustomerUserMembership.customer.company` + active |
| `GET /api/buildings/` | all | buildings in own companies + active | direct assignment + active | derived from `customer.building` + active |
| `GET /api/customers/` | all | customers in own companies + active | customers in own buildings + active | direct membership + active |
| `GET /api/users/` | all | union of users across own companies (admins, managers in own buildings, customer-users in own customers) | (403) | (403) |
| `GET /api/tickets/` | all | `Ticket.company_id IN ids` | `Ticket.building_id IN ids` | `Ticket.customer_id IN ids` |
| `GET /api/audit-logs/` | all | (403) | (403) | (403) |
| `GET /api/reports/*` | all | scoped via `_allowed_company_ids` | scoped via `_allowed_building_ids` | (403) |

**Important:** `scope_*_for(user)` (with the `scope_` prefix) hides
`is_active=False` rows for non-SUPER_ADMIN. SUPER_ADMIN sees inactive
rows too. This applies to companies / buildings / customers; tickets
themselves are *not* soft-deleted.

References: [accounts/scoping.py:73-127](../backend/accounts/scoping.py#L73-L127),
[reports/scoping.py:43-83](../backend/reports/scoping.py#L43-L83).

---

## 3. Attachment visibility matrix

For a single attachment row, with parent message having
`is_hidden`/`message_type`, what does each role see?

| Attachment.is_hidden | Parent message | SUPER_ADMIN | COMPANY_ADMIN | BUILDING_MANAGER | CUSTOMER_USER |
|---|---|---|---|---|---|
| False | none / PUBLIC_REPLY | listed + downloadable | listed + downloadable | listed + downloadable | listed + downloadable |
| True | none / PUBLIC_REPLY | listed + downloadable | listed + downloadable | listed + downloadable | **hidden** (filtered out + 403 on direct download) |
| False | INTERNAL_NOTE | listed + downloadable | listed + downloadable | listed + downloadable | **hidden** |
| True | INTERNAL_NOTE | listed + downloadable | listed + downloadable | listed + downloadable | **hidden** |
| any | message.is_hidden=True | staff visible | staff visible | staff visible | **hidden** |

Logic: [tickets/views.py:330-343](../backend/tickets/views.py#L330-L343)
(list filter), [tickets/views.py:367-399](../backend/tickets/views.py#L367-L399)
(direct download check).

Customer users **cannot upload** an attachment with `is_hidden=True`
([tickets/serializers.py:392-401](../backend/tickets/serializers.py#L392-L401))
and **cannot post** an INTERNAL_NOTE message
([tickets/serializers.py:312-317](../backend/tickets/serializers.py#L312-L317);
view also forces `message_type=PUBLIC_REPLY` at
[views.py:298](../backend/tickets/views.py#L298)).

File-type whitelist: `.jpg .jpeg .png .webp .pdf .heic .heif`
([tickets/serializers.py:57-78](../backend/tickets/serializers.py#L57-L78)).
Maximum size: 10 MB. MIME type validated.

Stored filename is randomised; `original_filename` is preserved for
download (`Content-Disposition: attachment; filename=<original>`).

---

## 4. Report visibility matrix

| Endpoint | SUPER_ADMIN | COMPANY_ADMIN | BUILDING_MANAGER | CUSTOMER_USER |
|---|---|---|---|---|
| `/api/reports/status-distribution/` | all data | own companies | own buildings | **403** |
| `/api/reports/tickets-over-time/` | all | own companies | own buildings | **403** |
| `/api/reports/manager-throughput/` | all | own companies | own buildings | **403** |
| `/api/reports/age-buckets/` | all | own | own | **403** |
| `/api/reports/sla-distribution/` | all | own | own | **403** |
| `/api/reports/sla-breach-rate-over-time/` | all | own | own | **403** |
| `/api/reports/tickets-by-type/` (+ csv/pdf) | all | own | own | **403** |
| `/api/reports/tickets-by-customer/` (+ csv/pdf) | all | own | own | **403** |
| `/api/reports/tickets-by-building/` (+ csv/pdf) | all | own | own | **403** |

All endpoints accept `?from=YYYY-MM-DD&to=YYYY-MM-DD&company=&building=`.
`?company=` and `?building=` narrow the scope; passing an id outside
the user's allowed set returns **403**, not 200-with-empty
([reports/scoping.py:104-116](../backend/reports/scoping.py#L104-L116)).

CSV exports begin with a UTF-8 BOM for Excel compatibility. PDFs use
`fpdf2` (A4, Helvetica). Both share the same scope as the JSON
endpoint they mirror.

---

## 5. Audit coverage matrix

| Entity | CREATE | UPDATE | DELETE | Sensitive fields redacted | Test |
|---|---|---|---|---|---|
| `accounts.User` | ✅ | ✅ (only changed fields) | ✅ (soft-delete is recorded as UPDATE with `is_active`) | ✅ password / token / hash / mfa filtered | `test_audit.py`, `test_audit_membership.py::UserRoleAndActiveAuditTests` |
| `companies.Company` | ✅ | ✅ | ✅ | n/a | `test_audit.py` |
| `buildings.Building` | ✅ | ✅ | ✅ | n/a | `test_audit.py` |
| `customers.Customer` | ✅ | ✅ | ✅ | n/a | `test_audit.py` |
| `companies.CompanyUserMembership` | ✅ rich payload | n/a | ✅ rich payload | n/a | `test_audit_membership.py::CompanyMembershipAuditTests` |
| `buildings.BuildingManagerAssignment` | ✅ rich payload | n/a | ✅ rich payload | n/a | `test_audit_membership.py::BuildingMembershipAuditTests` |
| `customers.CustomerUserMembership` | ✅ rich payload | n/a | ✅ rich payload | n/a | `test_audit_membership.py::CustomerMembershipAuditTests` |
| `tickets.Ticket` (lifecycle) | ❌ — recorded in `TicketStatusHistory` instead | – | – | n/a | `test_state_machine.py` |
| `tickets.TicketComment` / `Attachment` | ❌ | – | – | n/a | – |
| `notifications.NotificationLog` | ❌ | – | – | n/a | – |

The audit log is **intentionally narrow**: admin mutations + scope
mutations only. Ticket lifecycle is in `TicketStatusHistory`, which
the frontend Ticket Detail Page surfaces directly. This is by design
(see [docs/pilot-release-candidate.md](pilot-release-candidate.md)
"Verification results" §6).

Forbidden requests (403) **do NOT** write audit rows
([test_audit_membership.py:127-142](../backend/audit/tests/test_audit_membership.py#L127-L142)).

The actor on each row is whoever DRF resolved at view-layer auth
([audit/context.py:40-50](../backend/audit/context.py#L40-L50));
background / Celery / management-command writes have `actor=None`,
which is the correct semantics.

`request_ip` records the **first** hop of `X-Forwarded-For`, fallback
`REMOTE_ADDR` ([audit/context.py:53-68](../backend/audit/context.py#L53-L68)).
The proxy chain (NPM → frontend nginx → backend) is configured to
preserve XFF — see [docs/production-smoke-test.md](production-smoke-test.md) §11.

`request_id` records `X-Request-Id` or `X-Correlation-Id` if upstream
sets one ([audit/context.py:71-85](../backend/audit/context.py#L71-L85));
otherwise NULL.

---

## 6. Production-only checks (cannot be verified before pilot host)

These are *real* contracts of the system, but they cannot be exercised
by the test suite because they depend on the live infrastructure:

1. **TLS termination at NPM** — Force-SSL on NPM, HSTS, browser shows
   green padlock. The Django stack runs HTTP-internal; verifying TLS
   requires hitting the public domain. Runbook:
   [pilot-launch-checklist.md §1-2](pilot-launch-checklist.md).
2. **`X-Forwarded-Proto` reaches Django end-to-end** — proven only when
   `request.is_secure()` returns True under a real browser request,
   which causes session/CSRF cookies to land with `Secure` flag.
   Runbook: [production-smoke-test.md §12](production-smoke-test.md).
3. **`X-Forwarded-For` first hop reaches the audit log** — proven only
   by inspecting `audit_logs.request_ip` after a real human request
   from a known public IP. Runbook:
   [production-smoke-test.md §11](production-smoke-test.md).
4. **`/health/ready` reflects DB+Redis liveness** — verified locally but
   only meaningful against the real backing services.
5. **Postgres / Redis ports closed from outside the docker host** — must
   be `nc -vz` from a different host. Runbook:
   [production-smoke-test.md §13](production-smoke-test.md).
6. **SES delivers** — IAM SMTP creds working, sandbox exited.
   Runbook: [SMTP_AMAZON_SES.md](SMTP_AMAZON_SES.md).
7. **Postgres backups + restore drill** — operator must perform the
   first drill before go-live. Runbook:
   [backup-restore-runbook.md §3](backup-restore-runbook.md).
8. **Demo accounts (`Demo12345!`) absent on pilot host.**
9. **Single named human SUPER_ADMIN created and verified.**

---

## 7. Hard blockers vs acceptable pilot risks

### Hard blockers (any one is a no-go)

| Risk | Why it blocks | Code reference / runbook |
|---|---|---|
| Customer can see internal notes or hidden attachments | breaks tenant boundary; data leak | [tickets/views.py:280-343](../backend/tickets/views.py#L280-L343) |
| Cross-company ticket detail visible | tenant breach | [accounts/scoping.py:108-127](../backend/accounts/scoping.py#L108-L127) |
| Audit log records docker-bridge IP for a real client | proxy-header chain broken; compliance risk | [production-smoke-test.md §11](production-smoke-test.md) |
| `Secure` flag missing on session/csrf cookie | session hijack risk on TLS-terminating proxy | [production-smoke-test.md §12](production-smoke-test.md) |
| Postgres / Redis publicly reachable | unauthenticated DB access | [production-smoke-test.md §13](production-smoke-test.md) |
| No backup configured OR no restore drill performed | data-loss risk | [backup-restore-runbook.md](backup-restore-runbook.md) |
| Demo accounts present on pilot host | trivial admin compromise | [pilot-launch-checklist.md §8](pilot-launch-checklist.md) |
| SES not delivering | password reset / invitation email broken | [SMTP_AMAZON_SES.md](SMTP_AMAZON_SES.md) |
| Audit log lookup endpoint accessible to non-SUPER_ADMIN | privilege escalation surface | [audit/views.py:25](../backend/audit/views.py#L25) |

### Acceptable pilot risks (documented, monitored, not blocking)

| Risk | Reason it's acceptable for pilot |
|---|---|
| Membership create handler does not validate the *target user* belongs to the same company | object-permission gates the parent resource; defence-in-depth missing but not exploitable in the current API surface ([test-reliability-audit.md §8](test-reliability-audit.md)) |
| Notification preferences race condition (mute between mutation and enqueue) | small population, recoverable |
| `apply_transition` SELECT_FOR_UPDATE concurrency not load-tested | small population (≤50 users), unlikely to trigger |
| Frontend bundle size >500KB on `index-*.js` and `ReportsPage` chunk | UX-only, not a security/data risk |
| Email language coverage tested only on admin-override copy | other transitions render in Dutch by inspection; not a leak |
| Notification mute does not affect transactional events (PASSWORD_RESET, INVITATION_SENT) | this is the intended behaviour |

---

## 8. Frozen contract (informal)

The pilot operator can rely on these statements about the system as
shipped at commit `62659d7`:

1. Customer-users cannot read internal notes, see hidden
   attachments, or post internal notes.
2. Cross-company access is enforced both by queryset scoping and
   object permissions; both must be broken simultaneously to leak.
3. Every admin mutation on User / Company / Building / Customer
   produces exactly one audit row, with sensitive fields redacted.
4. Every membership/assignment grant or revocation produces exactly
   one audit row carrying the user's email and the entity's name.
5. Ticket status history is recorded in `TicketStatusHistory`,
   visible on the Ticket Detail page.
6. The audit log API is accessible only to SUPER_ADMIN.
7. Customer-users cannot reach any reports endpoint (403).
8. The state machine is the single chokepoint for ticket status
   changes; no view writes `Ticket.status` directly.
9. Soft-deleted users cannot authenticate; reactivation is
   SUPER_ADMIN-only.
10. The system runs HTTP-internal; TLS terminates at NPM. All cookie
    secure flags depend on `X-Forwarded-Proto` propagation, which
    operator-side smoke (production-smoke-test.md §12) verifies.
