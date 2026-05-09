# Pilot launch checklist

> **Owner:** the operator deploying the stack to the pilot host.
> **Goal:** every box ticked before the first real customer logs in
> on the pilot domain. None of the steps require code changes; they
> are configuration, secret-handling, and verification work.
>
> Pairs with:
> - [docs/deployment.md](deployment.md) — Sprint-4 production
>   topology and env reference.
> - [docs/backup-restore-runbook.md](backup-restore-runbook.md) —
>   the procedural detail for §6 below.
> - [docs/production-smoke-test.md](production-smoke-test.md) —
>   the procedural detail for §10 below.
> - Pre-existing operator docs that remain authoritative for legacy
>   sections: [BACKUP_RESTORE.md](BACKUP_RESTORE.md),
>   [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md),
>   [GO_LIVE.md](GO_LIVE.md), [SMTP_AMAZON_SES.md](SMTP_AMAZON_SES.md),
>   [MEDIA_STORAGE.md](MEDIA_STORAGE.md),
>   [SECURITY_REVIEW.md](SECURITY_REVIEW.md).

---

## 1. NGINX Proxy Manager (NPM)

NPM is the only public-facing component. It owns TLS, redirect, and
HSTS. Our app speaks internal HTTP only.

- [ ] NPM runs on the same host (or a host that can reach the pilot
      box on its docker network / LAN).
- [ ] **Proxy Host** added in NPM:
  - **Domain Names:** the pilot's public domain
        (`<your-public-domain>`).
  - **Scheme:** `http` (NPM speaks HTTP to our internal stack).
  - **Forward Hostname / IP:** the docker host's LAN IP or
        hostname.
  - **Forward Port:** `${FRONTEND_PORT:-80}` from
        `.env.production` (defaults to `80`).
  - **Block Common Exploits:** ✅
  - **Websockets Support:** not needed (no websocket routes today).
- [ ] **SSL** tab:
  - Cert provisioned (Let's Encrypt or DNS-01).
  - **Force SSL** ✅ (NPM does the redirect; the app's
        `DJANGO_SECURE_SSL_REDIRECT` MUST stay `False`).
  - **HTTP/2** ✅
  - **HSTS Enabled** ✅
  - **HSTS Subdomains** ✅ if applicable.
- [ ] **Forwarded headers reach Django.** NPM sets these by
      default; verify via the production smoke test (§10):
  - `X-Forwarded-Proto: https`
  - `X-Forwarded-For: <client-ip>`
  - `Host: <your-public-domain>` (or `X-Forwarded-Host` if NPM
        rewrites Host).

**Two-hop reminder:** the request path is
`Browser → NPM → frontend nginx → backend gunicorn`. The frontend
nginx ([frontend/nginx.conf](../frontend/nginx.conf)) preserves
those headers to the backend via a `map $http_x_forwarded_proto
$forwarded_proto` block that prefers NPM's value and only falls
back to `$scheme` when NPM omitted the header. Sprint 4's commit
`c9eb0ed` is what made this correct; if you forked the nginx
config, re-verify the map and the per-block `proxy_set_header`
directives.

---

## 2. TLS / Force SSL / HSTS

| Property | Value | Owner |
|---|---|---|
| TLS termination | NPM (or upstream firewall) | Operator |
| HTTP → HTTPS redirect | NPM "Force SSL" | NPM |
| HSTS policy | NPM | NPM |
| Cookie `Secure` flag | Django (`DJANGO_SESSION_COOKIE_SECURE=True`, `DJANGO_CSRF_COOKIE_SECURE=True`) | App env |
| `request.is_secure()` truthy | `DJANGO_USE_X_FORWARDED_PROTO=True` activates `SECURE_PROXY_SSL_HEADER` | App env |

- [ ] NPM cert valid (no warnings in browser).
- [ ] HTTPS redirect works (visit `http://<domain>` → 301/302 to
      `https://<domain>`).
- [ ] HSTS header present in HTTPS response (`Strict-Transport-Security`).
- [ ] App-level HSTS knobs (`DJANGO_SECURE_HSTS_SECONDS`) left at
      their `.env.production.example` defaults (`0`) unless you
      explicitly want a defense-in-depth duplicate.

---

## 3. Django env values

Source the values from
[.env.production.example](../.env.production.example). Replace EVERY
`replace-with-...` placeholder via the orchestrator's secret store.
**Never** commit the real `.env`.

- [ ] `DJANGO_DEBUG=False`
- [ ] `DJANGO_SECRET_KEY` is a long random string (≥ 50 chars), not
      a placeholder substring (`dev-secret`, `change-me`, etc. — the
      production-settings validator in
      [backend/config/security.py](../backend/config/security.py)
      rejects those).
- [ ] `DJANGO_ALLOWED_HOSTS` = the public domain(s), comma-
      separated. **Never** include `localhost` / `127.0.0.1` /
      `*` / `.localhost` — the validator rejects them at startup.
      The internal docker healthcheck does NOT need them (it uses a
      TCP socket probe, see §11).
- [ ] `CORS_ALLOWED_ORIGINS=https://<your-domain>` (no `http://`
      origins; validator rejects).
- [ ] `CSRF_TRUSTED_ORIGINS=https://<your-domain>`.
- [ ] `DJANGO_USE_X_FORWARDED_PROTO=True`.
- [ ] `DJANGO_SECURE_SSL_REDIRECT=False` (NPM owns redirect).
- [ ] `DJANGO_SESSION_COOKIE_SECURE=True`.
- [ ] `DJANGO_CSRF_COOKIE_SECURE=True`.
- [ ] `POSTGRES_PASSWORD` is a strong unique value (validator
      rejects weak / placeholder values like `password`, `postgres`,
      `cleaning_ticket_password`, anything < 12 chars).
- [ ] `DJANGO_LOG_LEVEL=WARNING` (or `INFO` for the first week).
- [ ] `SENTRY_DSN` either set to the pilot's project DSN OR left
      empty. Empty is OK — the SDK is a complete no-op when DSN
      is unset (Sprint 1.3).

---

## 4. SES SMTP setup

Detailed walkthrough in [SMTP_AMAZON_SES.md](SMTP_AMAZON_SES.md) and
[deployment.md §5](deployment.md). Short form:

- [ ] **Verified sender** in SES — either the entire sending
      domain (preferred, requires DKIM + SPF DNS records) or a
      single From address.
- [ ] **IAM SMTP credentials** generated (NOT raw IAM access keys).
      SES → "SMTP settings" → "Create SMTP credentials".
- [ ] **Out of sandbox** if you need to send to non-verified
      recipients.
- [ ] Region matches the verified sender, e.g.
      `email-smtp.eu-west-1.amazonaws.com`.
- [ ] `.env.production` populated:
  - `EMAIL_HOST=email-smtp.<region>.amazonaws.com`
  - `EMAIL_PORT=587`
  - `EMAIL_USE_TLS=True`
  - `EMAIL_HOST_USER=<SES SMTP user>`
  - `EMAIL_HOST_PASSWORD=<SES SMTP password>`
  - `DEFAULT_FROM_EMAIL=<verified from address>`
- [ ] **Smoke send** works — see §10 step 9, or run
      `scripts/ops/smtp_smoke.sh` (added in Sprint 6).

---

## 5. Backups configured

Detailed in [docs/backup-restore-runbook.md](backup-restore-runbook.md).

- [ ] `pg_dump` runs daily via cron (or systemd timer). The dump
      lives off-host, OR the host's disk is itself backed up.
- [ ] Retention policy chosen and implemented (default
      recommendation: 14 daily + 4 weekly).
- [ ] Media volume (`backend_media_prod`) is included in the
      backup plan (separate `tar` archive cron entry).
- [ ] Backup destination is monitored — alert if no new dump in
      the last 36 hours.

---

## 6. Restore drill

This is **mandatory before pilot go-live**, not optional.

- [ ] Spin up a separate compose stack (different `name:`) on a
      staging volume.
- [ ] Pipe the latest production dump into it
      (`CONFIRM_RESTORE=YES scripts/restore_postgres.sh
      backups/postgres/postgres-<timestamp>.dump`).
- [ ] Spot-check via the staging frontend: tickets / users /
      customers match production.
- [ ] Tear down staging.
- [ ] Document the restore time + disk requirement in the team's
      runbook.
- [ ] Repeat the drill quarterly.

---

## 7. Media volume backup

The `backend_media_prod` docker volume holds every uploaded ticket
attachment.

- [ ] `scripts/backup_media.sh` (or your own equivalent) is on a
      cron, archiving the volume nightly with the same retention
      policy as Postgres.
- [ ] Backup destination has enough headroom (estimate from current
      `du -sh /var/lib/docker/volumes/cleaning-ticket-prod_backend_media_prod/_data`).
- [ ] **Restore path tested** at least once — see
      [docs/backup-restore-runbook.md §3](backup-restore-runbook.md).

---

## 8. Demo account cleanup

The local-demo accounts (`demo-super@`, `demo-company-admin@`,
`demo-manager@`, `demo-customer@`) all use the predictable password
`Demo12345!`. They MUST NOT exist on the pilot host with that
password.

- [ ] **Did NOT** run `python manage.py seed_demo` against the
      production database. (The command is intended for local
      dev only — it idempotently re-applies `Demo12345!` to those
      four accounts, which would be a public credential leak in
      production.)
- [ ] If the pilot DB inherited dev fixtures by mistake: delete
      the four demo users with
      `User.objects.filter(email__startswith="demo-").delete()`,
      OR set them inactive and rotate their passwords to opaque
      random strings.
- [ ] Run a check from inside the backend container:
      ```
      docker compose -f docker-compose.prod.yml exec -T backend \
        python manage.py shell -c \
        "from accounts.models import User; \
         print('demo accounts present:', \
           User.objects.filter(email__startswith='demo-').count())"
      ```
      Expected output: `demo accounts present: 0`.

---

## 9. Admin account verification

- [ ] At least one real super-admin account exists, owned by a
      named human, with a strong unique password, and 2FA-on-the-
      browser if your OS supports it (the app does not currently
      enforce its own 2FA).
- [ ] That super-admin can log in via the public domain.
- [ ] That super-admin can browse `/api/audit-logs/` (Sprint 2.2 +
      Sprint 7) and see the User / Company / Building / Customer
      mutations AND the CompanyUserMembership /
      BuildingManagerAssignment / CustomerUserMembership grants and
      revocations they have performed during this checklist.
- [ ] At least one named operator has shell access to the docker
      host AND knows where the `.env.production` lives.

---

## 10. Smoke test after deployment

Run the full sequence from
[docs/production-smoke-test.md](production-smoke-test.md) after the
stack is up. The condensed list:

- [ ] Public HTTPS frontend loads.
- [ ] `/health/live` returns 200 (and the body is JSON, not HTML).
- [ ] `/health/ready` returns 200 with `{database: ok, redis: ok}`.
- [ ] Login works for the named super-admin.
- [ ] Admin user list loads.
- [ ] Customer creates a ticket end-to-end (the live flow from
      [docs/demo-walkthrough.md](demo-walkthrough.md)).
- [ ] Reports page renders all 9 chart cards (6 baseline + 3
      Sprint-5 dimensions).
- [ ] CSV export downloads without warnings.
- [ ] PDF export downloads (and opens) without warnings.
- [ ] SES test email arrives at a real inbox.
- [ ] Audit log row for a recent mutation has the correct
      `request_ip` (the original client's IP, **not** the docker
      gateway). This validates that NPM and the frontend nginx
      both forward `X-Forwarded-For` end-to-end.
- [ ] Browser dev tools confirm session / CSRF cookies have the
      `Secure` flag.
- [ ] `nc -vz <docker-host-ip> 5432` and
      `nc -vz <docker-host-ip> 6379` from outside the host BOTH
      refuse / time out (db and redis are container-internal).

---

## 11. Healthcheck `ALLOWED_HOSTS` caveat

Sprint 4 already addressed this in code; the operator just needs
to verify the resolved compose config matches the documented form.

- [ ] `docker-compose.prod.yml` `backend.healthcheck.test` uses a
      pure TCP socket probe (`socket.create_connection(('localhost',
      8000), 2)`), NOT an HTTP GET against `/health/live`. This is
      what makes the healthcheck pass with strict `ALLOWED_HOSTS`.
- [ ] `docker compose -f docker-compose.prod.yml ps` shows backend
      as `(healthy)` after the 30-second `start_period`.

---

## 12. Rollback steps

If the pilot deploy is wrong:

1. Take the public DNS off NPM (delete the proxy host or revert
   to the previous one).
2. Stop the new stack: `docker compose -f docker-compose.prod.yml
   down` (preserves volumes).
3. Restore the previous DB dump if migrations changed shape:
   `CONFIRM_RESTORE=YES scripts/restore_postgres.sh
   backups/postgres/postgres-<previous-timestamp>.dump`.
4. Bring back the previous compose / image revision and start it.
5. Re-run the smoke test (§10) before pointing DNS back.

---

## 13. Go / no-go (use as gate before announcing the pilot URL)

### Go (every box ticked)
- [ ] Backend tests in CI: green on the deployed commit.
- [ ] Admin smoke in dev: green on the deployed commit.
- [ ] Sections 1–10 above all complete.
- [ ] Restore drill (§6) performed and recorded.
- [ ] At least one named human owns the host, the `.env`, and the
      24-hour incident response.

### No-go (any one is a hard stop)
- Tests / smoke failing on the deployed commit.
- Demo accounts (`Demo12345!`) reachable on the pilot domain.
- `/api/audit-logs/` reachable by anyone other than super-admin.
- Postgres / Redis port reachable from the public IP.
- No backup configured, or no successful restore drill.
- SMTP not delivering to a real inbox.
- HSTS / Force SSL not enabled at NPM.
- TLS cert errors in the browser.

---

## What this document does not do

- It does not replace [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md)
  or [GO_LIVE.md](GO_LIVE.md) for the security / runtime / sentry /
  HTTPS items they already cover; this doc is the **pilot-launch**
  delta on top of those.
- It does not include the marketing / customer-onboarding plan;
  that lives elsewhere.
- It does not audit the cloud account itself (IAM, networking
  rules, billing alarms) — those are operator-level, not
  application-level.
