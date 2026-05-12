# Local & CI verification ladder

Sprint 24E introduced a tiered verification flow so a small PR does
not have to wait through the full 30-minute test universe before it
can be reviewed. The four tiers below climb in cost; pick the lowest
one that still covers the surface you touched, run it, then push.

Backend warnings note — every backend test run prints lines like

```
WARNING django.request: Bad Request: /api/staff-assignment-requests/.../approve/
WARNING django.request: Forbidden: /api/staff-assignment-requests/.../cancel/
WARNING django.request: Not Found: /api/staff-assignment-requests/.../cancel/
```

from Django's request handler whenever a **negative-path test**
asserts a `400` / `403` / `404`. These are expected and are NOT test
failures. The result is determined by the final `OK` /
`FAILED (errors=...)` line; everything above it is just the request
log echoing the rejected requests.

---

## Tier 1 — Fast (~30 s)

> backend `check` + `makemigrations --check --dry-run` + frontend `tsc --noEmit`

Run before every push.

```bash
scripts/verify_fast.sh
```

What it catches:
- Django app / settings / URL wiring errors
- A model change with no checked-in migration
- TypeScript compile errors

What it does NOT catch:
- Runtime regressions, scope bugs, UI regressions, mobile overflow.
  Those need Tier 2+.

Requires the dev stack to be up (`docker compose up -d`).

---

## Tier 2 — Focused PR check (~2-5 min)

> Tier 1 + backend focused test labels + frontend production build

Run before requesting code review on a sprint-sized PR.

```bash
scripts/verify_focused.sh
```

The default focused backend label set is curated in
[scripts/verify_backend_focused.sh](../scripts/verify_backend_focused.sh)
and pins the most recent sprint test files plus the cross-sprint
state-machine / scoping suites. Override the set when you've touched
a different app:

```bash
VERIFY_BACKEND_LABELS="customers.tests buildings.tests" \
  scripts/verify_focused.sh
```

Or skip ahead and run the focused backend slice on its own:

```bash
scripts/verify_backend_focused.sh accounts.tests.test_sprint24a_staff_management
```

---

## Tier 3 — Smoke Playwright (~5-10 min)

> Headless Chromium against a curated subset of e2e specs

Run when your change touches a UI page, a route guard, or a state
transition. Bring up the prod frontend container on the compose
network first (or a Vite dev server — set `PLAYWRIGHT_BASE_URL`
accordingly) so the specs can reach `/api/` and the SPA.

```bash
# Build + run a Sprint 24E-style prod frontend on :5173, attached
# to the compose network so /api/ proxies to the backend service.
docker build -t local-frontend:smoke frontend
docker run -d --rm --name smoke_frontend \
  --network cleaning-ticket-system_default -p 5173:80 \
  local-frontend:smoke

# Run the smoke subset.
PLAYWRIGHT_BASE_URL=http://localhost:5173 \
  npm --prefix frontend run test:e2e:smoke

# Cleanup.
docker rm -f smoke_frontend
```

The smoke set is the npm `test:e2e:smoke` script — defined in
[frontend/package.json](../frontend/package.json) and currently:

- `login.spec.ts`
- `routes.spec.ts`
- `scope.spec.ts`
- `workflow.spec.ts`
- `sprint24c_staff_cancel_assignment.spec.ts`
- `sprint24d_pending_discovery.spec.ts`

Bump the list when a newer sprint introduces a contract worth
including. Keep it short — Tier 4 catches the long tail.

There is also `npm --prefix frontend run test:e2e:sprint` which runs
every `sprint*.spec.ts` file (Sprint 23B onwards). Use it if you've
touched any of the staff-assignment / scoping flows.

---

## Tier 4 — Full validation

> Full Django regression + full Playwright + smoke API scripts + prod compose

Two entry points:

### Local

```bash
scripts/check_all.sh
```

Runs the full Django `manage.py test`, the bash API smoke suites,
and the frontend production build. Doesn't run Playwright (that
stays the Tier-3/4 split below). Reserve for pre-merge final
validation on a non-trivial PR.

For the absolute full sweep including production-compose smoke
tests, restore tests, and the prod stack:

```bash
scripts/final_validation.sh
```

### CI (no local cost)

Trigger the Playwright workflow from the **Actions** tab:

- Repo → **Actions** → **playwright** → **Run workflow**
- Optional `spec_filter` input lets you run a single spec without
  pulling the runner through the entire suite.

The same workflow runs automatically every night at **03:30 UTC**
on the master branch.

---

## What still runs on every PR

The per-PR safety net is unchanged from Sprint 24E:

| Workflow | Job | What it runs |
|---|---|---|
| `.github/workflows/test.yml` | `backend-test` | `check` + `makemigrations --check --dry-run` + full `manage.py test` against Postgres-16 + Redis-7 service containers |
| `.github/workflows/test.yml` | `frontend-build` | `npm ci` + `npm run lint` (informational) + `npm run build` (`tsc -b && vite build`) |

What is NOT on every PR:

| Workflow | Trigger |
|---|---|
| `.github/workflows/playwright.yml` | `workflow_dispatch` (manual) + nightly `03:30 UTC` schedule |
| `.github/workflows/build-images.yml` | master push only (publishes to GHCR) |

When to manually trigger Playwright on a PR:
- The PR touches a Playwright spec.
- The PR changes a UI page, route guard, ticket state machine, or
  permission gate that the smoke set might miss.
- The reviewer asks for it before merge.

---

## Cadence summary

| Tier | Cost | When |
|---|---|---|
| 1 — Fast | ~30 s | Every push |
| 2 — Focused | ~2-5 min | Before review request |
| 3 — Smoke Playwright | ~5-10 min | When UI / state / scope changes |
| 4 — Full | ~30 min + | Pre-merge for risky PRs, or via CI |

When in doubt, climb one rung higher than feels strictly necessary.
The cost of catching a regression in CI is always lower than the
cost of catching it in production.
