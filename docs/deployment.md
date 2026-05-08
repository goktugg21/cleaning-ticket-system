# Production deployment

> Sprint 4. The app runs **internal HTTP** behind an external proxy
> that owns TLS. This document is the operator's reference for the
> env vars, the proxy headers Django expects, the SES SMTP
> bootstrap, and the small set of compose-level decisions that make
> the stack pilot-ready.
>
> Pairs with [`docs/pilot-readiness-roadmap.md`](pilot-readiness-roadmap.md)
> (which sets the strategy) and `.env.production.example` (the
> annotated template).

---

## 1. Production topology

```
       Browser (HTTPS)
            │
            ▼
   NGINX Proxy Manager (Serdar)        ← TLS terminates here
            │  http (internal)
            ▼
   frontend container :80              ← nginx serves the SPA
   (cleaning_ticket_prod_frontend)        and proxies /api/, /admin/,
                                          /static/ to backend:8000
            │  http (docker network)
            ▼
   backend container :8000             ← gunicorn config.wsgi
   (cleaning_ticket_prod_backend)
            │
            ├── db    container        ← postgres:16-alpine, internal only
            └── redis container        ← redis:7-alpine,    internal only
```

- TLS / HTTPS is the external proxy's job. Our app does NOT
  terminate TLS.
- NPM owns redirects (HTTP→HTTPS) and HSTS.
- Only the **frontend** container exposes a public port
  (`${FRONTEND_PORT:-80}:80` in `docker-compose.prod.yml`). Backend,
  worker, beat, db, and redis are reachable only on the internal
  docker network.
- The frontend nginx config (`frontend/nginx.conf`) already
  terminates the SPA's `/` and proxies `/api/`, `/admin/`,
  `/static/` to `http://backend:8000`. Operators do NOT need a
  separate path-rewrite configuration in NPM — NPM just forwards
  everything to the frontend container.

---

## 2. NGINX Proxy Manager configuration

In NPM ("Hosts → Proxy Hosts → Add Proxy Host"):

| Field | Value |
|---|---|
| Domain Names | `<your-public-domain>`, e.g. `cleaning.example.com` |
| Scheme | `http` (NPM is talking to the *internal* frontend container; HTTPS only happens on the browser side of NPM) |
| Forward Hostname / IP | `<docker-host-ip>` or the LAN address of the box running `docker-compose.prod.yml` |
| Forward Port | the value of `FRONTEND_PORT` (default `80`) |
| Cache Assets | optional |
| Block Common Exploits | recommended on |
| Websockets Support | not required today (no websocket routes) |

On the **SSL** tab: request a cert (Let's Encrypt or DNS-01 of your
choice), then enable:

- Force SSL  ✓ (NPM does the redirect — this is why the app's
  `DJANGO_SECURE_SSL_REDIRECT` stays `False`)
- HSTS Enabled  ✓ (NPM owns the policy)
- HSTS Subdomains  ✓ if applicable

### Required forwarded headers

Django + the audit middleware rely on the upstream proxy setting
these headers. NPM sets them by default; verify in
**Edit Host → Advanced** (or the underlying `nginx.conf`):

| Header | Why |
|---|---|
| `X-Forwarded-Proto` | Wires `request.is_secure() == True` for proxied HTTPS via `SECURE_PROXY_SSL_HEADER` (active when `DJANGO_USE_X_FORWARDED_PROTO=True`). Required for cookie security flags + CSRF to behave correctly. |
| `X-Forwarded-For` | The audit log records the **first hop** as `AuditLog.request_ip` (see [`backend/audit/context.py`](../backend/audit/context.py#L53-L68)). Without this header, audit rows fall back to `REMOTE_ADDR`, which would be the docker network's gateway IP — useless for operator-facing audit. |
| `Host` (or `X-Forwarded-Host`) | Django's `ALLOWED_HOSTS` gate compares against the request's `Host`. NPM should preserve the public hostname here (or set `X-Forwarded-Host` if it rewrites `Host` upstream). |
| `X-Request-Id` / `X-Correlation-Id` (optional) | If NPM (or a load balancer in front of it) generates a per-request id, the audit middleware records it as `AuditLog.request_id`. Useful when correlating support tickets back to log lines. The app does not generate ids itself. |

In NPM's UI, none of these usually need explicit configuration —
NPM forwards them by default. Verify with a `curl -i` from the
public URL after the proxy is up.

---

## 3. Django env settings (production)

Source of truth is [`.env.production.example`](../.env.production.example).
The proxy posture lives in these knobs:

| Env var | Production value | Why |
|---|---|---|
| `DJANGO_DEBUG` | `False` | Production. Enforces `ALLOWED_HOSTS` and the `validate_production_settings` checks in [`backend/config/security.py`](../backend/config/security.py). |
| `DJANGO_SECRET_KEY` | a long random string (≥ 50 chars, no placeholder substring) | The validator rejects anything that contains `dev-secret`, `change-me`, etc. |
| `DJANGO_ALLOWED_HOSTS` | the public hostname(s), comma-separated | The validator REJECTS `localhost` / `127.0.0.1` / `*` from this list when `DEBUG=False`. The internal docker healthcheck does NOT route through this gate (it is a TCP socket probe — see §4), so an internal host entry is not needed. |
| `CORS_ALLOWED_ORIGINS` | `https://<your-domain>` | Public origin. The validator rejects `http://localhost` / `http://127.0.0.1` here too. |
| `CSRF_TRUSTED_ORIGINS` | same as CORS | Required for any unsafe-method form / DRF request from the SPA. |
| `DJANGO_USE_X_FORWARDED_PROTO` | `True` | Activates `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`. Without this, Django thinks every request is HTTP (because internally it is) and `request.is_secure()` returns False — breaking secure cookies and a few security checks. |
| `DJANGO_SECURE_SSL_REDIRECT` | `False` | NPM owns the redirect. Setting this `True` here would create a redirect loop or mixed-protocol confusion. |
| `DJANGO_SESSION_COOKIE_SECURE` | `True` | Browsers see HTTPS, so only-HTTPS cookies are correct. Works because of `DJANGO_USE_X_FORWARDED_PROTO`. |
| `DJANGO_CSRF_COOKIE_SECURE` | `True` | Same reasoning. |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` (NPM owns HSTS) | Set non-zero only if you want defense-in-depth at the app layer too. |
| `DJANGO_LOG_LEVEL` | `WARNING` | 200-OK request traffic does not pollute prod logs. |

Cookie security expectations:
- The browser MUST see HTTPS (NPM enforces this with Force SSL).
- `request.is_secure()` MUST return `True` for proxied requests
  (handled by `DJANGO_USE_X_FORWARDED_PROTO=True`).
- Session and CSRF cookies MUST be `Secure` and HTTPOnly. Django
  sets HTTPOnly by default; `*_COOKIE_SECURE=True` adds the
  `Secure` flag.

---

## 4. Healthcheck / `ALLOWED_HOSTS` caveat

**Sprint-4 fix:** the `cleaning_ticket_prod_backend` service in
`docker-compose.prod.yml` now uses a **pure TCP socket probe**
instead of an HTTP GET to `/health/live`. The before/after:

```yaml
# Before (Sprint 1.1):
test: ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health/live',timeout=3).getcode()==200 else 1)\""]

# After (Sprint 4):
test: ["CMD-SHELL", "python -c \"import socket,sys; s=socket.create_connection(('localhost',8000),2); s.close()\""]
```

### Why the change

With `DJANGO_DEBUG=False`, Django enforces `ALLOWED_HOSTS` on every
HTTP request. The production-settings validator in
[`backend/config/security.py:82-83`](../backend/config/security.py#L82-L83)
is **stricter than Django's own check** — it rejects
`localhost` / `127.0.0.1` / `*` / `.localhost` from appearing in
`DJANGO_ALLOWED_HOSTS` AT ALL when `DEBUG=False`:

```python
if any(host in {"*", ".localhost", "localhost", "127.0.0.1"}
       for host in allowed_hosts):
    errors.append("DJANGO_ALLOWED_HOSTS must not be empty, "
                  "wildcard, or localhost-only in production.")
```

That means the old HTTP-probe healthcheck (`Host: localhost:8000`)
WOULD 400 in production: the request never makes it to
`/health/live` because Django rejects the host first.

The TCP socket probe sidesteps the issue entirely — it just
verifies that gunicorn is accepting connections on port 8000.
That is what "liveness only" means in
[`backend/config/health.py`](../backend/config/health.py)'s
docstring; readiness (does Django actually answer? does the DB
respond?) is the load balancer / NPM's job, and `/health/ready`
remains available for that purpose with a properly host-headered
request.

### What an operator must NOT do

- Do **not** add `localhost` or `127.0.0.1` to
  `DJANGO_ALLOWED_HOSTS` to "make the healthcheck work". The
  security validator will refuse to start the app.
- Do **not** loosen the validator. It exists to catch shipped
  defaults that would expose production to host-header attacks.

### Optional: NPM-side readiness probe

NPM (or any external probe) CAN hit `/health/ready` to verify
Django + Postgres + Redis. The Host header arrives as the public
hostname, which is in `DJANGO_ALLOWED_HOSTS`, so it passes the
gate. Configure NPM's "Health Checks" tab (if available) to
target `https://<your-domain>/health/ready`.

---

## 5. SMTP / Amazon SES bootstrap

The app speaks plain SMTP via Django's `EmailBackend`. SES is
recommended; any other SMTP provider (Postmark, Mailgun, etc.)
that exposes user/password SMTP credentials works the same way.

### One-time setup in the AWS console

1. **Verify the sender.** SES → Verified identities → either:
   - verify the entire sending domain (preferred — set the
     suggested DKIM and SPF DNS records), or
   - verify a single address (e.g. `no-reply@your-domain.example`)
     if you only need one sender.
2. **Generate IAM SMTP credentials.** SES → SMTP settings →
   "Create SMTP credentials". This **is not the same** as raw
   IAM access keys — the SMTP user / password it produces are
   derived but distinct, and only this pair will authenticate
   against the SMTP endpoint.
3. **Exit the sandbox** if you need to send to anything other
   than verified addresses. SES → "Account dashboard" →
   "Request production access". Without this step, SES will
   only deliver to addresses you have explicitly verified.
4. **Pick the right region.** Your SMTP host is region-specific:
   `email-smtp.eu-west-1.amazonaws.com`,
   `email-smtp.us-east-1.amazonaws.com`, etc. The region must
   match where you verified the sender.

### Production env values

Populate these in the orchestrator-managed `.env` (NOT in the
committed example):

```
EMAIL_HOST=email-smtp.<region>.amazonaws.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<the SES SMTP user>
EMAIL_HOST_PASSWORD=<the SES SMTP password>
DEFAULT_FROM_EMAIL=no-reply@your-domain.example
```

### Smoke-test before the pilot

After credentials are in place, send a test from the running
backend container:

```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python manage.py shell -c "
from django.core.mail import send_mail
send_mail(
    subject='SES smoke',
    message='If you see this, SES is wired up correctly.',
    from_email=None,  # uses DEFAULT_FROM_EMAIL
    recipient_list=['<a-verified-recipient>'],
    fail_silently=False,
)
"
```

CI does NOT run this — CI uses the locmem email backend with
empty SMTP env. Real credentials must never enter the repo or
GitHub Actions secrets unless the team consciously decides to
add a deploy job (Sprint 4+ scope).

---

## 6. Database / Redis exposure

`docker-compose.prod.yml` is already correctly configured:

```
service     port-block?    public-reachable?
─────────   ───────────    ──────────────────
db          (none)         no
redis       (none)         no
backend     (none)         no  (only accessible via the docker network)
worker      (none)         no
beat        (none)         no
frontend    "${FRONTEND_PORT:-80}:80"  yes — this is what NPM
                                            forwards to
```

**Verification commands** (operator):

```bash
# 1. Inspect the generated config; only `frontend` should have a
#    `published` port.
docker compose -f docker-compose.prod.yml config | grep -A1 "ports:"

# 2. From the host, confirm you cannot reach Postgres/Redis
#    directly. Both should refuse the connection or hang.
nc -vz <docker-host-ip> 5432
nc -vz <docker-host-ip> 6379
```

If either Postgres or Redis is reachable from the host, an
operator added a `ports:` block by hand or is running a stale
`docker-compose.yml` (the **dev** compose file does expose those
for developer convenience). Stop the stack, remove the port
block, restart with `docker-compose.prod.yml`.

Production secrets are never committed:

- `.env` is in `.gitignore`. The repo only ships the annotated
  template `.env.production.example`.
- `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `EMAIL_HOST_PASSWORD`,
  `SENTRY_DSN`, etc. live in the orchestrator's secret store
  (or whatever the host's preferred method is — `docker secret`,
  ansible-vault, sops + age, etc.).

---

## 7. Backups

Required before pilot go-live, even for 2-3 customers / 50 users.

### Postgres

Two acceptable approaches:

- **`pg_dump` on a cron** running on the docker host:

  ```bash
  # Daily dump at 02:30; keeps last 14 days.
  30 2 * * * docker compose -f /path/to/docker-compose.prod.yml \
    exec -T db pg_dump -U cleaning_ticket_user cleaning_ticket_db \
    | gzip > /backups/cleaning_$(date +\%Y\%m\%d).sql.gz \
    && find /backups -name 'cleaning_*.sql.gz' -mtime +14 -delete
  ```

- **Managed Postgres snapshots** if you're running RDS / Cloud SQL
  / DigitalOcean Managed Postgres instead of the in-compose db
  container. In that case the `db` service is removed from
  `docker-compose.prod.yml` and `POSTGRES_HOST` points at the
  managed endpoint.

### Restore drill

The backup is only valid if it has been restored once. Before the
pilot:

1. Spin up a separate staging DB (a second compose stack on the
   same host with a different `name:` line is fine).
2. Pipe the latest dump into it:

   ```bash
   gunzip -c /backups/cleaning_<latest>.sql.gz \
     | docker compose -f docker-compose.staging.yml exec -T db \
       psql -U cleaning_ticket_user cleaning_ticket_db
   ```

3. Spot-check: log in to the staging frontend, see the same
   tickets / users / customers as production has.
4. Tear down staging.

Document the restore time and the disk-space requirement in the
team's runbook.

### Redis

Redis holds Celery's queue + result backend. Losing it loses
in-flight tasks; data is otherwise reproducible from Postgres.
Redis backups are NOT required for the pilot, but persistence
should be kept on (the prod compose mounts `redis_data_prod` so
Redis survives container restarts).

### Media uploads

`backend_media_prod` volume is where ticket attachments live.
Include it in the backup plan:

```bash
# Daily archive of the media volume.
docker run --rm -v cleaning-ticket-prod_backend_media_prod:/source:ro \
  -v /backups:/dest \
  alpine sh -c "tar czf /dest/media_$(date +%Y%m%d).tar.gz -C /source ."
```

Same restore-drill discipline applies.
