# Production smoke test

> **Owner:** the operator running the pilot deploy.
> **When to run:** every time the production stack restarts —
> initial deploy, code release, infrastructure change. Each step
> is fast (under a minute) and catches the silent-failure modes
> the dev / CI smoke can't see.
>
> Pairs with [scripts/prod_smoke_test.sh](../scripts/prod_smoke_test.sh)
> (the existing automated harness) and the new
> [scripts/ops/prod_health.sh](../scripts/ops/prod_health.sh)
> wrapper that hits the public domain.
>
> **No real credentials live in this document.** Every example uses
> placeholders (`<your-public-domain>`, `<a-real-inbox>`) and dummy
> demo accounts.

---

## Prerequisites

- The pilot domain (`<your-public-domain>`) resolves to NPM.
- NPM forwards to the docker host's frontend port.
- The stack is running:
  ```bash
  docker compose -f docker-compose.prod.yml ps
  ```
  Expected: backend / worker / beat / db / redis / frontend all
  Up; backend `(healthy)`.
- An operator-friendly host shell (the `nc`, `curl`, `psql`,
  `python` commands below all assume Linux/macOS).

Set a shell variable for convenience:

```bash
export DOMAIN=<your-public-domain>            # e.g. cleaning.example.com
export ADMIN_EMAIL=<a-real-super-admin-email>
```

---

## 1. Public HTTPS frontend loads

```bash
curl -sI https://$DOMAIN/ | head -1
```

Expected:

```
HTTP/2 200
```

(`HTTP/1.1 200 OK` is also fine.) A non-200 here means NPM
isn't routed correctly or TLS is broken.

Browser check: open `https://<your-public-domain>/login`. The
login page renders; no cert warning; no mixed-content errors in
the dev-tools console.

---

## 2. `/health/live`

```bash
curl -sI https://$DOMAIN/health/live | head -1
curl -s https://$DOMAIN/health/live
```

Expected:

```
HTTP/2 200
{"status": "ok"}
```

This is the cheap liveness signal — it confirms NPM + frontend
nginx + backend gunicorn are all up. It does NOT validate
Postgres or Redis (that's `/health/ready` below).

> **Note (Sprint 11):** earlier drafts of this runbook used
> `/api/health/live`. Django registers the route as `/health/live`
> (no `/api/` prefix); Sprint 11 added a `location /health/` block to
> [frontend/nginx.conf](../frontend/nginx.conf) so the public smoke
> reaches the backend instead of falling through to the SPA shell.
> If you see HTML in the response body, the nginx config is missing
> that block — check your build.

---

## 3. `/health/ready`

```bash
curl -sI https://$DOMAIN/health/ready | head -1
curl -s https://$DOMAIN/health/ready
```

Expected (healthy):

```
HTTP/2 200
{"status": "ok", "checks": {"database": "ok", "redis": "ok"}}
```

Failure modes:

- **503** with `database: error` → Postgres unreachable from the
  backend container. Check `docker compose -f docker-compose.prod.yml
  logs db` and that `POSTGRES_HOST=db` resolves.
- **503** with `redis: error` → Redis unreachable. Check
  `CELERY_BROKER_URL` and that the redis container is up.
- **400** Bad Request from Django → the Host header gate
  rejected the request. Means `DJANGO_ALLOWED_HOSTS` does not
  contain `$DOMAIN`. Fix the env value, restart backend.

---

## 4. Login works

Browser:

1. Open `https://$DOMAIN/login`.
2. Sign in as the named super-admin.
3. Land on the dashboard. No console errors.

API smoke (no browser):

```bash
curl -s -X POST https://$DOMAIN/api/auth/token/ \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"<the-password>\"}" \
  | python3 -m json.tool
```

Expected: a JSON body with `"access"` and `"refresh"` tokens.
Save the access token for the steps below:

```bash
export TOKEN="<the access token>"
```

---

## 5. Admin user list works

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://$DOMAIN/api/users/?page_size=5" | python3 -m json.tool | head -40
```

Expected: a paginated list of users — at least the super-admin
themselves. `count` reflects the real number of accounts (not
zero, not 1 if you've onboarded several).

Browser smoke (alternative):

- Navigate to `https://$DOMAIN/admin/users`.
- The list renders with at least the super-admin row.

---

## 6. Ticket create / update flow works

Manual two-browser walkthrough is the most reliable check —
follow [docs/demo-walkthrough.md §4.1](demo-walkthrough.md) but on
the production domain with REAL accounts (NOT `demo-customer@`).

The five things to verify:

- [ ] Customer creates a ticket with a photo attachment.
- [ ] Manager moves it to IN_PROGRESS.
- [ ] Manager posts a public reply.
- [ ] Manager moves it to WAITING_CUSTOMER_APPROVAL.
- [ ] Customer approves; admin closes.

Ticket lifecycle transitions are NOT in the audit-log scope —
they are recorded in `tickets.TicketStatusHistory`, which the
TicketDetailPage already surfaces. The audit-log feed instead
shows the User / Company / Building / Customer mutations and (as
of Sprint 7) the CompanyUserMembership / BuildingManagerAssignment
/ CustomerUserMembership grants and revocations. If this checklist
included onboarding a customer user or flipping a role, those
events are now visible:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://$DOMAIN/api/audit-logs/?page_size=10" | python3 -m json.tool | head -40
```

The smoke for the ticket workflow itself is the manual walkthrough
above; for compliance / change history, the audit-log feed is the
right place to look.

---

## 7. Reports page loads

Browser:

1. Open `https://$DOMAIN/reports`.
2. All **9** chart cards render: status distribution, tickets
   over time, manager throughput, age buckets, SLA distribution,
   SLA breach rate, **tickets by type**, **tickets by customer**,
   **tickets by building**.
3. No `.alert-error` banners on any card unless the role you're
   logged in as legitimately has no data.

API smoke for one of the new dimensions:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://$DOMAIN/api/reports/tickets-by-type/" | python3 -m json.tool
```

Expected: JSON with `from`, `to`, `scope`, `buckets`, `total`,
`generated_at`.

---

## 8. CSV export downloads

```bash
curl -sI -H "Authorization: Bearer $TOKEN" \
  "https://$DOMAIN/api/reports/tickets-by-type/export.csv" | head -10
```

Expected headers:

```
HTTP/2 200
content-type: text/csv; charset=utf-8
content-disposition: attachment; filename="tickets-by-type_<from>_<to>.csv"
```

Save and inspect the body:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://$DOMAIN/api/reports/tickets-by-type/export.csv" \
  > /tmp/tickets-by-type.csv
head -3 /tmp/tickets-by-type.csv
```

Expected first line:

```
ticket_type,ticket_type_label,count,period_from,period_to
```

(Note: a UTF-8 BOM precedes the header for Excel friendliness; it
is the three bytes `EF BB BF`. `head` will show it as a stray
character; that is correct.)

Repeat for `tickets-by-customer` and `tickets-by-building`.

---

## 9. PDF export downloads

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://$DOMAIN/api/reports/tickets-by-type/export.pdf" \
  > /tmp/tickets-by-type.pdf
file /tmp/tickets-by-type.pdf
head -c 4 /tmp/tickets-by-type.pdf
```

Expected:

```
/tmp/tickets-by-type.pdf: PDF document, version 1.x
%PDF
```

(`file` reports `PDF document`; the first four bytes are the
`%PDF` magic number.) Open the file in a viewer and confirm:

- Title row present (`Tickets by type`).
- Period and `Generated at` lines.
- A table with the same columns as the CSV.

Repeat for `tickets-by-customer` and `tickets-by-building`.

---

## 10. SES test email sends

Run from inside the backend container (so the running env is
exactly what production sees):

```bash
docker compose -f docker-compose.prod.yml exec -T backend \
  python manage.py shell -c "
from django.core.mail import send_mail
send_mail(
    subject='[pilot] SES smoke',
    message='If you can read this, SES is wired up correctly.',
    from_email=None,  # uses DEFAULT_FROM_EMAIL
    recipient_list=['<a-real-inbox>'],
    fail_silently=False,
)
print('queued')
"
```

Expected:

- Command exits 0 with `queued`.
- The recipient inbox receives the message within ~30 s.
- AWS SES → Account dashboard → "Sent last 24 hours" increments.

If you get an `SMTPSenderRefused`: the IAM SMTP credentials are
wrong or SES is still in sandbox.

---

## 11. Audit log captures real client IP

A common subtle failure: NPM forwards `X-Forwarded-For` correctly,
but frontend nginx strips it (or vice versa) — Django then records
the docker network gateway as the client IP, which is useless for
audit.

Verify after a real human action (e.g. step 6 above):

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://$DOMAIN/api/audit-logs/?page_size=1" \
  | python3 -m json.tool
```

Look at `results[0].request_ip`. Expected:

- A **public IP** (the operator's home / office IP) — that means
  NPM and frontend nginx forwarded `X-Forwarded-For` end-to-end
  and the audit middleware
  ([backend/audit/context.py:53-68](../backend/audit/context.py#L53-L68))
  recorded the first hop correctly.

NOT expected:

- A docker network IP (`10.x.x.x`, `172.x.x.x` from the docker
  bridge ranges) — means `X-Forwarded-For` is missing somewhere
  in the chain. Check both NPM (Advanced tab) and
  [frontend/nginx.conf](../frontend/nginx.conf)
  `proxy_set_header X-Forwarded-For` lines.

---

## 12. Cookies have the `Secure` flag

Browser dev tools → **Application** tab → **Cookies** →
`https://<your-public-domain>`:

- `sessionid` cookie: `Secure` ✅, `HttpOnly` ✅, `SameSite=Lax`.
- `csrftoken` cookie: `Secure` ✅.

If `Secure` is missing on either cookie:

- Confirm `DJANGO_SESSION_COOKIE_SECURE=True` and
  `DJANGO_CSRF_COOKIE_SECURE=True` in `.env.production`.
- Confirm `DJANGO_USE_X_FORWARDED_PROTO=True` (Django needs to
  recognise the proxied request as HTTPS before it sets the
  Secure flag).
- Restart backend.

---

## 13. db / redis ports are not publicly exposed

From a host **OUTSIDE** the docker host (your laptop, a different
VPS):

```bash
nc -vz <docker-host-ip-or-domain> 5432
nc -vz <docker-host-ip-or-domain> 6379
```

Expected: both refuse / time out / "No route to host" / "Connection
refused".

If either succeeds: someone added a `ports:` block to
`docker-compose.prod.yml`. Remove it, restart the stack. The
production compose file ships with NEITHER db nor redis exposed,
which is the correct posture (verified in the rendered config:
`docker compose -f docker-compose.prod.yml config | grep -B2
'published:'` should show ONE port = the frontend's `80`).

---

## Pass / fail summary

| # | Check | OK |
|---|---|---|
| 1 | Public HTTPS frontend loads | [ ] |
| 2 | `/health/live` 200 | [ ] |
| 3 | `/health/ready` 200 + database+redis ok | [ ] |
| 4 | Login works (browser + token) | [ ] |
| 5 | Admin user list returns rows | [ ] |
| 6 | Ticket workflow end-to-end | [ ] |
| 7 | Reports page renders 9 chart cards | [ ] |
| 8 | CSV export downloads with correct header | [ ] |
| 9 | PDF export downloads with `%PDF` magic | [ ] |
| 10 | SES test email arrives at a real inbox | [ ] |
| 11 | Audit log `request_ip` is the public client IP | [ ] |
| 12 | `sessionid` / `csrftoken` cookies have Secure | [ ] |
| 13 | db / redis ports closed from outside | [ ] |

If all 13 are checked, the stack is operationally green for the
pilot. If any fails, treat it as a no-go (per
[pilot-launch-checklist.md §13](pilot-launch-checklist.md)).
