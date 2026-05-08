# Security Review

## JWT storage strategy

Current frontend behavior:

- Access token is stored in `localStorage` as `accessToken`.
- Refresh token is stored in `localStorage` as `refreshToken`.
- API requests send the access token with the `Authorization: Bearer ...` header.
- Axios refresh logic uses `/api/auth/token/refresh/` when an access token expires.

Files reviewed:

- `frontend/src/auth/AuthContext.tsx`
- `frontend/src/api/client.ts`
- `backend/accounts/urls.py`
- `backend/accounts/views.py`
- `backend/config/settings.py`

## Risk

Storing JWTs in `localStorage` is simple and works for the current application, but it increases risk if an XSS vulnerability is introduced. JavaScript can read `localStorage`, so a successful XSS attack could steal both access and refresh tokens.

## Current mitigations

- Production Nginx security headers are enabled.
- `Permissions-Policy` disables camera, microphone, and geolocation by default.
- `X-Content-Type-Options` is enabled.
- `X-Frame-Options` is enabled.
- `Referrer-Policy` is enabled.
- API throttling is configured.
- Access token lifetime is limited.
- Role-based backend authorization and object scoping are enforced server-side.

## Production recommendation

Before a public launch, migrate refresh-token storage away from `localStorage`.

Recommended target:

- Store refresh token in an `HttpOnly`, `Secure`, `SameSite=Lax` or `SameSite=Strict` cookie.
- Keep access token short-lived.
- Prefer storing access token in memory rather than persistent browser storage.
- Add CSRF protection for cookie-based refresh/logout endpoints.
- Keep backend authorization checks as the source of truth.

## Decision

JWT storage strategy has been reviewed.

For private/internal testing, the current `localStorage` approach is acceptable with the existing mitigations.

For public production launch, cookie-based refresh token storage should be implemented before exposing the system to untrusted users.

## Audit-log coverage

Scope-changing actions are recorded in the `audit_auditlog` table
(see Sprint 2.2 + Sprint 7). Super admins can browse them at
`GET /api/audit-logs/` with the documented filters. Each row
captures the actor (resolved from the JWT-authenticated request,
not the middleware-time `request.user`), the action
(`CREATE` / `UPDATE` / `DELETE`), the target row, the per-field
`changes` payload, and request metadata (`request_ip` from the
first hop of `X-Forwarded-For`, optional `request_id` from
`X-Request-Id`). Sensitive fields (password, token, secret, hash,
otp, mfa) are stripped before persistence.

Coverage as of Sprint 7:

| Mutation | Audited target | Notes |
|---|---|---|
| Company / Building / Customer / User CREATE / UPDATE / DELETE | the row itself | Sprint 2.2 |
| User role change | `accounts.User` UPDATE | `changes.role.before/after` |
| User soft-delete (deactivate) | `accounts.User` UPDATE | `changes.is_active` flip + `deleted_at` stamp |
| **CompanyUserMembership create / delete** | `companies.CompanyUserMembership` | Sprint 7. Rich payload includes `user_id`, `user_email`, `company_id`, `company_name` so an operator does not need to cross-look-up pks. |
| **BuildingManagerAssignment create / delete** | `buildings.BuildingManagerAssignment` | Sprint 7. Payload mirrors the company case with `building_*`. |
| **CustomerUserMembership create / delete** | `customers.CustomerUserMembership` | Sprint 7. Payload mirrors with `customer_*`. |

Failed authorisation (403) and not-found (404) do NOT produce an
audit row, because the underlying mutation never ran. Tests in
`backend/audit/tests/test_audit_membership.py` pin this:
`test_forbidden_create_does_not_write_audit_log`.

Out of scope for the audit log today (deliberate, see
`docs/pilot-readiness-roadmap.md`):

- Ticket lifecycle transitions (already captured in
  `tickets.TicketStatusHistory`).
- Reads. Audit-log entries are mutation-only.
- Authentication events (login / logout / token refresh).
- Background / Celery system writes — those land with `actor=NULL`
  by design.
