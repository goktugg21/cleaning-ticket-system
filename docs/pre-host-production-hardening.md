# Pre-host production hardening (Sprint 10)

> **Audited commit:** Sprint 9 merge `362f341` + Sprint 10 work.
> **Audience:** the operator preparing to launch the pilot before
> the production host / domain / SES credentials are in hand.
>
> This file is the single index for the work that happens *before*
> the operator is given access to the pilot VPS. It tells you what
> has been verified pre-host, what remains host-only, and the exact
> commands to run when the host arrives.

Cross-links:

- [docs/pilot-launch-checklist.md](pilot-launch-checklist.md) — full
  operator runbook (host-side).
- [docs/production-smoke-test.md](production-smoke-test.md) —
  13-step post-deploy smoke (host-side).
- [docs/backup-restore-runbook.md](backup-restore-runbook.md) —
  Postgres + media backup / restore (host-side).
- [docs/ci-branch-protection.md](ci-branch-protection.md) — required
  GitHub settings on `master` (repo-side).
- [docs/system-behavior-audit.md](system-behavior-audit.md) — role /
  scope / audit contract.
- [docs/test-reliability-audit.md](test-reliability-audit.md) —
  test-coverage matrix + mutation results.

---

## What can be verified before host access

Every item below is checked by code in this repo. No real secrets
are required; no host access is required.

| # | Gate | How to run | Owner |
|---|---|---|---|
| 1 | Backend system check | `manage.py check` | CI + local |
| 2 | Migrations checked in | `manage.py makemigrations --check --dry-run` | CI + local |
| 3 | Backend tests | `manage.py test --noinput` | CI |
| 4 | Frontend build | `npm run build` (in `frontend/`) | CI |
| 5 | Production env file validation | `ENV_FILE=… ./scripts/prod_env_check.sh` | local |
| 6 | Production env validator self-test | `./scripts/ops/prod_env_check_test.sh` | local |
| 7 | Production compose validation | `./scripts/ops/prod_compose_validate.sh` | local |
| 8 | Demo-account guard | `manage.py check_no_demo_accounts` | local + CI |
| 9 | Black-box dev scope audit | `python3 scripts/audit/dev_scope_audit.py` | local |
| 10 | Pre-pilot readiness summary | `./scripts/ops/pilot_readiness_report.sh` | local |
| 11 | Branch protection on `master` | apply per [ci-branch-protection.md](ci-branch-protection.md) | repo admin |

### How the scripts work together

```
                                  +--------------------------+
                                  | pilot_readiness_report.sh|
                                  +-----------+--------------+
                                              |
                  +---------------------------+--------------------------+
                  |               |               |              |       |
                  v               v               v              v       v
            prod_env_check  prod_compose_   check_no_demo_   prod_health  backup/
                .sh         validate.sh     accounts         .sh (dom)    restore
                  |               |               |              |       |
                  v               v               v              v       v
              env file        compose           backend       public      scripts
              validation     posture audit       DB           HTTPS       presence
```

`pilot_readiness_report.sh` is the single command the operator runs
on the pilot host. Everything else is exercised by it indirectly.

---

## What remains host-only

These cannot be checked from the repo. They become real once the
operator has the pilot host, the public domain, and the SES
credentials.

| # | Item | Runbook |
|---|---|---|
| 1 | NPM proxy host configured (Force-SSL, HSTS, X-Forwarded-* headers) | [pilot-launch-checklist §1-2](pilot-launch-checklist.md) |
| 2 | Real `.env.production` placed on host with operator-managed secrets | [pilot-launch-checklist §3](pilot-launch-checklist.md) |
| 3 | AWS SES bootstrap (verified sender, IAM SMTP creds, sandbox exit) | [SMTP_AMAZON_SES.md](SMTP_AMAZON_SES.md) |
| 4 | Postgres backup cron + restore drill performed | [backup-restore-runbook §3](backup-restore-runbook.md) |
| 5 | Media volume backup configured | [backup-restore-runbook §4](backup-restore-runbook.md) |
| 6 | Demo accounts NOT present on pilot host | guard at [check_no_demo_accounts](#) |
| 7 | Named human SUPER_ADMIN created and verified | [pilot-launch-checklist §9](pilot-launch-checklist.md) |
| 8 | 13-step production smoke green on public domain | [production-smoke-test.md](production-smoke-test.md) |
| 9 | Audit log records the public client IP for a real human request | [production-smoke-test §11](production-smoke-test.md) |
| 10 | Session/CSRF cookies have `Secure` flag in browser inspection | [production-smoke-test §12](production-smoke-test.md) |
| 11 | db / redis ports unreachable from outside the docker host | [production-smoke-test §13](production-smoke-test.md) |

---

## Known finding to address before pilot launch

### Health endpoint path mismatch — operator action required

Current state:

- Django registers the health endpoints at **`/health/live`** and
  **`/health/ready`** (no `/api/` prefix —
  [backend/config/urls.py:18-19](../backend/config/urls.py#L18-L19)).
- The frontend nginx config at
  [frontend/nginx.conf](../frontend/nginx.conf) only proxies `/api/`,
  `/admin/`, and `/static/` to the backend. Plain `/health/...` is
  not forwarded; it falls through to `try_files $uri $uri/
  /index.html` and serves the SPA shell with HTTP 200 (a false
  positive!).
- The runbooks
  ([production-smoke-test.md §2-3](production-smoke-test.md),
  [pilot-launch-checklist.md §C2](pilot-launch-checklist.md)) and
  [scripts/ops/prod_health.sh](../scripts/ops/prod_health.sh) all
  curl `https://<domain>/api/health/live`, which is proxied to
  `backend:8000/api/health/live` — and Django returns **404** because
  Django expects bare `/health/live`.

Net: with the current code shipped to a real host, **neither
`/health/live` nor `/api/health/live` works through the public NPM
domain**. The internal docker healthcheck still works (it uses a TCP
socket probe that does not depend on Django routing), so the stack
itself runs healthy — but the operator-facing smoke at §2-3 of the
production smoke would either erroneously pass (SPA HTML 200 on the
unprefixed path) or fail (404 on the prefixed path).

**Why this was not caught earlier:** Sprint 9's `dev_scope_audit.py`
hits `localhost:8000/health/live` directly against the backend
container, which works (no nginx in the path). The full chain
(frontend nginx → backend) was never exercised against `/health/*`.

**Operator action — pick one before pilot launch:**

1. **Add an nginx route (recommended):** in `frontend/nginx.conf`,
   add a `location /health/` block that proxies to
   `http://backend:8000`. Keeps the runbooks and Django code as-is
   and changes only the frontend nginx routing. Smallest blast
   radius.
2. **Move Django URLs under /api/:** change
   `backend/config/urls.py` so the paths become `api/health/live` and
   `api/health/ready` — then update the docker-compose.prod.yml
   internal healthcheck (currently a TCP socket probe, so no change
   needed there) and `dev_scope_audit.py`. Larger blast radius
   (touches code + tests + scripts).

Sprint 10 deliberately does not pick a side — choosing requires a
sign-off from the operator on whether a public-facing
`/health/<...>` is acceptable in the URL space (option 1) or whether
all backend traffic must live under `/api/` (option 2). Once the
operator decides, the change is small. Sprint 10 surfaces the
mismatch so the operator does not ship to pilot with a broken smoke.

This is **not** a security issue (TLS, scope, audit are all
unaffected). It is a launch-readiness issue: the runbooks would
mislead the operator into thinking the stack was healthy when the
public smoke was actually returning the SPA shell or a 404.

---

## Exact commands to run when the production host arrives

The following sequence is the operator's pre-launch checklist on the
pilot host. Each command must finish 0 before moving on.

```bash
# --- once, on first deploy --------------------------------------

# 1. Repository on the host, on the merged release commit.
git fetch --tags
git checkout <release-tag>

# 2. .env.production placed on the host, mode 600.
sudo chmod 600 /opt/cleaning-ticket/.env.production
ENV_FILE=/opt/cleaning-ticket/.env.production ./scripts/prod_env_check.sh

# 3. Compose validation (operator's compose, not just the repo's).
./scripts/ops/prod_compose_validate.sh

# 4. Bring up the stack.
docker compose -f docker-compose.prod.yml --env-file /opt/cleaning-ticket/.env.production up -d

# 5. Migrations + collectstatic happen automatically in the backend
#    container's command. Wait for `(healthy)`:
docker compose -f docker-compose.prod.yml ps

# 6. Demo-account guard.
docker compose -f docker-compose.prod.yml exec -T backend \
    python manage.py check_no_demo_accounts

# 7. Create the named human SUPER_ADMIN (interactive).
docker compose -f docker-compose.prod.yml exec backend \
    python manage.py createsuperuser

# 8. Aggregate readiness report.
DOMAIN=cleaning.<your-domain>.tld \
    ./scripts/ops/pilot_readiness_report.sh

# 9. 13-step production smoke (manual).
DOMAIN=cleaning.<your-domain>.tld \
    ./scripts/ops/prod_health.sh
# ... and the rest of docs/production-smoke-test.md.

# 10. Backup setup + restore drill.
# See docs/backup-restore-runbook.md.
```

---

## What this document is NOT

- Not a host runbook — see
  [pilot-launch-checklist.md](pilot-launch-checklist.md).
- Not a security review — see
  [system-behavior-audit.md](system-behavior-audit.md) for the
  contract.
- Not a substitute for a live restore drill on the pilot host.
