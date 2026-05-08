# Pilot release candidate (RC)

> Snapshot of the master branch as it stood when Sprint 8 verified
> it. This is **not** a runbook — see
> [docs/pilot-launch-checklist.md](pilot-launch-checklist.md),
> [docs/backup-restore-runbook.md](backup-restore-runbook.md), and
> [docs/production-smoke-test.md](production-smoke-test.md) for
> procedure. This file is the short ledger an operator can
> reference to confirm "is the code ready?" before doing the
> environment work.

## Master commit verified

`c6b78d3` (Merge pull request #31 — sprint-7-audit-scope-membership-hardening),
verified on 2026-05-09 from the dev container.

## Included merged sprint PRs (most recent first)

| Sprint | PR | Merge commit | What landed |
|---|---|---|---|
| 7 | #31 | `c6b78d3` | Audit log expanded to membership & assignment scope changes; user role / is_active already covered. |
| 6 | #30 | `beab56d` | Pilot-launch checklist, backup-restore runbook, production-smoke-test runbook, `scripts/ops/` wrappers. |
| 5 | #29 | `7eb87fb` | Reports `tickets-by-{type,customer,building}` JSON + CSV/PDF export, three new chart cards. |
| 4 | #28 | `7ffb413` | Production HTTP-internal posture (NPM upstream), prod-compose backend healthcheck via TCP socket probe, frontend nginx forwards `X-Forwarded-Proto / -For / -Host`, `docs/deployment.md`. |
| 3.7 | #27 | `27f372e` | `python manage.py seed_demo` lifecycle-safe via `apply_transition`, `docs/demo-walkthrough.md`. |
| 3.6 | #26 | `ee4c305` | Pilot-readiness roadmap; explicit no-refactor decision on `Customer` hierarchy. |
| 3.5 | #25 | `0c2ff1f` | Product / demo readiness audit. |
| 3 | #24 | `49818e2` | GitHub Actions CI (test workflow + GHCR build-images workflow). |
| 2.2 | #23 | `0cad4aa` | Audit log infrastructure (User / Company / Building / Customer); `GET /api/audit-logs/`. |
| 2.1 | #22 | `42b6321` | `UserUpdateSerializer` returns full representation; frontend defensive guards removed. |
| 1.3 | #21 | `31a4f98` | Sentry integration (frontend + backend), DSN-gated. |
| 1.2 | #20 | `cd9c247` | Frontend `ErrorBoundary`. |
| 1.1 | #19 | `0599a7f` | Backend `/health/live` + `/health/ready`, structured `LOGGING`. |

## Verification results (Sprint 8)

| Gate | Command | Result |
|---|---|---|
| Backend system check | `manage.py check` | ✅ `System check identified no issues` |
| Migrations checked in | `manage.py makemigrations --check --dry-run` | ✅ `No changes detected` |
| Backend tests | `manage.py test --keepdb` | ✅ **`Ran 458 tests in 396.140s · OK`** |
| Frontend build | `npm run build` (Node 24) | ✅ clean (`tsc -b && vite build`) |
| Bundle size | – | main `index-*.js` 579.36 KB · ReportsPage chunk 435.42 KB · CSS 51.90 KB |
| Frontend nginx config | `nginx -t` (with `--add-host=backend:127.0.0.1`) | ✅ `syntax is ok` / `test is successful` |
| Production compose | `docker compose -f docker-compose.prod.yml config` (dummy env) | ✅ renders cleanly. **Only published port: `80` (frontend).** db / redis / backend / worker / beat have no published ports. |
| `scripts/ops/*.sh` syntax | `bash -n` | ✅ 4/4 |
| Existing prod scripts syntax | `bash -n` on `prod_env_check.sh`, `prod_smoke_test.sh`, `backup_postgres.sh`, `restore_postgres.sh`, `backup_media.sh`, `restore_media.sh` | ✅ 6/6 |
| Admin smoke | `scripts/playwright_admin_smoke/runner.sh` | ✅ **`PASS=58 FAIL=0 SKIP=0`** |

## Remaining manual operator checks before pilot launch

Each item below requires the operator's own infrastructure / accounts;
no automation in this repo can verify them. Each cross-references the
relevant runbook section.

| # | Item | Where |
|---|---|---|
| 1 | NPM proxy host configured (Force SSL, HSTS, `X-Forwarded-*` headers) | [pilot-launch-checklist §1-2](pilot-launch-checklist.md) |
| 2 | Real `.env.production` populated with non-placeholder secrets, mounted via the orchestrator's secret store | [pilot-launch-checklist §3](pilot-launch-checklist.md) |
| 3 | AWS SES bootstrap done: verified sender, IAM SMTP credentials, sandbox exit if needed | [pilot-launch-checklist §4](pilot-launch-checklist.md) + [SMTP_AMAZON_SES.md](SMTP_AMAZON_SES.md) |
| 4 | Postgres backups configured (cron / systemd timer) and shipping off-host | [backup-restore-runbook §1-2](backup-restore-runbook.md) |
| 5 | Postgres restore drill performed — backup is verified by being restored at least once | [backup-restore-runbook §3](backup-restore-runbook.md) — **mandatory before go-live** |
| 6 | Media volume backup configured | [backup-restore-runbook §4](backup-restore-runbook.md) |
| 7 | Demo accounts (`demo-*@example.com / Demo12345!`) NOT present on the pilot host | [pilot-launch-checklist §8](pilot-launch-checklist.md) |
| 8 | Named human super-admin verified (login + audit log visibility) | [pilot-launch-checklist §9](pilot-launch-checklist.md) |
| 9 | Production smoke (13 numbered checks) run and all green on the public domain | [production-smoke-test.md](production-smoke-test.md) |
| 10 | Audit log shows public client IP for a real request (validates the full NPM → nginx → backend XFF chain) | [production-smoke-test §11](production-smoke-test.md) |
| 11 | Session / CSRF cookies have the `Secure` flag on browser inspection | [production-smoke-test §12](production-smoke-test.md) |
| 12 | db / redis ports unreachable from outside the docker host (verified by `nc -vz` from a different host) | [production-smoke-test §13](production-smoke-test.md) |

## No-go conditions (any one is a hard stop)

- Any backend test failing in CI on the deployed commit.
- Admin smoke failing.
- A scope leak found by the production smoke (a role sees data outside its scope).
- Hidden / internal-note attachments visible to customer users.
- Postgres or Redis reachable from the public IP.
- No backup configured, OR no restore drill performed.
- SES not delivering to a real inbox.
- Demo accounts (`Demo12345!`) reachable on the pilot domain.
- TLS cert errors in the browser, OR the audit log records a docker network IP instead of the real client IP (means the proxy header chain is broken).

## What this document is NOT

- It is not an operations log (each pilot deploy gets its own).
- It does not duplicate the runbooks.
- It does not replace the operator's responsibility for the
  manual checks in §"Remaining manual operator checks".
