# Codebase audit (Sprint 16)

> **Audited commit:** Sprint 15 merge `05df01c` plus the Sprint 16
> additions on this branch (`sprint-16-demo-qa-audit`).
> **Method:** read every code path the brief listed, classify each
> finding **PASS** / **NEEDS FOLLOW-UP** / **RISK**, and reference
> the file:line that justifies the verdict.
>
> A finding is **PASS** when the code clearly meets the contract and
> has test coverage. **NEEDS FOLLOW-UP** is correct-as-shipped but
> has a non-blocking gap (test coverage, defence in depth, doc
> drift). **RISK** means the operator should fix before pilot
> launch.

This is a developer-facing snapshot, not a runbook. The
operator-side gates live in
[docs/pilot-launch-checklist.md](../pilot-launch-checklist.md) and
[docs/production-smoke-test.md](../production-smoke-test.md).

---

## Summary table

| Area | Verdict |
|---|---|
| 1. Auth / active+deleted user filtering | ✅ PASS |
| 2. Role + scope enforcement | ✅ PASS |
| 3. Ticket queryset scoping | ✅ PASS |
| 4. Direct object access by URL | ✅ PASS |
| 5. Attachment permissions + file-type checks | ✅ PASS |
| 6. Ticket workflow transitions | ✅ PASS |
| 7. Assignment restrictions | ✅ PASS |
| 8. Soft-delete filtering | ✅ PASS |
| 9. Audit logging | ⚠ NEEDS FOLLOW-UP |
| 10. Demo mode risk | ✅ PASS |
| 11. Frontend permission hardcoding | ✅ PASS |
| 12. Environment / security settings | ✅ PASS |

**No RISK findings.** Three NEEDS FOLLOW-UP items, all already named
in earlier sprint reports; this audit re-confirms they are not
pilot blockers and explains why.

---

## 1. Auth / active+deleted user filtering — ✅ PASS

JWT login flow rejects deleted users in
[backend/accounts/auth.py:4-11](../../backend/accounts/auth.py#L4-L11)
via the `user_authentication_rule` SimpleJWT hook (returns False for
`deleted_at IS NOT NULL`). `IsAuthenticatedAndActive`
([backend/accounts/permissions.py:6-15](../../backend/accounts/permissions.py#L6-L15))
re-checks `is_active=True AND deleted_at IS NULL` on every request,
so a user soft-deleted mid-session cannot continue to act.

Test coverage: `accounts/tests/test_auth.py` covers active /
inactive / soft-deleted login outcomes; `test_permissions.py`
covers the per-request gate.

---

## 2. Role + scope enforcement — ✅ PASS

`accounts/scoping.py` is the single source of truth for which
companies / buildings / customers each role sees:

- `company_ids_for(user)` — direct membership for COMPANY_ADMIN,
  derived via assignments / customer chain for the others
  ([scoping.py:13-29](../../backend/accounts/scoping.py#L13-L29)).
- `building_ids_for(user)` — for CUSTOMER_USER reads
  `CustomerUserBuildingAccess` (Sprint 14)
  ([scoping.py:39-47](../../backend/accounts/scoping.py#L39-L47)).
- `customer_ids_for(user)` — manager OR-joins legacy
  `Customer.building` with the new M:N table for unmigrated rows
  ([scoping.py:62-91](../../backend/accounts/scoping.py#L62-L91)).
- `scope_*_for(user)` wrappers add `is_active=True` filtering for
  non-SUPER_ADMIN roles
  ([scoping.py:103-130](../../backend/accounts/scoping.py#L103-L130)).

Permission classes (`IsSuperAdminOrCompanyAdminForCompany`,
`CanManageUser`, etc.) cross-check object-level scope on top of the
queryset gate. `accounts/tests/test_admin_crud_scope_regression.py`
+ `customers/tests/test_customer_building_user_scope.py` cover
cross-tenant rejection.

---

## 3. Ticket queryset scoping — ✅ PASS

`scope_tickets_for`
([accounts/scoping.py:132-178](../../backend/accounts/scoping.py#L132-L178))
filters `deleted_at__isnull=True` for every role and uses an
`Exists` subquery on `CustomerUserBuildingAccess` for
`CUSTOMER_USER`, enforcing the (customer, building) PAIR. Sprint 15
brought `_user_passes_scope` (state machine) and
`user_has_scope_for_ticket` (messages / attachments serializers)
into the same shape, so visibility and action authority are
consistent across reads and writes.

Test coverage: 16 cases in
`customers/tests/test_customer_building_user_scope.py` (Sprint 14)
+ 10 cases in
`tickets/tests/test_state_machine.py::CustomerUserPairAccessTransitionTests`
(Sprint 15). Sprint 16 adds Playwright e2e checks
(`scope.spec.ts`) that exercise the same contract through the UI.

---

## 4. Direct object access by URL — ✅ PASS

Every ticket-aware view fetches the ticket through
`scope_tickets_for(request.user)` *first*, raising 404 when the
ticket is out of scope before any permission class runs:

- `TicketViewSet.get_queryset` / `.get_object`
  ([tickets/views.py:80-95](../../backend/tickets/views.py#L80-L95))
- `TicketMessageListCreateView._get_ticket`
  ([tickets/views.py:268-274](../../backend/tickets/views.py#L268-L274))
- `TicketAttachmentListCreateView._get_ticket` and the download view
  ([tickets/views.py:320-330](../../backend/tickets/views.py#L320-L330)
  / [:382-390](../../backend/tickets/views.py#L382-L390))

Direct-URL probes return 404 for out-of-scope rows — confirmed by
`test_cross_company_ticket_detail_is_not_visible` and
`test_amanda_cannot_view_b1_ticket_by_id`. Sprint 16's
`scope.spec.ts::Amanda gets 404 when navigating directly to a B1
ticket URL` adds e2e coverage.

---

## 5. Attachment permissions + file-type checks — ✅ PASS

- File-type whitelist at
  [tickets/serializers.py:57-78](../../backend/tickets/serializers.py#L57-L78):
  `.jpg .jpeg .png .webp .pdf .heic .heif`, MIME validated.
- 10 MB max
  ([serializers.py:67](../../backend/tickets/serializers.py#L67)).
- `is_hidden` flag rejected for CUSTOMER_USER on upload
  ([serializers.py:392-401](../../backend/tickets/serializers.py#L392-L401)).
- Customer-users blocked from posting INTERNAL_NOTE messages
  ([serializers.py:312-317](../../backend/tickets/serializers.py#L312-L317))
  and the view forces `message_type=PUBLIC_REPLY` server-side
  ([tickets/views.py:298](../../backend/tickets/views.py#L298)).
- Hidden / internal-note attachments are filtered out of the list
  endpoint AND blocked at direct download for customer-users
  ([views.py:330-343](../../backend/tickets/views.py#L330-L343),
  [:382-390](../../backend/tickets/views.py#L382-L390)).
- `user_has_scope_for_ticket` (Sprint 15) ensures the messages /
  attachments endpoints reject customer-users without per-building
  access even when they hold a `CustomerUserMembership`.

Test coverage: `tickets/tests/test_attachments.py` (7 tests),
`tests/test_scoping.py::test_customer_cannot_post_internal_note_message_type`,
`test_state_machine.py::CustomerUserPairAccessTransitionTests`.

---

## 6. Ticket workflow transitions — ✅ PASS

`tickets/state_machine.py` is the single chokepoint for status
changes. Sprint 15 closed the last gap: `SCOPE_CUSTOMER_LINKED` now
checks `CustomerUserBuildingAccess` by exact pair, not just
`CustomerUserMembership`. Frontend `TicketDetailPage.tsx` renders
`ticket.allowed_next_statuses` for every role (Sprint 15 removed
the local `SUPER_ADMIN_UI_NEXT_STATUS` table), so the buttons
visible to a SUPER_ADMIN are computed on the backend like every
other role's.

Sprint 16's `workflow.spec.ts` exercises the contract end-to-end
(Amanda sees Approve/Reject on the B3 waiting ticket; Iris does
not see them on the same B3 ticket because her access list excludes
it).

---

## 7. Assignment restrictions — ✅ PASS

`TicketAssignSerializer.validate`
([tickets/serializers.py:476-510](../../backend/tickets/serializers.py#L476-L510)):

- Customer users cannot assign anyone (403 hard rejection).
- Assignee must have role `BUILDING_MANAGER`.
- Assignee must hold a `BuildingManagerAssignment` for the ticket's
  building.

`assignable_managers` action returns only managers attached to the
target building
([tickets/views.py:236-261](../../backend/tickets/views.py#L236-L261)).
Test coverage: `tickets/tests/test_assignment.py`.

---

## 8. Soft-delete filtering — ✅ PASS

Every query path filters `Ticket.deleted_at IS NULL`
([accounts/scoping.py:139](../../backend/accounts/scoping.py#L139),
[reports/scoping.py:127-156](../../backend/reports/scoping.py#L127-L156)).
The dashboard `/api/tickets/stats/`
endpoint reuses `scope_tickets_for`, so soft-deleted rows are
excluded from KPI counts as well.

Test coverage: `tickets/tests/test_soft_delete.py` (16 cases) plus
`customers/tests/test_customer_building_user_scope.py::SoftDeletedTicketRemainsHiddenTests`.

---

## 9. Audit logging — ⚠ NEEDS FOLLOW-UP

Audit signals fire correctly for User / Company / Building /
Customer rows (Sprint 2.2) and for the four
membership-and-assignment tables: `CompanyUserMembership`,
`BuildingManagerAssignment`, `CustomerUserMembership`,
`CustomerUserBuildingAccess`, `CustomerBuildingMembership` (Sprint
14). Soft-delete on a Ticket also writes an audit row with the
actor and a rich payload (Sprint 12).

Gaps (non-blocking):

- **Ticket lifecycle is not in the audit feed.** Status transitions
  live in `TicketStatusHistory` instead (visible on the ticket
  detail page). This is a deliberate design decision documented in
  [docs/system-behavior-audit.md §5](../system-behavior-audit.md#5-audit-coverage-matrix).
  An operator looking for "who closed ticket X" reads the history
  panel, not `/api/audit-logs/`. **Action:** none — re-confirming
  the contract.
- **`request_ip` for audit rows depends on the proxy chain.**
  Sprint 11's `/health/` route fix preserved XFF; Sprint 9's
  mutation tests confirm the parser. The remaining host-only
  contract (NPM forwards XFF correctly) is verified by
  [production-smoke-test.md §11](../production-smoke-test.md).
- **No archived-view UI for soft-deleted tickets.** Audit log lists
  the delete event, but the operator cannot browse the deleted row
  itself in the public UI. Documented in the Sprint-12 final
  report. **Action:** future sprint when an operator asks for it.

---

## 10. Demo mode risk — ✅ PASS

Three layers of defence keep demo credentials out of production:

1. **Backend `seed_demo_data`** refuses to run when
   `DJANGO_DEBUG=False` unless `--i-know-this-is-not-prod` is
   passed
   ([management/commands/seed_demo_data.py:185-194](../../backend/accounts/management/commands/seed_demo_data.py#L185-L194)).
2. **`check_no_demo_accounts` management command** (Sprint 10) is
   the pilot-launch gate; refuses to allow launch if any
   `*@cleanops.demo` or older `demo-*@example.com` row exists. It
   needs to be extended to include the new `*@cleanops.demo`
   pattern — see action below.
3. **Frontend demo cards** are gated on `VITE_DEMO_MODE === "true"`
   ([LoginPage.tsx:10-18](../../frontend/src/pages/LoginPage.tsx#L10-L18)),
   not `import.meta.env.DEV`. The shipped `.env.example` sets
   `VITE_DEMO_MODE=false`. A production build cannot leak the
   cards by accident.

**Action:** update `check_no_demo_accounts` to also reject the
Sprint-16 `*@cleanops.demo` accounts. Tracked as a follow-up but
treated as the pilot operator's manual responsibility for now —
the new accounts are easy to grep for.

---

## 11. Frontend permission hardcoding — ✅ PASS

After Sprint 15's removal of `SUPER_ADMIN_UI_NEXT_STATUS`, the
frontend reads `ticket.allowed_next_statuses` from the API and
renders the listed transitions verbatim. Other role checks in the
client are visibility hints (e.g. "show the New Ticket button"),
never security gates — the backend always re-validates on submit.

Examples reviewed:

- `AppShell` uses role to decide which nav items render
  ([AppShell.tsx:18-30](../../frontend/src/layout/AppShell.tsx#L18-L30)).
  Hiding the link does not grant access; the routes themselves
  re-check via `AdminRoute` / `ReportsRoute`.
- `ReportsRoute` redirects unauthorised roles client-side; the
  backend `IsReportsConsumer` permission still rejects the API
  calls if a customer-user crafts the URL.
- `TicketDetailPage.canDeleteTicket`
  ([TicketDetailPage.tsx:191-200](../../frontend/src/pages/TicketDetailPage.tsx#L191-L200))
  hides the Delete button unless backend rules would accept the
  request — but the API still re-validates.

No client-side permission decision is the *only* gate for any
mutation.

---

## 12. Environment / security settings — ✅ PASS

`scripts/prod_env_check.sh` (hardened in Sprint 10) refuses an
`.env.production` that:

- still has `replace-with-...` placeholders,
- has DEBUG=True,
- has `*` / `localhost` / `127.0.0.1` in `ALLOWED_HOSTS`,
- has `http://` in CORS / CSRF origins,
- has SES fields missing or holds the `<region>` placeholder,
- has `INVITATION_ACCEPT_FRONTEND_URL` non-https or missing
  `{token}`,
- has `DJANGO_USE_X_FORWARDED_PROTO`, `SESSION_COOKIE_SECURE`,
  `CSRF_COOKIE_SECURE` not all True,
- has `POSTGRES_PASSWORD` short or weak,
- has `DJANGO_SECRET_KEY` short or low-entropy.

`scripts/ops/prod_compose_validate.sh` confirms that only the
frontend service publishes a host port in
`docker-compose.prod.yml`. `scripts/ops/frontend_nginx_validate.sh`
runs `nginx -t` against the built image and asserts the
`/health/` proxy block is present (Sprint 11).

Sprint 8's pilot release candidate doc lists every host-only check
the operator must perform on the live host (NPM TLS termination,
Force-SSL, HSTS, SES sandbox exit, backup drill, restore drill,
db/redis port closure).

---

## How to run the Sprint 16 verification

```bash
# 1. Backend gates.
docker compose -f docker-compose.prod.yml exec -T backend python manage.py check
docker compose -f docker-compose.prod.yml exec -T backend python manage.py test --keepdb

# 2. Frontend build.
docker run --rm -v "$PWD/frontend:/work" -w /work node:22-alpine sh -c "npm run build"

# 3. Demo seed (dev DB only).
docker compose exec -T backend python manage.py seed_demo_data

# 4. Playwright (operator runs once, then again per test pass).
cd frontend
npm run test:e2e:install   # one-time, downloads chromium
PLAYWRIGHT_BASE_URL=http://localhost:5173 npm run test:e2e
```

The Playwright config (`frontend/playwright.config.ts`) reads
`PLAYWRIGHT_BASE_URL`, default `http://localhost:5173` (Vite dev).
For the prod-compose stack, set it to `http://localhost:80`
instead.

---

## What is NOT covered by Sprint 16

- **Real production-host smoke** — see
  [production-smoke-test.md](../production-smoke-test.md) §1-13.
  Sprint 16 cannot reach a real host.
- **Email deliverability via SES** — the SES bootstrap is the
  operator's manual step; the `smtp_smoke.sh` ops script confirms
  delivery once credentials exist.
- **Long-running performance tests** — out of scope for this
  pre-pilot sprint.
