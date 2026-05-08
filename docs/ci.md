# CI / CD

Two GitHub Actions workflows live under [.github/workflows/](../.github/workflows/).

## test.yml — PR + master push validation

Triggers:
- Pull requests targeting `master`
- Pushes to `master`
- Manual via the **Actions** tab (`workflow_dispatch`)

PR runs are de-duplicated: a force-push or new commit cancels the
previous in-flight run on the same ref.

### `backend-test`

Runs Django against real Postgres 16 and Redis 7 service containers
(not SQLite, not in-memory cache). The job:

1. `python manage.py check`
2. `python manage.py makemigrations --check --dry-run`
3. `python manage.py test --noinput`

All required env vars are provided inline as dummy values
(`DJANGO_SECRET_KEY=ci-dummy-...`, empty `SENTRY_DSN`, locmem email
backend). `DJANGO_DEBUG=True` keeps the production-settings validator
in `backend/config/security.py` quiet — that validator is meant to
fail loudly when someone deploys with placeholder secrets, which is
exactly what CI uses.

Pip wheels are cached via `actions/setup-python@v6`'s built-in cache
keyed on `backend/requirements.txt`.

### `frontend-build`

Runs on Node 24 (matching the local dev nvm version). The job:

1. `npm ci` (against the committed `frontend/package-lock.json`)
2. `npm run lint` — INFORMATIONAL ONLY (`continue-on-error: true`)
3. `npm run build` (`tsc -b && vite build`)

The Vite chunk-size warning above 500 KB is informational (recharts
is route-split into ReportsPage) and does NOT fail the job.

The lint step is non-blocking because the codebase carries 33
pre-existing ESLint errors (mostly `react-hooks/set-state-in-effect`
and unused-var warnings) that pre-date this CI sprint. Failing CI on
those would block every PR until they're cleaned up. The lint output
still appears in every run for visibility; once the backlog is
cleared in a dedicated cleanup batch, drop `continue-on-error: true`
from `.github/workflows/test.yml` to promote lint to a required gate.

npm cache is keyed on `frontend/package-lock.json`.

### Lint

- Backend: no linter is configured in the repo (no `pyproject.toml`,
  `setup.cfg`, `tox.ini`, `.ruff.toml`, or `.flake8`). Per the sprint
  rules, a fresh linter stack is not introduced here. Add one in a
  later sprint and add a backend lint step then.
- Frontend: `npm run lint` runs the existing flat-config ESLint.

### Smoke

The Playwright admin smoke (`scripts/playwright_admin_smoke/`) is
intentionally NOT a required PR job. It needs the full Django stack
plus the Vite dev server plus a Playwright container, and it exercises
real browser behaviour against a JWT-authenticated session — none of
which is cheap or rock-solid in a fresh ephemeral runner. The smoke
remains a local pre-commit gate; promoting it to a nightly
`workflow_dispatch` workflow is a follow-up.

## build-images.yml — GHCR publishes on master

Triggers:
- Pushes to `master`
- Manual via the **Actions** tab (`workflow_dispatch`)

Pull requests do NOT trigger image publishes. CI's job on PRs is
validation only; only merges to master produce images.

### Images

| Image | Source | Tags |
|---|---|---|
| `ghcr.io/<owner>/<repo>-backend` | `./backend/Dockerfile` | `latest`, `<git-sha>` |
| `ghcr.io/<owner>/<repo>-frontend` | `./frontend/Dockerfile` (existing multi-stage Node + nginx) | `latest`, `<git-sha>` |

`<owner>/<repo>` is normalised to lowercase before tagging; GHCR
rejects mixed-case image names. The two images build in parallel
via a matrix.

### GHCR auth

The default `secrets.GITHUB_TOKEN` with `permissions.packages: write`
is sufficient — no manually-created PAT is required. Running the
workflow once will create the packages; the first run a maintainer
needs to flip each package's visibility to whatever the project
prefers via **GitHub → Packages → <package> → Settings**.

### Build cache

`type=gha,scope=<image>,mode=max` is set as both `cache-from` and
`cache-to`, scoped per image. The frontend's multi-stage build
benefits most: `npm ci` doesn't redo work between pushes that don't
touch `package-lock.json`.

## Required secrets

None. Both workflows run on GitHub-hosted runners with the default
`GITHUB_TOKEN`. The dev/prod application secrets (real `SENTRY_DSN`,
SMTP credentials, production `POSTGRES_PASSWORD`, etc.) live in
operator-managed `.env` files outside source control and are not
needed for CI tests, lint, or image builds.

## Local equivalents

Reproduce each CI step locally before pushing:

```bash
# Backend tests (matches backend-test, but reuses the dev compose stack)
docker compose exec -T backend python manage.py check
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend python manage.py test --keepdb

# Frontend lint + build (matches frontend-build)
export PATH="/home/goktug/.nvm/versions/node/v24.15.0/bin:$PATH"
cd frontend
npm ci
npm run lint
npm run build

# Admin smoke (NOT in CI; local-only gate)
docker run --rm --add-host=host.docker.internal:host-gateway \
  -v "$(pwd)/scripts/playwright_admin_smoke:/work" -w /work \
  mcr.microsoft.com/playwright:v1.59.1-jammy bash runner.sh
```

## Out of scope

Production deploy (pulling these images into the prod compose stack,
DNS / TLS termination, `ALLOWED_HOSTS` healthcheck wiring, real SMTP,
backups) is **Sprint 4**. This sprint only ships the CI foundation:
PR validation + image publishing on master.
