# Sprint 18 — Follow-ups from the Sprint 17 audit

These two items came out of `docs/audit/sprint-17-full-business-logic-audit.md`.
Both are classified **NEEDS FOLLOW-UP**, **not pilot-blocking**.

---

## 1. Move Django admin from `/admin/` to `/django-admin/`

### Problem

`frontend/nginx.conf` proxies every `/admin/*` request to the Django
backend (so `/admin/`, the Django admin console, works). The SPA's
`/admin/companies`, `/admin/buildings`, `/admin/customers`,
`/admin/users`, `/admin/invitations` routes share the same prefix —
so a fresh page load (or bookmark) at `/admin/companies` is routed
to Django and 302's to `/admin/login/?next=/admin/companies`. The
SPA admin pages are reachable today only through in-app sidebar
navigation (React Router push).

### Fix

Three small edits, no data migration:

```diff
# backend/config/urls.py
-    path("admin/", admin.site.urls),
+    path("django-admin/", admin.site.urls),
```

```diff
# frontend/nginx.conf
-    location /admin/ {
-        proxy_pass http://backend:8000/admin/;
+    location /django-admin/ {
+        proxy_pass http://backend:8000/django-admin/;
```

```diff
# frontend/src/api/admin.ts (or wherever Django admin URLs are surfaced — usually nowhere)
```

The SPA's React Router routes at `/admin/*` stay unchanged. After
the change, nginx serves the SPA shell for every `/admin/*` URL via
the existing `try_files $uri $uri/ /index.html` fallback, the SPA
mounts, AdminRoute reads the role, and the page renders.

### Acceptance criteria

- `curl http://<host>/admin/companies` returns the SPA index HTML (200).
- `curl http://<host>/django-admin/login/` returns Django's login HTML.
- No backend reverse-URL lookups still resolve `admin:`-prefixed names without explicit namespacing (Django's `admin.site.urls` carries its own namespace so this should be transparent).
- Sprint 17 Playwright `routes.spec.ts` is updated to assert the SPA
  pages reachable via direct URL (not just sidebar nav).

### Out of scope

- The `/api/auth/admin/...` endpoints and other application URLs are unaffected.
- This change does not move the bookmark `https://<host>/admin/login/` for staff using Django's admin console; that bookmark becomes `https://<host>/django-admin/login/`. Communicate this to operators in the release notes.

---

## 2. Add a React `/admin/audit-logs` page

### Problem

`/api/audit-logs/` returns the immutable audit feed and is
super-admin-only (`audit/views.py::AuditLogViewSet`). There is no
SPA page that consumes it; super-admins read the feed by hitting
the API directly.

### Fix

A read-only admin page roughly mirroring `UsersAdminPage`:

- Route: `/admin/audit-logs` behind `AdminRoute` *and* an extra
  super-admin role check (since the backend filter is super-admin-only).
- Filters: `target_model`, `target_id`, `actor`, `date_from`,
  `date_to` — match the existing `AuditLogFilter` query params.
- Columns: `created_at`, `actor.email`, `action`, `target_model`,
  `target_id`, a "show changes" cell that opens a panel with the
  per-field `before` / `after` diff.
- Pagination: same DRF cursor pagination the rest of the admin
  pages use.

### Acceptance criteria

- COMPANY_ADMIN, BUILDING_MANAGER, CUSTOMER_USER are redirected to `/?admin_required=ok` if they hit `/admin/audit-logs` directly.
- SUPER_ADMIN sees the feed and can apply each filter.
- The "show changes" panel renders the same JSON shape `audit/serializers.py::AuditLogSerializer` produces, with sensitive-field redaction visibly preserved.
- Add `frontend/tests/e2e/audit_logs.spec.ts` with at least: SUPER_ADMIN sees the page; COMPANY_ADMIN is redirected.

### Out of scope

- No change to backend endpoints or serializers.
- No log-export feature (CSV/PDF) — left for a later sprint if requested.

---

## Pilot-launch reminders (still mandatory regardless of these follow-ups)

- `python manage.py check_no_demo_accounts` MUST exit 0 before launch (`accounts/management/commands/check_no_demo_accounts.py`).
- Frontend rebuild for production MUST omit `VITE_DEMO_MODE=true` so the bundle does not bake in demo-helper login cards.
