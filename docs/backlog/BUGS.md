# Bugs

Open defects with reproduction notes. Owner: **project-manager** sub-agent
(only the PM edits this file).

Format per row:

```
- [<severity>] [<id>] <one-line title>
  Source: <how it was found — audit doc, user report, test failure>
  Reproduction:
    <steps>
  Expected: <correct behaviour>
  Actual: <observed behaviour>
  Owner: backend-engineer | frontend-engineer | both
  Tests: <failing test file or NEEDS-TEST>
```

Severities:
- **S1** — data loss, security bypass, production-down
- **S2** — feature broken, no workaround
- **S3** — wrong behaviour with workaround
- **S4** — cosmetic / copy

---

## Open

### Backend

(none — all GAP_ANALYSIS_2026-05 §2a bugs closed by the CHANGE-1..16 +
Reports v1 + Sprint 1.1 deliveries already on master. New bugs append here.)

### Frontend

- [S4] [BUG-F3] The "Remember my device for 30 days" checkbox on login is
  visual-only — comment in code admits it (`TODO(backend): wire this
  checkbox` at `frontend/src/pages/LoginPage.tsx:473-475`).
  Source: GAP_ANALYSIS_2026-05 §2b. Tracked as FRONTEND-DEVICE-1.
  Reproduction:
    1. Login with the box checked.
    2. Inspect the cookie max-age.
  Expected: cookie expires in 30 days.
  Actual: session cookie (browser-close).
  Owner: frontend-engineer (resolved by FRONTEND-DEVICE-1).
  Tests: extend `frontend/tests/e2e/login.spec.ts`.

- [S3] [BUG-F4] The customer-decision override UX hard-codes
  `(role === "SUPER_ADMIN" || role === "COMPANY_ADMIN")` at
  `frontend/src/pages/TicketDetailPage.tsx:62-67`. The scope was narrowed
  in CHANGE-11 (override now visible to COMPANY_ADMIN, matching the
  state-machine widening on master), but the check is still role-driven,
  not effective-permission-driven. If a future sprint grants override to
  any other role (or carves COMPANY_ADMIN out per-customer via the policy
  resolver), the UI will silently fail to surface it.
  Source: GAP_ANALYSIS_2026-05 §2b. Tracked as FRONTEND-OVERRIDE-1.
  Reproduction: requires a backend permission change.
  Expected: override visibility comes from
  `effective_permissions().customer.ticket.approve_*`.
  Actual: hard-coded role check.
  Owner: frontend-engineer.
  Tests: extend `frontend/tests/e2e/` override spec.

### Operational

- [S4] [BUG-O2] Nginx `client_max_body_size 12M` is barely above the 10MB
  attachment limit. Tracked as OPS-NGINX-1.
  Source: GAP_ANALYSIS_2026-05 §2c.
  Owner: frontend-engineer (file is `frontend/nginx.conf:30`).

- [S4] [BUG-O3] Whitenoise + Nginx-proxy of `/static/` is double-served. No
  functional bug; wasted work.
  Source: GAP_ANALYSIS_2026-05 §2c.
  Owner: frontend-engineer.

---

## Triage notes

The PM agent re-confirms which "verified-still-missing" items from
GAP_ANALYSIS_2026-05 are actually still open before sending them out — the
gap analysis doc is dated `2026-05` and the repo has shipped the CHANGE-1..17
series + Reports v1 + SLA v1 + Settings/Profile B1/B2 + Sprint 23-27 since.
Closed bugs are in `DONE.md` as historical reference (the bug ID stays the
same so cross-references in older docs / commits still resolve).
