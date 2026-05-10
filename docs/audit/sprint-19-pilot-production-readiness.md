# Sprint 19 — Pilot / production readiness gate

Date: 2026-05-10
Branch: `sprint-19-pilot-production-readiness`

This doc is the final go / no-go for the pilot launch. It is a
verification pass over the existing readiness surface (settings,
demo guards, smoke scripts, backups, docs) plus three small,
defence-in-depth fixes that came out of the audit. No product
behaviour changed.

---

## Executive summary

The system is **ready for a pilot launch** with one operator-side
gate the runbook now mandates explicitly:
`python manage.py check_no_demo_accounts` **must** exit `0` on the
pilot DB. The command's coverage was extended in this sprint to
also reject the `demo_up.sh` / `prod_upload_download_test.sh`
accounts (`admin@example.com`, `companyadmin@example.com`,
`manager@example.com`, `customer@example.com`), closing a real but
narrow leak path that the pre-Sprint-19 guard missed.

Backend (522 tests), frontend (npm build), and Playwright
(138 tests) all pass on the deployed compose stack. The local
prod smoke test passes against `http://localhost:80`.

## Launch readiness verdict

**READY** — provided the operator runs the launch command
checklist below. No code change is required to ship; the doc
clarifications and the demo-guard extension landed in this sprint
make the existing path safer to follow.

## Blocking issues

None.

## Non-blocking warnings

| # | Topic | Note |
| --- | --- | --- |
| W-1 | JWT in `localStorage` | Refresh token still lives in `localStorage`. `docs/SECURITY_REVIEW.md` already documents this and recommends a cookie-based migration before public launch. Acceptable for a pilot with the existing throttle + scope checks. |
| W-2 | App-level HSTS off | `DJANGO_SECURE_HSTS_SECONDS=0` by design — NPM owns HSTS. Operator must verify HSTS at the NPM layer in `pilot-launch-checklist.md §2`. |
| W-3 | Mobile UI polish deferred | Not in scope for this readiness gate; tracked as a post-pilot follow-up. |
| W-4 | Audit-log UI is read-only super-admin | No CSV/PDF export from the audit page; out of scope per Sprint 18. |
| W-5 | `prod_upload_download_test.sh` seeds demo emails | Running it on a real pilot host would seed `admin@example.com` etc. with `Test12345!`. Sprint 19's extension to `check_no_demo_accounts` makes the guard catch the leak retrospectively, but the script itself remains operator-side dangerous. The script header should NOT be invoked on a real pilot host. Documented in §8 of `pilot-launch-checklist.md`. |

## Verified checks

### Demo-mode safety

- `frontend/Dockerfile:4` — `ARG VITE_DEMO_MODE=false` (default false).
- `docker-compose.prod.yml:117` — `VITE_DEMO_MODE: ${VITE_DEMO_MODE:-false}` (default false).
- A production rebuild path (`docker compose ... build frontend` with no `VITE_DEMO_MODE` env) bakes `import.meta.env.VITE_DEMO_MODE === "true"` to `false`, so the dead-code-elimination strips the entire demo cards block from the bundle. Confirmed by `grep -c demo-cards` on the resulting JS asset.
- `manage.py check_no_demo_accounts` exists at `backend/accounts/management/commands/check_no_demo_accounts.py`.
- The command exits `1` when any of the three demo families is present:
  - Sprint 10 (`demo-*@example.com`).
  - Sprint 16 (`@cleanops.demo` — eight personas + suffix guard).
  - **Sprint 19 (added)** (`admin@example.com`, `companyadmin@example.com`, `manager@example.com`, `customer@example.com` — the `demo_up.sh` / `prod_upload_download_test.sh` family).
- Verified live on the running dev/QA stack: command exits `1` and lists all eight `@cleanops.demo` rows.
- `docs/pilot-launch-checklist.md §8` and `§13`, `docs/PRODUCTION_CHECKLIST.md`, `docs/GO_LIVE.md §9` all now mention the command explicitly as a hard gate.

### Production settings (`backend/config/security.py`)

`validate_production_settings()` runs at module load time when `DJANGO_DEBUG=False` and refuses to start the process if any of the following is unsafe:

- `DJANGO_SECRET_KEY` empty, < 50 chars, or contains a placeholder substring (`change-me`, `replace-with`, `dev-secret`, `secret-key`).
- `DJANGO_ALLOWED_HOSTS` empty, wildcard (`*`), or any `localhost` / `127.0.0.1` / `.localhost`.
- `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` empty, wildcard, or any `http://localhost*` / `http://127.0.0.1*` origin.
- DRF throttle rate for `anon` / `auth_token` / `auth_token_refresh` / `user` missing or more permissive than the ceiling defined in `MAX_PRODUCTION_THROTTLES`.
- `POSTGRES_PASSWORD` empty, weak (`postgres`, `password`, `cleaning_ticket_password`, etc.), or shorter than 12 characters.

Other production knobs (verified via `backend/config/settings.py` defaults):

- `DEBUG = env_bool("DJANGO_DEBUG", "False")` — defaults to off.
- `SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", "False")` — NPM owns redirect.
- `SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", "False")` — flipped to `True` in `.env.production.example`.
- `CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", "False")` — flipped to `True` in `.env.production.example`.
- `SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))` — owned by NPM, default 0.
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")` — gated on `DJANGO_USE_X_FORWARDED_PROTO=True`.

Email/SMTP, Postgres, Redis, Celery, and invitation TTL env vars are all listed in `.env.production.example` with placeholder values.

### Backup / restore readiness

- `scripts/backup_postgres.sh`, `scripts/restore_postgres.sh`, `scripts/backup_media.sh`, `scripts/restore_media.sh` exist.
- `docs/BACKUP_RESTORE.md` and `docs/backup-restore-runbook.md` document daily `pg_dump` + media archive, retention defaults (14 daily + 4 weekly), and the staged-restore drill.
- `docs/pilot-launch-checklist.md §6` makes the restore drill **mandatory** before pilot go-live.
- Uploaded media volume `backend_media_prod` is documented in `docs/MEDIA_STORAGE.md` and included in `pilot-launch-checklist.md §7`.

### Smoke scripts

- `scripts/prod_smoke_test.sh` — uses `/django-admin/login/` (Sprint 18 fix). HTTP checks for frontend, `/api/auth/me/` 401, `/django-admin/login/` 200, and the four security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy).
- `scripts/prod_upload_download_test.sh` — uses `/django-admin/login/`. Seeds the `admin/manager/customer @example.com` demo accounts and runs a real attachment upload + download. **Do NOT run on a real pilot host** — the seeded accounts use known demo passwords. Sprint 19's `check_no_demo_accounts` extension catches the leak if it happens.
- `scripts/demo_up.sh` — uses `/django-admin/login/`. Same caveat: it seeds demo accounts that the new guard rejects.

### Audit / authorization posture (rolled forward from Sprint 17)

- Four roles, four scope helpers, queryset gates on every read path. Pair-aware customer-user check (Sprint 14 / Sprint 15) is in `accounts/scoping.py::scope_tickets_for` and `tickets/state_machine.py::_user_passes_scope`.
- Audit log feed (`/api/audit-logs/`) is super-admin only at the API and the SPA (`SuperAdminRoute` from Sprint 18).
- Soft-delete (`deleted_at`) is filtered at every read site.

## Commands run and results

| Command | Result |
| --- | --- |
| `git checkout master && git pull --ff-only` | up to date at `0e003cb` (Sprint 18-3 merged) |
| `docker compose -f docker-compose.prod.yml build backend` | image rebuilt with Sprint 19 demo-guard extension |
| `docker compose -f docker-compose.prod.yml up -d --force-recreate backend` | container healthy |
| `docker compose -f docker-compose.prod.yml exec -T backend python manage.py check` | 0 issues |
| `docker compose -f docker-compose.prod.yml exec -T backend python manage.py test --keepdb` | **522 / 522** in 491s |
| `docker run --rm node:22-alpine npm run build` | clean (chunk-size warning unchanged) |
| `npm run test:e2e` (Playwright, demo-mode build) | **138 / 138** in 4.1m, no skips |
| `FRONTEND_PORT=80 ./scripts/prod_smoke_test.sh` | passed; admin login at `/django-admin/login/` returns 200; all security headers present |
| `python manage.py check_no_demo_accounts` (live) | exits 1 with the eight `@cleanops.demo` rows listed (expected on a dev/QA stack) |

`scripts/prod_upload_download_test.sh` was **inspected, not executed**, because it would seed the four `@example.com` demo accounts that this sprint's extended `check_no_demo_accounts` correctly rejects, putting our running dev stack into a temporary fail state. The script file itself is correct (the `/django-admin/login/` reference is in place from Sprint 18) and the upload/download path is exercised by the existing `tickets/tests/test_attachments.py` suite at the model/view layer.

## Production launch command checklist

Run on the real pilot host, in order:

```bash
# 1. Final pull on the pilot box
cd /opt/cleaning-ticket-system
git fetch origin
git checkout <release-tag>

# 2. Validate the .env that lives on the pilot box (NOT in git)
./scripts/prod_env_check.sh

# 3. Build images WITHOUT VITE_DEMO_MODE — defaults to false
FRONTEND_PORT=80 docker compose -f docker-compose.prod.yml build

# 4. Bring everything up
FRONTEND_PORT=80 docker compose -f docker-compose.prod.yml up -d

# 5. Demo-account guard — MUST exit 0
docker compose -f docker-compose.prod.yml exec -T backend \
  python manage.py check_no_demo_accounts

# 6. Settings runtime validator (already ran at startup, double-check)
docker compose -f docker-compose.prod.yml exec -T backend \
  python manage.py check

# 7. SPA + Django routing smoke
ASSET=$(curl -sS https://<host>/login | grep -oE '/assets/[^"]+\.js' | head -1)
# Demo cards must NOT be in the production bundle
curl -sS "https://<host>${ASSET}" | grep -c demo-cards   # MUST print 0
# SPA admin pages
curl -sI https://<host>/admin/companies                  # 200, SPA HTML
# Django admin still reachable for super-admins who need the console
curl -sI https://<host>/django-admin/login/              # 200, Django HTML
# API auth
curl -sI https://<host>/api/auth/me/                     # 401 without token

# 8. SES / email smoke
./scripts/notification_email_test.sh

# 9. Take an immediate post-launch backup snapshot
./scripts/backup_postgres.sh
./scripts/backup_media.sh

# 10. Hand the admin console URL to the operator and watch the audit log
docker compose -f docker-compose.prod.yml logs -f backend | tee /var/log/cleaning-ticket-launch.log
```

If any of `check_no_demo_accounts`, `manage.py check`, the SPA bundle
demo-card grep, or the SES smoke fails — **stop**, follow the rollback
notes below, fix, and rerun.

## Rollback notes

The compose stack is the unit of rollback. Steps:

1. **DNS** — pull the public hostname off NPM (delete the proxy host or point it at a maintenance page).
2. **Stop the new stack:** `docker compose -f docker-compose.prod.yml down`. Volumes (`postgres_data_prod`, `redis_data_prod`, `backend_media_prod`) are preserved by default — do NOT pass `-v`.
3. **DB rollback (only if a migration changed shape):**
   ```
   CONFIRM_RESTORE=YES ./scripts/restore_postgres.sh \
     backups/postgres/postgres-<previous-timestamp>.dump
   ```
4. **Image rollback:** `git checkout <previous-release-tag>` and rebuild with the same `docker compose ... build` command. Bring the stack back up.
5. Re-run the command checklist from §"Production launch command checklist", stopping at step 7 (the smoke checks).
6. Once the smoke run is clean, point NPM back at the host.

`pilot-launch-checklist.md §12` carries the long-form version.

## Remaining follow-ups after pilot

| ID | Item | Source | Severity |
| --- | --- | --- | --- |
| F-1 | Migrate refresh token from `localStorage` to an `HttpOnly Secure` cookie | `docs/SECURITY_REVIEW.md` | Pre-public-launch |
| F-2 | Mobile UI polish | Sprint 18-3 brief (deferred) | Post-pilot |
| F-3 | Audit-log CSV / PDF export | `docs/sprint-18-followups.md` (extension) | Post-pilot, nice-to-have |
| F-4 | Per-actor-email filter on the audit-log endpoint | Sprint 18 audit-log UI follow-up | Post-pilot |
| F-5 | Re-skin `scripts/demo_up.sh` to write its accounts under `@cleanops.demo` so all demo families share one TLD guard | Sprint 19 audit | Post-pilot, dev-ergonomics |

---

## Files changed in Sprint 19

```
backend/accounts/management/commands/check_no_demo_accounts.py  | +13
backend/accounts/tests/test_check_no_demo_accounts.py            | +33
docs/DEPLOYMENT.md                                               |  +5 / -1
docs/GO_LIVE.md                                                  | +14
docs/PRODUCTION_CHECKLIST.md                                     | +12 / -1
docs/audit/sprint-19-pilot-production-readiness.md               | new
docs/pilot-launch-checklist.md                                   | +28 / -23
```

Backend: 522 / 522 (was 521; +1 new Sprint-19 test).
Frontend: no source change. Playwright: 138 / 138 (unchanged from Sprint 18-3).
