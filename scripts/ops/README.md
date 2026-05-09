# scripts/ops/

Operator-facing convenience wrappers added in Sprint 6.

These do not replace anything in `scripts/` (`backup_postgres.sh`,
`restore_postgres.sh`, `backup_media.sh`, `restore_media.sh`,
`prod_smoke_test.sh` etc.) — the wrappers call those scripts with
default env vars and human-readable output, so a tired operator at
2am can run the right thing without re-reading the runbook.

| Script | What it does | Where to read more |
|---|---|---|
| `prod_health.sh` | Hits `/api/health/live` and `/api/health/ready` against the public domain | [docs/production-smoke-test.md §2-3](../../docs/production-smoke-test.md) |
| `pg_backup.sh` | Calls `scripts/backup_postgres.sh` with the prod compose default; prints the resulting filename | [docs/backup-restore-runbook.md §1](../../docs/backup-restore-runbook.md) |
| `pg_restore_template.sh` | Prints a pasteable, dry-run-by-default `restore_postgres.sh` invocation. **Never restores by itself.** | [docs/backup-restore-runbook.md §3](../../docs/backup-restore-runbook.md) |
| `smtp_smoke.sh` | Sends a one-line SES smoke email from inside the backend container | [docs/pilot-launch-checklist.md §4](../../docs/pilot-launch-checklist.md) |
| `prod_env_check_test.sh` | Sprint 10 — self-test for `scripts/prod_env_check.sh` using dummy good/bad env files. No real secrets. | [docs/pre-host-production-hardening.md](../../docs/pre-host-production-hardening.md) |
| `prod_compose_validate.sh` | Sprint 10 — host-agnostic validation of `docker-compose.prod.yml` rendering and host-port posture. Uses a dummy env. | [docs/pre-host-production-hardening.md](../../docs/pre-host-production-hardening.md) |
| `pilot_readiness_report.sh` | Sprint 10 — single-command OK/WARN/FAIL summary across env / compose / demo-accounts / backups / domain. Skips host-only checks gracefully. | [docs/pre-host-production-hardening.md](../../docs/pre-host-production-hardening.md) |
| `frontend_nginx_validate.sh` | Sprint 11 — runs `nginx -t` against the frontend config inside `nginx:1.27-alpine` and asserts the `/health/` proxy block is present. Locks the Sprint-11 fix against future regressions. | [docs/pre-host-production-hardening.md](../../docs/pre-host-production-hardening.md) |

## Rules

- **No secrets in this directory.** Every value comes from env
  vars or interactive prompts.
- **No destructive defaults.** Restore prints the command; the
  operator runs it after reading.
- **Every script is bash + standard tools** (`docker compose`,
  `curl`, `python3`). No new dependencies.
