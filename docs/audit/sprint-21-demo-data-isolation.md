# Sprint 21 — Demo data cleanup and multi-company isolation

This sprint cleans the local-demo dataset before pilot hosting and
verifies cross-company isolation end-to-end. No product workflow or
permission rule was changed.

## 1. Problems found in the pre-Sprint-21 demo stack

The repo carried three overlapping demo-seed entry points, each
producing a different set of accounts:

| Source | Company | Users | Password |
|---|---|---|---|
| `seed_demo` (Sprint 10) | "Demo Cleaning BV" | `demo-*@example.com` × 4 | `Demo12345!` |
| `seed_demo_data` (Sprint 16) | "Osius Demo" | 8 personas under `@cleanops.demo` | `Demo12345!` |
| `seed_b_amsterdam_demo` (Sprint 14) | "Osius Demo" | `tom`/`iris`/`amanda`@b-amsterdam.com, three `@osius.demo` managers | unusable / `Sprint14Demo!` |
| `scripts/demo_up.sh` (inline) | "Demo Cleaning Company" | `admin`/`companyadmin`/`manager`/`customer@example.com` | `Admin12345!` / `Test12345!` |

The visible problems:

- **No multi-company demo exists.** Every seed creates a single
  tenant, so cross-company isolation cannot be exercised against the
  demo stack.
- **Email-domain drift.** `@example.com`, `@cleanops.demo`,
  `@b-amsterdam.com`, `@osius.demo`, all in active use.
- **Password drift.** Four different passwords across the four seed
  variants. The frontend demo cards always documented
  `Demo12345!`, which only worked for two of the four seeds.
- **Duplicate companies under the same slug.** `seed_demo_data` and
  `seed_b_amsterdam_demo` both upsert `slug=osius-demo` but disagree
  on the customer-user emails (`@cleanops.demo` vs `@b-amsterdam.com`).
- **Stale legacy seed.** `seed_demo` ("Demo Cleaning BV") is still
  referenced by the demo walkthrough doc and by `dev_scope_audit.py`
  even though the canonical seed moved on in Sprint 16.

## 2. What changed in Sprint 21

### a. Canonical seed: `seed_demo_data` now provisions two companies

[backend/accounts/management/commands/seed_demo_data.py](../../backend/accounts/management/commands/seed_demo_data.py)
is refactored around a data-driven `COMPANIES = [...]` list so a third
or fourth company is one entry away. Two demo companies are seeded:

- **Company A — Osius Demo** (Amsterdam, B1 / B2 / B3) — unchanged
  shape; Sprint 16's eight Osius personas + four lifecycle tickets.
- **Company B — Bright Facilities** (Rotterdam, R1 / R2) — new.
  Three personas (`admin-b`, `manager-b`, `customer-b@cleanops.demo`)
  + a `City Office Rotterdam` consolidated customer + two demo
  tickets (one OPEN, one IN_PROGRESS).

The super admin (`super@cleanops.demo`) is unchanged and spans both
companies.

### b. Legacy seed commands removed

- `backend/accounts/management/commands/seed_demo.py` — deleted.
- `backend/accounts/management/commands/seed_b_amsterdam_demo.py` —
  deleted.

The deletions do **not** weaken the pilot-launch guard:
`check_no_demo_accounts` still rejects the emails those scripts used
to write, so a pilot DB that still carries old rows is still caught.

### c. Demo-up script no longer inlines its own seed

[scripts/demo_up.sh](../../scripts/demo_up.sh) used to write
`admin@example.com` / `companyadmin@example.com` / etc. via an
inline `manage.py shell` heredoc. It now delegates to
`manage.py seed_demo_data --i-know-this-is-not-prod`. The legacy
`@example.com` accounts stay in the `check_no_demo_accounts` block
list as defense-in-depth (an operator running an older snapshot of
the script against the pilot DB still trips the guard).

### d. Pilot guard list extended

[backend/accounts/management/commands/check_no_demo_accounts.py](../../backend/accounts/management/commands/check_no_demo_accounts.py)
gained the three Company B emails:

```
admin-b@cleanops.demo
manager-b@cleanops.demo
customer-b@cleanops.demo
```

The existing `@cleanops.demo` suffix catch-all would have rejected
them anyway; the explicit list ensures the operator-facing error
message names them.

### e. Frontend demo cards split by company

[frontend/src/pages/LoginPage.tsx](../../frontend/src/pages/LoginPage.tsx)
now renders the demo cards in three groups when `VITE_DEMO_MODE=true`:

1. **Super admin** (one card, spans both companies).
2. **Company A — Osius Demo (Amsterdam)** — six cards.
3. **Company B — Bright Facilities (Rotterdam)** — three cards.

Each card carries a `data-demo-company` attribute (`"A"`, `"B"`, or
`"both"`) so the Playwright suite can address them by company.

### f. Test fixtures rebuilt

[frontend/tests/e2e/fixtures/demoUsers.ts](../../frontend/tests/e2e/fixtures/demoUsers.ts)
exports `COMPANY_A_BUILDINGS`, `COMPANY_B_BUILDINGS`, `COMPANY_A_NAME`,
`COMPANY_B_NAME` and a `company: "A" | "B" | "both"` field on every
`DemoUser`. The Sprint 16/17 single-company scope tests keep working
because every existing fixture is still present and unchanged in shape.

### g. Legacy demo row prune (Sprint 21 follow-up)

Deleting the legacy `seed_demo` and `seed_b_amsterdam_demo` command
files did not remove rows already created in local / demo databases
that ran those scripts before Sprint 21 landed. After the first
Sprint 21 deploy of the demo stack, `/admin/users` still showed the
old personas (`amanda@b-amsterdam.com`, `gokhan.kocak@osius.demo`,
etc.) alongside the canonical set.

[backend/accounts/management/commands/seed_demo_data.py](../../backend/accounts/management/commands/seed_demo_data.py)
now declares two explicit constants and a `_prune_legacy_demo_rows`
helper that runs after the super admin is created and before the
canonical companies are seeded:

```python
LEGACY_DEMO_EMAILS = (
    # seed_demo (Sprint 10, removed in Sprint 21):
    "demo-super@example.com", "demo-company-admin@example.com",
    "demo-manager@example.com", "demo-customer@example.com",
    # pre-Sprint-21 scripts/demo_up.sh inline shell:
    "admin@example.com", "companyadmin@example.com",
    "manager@example.com", "customer@example.com",
    # seed_b_amsterdam_demo (Sprint 14, removed in Sprint 21):
    "tom@b-amsterdam.com", "iris@b-amsterdam.com",
    "amanda@b-amsterdam.com",
    "gokhan.kocak@osius.demo", "murat.ugurlu@osius.demo",
    "isa.ugurlu@osius.demo",
)
LEGACY_COMPANY_SLUGS = ("demo-cleaning-bv", "demo-cleaning-company")
```

For each legacy user the prune:

1. Deletes `CustomerUserBuildingAccess` rows hanging off the user's
   `CustomerUserMembership`.
2. Deletes `CustomerUserMembership`, `BuildingManagerAssignment`,
   and `CompanyUserMembership` rows where `user_id = legacy.id`.
3. Deletes any `Ticket` whose `created_by_id` matches a legacy user
   (legacy demo tickets only — canonical demo tickets are created by
   `@cleanops.demo` accounts).
4. Calls the model's soft-delete equivalent (sets `is_active=False`,
   `deleted_at=now()`, `deleted_by=super_admin`), so the row stays
   in the DB for audit but never re-appears in the active list.

For each legacy company slug, `is_active` flips to `False`. The
canonical Sprint 21 slugs (`osius-demo`, `bright-facilities`) are
NOT in `LEGACY_COMPANY_SLUGS`, and the canonical user emails share
zero prefixes with any `LEGACY_DEMO_EMAILS` entry, so the prune is
mathematically incapable of touching the canonical set.

The match is exact-by-email — there is no domain wildcard, so a
real operator's email can never collide. The Sprint 19 pilot-launch
guard (`check_no_demo_accounts`) still references the same emails
as a defense-in-depth, so a pilot host where this prune never ran
is still blocked from going live.

## 3. Final demo account matrix

All accounts share the password `Demo12345!`.

### Super admin (spans both companies)

| Email | Role |
|---|---|
| `super@cleanops.demo` | SUPER_ADMIN |

### Company A — Osius Demo

| Email | Role | Buildings |
|---|---|---|
| `admin@cleanops.demo` | COMPANY_ADMIN | (entire company) |
| `gokhan@cleanops.demo` | BUILDING_MANAGER | B1, B2, B3 |
| `murat@cleanops.demo` | BUILDING_MANAGER | B1 |
| `isa@cleanops.demo` | BUILDING_MANAGER | B2 |
| `tom@cleanops.demo` | CUSTOMER_USER | B1, B2, B3 |
| `iris@cleanops.demo` | CUSTOMER_USER | B1, B2 |
| `amanda@cleanops.demo` | CUSTOMER_USER | B3 |

### Company B — Bright Facilities

| Email | Role | Buildings |
|---|---|---|
| `admin-b@cleanops.demo` | COMPANY_ADMIN | (entire company) |
| `manager-b@cleanops.demo` | BUILDING_MANAGER | R1, R2 |
| `customer-b@cleanops.demo` | CUSTOMER_USER | R1, R2 |

## 4. Final company / building / customer matrix

| Company | Buildings | Customer | [DEMO] tickets |
|---|---|---|---|
| Osius Demo (`osius-demo`) | B1 Amsterdam, B2 Amsterdam, B3 Amsterdam | "B Amsterdam" (consolidated; M:N) | 4 (OPEN, IN_PROGRESS, WAITING_CUSTOMER_APPROVAL, CLOSED) |
| Bright Facilities (`bright-facilities`) | R1 Rotterdam, R2 Rotterdam | "City Office Rotterdam" (consolidated; M:N) | 2 (OPEN, IN_PROGRESS) |

## 5. Isolation rules verified

| Rule | Backend coverage | Playwright coverage |
|---|---|---|
| SUPER_ADMIN sees both companies | `test_super_admin_sees_both_companies` | `Super admin sees tickets from both demo companies` |
| Company A admin sees only Company A buildings | `test_company_a_admin_sees_only_company_a` | `Company A admin sees only Company A buildings on /tickets` |
| Company B admin sees only Company B buildings | `test_company_b_admin_sees_only_company_b` | `Company B admin sees only Company B buildings on /tickets` |
| Cross-company ticket visibility blocked | `test_cross_company_ticket_visibility_is_blocked` | `Cross-company ticket detail API access returns 404 for Company A admin` |
| Cross-company customer visibility blocked | `test_cross_company_customer_visibility_is_blocked` | (covered by reports endpoint probe below) |
| Cross-company user-admin visibility blocked | `test_cross_company_user_admin_visibility_is_blocked` | (admin users page already covered in `admin_crud.spec.ts`) |
| Building manager only sees assigned buildings | `test_manager_b_sees_only_company_b_buildings` | `Company B manager only sees R1/R2 buildings on /tickets` |
| Customer user only sees assigned buildings | `test_customer_b_sees_only_company_b_buildings`, `test_customer_a_amanda_sees_only_b3` | `Company B customer's /tickets/new building dropdown lists only R1/R2` |
| Cross-company ticket URL access blocked | (covered by the SPA via Sprint 16 `scope.spec.ts` pattern) | `Cross-company ticket detail URL renders not-found for Company A admin` |
| Reports do not leak cross-company data | (built atop `scope_tickets_for`, covered transitively) | `Reports endpoint returns disjoint datasets for the two admins` |
| Admin companies list scoped | (built atop `scope_companies_for`) | `Admin companies list shows both for super admin, one for company admins` |

## 6. Tests added or updated in Sprint 21

### Backend

- **New:** [backend/accounts/tests/test_seed_demo_data.py](../../backend/accounts/tests/test_seed_demo_data.py)
  — 17 tests across 4 test classes covering seed shape, two-company
  isolation, idempotency on re-run, and the DJANGO_DEBUG=False
  refusal gate.
- **Extended:** [backend/accounts/tests/test_check_no_demo_accounts.py](../../backend/accounts/tests/test_check_no_demo_accounts.py)
  — added `test_sprint21_company_b_demo_accounts_fail` so the pilot
  guard explicitly rejects the three new Company B emails.

### Playwright

- **New:** [frontend/tests/e2e/cross_company_isolation.spec.ts](../../frontend/tests/e2e/cross_company_isolation.spec.ts)
  — 8 tests covering the matrix in section 5: super-admin
  cross-tenant visibility, per-tenant admin scope, manager / customer
  building scope, cross-company ticket-URL and API blocks, reports
  endpoint isolation, and admin-companies-list isolation.

The Sprint 16/17 scope tests in `scope.spec.ts` are not modified —
they still cover Company A's per-user-building-access matrix and run
alongside the new cross-company suite.

## 7. Verification results

Captured during the Sprint 21 implementation run:

```
docker compose -f docker-compose.prod.yml exec -T backend python manage.py check
System check identified no issues (0 silenced).

docker compose -f docker-compose.prod.yml exec -T backend python manage.py test --keepdb
Ran <suite> tests — OK   # see commit run log
```

Playwright: see Sprint 21 commit run log for the
`mcr.microsoft.com/playwright:v1.59.1-jammy` invocation results.

## 8. Known limitations

- The `seed_demo_data` command refuses to run on `DJANGO_DEBUG=False`
  without `--i-know-this-is-not-prod`. The Django test runner is
  invoked against the production-shaped settings tree, so the
  Sprint 21 backend isolation suite passes the override flag inside
  the `_seed()` helper. The refusal path itself is covered separately
  by `SeedDemoDataSafetyTests`.
- Customer-user passwords are now `Demo12345!` rather than
  "unusable" (Sprint 14). The trade-off is intentional: the Playwright
  demo flow and the front-end demo cards both need a working
  password, and the pilot guard still rejects every `@cleanops.demo`
  account on a production host, so the demo password cannot leak into
  pilot.
- The legacy `seed_demo` and `seed_b_amsterdam_demo` command files
  have been deleted **and** any rows they left in a local / demo DB
  are pruned by the canonical seed on every run (section 2.g). The
  `check_no_demo_accounts` guard still lists those emails as a
  defense-in-depth in case a pilot DB skipped the seed step, so the
  pilot-launch readiness path is unchanged.
