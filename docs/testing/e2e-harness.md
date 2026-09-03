# The e2e harness — one command next time (P-16 Part B)

How to run the FULL Playwright suite against the dev stack, assembled
from what FE-7 / P-11 / P-13 / P-15 each had to rediscover. Everything
below runs on the dev server from the repo root.

## The moving parts

1. **A production build served by vite preview on :5173** with a
   Host-rewriting proxy (the dev backend's ALLOWED_HOSTS wants
   `crmticket`; `changeOrigin` would send 127.0.0.1 and Django 400s).
   The config is `frontend/preview.config.mjs` — a scratch file,
   NEVER staged (CLAUDE.md §3):

   ```js
   import { defineConfig } from "vite";
   export default defineConfig({
     root: "/app",
     preview: {
       port: 5173, host: true,
       proxy: {
         "/api":          { target: "http://127.0.0.1:8000", headers: { host: "crmticket" } },
         "/django-admin": { target: "http://127.0.0.1:8000", headers: { host: "crmticket" } },
         "/static":       { target: "http://127.0.0.1:8000", headers: { host: "crmticket" } },
       },
     },
   });
   ```

2. **A second backend for the suite** — the dev backend's
   `auth_token` throttle (20/min) kills a 400-test run, and the
   security validator refuses a looser rate under DEBUG=False:

   ```bash
   sg docker -c 'docker compose run -d --name e2e-backend --no-deps -p 8001:8000 \
     -e DJANGO_DEBUG=True -e CONN_MAX_AGE=0 \
     -e DRF_THROTTLE_AUTH_TOKEN_RATE=2000/minute -e DRF_THROTTLE_ANON_RATE=2000/minute \
     -e DJANGO_ALLOWED_HOSTS=crmticket,localhost,127.0.0.1 \
     backend python manage.py runserver 0.0.0.0:8000'
   ```

   Point the preview's proxy at :8001 when using it. `CONN_MAX_AGE=0`
   because dev Postgres has max_connections=100 and two threaded
   runservers with kept-alive connections exhaust it (FE-7's "too many
   clients already"). Never run a screenshot sweep concurrently.

3. **Build + serve** (the build needs the repo's `frontend/.env*`;
   `VITE_DEMO_MODE=true` explicitly, because a stray
   `.env.production.local` can force it off and silently skip the
   three demo-card specs):

   ```bash
   sg docker -c 'docker run --rm -v /home/adm-local/cleaning-ticket-system/frontend:/app \
     -w /app -e VITE_DEMO_MODE=true node:22-alpine npm run build'
   sg docker -c 'docker run -d --name e2e-preview --network host \
     -v /home/adm-local/cleaning-ticket-system/frontend:/app -w /app node:22-alpine \
     npx vite preview --config preview.config.mjs'
   ```

4. **The suite, via the PROJECT's own Playwright CLI** — `npx
   playwright` inside the MS image resolves a global 1.62 and reports
   "No tests found" (two runner instances). The image version must
   match `frontend/node_modules/@playwright/test` (1.59.1):

   ```bash
   sg docker -c 'docker run --rm --network host \
     -v /home/adm-local/cleaning-ticket-system/frontend:/app -w /app \
     -e PLAYWRIGHT_BASE_URL=http://localhost:5173 \
     -e PLAYWRIGHT_API_BASE_URL=http://localhost:5173 \
     mcr.microsoft.com/playwright:v1.59.1-noble \
     node node_modules/@playwright/test/cli.js test --reporter=line'
   ```

   BOTH env vars: `fixtures/apiAs.ts` defaults the API to
   `http://localhost:8000`, which fails ALLOWED_HOSTS behind the
   proxy. The helpers fetch same-origin since P-15 (`pageApiGet`) —
   pointing both at the preview keeps every request on one origin.

## The one pre-run fixture

`sprint30` K2 tests the retry-spawn repair for a state the API can no
longer produce (a CUSTOMER_APPROVED EW with zero spawned tickets —
auto-spawn is the fix it exercises). Seed one ORM row BEFORE each full
run; K2 heals it by pressing the button, so the row is consumed per
run:

```python
# docker compose exec -T backend python manage.py shell -c "exec(...)"
from extra_work.models import ExtraWorkRequest, ExtraWorkStatus
from customers.models import Customer, CustomerBuildingMembership
from accounts.models import User
import time
tom = User.objects.get(email="tom-customer-b-amsterdam@b-amsterdam.demo")
customer = Customer.objects.filter(name="B Amsterdam").first()
building = CustomerBuildingMembership.objects.filter(customer=customer).first().building
ExtraWorkRequest.objects.create(
    company=customer.company, customer=customer, building=building,
    title=f"[P16-FIXTURE] Stuck approved EW (K2) {int(time.time())}",
    description="e2e fixture: CUSTOMER_APPROVED, zero tickets, for the K2 retry-spawn pin.",
    status=ExtraWorkStatus.CUSTOMER_APPROVED, created_by=tom,
)
```

## Afterwards

- Playwright artifacts (`test-results/`) come out root-owned — chown
  or remove them from inside a container.
- Kill the scratch containers: `docker rm -f e2e-backend e2e-preview`.
- `preview.config.mjs` is recreated from this page; delete it rather
  than leaving it untracked.

## The suite's history (why a red is a sprint item)

P-14 proved the standing-reds trap: 15 FE-7-era reds sat in the suite
so long that three NEW breaks (P-13's testid trio, a P-4 fact-block
pin, the P-5 catch-all pin) and six helper-defect reds hid among them
unnoticed. P-16 repaired/repinned/deleted every red
(`p16-suite-repair.md`); from now on the full suite runs at the close
of every sprint and a red is a sprint item, not a note.
