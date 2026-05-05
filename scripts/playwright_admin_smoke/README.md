# Playwright admin UI smoke

End-to-end UI audit for the operator admin workflow: sidebar gating per role, list/filter/search on every admin page, invitation creation across all four roles, membership management on company/building/customer detail pages, deactivate/reactivate flows, dialog UX, and cross-tenant scope enforcement (COMPANY_ADMIN attempting to read a different tenant's URL must 403/404 with no UI bypass). The script encodes 42 distinct assertions and runs them against a live dev stack — it does **not** mock the backend, so any regression in CRUD scoping, role mutability, or invitation lifecycle surfaces immediately.

## Files

| File | Purpose |
| --- | --- |
| `run.mjs` | Playwright runner with the 42 assertions. Logs in as four roles and walks the relevant pages. |
| `proxy.mjs` | Two HTTP+WS proxies that bridge the Playwright container to the WSL host: `127.0.0.1:18000` → Vite (with Host header rewritten so Vite's `allowedHosts` guard does not 403) and `127.0.0.1:8000` → backend (with `Access-Control-Allow-Origin` forced so axios calls from the proxy origin succeed). |
| `runner.sh` | Boots `proxy.mjs` in the background, then runs `run.mjs` against the proxy ports. Expected to be mounted at `/work` inside the container. |
| `package.json` | Marker for `npm`. `runner.sh` installs `playwright@1.59.1` into a local `node_modules/` on first run; the install is gitignored. |

## Prerequisites

1. The dev compose stack is up:
   ```bash
   docker compose up -d
   ```
   Backend on `http://localhost:8000`, Vite dev server on `http://localhost:5173`, Postgres and Redis running.

2. The four smoke accounts exist with password `Test12345!`:

   | Email | Role |
   | --- | --- |
   | `smoke-super@example.com` | SUPER_ADMIN |
   | `companyadmin@example.com` | COMPANY_ADMIN, member of one company |
   | `manager@example.com` | BUILDING_MANAGER, assigned to one building in that company |
   | `customer@example.com` | CUSTOMER_USER, member of one customer in that building |

   The COMPANY_ADMIN / BUILDING_MANAGER / CUSTOMER_USER accounts are typically already in your local fixture set. If `smoke-super@example.com` does not exist, create it once via the Django shell:

   ```bash
   docker compose exec -T backend python manage.py shell -c "
   from accounts.models import User, UserRole
   User.objects.create_user(
       email='smoke-super@example.com',
       password='Test12345!',
       full_name='Smoke Super',
       role=UserRole.SUPER_ADMIN,
       is_staff=True,
       is_superuser=True,
   )
   "
   ```

   If any of the other three accounts is missing, create it the same way with the matching role and add the corresponding membership / assignment row so the role-scoped pages have something to render. `accounts.UserRole` enum values: `SUPER_ADMIN`, `COMPANY_ADMIN`, `BUILDING_MANAGER`, `CUSTOMER_USER`.

3. Docker Desktop is running and the WSL host is reachable from containers via `host.docker.internal`. On WSL2 with Docker Desktop this is automatic; on plain Linux Docker, the `--add-host` flag below pins the resolution.

## How to run

From the repo root, in WSL:

```bash
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -v "$(pwd)/scripts/playwright_admin_smoke:/work" \
  -w /work \
  mcr.microsoft.com/playwright:v1.59.1-jammy \
  bash runner.sh
```

On first run the runner installs `playwright@1.59.1` into the local `node_modules/` (about 5–10 s on a warm npm cache); subsequent runs reuse it. The directory is gitignored under the repo's existing `node_modules/` rule.

The runner cds to `/work`, starts `proxy.mjs` in the background, waits one second, and invokes `run.mjs` with `FRONTEND_URL=http://127.0.0.1:18000` and `BACKEND_URL=http://127.0.0.1:8000`. All assertions print to stdout as they run; the final block prints a counted summary plus any captured console errors.

## What success looks like

```
PASS: 42
FAIL: 0
SKIP: 0
Console errors: 12
```

All 12 expected console errors come from the cross-tenant scope-enforcement assertions: the script logs in as a COMPANY_ADMIN whose membership is on company A, then directly navigates to `/admin/companies/<B-id>`, `/admin/buildings/<B-id>`, `/admin/customers/<B-id>`, and a few user-detail URLs whose target is not in the actor's scope. The backend correctly returns 403/404 and the SPA's axios layer logs the error to the page console; the assertion verifies the page renders an empty/forbidden state, not a 200 with leaked data. Any console error originating from a path the actor *should* be able to load is unexpected and indicates a regression.

If the run reports any FAIL, the first failure log line includes the role, the URL, and a one-line diagnosis. Re-run with `DEBUG=pw:api ...` prepended for full Playwright tracing.

## Known limitations

- The container reaches Vite and the backend through `host.docker.internal`. The `--add-host=host.docker.internal:host-gateway` flag is required on plain Linux Docker; harmless under Docker Desktop.
- The bind mount path `$(pwd)/scripts/playwright_admin_smoke` resolves correctly when invoked from the repo root in WSL. Running it from a different working directory or with a Windows-style path (`C:\Users\...`) requires editing the `-v` argument; the mount target inside the container (`/work`) is hard-coded in `runner.sh`.
- The Vite dev server's `allowedHosts` guard rejects requests whose `Host` header is not `localhost`. `proxy.mjs` rewrites Host before forwarding; do **not** point Playwright directly at `host.docker.internal:5173` to bypass the proxy — Vite will return 403 and the smoke will fail before the first assertion.
- The proxy forces CORS response headers on backend traffic. If a future backend change adds genuine CORS logic (e.g. credentials-mode pinning), the forced headers may mask a real misconfiguration. Re-validate by hitting the backend directly from the host browser if anything in the auth flow starts behaving oddly.
- The Microsoft `mcr.microsoft.com/playwright:v1.59.1-jammy` image ships the browser binaries under `/ms-playwright/` but does **not** preinstall the `playwright` Node module. `runner.sh` does an `npm install playwright@1.59.1 --no-save` into the bind-mounted `/work/node_modules/` on first run; the version pin matches the image tag and must be bumped in lockstep when the image tag changes.
- Soft-deleted users created by previous runs accumulate in the dev DB. The smoke does not clean up after itself; running it many times in a row will inflate the user table. `docker compose exec backend python manage.py flush` (or a more targeted cleanup) resets it.

## When to re-run

Anytime you change anything under `frontend/src/pages/admin/`, `accounts/views_*.py`, `*/views_memberships.py`, scoping helpers, or permission classes. The runtime is roughly two minutes on a warm cache; cheap enough to run before opening a PR that touches the admin surface.
